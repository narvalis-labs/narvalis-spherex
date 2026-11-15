# References and the decisions they justify

Identifiers below were checked on **2026-11-14** against publisher, arXiv or ADS records found by
web search. **Verification level:** *metadata + abstract* unless stated otherwise — full texts were
not read. Each entry lists the concrete engineering decision it supports; references are not decoration.

## A. SPHEREx mission and data

**[1]** Crill, B. P., Werner, M., Akeson, R., et al. (2024). *SPHEREx: NASA's Near-Infrared
Spectrophotometric All-Sky Survey.* arXiv:2404.11017 (SPIE proceedings). DOI 10.48550/arXiv.2404.11017.
- States 0.75–5 µm coverage, R≈40 (0.75–3.8 µm) and R≈120 (3.8–5 µm), 6.2″×6.2″ pixels, LVF design;
  describes the Sky Simulator and IRSA distribution, including forced-photometry tools.
- **Decision:** position changes of nearby stars are sub-pixel per visit → must be *measured*
  (centroids + uncertainties), not judged visually; wavelength differs per exposure → matched-λ comparison.

**[2]** Crill, B. P., Bach, Y. P., Bryan, S. A., Choppin de Janvry, J., Cukierman, A. J., et al. (2025).
*The SPHEREx Sky Simulator: Science Data Modeling for the First All-Sky Near-Infrared Spectral Survey.*
ApJS 281, 10 (bibcode 2025ApJS..281...10C); arXiv:2505.24856.
- Level-2 images are 2040×2040 science arrays at 6.15″/pix with flag/mask planes; predicted 5σ
  point-source sensitivity m_AB ≈ 18.5–19 (0.75–3.8 µm) and ≈ 16.6–18 (3.8–5 µm), zodiacal-light limited.
- **Decisions:** pixel scale used for stamp sizes and display grid; flag-plane rejection; the
  wavelength-dependent depth motivates reporting detections **per wavelength** (see C2).

**[3]** Cukierman, A. J., Chen, S.-S., Kang, J. H., et al. (2026, draft). *Spectral Map Making with
SPHEREx.* arXiv:2603.25790.
- Spectral cubes/HEALPix maps are combinations of many exposures.
- **Decision:** cubes are excluded from motion analysis (`discover_collections` skips "cube");
  only per-exposure spectral images carry epoch information.

**[4]** NASA/IPAC IRSA SPHEREx data releases: DR1 Spectral Images DOI 10.26131/IRSA678;
DR1 All-Sky Cube DOI 10.26131/IRSA679; Quick Release DOI 10.26131/IRSA662 (identifiers from the team's
verification of IRSA pages). IPAC news 2025-07-08: weekly Quick Release, access via astroquery and the
AWS Open Data bucket `s3://nasa-irsa-spherex`.
- **Decision:** IRSA SIA2 + cutouts as the only image source; per-file URL + SHA-256 in every dossier.

## B. Astrometric reference and epoch propagation

**[5]** Gaia Collaboration, Vallenari, A., Brown, A. G. A., et al. (2023). *Gaia Data Release 3:
Summary of the content and survey properties.* A&A 674, A1. DOI 10.1051/0004-6361/202243940.

**[6]** Lindegren, L., Klioner, S. A., Hernández, J., et al. (2021). *Gaia Early Data Release 3:
The astrometric solution.* A&A 649, A2. DOI 10.1051/0004-6361/202039709.
- Gaia (E)DR3 astrometry (positions, parallaxes, proper motions; same astrometry carried into DR3).
- **Decisions:** Gaia DR3 is the primary reference; positions are propagated from the catalogue
  reference epoch (`ref_epoch`) with proper motion, parallax and radial velocity; catalogue PM errors
  are combined in quadrature in the z-score.

**[7]** Luhman, K. L. (2014). *Discovery of a ~250 K Brown Dwarf at 2 pc from the Sun.* ApJL 786, L18.
DOI 10.1088/2041-8205/786/2/L18; arXiv:1404.6501.
- WISE 0855−0714: proper motion 8.1 ± 0.1″/yr, parallax 0.454 ± 0.045″, from WISE + Spitzer.
- **Decision:** expected motion ≈ 1.3 SPHEREx pixels per year → measurable in principle; the object
  has no Gaia counterpart, so the reference falls back to SIMBAD/Sesame (flagged in the dossier caveats).

