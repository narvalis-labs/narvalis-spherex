# Narvalis — NASA Space Apps Challenge 2026 · Planet X and SPHEREx

## One-line summary
Narvalis turns a star's name or coordinates into a verified, reproducible answer from real SPHEREx images:
**does it move, how far is it, does its brightness change, and can I trust the result?**

## Project description
SPHEREx images the whole sky in 102 infrared colours and returns to every field about every six months. A nearby
object (a fast-moving star, a cold brown dwarf, a hypothetical "Planet X") reveals itself through its motion and
its parallax across those visits. That change is in the data, but it is spread over hundreds of single exposures
taken at different wavelengths, and nobody looks at them side by side.

Narvalis does it automatically. For any position on the sky it:

1. **fetches every SPHEREx exposure** covering it from NASA/IPAC IRSA (up to 150 by default), with pixel flags;
2. **predicts** where the source should be at each exposure's time (Gaia DR3 astrometry with proper motion,
   parallax and radial velocity) and **measures** where it really is, on native pixels;
3. **calibrates every exposure on its own Gaia field stars**, so the error bars are real;
4. fits the **motion** and, independently of any catalogue, the **parallax**, which gives the **distance from
   SPHEREx alone**;
5. compares brightness **only between exposures at the same wavelength** (SPHEREx sees a source in a different
   colour at each visit, so a naive comparison invents variability);
6. runs the **same pipeline on dozens of Gaia field stars** as controls, and states for every result whether it is
   reliable, with the rule that was applied;
7. writes a **dossier**: archive URL and SHA-256 of every file, all parameters and software versions; one command
   re-runs it and checks that the result is identical.

The web app shows the real exposures as a filmstrip and an animated viewer, the measured and predicted positions,
a sky map with the challenge targets, and four plain-language answers. It works on desktop and phone, has a
research mode (exact RA/Dec under the cursor, pins fixed on the sky across epochs), a guided tour and a live
status panel of the archives it depends on.

## Results on the challenge targets (real SPHEREx DR1 data)

| Target | Narvalis (SPHEREx only) | Gaia DR3 / known | Verdict |
|---|---|---|---|
| Barnard's Star | 136 epochs · µ = (−718 ± 106, 10395 ± 105) mas/yr | (−802, 10362) | **+0.25 % in total proper motion, 0.25σ** |
| ε Indi B | µ = (3911 ± 69, −2489 ± 70) mas/yr · **distance 3.3 pc (2.9–3.9), 6.6σ** | 3.69 pc | consistent (motion and distance) |
| WISE 0855−0714 | seen **only at 4.2–4.6 µm**, as expected for the coldest known brown dwarf · µ = (−7033 ± 1154, 1284 ± 1145) | (−8124, 673) | consistent (0.9σ) |
| RW Aurigae | brightness varies ×4.0 at matched wavelength; photocentre shifts with wavelength | young variable binary | variable |
| R Draconis | saturated core; flux varies ×4.7 in the unsaturated wings | Mira variable | possible |

Every field passes its control test: 0 % of the Gaia field stars beyond 3σ, in motion and in parallax
(166 stars in 5 fields). Narvalis also reports its own limits: for saturated stars (Barnard, R Dra) and for
RW Aur (photocentre shift) the parallax fit returns spurious values, so the distance is reported as
**not reliable** instead of a wrong number. In the WISE 0855 field it rejects a background star (Gaia DR3
5756956644387831296) that the brown dwarf is passing within 4″ of in 2026.

Reliability: injection–recovery of a synthetic moving star in real images recovers the motion within 3σ at every
level with ≥ 3 detected epochs; 0 SHA-256 mismatches when re-downloading the files; 72 automated tests.

## Relation to the challenge
The challenge asks for a tool that shows how a region of the sky changes over time in SPHEREx data and tests it on
known objects. Narvalis does that for any position, and goes further in the direction "Planet X" needs: a real
distant planet or cold brown dwarf would be faint, red and visible only at the longest wavelengths, and it would be
recognised by its motion and parallax. Narvalis measures both from SPHEREx alone, finds WISE 0855 exactly where and
at the wavelengths physics predicts, and refuses to claim what the data cannot support.

## Limits and next steps
- Star model: circular Gaussian on 6.2″ pixels; an empirical SPHEREx PSF would fix the parallax of saturated stars.
- Faint targets: per-season stacking increases detection S/N (WISE 0855: S/N 18–32 per season) but did not yet
  improve positions; subtracting known neighbours that are closer than one pixel is the next step.
- Archive availability: the IRSA image search was down during the final day; Narvalis keeps working from its cache
  and uses a Gaia DR3 mirror (GAVO Heidelberg) when the ESA archive is unreachable.

## NASA and other data used
- NASA/IPAC Infrared Science Archive (IRSA): SPHEREx Level-2 spectral images, DR1 (doi:10.26131/IRSA678) and quick
  release (doi:10.26131/IRSA662), via SIA2 and cutout services.
- ESA Gaia DR3 (Gaia Collaboration, Vallenari et al. 2023), through the ESA Gaia archive and the GAVO Heidelberg mirror.
- CDS SIMBAD and Sesame (name resolution); Aladin Lite with 2MASS/DSS imagery (sky context only, not used in measurements).
- Software: Astropy, astroquery, PyVO, NumPy, SciPy, reproject, FastAPI, GridStack.js. Literature: docs/REFERENCES.md.

## Use of AI
The code and documentation were written with the help of an AI assistant (Claude, by Anthropic), directed, reviewed
and tested by the team. All scientific results come from running the code on public archive data; no number, image
or result was produced by an AI model. The app uses no AI-generated images or video.

Narvalis is an independent student project and is not affiliated with or endorsed by NASA, JPL, Caltech, IPAC or ESA.
