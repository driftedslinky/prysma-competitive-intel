"""Watch lists keep the two demo markets apart: the migration, the scoped read
queries, alert dismissal, and the dashboard routes that use them."""
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from prysma.storage.database import DEFAULT_WATCH_LIST, WATCH_LISTS, Database
from prysma.web import app as web_app

BLOCKERS = "app-blockers"


@pytest.fixture
def test_db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.add_competitor("Timer A")
    database.add_competitor("Blocker B", watch_list=BLOCKERS)
    return database


def _cid(database, name):
    return database.get_competitor_by_name(name)


def _names(rows, key="name"):
    return sorted(r[key] for r in rows)


class TestMigration:
    def _old_db(self, path):
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE competitors (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                website TEXT, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1, store_ids TEXT);
            CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, competitor_id INTEGER,
                alert_type TEXT, severity TEXT, title TEXT NOT NULL, message TEXT, source_table TEXT,
                source_id INTEGER, is_sent BOOLEAN DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE digests (id INTEGER PRIMARY KEY AUTOINCREMENT, digest_type TEXT, content TEXT NOT NULL,
                sent_via_telegram BOOLEAN DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO competitors (name, store_ids) VALUES ('Tabata Timer', '{"android": "x"}');
            INSERT INTO competitors (name, is_active) VALUES ('Gone', 0);
            INSERT INTO alerts (competitor_id, severity, title, source_table, source_id)
                VALUES (1, 'high', 'Old alert', 'findings', 1);
            INSERT INTO digests (digest_type, content) VALUES ('research', '🧠 *Strategic Analysis* old');
        """)
        conn.commit()
        conn.close()

    def test_existing_rows_join_the_default_list(self, tmp_path):
        path = str(tmp_path / "old.db")
        self._old_db(path)
        database = Database(path)

        with database.get_conn() as conn:
            rows = database._rows_to_dicts(conn.execute("SELECT * FROM competitors ORDER BY id").fetchall())
        assert {r["name"]: r["watch_list"] for r in rows} == {"Tabata Timer": DEFAULT_WATCH_LIST, "Gone": DEFAULT_WATCH_LIST}
        assert rows[0]["store_ids"] == '{"android": "x"}'
        assert [a["title"] for a in database.get_recent_alerts(watch_list=DEFAULT_WATCH_LIST)] == ["Old alert"]
        assert database.get_latest_digest("research", "🧠", DEFAULT_WATCH_LIST)["content"].endswith("old")
        assert database.get_latest_digest("research", "🧠", BLOCKERS) is None

    def test_migration_is_idempotent(self, tmp_path):
        path = str(tmp_path / "old.db")
        self._old_db(path)
        Database(path)
        database = Database(path)  # second init is a no-op, not an error
        assert _names(database.get_active_competitors()) == ["Tabata Timer"]


class TestSeeding:
    def test_seeds_both_lists_once(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        total = sum(len(meta["seed"]) for meta in WATCH_LISTS.values())
        assert database.seed_watch_lists() == total
        assert database.seed_watch_lists() == 0
        blockers = _names(database.get_active_competitors(watch_list=BLOCKERS))
        assert "Opal" in blockers and "Tabata Timer" not in blockers
        assert "Gravl" in _names(database.get_active_competitors(watch_list=DEFAULT_WATCH_LIST))

    def test_seeding_keeps_unwatched_competitors_unwatched(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        database.seed_watch_lists()
        database.remove_competitor("Opal")
        database.seed_watch_lists()
        assert "Opal" not in _names(database.get_active_competitors())

    def test_seeding_keeps_existing_rows(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        database.add_competitor("Tabata Timer", description="mine")
        database.seed_watch_lists()
        row = next(c for c in database.get_active_competitors() if c["name"] == "Tabata Timer")
        assert row["description"] == "mine"


class TestScopedQueries:
    def test_competitors(self, test_db):
        assert _names(test_db.get_active_competitors(watch_list=DEFAULT_WATCH_LIST)) == ["Timer A"]
        assert _names(test_db.get_active_competitors(watch_list=BLOCKERS)) == ["Blocker B"]
        assert _names(test_db.get_active_competitors()) == ["Blocker B", "Timer A"]

    def test_findings(self, test_db):
        test_db.add_finding(_cid(test_db, "Timer A"), "news", "timer news")
        test_db.add_finding(_cid(test_db, "Blocker B"), "news", "blocker news")
        test_db.add_finding(None, "news", "market news")
        assert _names(test_db.get_recent_findings(watch_list=BLOCKERS), "title") == ["blocker news"]
        # A finding without a competitor belongs to the default list
        assert _names(test_db.get_recent_findings(watch_list=DEFAULT_WATCH_LIST), "title") == ["market news", "timer news"]
        assert len(test_db.get_recent_findings()) == 3
        assert _names(test_db.get_recent_findings(finding_type="news", watch_list=BLOCKERS), "title") == ["blocker news"]

    def test_aso_changes(self, test_db):
        with test_db.get_conn() as conn:
            for name in ("Timer A", "Blocker B"):
                conn.execute(
                    "INSERT INTO aso_changes (competitor_id, platform, change_type, old_value, new_value) "
                    "VALUES (?, 'ios', 'title', 'a', 'b')", (_cid(test_db, name),)
                )
        assert _names(test_db.get_aso_changes(watch_list=BLOCKERS), "competitor_name") == ["Blocker B"]
        assert len(test_db.get_aso_changes()) == 2

    def test_alerts_and_dismissal(self, test_db):
        timer = test_db.add_alert(_cid(test_db, "Timer A"), "news", "high", "t", "timer", "findings", 1)
        test_db.add_alert(_cid(test_db, "Blocker B"), "news", "high", "b", "blocker", "findings", 2)
        assert _names(test_db.get_recent_alerts(watch_list=BLOCKERS), "message") == ["blocker"]

        assert test_db.dismiss_alert(timer)
        assert test_db.get_recent_alerts(watch_list=DEFAULT_WATCH_LIST) == []
        # A rebuild for the same source row must not bring the alert back
        assert test_db.add_alert(_cid(test_db, "Timer A"), "news", "high", "t", "timer", "findings", 1) is None
        assert test_db.get_recent_alerts(watch_list=DEFAULT_WATCH_LIST) == []

    def test_watching_again_moves_to_the_given_list(self, test_db):
        test_db.remove_competitor("Timer A")
        test_db.add_competitor("Timer A", watch_list=BLOCKERS)
        assert _names(test_db.get_active_competitors(watch_list=BLOCKERS)) == ["Blocker B", "Timer A"]

    def test_digests(self, test_db):
        test_db.add_digest("research", "🧠 *Strategic Analysis* blockers", watch_list=BLOCKERS)
        test_db.add_digest("research", "🕳 *Market Gap Analysis* timers", watch_list=DEFAULT_WATCH_LIST)
        assert test_db.get_latest_digest("research", "🧠", BLOCKERS)["content"].endswith("blockers")
        assert test_db.get_latest_digest("research", "🧠", DEFAULT_WATCH_LIST) is None
        assert test_db.get_latest_digest("research", "🕳", DEFAULT_WATCH_LIST)["content"].endswith("timers")


@pytest.fixture
def client(test_db):
    web_app._rate_hits.clear()
    web_app._jobs.clear()
    with patch("prysma.web.app.db", test_db):
        yield TestClient(web_app.app)
    web_app._rate_hits.clear()
    web_app._jobs.clear()


class TestDashboard:
    def test_page_shows_only_the_selected_list(self, client):
        page = client.get("/", params={"list": BLOCKERS}).text
        assert "Blocker B" in page and "Timer A" not in page
        page = client.get("/").text
        assert "Timer A" in page and "Blocker B" not in page

    def test_unknown_list_falls_back_to_default(self, client):
        assert "Timer A" in client.get("/", params={"list": "<script>"}).text

    def test_kpi_labels_state_their_window(self, client):
        page = client.get("/").text
        assert "Findings (7d)" in page and "Alerts (30d)" in page and "ASO changes (7d)" in page

    def test_scraped_text_is_escaped_and_never_used_as_a_placeholder(self, client, test_db):
        test_db.add_competitor("Evil", description="<img src=x onerror=alert(1)> {alert_rows}")
        page = client.get("/").text
        assert "<img src=x" not in page
        assert "&lt;img src=x onerror=alert(1)&gt; {alert_rows}" in page

    def test_watch_adds_to_the_given_list(self, client, test_db):
        resp = client.post("/api/watch", json={"candidates": [{"name": "Opal"}], "watch_list": BLOCKERS})
        assert resp.json() == {"added": 1}
        assert "Opal" in _names(test_db.get_active_competitors(watch_list=BLOCKERS))

    def test_watch_without_a_list_uses_the_default(self, client, test_db):
        client.post("/api/watch", json={"candidates": [{"name": "Gravl"}]})
        assert "Gravl" in _names(test_db.get_active_competitors(watch_list=DEFAULT_WATCH_LIST))

    def test_unwatch_and_dismiss(self, client, test_db):
        assert client.post("/api/unwatch", json={"name": "Blocker B"}).json() == {"removed": True}
        assert test_db.get_active_competitors(watch_list=BLOCKERS) == []
        alert_id = test_db.add_alert(_cid(test_db, "Timer A"), "news", "high", "t", "m", "findings", 1)
        assert client.post(f"/api/alerts/{alert_id}/dismiss").json() == {"dismissed": True}
        assert test_db.get_recent_alerts() == []

    def test_analysis_status_reports_the_latest_scoped_report(self, client, test_db):
        test_db.add_digest("research", "🧠 *Strategic Analysis* for blockers", watch_list=BLOCKERS)
        body = client.get("/api/analysis", params={"list": BLOCKERS}).json()
        assert body["analyze"]["state"] == "idle"
        assert body["analyze"]["report"]["content"].endswith("for blockers")
        assert body["gaps"]["report"] is None

    def test_gap_run_is_tracked_and_scoped(self, client):
        with patch("prysma.agents.analyst.AnalystAgent") as agent:
            agent.return_value.generate_gap_analysis.return_value = "🕳 *Market Gap Analysis* ok"
            assert client.post("/api/gaps", params={"list": BLOCKERS}).json() == {"report": "🕳 *Market Gap Analysis* ok"}
        agent.return_value.generate_gap_analysis.assert_called_once_with(watch_list=BLOCKERS)
        assert client.get("/api/analysis", params={"list": BLOCKERS}).json()["gaps"]["state"] == "done"

    def test_failed_gap_run_reports_an_error(self, client):
        with patch("prysma.agents.analyst.AnalystAgent") as agent:
            agent.return_value.generate_gap_analysis.return_value = "⚠️ Gap analysis needs NEBIUS_API_KEY."
            client.post("/api/gaps")
        job = client.get("/api/analysis").json()["gaps"]
        assert job["state"] == "error" and "NEBIUS_API_KEY" in job["message"]

    def test_second_strategic_run_does_not_start_while_one_runs(self, client):
        web_app._job_start("analyze", BLOCKERS)
        with patch("prysma.agents.analyst.AnalystAgent") as agent:
            resp = client.post("/api/analyze", params={"list": BLOCKERS})
        assert resp.json()["status"] == "running"
        agent.assert_not_called()

    def test_status_route_is_unchanged(self, client):
        body = client.get("/api/status").json()
        assert body["status"] == "ok" and body["competitors"] == 2
