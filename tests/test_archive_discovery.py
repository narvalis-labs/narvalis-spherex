"""SIA2 discovery fallbacks (pyvo and astroquery mocked; no network)."""
from astropy.table import Table

import epochlab.archive as ar
from epochlab.config import Settings


def _table(n, coll):
    return Table({"access_url": [f"https://x/{coll}/f{i}.fits" for i in range(n)],
                  "obs_collection": [coll] * n, "access_format": ["image/fits"] * n,
                  "dataproduct_type": ["image"] * n, "t_min": [61000.0 + i for i in range(n)],
                  "t_max": [61000.01 + i for i in range(n)], "obs_id": [f"{coll}{i}" for i in range(n)]})


class FakeSvc:
    def __init__(self, data):
        self.data, self.calls = data, []

    def search(self, pos, maxrec, collection=None):
        self.calls.append(collection)
        t = self.data.get(collection, _table(0, "none"))
        return type("R", (), {"to_table": lambda self_: t})()


def _patch(monkeypatch, data, discovered):
    svc = FakeSvc(data)
    import pyvo
    monkeypatch.setattr(pyvo.dal, "SIA2Service", lambda url, **kw: svc)
    monkeypatch.setattr(ar, "discover_collections", lambda: discovered)
    return svc


def test_configured_collection_used_when_it_has_data(monkeypatch):
    _patch(monkeypatch, {"spherex_qr": _table(3, "spherex_qr")}, ["spherex_dr1"])
    log = []
    obs = ar.query_observations(1, 2, Settings(collections=("spherex_qr",)), log=log)
    assert len(obs) == 3 and "configured" in log[0]


def test_falls_back_to_discovered_collections(monkeypatch):
    svc = _patch(monkeypatch, {"spherex_dr1": _table(4, "spherex_dr1"), "spherex_qr3": _table(2, "spherex_qr3")},
                 ["spherex_dr1", "spherex_qr3"])
    log = []
    obs = ar.query_observations(1, 2, Settings(collections=("wrong_name",)), log=log)
    assert len(obs) == 6 and svc.calls == ["wrong_name", "spherex_dr1", "spherex_qr3"]
    assert any("advertises" in l for l in log)


def test_unrestricted_fallback_filters_to_spherex(monkeypatch):
    mixed = _table(2, "spherex_quick")
    mixed.add_row(["https://x/wise/a.fits", "wise_allwise", "image/fits", "image", 1.0, 1.1, "w"])
    _patch(monkeypatch, {None: mixed}, [])
    obs = ar.query_observations(1, 2, Settings(collections=("auto",)))
    assert len(obs) == 2 and all("spherex" in o.collection for o in obs)


def test_duplicates_across_collections_removed(monkeypatch):
    t1, t2 = _table(3, "a"), _table(3, "a")
    _patch(monkeypatch, {"c1": t1, "c2": t2}, [])
    obs = ar.query_observations(1, 2, Settings(collections=("c1", "c2")))
    assert len(obs) == 3
