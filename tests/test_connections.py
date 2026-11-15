from fastapi.testclient import TestClient

from epochlab import api


def test_connections_reports_every_service(monkeypatch, tmp_path):
    monkeypatch.setattr(api.settings, "data_dir", tmp_path)
    monkeypatch.setattr(api, "_probe_full", lambda url, head=False: {"state": "online", "http": 200, "ms": 12})
    api._conn_cache.update(t=0.0, data=None)
    r = TestClient(api.app).get("/api/connections?refresh=true").json()
    ids = [s["id"] for s in r["services"]]
    assert ids == ["irsa_sia", "irsa_tap", "irsa_files", "gaia", "sesame", "simbad", "sky"]
    by = {s["id"]: s for s in r["services"]}
    assert by["irsa_sia"]["state"] == "online" and by["irsa_sia"]["host"] == "irsa.ipac.caltech.edu"
    assert by["irsa_files"]["state"] == "untested"     # no real analysis in an empty data dir
