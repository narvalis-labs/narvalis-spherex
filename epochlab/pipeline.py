"""End-to-end analysis of one sky position: discovery -> cutouts -> per-epoch measurement -> fits -> dossier."""
from __future__ import annotations

import json
import platform
import time
import traceback
import uuid
from dataclasses import dataclass, asdict, field, replace
from pathlib import Path
from typing import Callable

import numpy as np

from . import __version__
from .archive import Observation, query_observations, select_spread, cutout_url, fetch_many
from .astrometry import AstrometricReference, predict_position, fit_centroid, fit_motion, fit_parallax, pixel_scale_arcsec
from .config import Settings, settings as default_settings
from .photometry import forced_aperture, variability_by_bin, wavelength_bins, psf_wing_flux
from .calibration import (field_references, measure_field, systematic_floor, calibrate, apply_offset,
                          field_controls, photometric_floor)
from .render import common_wcs, reproject_to, save_png, to_display_frac, display_limits
from .spherex_fits import open_frame

SCHEMA = "epochlab-dossier/1"
DISPLAY_PIX_ARCSEC = 3.075  # 2x oversampled display grid (display only)


@dataclass
class AnalysisRequest:
    target_name: str | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None
    # Optional manual reference (overrides catalogues); epoch in Julian years
    ref_pmra: float | None = None
    ref_pmdec: float | None = None
    ref_parallax: float | None = None
    ref_epoch: float | None = None
    use_gaia: bool = True
    n_controls: int = 2
    cutout_size_arcsec: float | None = None
    max_frames: int | None = None
    collections: list[str] | None = None
    # When set, archive discovery is skipped and exactly these observations are used (reproduction).
    pinned_observations: list[dict] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


Progress = Callable[[float, str], None]


def _versions() -> dict:
    import astropy, numpy, scipy, pyvo, reproject
    v = {"epochlab": __version__, "python": platform.python_version(), "astropy": astropy.__version__,
         "numpy": numpy.__version__, "scipy": scipy.__version__, "pyvo": pyvo.__version__,
         "reproject": reproject.__version__}
    try:
        import astroquery
        v["astroquery"] = astroquery.__version__
    except Exception:  # noqa: BLE001
        pass
    return v


def resolve_reference(req: AnalysisRequest, log: list[str]) -> tuple[AstrometricReference | None, str | None]:
    """Return (reference, display_name). Manual values > Gaia DR3 > SIMBAD > none."""
    name = req.target_name
    if req.ref_pmra is not None and req.ref_pmdec is not None:
        if req.ra_deg is None or req.dec_deg is None:
            raise ValueError("manual reference requires ra_deg/dec_deg")
        ref = AstrometricReference(req.ra_deg, req.dec_deg, req.ref_epoch or 2000.0, req.ref_pmra, req.ref_pmdec,
                                   req.ref_parallax, None, source="manual (user-supplied)")
        log.append("Reference: manual values supplied by user")
        return ref, name
    if name:
        from .references import resolve_name, match_gaia
        seed, rlog = resolve_name(name)
        log.extend(rlog)
        log.append(f"Resolved '{name}' with {seed.source}")
        if not seed.pm_known:
            log.append("WARNING: the name resolver returned no proper motion; no catalogue track can be predicted. "
                       "Using the resolver position as a static seed and fitting motion freely.")
        if req.use_gaia:
            try:
                g, note = match_gaia(seed)
                if g is not None:
                    log.append(f"Reference: {g.source} ({note})")
                    return g, name
                log.append(f"Gaia: {note}; using resolver astrometry")
            except Exception as exc:  # noqa: BLE001
                log.append(f"Gaia query failed ({exc}); using resolver astrometry")
        if not seed.pm_known:
            req.ra_deg, req.dec_deg = seed.ra_deg, seed.dec_deg
            return None, name
        return seed, name
    if req.ra_deg is None or req.dec_deg is None:
        raise ValueError("provide target_name or ra_deg/dec_deg")
    log.append("No catalogue reference: position treated as static seed, motion fitted freely")
    return None, None


