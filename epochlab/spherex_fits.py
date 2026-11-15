"""Parsing of SPHEREx Level-2 spectral image MEF files (full images or IRSA cutouts).

Expected extensions (per IRSA SPHEREx documentation): IMAGE (MJy/sr), FLAGS (bitmask),
VARIANCE, ZODI (model), PSF, WCS-WAVE (lookup table for the spectral WCS, key 'W').
The parser is defensive: anything it cannot find is reported in `warnings`, never invented.
"""
from __future__ import annotations

import warnings as _pywarnings
from dataclasses import dataclass, field

import numpy as np
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS, FITSFixedWarning

_TIME_KEYS_MJD = ("MJD-AVG", "MJD-MID", "MJDMID", "MJD-OBS", "MJD-BEG")
_TIME_KEYS_ISO = ("DATE-AVG", "DATE-MID", "DATE-OBS", "DATE-BEG")


@dataclass
class SpherexFrame:
    image: np.ndarray
    variance: np.ndarray | None
    flags: np.ndarray | None
    zodi: np.ndarray | None
    wcs: WCS
    header: fits.Header
    hdul: fits.HDUList | None = None
    flag_bits: dict[str, int] = field(default_factory=dict)
    time_mjd: float | None = None
    time_source: str | None = None
    detector: str | None = None
    warnings: list[str] = field(default_factory=list)

    # ---- derived quantities -------------------------------------------------
    def wavelength_at(self, x: float, y: float) -> tuple[float | None, float | None, str]:
        """Central wavelength and bandwidth (micron) at 0-based pixel (x, y).

        Uses the alternate spectral WCS 'W' (-TAB lookup in WCS-WAVE). Returns (None, None, reason)
        if it cannot be evaluated; never guesses.
        """
        if self.hdul is None:
            return None, None, "no HDUList available for -TAB lookup"
        try:
            with _pywarnings.catch_warnings():
                _pywarnings.simplefilter("ignore", FITSFixedWarning)
                sw = WCS(self.header, fobj=self.hdul, key="W")
                sw.sip = None
                out = sw.wcs_pix2world(np.array([[x, y]], dtype=float), 0)[0]
            lam = float(out[0])
            bw = float(out[1]) if len(out) > 1 else None
            if not np.isfinite(lam):
                return None, None, "spectral WCS returned non-finite value"
            return lam, bw, "WCS key W (-TAB)"
        except Exception as exc:  # noqa: BLE001 — we report the exact failure
            return None, None, f"spectral WCS failed: {type(exc).__name__}: {exc}"

    def bad_pixel_mask(self, reject_substrings: tuple[str, ...]) -> tuple[np.ndarray, list[str]]:
        """True where the pixel must not be used. Returns (mask, names of rejected flags)."""
        mask = ~np.isfinite(self.image)
        if self.variance is not None:
            mask |= ~np.isfinite(self.variance) | (self.variance <= 0)
        used: list[str] = []
        if self.flags is not None and self.flag_bits:
            bits = 0
            for name, bit in self.flag_bits.items():
                if any(s in name.upper() for s in reject_substrings):
                    bits |= 1 << bit
                    used.append(name)
            if bits:
                mask |= (self.flags.astype(np.int64) & bits) != 0
        return mask, used


def _find(hdul: fits.HDUList, *names: str):
    for n in names:
        if n in hdul:
            return hdul[n]
    return None


def _parse_flag_bits(hdr: fits.Header) -> dict[str, int]:
    """Bit definitions of the FLAGS plane, as {name: bit index}. Returns {} if absent.

    Two conventions are read:
    * MP_<NAME> = <bit>                         (assumed before real data were available; kept for the test fixtures)
    * MSKNnnnn = '<NAME>', MSKMnnnn = 1 << nnnn (what SPHEREx DR1 L2 cutouts actually carry, checked Nov 2026;
      e.g. MSKN0001 = 'OVERFLOW', MSKN0015 = 'NONLINEAR')
    """
    out: dict[str, int] = {}
    for key in hdr.keys():
        if key.startswith("MP_"):
            try:
                out[key[3:]] = int(hdr[key])
            except (TypeError, ValueError):
                continue
        elif key.startswith("MSKN") and key[4:].isdigit():
            n = int(key[4:])
            m = hdr.get(f"MSKM{key[4:]}")
            try:
                if m is not None and int(m) > 0 and int(m) & (int(m) - 1) == 0:
                    n = int(m).bit_length() - 1      # trust the explicit mask when it is a single bit
            except (TypeError, ValueError):
                pass
            out[str(hdr[key]).strip().upper()] = n
    return out


def _parse_time(hdrs: list[fits.Header]) -> tuple[float | None, str | None]:
    for h in hdrs:
        for k in _TIME_KEYS_MJD:
            if k in h:
                try:
                    return float(h[k]), f"header {k}"
                except (TypeError, ValueError):
                    pass
        for k in _TIME_KEYS_ISO:
            if k in h:
                try:
                    return float(Time(h[k], scale="utc").mjd), f"header {k}"
                except Exception:  # noqa: BLE001
                    pass
    return None, None


def open_frame(path_or_hdul) -> SpherexFrame:
    hdul = path_or_hdul if isinstance(path_or_hdul, fits.HDUList) else fits.open(path_or_hdul, memmap=False)
    warns: list[str] = []
    img_hdu = _find(hdul, "IMAGE", "SCI")
    if img_hdu is None:
        # Fall back to first HDU with 2D data, but say so.
        img_hdu = next((h for h in hdul if getattr(h, "data", None) is not None and np.ndim(h.data) == 2), None)
        if img_hdu is None:
            raise ValueError("No 2D image extension found")
        warns.append(f"IMAGE extension not found; using HDU '{img_hdu.name}'")
    hdr = img_hdu.header
    with _pywarnings.catch_warnings():
        _pywarnings.simplefilter("ignore", FITSFixedWarning)
        wcs = WCS(hdr, fobj=hdul).celestial
    var_hdu = _find(hdul, "VARIANCE", "VAR")
    flg_hdu = _find(hdul, "FLAGS", "MASK")
    zod_hdu = _find(hdul, "ZODI")
    if var_hdu is None:
        warns.append("VARIANCE extension missing: uncertainties unavailable")
    if flg_hdu is None:
        warns.append("FLAGS extension missing: no instrumental flag rejection")
    if zod_hdu is None:
        warns.append("ZODI extension missing: zodiacal model not subtracted (annulus background only)")
    flag_bits = _parse_flag_bits(flg_hdu.header) if flg_hdu is not None else {}
    if flg_hdu is not None and not flag_bits:
        warns.append("FLAGS present but no MP_*/MSKN* bit definitions in header: flags not interpreted")
    t, tsrc = _parse_time([hdr, hdul[0].header])
    det = None
    for k in ("DETECTOR", "DETNAME", "DETID"):
        for h in (hdr, hdul[0].header):
            if k in h:
                det = str(h[k])
                break
        if det:
            break
    return SpherexFrame(
        image=np.asarray(img_hdu.data, dtype=float),
        variance=None if var_hdu is None else np.asarray(var_hdu.data, dtype=float),
        flags=None if flg_hdu is None else np.asarray(flg_hdu.data),
        zodi=None if zod_hdu is None else np.asarray(zod_hdu.data, dtype=float),
        wcs=wcs,
        header=hdr,
        hdul=hdul,
        flag_bits=flag_bits,
        time_mjd=t,
        time_source=tsrc,
        detector=det,
        warnings=warns,
    )
