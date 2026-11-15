"""End-to-end pipeline + API on SYNTHETIC MEF files (archive and catalogues are mocked).

Verifies wiring, dossier completeness, verdict logic, reproducibility and that synthetic inputs are
labelled as such. It says nothing about performance on real SPHEREx data (see scripts/selftest_real.py).
"""
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import epochlab.pipeline as pl
import epochlab.references as refs
from epochlab.archive import Observation, Download
from epochlab.astrometry import AstrometricReference, predict_position
from epochlab.config import Settings
from conftest import make_mef

MOVER = AstrometricReference(150.0, 20.0, 2026.0, 3000.0, -2000.0, parallax_mas=200.0,
                             source="SYNTHETIC mover", pmra_err=0.1, pmdec_err=0.1)
CONTROL = AstrometricReference(150.0 + 40 / 3600 / np.cos(np.radians(20)), 20.0 - 30 / 3600, 2016.0, 0.5, -0.3,
                               parallax_mas=1.0, source="SYNTHETIC control", pmra_err=0.05, pmdec_err=0.05)
_r = np.random.default_rng(7)
FIELD = [CONTROL] + [AstrometricReference(150.0 + dx / 3600 / np.cos(np.radians(20)), 20.0 + dy / 3600, 2016.0,
                                          float(_r.normal(0, 8)), float(_r.normal(0, 8)), parallax_mas=float(_r.uniform(0.2, 3)),
                                          source=f"SYNTHETIC field {k}", pmra_err=0.05, pmdec_err=0.05)
                     for k, (dx, dy) in enumerate([(-90, 70), (100, 95), (-110, -85), (75, -110), (-40, 120),
                                                   (115, 10), (-120, 15), (20, -125)])]


def _archive(tmp_path, monkeypatch, wcs_err_sigma=0.0):
    rng = np.random.default_rng(2026)
    mjds = np.sort(np.concatenate([b + rng.uniform(0, 8, 4) for b in (60800, 60985, 61170, 61355)]))
    lam_choices = [1.2, 2.4, 3.6, 4.4]
    obs, files = [], {}
    for k, m in enumerate(mjds):
        lam0 = lam_choices[k % 4] + rng.uniform(0, 0.005)
        ra_m, dec_m = predict_position(MOVER, m, True)
        amp = 40.0 * (lam0 / 1.5) ** -1.5  # constant in time, steep in wavelength
        srcs = [(ra_m, dec_m, amp)] + [(*predict_position(fs, m, True), 30.0) for fs in FIELD]
        err = tuple(rng.normal(0, wcs_err_sigma, 2)) if wcs_err_sigma else (0.0, 0.0)
        p = make_mef(tmp_path / f"f{k:02d}.fits", ra0=150.0, dec0=20.0, mjd=m, sources=srcs, n=49,
                     rot_deg=float(rng.uniform(0, 360)), noise=1.0, lam0=lam0, dlam_dy=0.0002, rng=rng,
                     wcs_error_arcsec=err)
        url = f"synthetic://frame/{k:02d}"
        files[url] = p
        obs.append(Observation(f"syn{k:02d}", "synthetic", url, m - 0.001, m + 0.001, None, None, "D1", "test", None))

    monkeypatch.setattr(pl, "query_observations", lambda ra, dec, s, c, log=None: list(obs))

    def fake_fetch_many(urls, s):
        out = []
        for u in urls:
            base = u.split("?")[0]
            data = Path(files[base]).read_bytes()
            import hashlib
            out.append(Download(u, str(files[base]), hashlib.sha256(data).hexdigest(), len(data), True, "n/a", None))
        return out
    monkeypatch.setattr(pl, "fetch_many", fake_fetch_many)
    monkeypatch.setattr(pl, "field_references", lambda *a, **k: list(FIELD))
    s = Settings(data_dir=tmp_path / "data", cutout_query="")
    return s


@pytest.fixture
def synthetic_archive(tmp_path, monkeypatch):
    return _archive(tmp_path, monkeypatch, 0.0)