def analyze(req: AnalysisRequest, settings: Settings = default_settings, job_id: str | None = None,
            progress: Progress | None = None) -> Path:
    progress = progress or (lambda f, m: None)
    job_id = job_id or uuid.uuid4().hex[:12]
    jdir = settings.data_dir / "jobs" / job_id
    (jdir / "frames").mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    size = req.cutout_size_arcsec or settings.cutout_size_arcsec
    max_frames = req.max_frames or settings.max_frames
    colls = tuple(req.collections) if req.collections else settings.collections

    progress(0.02, "Resolving target")
    ref, name = resolve_reference(req, log)

    def pred(mjd):
        if ref is None:
            return float(req.ra_deg), float(req.dec_deg)
        return predict_position(ref, mjd, include_parallax=True)

    # Archive discovery at the position predicted for the middle of the SPHEREx era
    from astropy.time import Time
    mjd_seed = Time(2026.0, format="jyear").utc.mjd
    ra_q, dec_q = pred(mjd_seed)
    if req.pinned_observations:
        keep = set(Observation.__dataclass_fields__)
        obs_all = [Observation(**{k: v for k, v in o.items() if k in keep}) for o in req.pinned_observations]
        obs = obs_all
        log.append(f"Pinned observations: {len(obs)} (archive discovery skipped for reproduction)")
    else:
        progress(0.06, "Querying IRSA SIA2")
        qlog: list[str] = []
        obs_all = query_observations(ra_q, dec_q, settings, colls, log=qlog)
        log.extend(qlog)
        log.append(f"SIA2: {len(obs_all)} spectral images contain ({ra_q:.6f}, {dec_q:.6f})")
        if not obs_all:
            joined = " | ".join(qlog)
            if any(t in joined for t in ("HTTP 50", " 502", " 503", " 504", "Proxy Error", "timed out", "Timeout")):
                # the archive failed to answer: say so, instead of implying that the sky has no SPHEREx data here
                raise LookupError(f"IRSA did not answer the image search for ({ra_q:.5f}, {dec_q:.5f}) "
                                  f"(server error, also after retries). Tried: " + joined)
            raise LookupError(f"IRSA returned no SPHEREx images covering ({ra_q:.5f}, {dec_q:.5f}). Tried: "
                              + joined)
        obs = select_spread(obs_all, max_frames)
    urls = [cutout_url(o, ra_q, dec_q, size, settings) for o in obs]
    progress(0.10, f"Downloading {len(urls)} cutouts")
    dls = fetch_many(urls, settings)

    # Known neighbours for deblending: Gaia stars that come within 45" of the target's track during the survey.
    nb_prop, nb_n = None, 0
    if req.use_gaia and settings.deblend_gaia:
        try:
            from .references import gaia_cone
            from .calibration import FieldPropagator
            tab, _ = gaia_cone(ra_q, dec_q, size / 2 * 0.95, top=600)
            own = ref.source.split()[-1] if (ref is not None and str(ref.source).startswith("Gaia DR3")) else None
            reach = 45.0 + (np.hypot(ref.pmra_masyr, ref.pmdec_masyr) / 1000.0 * 1.5 if ref is not None else 0.0)
            nbs = []
            for r in tab:
                if own is not None and str(int(r["source_id"])) == own:
                    continue
                sep = np.hypot((float(r["ra"]) - ra_q) * np.cos(np.radians(dec_q)), float(r["dec"]) - dec_q) * 3600
                if sep > reach + 30.0:
                    continue
                pm_ok = not (np.ma.is_masked(r["pmra"]) or np.ma.is_masked(r["pmdec"]))
                nbs.append(AstrometricReference(
                    float(r["ra"]), float(r["dec"]), 2016.0, float(r["pmra"]) if pm_ok else 0.0,
                    float(r["pmdec"]) if pm_ok else 0.0,
                    (None if np.ma.is_masked(r["parallax"]) else float(r["parallax"])) if pm_ok else None,
                    None, source=f"Gaia DR3 {int(r['source_id'])}"))
            if nbs:
                nb_prop, nb_n = FieldPropagator(nbs), len(nbs)
            log.append(f"Deblending: {nb_n} Gaia neighbours near the target's track are fitted with it (fixed positions)")
        except Exception as exc:  # noqa: BLE001
            log.append(f"Deblending unavailable: {type(exc).__name__}: {exc}")

    disp_wcs, n_disp = common_wcs(ra_q, dec_q, size * 0.9, DISPLAY_PIX_ARCSEC)
    frames: list[dict] = []
    reproj: list[np.ndarray | None] = []
    native: list[tuple] = []  # (frame obj, bad mask) kept for control-star measurements
    for i, (o, d) in enumerate(zip(obs, dls)):
        progress(0.12 + 0.70 * i / max(len(obs), 1), f"Measuring frame {i + 1}/{len(obs)}")
        rec: dict = {"index": i, "observation": o.to_dict(), "warnings": []}
        if isinstance(d, Exception):
            rec.update(status="download_failed", error=str(d))
            frames.append(rec); reproj.append(None); native.append(None)
            continue
        rec["download"] = d.to_dict()
        try:
            fr = open_frame(d.path)
        except Exception as exc:  # noqa: BLE001
            rec.update(status="unreadable", error=f"{type(exc).__name__}: {exc}")
            frames.append(rec); reproj.append(None); native.append(None)
            continue
        rec["warnings"] += fr.warnings
        t = o.t_mid_mjd if o.t_mid_mjd is not None else fr.time_mjd
        rec["time_mjd"] = t
        rec["time_source"] = "SIA t_min/t_max midpoint" if o.t_mid_mjd is not None else fr.time_source
        rec["header_time_mjd"], rec["header_time_source"] = fr.time_mjd, fr.time_source
        if t is None:
            rec.update(status="no_time")
            frames.append(rec); reproj.append(None); native.append(None)
            continue
        if fr.time_mjd is not None and o.t_mid_mjd is not None and abs(fr.time_mjd - o.t_mid_mjd) > 1 / 1440:
            rec["warnings"].append(f"header time differs from SIA midpoint by {abs(fr.time_mjd - o.t_mid_mjd) * 1440:.1f} min")
        rec["detector"] = fr.detector
        pra, pdec = pred(t)
        px, py = (float(v) for v in fr.wcs.world_to_pixel_values(pra, pdec))
        lam, bw, lsrc = fr.wavelength_at(px, py)
        bad, rejected = fr.bad_pixel_mask(settings.reject_flag_substrings)
        rec.update(predicted={"ra_deg": pra, "dec_deg": pdec, "x": px, "y": py},
                   wavelength_um=lam, bandwidth_um=bw, wavelength_source=lsrc,
                   flags_rejected=rejected, pixel_scale_arcsec=pixel_scale_arcsec(fr.wcs))
        h = settings.stamp_half_px
        xi, yi = int(round(px)), int(round(py))
        stamp_bad = bad[max(yi - h, 0):yi + h + 1, max(xi - h, 0):xi + h + 1]
        rec["n_flagged_in_stamp"] = int(stamp_bad.sum())
        nbxy = []
        if nb_prop is not None:
            nra, ndec = nb_prop.at(t)
            nx, ny = fr.wcs.world_to_pixel_values(nra, ndec)
            for a_, b_ in zip(np.atleast_1d(nx), np.atleast_1d(ny)):
                dpx = float(np.hypot(a_ - px, b_ - py)) * pixel_scale_arcsec(fr.wcs)
                if 2.0 < dpx < (h + 3) * pixel_scale_arcsec(fr.wcs) * 1.5:   # too close to separate: not fitted
                    nbxy.append((float(a_), float(b_)))
        cen = fit_centroid(fr.image - (fr.zodi if fr.zodi is not None else 0), fr.variance, bad, fr.wcs, px, py,
                           half=h, min_snr=settings.min_snr_centroid, floor_arcsec=settings.astrometric_floor_arcsec,
                           neighbours=nbxy)
        rec["centroid"] = cen.to_dict()
        if cen.ok:
            cra, cdec = (cen.ra_deg, cen.dec_deg)
            from .astrometry import tangent_offsets
            dx, dy = tangent_offsets(cra, cdec, pra, pdec)
            rec["centroid"]["offset_from_prediction_arcsec"] = [float(dx), float(dy)]
        # Forced photometry at the predicted position (independent of whether the centroid succeeded)
        phot = forced_aperture(fr.image, fr.variance, bad, fr.zodi, fr.wcs, px, py,
                               r=settings.aperture_radius_px, annulus=settings.annulus_px)
        if not phot.ok and "flagged" in phot.reason and cen.ok:
            phot = psf_wing_flux(cen, fr.wcs, phot.reason)   # saturated core: use the unflagged wings
        rec["photometry"] = phot.to_dict()
        rec["status"] = "ok"
        # Display products
        try:
            rp = reproject_to(fr.image - (fr.zodi if fr.zodi is not None else 0), bad, fr.wcs, disp_wcs, n_disp)
        except Exception as exc:  # noqa: BLE001
            rp = None
            rec["warnings"].append(f"display reprojection failed: {exc}")
        reproj.append(rp)
        native.append((fr, bad))
        disp = {"pred_frac": to_display_frac(disp_wcs, n_disp, pra, pdec)}
        if cen.ok:
            disp["meas_frac"] = to_display_frac(disp_wcs, n_disp, cen.ra_deg, cen.dec_deg)
        rec["display"] = disp
        frames.append(rec)

    # ---------------- differential calibration with Gaia field stars ----------------
    cal_info: dict = {"enabled": False}
    cals = [None] * len(frames)
    refs_f: list = []
    floor = settings.astrometric_floor_arcsec
    pfloor = None
    if req.use_gaia:
        progress(0.78, "Querying Gaia DR3 for field stars")
        try:
            refs_f = field_references(ra_q, dec_q, size / 2 * 0.95, ref, gmax=settings.field_gmax)
            cals = measure_field(frames, native, refs_f, pred, settings,
                                 progress=lambda k, n: progress(0.79 + 0.04 * k / max(n, 1),
                                                                f"Calibrating exposure {k + 1}/{n} with {len(refs_f)} Gaia stars"))
            progress(0.83, "Field-star error floor and controls")
            floor = max(floor, systematic_floor(cals))
            calibrate(cals, floor)
            pfloor = photometric_floor(frames, cals, settings.wavelength_bin_rel)
            ncal = sum(1 for c in cals if c and c.ok)
            nst = [c.n for c in cals if c and c.ok]
            cal_info = {"enabled": True, "n_reference_stars": len(refs_f), "frames_calibrated": ncal,
                        "frames_usable": sum(1 for c in cals if c is not None),
                        "median_stars_per_frame": float(np.median(nst)) if nst else 0,
                        "astrometric_floor_arcsec": floor, "photometric_floor_frac": pfloor,
                        "gaia_gmax": settings.field_gmax}
            log.append(f"Field calibration: {len(refs_f)} Gaia stars, {ncal} frames calibrated, "
                       f"systematic floor {floor:.3f}\", photometric floor {pfloor}")
        except Exception as exc:  # noqa: BLE001
            log.append(f"Field calibration unavailable: {type(exc).__name__}: {exc}")
    use_cal = cal_info.get("enabled") and cal_info.get("frames_calibrated", 0) >= 3
    # Exposures without enough field stars keep their raw position, with an extra error equal to the
    # exposure-to-exposure scatter of the offsets measured where calibration was possible.
    offs = np.array([[c.off_xi, c.off_eta] for c in cals if c and c.ok]) if use_cal else np.zeros((0, 2))
    uncal_sigma = None
    if len(offs) >= 5:
        uncal_sigma = [float(1.4826 * np.median(np.abs(offs[:, k] - np.median(offs[:, k])))) for k in (0, 1)]
        cal_info["uncalibrated_exposure_extra_sigma_arcsec"] = uncal_sigma
    from .astrometry import tangent_offsets
    for f, cal, nat in zip(frames, cals, native):
        if f.get("status") != "ok":
            continue
        f["astrometric_calibration"] = cal.to_dict() if cal else {"ok": False, "n_stars": 0}
        if use_cal and cal and cal.ok and nat is not None:
            # forced photometry where the target really is in this exposure: prediction + exposure offset
            fr, bad = nat
            p0 = f["predicted"]
            sra, sdec = apply_offset(p0["ra_deg"], p0["dec_deg"], -cal.off_xi, -cal.off_eta)
            sx, sy = (float(v) for v in fr.wcs.world_to_pixel_values(sra, sdec))
            ph = forced_aperture(fr.image, fr.variance, bad, fr.zodi, fr.wcs, sx, sy,
                                 r=settings.aperture_radius_px, annulus=settings.annulus_px)
            if not ph.ok and "flagged" in ph.reason and f["centroid"]["ok"]:
                from .astrometry import Centroid
                ph = psf_wing_flux(Centroid(**{k: v for k, v in f["centroid"].items() if k in Centroid.__dataclass_fields__}),
                                   fr.wcs, ph.reason)
            f["photometry"] = {**ph.to_dict(), "position": "prediction + exposure offset"}
        c = f["centroid"]
        if not c["ok"]:
            continue
        c["ra_raw_deg"], c["dec_raw_deg"] = c["ra_deg"], c["dec_deg"]
        c["calibrated"] = False
        if use_cal and not (cal and cal.ok):
            if uncal_sigma is None:
                c["ok"], c["reason"] = False, "exposure could not be calibrated (<3 field stars)"
                continue
            c["sigma_ra_arcsec"] = float(np.sqrt(c["sigma_ra_arcsec"] ** 2 + uncal_sigma[0] ** 2 + floor ** 2))
            c["sigma_dec_arcsec"] = float(np.sqrt(c["sigma_dec_arcsec"] ** 2 + uncal_sigma[1] ** 2 + floor ** 2))
            c["calibration_note"] = "no field stars: raw position, error inflated by exposure-to-exposure WCS scatter"
        elif use_cal:
            c["ra_deg"], c["dec_deg"] = apply_offset(c["ra_deg"], c["dec_deg"], cal.off_xi, cal.off_eta)
            c["sigma_ra_arcsec"] = float(np.sqrt(c["sigma_ra_arcsec"] ** 2 + cal.err_xi ** 2 + floor ** 2))
            c["sigma_dec_arcsec"] = float(np.sqrt(c["sigma_dec_arcsec"] ** 2 + cal.err_eta ** 2 + floor ** 2))
            c["calibrated"] = True
        p = f["predicted"]
        dx, dy = tangent_offsets(c["ra_deg"], c["dec_deg"], p["ra_deg"], p["dec_deg"])
        c["raw_offset_from_prediction_arcsec"] = c.get("offset_from_prediction_arcsec")
        c["offset_from_prediction_arcsec"] = [float(dx), float(dy)]
        # Association gate: with a known catalogue track, a detection far from it is a different source.
        # The gate scales with the detection's own error when the catalogue gives proper motion and parallax.
        gate = settings.association_radius_arcsec
        if ref is not None and getattr(ref, "pm_known", True) and ref.parallax_mas is not None:
            s1 = float(np.hypot(c["sigma_ra_arcsec"], c["sigma_dec_arcsec"]) / np.sqrt(2))
            gate = min(gate, max(settings.association_min_arcsec, settings.association_nsigma * s1))
        c["association_gate_arcsec"] = float(gate)
        if ref is not None and np.hypot(dx, dy) > gate:
            c["ok"] = False
            c["reason"] = (f"detection {np.hypot(dx, dy):.1f}\" from predicted position "
                           f"(> {gate:.1f}\" gate): likely a neighbouring source")
            f["display"].pop("meas_frac", None)
            continue
        f["display"]["meas_frac"] = to_display_frac(disp_wcs, n_disp, c["ra_deg"], c["dec_deg"])

    progress(0.83, "Rendering frames on a shared scale per wavelength bin")
    _render_frames(frames, reproj, jdir, settings)
    progress(0.84, "Wavelength-matched differences")
    _matched_differences(frames, reproj, jdir, settings)

    progress(0.88, "Fitting motion and variability")
    good = [f for f in frames if f.get("status") == "ok" and f["centroid"]["ok"]]
    motion = fit_motion([f["time_mjd"] for f in good], [f["centroid"]["ra_deg"] for f in good],
                        [f["centroid"]["dec_deg"] for f in good], [f["centroid"]["sigma_ra_arcsec"] for f in good],
                        [f["centroid"]["sigma_dec_arcsec"] for f in good], ref)
    motion_dict = motion.to_dict()
    motion_dict["calibrated"] = bool(use_cal)
    # Parallax from SPHEREx alone (5-parameter fit; the catalogue parallax is only used for comparison)
    motion_dict["parallax_fit"] = fit_parallax([f["time_mjd"] for f in good], [f["centroid"]["ra_deg"] for f in good],
                                               [f["centroid"]["dec_deg"] for f in good],
                                               [f["centroid"]["sigma_ra_arcsec"] for f in good],
                                               [f["centroid"]["sigma_dec_arcsec"] for f in good], ref)
    motion_dict["parallax_fit"]["saturated_epoch_fraction"] = (
        float(np.mean([(f["centroid"].get("core_flagged_px") or 0) >= 3 for f in good])) if good else None)
    okp = [f for f in frames if f.get("status") == "ok" and f["photometry"]["ok"]
           and f["photometry"]["flux_err_ujy"] and f["photometry"]["flux_ujy"] / f["photometry"]["flux_err_ujy"] >= 3]
    pf = pfloor or 0.0
    var = variability_by_bin([f["wavelength_um"] for f in okp], [f["photometry"]["flux_ujy"] for f in okp],
                             [float(np.hypot(f["photometry"]["flux_err_ujy"], pf * f["photometry"]["flux_ujy"])) for f in okp],
                             settings.wavelength_bin_rel, methods=[f["photometry"].get("method", "aperture") for f in okp])
    var["photometric_floor_frac"] = pfloor
    var["points_used"] = len(okp)
    var["max_amplitude_ratio"] = max((b["max_over_min"] or 1.0 for b in var["bins"] if b["p_value"] < 1e-3), default=None)
    # how much brighter than the calibration stars is the target? (non-linearity / saturation risk)
    fstar = [m.flux for c in cals if c for m in c.stars if m.flux and m.flux > 0]
    ftgt = [f["photometry"]["flux_ujy"] for f in okp if f["photometry"]["flux_ujy"] > 0]
    var["target_to_field_flux_ratio"] = float(np.median(ftgt) / np.median(fstar)) if fstar and ftgt else None
    diag = photocentre_diagnostics(frames, settings)

    sed = spectral_energy_distribution(frames)

    progress(0.92, "False-positive controls (field stars)")
    controls = {"n_stars": 0, "note": "calibration disabled or unavailable"}
    if use_cal and req.n_controls:
        try:
            controls = field_controls(frames, cals, refs_f, floor)
        except Exception as exc:  # noqa: BLE001
            log.append(f"Controls unavailable: {exc}")

    dossier = {
        "schema": SCHEMA,
        "job_id": job_id,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data_kind": ("SYNTHETIC test fixture — not astronomical data"
                      if any(o.access_url.startswith("synthetic://") for o in obs)
                      else "REAL — IRSA SPHEREx archive"),
        "software": _versions(),
        "settings": settings.public_dict(),
        "request": req.to_dict(),
        "target": {"name": name, "reference": ref.to_dict() if ref else None,
                   "query_position_deg": [ra_q, dec_q], "query_epoch_jyear": 2026.0},
        "archive": {"sia_url": settings.irsa_sia_url,
                    "collections": sorted({o.collection for o in obs}) or list(colls), "n_found": len(obs_all),
                    "n_selected": len(obs), "cutout_size_arcsec": size,
                    "time_range_mjd": [obs_all[0].t_mid_mjd, obs_all[-1].t_mid_mjd]},
        "display_grid": {"pix_arcsec": DISPLAY_PIX_ARCSEC, "n": n_disp, "resampling": "nearest-neighbour",
                         "note": "north up, east left; greyscale = measured surface brightness; "
                                 "resampled for display only, measurements use native pixels"},
        "frames": frames,
        "results": {"motion": motion_dict, "variability": var, "sed": sed, "controls": controls,
                    "calibration": cal_info, "photocentre": diag},
        "log": log,
    }
    dossier["verdicts"] = verdicts(dossier)
    dossier["caveats"] = caveats(dossier)
    dossier["reproduce"] = {"cli": f"python -m epochlab.cli reproduce data/jobs/{job_id}/dossier.json",
                            "note": "Re-runs the identical request/settings and compares file hashes and results."}
    (jdir / "dossier.json").write_text(json.dumps(dossier, indent=1, default=_json_default))
    progress(1.0, "Done")
    return jdir


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, Path):
        return str(o)
    raise TypeError(type(o))


