"""Local-network-only actions must not be reachable from the internet through a reverse proxy."""
import json

import pytest
from fastapi.testclient import TestClient

from epochlab import api

JOB = "abcdefabcdef"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api.settings, "data_dir", tmp_path)
    d = tmp_path / "jobs" / JOB
    d.mkdir(parents=True)
    (d / "status.json").write_text(json.dumps({"state": "done"}))  # finished, no owner token
    return TestClient(api.app)


def test_public_client_behind_proxy_cannot_delete(client):
    assert client.delete(f"/api/jobs/{JOB}", headers={"X-Forwarded-For": "8.8.8.8"}).status_code == 403


def test_forged_private_address_before_public_one_is_ignored(client):
    assert client.delete(f"/api/jobs/{JOB}", headers={"X-Forwarded-For": "127.0.0.1, 8.8.8.8"}).status_code == 403


def test_public_client_cannot_start_selftest():
    assert TestClient(api.app).post("/api/selftest", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 403


def test_lan_client_behind_proxy_may_delete(client):
    assert client.delete(f"/api/jobs/{JOB}", headers={"X-Forwarded-For": "192.168.1.20"}).status_code == 200


def test_trusted_public_network_can_delete_through_proxy(client, monkeypatch):
    monkeypatch.setenv("EPOCHLAB_TRUSTED_NETS", "1.2.3.0/24")
    assert client.delete(f"/api/jobs/{JOB}", headers={"X-Forwarded-For": "8.8.4.4"}).status_code == 403
    assert client.delete(f"/api/jobs/{JOB}", headers={"X-Forwarded-For": "1.2.3.7"}).status_code == 200