@pytest.fixture
def synthetic_archive_wcs_errors(tmp_path, monkeypatch):
    """Per-exposure astrometric zero-point errors of 1.2" rms — the failure mode seen in real data."""
    return _archive(tmp_path, monkeypatch, 1.2)


def _req():
    return pl.AnalysisRequest(ra_deg=MOVER.ra_deg, dec_deg=MOVER.dec_deg, ref_pmra=MOVER.pmra_masyr,
                              ref_pmdec=MOVER.pmdec_masyr, ref_parallax=MOVER.parallax_mas, ref_epoch=2026.0,
                              n_controls=1)


def test_end_to_end_synthetic(synthetic_archive):
    s = synthetic_archive
    jd = pl.analyze(_req(), s, job_id="aaaaaaaaaaaa")
    d = json.loads((jd / "dossier.json").read_text())
    assert d["data_kind"].startswith("SYNTHETIC")
    v = {x["check"]: x["result"] for x in d["verdicts"]}
    assert v["data_provenance"] == "PASS"
    assert v["detection"] == "PASS"
    assert v["motion_detected"] == "YES"
    assert v["proper_motion_vs_catalogue"] == "CONSISTENT", d["results"]["motion"]
    assert v["field_star_controls"] == "PASS", d["results"]["controls"]
    assert v["astrometric_calibration"] == "PASS", d["results"]["calibration"]
    # constant source with steep spectrum: matched-wavelength test must NOT call it variable
    assert v["variability_matched_wavelength"] == "NO EVIDENCE", d["results"]["variability"]
    f0 = d["frames"][0]
    for key in ("observation", "download", "time_mjd", "wavelength_um", "predicted", "centroid", "photometry", "display"):
        assert key in f0
    assert (jd / f0["display"]["png"]).exists()
    # frames of the same wavelength bin share one display scale
    from epochlab.photometry import wavelength_bins
    ok = [f for f in d["frames"] if f.get("status") == "ok"]
    b = wavelength_bins([f["wavelength_um"] for f in ok], d["settings"]["wavelength_bin_rel"])
    for k in set(b.tolist()):
        scales = {(f["display"]["stretch"]["vmin"], f["display"]["stretch"]["vmax"]) for f, bb in zip(ok, b) if bb == k}
        assert len(scales) == 1
    assert d["display_grid"]["resampling"] == "nearest-neighbour"
    sed = d["results"]["sed"]
    n_phot = sum(1 for f in ok if f["photometry"]["ok"])
    assert sed["n"] == n_phot > 0
    lams = [p["lambda_um"] for p in sed["points"]]
    assert lams == sorted(lams)
    # synthetic source flux falls steeply with wavelength (amp ∝ λ^-1.5): the SED must show it
    blue = [p["flux_ujy"] for p in sed["points"] if p["lambda_um"] < 1.5]
    red = [p["flux_ujy"] for p in sed["points"] if p["lambda_um"] > 4.0]
    assert min(blue) > max(red)
    assert any("diff_png" in f["display"] for f in d["frames"])
    m = d["results"]["motion"]
    assert abs(m["pmra_masyr"] - 3000) < 5 * m["pmra_err"] and m["pmra_err"] < 200


def test_reproduce_is_identical(synthetic_archive):
    s = synthetic_archive
    jd = pl.analyze(_req(), s, job_id="bbbbbbbbbbbb")
    out = pl.reproduce(jd / "dossier.json", s)
    assert out["identical_results"], out
    assert out["files_compared"] == 16