def photocentre_diagnostics(frames, settings, min_points: int = 8) -> dict:
    """Does the measured position (relative to the catalogue track) correlate with brightness or with
    wavelength? For an unresolved pair with a variable or differently-coloured component, the centre of
    light shifts as the flux ratio changes (variability-induced / chromatic photocentre shift)."""
    from scipy.stats import pearsonr
    rows = [f for f in frames if f.get("status") == "ok" and f["centroid"]["ok"] and f["photometry"]["ok"]
            and f.get("wavelength_um") and f["photometry"]["flux_ujy"] > 0]
    if len(rows) < min_points:
        return {"ok": False, "reason": f"needs >= {min_points} epochs with position and flux, have {len(rows)}"}
    off = np.array([f["centroid"]["offset_from_prediction_arcsec"] for f in rows])
    off = off - np.median(off, axis=0)
    lam = np.log([f["wavelength_um"] for f in rows])
    lf = np.log([f["photometry"]["flux_ujy"] for f in rows])
    # brightness relative to a smooth SED trend (removes the wavelength dependence, keeps variability)
    deg = 3 if len(rows) >= 12 else 1
    trend = np.polyval(np.polyfit(lam, lf, deg), lam)
    dflux = lf - trend
    out = {"ok": True, "n": len(rows), "tests": []}
    for label, x in (("brightness", dflux), ("wavelength", lam)):
        for k, axis in ((0, "RA*"), (1, "Dec")):
            r, p = pearsonr(x, off[:, k])
            out["tests"].append({"versus": label, "axis": axis, "r": float(r), "p": float(min(1.0, p * 4))})  # 4 tests
    best = min(out["tests"], key=lambda t: t["p"])
    out["most_significant"] = best
    out["shift_detected"] = bool(best["p"] < 1e-3)
    return out


