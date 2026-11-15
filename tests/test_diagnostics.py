"""Photocentre-shift diagnostic and verdict gating (SYNTHETIC inputs)."""
import numpy as np

import epochlab.pipeline as pl
from epochlab.config import Settings


def _frames(n, shift_per_dex, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        lam = float(rng.uniform(0.8, 4.8))
        u = float(rng.normal(0, 0.25))                  # brightness variation (dex-like)
        flux = 1000 * lam ** -1.0 * 10 ** u
        dx = shift_per_dex * u + rng.normal(0, 0.05)   # photocentre moves with brightness
        out.append({"status": "ok", "wavelength_um": lam, "time_mjd": 61000 + i,
                    "centroid": {"ok": True, "offset_from_prediction_arcsec": [dx, rng.normal(0, 0.05)]},
                    "photometry": {"ok": True, "flux_ujy": flux, "flux_err_ujy": flux * 0.01}})
    return out


def test_photocentre_shift_detected_for_variable_blend():
    d = pl.photocentre_diagnostics(_frames(30, shift_per_dex=1.0), Settings())
    assert d["ok"] and d["shift_detected"] and d["most_significant"]["versus"] == "brightness"


def test_no_photocentre_shift_for_single_star():
    d = pl.photocentre_diagnostics(_frames(30, shift_per_dex=0.0, seed=3), Settings())
    assert d["ok"] and not d["shift_detected"]


def _dossier(n_detected, var_p, amp):
    frames = [{"status": "ok", "download": {}, "wavelength_um": 1.0,
               "centroid": {"ok": i < n_detected}, "photometry": {"ok": True}} for i in range(10)]
    return {"frames": frames, "settings": {"large_amplitude": 1.2},
            "results": {"motion": {"ok": False, "reason": "x"}, "controls": {}, "calibration": {}, "photocentre": {},
                        "variability": {"combined_dof": 10, "combined_p_value": var_p, "combined_chi2": 50.0,
                                        "max_amplitude_ratio": amp, "photometric_floor_frac": 0.02}}}


def _var(d):
    return next(v for v in pl.verdicts(d) if v["check"] == "variability_matched_wavelength")["result"]


def test_variability_not_assessed_without_detection():
    assert _var(_dossier(0, 1e-6, 2.0)) == "INCONCLUSIVE"


def test_variability_tiers():
    assert _var(_dossier(10, 1e-6, 2.0)) == "VARIABLE"
    assert _var(_dossier(10, 1e-6, 1.05)) == "POSSIBLE (low amplitude)"
    assert _var(_dossier(10, 0.2, 1.05)) == "NO EVIDENCE"


def _bin(p, method="aperture", lam=1.8):
    return {"p_value": p, "method": method, "lambda_um_min": lam, "lambda_um_max": lam + 0.01, "n": 3, "max_over_min": 1.5}


def test_variability_needs_two_bins_and_unsaturated_photometry():
    """Real-data lessons (Nov 2026): eps Ind B's rejection came from one bin; Barnard's only from saturated PSF wings."""
    d = _dossier(10, 1e-6, 2.0)
    d["results"]["variability"]["bins"] = [_bin(1e-5), _bin(0.5, lam=4.0)]
    assert _var(d) == "POSSIBLE (one λ bin)"
    d["results"]["variability"]["bins"] = [_bin(1e-5, "psf_wings"), _bin(1e-4, "psf_wings", 4.0)]
    assert _var(d) == "POSSIBLE (saturated core)"
    d["results"]["variability"]["bins"] = [_bin(1e-5), _bin(1e-4, lam=4.0)]
    assert _var(d) == "VARIABLE"


def test_variability_with_one_repeat_is_inconclusive_not_no_evidence():
    """R Dra (Nov 2026) was saturated in most exposures: 1 degree of freedom must not read as 'no evidence'."""
    d = _dossier(10, 0.05, 1.0)
    d["results"]["variability"]["combined_dof"] = 1
    assert _var(d) == "INCONCLUSIVE"
