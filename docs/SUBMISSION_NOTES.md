# Submission notes (draft — fill in after the real-data run)

## Challenge requirement → feature → evidence

| Requirement (Planet X and SPHEREx) | Feature | Evidence to show |
|---|---|---|
| Public web tool | EpochLab web UI behind HTTPS | public URL (no login) |
| Enter RA/Dec | name or ICRS RA/Dec form | live demo |
| Real SPHEREx images | IRSA SIA2 + cutouts, per-file URL + SHA-256 | dossier `frames[].download` |
| How a region changes over time | time-ordered blink, timeline, matched-λ differences | 30 s video |
| Test objects | 5 presets; `validation/REPORT.md` | report table (including failures) |

## What is different from a blink viewer

1. Catalogue track propagated to **each exposure's time** (PM + parallax + RV) and measured position
   with **calibrated uncertainties** → z-score vs Gaia, not "looks like it moved".
2. **Wavelength-matched** comparison: SPHEREx sees a source at a different λ in each visit.
3. **Static control stars** and **injection-recovery** run through the same code.
4. **Reproducible dossier** + `cli reproduce`.

## AI use declaration (edit to match what you actually did)

Code and documentation were drafted with the assistance of an AI coding assistant (Claude, Anthropic)
and reviewed, tested and deployed by the team. All scientific results come from executing the code on
public archive data; no result, number or image was produced by an AI model. No AI-generated images or
video are used [if any are, they carry a visible "AI-generated" mark and no NASA identity elements].

## Claims we can make / cannot make

- Can: "reproduces the catalogue proper motion of X within Nσ using N SPHEREx epochs" — only if REPORT.md says so.
- Can: "a constant source with a steep spectrum is not flagged by our matched-λ test, while a naive comparison is" (unit test).
- Cannot: any discovery claim; any sensitivity number not in REPORT.md.

## Space Apps "resources used" field (draft)

- NASA/IPAC IRSA SPHEREx spectral images (DR1 10.26131/IRSA678; QR 10.26131/IRSA662) via SIA2 and cutouts.
- ESA Gaia DR3 (Vallenari et al. 2023, doi:10.1051/0004-6361/202243940) via the Gaia TAP service.
- CDS SIMBAD / Sesame name resolution; Aladin Lite for sky context.
- GridStack.js (MIT) for the customisable cockpit layout.
- Methods literature: see docs/REFERENCES.md (14 verified references, each tied to a design decision).
- Software: Astropy, astroquery, PyVO, SciPy, NumPy, reproject, FastAPI.