def spectral_energy_distribution(frames) -> dict:
    """SPHEREx builds spectra from many exposures, each at a different wavelength. The same forced-aperture
    fluxes used for variability, ordered by wavelength, give an approximate 0.75-5 um SED of the target."""
    pts = [{"index": f["index"], "lambda_um": f["wavelength_um"], "bandwidth_um": f.get("bandwidth_um"),
            "flux_ujy": f["photometry"]["flux_ujy"], "flux_err_ujy": f["photometry"]["flux_err_ujy"],
            "time_mjd": f["time_mjd"]}
           for f in frames if f.get("status") == "ok" and f["photometry"]["ok"] and f.get("wavelength_um")]
    pts.sort(key=lambda p: p["lambda_um"])
    return {
        "points": pts,
        "n": len(pts),
        "lambda_range_um": [pts[0]["lambda_um"], pts[-1]["lambda_um"]] if pts else None,
        "kind": "approximate SED from forced aperture photometry",
        "caveat": ("Aperture fluxes without aperture correction; the PSF size changes with wavelength, so the "
                   "spectral shape is approximate. Not a calibrated spectrum; no molecular detection is claimed."),
    }


def _render_frames(frames, reproj, jdir: Path, settings: Settings):
    """One intensity scale per wavelength bin (shared by all its epochs); frames with unknown wavelength
    get their own scale, and say so."""
    lams = [f.get("wavelength_um") if f.get("status") == "ok" else None for f in frames]
    bins = wavelength_bins(lams, settings.wavelength_bin_rel)
    groups: dict[int, list[int]] = {}
    for i, f in enumerate(frames):
        if f.get("status") == "ok" and reproj[i] is not None:
            groups.setdefault(int(bins[i]) if bins[i] >= 0 else -1000 - i, []).append(i)
    for b, idx in groups.items():
        lim = display_limits([reproj[i] for i in idx])
        for i in idx:
            st = save_png(reproj[i], jdir / "frames" / f"{i:03d}.png",
                          *(lim if lim else (None, None)))
            ls = [lams[k] for k in idx]
            st["scope"] = (f"shared by {len(idx)} epoch(s) at λ {min(ls):.3f}–{max(ls):.3f} µm" if b >= 0
                           else "this frame only (wavelength unknown)")
            frames[i]["display"].update(png=f"frames/{i:03d}.png", stretch=st)


