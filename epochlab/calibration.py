"""Differential (field-star) calibration of every exposure.

Real SPHEREx data showed per-exposure astrometric errors that dominate the formal centroid errors
(static stars appeared to move by hundreds of mas/yr; reduced chi2 >> 1). The standard remedy is
differential astrometry: in each exposure, measure Gaia DR3 stars of the same field, compare with their
catalogue positions propagated to that epoch, and subtract the exposure's mean offset from the target.
The scatter of the field stars after correction gives an empirical systematic error floor, and the same
stars, measured with leave-one-out corrections, are the false-positive controls.

Photometry uses the same stars: the scatter of their fluxes within wavelength bins gives an empirical
fractional error floor for the variability test.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .astrometry import AstrometricReference, predict_position, fit_centroid, tangent_offsets, fit_motion, fit_parallax
from .photometry import forced_aperture, wavelength_bins


class FieldPropagator:
    """Vectorised epoch propagation (proper motion + parallax + RV) of all field stars at once.
    Equivalent to astrometry.predict_position, but one astropy call per exposure instead of one per star."""

    def __init__(self, refs: list[AstrometricReference]):
        import astropy.units as u
        from astropy.coordinates import SkyCoord, Distance
        from astropy.time import Time
        self.refs = refs
        if not refs:
            return
        plx = np.array([r.parallax_mas if (r.parallax_mas and r.parallax_mas > 0.05) else np.nan for r in refs])
        self.has_plx = np.isfinite(plx)
        dist = np.where(self.has_plx, 1000.0 / np.where(self.has_plx, plx, 1.0), 1e5) * u.pc
        epochs = {r.epoch_jyear for r in refs}
        if len(epochs) != 1:
            raise ValueError("field stars must share one reference epoch")
        self.c = SkyCoord(ra=[r.ra_deg for r in refs] * u.deg, dec=[r.dec_deg for r in refs] * u.deg,
                          distance=dist, pm_ra_cosdec=[r.pmra_masyr for r in refs] * u.mas / u.yr,
                          pm_dec=[r.pmdec_masyr for r in refs] * u.mas / u.yr,
                          radial_velocity=[r.rv_kms or 0.0 for r in refs] * u.km / u.s,
                          obstime=Time(epochs.pop(), format="jyear", scale="tcb"), frame="icrs")

    def at(self, mjd: float) -> tuple[np.ndarray, np.ndarray]:
        import astropy.units as u
        from astropy.coordinates import get_body_barycentric
        from astropy.time import Time
        if not self.refs:
            return np.zeros(0), np.zeros(0)
        t = Time(mjd, format="mjd", scale="utc")
        m = self.c.apply_space_motion(new_obstime=t)
        xyz = m.cartesian.xyz.to(u.au).value.T                     # (n, 3)
        earth = get_body_barycentric("earth", t).xyz.to(u.au).value
        v = np.where(self.has_plx[:, None], xyz - earth, xyz)      # no parallax shift without a parallax
        v /= np.linalg.norm(v, axis=1)[:, None]
        return np.degrees(np.arctan2(v[:, 1], v[:, 0])) % 360.0, np.degrees(np.arcsin(v[:, 2]))


@dataclass
class StarMeas:
    star: int
    dxi: float      # measured - predicted, arcsec (tangent plane at predicted position)
    deta: float
    sx: float       # formal errors, arcsec
    sy: float
    flux: float | None = None
    flux_err: float | None = None
    pra: float = 0.0     # predicted position used (deg)
    pdec: float = 0.0


@dataclass
class FrameCal:
    n: int = 0
    ok: bool = False
    off_xi: float = 0.0
    off_eta: float = 0.0
    err_xi: float = 0.0
    err_eta: float = 0.0
    stars: list[StarMeas] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "n_stars": self.n, "offset_arcsec": [self.off_xi, self.off_eta],
                "offset_err_arcsec": [self.err_xi, self.err_eta]}


def field_references(ra: float, dec: float, radius_arcsec: float, target: AstrometricReference | None,
                     gmax: float = 18.5, top: int = 600, exclude_arcsec: float = 8.0,
                     max_stars: int = 120) -> list[AstrometricReference]:
    """Gaia DR3 stars (with full astrometry) in the cutout, excluding the target itself."""
    from .references import gaia_cone, _from_gaia_row
    tab, _ = gaia_cone(ra, dec, radius_arcsec, top=top)
    if target is not None:
        from astropy.time import Time
        t_ra, t_dec = predict_position(target, Time(2016.0, format="jyear", scale="tcb").utc.mjd, False)
    else:
        t_ra, t_dec = ra, dec
    out = []
    for r in tab:
        if np.ma.is_masked(r["pmra"]) or np.ma.is_masked(r["phot_g_mean_mag"]) or float(r["phot_g_mean_mag"]) > gmax:
            continue
        sep = np.hypot((float(r["ra"]) - t_ra) * np.cos(np.radians(t_dec)), float(r["dec"]) - t_dec) * 3600
        if sep < exclude_arcsec:
            continue
        out.append(_from_gaia_row(r))
        if len(out) >= max_stars:   # brightest first (query is ordered by G); plenty for a robust offset
            break
    return out


def _robust_mean(v, s, extra=0.0):
    """Sigma-clipped weighted mean; returns (mean, error, kept_mask)."""
    v, s = np.asarray(v, float), np.asarray(s, float)
    keep = np.ones(len(v), bool)
    for _ in range(3):
        if keep.sum() < 3:
            break
        med = np.median(v[keep])
        mad = 1.4826 * np.median(np.abs(v[keep] - med)) or np.median(s[keep])
        keep = np.abs(v - med) <= 3 * max(mad, 1e-6)
    w = 1 / (s[keep] ** 2 + extra ** 2)
    m = float(np.sum(w * v[keep]) / np.sum(w))
    chi = float(np.sum(w * (v[keep] - m) ** 2) / max(keep.sum() - 1, 1))
    return m, float(np.sqrt(1 / np.sum(w)) * np.sqrt(max(1.0, chi))), keep


def frame_offset(stars: list[StarMeas], exclude: int | None = None, floor: float = 0.0, min_n: int = 3):
    use = [m for m in stars if m.star != exclude]
    if len(use) < min_n:
        return None
    mx, ex, kx = _robust_mean([m.dxi for m in use], [m.sx for m in use], floor)
    my, ey, ky = _robust_mean([m.deta for m in use], [m.sy for m in use], floor)
    n = int(min(kx.sum(), ky.sum()))
    if n < min_n:
        return None
    return mx, my, ex, ey, n


def measure_field(frames, native, refs, target_pred, settings, min_snr: float = 8.0,
                  exclude_radius_arcsec: float = 15.0, max_good_per_frame: int = 40,
                  progress=None) -> list[FrameCal | None]:
    """Centroid + forced photometry of every reference star in every usable frame."""
    out: list[FrameCal | None] = []
    prop = FieldPropagator(refs)
    for k, (f, nat) in enumerate(zip(frames, native)):
        if progress and k % 5 == 0:
            progress(k, len(frames))
        if nat is None or f.get("status") != "ok":
            out.append(None)
            continue
        fr, bad = nat
        img = fr.image - (fr.zodi if fr.zodi is not None else 0)
        ny, nx = fr.image.shape
        h = settings.stamp_half_px
        tra, tdec = target_pred(f["time_mjd"])
        cal = FrameCal()
        ras, decs = prop.at(f["time_mjd"])
        if len(ras):
            xs, ys = fr.wcs.world_to_pixel_values(ras, decs)
        for j in range(len(refs)):
            if len(cal.stars) >= max_good_per_frame:   # 40 well-measured stars pin the offset; more only costs time
                break
            ra, dec = float(ras[j]), float(decs[j])
            sep = np.hypot((ra - tra) * np.cos(np.radians(dec)), dec - tdec) * 3600
            if sep < exclude_radius_arcsec:
                continue
            x, y = float(xs[j]), float(ys[j])
            if not (h + 1 <= x < nx - h - 1 and h + 1 <= y < ny - h - 1):
                continue
            c = fit_centroid(img, fr.variance, bad, fr.wcs, x, y, half=min(h, 3), min_snr=min_snr)
            if not c.ok:
                continue
            dxi, deta = tangent_offsets(c.ra_deg, c.dec_deg, ra, dec)
            if np.hypot(dxi, deta) > settings.association_radius_arcsec:
                continue
            ph = forced_aperture(fr.image, fr.variance, bad, fr.zodi, fr.wcs, c.x, c.y,
                                 r=settings.aperture_radius_px, annulus=settings.annulus_px)
            cal.stars.append(StarMeas(j, float(dxi), float(deta), c.sigma_ra_arcsec, c.sigma_dec_arcsec,
                                      ph.flux_ujy if ph.ok else None, ph.flux_err_ujy if ph.ok else None, ra, dec))
        out.append(cal)
    return out


def systematic_floor(cals: list[FrameCal | None]) -> float:
    """Extra per-measurement astrometric error (arcsec) that makes field-star residuals around their
    frame offsets consistent with chi2/dof = 1 (leave-one-out residuals)."""
    res, sig = [], []
    for cal in cals:
        if not cal or len(cal.stars) < 4:
            continue
        for m in cal.stars:
            off = frame_offset(cal.stars, exclude=m.star)
            if off is None:
                continue
            res += [m.dxi - off[0], m.deta - off[1]]
            sig += [np.hypot(m.sx, off[2]), np.hypot(m.sy, off[3])]
    if len(res) < 10:
        return 0.0
    res, sig = np.asarray(res), np.asarray(sig)
    # robust: clip gross outliers (blends, cosmic rays) before solving
    med = np.median(np.abs(res))
    keep = np.abs(res) < 6 * 1.4826 * med + 1e-9
    res, sig = res[keep], sig[keep]
    chi = lambda f: np.mean(res ** 2 / (sig ** 2 + f ** 2))
    if chi(0.0) <= 1.0:
        return 0.0
    lo, hi = 0.0, 10.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if chi(mid) > 1.0 else (lo, mid)
    return float(hi)


def calibrate(cals: list[FrameCal | None], floor: float) -> None:
    for cal in cals:
        if not cal:
            continue
        off = frame_offset(cal.stars, floor=floor)
        if off is None:
            cal.n, cal.ok = len(cal.stars), False
            continue
        cal.off_xi, cal.off_eta, cal.err_xi, cal.err_eta, cal.n = off
        cal.ok = True


def apply_offset(ra: float, dec: float, off_xi: float, off_eta: float) -> tuple[float, float]:
    return ra - off_xi / 3600.0 / np.cos(np.radians(dec)), dec - off_eta / 3600.0


def field_controls(frames, cals, refs, floor: float, max_report: int = 25) -> dict:
    """Every field star measured in >=3 calibrated frames, corrected with LEAVE-ONE-OUT frame offsets,
    is a control: its fitted proper motion must agree with Gaia. The z-score distribution is the test."""
    per_star: dict[int, list] = {}
    for f, cal in zip(frames, cals):
        if not cal or not cal.ok:
            continue
        for m in cal.stars:
            off = frame_offset(cal.stars, exclude=m.star, floor=floor)
            if off is None:
                continue
            pra, pdec = m.pra, m.pdec
            # reconstruct measured position from the stored offset, then correct it
            mra = pra + m.dxi / 3600.0 / np.cos(np.radians(pdec))
            mdec = pdec + m.deta / 3600.0
            cra, cdec = apply_offset(mra, mdec, off[0], off[1])
            per_star.setdefault(m.star, []).append(
                (f["time_mjd"], cra, cdec, float(np.sqrt(m.sx ** 2 + off[2] ** 2 + floor ** 2)),
                 float(np.sqrt(m.sy ** 2 + off[3] ** 2 + floor ** 2))))
    stars, zs, zp = [], [], []
    for j, rows in per_star.items():
        if len(rows) < 3:
            continue
        a = np.array(rows)
        mfit = fit_motion(a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], refs[j])
        if not mfit.ok or mfit.z_pmra is None:
            continue
        zs += [mfit.z_pmra, mfit.z_pmdec]
        rec = {"source": refs[j].source, "n_epochs": len(rows), "z": [mfit.z_pmra, mfit.z_pmdec],
               "pm_measured": [mfit.pmra_masyr, mfit.pmdec_masyr], "pm_err": [mfit.pmra_err, mfit.pmdec_err],
               "pm_gaia": [refs[j].pmra_masyr, refs[j].pmdec_masyr]}
        # same null test for the free-parallax (5-parameter) fit: the parallax must agree with Gaia
        if len(rows) >= 8:
            pf = fit_parallax(a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], refs[j])
            if pf.get("ok") and pf.get("z_vs_catalogue") is not None:
                zp.append(pf["z_vs_catalogue"])
                rec.update(parallax_measured=pf["parallax_mas"], parallax_err=pf["parallax_err_mas"],
                           parallax_gaia=refs[j].parallax_mas, z_parallax=pf["z_vs_catalogue"])
        stars.append(rec)
    zs = np.asarray(zs, float)
    zp = np.asarray(zp, float)
    stars.sort(key=lambda s: -s["n_epochs"])
    return {
        "n_stars": len(stars),
        "frac_abs_z_gt_3": float(np.mean(np.abs(zs) > 3)) if zs.size else None,
        "z_std": float(np.std(zs)) if zs.size else None,
        "z_median_abs": float(np.median(np.abs(zs))) if zs.size else None,
        "parallax_n_stars": int(zp.size),
        "parallax_frac_abs_z_gt_3": float(np.mean(np.abs(zp) > 3)) if zp.size else None,
        "parallax_z_std": float(np.std(zp)) if zp.size else None,
        "parallax_z_median": float(np.median(zp)) if zp.size else None,
        "stars": stars[:max_report],
        "method": "leave-one-out per-exposure offsets; Gaia DR3 catalogue motion (and parallax) as truth",
    }


def photometric_floor(frames, cals, rel_width: float) -> float | None:
    """Fractional flux error to add in quadrature so that field-star fluxes within wavelength bins are
    consistent with constancy (chi2/dof = 1). Variable field stars make this conservative (larger)."""
    groups: dict[tuple, list] = {}
    lams = [f.get("wavelength_um") if f.get("status") == "ok" else None for f in frames]
    bins = wavelength_bins(lams, rel_width)
    for f, cal, b in zip(frames, cals, bins):
        if not cal or b < 0:
            continue
        for m in cal.stars:
            if m.flux is not None and m.flux_err and m.flux > 0:
                groups.setdefault((m.star, int(b)), []).append((m.flux, m.flux_err))
    sets = [np.array(v) for v in groups.values() if len(v) >= 2]
    if len(sets) < 5:
        return None

    def chi(fr):
        tot, dof = 0.0, 0
        for a in sets:
            e2 = a[:, 1] ** 2 + (fr * a[:, 0]) ** 2
            w = 1 / e2
            mu = np.sum(w * a[:, 0]) / np.sum(w)
            r = (a[:, 0] - mu) ** 2 / e2
            tot += float(np.sum(np.minimum(r, 25.0)))   # cap single outliers (cosmic rays, blends)
            dof += len(a) - 1
        return tot / max(dof, 1)
    if chi(0.0) <= 1.0:
        return 0.0
    lo, hi = 0.0, 2.0
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if chi(mid) > 1.0 else (lo, mid)
    return float(hi)
