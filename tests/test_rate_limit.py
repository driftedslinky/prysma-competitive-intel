"""Tests for the per-IP rate limit on the credit-spending web endpoints. Network calls are stubbed."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from prysma.storage.database import Database
from prysma.config import config
from prysma.web import app as web_app


def _request(host):
    """A minimal stand-in for a Starlette Request."""
    return type("R", (), {"client": type("C", (), {"host": host})()})()


@pytest.fixture
def client(tmp_path):
    web_app._rate_hits.clear()
    with patch("prysma.web.app.db", Database(str(tmp_path / "test.db"))):
        yield TestClient(web_app.app)
    web_app._rate_hits.clear()


def test_rate_limit_returns_429_after_cap(client):
    analyst = MagicMock()
    analyst.generate_gap_analysis.return_value = "stub report"
    with patch("prysma.agents.analyst.AnalystAgent", return_value=analyst):
        for _ in range(web_app.RATE_LIMIT_PER_HOUR):
            assert client.post("/api/gaps").status_code == 200
        resp = client.post("/api/gaps")
    assert resp.status_code == 429
    assert resp.json() == {"error": "Rate limit reached for now. Try again later."}
    assert analyst.generate_gap_analysis.call_count == web_app.RATE_LIMIT_PER_HOUR


def test_limit_is_shared_across_credit_endpoints(client):
    web_app._rate_hits["testclient"] = web_app.deque(
        [web_app.time.monotonic()] * web_app.RATE_LIMIT_PER_HOUR
    )
    with patch("prysma.sources.tavily_search.TavilySource") as tavily, \
         patch.object(web_app.config, "tavily_api_key", "test-key"):
        resp = client.get("/api/tavily", params={"query": "timer"})
    assert resp.status_code == 429
    tavily.assert_not_called()


def test_old_hits_leave_the_window(client):
    old = web_app.time.monotonic() - web_app.RATE_LIMIT_WINDOW_SECONDS - 1
    web_app._rate_hits["testclient"] = web_app.deque([old] * web_app.RATE_LIMIT_PER_HOUR)
    analyst = MagicMock()
    analyst.generate_gap_analysis.return_value = "stub report"
    with patch("prysma.agents.analyst.AnalystAgent", return_value=analyst):
        assert client.post("/api/gaps").status_code == 200


def test_status_is_never_rate_limited(client):
    web_app._rate_hits["testclient"] = web_app.deque(
        [web_app.time.monotonic()] * web_app.RATE_LIMIT_PER_HOUR
    )
    for _ in range(web_app.RATE_LIMIT_PER_HOUR * 2):
        assert client.get("/api/status").status_code == 200


def test_api_docs_are_disabled(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_bucket_map_never_grows_past_its_cap(client, monkeypatch):
    """Many distinct clients must not grow the map without bound.

    The first version pruned only when the map was already *over* the cap and
    inserted the new client afterwards, so it settled one over.
    """
    cap = 50
    monkeypatch.setattr(web_app, "RATE_LIMIT_MAX_CLIENTS", cap)
    web_app._rate_hits.clear()

    worst = 0
    for i in range(cap * 4):
        web_app._rate_limited(_request(f"10.0.0.{i}"))
        worst = max(worst, len(web_app._rate_hits))

    assert worst <= cap, f"tracked {worst} clients against a cap of {cap}"


def test_a_returning_client_is_not_evicted_by_itself(client, monkeypatch):
    cap = 10
    monkeypatch.setattr(web_app, "RATE_LIMIT_MAX_CLIENTS", cap)
    web_app._rate_hits.clear()
    for i in range(cap):
        web_app._rate_limited(_request(f"10.0.1.{i}"))

    web_app._rate_limited(_request("10.0.1.0"))  # a client already in the map

    assert "10.0.1.0" in web_app._rate_hits


def test_trusted_proxies_does_not_trust_everyone():
    """A '*' allow-list lets any caller forge X-Forwarded-For and pick its own bucket."""
    assert config.web_trusted_proxies != "*"
    assert config.web_trusted_proxies.strip(), "must name the proxy network"