def _matched_differences(frames, reproj, jdir: Path, settings: Settings, min_dt_days: float = 30.0):
    """For each frame, difference against the closest-in-wavelength frame of the SAME bin taken
    at least `min_dt_days` apart. Frames with no partner get no difference image (stated explicitly)."""
    lams = [f.get("wavelength_um") if f.get("status") == "ok" else None for f in frames]
    bins = wavelength_bins(lams, settings.wavelength_bin_rel)
    for i, f in enumerate(frames):
        if f.get("status") != "ok" or reproj[i] is None or bins[i] < 0:
            continue
        best, bestd = None, np.inf
        for j, g in enumerate(frames):
            if j == i or bins[j] != bins[i] or reproj[j] is None:
                continue
            if abs(g["time_mjd"] - f["time_mjd"]) < min_dt_days:
                continue
            d = abs(lams[j] - lams[i])
            if d < bestd:
                best, bestd = j, d
        if best is None:
            f["display"]["diff_note"] = "no other epoch in the same wavelength bin"
            continue
        diff = reproj[i] - reproj[best]
        p = jdir / "frames" / f"{i:03d}_diff.png"
        dst = save_png(diff, p, symmetric=True)
        f["display"].update(diff_png=f"frames/{i:03d}_diff.png", diff_ref_index=best, diff_stretch=dst,
                            diff_dlambda_um=float(bestd),
                            diff_dt_days=float(f["time_mjd"] - frames[best]["time_mjd"]))


