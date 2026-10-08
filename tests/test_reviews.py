"""Tests for review collection and dedupe. All network calls are stubbed."""
import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from prysma.agents.competitive_intel import CompetitiveIntelAgent
from prysma.storage.database import Database


APP_STORE_FEED = {
    "feed": {
        "entry": [
            # Feed-metadata entry: no im:rating, must be skipped
            {"im:name": {"label": "Some App"}, "title": {"label": "Some App"}},
            {
                "im:rating": {"label": "2"},
                "title": {"label": "Too many ads"},
                "content": {"label": "  Too many <b>ads</b>, it crashes  "},
                "author": {"name": {"label": "alice"}},
                "updated": {"label": "2026-10-01T05:12:33-07:00"},
            },
            {
                "im:rating": {"label": "5"},
                "title": {"label": "Great"},
                "content": {"label": "Works well for me"},
                "author": {"name": {"label": "bob"}},
                "updated": {"label": "2026-09-30T10:00:00-07:00"},
            },
        ]
    }
}


def _play_response(rows):
    inner = json.dumps([rows, None])
    return ")]}'\n\n" + json.dumps([["wrb.fr", "UsvDTd", inner, None, None, None, "generic"]])


PLAY_ROWS = [
    ["id-1", ["Carol", [None, 2]], 1, None, "Crash on start every time", [1791395865, 0], 0],
    ["id-2", ["Dan", [None, 2]], 4, None, "Pretty good", [1791300000, 0], 0],
]


@pytest.fixture
def test_db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.add_competitor("Rival")
    return database


@pytest.fixture
def agent(test_db):
    with patch("prysma.agents.competitive_intel.db", test_db):
        a = CompetitiveIntelAgent()
        a.client = MagicMock()
        yield a


def _stub_get(agent, payload):
    resp = MagicMock()
    resp.json.return_value = payload
    agent.client.get.return_value = resp


def _stub_post(agent, text):
    resp = MagicMock()
    resp.text = text
    agent.client.post.return_value = resp


class TestReviewDedupe:
    def test_review_exists_normalises_case_and_whitespace(self, test_db):
        cid = test_db.get_competitor_by_name("Rival")
        assert not test_db.review_exists(cid, "Great app")
        test_db.add_review(cid, "ios", 5, "", "Great app", "a", "2026-10-01")
        assert test_db.review_exists(cid, "  great APP ")
        assert not test_db.review_exists(cid + 1, "Great app")

    def test_migration_adds_and_backfills_hash_on_old_schema(self, tmp_path):
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE competitors (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                website TEXT, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1);
            CREATE TABLE competitor_reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, competitor_id INTEGER,
                platform TEXT, rating INTEGER, title TEXT, content TEXT, author TEXT, review_date DATE,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO competitors (name) VALUES ('Old');
            INSERT INTO competitor_reviews (competitor_id, platform, rating, content) VALUES (1, 'ios', 3, 'Old review');
        """)
        conn.commit()
        conn.close()

        database = Database(path)
        assert database.review_exists(1, "old review")
        Database(path)  # second init is a no-op, not an error


class TestAppStoreReviews:
    def test_parse_skips_metadata_entry(self):
        reviews = CompetitiveIntelAgent._parse_app_store_reviews(APP_STORE_FEED)
        assert [r["rating"] for r in reviews] == [2, 5]
        assert reviews[0]["author"] == "alice"
        assert reviews[0]["review_date"] == "2026-10-01"

    def test_parse_empty_feed(self):
        assert CompetitiveIntelAgent._parse_app_store_reviews({"feed": {}}) == []

    def test_scan_stores_sanitized_and_dedupes(self, agent, test_db):
        _stub_get(agent, APP_STORE_FEED)
        competitor = {"id": test_db.get_competitor_by_name("Rival"), "name": "Rival"}

        assert agent._scan_app_store_reviews(competitor, "id123") == 2
        url = agent.client.get.call_args[0][0]
        assert "/gb/rss/customerreviews/id=123/sortBy=mostRecent/json" in url

        reviews = test_db.get_recent_reviews(competitor_id=competitor["id"], hours=24)
        contents = {r["content"] for r in reviews}
        assert "Too many <b>ads</b>, it crashes" in contents  # whitespace collapsed
        assert all(r["platform"] == "ios" for r in reviews)

        # Re-running must not duplicate
        assert agent._scan_app_store_reviews(competitor, "id123") == 0
        assert len(test_db.get_recent_reviews(competitor_id=competitor["id"], hours=24)) == 2

    def test_negative_keyword_review_creates_opportunity(self, agent, test_db):
        _stub_get(agent, APP_STORE_FEED)
        competitor = {"id": test_db.get_competitor_by_name("Rival"), "name": "Rival"}
        agent._scan_app_store_reviews(competitor, "123")
        findings = test_db.get_recent_findings(hours=24, finding_type="opportunity")
        assert len(findings) == 1


class TestPlayReviews:
    def test_parse(self):
        reviews = CompetitiveIntelAgent._parse_play_reviews(_play_response(PLAY_ROWS))
        assert [(r["rating"], r["author"]) for r in reviews] == [(1, "Carol"), (4, "Dan")]
        assert reviews[0]["review_date"] == "2026-10-07"

    def test_parse_no_reviews(self):
        text = ")]}'\n\n" + json.dumps([["wrb.fr", "UsvDTd", json.dumps([None, None])]])
        assert CompetitiveIntelAgent._parse_play_reviews(text) == []

    def test_parse_changed_shape_raises(self):
        with pytest.raises(ValueError):
            CompetitiveIntelAgent._parse_play_reviews(_play_response([["id", "x"]]))
        with pytest.raises(ValueError):
            CompetitiveIntelAgent._parse_play_reviews(")]}'\n\n[[\"wrb.fr\", \"Other\", \"[]\"]]")


class TestScanReviews:
    def test_uses_db_store_ids_and_both_platforms(self, agent, test_db):
        test_db.set_competitor_store_ids(test_db.get_competitor_by_name("Rival"),
                                         {"ios": "id1", "android": "com.rival"})
        _stub_get(agent, APP_STORE_FEED)
        _stub_post(agent, _play_response(PLAY_ROWS))

        agent._scan_reviews()

        assert agent.results["new_reviews"] == 4
        assert agent.results["errors"] == 0
        platforms = {r["platform"] for r in test_db.get_recent_reviews(hours=24)}
        assert platforms == {"ios", "android"}

    def test_falls_back_to_seed_map_when_column_empty(self, agent, test_db):
        test_db.add_competitor("Tabata Timer")  # in DEFAULT_COMPETITOR_STORE_IDS, no store_ids saved
        competitor = next(c for c in test_db.get_active_competitors() if c["name"] == "Tabata Timer")
        assert agent._store_ids(competitor)["ios"] == "id1255964203"

    def test_fetch_failure_counts_error(self, agent, test_db):
        test_db.set_competitor_store_ids(test_db.get_competitor_by_name("Rival"), {"ios": "id1"})
        agent.client.get.side_effect = RuntimeError("network down")
        agent._scan_reviews()
        assert agent.results["errors"] == 1
        assert agent.results["new_reviews"] == 0
