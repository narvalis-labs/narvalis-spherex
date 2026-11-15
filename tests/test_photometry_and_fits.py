"""Photometry, wavelength matching and MEF parsing (SYNTHETIC inputs)."""
import numpy as np

from epochlab.photometry import forced_aperture, variability_by_bin, wavelength_bins
from epochlab.spherex_fits import open_frame
from conftest import celestial_wcs, FLAG_BITS


def test_parse_synthetic_mef(mef_factory):
    p = mef_factory(ra0=100.0, dec0=10.0, mjd=61000.5, sources=[(100.0, 10.0, 20.0)], saturate=(3, 4))
    fr = open_frame(p)
    assert fr.time_mjd == 61000.5 and fr.time_source == "header MJD-AVG"
    assert fr.flag_bits == FLAG_BITS
    bad, used = fr.bad_pixel_mask(("SATUR", "NONFUNC"))
    assert bad[4, 3] and "SATURATED" in used and "SOURCE" not in used
    lam_lo, _, src = fr.wavelength_at(12, 2)
    lam_hi, _, _ = fr.wavelength_at(12, 22)
    assert src.startswith("WCS key W") and lam_hi > lam_lo
    assert abs((lam_hi - lam_lo) - 0.004 * 20) < 0.005


def test_missing_extensions_are_reported(tmp_path):
    from astropy.io import fits
    w = celestial_wcs(0, 0, 20, 0)
    p = tmp_path / "bare.fits"
    fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(np.zeros((20, 20)), header=w.to_header(), name="IMAGE")]).writeto(p)
    fr = open_frame(p)
    assert any("VARIANCE" in x for x in fr.warnings) and any("FLAGS" in x for x in fr.warnings)
    lam, bw, why = fr.wavelength_at(5, 5)
    assert lam is None and why  # never guesses a wavelength


def test_forced_aperture_flux_scales_linearly():
    w = celestial_wcs(0, 0, 31, 0)
    yy, xx = np.mgrid[0:31, 0:31]
    rng = np.random.default_rng(0)
    out = []
    for amp in (10.0, 20.0):
        img = 2.0 + amp * np.exp(-((xx - 15) ** 2 + (yy - 15) ** 2) / 2.0) + rng.normal(0, 0.01, (31, 31))
        ph = forced_aperture(img, np.full_like(img, 1e-4), np.zeros_like(img, bool), None, w, 15, 15)
        assert ph.ok
        out.append(ph.flux_ujy)
    assert abs(out[1] / out[0] - 2.0) < 0.01


def test_forced_aperture_refuses_flagged_aperture():
    w = celestial_wcs(0, 0, 31, 0)
    img = np.ones((31, 31))
    bad = np.zeros_like(img, bool)
    bad[15, 15] = True
    ph = forced_aperture(img, np.ones_like(img), bad, None, w, 15, 15)
    assert not ph.ok and "flagged" in ph.reason


def test_wavelength_matching_avoids_false_variability():
    """A CONSTANT source with a steep spectrum, observed at different wavelengths.
    A naive epoch-to-epoch comparison sees large 'changes'; the matched-wavelength test does not."""
    rng = np.random.default_rng(5)
    lams = np.concatenate([1.0 + rng.uniform(0, 0.01, 6), 2.0 + rng.uniform(0, 0.02, 6), 4.0 + rng.uniform(0, 0.04, 6)])
    true = 100.0 * lams ** -3          # steep spectrum, no time variation
    err = 0.01 * true
    flux = true + rng.normal(0, err)
    # naive: chi2 of a single constant across all epochs
    w = 1 / err ** 2
    mu = np.sum(w * flux) / np.sum(w)
    naive_chi2 = np.sum(((flux - mu) / err) ** 2)
    assert naive_chi2 > 1e4
    res = variability_by_bin(lams, flux, err, rel_width=0.02)
    assert res["combined_dof"] > 0 and res["combined_p_value"] > 1e-3


def test_wavelength_matching_detects_real_variability():
    rng = np.random.default_rng(9)
    lams = 2.0 + rng.uniform(0, 0.02, 10)
    err = np.full(10, 1.0)
    flux = 100 + np.where(np.arange(10) < 5, 0.0, 30.0) + rng.normal(0, 1, 10)  # 30% step in time
    res = variability_by_bin(lams, flux, err, 0.02)
    assert res["combined_p_value"] < 1e-6


def test_wavelength_bins_handle_missing():
    b = wavelength_bins([1.0, None, float("nan"), 1.005], 0.02)
    assert b[1] == -1 and b[2] == -1 and b[0] == b[3]


def test_psf_wing_flux_recovers_saturated_star():
    """Core pixels flagged (saturated): the wing fit must still recover the total flux within ~10%."""
    from epochlab.astrometry import fit_centroid
    from epochlab.photometry import psf_wing_flux, pixel_solid_angle_sr
    w = celestial_wcs(0, 0, 31, 0)
    yy, xx = np.mgrid[0:31, 0:31]
    rng = np.random.default_rng(2)
    amp, sig = 500.0, 1.1
    img = amp * np.exp(-((xx - 15.2) ** 2 + (yy - 14.9) ** 2) / (2 * sig ** 2)) + rng.normal(0, 0.5, (31, 31))
    var = np.full_like(img, 0.25)
    bad = np.hypot(xx - 15.2, yy - 14.9) < 1.3   # saturated core
    c = fit_centroid(img, var, bad, w, 15.0, 15.0)
    assert c.ok
    ph = psf_wing_flux(c, w, "core flagged")
    true = 2 * np.pi * sig ** 2 * amp * pixel_solid_angle_sr(w) * 1e12
    assert ph.ok and ph.method == "psf_wings" and abs(ph.flux_ujy / true - 1) < 0.1


def test_dr1_msk_flag_convention_is_read():
    """SPHEREx DR1 cutouts define FLAGS bits as MSKNnnnn/MSKMnnnn, not MP_*: they must be interpreted."""
    import numpy as np
    from astropy.io import fits
    from epochlab.spherex_fits import _parse_flag_bits, SpherexFrame
    from epochlab.config import settings
    h = fits.Header()
    for n, name in [(0, "TRANSIENT"), (1, "OVERFLOW"), (15, "NONLINEAR"), (21, "SOURCE"), (22, "GHOST")]:
        h[f"MSKN{n:04d}"] = name
        h[f"MSKM{n:04d}"] = 1 << n
    bits = _parse_flag_bits(h)
    assert bits == {"TRANSIENT": 0, "OVERFLOW": 1, "NONLINEAR": 15, "SOURCE": 21, "GHOST": 22}
    img = np.ones((3, 3)); flags = np.zeros((3, 3), np.int32)
    flags[0, 0] = 1 << 1; flags[1, 1] = 1 << 21; flags[2, 2] = 1 << 15
    fr = SpherexFrame.__new__(SpherexFrame)
    fr.image, fr.variance, fr.flags, fr.flag_bits = img, np.ones((3, 3)), flags, bits
    mask, used = fr.bad_pixel_mask(settings.reject_flag_substrings)
    assert mask[0, 0] and mask[2, 2] and not mask[1, 1]          # OVERFLOW, NONLINEAR rejected; SOURCE kept
    assert set(used) >= {"OVERFLOW", "NONLINEAR", "TRANSIENT"} and "SOURCE" not in used and "GHOST" not in used
