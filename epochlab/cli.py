"""Command line interface.

python -m epochlab.cli analyze --name "Barnard's Star"
python -m epochlab.cli analyze --ra 269.45 --dec 4.69
python -m epochlab.cli reproduce data/jobs/<id>/dossier.json
python -m epochlab.cli inject data/jobs/<id>/dossier.json --pmra 3000 --pmdec -2000 --snr 15
python -m epochlab.cli export-static --jobs <id> <id> --out site/
python -m epochlab.cli serve --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .config import settings


def _print(o):
    print(json.dumps(o, indent=1, default=str))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="epochlab")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze")
    a.add_argument("--name")
    a.add_argument("--ra", type=float)
    a.add_argument("--dec", type=float)
    a.add_argument("--max-frames", type=int)
    a.add_argument("--size", type=float, help="cutout size, arcsec")
    a.add_argument("--no-gaia", action="store_true")
    a.add_argument("--controls", type=int, default=2)

    r = sub.add_parser("reproduce")
    r.add_argument("dossier")

    i = sub.add_parser("inject")
    i.add_argument("dossier")
    i.add_argument("--pmra", type=float, required=True)
    i.add_argument("--pmdec", type=float, required=True)
    i.add_argument("--snr", type=float, default=15)
    i.add_argument("--seed", type=int, default=1)

    e = sub.add_parser("export-static")
    e.add_argument("--jobs", nargs="+", required=True)
    e.add_argument("--out", default="site")

    sub.add_parser("diagnose", help="check connectivity to every external service")

    cc = sub.add_parser("cache", help="show or prune the local FITS cache")
    cc.add_argument("--prune-days", type=float, help="delete cached files not used for this many days")

    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    args = ap.parse_args(argv)

    if args.cmd == "analyze":
        from .pipeline import AnalysisRequest, analyze
        req = AnalysisRequest(target_name=args.name, ra_deg=args.ra, dec_deg=args.dec, use_gaia=not args.no_gaia,
                              n_controls=args.controls, cutout_size_arcsec=args.size, max_frames=args.max_frames)
        jd = analyze(req, settings, progress=lambda f, m: print(f"[{f * 100:5.1f}%] {m}", file=sys.stderr))
        d = json.loads((jd / "dossier.json").read_text(encoding="utf-8"))
        _print({"job_dir": str(jd), "verdicts": d["verdicts"], "motion": d["results"]["motion"]})
    elif args.cmd == "reproduce":
        from .pipeline import reproduce
        out = reproduce(Path(args.dossier), settings)
        _print(out)
        sys.exit(0 if out["identical_results"] else 2)
    elif args.cmd == "inject":
        from .injection import inject_recover
        _print(inject_recover(Path(args.dossier), args.pmra, args.pmdec, args.snr, seed=args.seed, settings=settings))
    elif args.cmd == "export-static":
        export_static(args.jobs, Path(args.out))
    elif args.cmd == "cache":
        cache_cmd(args.prune_days)
    elif args.cmd == "diagnose":
        diagnose()
    elif args.cmd == "serve":
        import uvicorn
        uvicorn.run("epochlab.api:app", host=args.host, port=args.port)


def cache_cmd(prune_days):
    """Cached archive files (data/cache). Dossiers keep URL + SHA-256, so pruned files can be re-downloaded
    and verified by `reproduce`; nothing in a dossier depends on the cache existing."""
    import time as _t
    d = settings.data_dir / "cache"
    files = list(d.glob("*.fits")) if d.exists() else []
    total = sum(f.stat().st_size for f in files)
    print(f"{len(files)} cached FITS files, {total / 1e6:.1f} MB in {d}")
    if prune_days:
        cutoff = _t.time() - prune_days * 86400
        n = 0
        for f in files:
            if f.stat().st_atime < cutoff and f.stat().st_mtime < cutoff:
                f.unlink()
                f.with_suffix(".json").unlink(missing_ok=True)
                n += 1
        print(f"pruned {n} files older than {prune_days} days")


def diagnose():
    """Probe each external dependency and print OK/FAIL with the exact error."""
    import time as _t

    def check(label, fn):
        t0 = _t.time()
        try:
            info = fn()
            print(f"OK    {label:28s} {(_t.time() - t0):5.1f}s  {info}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {label:28s} {(_t.time() - t0):5.1f}s  {type(exc).__name__}: {' '.join(str(exc).split())[:220]}")

    from .references import resolve_simbad, resolve_sesame, gaia_cone
    from .archive import query_observations
    check("SIMBAD (astroquery TAP)", lambda: resolve_simbad("Barnard's Star").source)
    check("Sesame (CDS / CfA mirror)", lambda: resolve_sesame("Barnard's Star").source)
    check("Gaia DR3 TAP (ESA)", lambda: f"{len(gaia_cone(269.4486, 4.7398, 10)[0])} rows")
    from .archive import discover_collections
    check("IRSA SPHEREx collections", lambda: ", ".join(discover_collections()))
    qlog: list[str] = []
    check("IRSA SIA2 at Barnard's Star", lambda: f"{len(query_observations(269.4486, 4.7398, settings, None, log=qlog))} images")
    for line in qlog:
        print("      ", line)
    import httpx
    from .api import HIPS_MIRRORS, UA
    for base in HIPS_MIRRORS["2MASS/Color"]:
        check(f"Sky context {base.split('/')[2]}"[:28], lambda b=base: f"HTTP {httpx.get(b + '/properties', timeout=15, headers=UA, follow_redirects=True).status_code}  {b}/properties")


def export_static(job_ids: list[str], out: Path):
    """Self-contained static site (e.g. GitHub Pages) with precomputed REAL-data jobs, same URL layout."""
    web = Path(__file__).resolve().parent.parent / "web"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(web, out)
    index = []
    for j in job_ids:
        src = settings.data_dir / "jobs" / j
        if not (src / "dossier.json").exists():
            raise SystemExit(f"job {j} has no dossier")
        dst = out / "api" / "jobs" / j
        (dst / "frames").mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / "dossier.json", dst / "dossier.json")
        shutil.copy2(src / "status.json", dst / "status.json") if (src / "status.json").exists() else None
        for p in (src / "frames").glob("*.png"):
            shutil.copy2(p, dst / "frames" / p.name)
        d = json.loads((src / "dossier.json").read_text(encoding="utf-8"))
        index.append({"job_id": j, "state": "done", "request": d["request"], "updated_utc": d["created_utc"]})
    (out / "api" / "jobs" / "index.json").write_text(json.dumps({"jobs": index}, indent=1))
    (out / "api" / "health.json").write_text(json.dumps({"ok": True, "mode": "static"}))
    (out / ".nojekyll").write_text("")
    print(f"static site written to {out} ({len(index)} jobs)")


if __name__ == "__main__":
    main()
