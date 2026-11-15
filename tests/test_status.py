"""/api/status reports per-service reachability (no network: the probe is replaced)."""
from fastapi.testclient import TestClient

import epochlab.api as api


def test_status_reports_each_service_and_caches(monkeypatch):
    calls = []

    def fake_probe(url):
        calls.append(url)
        return {"state": "degraded", "http": 502, "ms": 5} if "SIA" in url else {"state": "offline", "http": None, "ms": 9}
    monkeypatch.setattr(api, "_probe", fake_probe)
    api._status_cache.update(t=0.0, data=None)
    c = TestClient(api.app)
    d = c.get("/api/status").json()
    assert d["irsa"]["state"] == "degraded" and d["irsa"]["http"] == 502 and d["cds"]["state"] == "offline"
    c.get("/api/status")
    n = len(calls)                              # IRSA + every CDS mirror
    assert n == 1 + len(api.HIPS_MIRRORS["2MASS/Color"])
    c.get("/api/status")
    assert len(calls) == n                      # second call served from the 60 s cache
    c.get("/api/status?refresh=true")
    assert len(calls) == 2 * n
