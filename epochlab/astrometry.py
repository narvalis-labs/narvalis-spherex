"""Epoch propagation, PSF centroiding and proper-motion fitting.

Conventions
- Proper motions in mas/yr; pmra is mu_alpha* = mu_alpha cos(dec) (Gaia convention).
- Times in MJD (UTC) at the interface; Julian years internally.
- Predicted positions are *astrometric* geocentric directions (proper motion + space motion +
  annual parallax, no aberration), matching an image WCS calibrated against astrometric catalogues.
  SPHEREx is in low-Earth orbit; the orbit's parallax contribution (<1e-4 of annual) is neglected.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, Distance, get_body_barycentric
from astropy.time import Time
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from scipy.optimize import least_squares
from scipy.special import erf

# PSF model and detection test of fit_centroid (recorded in every dossier through Settings).
#  "pixel": circular Gaussian integrated over each pixel's area. SPHEREx pixels (6.2") are about as wide as the
#           PSF core, so sampling the Gaussian at pixel centres (the "point" model) biases the centroid towards
#           the pixel centre (pixel-phase error) and misfits bright stars.
#  detection "hybrid": "dchi2" when the core is saturated (>=3 flagged pixels within 1.5 px), else "amplitude",
#           so faint targets keep the conservative test while saturated bright stars are no longer rejected.
#  detection "dchi2": the source is detected if a point source improves the fit of the stamp over an empty
#           (constant) stamp by sqrt(delta chi2) >= min_snr. This is the likelihood-ratio detection test. The
#           older "amplitude" test (peak / its error, after chi2 inflation) wrongly rejects saturated stars,
#           whose masked core leaves the peak height undetermined while the position stays well measured.

MAS = 1e-3  # arcsec


@dataclass
class AstrometricReference:
    """Catalogue astrometry of the target. `source` says where it came from (e.g. 'Gaia DR3 <id>')."""
    ra_deg: float
    dec_deg: float
    epoch_jyear: float              # e.g. 2016.0 for Gaia DR3, 2000.0 for SIMBAD positions
    pmra_masyr: float
    pmdec_masyr: float
    parallax_mas: float | None = None
    rv_kms: float | None = None
    source: str = "unspecified"
    pmra_err: float | None = None
    pmdec_err: float | None = None
    pm_known: bool = True           # False if the resolver returned no proper motion (never silently 0)

    def to_dict(self) -> dict:
        return asdict(self)


def _coord(ref: AstrometricReference, with_distance: bool = True) -> SkyCoord:
    plx = ref.parallax_mas if (ref.parallax_mas and ref.parallax_mas > 0) else None
    dist = Distance(parallax=plx * u.mas) if (plx and with_distance) else 1e6 * u.pc
    return SkyCoord(
        ra=ref.ra_deg * u.deg, dec=ref.dec_deg * u.deg, distance=dist,
        pm_ra_cosdec=ref.pmra_masyr * u.mas / u.yr, pm_dec=ref.pmdec_masyr * u.mas / u.yr,
        radial_velocity=(ref.rv_kms or 0.0) * u.km / u.s,
        obstime=Time(ref.epoch_jyear, format="jyear", scale="tcb"), frame="icrs",
    )


def predict_position(ref: AstrometricReference, mjd: float, include_parallax: bool = True) -> tuple[float, float]:
    """Astrometric (RA, Dec) in deg of the target as seen from the geocentre at `mjd` (UTC)."""
    t = Time(mjd, format="mjd", scale="utc")
    moved = _coord(ref).apply_space_motion(new_obstime=t)
    if not (include_parallax and ref.parallax_mas and ref.parallax_mas > 0):
        return float(moved.ra.deg), float(moved.dec.deg)
    star = moved.cartesian.xyz.to(u.au).value
    earth = get_body_barycentric("earth", t).xyz.to(u.au).value
    v = star - earth
    v /= np.linalg.norm(v)
    ra = np.degrees(np.arctan2(v[1], v[0])) % 360.0
    dec = np.degrees(np.arcsin(v[2]))
    return float(ra), float(dec)


def predict_positions(ref: AstrometricReference, mjds, include_parallax: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised predict_position for many epochs of one star (one astropy call instead of one per epoch)."""
    mjds = np.atleast_1d(np.asarray(mjds, float))
    t = Time(mjds, format="mjd", scale="utc")
    moved = _coord(ref).apply_space_motion(new_obstime=t)
    if not (include_parallax and ref.parallax_mas and ref.parallax_mas > 0):
        return np.asarray(moved.ra.deg, float), np.asarray(moved.dec.deg, float)
    star = moved.cartesian.xyz.to(u.au).value.T                    # (n, 3)
    earth = get_body_barycentric("earth", t).xyz.to(u.au).value.T  # (n, 3)
    v = star - earth
    v /= np.linalg.norm(v, axis=1)[:, None]
    return np.degrees(np.arctan2(v[:, 1], v[:, 0])) % 360.0, np.degrees(np.arcsin(v[:, 2]))


