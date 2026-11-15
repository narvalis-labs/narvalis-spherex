# Narvalis — SPHEREx time-domain verifier

*(Python package and commands: `epochlab`.)*

Epoch- and wavelength-aware verification of **proper motion**, **distance (parallax)** and **variability** in real SPHEREx
spectral images (NASA Space Apps Challenge 2026 — *Planet X and SPHEREx*).

Enter a name or RA/Dec → Narvalis retrieves every SPHEREx Level-2 spectral image that covers the
position from NASA/IPAC IRSA, and for each exposure:

1. **predicts** where the source should be at that exact time (Gaia DR3 / SIMBAD astrometry propagated
   with proper motion, parallax and radial velocity),
2. **measures** where it is on native pixels (variance-weighted PSF-core fit, flagged pixels rejected),
3. records the **wavelength** at which SPHEREx saw it (spectral WCS of the linear variable filter),
4. compares brightness **only between epochs in the same wavelength bin**,
5. runs the same pipeline on **static Gaia stars** in the same cutouts as false-positive controls,
6. writes a **dossier** (archive URL + SHA-256 per file, all parameters, software versions, verdicts)
   that `cli reproduce` re-runs and checks.

Frames are resampled north-up (nearest-neighbour, so every displayed value is a real pixel value) only for
display; nothing is measured on resampled images. The viewer shows measured surface brightness in grey —
SPHEREx exposures are single near-infrared bands, so any colour would be invented (an optional, labelled
false-colour mode keys hue to wavelength). All epochs in the same wavelength bin share one intensity scale,
shown with its MJy/sr range, so on-screen brightness differences are real differences in the data.

> Status labels used everywhere: **implemented** = code exists and passes tests; **tested with real
> data** = `scripts/selftest_real.py` has been run and its report is in `validation/`.
> Synthetic data appear only in `tests/` and are labelled in every output they touch.

## Run on Windows 11 (5 minutes)

Needs Python 3.12 or newer (python.org, tick "Add python.exe to PATH").

```bat
cd epochlab
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m epochlab.cli serve --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. The five validated analyses in `data/jobs/` open immediately (listed in the
Explore panel). New searches need the NASA/IPAC IRSA archive online; the antenna icon shows the live status of every
service. Tests: `pip install -r requirements-dev.txt` then `python -m pytest -q`.

The final results and how they were obtained are in `docs/SUBMISSION.md` (English) and `validation/`.
To re-run a saved analysis with every exposure already downloaded: `python scripts/reanalyse_cached.py <job_id>`.

## Quick start (Debian 13 VM on Proxmox)

```bash
# Proxmox host: create the VM (adjust storage/bridge/IDs)
qm create 240 --name epochlab --memory 16384 --cores 6 --cpu host --net0 virtio,bridge=vmbr0 \
  --scsihw virtio-scsi-single --scsi0 local-lvm:100,discard=on,ssd=1 --agent enabled=1 \
  --ide2 local:iso/debian-13-netinst-amd64.iso,media=cdrom --boot order=scsi0\;ide2 --ostype l26
qm start 240     # install Debian 13 minimal + SSH server