def verdicts(d: dict) -> list[dict]:
    """Automatic, conservative checks. Each verdict states the rule used."""
    v = []
    frames = d["frames"]
    n_ok = sum(1 for f in frames if f.get("status") == "ok")
    n_cen = sum(1 for f in frames if f.get("status") == "ok" and f["centroid"]["ok"])
    v.append({"check": "data_provenance", "result": "PASS" if all("download" in f for f in frames if f.get("status") == "ok") and n_ok else "FAIL",
              "rule": "every measured frame has archive URL + SHA-256", "detail": f"{n_ok} frames measured"})
    lam_det = [f["wavelength_um"] for f in frames if f.get("status") == "ok" and f["centroid"]["ok"] and f.get("wavelength_um")]
    v.append({"check": "detection", "result": "PASS" if n_cen >= 3 else "FAIL",
              "rule": "centroid S/N >= threshold, at the predicted position, in >= 3 epochs",
              "detail": f"{n_cen}/{n_ok} epochs" + (f" at λ {min(lam_det):.2f}–{max(lam_det):.2f} µm" if lam_det else "")})
    cal = d["results"].get("calibration", {})
    if cal.get("enabled"):
        ok = cal["frames_calibrated"] >= 3
        v.append({"check": "astrometric_calibration", "result": "PASS" if ok else "FAIL",
                  "rule": "per-exposure offsets from >= 3 Gaia field stars in >= 3 exposures",
                  "detail": f"{cal['frames_calibrated']}/{cal['frames_usable']} exposures, median "
                            f"{cal['median_stars_per_frame']:.0f} stars, floor {cal['astrometric_floor_arcsec']:.2f}″"})
    m = d["results"]["motion"]
    if m["ok"]:
        moving = m["p_value_static"] is not None and m["p_value_static"] < 1e-3
        v.append({"check": "motion_detected", "result": "YES" if moving else "NO EVIDENCE",
                  "rule": "static-position model rejected at p < 1e-3",
                  "detail": f"p = {m['p_value_static']:.2e}, span {m['time_span_yr']:.2f} yr"})
        if m.get("z_pmra") is not None:
            ok = abs(m["z_pmra"]) < 3 and abs(m["z_pmdec"]) < 3
            v.append({"check": "proper_motion_vs_catalogue", "result": "CONSISTENT" if ok else "INCONSISTENT",
                      "rule": "|measured - catalogue| < 3 sigma in both axes",
                      "detail": f"z = ({m['z_pmra']:+.2f}, {m['z_pmdec']:+.2f})"})
    else:
        v.append({"check": "motion_fit", "result": "INCONCLUSIVE", "rule": "needs >=3 epochs over >=0.1 yr",
                  "detail": m["reason"]})
    var = d["results"]["variability"]
    if n_cen < 3:
        v.append({"check": "variability_matched_wavelength", "result": "INCONCLUSIVE",
                  "rule": "variability is only assessed for a detected target", "detail": "target not detected"})
    elif var["combined_dof"] and var["combined_dof"] < d["settings"].get("min_variability_dof", 3):
        v.append({"check": "variability_matched_wavelength", "result": "INCONCLUSIVE",
                  "rule": f"needs >= {d['settings'].get('min_variability_dof', 3)} repeat measurements in common wavelength bins",
                  "detail": f"only {var['combined_dof']} (chi2/dof = {var['combined_chi2']:.1f}/{var['combined_dof']}); "
                            "a bright target may be saturated in most exposures"})
    elif var["combined_dof"]:
        p = var["combined_p_value"]
        pf = var.get("photometric_floor_frac")
        amp = var.get("max_amplitude_ratio") or 1.0
        res = "NO EVIDENCE" if p >= 1e-3 else ("VARIABLE" if amp >= d["settings"].get("large_amplitude", 1.2)
                                               else "POSSIBLE (low amplitude)")
        # Robustness (added after the first real-data run, Nov 2026): a rejection carried only by fluxes from the
        # wings of a saturated PSF, or by a single wavelength bin (often one outlying exposure), is not called VARIABLE.
        sig = [b for b in var.get("bins", []) if b.get("p_value", 1.0) < 1e-2]
        why = ""
        if p < 1e-3 and sig and all(b.get("method") != "aperture" for b in sig):
            res, why = "POSSIBLE (saturated core)", "; signal only in PSF-wing fluxes of a saturated core"
        elif p < 1e-3 and len(sig) == 1:
            b = sig[0]
            res, why = "POSSIBLE (one λ bin)", f"; driven by one bin ({b['lambda_um_min']:.2f}–{b['lambda_um_max']:.2f} µm, n={b['n']})"
        v.append({"check": "variability_matched_wavelength", "result": res,
                  "rule": "constant flux rejected at p < 1e-3 within same-wavelength bins (errors incl. field-star floor); "
                          "VARIABLE if max/min >= 1.2 and the rejection is seen in >= 2 bins with aperture photometry; "
                          "otherwise POSSIBLE (low amplitude / one bin / saturated core)",
                  "detail": f"chi2/dof = {var['combined_chi2']:.1f}/{var['combined_dof']}, p = {p:.2e}, max/min {amp:.2f}"
                            + (f", floor {100 * pf:.1f}%" if pf is not None else ", no floor (no field stars)") + why})
    else:
        v.append({"check": "variability_matched_wavelength", "result": "INCONCLUSIVE",
                  "rule": "needs >=2 epochs in a common wavelength bin", "detail": "no bin with >=2 epochs"})
    ph = d["results"].get("photocentre", {})
    if ph.get("ok"):
        b = ph["most_significant"]
        v.append({"check": "photocentre_shift", "result": "DETECTED" if ph["shift_detected"] else "NO EVIDENCE",
                  "rule": "position residual vs brightness or wavelength, Pearson p < 1e-3 (4 tests, Bonferroni)",
                  "detail": f"strongest: {b['axis']} vs {b['versus']}, r = {b['r']:+.2f}, p = {b['p']:.1e}"})
    ctr = d["results"]["controls"]
    v += _parallax_verdict(d)
    if ctr.get("n_stars", 0) >= 3:
        ok = ctr["frac_abs_z_gt_3"] <= 0.10 and ctr["z_std"] < 2.0
        v.append({"check": "field_star_controls", "result": "PASS" if ok else "FAIL",
                  "rule": "Gaia field stars through the same pipeline: <=10% with |z|>3 and z spread < 2",
                  "detail": f"{ctr['n_stars']} stars, {100 * ctr['frac_abs_z_gt_3']:.0f}% |z|>3, z std {ctr['z_std']:.2f}"})
    elif cal.get("enabled"):
        v.append({"check": "field_star_controls", "result": "INCONCLUSIVE", "rule": "needs >= 3 field stars in >= 3 epochs",
                  "detail": f"{ctr.get('n_stars', 0)} usable stars"})
    return v