def tangent_offsets(ra, dec, ra0: float, dec0: float):
    """Gnomonic offsets (xi, eta) in arcsec of (ra, dec) [deg] about (ra0, dec0)."""
    ra, dec = np.radians(np.asarray(ra, float)), np.radians(np.asarray(dec, float))
    a0, d0 = np.radians(ra0), np.radians(dec0)
    cosc = np.sin(d0) * np.sin(dec) + np.cos(d0) * np.cos(dec) * np.cos(ra - a0)
    xi = np.cos(dec) * np.sin(ra - a0) / cosc
    eta = (np.cos(d0) * np.sin(dec) - np.sin(d0) * np.cos(dec) * np.cos(ra - a0)) / cosc
    return np.degrees(xi) * 3600.0, np.degrees(eta) * 3600.0


def pixel_scale_arcsec(wcs: WCS) -> float:
    return float(np.mean(proj_plane_pixel_scales(wcs.celestial)) * 3600.0)


# --------------------------------------------------------------------------- centroiding
@dataclass
class Centroid:
    ok: bool
    reason: str
    x: float | None = None
    y: float | None = None
    sx: float | None = None
    sy: float | None = None
    ra_deg: float | None = None
    dec_deg: float | None = None
    sigma_ra_arcsec: float | None = None   # along RA* (great-circle)
    sigma_dec_arcsec: float | None = None
    amplitude: float | None = None
    amplitude_err: float | None = None
    snr: float | None = None
    sigma_psf_px: float | None = None
    sigma_psf_err: float | None = None
    reduced_chi2: float | None = None
    n_pix: int | None = None
    snr_amplitude: float | None = None     # peak / its (chi2-inflated) error
    snr_detection: float | None = None     # sqrt(chi2(empty stamp) - chi2(point source))
    psf_model: str | None = None
    core_flagged_px: int | None = None      # flagged pixels within 1.5 px of the centroid (saturation)
    n_neighbours_fitted: int | None = None  # known (Gaia) neighbours fitted simultaneously at fixed positions

    def to_dict(self) -> dict:
        return asdict(self)


