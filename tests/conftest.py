"""SYNTHETIC test fixtures. These files mimic the *structure* of SPHEREx L2 MEF cutouts
(IMAGE/FLAGS/VARIANCE/ZODI/WCS-WAVE) so that the code path can be tested offline.
They are NOT astronomical data and are never used by the application at runtime.
"""
from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

PIX = 6.15  # arcsec / pixel (SPHEREx plate scale)
FLAG_BITS = {"SATURATED": 1, "NONFUNC": 2, "SOURCE": 21, "TRANSIENT": 4}


def celestial_wcs(ra, dec, n, rot_deg, pix=PIX, crpix_off=(0.0, 0.0)):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2 + crpix_off[0], (n + 1) / 2 + crpix_off[1]]
    c, s = np.cos(np.radians(rot_deg)), np.sin(np.radians(rot_deg))
    d = pix / 3600.0
    w.wcs.cd = np.array([[-d * c, d * s], [d * s, d * c]])
    w.wcs.radesys = "ICRS"
    return w


def make_mef(path, ra0, dec0, mjd, sources, n=25, rot_deg=0.0, noise=1.0, lam0=1.5, dlam_dy=0.004,
             sigma_px=1.0, zodi=5.0, saturate=None, rng=None, write_time_header=True, wcs_error_arcsec=(0.0, 0.0)):
    """sources: list of (ra, dec, amplitude). Wavelength varies along detector y (like an LVF).
    wcs_error_arcsec simulates a per-exposure astrometric zero-point error: every source lands shifted
    by this amount relative to what the WCS says (as seen in real SPHEREx exposures)."""
    rng = rng or np.random.default_rng(0)
    w = celestial_wcs(ra0, dec0, n, rot_deg, crpix_off=tuple(rng.uniform(-0.5, 0.5, 2)))
    yy, xx = np.mgrid[0:n, 0:n]
    img = np.full((n, n), zodi, float)
    for ra, dec, amp in sources:
        dec_s = dec + wcs_error_arcsec[1] / 3600.0
        ra_s = ra + wcs_error_arcsec[0] / 3600.0 / np.cos(np.radians(dec))
        x, y = w.world_to_pixel_values(ra_s, dec_s)
        img += amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma_px ** 2))
    var = np.full((n, n), noise ** 2)
    img += rng.normal(0, noise, img.shape)
    flags = np.zeros((n, n), np.int32)
    if saturate is not None:
        sx, sy = saturate
        flags[sy, sx] |= 1 << FLAG_BITS["SATURATED"]
        img[sy, sx] = np.nan
    h = w.to_header()
    if write_time_header:
        h["MJD-AVG"] = mjd
    h["DETECTOR"] = 1
    # spectral WCS 'W' as a 2-D -TAB lookup (same mechanism as SPHEREx L2)
    K = 6
    xs = np.linspace(0, n + 1, K)
    ys = np.linspace(0, n + 1, K)
    X, Y = np.meshgrid(xs, ys)
    lam = lam0 + dlam_dy * Y
    bw = lam / 40.0
    coords = np.stack([lam, bw], -1)[None].astype("f4")
    tab = fits.BinTableHDU.from_columns([
        fits.Column(name="VALUES", format=f"{K * K * 2}E", dim=f"(2,{K},{K})", array=coords),
        fits.Column(name="X", format=f"{K}E", array=xs[None].astype("f4")),
        fits.Column(name="Y", format=f"{K}E", array=ys[None].astype("f4")),
    ], name="WCS-WAVE")
    for i, idx in ((1, "X"), (2, "Y")):
        h[f"CTYPE{i}W"] = "WAVE-TAB"
        h[f"CUNIT{i}W"] = "um"
        h[f"CRPIX{i}W"] = 0.0
        h[f"CRVAL{i}W"] = 0.0
        h[f"CDELT{i}W"] = 1.0
        h[f"PS{i}_0W"] = "WCS-WAVE"
        h[f"PS{i}_1W"] = "VALUES"
        h[f"PS{i}_2W"] = idx
        h[f"PV{i}_3W"] = i
    h["WCSAXESW"] = 2
    fh = fits.Header()
    for k, b in FLAG_BITS.items():
        fh[f"MP_{k}"] = b
    hdul = fits.HDUList([
        fits.PrimaryHDU(),
        fits.ImageHDU(img.astype("f4"), header=h, name="IMAGE"),
        fits.ImageHDU(flags, header=fh, name="FLAGS"),
        fits.ImageHDU(var.astype("f4"), name="VARIANCE"),
        fits.ImageHDU(np.full((n, n), zodi, "f4"), name="ZODI"),
        tab,
    ])
    hdul.writeto(path, overwrite=True)
    return path


@pytest.fixture
def mef_factory(tmp_path):
    counter = {"i": 0}

    def _make(**kw):
        counter["i"] += 1
        return make_mef(tmp_path / f"synthetic_{counter['i']:04d}.fits", **kw)
    return _make