# Inside the VM, as root
git clone https://github.com/narvalis-labs/narvalis-spherex.git /opt/epochlab   # or extract the project ZIP to /opt/epochlab
bash /opt/epochlab/deploy/setup-debian.sh                        # LAN only: http://<VM_IP>:8000
# later, behind the NanoPi:  NANOPI_IP=192.168.1.2 bash /opt/epochlab/deploy/setup-debian.sh
```

Then on the NanoPi: copy `deploy/nginx-nanopi.conf`, set `VM_IP`, add the `limit_req_zone` line,
`certbot --nginx -d narvalis.pitipo-app.com`, reload nginx.

Without Docker: see `deploy/epochlab.service` (venv + systemd, Python ≥ 3.12).

## First thing to run on the VM (real data)

```bash
cd /opt/epochlab
docker compose exec epochlab python -m epochlab.cli diagnose                       # SIMBAD / Sesame / Gaia / IRSA reachability
docker compose exec epochlab python scripts/selftest_real.py --list-collections   # QR / DR1 names
# put the names in .env, e.g.  EPOCHLAB_COLLECTIONS=spherex_dr1,spherex_qr   then: docker compose up -d
docker compose exec epochlab python scripts/selftest_real.py --probe --full       # HDUs, keywords, cutout λ check
docker compose exec epochlab python scripts/selftest_real.py --run                # 5 targets → validation/REPORT.md
```

`--probe` prints the real FITS structure. If a keyword differs from what `epochlab/spherex_fits.py`
expects (time, detector, `MP_*` flag bits, spectral WCS key `W`), fix it there — the parser reports
every missing item as a warning instead of guessing.

## CLI

```bash
python -m epochlab.cli analyze --name "Barnard's Star"
python -m epochlab.cli analyze --ra 269.452 --dec 4.693 --no-gaia
python -m epochlab.cli reproduce data/jobs/<id>/dossier.json
python -m epochlab.cli inject data/jobs/<id>/dossier.json --pmra 2000 --pmdec -1500 --snr 10
python -m epochlab.cli export-static --jobs <id1> <id2> --out site   # GitHub Pages fallback demo
```

## API

| Method | Path | |
|---|---|---|
| GET | `/api/health` | version, collections |
| POST | `/api/jobs` | `{target_name}` or `{ra_deg, dec_deg}` (+ optional `max_frames`, `cutout_size_arcsec`, `n_controls`, `use_gaia`, manual `ref_*`) |
| GET | `/api/jobs` | recent jobs |
| GET | `/api/jobs/{id}/status.json` | state, progress |
| GET | `/api/jobs/{id}/dossier.json` | full dossier |
| GET | `/api/jobs/{id}/frames/NNN.png`, `NNN_diff.png` | display frames |
| GET | `/api/jobs/{id}/bundle.zip` | dossier + PNGs + URL/SHA-256 list + reproduction notes |

## Methods (and their limits)

Numbers in brackets refer to `docs/REFERENCES.md`, which states for each source the decision it justifies.

| Step | Method | Basis | Limit |
|---|---|---|---|
| Discovery | IRSA SIA2, footprint contains position; SPHEREx collections auto-discovered | [4] | per-epoch images only; cubes excluded [3] |
| Pixels | IRSA cutout service (`?center=…&size=…`) | [4] | cutout λ-WCS checked by `--probe --full` |
| Time | SIA `t_min/t_max` midpoint; header time cross-checked | | |
| Wavelength | spectral WCS key `W` (-TAB lookup in `WCS-WAVE`) at the predicted pixel | [1][2][13] | |
| Reference | Gaia DR3, propagated from `ref_epoch` with PM, parallax, RV; SIMBAD/Sesame fallback | [5][6][13] | no Gaia counterpart for some brown dwarfs [7] |
| Position | circular Gaussian + constant, variance-weighted least squares, `FLAGS` bits rejected | [2][8] | PSF extension not yet used (ePSF = next step) |
| Calibration | **differential astrometry**: per exposure, Gaia DR3 field stars (G ≤ 17.5) give the exposure's offset (sigma-clipped weighted mean); their leave-one-out residuals give an empirical systematic floor | [5][6] | needs ≥ 3 field stars per exposure (300″ cutouts) |
| Association | a detection > 6″ from the predicted (calibrated) position is rejected as a neighbouring source | | |
| Errors | Jacobian covariance × max(1, χ²ᵣ); pull width verified = 1 in tests | [8] | systematic floor configurable, default 0 |
| Motion | weighted linear fit after removing catalogue parallax; z-score vs Gaia | [6][10] | ≥ 3 epochs over ≥ 0.1 yr |
| Variability | χ² of constant flux within 2 % wavelength bins, p < 10⁻³; errors include a fractional floor measured from field stars; aperture placed at prediction + exposure offset | [9] | saturated cores → PSF-wing flux, compared only with itself |
| Photocentre | correlation of position residuals with brightness (relative to a smooth SED) and with wavelength; flags variability-induced / chromatic centre-of-light shifts of unresolved pairs | | diagnostic only |
| Spectrum | the same forced-aperture fluxes ordered by wavelength → approximate 0.75–5 µm SED, coloured by date | [1][2] | aperture flux; PSF size varies with λ; not a calibrated spectrum |
| Controls | all calibrated Gaia field stars, corrected with leave-one-out offsets, must reproduce their Gaia motion (≤ 10 % with \|z\| > 3) | [5] | |
| Injection | synthetic moving source added to real cutouts, recovered by production code | — | labelled INJECTED |
| Not implemented | shift-and-stack for sub-threshold movers | [12] | future work |

Prior art for the blink/difference workflow: Backyard Worlds [11]. EpochLab's contribution is the
quantitative layer (epoch-propagated catalogue track, calibrated uncertainties, matched-λ photometry,
controls, reproducible dossier), not the animation itself.

## Tests

`pytest -q` — 42 tests on synthetic fixtures: epoch propagation (incl. textbook parallax formula),
centroid error calibration (pull σ ≈ 1 over 300 trials), motion-fit calibration (200 trials),
false-motion rate on static sources, flag handling, λ-matching vs naive comparison, MEF parsing with a
2-D `-TAB` spectral WCS, per-exposure WCS errors removed by field-star calibration (reproducing the failure first seen on real data), association gate, injection–recovery, PSF-wing photometry of saturated stars, SIMBAD→Sesame name-resolution fallback, end-to-end pipeline, reproducibility, API (incl. path traversal / bad IDs).

## Credits and licences

Narvalis source code and accompanying software documentation are available under the [MIT License](LICENSE).
Third-party software, fonts and data remain subject to their respective licences and terms of use.

Full bibliography: `docs/REFERENCES.md`.


Data: SPHEREx (NASA/JPL-Caltech) via NASA/IPAC IRSA — cite the release DOIs (DR1 images 10.26131/IRSA678,
QR 10.26131/IRSA662) listed in each dossier's collection. Gaia DR3 (ESA/DPAC), SIMBAD (CDS),
Aladin Lite (CDS) for context imagery. Built with Astropy, astroquery, PyVO, SciPy, reproject, FastAPI. Sky context uses Aladin Lite 3.9.2 (CDS), bundled unmodified
under LGPL-3.0 in `web/vendor/aladin-lite/`; its 2MASS tiles (1997–2001) are for orientation only and are relayed
through the server (`/api/sky/…`, allow-listed and cached) so they load even when the browser cannot reach CDS. Interface fonts: Doto, Space Grotesk and
Space Mono, self-hosted under the SIL Open Font License 1.1 (`web/fonts/OFL-*.txt`). The customisable cockpit layout
uses GridStack.js 12.6.0, bundled unmodified under the MIT licence in `web/vendor/gridstack/`.
Independent student project, not endorsed by NASA, Caltech, IPAC or ESA.

## Interface layouts

On desktop the page opens in **Cockpit** mode: every part of the interface (viewer, target, time sequence, motion,
brightness, spectrum, checks, frame details, targets, analyses, sky context, exports) is a module on a 12-column grid.
The layout button in the header switches between Cockpit and the Classic three-column page, applies presets
(Default, Astrometry, Variability, Present) and enters *Customise*, where modules are dragged by their title bar,
resized from their edges or hidden. The layout is stored only in the browser (localStorage key `epochlab_layout_v1`).
Modules are the same page elements moved into the grid, so the analysis and its numbers are identical in both
layouts. Phones always use the stacked mobile interface. The guided tour (? button) adapts to whichever layout is on screen and skips hidden modules.

## Known warnings (silenced)

- `ERFA pmsafe ... distance overridden (Note 6)`: stars without a usable parallax get ERFA's default distance;
  only the negligible radial-velocity term is affected.
- `SIP distortion coefficients are being applied ... append "-SIP"`: SPHEREx headers carry SIP distortion with a
  TAN projection; astropy applies it to sky positions (intended), and the spectral WCS drops it explicitly.