def fit_centroid(image: np.ndarray, variance: np.ndarray | None, bad: np.ndarray, wcs: WCS,
                 x0: float, y0: float, half: int = 5, min_snr: float = 5.0,
                 floor_arcsec: float = 0.0, psf_model: str | None = None,
                 detection: str | None = None, neighbours=None) -> Centroid:
    """Variance-weighted circular-Gaussian + constant fit in a (2*half+1)^2 stamp around (x0, y0).

    The Gaussian approximates the SPHEREx PSF core (undersampled, ~6.2"/px). Pixel uncertainties come
    from the VARIANCE plane; parameter covariance is inflated by max(1, reduced chi2).
    """
    ny, nx = image.shape
    xi, yi = int(round(x0)), int(round(y0))
    if not (half <= xi < nx - half and half <= yi < ny - half):
        return Centroid(False, "predicted position too close to image edge")
    sl = (slice(yi - half, yi + half + 1), slice(xi - half, xi + half + 1))
    data = image[sl]
    m = ~bad[sl]
    if variance is not None:
        var = variance[sl]
    else:
        good = data[m]
        mad = np.median(np.abs(good - np.median(good))) * 1.4826 if good.size else np.nan
        var = np.full_like(data, mad ** 2)
    m &= np.isfinite(var) & (var > 0) & np.isfinite(data)
    if m.sum() < 12:
        return Centroid(False, f"too few good pixels in stamp ({int(m.sum())})")
    yy, xx = np.mgrid[sl]
    X, Y, D, W = xx[m].astype(float), yy[m].astype(float), data[m], 1.0 / np.sqrt(var[m])

    b0 = float(np.median(D))
    a0 = float(max(D.max() - b0, 1e-12))
    p0 = np.array([a0, x0, y0, 1.0, b0])

    from .config import settings as _st
    psf_model = psf_model or getattr(_st, "psf_model", "point")
    detection = detection or getattr(_st, "detection_test", "amplitude")

    if psf_model == "pixel":
        def shape(xc, yc, s):
            k = 1.0 / (np.sqrt(2.0) * s)
            gx = (erf((X + 0.5 - xc) * k) - erf((X - 0.5 - xc) * k)) * (s * np.sqrt(np.pi / 2.0))
            gy = (erf((Y + 0.5 - yc) * k) - erf((Y - 0.5 - yc) * k)) * (s * np.sqrt(np.pi / 2.0))
            return gx * gy          # integral over the pixel of a unit-peak Gaussian
    elif psf_model == "ellip":
        # elongated Gaussian with ellipticity components (e1, e2) as the last two parameters (shared by all
        # sources in the stamp): no degeneracy for a round star, unlike (axis ratio, angle)
        def shape(xc, yc, s, e1=0.0, e2=0.0):
            dx, dy = X - xc, Y - yc
            return np.exp(-0.5 * ((1 + e1) * dx * dx + 2 * e2 * dx * dy + (1 - e1) * dy * dy) / (s * s))
    else:
        def shape(xc, yc, s):
            return np.exp(-((X - xc) ** 2 + (Y - yc) ** 2) / (2 * s * s))

    # Known neighbours (e.g. Gaia stars propagated to this epoch): fixed positions, free non-negative amplitudes,
    # same PSF width as the target. They are fitted together with the target, so a blend cannot pull the centroid.
    nb = [(float(nx), float(ny)) for nx, ny in (neighbours or [])
          if xi - half - 3 <= nx <= xi + half + 3 and yi - half - 3 <= ny <= yi + half + 3]
    k = len(nb)

    ell = psf_model == "ellip"

    def model(p):
        a, xc, yc, s, b = p[:5]
        ex = (p[5 + k], p[6 + k]) if ell else ()
        m = a * shape(xc, yc, s, *ex) + b
        for j, (nx, ny) in enumerate(nb):
            m = m + p[5 + j] * shape(nx, ny, s, *ex)
        return m

    def resid(p):
        return (D - model(p)) * W

    lo = [0.0, xi - half, yi - half, 0.3, -np.inf] + [0.0] * k
    hi = [np.inf, xi + half, yi + half, 4.0, np.inf] + [np.inf] * k
    if k:
        p0 = np.concatenate([p0, np.full(k, 0.5 * a0)])
    if ell:
        p0 = np.concatenate([p0, [0.0, 0.0]])
        lo += [-0.6, -0.6]
        hi += [0.6, 0.6]
    try:
        res = least_squares(resid, p0, bounds=(lo, hi), x_scale="jac")
    except Exception as exc:  # noqa: BLE001
        return Centroid(False, f"fit failed: {exc}")
    dof = max(len(D) - 5 - k - (2 if ell else 0), 1)
    chi2_fit = float(np.sum(res.fun ** 2))
    rchi2 = chi2_fit / dof
    w2 = W ** 2
    if k:   # null hypothesis: background + the known neighbours, no target
        def rnull(q):
            pp = np.concatenate([[0.0, res.x[1], res.x[2], res.x[3]], q, res.x[5 + k:]])
            return resid(pp)
        rn = least_squares(rnull, np.concatenate([[res.x[4]], res.x[5:5 + k]]),
                           bounds=([-np.inf] + [0.0] * k, [np.inf] * (k + 1)))
        chi2_null = float(np.sum(rn.fun ** 2))
    else:
        b_null = float(np.sum(w2 * D) / np.sum(w2))
        chi2_null = float(np.sum(((D - b_null) * W) ** 2))
    snr_det = float(np.sqrt(max(0.0, chi2_null - chi2_fit)))
    try:
        cov = np.linalg.inv(res.jac.T @ res.jac) * max(1.0, rchi2)
        perr = np.sqrt(np.diag(cov))
    except np.linalg.LinAlgError:
        return Centroid(False, "singular covariance")
    if not np.all(np.isfinite(perr[:4])):
        return Centroid(False, "singular covariance (non-finite errors)")
    a, xc, yc, s, b = res.x[:5]
    snr_amp = float(a / perr[0]) if perr[0] > 0 else 0.0
    # saturated core: >=3 flagged pixels within 1.5 px of the fitted centre (a cosmic ray flags 1-2 pixels)
    yy0, xx0 = np.mgrid[sl]
    core_flagged = int(np.sum(bad[sl] & (np.hypot(xx0 - res.x[1], yy0 - res.x[2]) <= 1.5)))
    if detection == "dchi2" or (detection == "hybrid" and core_flagged >= 3):
        snr = snr_det
    else:
        snr = snr_amp
    out = Centroid(False, "", x=float(xc), y=float(yc), sx=float(perr[1]), sy=float(perr[2]),
                   amplitude=float(a), amplitude_err=float(perr[0]), snr=snr, sigma_psf_px=float(s),
                   sigma_psf_err=float(perr[3]), reduced_chi2=rchi2, n_pix=int(len(D)),
                   snr_amplitude=snr_amp, snr_detection=snr_det, psf_model=psf_model,
                   core_flagged_px=core_flagged, n_neighbours_fitted=k)
    if not res.success:
        out.reason = "optimizer did not converge"
        return out
    if snr < min_snr:
        out.reason = f"S/N {snr:.1f} below threshold {min_snr}"
        return out
    if snr is snr_det and max(perr[1], perr[2]) > 0.5:
        out.reason = f"position undetermined (error {max(perr[1], perr[2]):.2f} px)"
        return out
    if np.hypot(xc - x0, yc - y0) > half - 1:
        out.reason = "centroid ran to stamp edge"
        return out
    sky = wcs.pixel_to_world(xc, yc)
    # Convert pixel errors to sky errors using the local Jacobian of the WCS.
    eps = 0.5
    r1, d1 = tangent_offsets(*_pix2deg(wcs, xc + eps, yc), sky.ra.deg, sky.dec.deg)
    r2, d2 = tangent_offsets(*_pix2deg(wcs, xc, yc + eps), sky.ra.deg, sky.dec.deg)
    J = np.array([[r1, r2], [d1, d2]]) / eps  # arcsec per pixel
    C_sky = J @ cov[1:3, 1:3] @ J.T
    out.ok, out.reason = True, "ok"
    out.ra_deg, out.dec_deg = float(sky.ra.deg), float(sky.dec.deg)
    out.sigma_ra_arcsec = float(np.sqrt(C_sky[0, 0] + floor_arcsec ** 2))
    out.sigma_dec_arcsec = float(np.sqrt(C_sky[1, 1] + floor_arcsec ** 2))
    return out


