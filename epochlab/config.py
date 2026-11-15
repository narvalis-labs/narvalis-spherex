"""Runtime configuration. Every value is recorded in each dossier so results are reproducible."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    # Storage
    data_dir: Path = field(default_factory=lambda: Path(_env("EPOCHLAB_DATA", "./data")).resolve())

    # IRSA access. Collection names are configurable because they differ between releases
    # (QR vs DR1). Run `python scripts/selftest_real.py --list-collections` to discover them.
    irsa_sia_url: str = _env("EPOCHLAB_SIA_URL", "https://irsa.ipac.caltech.edu/SIA")
    collections: tuple[str, ...] = tuple(
        c.strip() for c in _env("EPOCHLAB_COLLECTIONS", "auto").split(",") if c.strip()
    )
    # Cutout URL template appended to the SIA access_url. {ra},{dec} in deg, {size} in deg.
    cutout_query: str = _env("EPOCHLAB_CUTOUT_QUERY", "?center={ra},{dec}deg&size={size}deg")
    http_timeout_s: float = float(_env("EPOCHLAB_HTTP_TIMEOUT", "120"))
    max_parallel_downloads: int = int(_env("EPOCHLAB_PARALLEL", "3"))

    # Analysis defaults (overridable per request; final values go into the dossier)
    cutout_size_arcsec: float = 600.0       # large enough to contain Gaia field stars even at high latitude
    max_frames: int = 150                   # Nov 2026: 80 -> 150 (Barnard: 137 exposures halved the error vs 80)
    # Centroid model (see astrometry.fit_centroid). Defaults chosen by the Nov 2026 comparison against Gaia DR3.
    psf_model: str = _env("EPOCHLAB_PSF", "point")              # "point" | "pixel" | "ellip" (pixel, ellip: no gain on real data, Nov 2026)
    detection_test: str = _env("EPOCHLAB_DETECT", "hybrid")     # "amplitude" | "dchi2" | "hybrid"
    # Optional: fit known Gaia neighbours (fixed positions, free fluxes) together with the target. OFF by default:
    # tested Nov 2026, Barnard's fit improved (reduced chi2 2.5 -> 1.3) but WISE 0855, which passes 4" (< 1 pixel)
    # from Gaia DR3 5756956644387831296, lost 4 of its 5 detections (the two are not separable at 6.2"/px).
    deblend_gaia: bool = _env("EPOCHLAB_DEBLEND", "0") not in ("0", "false", "no")
    stamp_half_px: int = 5            # centroid fit window half-size (pixels)
    aperture_radius_px: float = 2.0
    annulus_px: tuple[float, float] = (4.0, 7.0)
    min_snr_centroid: float = 5.0
    astrometric_floor_arcsec: float = 0.0   # extra systematic term added in quadrature (assumption; recorded)
    association_radius_arcsec: float = 6.0  # a detection farther than this from the predicted position is rejected
    # With catalogue astrometry (PM + parallax) the prediction is good to << 1": the gate then shrinks to
    # max(association_min_arcsec, association_nsigma x the detection's own 1-sigma error). First real-data run
    # (Nov 2026): a background source 4.4" from WISE 0855 passed the fixed 6" gate at 0.9-2.5 um.
    association_min_arcsec: float = 2.5
    association_nsigma: float = 4.0
    min_variability_dof: int = 3            # fewer repeat measurements than this: variability is INCONCLUSIVE
    field_gmax: float = 18.5                # faintest Gaia G used for field-star calibration
    wavelength_bin_rel: float = 0.02        # bin width as fraction of lambda (~ R=50)
    large_amplitude: float = 1.2            # max/min flux ratio within a bin above which variability is "large"
    # Flag names (from FLAGS header MP_* keywords) whose pixels are rejected. Substring match.
    reject_flag_substrings: tuple[str, ...] = (
        "SATUR", "NONFUNC", "HOT", "COLD", "NONLINEAR", "MISSING", "PERSIST",
        "TRANSIENT", "OVERFLOW", "SUR_ERROR", "PHANMISS", "DICHROIC",
        # artefact planes named in SPHEREx DR1 FLAGS headers (MSKNnnnn). SOURCE, GHOST*, CROSSTALK and FULLSAMPLE
        # are deliberately kept: SOURCE marks the star itself, the others would remove real flux near bright stars.
        "OUTLIER", "STREAK", "SNOWBALL", "BLOOM", "HALO",
    )

    def public_dict(self) -> dict:
        d = asdict(self)
        d["data_dir"] = str(self.data_dir)
        return d


settings = Settings()