def test_api_job_lifecycle(synthetic_archive, monkeypatch):
    import time
    import epochlab.api as api
    from fastapi.testclient import TestClient
    monkeypatch.setattr(api, "settings", synthetic_archive)
    c = TestClient(api.app)
    assert c.get("/api/health").json()["ok"]
    assert c.post("/api/jobs", json={}).status_code == 422
    assert c.post("/api/jobs", json={"ra_deg": 400, "dec_deg": 0}).status_code == 422
    r = c.post("/api/jobs", json={"ra_deg": MOVER.ra_deg, "dec_deg": MOVER.dec_deg, "ref_pmra": 3000,
                                  "ref_pmdec": -2000, "ref_parallax": 200, "ref_epoch": 2026.0, "n_controls": 1})
    jid = r.json()["job_id"]
    for _ in range(240):
        st = c.get(f"/api/jobs/{jid}/status.json").json()
        if st["state"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert st["state"] == "done", st
    d = c.get(f"/api/jobs/{jid}/dossier.json").json()
    assert d["job_id"] == jid
    assert c.get(f"/api/jobs/{jid}/frames/000.png").status_code == 200
    assert c.get(f"/api/jobs/{jid}/frames/../../etc/passwd").status_code in (400, 404)
    assert c.get("/api/jobs/not-a-job/dossier.json").status_code == 400
    z = c.get(f"/api/jobs/{jid}/bundle.zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"
    assert any(j["job_id"] == jid for j in c.get("/api/jobs").json()["jobs"])


def test_wcs_errors_break_raw_astrometry_and_calibration_fixes_it(synthetic_archive_wcs_errors):
    """Reproduces the real-data failure (per-exposure WCS errors) and shows the field-star fix."""
    s = synthetic_archive_wcs_errors
    # 1) without field calibration (use_gaia=False, manual reference): formal errors are far too small
    raw = pl.AnalysisRequest(**{**_req().to_dict(), "use_gaia": False})
    d0 = json.loads((pl.analyze(raw, s, job_id="cccccccccccc") / "dossier.json").read_text())
    m0 = d0["results"]["motion"]
    assert m0["reduced_chi2_linear"] > 3 and not m0["calibrated"]
    # 2) with field calibration: consistent with the catalogue, realistic errors, controls pass
    d1 = json.loads((pl.analyze(_req(), s, job_id="dddddddddddd") / "dossier.json").read_text())
    m1 = d1["results"]["motion"]
    v = {x["check"]: x["result"] for x in d1["verdicts"]}
    assert m1["calibrated"] and m1["reduced_chi2_linear"] < 2.5, m1
    assert v["proper_motion_vs_catalogue"] == "CONSISTENT", m1
    assert v["field_star_controls"] == "PASS", d1["results"]["controls"]


def test_association_gate_rejects_neighbours(synthetic_archive):
    """A detection far from the predicted track (here: a wrong catalogue motion) must not count."""
    s = synthetic_archive
    wrong = pl.AnalysisRequest(**{**_req().to_dict(), "ref_pmra": -3000.0, "ref_pmdec": 2000.0})
    d = json.loads((pl.analyze(wrong, s, job_id="eeeeeeeeeeee") / "dossier.json").read_text())
    reasons = [f["centroid"]["reason"] for f in d["frames"] if f.get("status") == "ok" and not f["centroid"]["ok"]]
    assert any("neighbouring source" in r for r in reasons)


def test_injection_recovery_on_calibrated_dossier(synthetic_archive_wcs_errors):
    from epochlab.injection import inject_recover
    s = synthetic_archive_wcs_errors
    jd = pl.analyze(_req(), s, job_id="ffffffffffff")
    r = inject_recover(jd / "dossier.json", 2000.0, -1500.0, snr=20, settings=s)
    assert r["data_kind"].startswith("INJECTED")
    assert r["epochs_recovered"] >= 5 and r["recovered_within_3sigma"], r


def test_stale_running_jobs_are_marked_after_restart(tmp_path, monkeypatch):
    import epochlab.api as api
    from epochlab.config import Settings
    monkeypatch.setattr(api, "settings", Settings(data_dir=tmp_path))
    for jid, state in (("aaaaaaaaaaa1", "running"), ("aaaaaaaaaaa2", "done"), ("aaaaaaaaaaa3", "queued")):
        api._write_status(jid, state=state, progress=0.8, message="x")
    assert api.mark_interrupted_jobs() == 2
    states = {p.parent.name: json.loads(p.read_text())["state"] for p in (tmp_path / "jobs").glob("*/status.json")}
    assert states == {"aaaaaaaaaaa1": "failed", "aaaaaaaaaaa2": "done", "aaaaaaaaaaa3": "failed"}
