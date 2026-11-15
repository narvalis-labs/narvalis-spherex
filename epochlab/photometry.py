"""Forced aperture photometry and wavelength-matched variability statistics.

Why wavelength matching: each SPHEREx exposure samples a source at a wavelength set by where it
lands on the linear variable filter. Two epochs of the same source are generally at *different*
wavelengths, so a raw flux difference mixes spectral shape with temporal change. We only compare
epochs whose central wavelengths fall in the same narrow bin.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_area


@dataclass
class Photometry:
    ok: bool
    reason: str
    method: str = "aperture"
    flux_ujy: float | None = None
    flux_err_ujy: float | None = None
    background_mjysr: float | None = None
    n_aperture_pix: int | None = None
    n_bad_in_aperture: int | None = None
    zodi_subtracted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def pixel_solid_angle_sr(wcs: WCS) -> float:
    return float(proj_plane_pixel_area(wcs.celestial) * (np.pi / 180.0) ** 2)


def forced_aperture(image, variance, bad, zodi, wcs: WCS, x: float, y: float,
                    r: float = 2.0, annulus: tuple[float, float] = (4.0, 7.0),
                    max_bad_frac: float = 0.0) -> Photometry:
    """Sum of (image - zodi - local annulus median) in a circular aperture, in micro-Jansky.

    This is an *aperture* flux (no aperture correction): valid for relative comparisons of the same
    source at matched wavelength, not as an absolute total flux.
    """
    ny, nx = image.shape
    rr = annulus[1] + 1
    if not (rr <= x < nx - rr and rr <= y < ny - rr):
        return Photometry(False, "aperture too close to edge")
    yy, xx = np.mgrid[0:ny, 0:nx]
    d = np.hypot(xx - x, yy - y)
    ap = d <= r
    an = (d >= annulus[0]) & (d <= annulus[1])
    img = image - zodi if zodi is not None else image
    nbad = int((ap & bad).sum())
    if nbad > max_bad_frac * ap.sum():
        return Photometry(False, f"{nbad} flagged pixel(s) in aperture", n_bad_in_aperture=nbad,
                          n_aperture_pix=int(ap.sum()), zodi_subtracted=zodi is not None)
    bg_pix = img[an & ~bad]
    if bg_pix.size < 10:
        return Photometry(False, "too few good background pixels")
    bg = float(np.median(bg_pix))
    bg_err = 1.2533 * np.std(bg_pix) / np.sqrt(bg_pix.size)
    npx = int(ap.sum())
    s = float(np.sum(img[ap] - bg))
    if variance is not None:
        v = float(np.sum(variance[ap])) + (npx * bg_err) ** 2
    else:
        v = npx * float(np.var(bg_pix)) + (npx * bg_err) ** 2
    k = pixel_solid_angle_sr(wcs) * 1e12  # MJy/sr * sr -> uJy
    return Photometry(True, "ok", flux_ujy=s * k, flux_err_ujy=float(np.sqrt(v)) * k,
                      background_mjysr=bg, n_aperture_pix=npx, n_bad_in_aperture=nbad,
                      zodi_subtracted=zodi is not None)


def wavelength_bins(lams, rel_width: float) -> np.ndarray:
    """Assign each wavelength to a logarithmic bin of relative width `rel_width`. -1 for missing."""
    lams = np.asarray([np.nan if v is None else v for v in lams], float)
    out = np.full(lams.shape, -1, int)
    ok = np.isfinite(lams) & (lams > 0)
    out[ok] = np.floor(np.log(lams[ok]) / np.log1p(rel_width)).astype(int)
    return out


def psf_wing_flux(centroid, wcs: WCS, reason: str) -> Photometry:
    """Flux of a source whose core is flagged (e.g. saturated), from the Gaussian fitted to the unflagged
    wings: F = 2*pi*sigma^2*A. Less accurate than aperture photometry; labelled and compared only with itself."""
    a, s = centroid.amplitude, centroid.sigma_psf_px
    if not (a and s and centroid.amplitude_err and centroid.sigma_psf_err):
        return Photometry(False, reason)
    k = pixel_solid_angle_sr(wcs) * 1e12
    f = 2 * np.pi * s * s * a * k
    e = f * float(np.hypot(centroid.amplitude_err / a, 2 * centroid.sigma_psf_err / s))
    return Photometry(True, f"aperture rejected ({reason}); PSF-wing fit used", method="psf_wings",
                      flux_ujy=float(f), flux_err_ujy=e)


def variability_by_bin(lams, flux, err, rel_width: float, methods=None) -> dict:
    """Chi-square of a constant-flux model, computed separately inside each wavelength bin.

    Returns per-bin details and a combined statistic over bins with >=2 epochs.
    """
    from scipy.stats import chi2 as chi2dist

    lams = np.asarray([np.nan if v is None else v for v in lams], float)
    flux = np.asarray([np.nan if v is None else v for v in flux], float)
    err = np.asarray([np.nan if v is None else v for v in err], float)
    bins = wavelength_bins(lams, rel_width)
    methods = np.asarray(methods if methods is not None else ["aperture"] * len(bins), dtype=object)
    per = []
    tot_chi, tot_dof = 0.0, 0
    keys = sorted({(b, m) for b, m in zip(bins.tolist(), methods.tolist()) if b != -1}, key=lambda k: (k[0], str(k[1])))
    for b, meth in keys:
        sel = (bins == b) & (methods == meth) & np.isfinite(flux) & np.isfinite(err) & (err > 0)
        if sel.sum() < 2:
            continue
        f, e = flux[sel], err[sel]
        w = 1 / e ** 2
        mu = float(np.sum(w * f) / np.sum(w))
        c = float(np.sum(((f - mu) / e) ** 2))
        dof = int(sel.sum() - 1)
        tot_chi += c
        tot_dof += dof
        per.append({
            "bin": int(b), "method": meth, "lambda_um_min": float(lams[sel].min()), "lambda_um_max": float(lams[sel].max()),
            "n": int(sel.sum()), "weighted_mean_ujy": mu, "chi2": c, "dof": dof,
            "p_value": float(chi2dist.sf(c, dof)),
            "max_over_min": float(f.max() / f.min()) if f.min() > 0 else None,
        })
    return {
        "bin_rel_width": rel_width,
        "bins": per,
        "combined_chi2": tot_chi if tot_dof else None,
        "combined_dof": tot_dof,
        "combined_p_value": float(chi2dist.sf(tot_chi, tot_dof)) if tot_dof else None,
    }
