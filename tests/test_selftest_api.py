"""The self-test endpoint is refused to anyone but the local machine (no process is started here)."""
from fastapi.testclient import TestClient

import epochlab.api as api


def test_selftest_refused_for_remote_clients():
    c = TestClient(api.app, client=("203.0.113.7", 50000))
    assert c.post("/api/selftest").status_code == 403
    assert c.get("/api/selftest").status_code == 403


def test_selftest_status_without_a_run():
    c = TestClient(api.app, client=("127.0.0.1", 50000))
    r = c.get("/api/selftest")
    assert r.status_code == 200 and r.json()["state"] in ("never started", "running") or r.json()["state"].startswith("finished")
