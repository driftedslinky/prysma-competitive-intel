"""Tests for the per-IP rate limit on the credit-spending web endpoints. Network calls are stubbed."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from prysma.storage.database import Database
from prysma.web import app as web_app


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
