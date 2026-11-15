#!/usr/bin/env python3
"""REAL-DATA validation run. Execute on a machine with internet access to IRSA, Gaia and SIMBAD.

    python scripts/selftest_real.py --list-collections      # discover SPHEREx collection names (QR/DR1)
    python scripts/selftest_real.py --probe                 # inspect one real cutout: HDUs, keywords, wavelength
    python scripts/selftest_real.py --probe --full          # + compare cutout vs full-image spectral WCS
    python scripts/selftest_real.py --run                   # 5 challenge targets + controls + injection + reproduce

Writes validation/results.json and validation/REPORT.md. Every number in the report comes from this run;
tests that could not be executed are reported as PENDING / ERROR with the exception text.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from epochlab.config import settings  # noqa: E402

TARGETS = [
    # name for SIMBAD, what the challenge test is about, which automatic check is the primary criterion
    ("Barnard's Star", "high proper motion", "proper_motion_vs_catalogue"),
    ("eps Ind B", "nearby brown dwarf, proper motion", "proper_motion_vs_catalogue"),
    ("WISE J085510.83-071442.5", "coldest known brown dwarf; if detected, expected only at >=3.8 um (hypothesis, docs/REFERENCES.md)", "detection"),
    ("RW Aur", "young variable star", "variability_matched_wavelength"),
    ("R Dra", "Mira variable", "variability_matched_wavelength"),
]
OUT = Path(__file__).resolve().parent.parent / "validation"


def list_collections():
    from astroquery.ipac.irsa import Irsa
    t = Irsa.list_collections(filter="spherex")
    print(t)


def probe(full: bool):
    import numpy as np
    from astropy.io import fits
    from epochlab.archive import query_observations, cutout_url, fetch
    from epochlab.spherex_fits import open_frame
    ra, dec = 269.4521, 4.6934  # near Barnard's Star (J2000 position); any covered point works for a probe
    obs = query_observations(ra, dec, settings)
    print(f"SIA2 returned {len(obs)} images in {settings.collections}")
    if not obs:
        return
    o = obs[len(obs) // 2]
    print(json.dumps(o.to_dict(), indent=1))
    d = fetch(cutout_url(o, ra, dec, 150, settings), settings)
    print("cutout:", d.to_dict())
    with fits.open(d.path) as h:
        h.info()
        hdr = h[1].header if len(h) > 1 else h[0].header
        keys = [k for k in hdr.keys() if k.startswith(("MJD", "DATE", "DET", "CTYPE", "PS", "PV", "CRPIX", "BUNIT"))]
        for k in keys:
            print(f"  {k:10s} = {hdr[k]!r}")
        if "FLAGS" in h:
            print("  FLAGS bit definitions:", {k: h["FLAGS"].header[k] for k in h["FLAGS"].header if k.startswith("MP_")})
    fr = open_frame(d.path)
    x, y = fr.wcs.world_to_pixel_values(ra, dec)
    lam = fr.wavelength_at(float(x), float(y))
    print("time:", fr.time_mjd, fr.time_source, "| detector:", fr.detector, "| wavelength:", lam, "| warnings:", fr.warnings)
    if full:
        d2 = fetch(o.access_url, settings)
        fr2 = open_frame(d2.path)
        x2, y2 = fr2.wcs.world_to_pixel_values(ra, dec)
        lam2 = fr2.wavelength_at(float(x2), float(y2))
        print("full image wavelength at same sky position:", lam2)
        if lam[0] and lam2[0]:
            print(f"CUTOUT SPECTRAL WCS CHECK: |dlambda| = {abs(lam[0] - lam2[0]):.5f} um "
                  f"-> {'PASS' if abs(lam[0] - lam2[0]) < 0.002 else 'FAIL'}")


def run():
    from epochlab.pipeline import AnalysisRequest, analyze, reproduce
    from epochlab.injection import inject_recover
    OUT.mkdir(exist_ok=True)
    res = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "collections": list(settings.collections), "targets": [], "injection": [], "reproduce": None}
    first_ok = None
    for name, why, primary in TARGETS:
        print(f"\n=== {name} ({why})", flush=True)
        entry = {"name": name, "purpose": why, "primary_check": primary}
        try:
            jd = analyze(AnalysisRequest(target_name=name, n_controls=2), settings,
                         progress=lambda f, m: print(f"  [{f * 100:5.1f}%] {m}", flush=True))
            d = json.loads((jd / "dossier.json").read_text(encoding="utf-8"))
            (jd / "status.json").write_text(json.dumps({"state": "done", "progress": 1, "message": "Done",
                                                        "request": d["request"]}))
            entry.update(job_id=d["job_id"], n_found=d["archive"]["n_found"], n_selected=d["archive"]["n_selected"],
                         reference=d["target"]["reference"], verdicts=d["verdicts"], motion=d["results"]["motion"],
                         variability_combined={k: d["results"]["variability"][k] for k in ("combined_chi2", "combined_dof", "combined_p_value")},
                         controls={k: d["results"]["controls"].get(k) for k in ("n_stars", "frac_abs_z_gt_3", "z_std", "z_median_abs")},
                         calibration=d["results"].get("calibration"),
                         frame_status={s: sum(1 for f in d["frames"] if f.get("status") == s) for s in {f.get("status") for f in d["frames"]}},
                         centroid_failures=_reasons(d),
                         detected_wavelengths_um=sorted(f["wavelength_um"] for f in d["frames"]
                                                        if f.get("status") == "ok" and f["centroid"]["ok"]
                                                        and f.get("wavelength_um") is not None))
            if first_ok is None and any(v["check"] == "detection" and v["result"] == "PASS" for v in d["verdicts"]):
                first_ok = jd
        except Exception as exc:  # noqa: BLE001
            entry.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc()[-2000:])
            print("  ERROR:", entry["error"])
        res["targets"].append(entry)
        _save(res)

    if first_ok is not None:
        res["injection"] = _injections(first_ok)
        try:
            res["reproduce"] = reproduce(first_ok / "dossier.json", settings)
        except Exception as exc:  # noqa: BLE001
            res["reproduce"] = {"error": str(exc)}
    res["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save(res)
    print(f"\nWrote {OUT / 'results.json'} and {OUT / 'REPORT.md'}")


SNRS = (5, 8, 12, 16, 20, 30, 40)


def _injections(host: Path) -> list:
    from epochlab.injection import inject_recover
    out = []
    for snr in SNRS:
        try:
            r = inject_recover(host / "dossier.json", pmra=2000.0, pmdec=-1500.0, snr=snr, settings=settings)
            r["host_job"] = host.name
            out.append(r)
            print(f"  injection S/N {snr}: recovered {r['epochs_recovered']}/{r['epochs_tried']}, "
                  f"fitted S/N median {r['fit_snr_median']:.1f}, lost {r['lost_epochs_by_reason']}, "
                  f"within3sigma={r.get('recovered_within_3sigma')}", flush=True)
        except Exception as exc:  # noqa: BLE001
            out.append({"target_snr": snr, "error": str(exc)})
    return out


def injection_only():
    """Re-run only injection-recovery on the host field recorded by the last --run (keeps everything else)."""
    res = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
    host = next((r.get("host_job") for r in res.get("injection", []) if r.get("host_job")), None)
    if host is None:
        print("no host job in results.json: run --run first"); return
    print(f"=== injection-recovery on host job {host}", flush=True)
    res["injection"] = _injections(Path(settings.data_dir) / "jobs" / host)
    res["injection_rerun_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save(res)
    print(f"\nWrote {OUT / 'results.json'} and {OUT / 'REPORT.md'}")


def _reasons(d):
    from collections import Counter
    c = Counter(f["centroid"]["reason"].split(" ")[0] for f in d["frames"]
                if f.get("status") == "ok" and not f["centroid"]["ok"])
    return dict(c)


def _save(res):
    # explicit UTF-8: on Windows the default text encoding is cp1252, which cannot write "→", "σ", "µ"…
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    (OUT / "REPORT.md").write_text(report(res), encoding="utf-8")


def report(res) -> str:
    L = ["# EpochLab — real-data validation report", "",
         f"Run: {res['started_utc']} → {res.get('finished_utc', 'in progress')}  ",
         f"Collections: {', '.join(res['collections'])}  ",
         "All numbers below were produced by `scripts/selftest_real.py` on real IRSA SPHEREx data.", "",
         "## Challenge targets", "",
         "| Target | Purpose | Images found/used | Primary check | Result | Detail |", "|---|---|---|---|---|---|"]
    for t in res["targets"]:
        if "error" in t:
            L.append(f"| {t['name']} | {t['purpose']} | — | {t['primary_check']} | ERROR | {t['error'][:120].replace(chr(10), ' ').replace('|', '/')} |")
            continue
        v = {x["check"]: x for x in t["verdicts"]}
        p = v.get(t["primary_check"], {"result": "INCONCLUSIVE", "detail": "check not evaluated"})
        L.append(f"| {t['name']} | {t['purpose']} | {t['n_found']}/{t['n_selected']} | {t['primary_check']} | "
                 f"**{p['result']}** | {p['detail']} |")
    L += ["", "## All automatic checks per target", ""]
    for t in res["targets"]:
        L.append(f"### {t['name']}")
        if "error" in t:
            L += ["", f"ERROR: `{t['error']}`", ""]
            continue
        ref = t.get("reference") or {}
        L.append(f"Reference: {ref.get('source', 'none')} · job `{t['job_id']}` · frame status {t['frame_status']} · "
                 f"centroid rejections {t['centroid_failures']}")
        cal = t.get("calibration") or {}
        if cal.get("enabled"):
            L.append(f"Calibration: {cal.get('frames_calibrated')}/{cal.get('frames_usable')} exposures, "
                     f"{cal.get('n_reference_stars')} Gaia field stars (median {cal.get('median_stars_per_frame')} per exposure), "
                     f"astrometric floor {cal.get('astrometric_floor_arcsec', 0):.3f}″, photometric floor {cal.get('photometric_floor_frac')}")
        ctl = t.get("controls") or {}
        if ctl.get("n_stars"):
            L.append(f"Field-star controls: {ctl['n_stars']} stars, |z|>3 fraction {ctl['frac_abs_z_gt_3']:.2f}, z std {ctl['z_std']:.2f}")
        if t.get("detected_wavelengths_um"):
            w = t["detected_wavelengths_um"]
            L.append(f"Detections at λ = {min(w):.2f}–{max(w):.2f} µm ({len(w)} epochs)")
        L.append("")
        for x in t["verdicts"]:
            L.append(f"- **{x['check']}**: {x['result']} — {x['detail']} _(rule: {x['rule']})_")
        m = t["motion"]
        if m.get("ok"):
            L.append(f"- measured µα* = {m['pmra_masyr']:.0f} ± {m['pmra_err']:.0f}, µδ = {m['pmdec_masyr']:.0f} ± "
                     f"{m['pmdec_err']:.0f} mas/yr; catalogue {ref.get('pmra_masyr', float('nan')):.1f}, "
                     f"{ref.get('pmdec_masyr', float('nan')):.1f}; reduced χ² (linear) = {m['reduced_chi2_linear']:.2f}; "
                     f"calibrated: {m.get('calibrated')}")
        L.append("")
    L += ["## Injection–recovery (synthetic source added to real cutouts)", ""]
    if res["injection"]:
        L += ["Injected S/N = matched-filter (optimal) S/N of the injected Gaussian. Detection requires amplitude S/N >= "
              f"{settings.min_snr_centroid:g} in a 5-parameter Gaussian fit, which is lower: the column *fitted S/N* gives the "
              "median measured on these exact frames.", "",
              "| Injected S/N | Fitted S/N (median) | Epochs recovered | Completeness | Epochs lost, by reason | PM recovered within 3σ |",
              "|---|---|---|---|---|---|"]
        for r in res["injection"]:
            if "error" in r:
                L.append(f"| {r['target_snr']} | | ERROR | | {r['error'][:80]} | |")
            else:
                c = r["completeness"]
                fs = r.get("fit_snr_median")
                lost = ", ".join(f"{k}: {v}" for k, v in sorted((r.get("lost_epochs_by_reason") or {}).items(), key=lambda kv: -kv[1])) or "—"
                L.append(f"| {r['injected']['target_snr']} | {'—' if fs is None else f'{fs:.1f}'} | {r['epochs_recovered']}/{r['epochs_tried']} | "
                         f"{'—' if c is None else f'{c:.2f}'} | {lost} | {r.get('recovered_within_3sigma', 'n/a (<3 epochs)')} |")
    else:
        L.append("PENDING — no target was detected, so there was no host field.")
    L += ["", "## Reproducibility", ""]
    rp = res.get("reproduce")
    if rp is None:
        L.append("PENDING")
    elif "error" in rp:
        L.append(f"ERROR: {rp['error']}")
    else:
        L.append(f"Re-run of job `{rp['old_job']}` as `{rp['new_job']}`: {rp['files_compared']} files compared, "
                 f"{len(rp['hash_mismatches'])} hash mismatches, identical results: **{rp['identical_results']}**")
    L += ["", "## Not covered by this run", "",
          "- ePSF fitting (Gaussian core approximation used).",
          "- Independent repetition on a second machine (run `cli reproduce` elsewhere to close Test 7).", ""]
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-collections", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--injection", action="store_true", help="re-run only injection-recovery on the last host field")
    a = ap.parse_args()
    if a.list_collections:
        list_collections()
    if a.probe:
        probe(a.full)
    if a.run:
        run()
    if a.injection:
        injection_only()
    if not (a.list_collections or a.probe or a.run or a.injection):
        ap.print_help()