def _pix2deg(wcs: WCS, x: float, y: float) -> tuple[float, float]:
    c = wcs.pixel_to_world(x, y)
    return float(c.ra.deg), float(c.dec.deg)


# --------------------------------------------------------------------------- motion fitting
@dataclass
class MotionFit:
    ok: bool
    reason: str
    n_epochs: int = 0
    time_span_yr: float = 0.0
    pmra_masyr: float | None = None
    pmdec_masyr: float | None = None
    pmra_err: float | None = None
    pmdec_err: float | None = None
    reduced_chi2_linear: float | None = None
    # Consistency of measured positions with the catalogue prediction (incl. parallax)
    chi2_vs_reference: float | None = None
    dof_vs_reference: int | None = None
    p_value_vs_reference: float | None = None
    # Measured vs catalogue proper motion
    z_pmra: float | None = None
    z_pmdec: float | None = None
    error_scale: float | None = None   # sqrt(max(1, reduced chi2)) applied to the PM errors (Birge ratio)
    # Motion significance: is the source moving at all? (chi2 of a static model)
    chi2_static: float | None = None
    p_value_static: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def fit_motion(mjd, ra, dec, sig_ra, sig_dec, ref: AstrometricReference | None) -> MotionFit:
    """Weighted linear fit of position vs time in the tangent plane.

    If `ref` has a parallax, the predicted parallactic displacement is removed before the linear fit,
    so the fitted slope is a proper motion directly comparable with the catalogue value.
    """
    from scipy.stats import chi2 as chi2dist

    mjd = np.asarray(mjd, float)
    n = len(mjd)
    if n < 3:
        return MotionFit(False, f"need >=3 good epochs, have {n}", n_epochs=n)
    t = Time(mjd, format="mjd", scale="utc").jyear
    span = float(t.max() - t.min())
    if span < 0.1:
        return MotionFit(False, f"time span {span:.3f} yr too short", n_epochs=n, time_span_yr=span)
    ra0, dec0 = float(np.mean(ra)), float(np.mean(dec))
    xi, eta = tangent_offsets(ra, dec, ra0, dec0)
    sx, sy = np.asarray(sig_ra, float), np.asarray(sig_dec, float)

    # Parallax correction from the reference (if any)
    px_xi = np.zeros(n)
    px_eta = np.zeros(n)
    pred_xi = pred_eta = None
    if ref is not None:
        pw = np.column_stack(predict_positions(ref, mjd, True))
        pn = np.column_stack(predict_positions(ref, mjd, False))
        a, b = tangent_offsets(pw[:, 0], pw[:, 1], ra0, dec0)
        c, d = tangent_offsets(pn[:, 0], pn[:, 1], ra0, dec0)
        px_xi, px_eta = a - c, b - d
        pred_xi, pred_eta = a, b

    tm = t - np.average(t, weights=1 / sx ** 2)

    def wfit(y, s):
        A = np.vstack([np.ones(n), tm]).T
        Wt = 1 / s ** 2
        cov = np.linalg.inv(A.T @ (A * Wt[:, None]))
        p = cov @ (A.T @ (Wt * y))
        r = (y - A @ p) / s
        return p, cov, float(np.sum(r ** 2))

    p1, c1, chi_x = wfit(xi - px_xi, sx)
    p2, c2, chi_y = wfit(eta - px_eta, sy)
    dof_lin = 2 * n - 4
    rchi = float((chi_x + chi_y) / max(dof_lin, 1))
    scale = float(np.sqrt(max(1.0, rchi)))   # if the scatter exceeds the errors, do not trust the errors
    out = MotionFit(True, "ok", n_epochs=n, time_span_yr=span,
                    pmra_masyr=float(p1[1] / MAS), pmdec_masyr=float(p2[1] / MAS),
                    pmra_err=float(np.sqrt(c1[1, 1]) / MAS * scale), pmdec_err=float(np.sqrt(c2[1, 1]) / MAS * scale),
                    reduced_chi2_linear=rchi, error_scale=scale)

    # Static model: weighted mean position only
    def static_chi(y, s):
        w = 1 / s ** 2
        mu = np.sum(w * y) / np.sum(w)
        return float(np.sum(((y - mu) / s) ** 2))
    cs = static_chi(xi - px_xi, sx) + static_chi(eta - px_eta, sy)
    out.chi2_static = cs
    out.p_value_static = float(chi2dist.sf(cs, 2 * n - 2))

    if ref is not None:
        # Allow a free constant offset (catalogue/WCS zero-point), test the shape of the trajectory.
        rx, ry = xi - pred_xi, eta - pred_eta
        cr = static_chi(rx, sx) + static_chi(ry, sy)
        out.chi2_vs_reference = cr
        out.dof_vs_reference = 2 * n - 2
        out.p_value_vs_reference = float(chi2dist.sf(cr, 2 * n - 2))
        e1 = np.hypot(out.pmra_err, ref.pmra_err or 0.0)
        e2 = np.hypot(out.pmdec_err, ref.pmdec_err or 0.0)
        out.z_pmra = float((out.pmra_masyr - ref.pmra_masyr) / e1)
        out.z_pmdec = float((out.pmdec_masyr - ref.pmdec_masyr) / e2)
    return out


