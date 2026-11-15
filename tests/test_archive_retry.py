"""Transient IRSA errors (HTTP 502 'Proxy Error') are retried; real errors are not. No network used."""
import pytest

import epochlab.archive as ar


def test_transient_502_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(ar.time, "sleep", lambda s: None)
    calls, log = {"n": 0}, []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("DALServiceError: 502 Server Error: Proxy Error for url: https://irsa.ipac.caltech.edu/SIA")
        return "ok"
    assert ar._retry(flaky, "SIA2", log) == "ok"
    assert calls["n"] == 3 and len(log) == 2 and "retry 1/3" in log[0]


def test_non_transient_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(ar.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def bad():
        calls["n"] += 1
        raise ValueError("bad collection name")
    with pytest.raises(ValueError):
        ar._retry(bad, "SIA2", [])
    assert calls["n"] == 1


def test_persistent_502_gives_up_after_all_attempts(monkeypatch):
    monkeypatch.setattr(ar.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def down():
        calls["n"] += 1
        raise RuntimeError("502 Server Error: Proxy Error")
    with pytest.raises(RuntimeError):
        ar._retry(down, "SIA2", [])
    assert calls["n"] == 4



def test_capabilities_endpoint_is_not_needed(monkeypatch):
    """The SIA2 client is built straight on the query endpoint: no /capabilities request (IRSA 502s it)."""
    import pyvo
    from epochlab.config import Settings
    monkeypatch.setattr(ar.time, "sleep", lambda s: None)
    seen = {}
    real = pyvo.dal.SIA2Service

    def spy(url, **kw):
        seen.update(kw, url=url)
        svc = real(url, **kw)
        svc.search = lambda **k: (_ for _ in ()).throw(RuntimeError("502 Server Error: Proxy Error"))
        return svc
    monkeypatch.setattr(pyvo.dal, "SIA2Service", spy)
    monkeypatch.setattr(ar, "discover_collections", lambda: [])
    log = []
    assert ar.query_observations(1.0, 2.0, Settings(), log=log) == []
    assert seen["check_baseurl"] is False
    assert any("retry 3/3" in l for l in log) and any("unrestricted search failed" in l for l in log)
