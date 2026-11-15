"""Unit tests for epoch propagation, centroiding and motion fitting (SYNTHETIC inputs)."""
import numpy as np
import astropy.units as u
from astropy.coordinates import get_body_barycentric
from astropy.time import Time

from epochlab.astrometry import (AstrometricReference, predict_position, tangent_offsets, fit_centroid,
                                 fit_motion)
from conftest import celestial_wcs


def _jy(mjd):
    return Time(mjd, format="mjd").jyear


def test_static_source_does_not_move():
    ref = AstrometricReference(150.0, 20.0, 2016.0, 0.0, 0.0)
    for mjd in (57000, 60500, 61000):
        ra, dec = predict_position(ref, mjd)
        assert abs(ra - 150.0) * 3600 < 1e-6 and abs(dec - 20.0) * 3600 < 1e-6


def test_linear_proper_motion_10yr():
    ref = AstrometricReference(10.0, 0.0, 2016.0, 1000.0, -500.0)
    mjd = Time(2026.0, format="jyear", scale="tcb").utc.mjd
    ra, dec = predict_position(ref, mjd, include_parallax=False)
    xi, eta = tangent_offsets(ra, dec, 10.0, 0.0)
    assert abs(xi - 10.0) < 1e-3 and abs(eta + 5.0) < 1e-3


def test_parallax_matches_textbook_formula():
    plx = 500.0  # mas
    ra0, dec0 = 60.0, 30.0
    ref = AstrometricReference(ra0, dec0, 2026.0, 0.0, 0.0, parallax_mas=plx)
    a, d = np.radians(ra0), np.radians(dec0)
    for mjd in np.linspace(61040, 61400, 7):
        ra, dec = predict_position(ref, mjd, True)
        xi, eta = tangent_offsets(ra, dec, ra0, dec0)
        X, Y, Z = get_body_barycentric("earth", Time(mjd, format="mjd")).xyz.to(u.au).value
        e_xi = plx * 1e-3 * (X * np.sin(a) - Y * np.cos(a))
        e_eta = plx * 1e-3 * (X * np.cos(a) * np.sin(d) + Y * np.sin(a) * np.sin(d) - Z * np.cos(d))
        assert abs(xi - e_xi) < 2e-3 and abs(eta - e_eta) < 2e-3


def _gauss_image(n, x, y, amp, sigma, noise, rng, bg=3.0):
    yy, xx = np.mgrid[0:n, 0:n]
    img = bg + amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2)) + rng.normal(0, noise, (n, n))
    return img, np.full((n, n), noise ** 2)


def test_centroid_errors_are_calibrated():
    """Pull distribution (fit - truth)/sigma must have unit width: the uncertainties mean what they say."""
    rng = np.random.default_rng(42)
    w = celestial_wcs(200.0, -10.0, 25, rot_deg=33.0)
    pulls = []
    for _ in range(300):
        x, y = 12 + rng.uniform(-0.5, 0.5), 12 + rng.uniform(-0.5, 0.5)
        img, var = _gauss_image(25, x, y, amp=12.0, sigma=1.0, noise=1.0, rng=rng)
        c = fit_centroid(img, var, np.zeros_like(img, bool), w, 12.0, 12.0, half=5, min_snr=5)
        assert c.ok, c.reason
        pulls += [(c.x - x) / c.sx, (c.y - y) / c.sy]
    s = np.std(pulls)
    assert 0.85 < s < 1.15, s
    assert abs(np.mean(pulls)) < 0.1


def test_centroid_rejects_noise_only():
    rng = np.random.default_rng(1)
    w = celestial_wcs(0.0, 0.0, 25, 0.0)
    img, var = _gauss_image(25, 12, 12, amp=0.0, sigma=1.0, noise=1.0, rng=rng)
    c = fit_centroid(img, var, np.zeros_like(img, bool), w, 12.0, 12.0, min_snr=5)
    assert not c.ok


def test_centroid_ignores_flagged_pixels():
    rng = np.random.default_rng(3)
    w = celestial_wcs(0.0, 0.0, 25, 0.0)
    img, var = _gauss_image(25, 12.2, 11.8, amp=30.0, sigma=1.1, noise=1.0, rng=rng)
    bad = np.zeros_like(img, bool)
    img[12, 12] = 1e6   # simulated hot/saturated pixel
    bad[12, 12] = True
    c = fit_centroid(img, var, bad, w, 12.0, 12.0)
    assert c.ok and abs(c.x - 12.2) < 0.2 and abs(c.y - 11.8) < 0.2


def _simulate_track(ref, mjds, sig_arcsec, rng):
    ra, dec = [], []
    for m in mjds:
        r, d = predict_position(ref, m, True)
        ra.append(r + rng.normal(0, sig_arcsec) / 3600 / np.cos(np.radians(d)))
        dec.append(d + rng.normal(0, sig_arcsec) / 3600)
    return np.array(ra), np.array(dec)


def test_motion_fit_recovers_pm_and_is_calibrated():
    rng = np.random.default_rng(7)
    ref = AstrometricReference(269.45, 4.69, 2016.0, -800.0, 10300.0, parallax_mas=550.0)
    mjds = np.sort(np.concatenate([60800 + rng.uniform(0, 10, 4), 60985 + rng.uniform(0, 10, 4),
                                   61170 + rng.uniform(0, 10, 4), 61355 + rng.uniform(0, 10, 4)]))
    sig = 0.6
    zs = []
    for _ in range(200):
        ra, dec = _simulate_track(ref, mjds, sig, rng)
        m = fit_motion(mjds, ra, dec, np.full(len(mjds), sig), np.full(len(mjds), sig), ref)
        assert m.ok
        zs += [m.z_pmra, m.z_pmdec]
    assert 0.85 < np.std(zs) < 1.15
    assert abs(np.mean(zs)) < 0.15


def test_static_source_not_flagged_as_moving():
    rng = np.random.default_rng(11)
    ref = AstrometricReference(30.0, -45.0, 2016.0, 0.0, 0.0)
    mjds = np.linspace(60800, 61350, 12)
    false = 0
    for _ in range(300):
        ra, dec = _simulate_track(ref, mjds, 0.5, rng)
        m = fit_motion(mjds, ra, dec, np.full(12, 0.5), np.full(12, 0.5), None)
        false += m.p_value_static < 1e-3
    assert false <= 3  # expected 0.3 at p<1e-3


def test_motion_fit_refuses_insufficient_data():
    m = fit_motion([60800, 60801], [1, 1], [1, 1], [1, 1], [1, 1], None)
    assert not m.ok
    m = fit_motion([60800, 60801, 60802], [1, 1, 1], [1, 1, 1], [1, 1, 1], [1, 1, 1], None)
    assert not m.ok and "span" in m.reason
