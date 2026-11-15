"""Sky-tile relay: allow-list, path validation, caching (CDS mocked; no network)."""
import httpx
import pytest
from fastapi.testclient import TestClient

import epochlab.api as api
from epochlab.config import Settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "settings", Settings(data_dir=tmp_path))
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return httpx.Response(200, content=b"\xff\xd8fakejpeg" if url.endswith(".jpg") else
                              b"hips_order = 9\nhips_service_url = https://alasky.cds.unistra.fr/2MASS/Color\nhips_service_url_1 = http://x\n")
    monkeypatch.setattr(httpx, "get", fake_get)
    return TestClient(api.app), calls


def test_allowed_tile_is_fetched_once_then_cached(client):
    c, calls = client
    for _ in range(2):
        r = c.get("/api/sky/2MASS/Color/Norder3/Dir0/Npix123.jpg")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert calls == ["https://irsa.ipac.caltech.edu/data/hips/CDS/2MASS/Color/Norder3/Dir0/Npix123.jpg"]
    pr = c.get("/api/sky/2MASS/Color/properties")
    assert pr.status_code == 200 and b"hips_order = 9" in pr.content and b"hips_service_url" not in pr.content


@pytest.mark.parametrize("url", ["/api/sky/evil/Survey/properties", "/api/sky/2MASS/Color/../../etc/passwd",
                                 "/api/sky/2MASS/Color/Norder3/Dir0/x.php", "/api/sky/2MASS/Color/index.html"])
def test_rejects_anything_else(client, url):
    c, calls = client
    assert c.get(url).status_code in (400, 404)
    assert calls == []


def test_properties_fall_back_to_the_next_cds_mirror(tmp_path, monkeypatch):
    """One mirror answering 404 (alasky showed 'page unavailable' in Nov 2026) must not end the sky context."""
    monkeypatch.setattr(api, "settings", Settings(data_dir=tmp_path))
    monkeypatch.setattr(api, "_hips_good", {})
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return httpx.Response(404 if "//irsa." in url else 200, content=b"hips_order = 9\n")
    monkeypatch.setattr(httpx, "get", fake_get)
    c = TestClient(api.app)
    r = c.get("/api/sky/2MASS/Color/properties")
    assert r.status_code == 200 and calls[0].startswith("https://irsa.") and calls[1].startswith("https://alasky.cds")
    c.get("/api/sky/2MASS/Color/Norder3/Dir0/Npix1.jpg")
    assert calls[-1].startswith("https://alasky.cds")          # the mirror that answered is tried first afterwards


def test_all_mirrors_failing_reports_each(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "settings", Settings(data_dir=tmp_path))
    monkeypatch.setattr(api, "_hips_good", {})
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(404))
    r = TestClient(api.app).get("/api/sky/2MASS/Color/properties")
    assert r.status_code == 404 and "alaskybis" in r.json()["detail"] and "irsa" in r.json()["detail"]