# --------------------------------------------------------------------------- parallax (5-parameter fit)
def parallax_factors(mjd, ra_deg: float, dec_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Displacement (arcsec along RA*, Dec) per 1 mas of parallax at each epoch, from the Earth's barycentric
    position (SPHEREx's low-Earth orbit adds < 1e-4 of the annual term)."""
    t = Time(np.atleast_1d(np.asarray(mjd, float)), format="mjd", scale="utc")
    X, Y, Z = get_body_barycentric("earth", t).xyz.to(u.au).value
    a, d = np.radians(ra_deg), np.radians(dec_deg)
    fx = X * np.sin(a) - Y * np.cos(a)
    fy = X * np.cos(a) * np.sin(d) + Y * np.sin(a) * np.sin(d) - Z * np.cos(d)
    return fx * MAS, fy * MAS


def fit_parallax(mjd, ra, dec, sig_ra, sig_dec, ref: AstrometricReference | None = None) -> dict:
    """Weighted 5-parameter astrometric fit: offset (2), proper motion (2) and parallax, from SPHEREx alone.

    The catalogue parallax is NOT used; it is only compared with afterwards. Errors are scaled by
    sqrt(max(1, reduced chi2)). Returns a plain dict (stored in the dossier as results.motion.parallax_fit).
    """
    mjd = np.asarray(mjd, float)
    n = len(mjd)
    if n < 8:
        return {"ok": False, "reason": f"needs >= 8 epochs, have {n}", "n_epochs": n}
    t = Time(mjd, format="mjd", scale="utc").jyear
    span = float(t.max() - t.min())
    ra0, dec0 = float(np.mean(ra)), float(np.mean(dec))
    xi, eta = tangent_offsets(ra, dec, ra0, dec0)
    sx, sy = np.asarray(sig_ra, float), np.asarray(sig_dec, float)
    fx, fy = parallax_factors(mjd, ra0, dec0)
    # the annual ellipse must be sampled: the parallax factors must vary by > 0.5 AU over the epochs
    if span < 0.4 or max(np.ptp(fx), np.ptp(fy)) / MAS < 0.5:
        return {"ok": False, "reason": f"epochs do not sample the annual parallax ellipse (span {span:.2f} yr)",
                "n_epochs": n, "time_span_yr": span}
    tm = t - t.mean()
    M = np.zeros((2 * n, 5))
    M[:n, 0] = 1; M[n:, 1] = 1; M[:n, 2] = tm; M[n:, 3] = tm; M[:n, 4] = fx; M[n:, 4] = fy
    y = np.concatenate([xi, eta]); s = np.concatenate([sx, sy]); w = 1 / s ** 2
    try:
        C = np.linalg.inv(M.T @ (M * w[:, None]))
    except np.linalg.LinAlgError:
        return {"ok": False, "reason": "degenerate epochs (parallax and motion not separable)", "n_epochs": n}
    q = C @ (M.T @ (w * y))
    r = (y - M @ q) / s
    dof = 2 * n - 5
    rchi = float(r @ r / dof)
    scale = float(np.sqrt(max(1.0, rchi)))
    e = np.sqrt(np.diag(C)) * scale
    plx, plx_err = float(q[4]), float(e[4])   # parallax column is in arcsec per mas, so q[4] is in mas
    out = {"ok": True, "reason": "ok", "n_epochs": n, "time_span_yr": span,
           "parallax_mas": plx, "parallax_err_mas": plx_err, "significance": plx / plx_err if plx_err > 0 else 0.0,
           "pmra_masyr": float(q[2] / MAS), "pmdec_masyr": float(q[3] / MAS),
           "pmra_err": float(e[2] / MAS), "pmdec_err": float(e[3] / MAS),
           "reduced_chi2": rchi, "error_scale": scale,
           "corr_parallax_pm": [float(C[4, 2] / np.sqrt(C[4, 4] * C[2, 2])), float(C[4, 3] / np.sqrt(C[4, 4] * C[3, 3]))],
           "distance_pc": (1000.0 / plx) if plx > 3 * plx_err else None,
           "distance_pc_range_1sigma": ([1000.0 / (plx + plx_err), 1000.0 / (plx - plx_err)]
                                        if plx > 3 * plx_err else None),
           "distance_lower_limit_pc_3sigma": (1000.0 / (max(plx, 0.0) + 3 * plx_err)) if plx <= 3 * plx_err else None}
    # Plot data: parallax-only residuals (offset and proper motion removed), averaged per visit (gap > 10 d),
    # and the unit parallax ellipse over one year (mas of displacement per mas of parallax).
    rx = (xi - q[0] - q[2] * tm) / MAS
    ry = (eta - q[1] - q[3] * tm) / MAS
    vis = np.cumsum(np.r_[0, np.diff(np.sort(mjd)) > 10.0])
    order = np.argsort(mjd)
    bins = []
    for v in np.unique(vis):
        ii = order[vis == v]
        wx, wy = 1 / sx[ii] ** 2, 1 / sy[ii] ** 2
        bins.append([float(np.mean(mjd[ii])), float(np.sum(wx * rx[ii]) / np.sum(wx)), float(np.sum(wy * ry[ii]) / np.sum(wy)),
                     float(scale / np.sqrt(np.sum(wx)) / MAS), float(scale / np.sqrt(np.sum(wy)) / MAS), int(len(ii))])
    tt = float(mjd.min()) + np.arange(0, 366, 4.0)
    ux, uy = parallax_factors(tt, ra0, dec0)
    out["plot"] = {"visits": bins, "unit_ellipse": [[float(a / MAS), float(b / MAS)] for a, b in zip(ux, uy)],
                   "note": "visits: [mjd, dRA* mas, dDec mas, err RA*, err Dec, n]; ellipse x parallax = expected track"}
    if ref is not None and ref.parallax_mas is not None:
        ez = np.hypot(plx_err, 0.0)
        out["catalogue_parallax_mas"] = float(ref.parallax_mas)
        out["z_vs_catalogue"] = float((plx - ref.parallax_mas) / ez)
    return out
