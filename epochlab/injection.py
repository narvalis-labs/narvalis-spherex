"""Injection-recovery on REAL cutouts: add a synthetic moving point source of known motion and S/N,
then measure it with the exact production code path. Results are always labelled INJECTED.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .astrometry import AstrometricReference, predict_position, fit_centroid, fit_motion
from .calibration import apply_offset
from .config import Settings, settings as default_settings
from .spherex_fits import open_frame


def _clean_site(d, settings, radii=None, n_angles=16):
    """Pick the injection offset whose neighbourhood is emptiest in the real images (median over a few
    exposures of the brightest pixel within 18\" in noise units), so the injected source is not blended."""
    ra0, dec0 = d["target"]["query_position_deg"]
    if radii is None:
        rmax = d["archive"]["cutout_size_arcsec"] / 2 - 30
        radii = np.arange(25.0, max(rmax, 30.0), 12.0)
    frames = [f for f in d["frames"] if f.get("status") == "ok"][:6]
    best, best_score = (30.0, -24.0), np.inf
    opened = [open_frame(f["download"]["path"]) for f in frames]
    for r in radii:
        for k in range(n_angles):
            a = 2 * np.pi * k / n_angles
            dx, dy = r * np.cos(a), r * np.sin(a)
            ra = ra0 + dx / 3600 / np.cos(np.radians(dec0))
            dec = dec0 + dy / 3600
            scores = []
            for fr in opened:
                x, y = (int(round(float(v))) for v in fr.wcs.world_to_pixel_values(ra, dec))
                ny, nx = fr.image.shape
                m = settings.stamp_half_px + 1
                if not (m <= x < nx - m and m <= y < ny - m):
                    scores.append(np.inf)
                    continue
                st = fr.image[y - 3:y + 4, x - 3:x + 4]
                bg = np.nanmedian(fr.image)
                noise = np.sqrt(np.nanmedian(fr.variance)) if fr.variance is not None else np.nanstd(fr.image)
                scores.append(float(np.nanmax(st - bg) / noise))
            sc = float(np.median(scores)) if scores else np.inf
            if sc < best_score:
                best, best_score = (float(dx), float(dy)), sc
    return best, best_score


def inject_recover(dossier_path: Path, pmra: float, pmdec: float, snr: float,
                   offset_arcsec=None, sigma_px: float = 1.0, seed: int = 1,
                   settings: Settings = default_settings) -> dict:
    d = json.loads(Path(dossier_path).read_text(encoding="utf-8"))
    ra0, dec0 = d["target"]["query_position_deg"]
    site_score = None
    if offset_arcsec is None:
        offset_arcsec, site_score = _clean_site(d, settings)
    dec_off = dec0 + offset_arcsec[1] / 3600
    ra_off = ra0 + offset_arcsec[0] / 3600 / np.cos(np.radians(dec0))
    truth = AstrometricReference(ra_off, dec_off, 2026.0, pmra, pmdec, None, None, source="INJECTED")
    rng = np.random.default_rng(seed)
    cal = d["results"].get("calibration", {})
    floor = cal.get("astrometric_floor_arcsec", 0.0) if cal.get("enabled") else 0.0
    m = settings.stamp_half_px + 1
    rows, n_tried = [], 0
    fit_snr, lost = [], {}   # diagnostics: fitted amplitude S/N of every attempt, and why epochs were lost
    for f in d["frames"]:
        if f.get("status") != "ok":
            continue
        ac = f.get("astrometric_calibration", {})
        if cal.get("enabled") and not ac.get("ok"):
            continue
        off = ac.get("offset_arcsec", [0.0, 0.0]) if ac.get("ok") else [0.0, 0.0]
        offe = ac.get("offset_err_arcsec", [0.0, 0.0]) if ac.get("ok") else [0.0, 0.0]
        fr = open_frame(f["download"]["path"])
        bad, _ = fr.bad_pixel_mask(settings.reject_flag_substrings)
        pra, pdec = predict_position(truth, f["time_mjd"], False)
        # place it where a real star would land: shifted by this exposure's measured astrometric offset
        pra, pdec = apply_offset(pra, pdec, -off[0], -off[1])
        x, y = (float(v) for v in fr.wcs.world_to_pixel_values(pra, pdec))
        ny, nx = fr.image.shape
        if not (m <= x < nx - m and m <= y < ny - m):
            continue
        n_tried += 1
        yy, xx = np.mgrid[0:ny, 0:nx]
        if fr.variance is not None:
            noise = float(np.sqrt(np.nanmedian(fr.variance[int(y) - 3:int(y) + 4, int(x) - 3:int(x) + 4])))
        else:
            noise = float(np.nanstd(fr.image))
        # Peak amplitude such that the Gaussian-fit amplitude S/N ~ snr (approximate, documented)
        amp = snr * noise / np.sqrt(np.pi * sigma_px ** 2) * 1.0
        img = fr.image + amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma_px ** 2))
        # jitter the starting guess so the fit is not handed the truth
        gx, gy = x + rng.normal(0, 0.3), y + rng.normal(0, 0.3)
        cen = fit_centroid(img - (fr.zodi if fr.zodi is not None else 0), fr.variance, bad, fr.wcs, gx, gy,
                           half=settings.stamp_half_px, min_snr=settings.min_snr_centroid,
                           floor_arcsec=settings.astrometric_floor_arcsec)
        fit_snr.append(float(cen.snr or 0.0))
        if not cen.ok:
            key = "S/N below threshold" if cen.reason.startswith("S/N") else cen.reason.split(" (")[0]
            lost[key] = lost.get(key, 0) + 1
        if cen.ok:
            cra, cdec = apply_offset(cen.ra_deg, cen.dec_deg, off[0], off[1])   # same correction as the target
            rows.append((f["time_mjd"], cra, cdec, float(np.sqrt(cen.sigma_ra_arcsec ** 2 + offe[0] ** 2 + floor ** 2)),
                         float(np.sqrt(cen.sigma_dec_arcsec ** 2 + offe[1] ** 2 + floor ** 2))))
    out = {"data_kind": "INJECTED synthetic source added to REAL SPHEREx cutouts",
           "injected": {"pmra_masyr": pmra, "pmdec_masyr": pmdec, "target_snr": snr, "sigma_px": sigma_px,
                        "offset_arcsec": list(offset_arcsec), "site_peak_noise_units": site_score, "seed": seed},
           "epochs_tried": n_tried, "epochs_recovered": len(rows),
           "completeness": len(rows) / n_tried if n_tried else None,
           # The injected S/N is the matched-filter (optimal) S/N of the Gaussian. The detection test uses the
           # amplitude S/N of a 5-parameter fit (amplitude, x, y, width, background), which is lower; the median
           # ratio below measures that conversion on these exact frames.
           "fit_snr_median": float(np.median(fit_snr)) if fit_snr else None,
           "fit_snr_over_injected": float(np.median(fit_snr) / snr) if fit_snr else None,
           "lost_epochs_by_reason": lost}
    if len(rows) >= 3:
        a = np.array(rows)
        m = fit_motion(a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], truth)
        out["motion"] = m.to_dict()
        out["recovered_within_3sigma"] = bool(m.ok and abs(m.z_pmra) < 3 and abs(m.z_pmdec) < 3)
    return out
