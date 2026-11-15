"""Nov 2026 precision upgrades: hybrid detection test for saturated stars, Gaia mirror cache."""
import json

import numpy as np
from astropy.wcs import WCS

from epochlab.astrometry import fit_centroid


def _wcs():
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [180.0, 0.0]
    w.wcs.crpix = [32.0, 32.0]
    w.wcs.cdelt = [-6.2 / 3600, 6.2 / 3600]
    return w


def _star(amp, x0=31.3, y0=30.8, s=1.0, noise=1.0, seed=1):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:64, 0:64]
    img = amp * np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * s * s)) + rng.normal(0, noise, (64, 64))
    return img, np.full((64, 64), noise ** 2)


def test_saturated_core_is_kept_by_hybrid_but_lost_by_amplitude():
    img, var = _star(5000.0)
    bad = np.zeros_like(img, bool)
    yy, xx = np.mgrid[0:64, 0:64]
    bad[np.hypot(xx - 31.3, yy - 30.8) < 1.8] = True          # saturated, flagged core
    img[bad] = 0.0
    # mimic the real failure mode: model mismatch in the wings inflates chi2
    img += 40.0 * np.exp(-((xx - 31.3) ** 2 + (yy - 30.8) ** 2) / (2 * 3.0 ** 2))
    w = _wcs()
    amp = fit_centroid(img, var, bad, w, 31.0, 31.0, detection="amplitude", min_snr=5.0)
    hyb = fit_centroid(img, var, bad, w, 31.0, 31.0, detection="hybrid", min_snr=5.0)
    assert hyb.ok, hyb.reason
    assert hyb.core_flagged_px >= 3
    assert abs(hyb.x - 31.3) < 0.1 and abs(hyb.y - 30.8) < 0.1
    assert hyb.snr_detection > hyb.snr_amplitude
    # the amplitude test is what rejected 30/80 Barnard exposures; it must stay available but stricter
    assert amp.snr_amplitude == hyb.snr_amplitude


def test_hybrid_equals_amplitude_for_unsaturated_faint_source():
    img, var = _star(4.0, seed=3)
    bad = np.zeros_like(img, bool)
    w = _wcs()
    a = fit_centroid(img, var, bad, w, 31.0, 31.0, detection="amplitude")
    h = fit_centroid(img, var, bad, w, 31.0, 31.0, detection="hybrid")
    assert h.core_flagged_px == 0
    assert (a.ok, a.reason, a.snr) == (h.ok, h.reason, h.snr)