def _parallax_verdict(d: dict) -> list[dict]:
    """Distance from SPHEREx alone. Trusted only when the target is unsaturated, shows no photocentre shift,
    and the same fit gives Gaia's parallaxes for the field stars. First real-data test (15 Nov 2026): eps Ind B
    300 +/- 46 mas vs Gaia 271; the saturated stars (Barnard, R Dra) and RW Aur (photocentre shift) gave
    spurious values of 350-1000 mas, so those cases are reported as NOT RELIABLE."""
    pf = (d["results"].get("motion") or {}).get("parallax_fit") or {}
    rule = ("5-parameter fit (offset, proper motion, parallax) with no catalogue input; reliable only if the target "
            "is unsaturated (<50% of epochs with a flagged core), shows no photocentre shift, and the field stars' "
            "fitted parallaxes agree with Gaia (<=10% beyond 3 sigma, z spread < 2); detected if >= 3 sigma")
    if not pf.get("ok"):
        return [{"check": "distance_from_parallax", "result": "NOT MEASURED", "rule": rule,
                 "detail": pf.get("reason", "no motion fit")}]
    plx, err = pf["parallax_mas"], pf["parallax_err_mas"]
    val = f"parallax {plx:.0f} ± {err:.0f} mas"
    if pf.get("catalogue_parallax_mas") is not None:
        val += f" (Gaia {pf['catalogue_parallax_mas']:.1f}, z = {pf['z_vs_catalogue']:+.1f})"
    why = []
    if (pf.get("saturated_epoch_fraction") or 0) >= 0.5:
        why.append(f"saturated core in {100 * pf['saturated_epoch_fraction']:.0f}% of epochs")
    ph = d["results"].get("photocentre", {})
    if ph.get("ok") and ph.get("shift_detected"):
        why.append("photocentre shifts with brightness or wavelength")
    ctr = d["results"].get("controls", {})
    if (ctr.get("parallax_n_stars") or 0) < 3:
        why.append("too few field stars to test the parallax fit")
    elif ctr["parallax_frac_abs_z_gt_3"] > 0.10 or ctr["parallax_z_std"] >= 2.0:
        why.append(f"field-star parallax controls fail (z std {ctr['parallax_z_std']:.2f})")
    if why:
        return [{"check": "distance_from_parallax", "result": "NOT RELIABLE", "rule": rule,
                 "detail": val + "; " + "; ".join(why)}]
    ctl = f"; {ctr['parallax_n_stars']} control stars, z std {ctr['parallax_z_std']:.2f}"
    if plx < 3 * err:
        lim = 1000.0 / (max(plx, 0.0) + 3 * err)
        return [{"check": "distance_from_parallax", "result": "NOT DETECTED", "rule": rule,
                 "detail": f"{val}; farther than {lim:.1f} pc (3σ){ctl}"}]
    lo, hi = pf["distance_pc_range_1sigma"]
    res = "MEASURED"
    if pf.get("z_vs_catalogue") is not None and abs(pf["z_vs_catalogue"]) >= 3:
        res = "INCONSISTENT"
    return [{"check": "distance_from_parallax", "result": res, "rule": rule,
             "detail": f"{val}; distance {1000 / plx:.1f} pc ({lo:.1f}–{hi:.1f}), {plx / err:.1f}σ{ctl}"}]


