"""Re-run a saved analysis with every SPHEREx exposure of the same target already in the local cache.

Why: the archive search (IRSA SIA) can be unavailable while the image files themselves are still served or cached.
Earlier analyses of the same target each kept their own selection of exposures (max 80); their union is often
much larger. This script pins that union (archive discovery is skipped, exactly like `reproduce`) and reuses the
validated catalogue reference of the original dossier, so the only thing that changes is the number of epochs.

Usage:
    python scripts/reanalyse_cached.py <job_id> [--only-original] [--new-job ID] [--offline]

--only-original  pin exactly the original 80 exposures (environment check: must reproduce the dossier)
--offline        never touch the network (all cutouts and Gaia answers must be cached)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from epochlab import archive, pipeline  # noqa: E402
from epochlab.astrometry import AstrometricReference  # noqa: E402
from epochlab.config import settings  # noqa: E402


def _dossiers():
    for sub in ("jobs", "trash"):
        for p in sorted((settings.data_dir / sub).glob("*/dossier.json")):
            try:
                yield p, json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue


def _cache_path(url: str) -> Path:
    import hashlib
    return settings.data_dir / "cache" / f"{hashlib.sha256(url.encode()).hexdigest()[:32]}.fits"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("--only-original", action="store_true")
    ap.add_argument("--new-job", default=None)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--gaia-cones", action="store_true", help="print the Gaia cone searches this run needs")
    a = ap.parse_args()

    src = settings.data_dir / "jobs" / a.job / "dossier.json"
    d = json.loads(src.read_text(encoding="utf-8"))
    req0 = d["request"]
    ref = AstrometricReference(**d["target"]["reference"]) if d["target"].get("reference") else None
    ra_q, dec_q = d["target"]["query_position_deg"]
    size = d["archive"]["cutout_size_arcsec"]

    # ---- collect exposures: original selection first, then every other cached exposure of the same field
    orig = [f["observation"] for f in d["frames"]]
    seen = {o["obs_id"] for o in orig}
    pool = list(orig)
    alias: dict[str, Path] = {}   # exact cutout URL -> cached cutout of the same exposure around a nearby centre
    if not a.only_original:
        for p, o_d in _dossiers():
            if p == src:
                continue
            q = o_d.get("target", {}).get("query_position_deg")
            if not q or abs(q[0] - ra_q) * max(0.05, abs(__import__("math").cos(__import__("math").radians(dec_q)))) > 0.02 \
                    or abs(q[1] - dec_q) > 0.02:
                continue
            for f in o_d.get("frames", []):
                o = f.get("observation")
                if not o or o["obs_id"] in seen:
                    continue
                obs = archive.Observation(**{k: v for k, v in o.items() if k in archive.Observation.__dataclass_fields__})
                exact = archive.cutout_url(obs, ra_q, dec_q, size, settings)
                if not _cache_path(exact).exists():
                    # same exposure, cut out around another centre: usable if our target sits well inside it
                    url = (f.get("download") or {}).get("url") or ""
                    import re
                    mm = re.search(r"center=([-\d.]+),([-\d.]+)deg", url)
                    if not (mm and _cache_path(url).exists()):
                        continue
                    from epochlab.astrometry import tangent_offsets
                    dx, dy = tangent_offsets(float(mm.group(1)), float(mm.group(2)), ra_q, dec_q)
                    if max(abs(dx), abs(dy)) > 0.25 * size:
                        continue
                    alias[exact] = _cache_path(url)
                seen.add(o["obs_id"])
                pool.append(o)
    pool.sort(key=lambda o: (o.get("t_min_mjd") or 0.0, o["obs_id"]))
    if a.gaia_cones:   # same arguments as pipeline.analyze -> calibration.field_references -> gaia_cone
        print(json.dumps({"ra": ra_q, "dec": dec_q, "radius_arcsec": size / 2 * 0.95, "top": 600}))
        return 0
    print(f"{d['target']['name']}: {len(orig)} original exposures, {len(pool)} pinned "
          f"(archive listed {d['archive'].get('n_found')})", flush=True)

    # ---- the cache metadata stores the absolute path of the machine that downloaded it; remap to this machine
    real_fetch = archive.fetch

    def fetch(url, st):
        cp = alias.get(url, _cache_path(url))
        if cp.exists() and cp.with_suffix(".json").exists():
            m = json.loads(cp.with_suffix(".json").read_text(encoding="utf-8"))
            m["path"] = str(cp)   # m["url"] stays the URL actually downloaded (may be a nearby centre)
            return archive.Download(**{**m, "cached": True})
        if a.offline:
            raise RuntimeError(f"not cached (offline): {url}")
        return real_fetch(url, st)
    archive.fetch = fetch

    # ---- reuse the validated reference (the name resolver and Gaia match are not repeated)
    name = d["target"]["name"]
    pipeline.resolve_reference = lambda req, log: (log.append(f"Reference reused from dossier {a.job}: "
                                                               f"{ref.source if ref else 'none'}") or (ref, name))

    keep = set(pipeline.AnalysisRequest.__dataclass_fields__)
    req = pipeline.AnalysisRequest(**{k: v for k, v in req0.items() if k in keep})
    req.pinned_observations = pool
    req.max_frames = len(pool)
    out = pipeline.analyze(req, settings, job_id=a.new_job,
                           progress=lambda f, m: print(f"  {f * 100:5.1f}%  {m}", flush=True) if "Measuring" not in m
                           or m.endswith(("/1", "0/" + str(len(pool)))) else None)
    out = Path(out) / "dossier.json"
    nd = json.loads(out.read_text(encoding="utf-8"))
    nd["archive"]["n_found"] = d["archive"].get("n_found")   # what the archive listed, not what was pinned
    nd["log"].append(f"Reanalysis of {a.job} with {len(pool)} cached exposures "
                     f"({'original selection only' if a.only_original else 'union of all cached analyses'})")
    nd["reanalysis_of"] = a.job
    out.write_text(json.dumps(nd, indent=1, default=pipeline._json_default), encoding="utf-8")
    m = nd["results"]["motion"]
    print(json.dumps({k: m.get(k) for k in ("n_epochs", "pmra_masyr", "pmdec_masyr", "pmra_err", "pmdec_err",
                                            "reduced_chi2_linear", "time_span_yr")}, indent=1))
    print("dossier:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