def test_gaia_cone_reads_cache_without_network(tmp_path, monkeypatch):
    from epochlab import references
    from epochlab.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    rows = [{"source_id": 4472832130942575872, "ra": 269.4485, "dec": 4.7394, "pmra": -801.55, "pmdec": 10362.39,
             "pmra_error": 0.03, "pmdec_error": 0.04, "parallax": 546.98, "radial_velocity": None,
             "phot_g_mean_mag": 8.19, "ref_epoch": 2016.0}]
    p = references._gaia_cache_path(269.4486, 4.7398, 10.0, 200)
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"service": "GAVO Heidelberg mirror", "query": "q", "rows": rows}))
    monkeypatch.setattr(references, "_tap_sync", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    tab, q = references.gaia_cone(269.4486, 4.7398, 10.0)
    assert "cached" in q and len(tab) == 1
    assert np.ma.is_masked(tab[0]["radial_velocity"])
    ref = references._from_gaia_row(tab[0])
    assert ref.source == "Gaia DR3 4472832130942575872" and ref.rv_kms is None


def test_gaia_cone_falls_back_to_mirror(tmp_path, monkeypatch):
    from astropy.table import Table
    from epochlab import references
    from epochlab.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    calls = []

    def fake(url, q):
        calls.append(url)
        if "esa" in url:
            raise TimeoutError("ESA down")
        return Table({f: [1.0] for f in references.GAIA_FIELDS})
    monkeypatch.setattr(references, "_tap_sync", fake)
    tab, q = references.gaia_cone(10.0, 10.0, 30.0)
    assert len(calls) == 2 and "GAVO" in q and len(tab) == 1
    tab2, q2 = references.gaia_cone(10.0, 10.0, 30.0)     # second call: cache, no network
    assert len(calls) == 2 and "cached" in q2


def _synthetic_track(plx_mas, n=60, noise=0.05, seed=0):
    from epochlab.astrometry import AstrometricReference, predict_positions
    rng = np.random.default_rng(seed)
    ref = AstrometricReference(331.0, -56.8, 2016.0, 3982.0, -2467.0, plx_mas, None, source="synthetic")
    # SPHEREx-like sampling: three visibility windows over ~1.4 yr
    t = np.sort(np.concatenate([rng.uniform(60900, 60930, n // 3), rng.uniform(61080, 61110, n // 3),
                                rng.uniform(61270, 61300, n - 2 * (n // 3))]))
    ra, dec = predict_positions(ref, t, True)
    ra = ra + rng.normal(0, noise, n) / 3600 / np.cos(np.radians(dec))
    dec = dec + rng.normal(0, noise, n) / 3600
    return ref, t, ra, dec, np.full(n, noise), np.full(n, noise)


def test_parallax_recovered_without_catalogue_input():
    from epochlab.astrometry import fit_parallax
    ref, t, ra, dec, sx, sy = _synthetic_track(270.0)
    r = fit_parallax(t, ra, dec, sx, sy, ref)
    assert r["ok"] and abs(r["parallax_mas"] - 270.0) < 3 * r["parallax_err_mas"]
    assert r["significance"] > 10 and abs(r["z_vs_catalogue"]) < 3
    assert abs(r["pmra_masyr"] - 3982.0) < 3 * r["pmra_err"]
    assert 3.0 < r["distance_pc"] < 4.5


def test_distant_star_gives_lower_limit():
    from epochlab.astrometry import fit_parallax
    ref, t, ra, dec, sx, sy = _synthetic_track(1.0, noise=0.3)
    r = fit_parallax(t, ra, dec, sx, sy, None)
    assert r["ok"] and r["distance_pc"] is None and r["distance_lower_limit_pc_3sigma"] > 1.0


def test_parallax_verdict_refuses_saturated_targets():
    from epochlab.pipeline import _parallax_verdict
    pf = {"ok": True, "parallax_mas": 975.0, "parallax_err_mas": 38.0, "catalogue_parallax_mas": 547.0,
          "z_vs_catalogue": 11.3, "saturated_epoch_fraction": 0.99, "distance_pc_range_1sigma": [1.0, 1.1]}
    ctr = {"parallax_n_stars": 40, "parallax_frac_abs_z_gt_3": 0.0, "parallax_z_std": 0.8}
    d = {"results": {"motion": {"parallax_fit": pf}, "controls": ctr, "photocentre": {}}}
    assert _parallax_verdict(d)[0]["result"] == "NOT RELIABLE"
    pf.update(parallax_mas=300.0, parallax_err_mas=46.0, catalogue_parallax_mas=271.0, z_vs_catalogue=0.6,
              saturated_epoch_fraction=0.0, distance_pc_range_1sigma=[2.9, 3.9])
    v = _parallax_verdict(d)[0]
    assert v["result"] == "MEASURED" and "3.3 pc" in v["detail"]


def test_known_neighbour_fit_removes_blend_bias():
    """A neighbour 2 px (12") away pulls a plain fit; fitting it at its known position removes the bias."""
    rng = np.random.default_rng(5)
    yy, xx = np.mgrid[0:64, 0:64]
    g = lambda x0, y0, a: a * np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / 2.0)
    img = g(31.2, 30.9, 60.0) + g(33.2, 30.9, 40.0) + rng.normal(0, 1.0, (64, 64))
    var = np.ones((64, 64)); bad = np.zeros((64, 64), bool); w = _wcs()
    plain = fit_centroid(img, var, bad, w, 31.0, 31.0, detection="amplitude")
    deb = fit_centroid(img, var, bad, w, 31.0, 31.0, detection="amplitude", neighbours=[(33.2, 30.9)])
    assert deb.ok and deb.n_neighbours_fitted == 1
    assert abs(plain.x - 31.2) > 0.3                     # the blend pulls the plain fit
    assert abs(deb.x - 31.2) < 0.1 and abs(deb.y - 30.9) < 0.1


def test_parallax_plot_data_follow_the_ellipse():
    """Visit-averaged parallax residuals must lie on the fitted ellipse (synthetic star, small noise)."""
    from epochlab.astrometry import fit_parallax, parallax_factors
    ref, t, ra, dec, sx, sy = _synthetic_track(270.0, noise=0.02)
    r = fit_parallax(t, ra, dec, sx, sy, ref)
    pl = r["plot"]
    assert len(pl["visits"]) == 3 and len(pl["unit_ellipse"]) > 80
    for mjd, dx, dy, ex, ey, n in pl["visits"]:
        fx, fy = parallax_factors([mjd], float(np.mean(ra)), float(np.mean(dec)))
        assert abs(dx - fx[0] * 1000 * r["parallax_mas"]) < 4 * ex + 15
        assert abs(dy - fy[0] * 1000 * r["parallax_mas"]) < 4 * ey + 15