## C. Measurement methods

**[8]** Mendez, R. A., Orostica, R., Lobos, R. (2014). *Analysis of the Cramér-Rao Bound in the Joint
Estimation of Astrometry and Photometry.* PASP 126, 798–810. DOI 10.1086/678041; arXiv:1407.3753.
- Cramér-Rao precision limits for a Gaussian source on a pixel array; least-squares estimators approach
  but do not formally reach the bound (Mendez 2013, arXiv:1304.6361).
- **Decision:** variance-weighted least-squares Gaussian fit for centroids; our test
  `test_centroid_errors_are_calibrated` checks that reported errors match the actual scatter (pull σ ≈ 1).

**[9]** Sokolovsky, K. V., Gavras, P., Karampelas, A., et al. (2017). *Comparative performance of
selected variability detection techniques in photometric time series data.* MNRAS 464, 274.
DOI 10.1093/mnras/stw2262; arXiv:1609.01716.
- Compares 18 variability indices; χ² against a constant model is a standard (error-sensitive) index.
- **Decision:** χ² of constant flux per wavelength bin; because χ² is sensitive to underestimated
  errors (discussed in [9]), the verdict threshold is conservative (p < 10⁻³) and labelled "candidate".

**[10]** Marocco, F., Eisenhardt, P. R. M., Fowler, J. W., et al. (2021). *The CatWISE2020 Catalog.*
ApJS 253, 8. DOI 10.3847/1538-4365/abd805; arXiv:2012.13084.
- Infrared proper motions validated by comparison with Gaia (≈20 mas/yr at W1≈15, ≈100 mas/yr at W1≈17).
- **Decision:** validate SPHEREx-measured motions against Gaia, and report accuracy as a function of
  brightness rather than a single number.

## D. Moving-object search context (prior art, not implemented)

**[11]** Kuchner, M. J., Faherty, J. K., Schneider, A. C., et al. (2017). *The First Brown Dwarf
Discovered by the Backyard Worlds: Planet 9 Citizen Science Project.* ApJL 841, L19.
ADS 2017ApJ...841L..19K; arXiv:1705.02919 (publisher DOI not fully confirmed in this session).
- Volunteers inspect animations of difference images from time-resolved WISE coadds.
- **Decision (positioning):** the blink/difference workflow is established prior art; EpochLab's
  contribution is quantitative verification (catalogue track, calibrated errors, controls), not blinking.

**[12]** Whidden, P. J., Kalmbach, J. B., Connolly, A. J., et al. (2019). *Fast algorithms for slow
moving asteroids: constraints on the distribution of Kuiper Belt Objects.* AJ 157.
DOI 10.3847/1538-3881/aafd2d; arXiv:1901.02492. (KBMOD shift-and-stack, open source.)
- **Decision:** shift-and-stack for sources below single-exposure detection is listed as future work,
  not claimed.

## E. Software

**[13]** Astropy Collaboration, Price-Whelan, A. M., Lim, P. L., et al. (2022). ApJ 935, 167.
DOI 10.3847/1538-4357/ac7c74. — coordinates, space motion, WCS (incl. -TAB), FITS, time scales.

**[14]** Ginsburg, A., Sipőcz, B. M., Brasseur, C. E., et al. (2019). *astroquery: An Astronomical
Web-querying Package in Python.* AJ 157, 98. DOI 10.3847/1538-3881/aafc33. — IRSA, SIMBAD access.

Also used, cited by software name/version in each dossier: PyVO, SciPy, NumPy, reproject, FastAPI;
Aladin Lite (CDS) for sky context only.

## Methods without a specific verified reference

- **Injection–recovery** on real images: standard survey-pipeline practice; no single paper was verified
  in this session, so none is cited.
- **Annual parallax formula** used as an independent test: textbook relation; the implementation itself
  uses Astropy [13] and the test cross-checks the two.
- **Wavelength-matched comparison** for LVF data: our design decision derived from [1], [2]; we did not
  find (or search exhaustively for) prior work describing the same procedure for SPHEREx epochs.

## Hypothesis derived from these sources (to be tested, not a result)

WISE 0855−0714 is extremely red ([7]); with SPHEREx single-exposure depth shallower at 3.8–5 µm
than at shorter wavelengths ([2]), detections, if any, are expected only in the longest-wavelength
exposures. `selftest_real.py` records the wavelength of every successful centroid so this can be checked.
