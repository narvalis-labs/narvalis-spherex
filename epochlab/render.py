"""Display products. Measurements are always made on native pixels; these images are only for viewing.

Faithfulness rules for what the user sees:
- Grey levels are the measured surface brightness (MJy/sr, zodiacal model subtracted). No colour is
  added: each SPHEREx exposure is a single narrow near-infrared band, so any hue would be invented.
- SPHEREx exposures have arbitrary position angles, so frames are resampled onto a common north-up TAN
  grid with NEAREST-NEIGHBOUR sampling: every displayed value is an actual pixel value (no smoothing).
- Frames in the same wavelength bin share one intensity scale, so a brightness difference between
  two epochs on screen is a brightness difference in the data. The scale is stored in the dossier.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.wcs import WCS
from PIL import Image


def common_wcs(ra: float, dec: float, size_arcsec: float, pix_arcsec: float) -> tuple[WCS, int]:
    n = int(np.ceil(size_arcsec / pix_arcsec)) | 1  # odd, so the target is on a pixel centre
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-pix_arcsec / 3600.0, pix_arcsec / 3600.0]
    w.wcs.radesys = "ICRS"
    return w, n


def reproject_to(image: np.ndarray, bad: np.ndarray, src_wcs: WCS, dst_wcs: WCS, n: int) -> np.ndarray:
    from reproject import reproject_interp
    img = np.where(bad, np.nan, image)
    out, foot = reproject_interp((img, src_wcs), dst_wcs, shape_out=(n, n), order="nearest-neighbor")
    out[foot == 0] = np.nan
    return out


ASINH_SOFT = 8.0  # asinh softening: linear near vmin, logarithmic for bright stars (recorded in dossier)


def display_limits(arrays, lo_p=1.0, hi_p=99.7) -> tuple[float, float] | None:
    """Shared (vmin, vmax) from the pooled finite pixels of several frames."""
    vals = [a[np.isfinite(a)] for a in arrays if a is not None]
    vals = [v for v in vals if v.size]
    if not vals:
        return None
    v = np.concatenate(vals)
    lo, hi = np.percentile(v, [lo_p, hi_p])
    return float(lo), float(hi if hi > lo else lo + 1e-9)


def _to_unit(a, vmin, vmax, symmetric):
    if symmetric:  # signed difference: 0.5 = no change
        x = np.clip((a + vmax) / (2 * vmax), 0, 1)
    else:
        x = np.clip((a - vmin) / (vmax - vmin), 0, 1)
        x = np.arcsinh(ASINH_SOFT * x) / np.arcsinh(ASINH_SOFT)
    return np.where(np.isfinite(x), x, 0)


def save_png(a: np.ndarray, path: Path, vmin: float | None = None, vmax: float | None = None,
             symmetric: bool = False, upscale: int = 4) -> dict:
    """Write a greyscale PNG (north up, east left). Returns the exact stretch used."""
    if symmetric:
        v = a[np.isfinite(a)]
        m = float(np.percentile(np.abs(v), 99.7)) if v.size else 1.0
        vmin, vmax = -(m or 1.0), (m or 1.0)
    elif vmin is None or vmax is None:
        lim = display_limits([a]) or (0.0, 1.0)
        vmin, vmax = lim
    u8 = (_to_unit(a, vmin, vmax, symmetric) * 255).astype(np.uint8)[::-1]
    nanmask = ~np.isfinite(a)[::-1]
    rgb = np.stack([u8, u8, u8], -1)
    rgb[nanmask] = (40, 8, 12)  # no data / flagged: dark red, never confused with sky
    im = Image.fromarray(rgb, "RGB").resize((a.shape[1] * upscale, a.shape[0] * upscale), Image.NEAREST)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, optimize=True)
    return {"type": "linear" if symmetric else "asinh", "asinh_softening": None if symmetric else ASINH_SOFT,
            "vmin": float(vmin), "vmax": float(vmax), "unit": "MJy/sr (zodi-subtracted)",
            "nodata_rgb": [40, 8, 12]}


def to_display_frac(wcs: WCS, n: int, ra: float, dec: float) -> tuple[float, float]:
    """Position as fractions (0..1) of the displayed PNG (x to the right, y downward)."""
    x, y = wcs.world_to_pixel_values(ra, dec)
    return float((x + 0.5) / n), float(1.0 - (y + 0.5) / n)
