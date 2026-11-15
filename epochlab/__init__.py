"""EpochLab — epoch- and wavelength-aware motion/variability verifier for SPHEREx spectral images."""
import warnings as _w

__version__ = "0.1.0"

# Two known, harmless warnings that would otherwise flood the logs (see README "Known warnings"):
# - ERFA pmsafe "distance overridden": stars without a usable parallax get ERFA's default distance; only the
#   (negligible) radial-velocity term is affected, proper-motion propagation is unchanged.
# - astropy "SIP distortion coefficients ... append -SIP": SPHEREx headers carry SIP terms with a TAN CTYPE;
#   astropy applies them (the intended optical distortion) and our spectral WCS explicitly drops them.
_w.filterwarnings("ignore", message=r".*distance overridden.*")
_w.filterwarnings("ignore", message=r".*SIP distortion coefficients.*")
