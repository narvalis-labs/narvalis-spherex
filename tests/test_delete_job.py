import json

from fastapi.testclient import TestClient

from epochlab import api


def _mk(tmp_path, job_id, state):
    d = tmp_path / "jobs" / job_id
    d.mkdir(parents=True)
    (d / "status.json").write_text(json.dumps({"state": state, "request": {"target_name": "X"}}))
    (d / "dossier.json").write_text("{}")
    return d


def test_delete_moves_to_trash_and_restores(tmp_path, monkeypatch):
    monkeypatch.setattr(api.settings, "data_dir", tmp_path)
    d = _mk(tmp_path, "aaaaaaaaaaaa", "done")
    c = TestClient(api.app)
    r = c.delete("/api/jobs/aaaaaaaaaaaa")
    assert r.status_code == 200 and not d.exists()
    assert [j["job_id"] for j in c.get("/api/trash").json()["jobs"]] == ["aaaaaaaaaaaa"]
    assert all(j["job_id"] != "aaaaaaaaaaaa" for j in c.get("/api/jobs").json()["jobs"])
    assert c.post("/api/trash/aaaaaaaaaaaa/restore").status_code == 200
    assert d.exists() and (d / "dossier.json").exists()
    assert c.get("/api/trash").json()["jobs"] == []
    assert c.post("/api/trash/aaaaaaaaaaaa/restore").status_code == 404


def test_refuse_running_and_bad_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(api.settings, "data_dir", tmp_path)
    d = _mk(tmp_path, "bbbbbbbbbbbb", "running")
    c = TestClient(api.app)
    assert c.delete("/api/jobs/bbbbbbbbbbbb").status_code == 409 and d.exists()
    assert c.delete("/api/jobs/..%2F..").status_code in (400, 404, 405)
    assert c.post("/api/trash/..%2F../restore").status_code in (400, 404, 405)


def test_private_network_allowed_public_refused():
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    ok = lambda h: api._local_or_private(SimpleNamespace(client=SimpleNamespace(host=h)))  # noqa: E731
    for h in ("127.0.0.1", "192.168.1.101", "10.0.0.5", "172.20.1.2", "::1"):
        ok(h)
    for h in ("8.8.8.8", "1.1.1.1"):
        with pytest.raises(HTTPException):
            ok(h)


def test_public_visitor_may_remove_failed_or_own_only(tmp_path, monkeypatch):
    """From the internet: someone else's analysis is protected; failed ones and your own (owner token) can go."""
    monkeypatch.setattr(api.settings, "data_dir", tmp_path)
    c = TestClient(api.app, client=("203.0.113.9", 50000))
    monkeypatch.setattr(api, "_local_or_private", lambda request: (_ for _ in ()).throw(api.HTTPException(403, "x")))
    other = _mk(tmp_path, "cccccccccccc", "done")
    assert c.delete("/api/jobs/cccccccccccc").status_code == 403 and other.exists()
    failed = _mk(tmp_path, "dddddddddddd", "failed")
    assert c.delete("/api/jobs/dddddddddddd").status_code == 200 and not failed.exists()
    assert c.post("/api/trash/dddddddddddd/restore").status_code == 200
    mine = _mk(tmp_path, "eeeeeeeeeeee", "done")
    st = json.loads((mine / "status.json").read_text())
    st["owner_sha256"] = api._sha("secret-token")
    (mine / "status.json").write_text(json.dumps(st))
    assert c.delete("/api/jobs/eeeeeeeeeeee", headers={"X-Narvalis-Owner": "wrong"}).status_code == 403
    assert c.delete("/api/jobs/eeeeeeeeeeee", headers={"X-Narvalis-Owner": "secret-token"}).status_code == 200
    assert c.post("/api/trash/eeeeeeeeeeee/restore").status_code == 403          # restoring also needs the token
    assert c.post("/api/trash/eeeeeeeeeeee/restore", headers={"X-Narvalis-Owner": "secret-token"}).status_code == 200


def test_create_job_returns_owner_token_and_stores_only_its_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(api.settings, "data_dir", tmp_path)
    monkeypatch.setattr(api._pool, "submit", lambda *a, **k: None)
    r = TestClient(api.app).post("/api/jobs", json={"ra_deg": 10.0, "dec_deg": 10.0})
    j = r.json()
    assert r.status_code == 200 and len(j["owner_token"]) > 16
    st = json.loads((tmp_path / "jobs" / j["job_id"] / "status.json").read_text())
    assert st["owner_sha256"] == api._sha(j["owner_token"]) and j["owner_token"] not in json.dumps(st)