def caveats(d: dict) -> list[str]:
    c = []
    cal = d["results"].get("calibration", {})
    if not cal.get("enabled") or cal.get("frames_calibrated", 0) < 3:
        c.append("Per-exposure astrometric calibration with field stars was NOT applied: positions carry the "
                 "archive WCS systematics, which on real SPHEREx data exceed the formal errors.")
    tf = d["results"]["variability"].get("target_to_field_flux_ratio")
    if tf and tf > 50:
        c.append(f"The target is ~{tf:.0f}x brighter than the calibration stars; the photometric floor measured on them "
                 "may not capture bright-star systematics (non-linearity, saturation, halo). Treat low-amplitude "
                 "variability as unconfirmed.")
    ph = d["results"].get("photocentre", {})
    if ph.get("shift_detected"):
        c.append("Position correlates with " + ph["most_significant"]["versus"] + ": the measured motion can be biased "
                 "by a shifting centre of light (e.g. an unresolved companion, a variable component, or nebulosity). "
                 "This is a diagnostic, not a claim about the system.")
    m = d["results"]["motion"]
    if m.get("error_scale") and m["error_scale"] > 1.5:
        c.append(f"Proper-motion errors were scaled by {m['error_scale']:.1f} (sqrt of reduced chi2) because the "
                 "positional scatter exceeds the formal errors.")
    if any(f.get("photometry", {}).get("method") == "psf_wings" for f in d["frames"] if f.get("status") == "ok"):
        c.append("Some fluxes come from a Gaussian fit to unflagged PSF wings because the core was flagged "
                 "(e.g. saturated); they are compared only with each other.")
    c += ["Positions are measured with a circular-Gaussian approximation to the PSF on native pixels; "
         "the PSF extension is not yet used (ePSF fitting is a planned upgrade).",
         "Fluxes are aperture fluxes without aperture correction; compare only within a wavelength bin.",
         "A significant motion or variability statistic identifies a candidate for follow-up, not a discovery."]
    if not cal.get("enabled") and d["settings"]["astrometric_floor_arcsec"] == 0:
        c.append("No systematic astrometric floor was added; reduced chi2 of the linear fit indicates whether "
                 "formal errors are realistic.")
    m = d["results"]["motion"]
    if m.get("reduced_chi2_linear") and m["reduced_chi2_linear"] > 2:
        c.append(f"Linear-motion reduced chi2 = {m['reduced_chi2_linear']:.1f} > 2: formal position errors "
                 "are likely underestimated; treat z-scores with caution.")
    if d["target"]["reference"] is None and d["target"]["name"]:
        c.append("No catalogue proper motion was available for this name, so no predicted track is shown and the "
                 "comparison with a catalogue is skipped; motion is fitted freely. A fast mover may sit off-centre "
                 "in the cutouts.")
    ref = d["target"]["reference"]
    if ref and ref["source"].startswith(("SIMBAD", "Sesame")):
        c.append("Reference astrometry from SIMBAD (no Gaia DR3 match); catalogue uncertainties not propagated.")
    return c


def reproduce(dossier_path: Path, settings: Settings = default_settings) -> dict:
    """Re-run an analysis from its dossier and compare hashes and key numbers."""
    old = json.loads(Path(dossier_path).read_text(encoding="utf-8"))
    req = AnalysisRequest(**old["request"])
    req.pinned_observations = [f["observation"] for f in old["frames"] if f.get("status") == "ok"]
    s = replace(settings, **{k: (tuple(v) if isinstance(v, list) else v) for k, v in old["settings"].items()
                             if k in Settings.__dataclass_fields__ and k != "data_dir"})
    new_dir = analyze(req, s)
    new = json.loads((new_dir / "dossier.json").read_text(encoding="utf-8"))
    oh = {f["download"]["url"]: f["download"]["sha256"] for f in old["frames"] if "download" in f and f.get("status") == "ok"}
    nh = {f["download"]["url"]: f["download"]["sha256"] for f in new["frames"] if "download" in f}
    same_files = sorted(set(oh) & set(nh))
    mismatched = [u for u in same_files if oh[u] != nh[u]]
    om, nm = old["results"]["motion"], new["results"]["motion"]
    keys = ["pmra_masyr", "pmdec_masyr", "pmra_err", "pmdec_err", "chi2_static"]
    diffs = {k: (om.get(k), nm.get(k)) for k in keys}
    same_numbers = all((a is None and b is None) or (a is not None and b is not None and abs(a - b) <= 1e-6 * max(1, abs(a)))
                       for a, b in diffs.values())
    return {"old_job": old["job_id"], "new_job": new["job_id"], "files_compared": len(same_files),
            "hash_mismatches": mismatched, "only_in_old": sorted(set(oh) - set(nh)),
            "only_in_new": sorted(set(nh) - set(oh)), "motion_values": diffs,
            "identical_results": not mismatched and same_numbers}
