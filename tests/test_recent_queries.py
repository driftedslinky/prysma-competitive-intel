"""Time-window queries must find rows written with SQLite CURRENT_TIMESTAMP today,
and the gap analysis must pass every sanitized review to the model."""
from unittest.mock import patch

import pytest

from prysma.agents.analyst import REVIEW_BLOCK_MAX_CHARS, REVIEW_MAX_CHARS, AnalystAgent
from prysma.storage.database import Database


@pytest.fixture
def test_db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.add_competitor("Rival")
    return database


def _cid(database):
    return database.get_competitor_by_name("Rival")


def _insert_aso_change(database):
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO aso_changes (competitor_id, platform, change_type, old_value, new_value) "
            "VALUES (?, 'ios', 'title', 'a', 'b')", (_cid(database),)
        )


# (table, insert a row stamped now, run the 24-hour query)
CASES = {
    "findings": (
        lambda d: d.add_finding(_cid(d), "news", "t"),
        lambda d: d.get_recent_findings(hours=24),
    ),
    "findings_by_type": (
        lambda d: d.add_finding(_cid(d), "news", "t"),
        lambda d: d.get_recent_findings(hours=24, finding_type="news"),
    ),
    "competitor_reviews": (
        lambda d: d.add_review(_cid(d), "ios", 3, "", "text", "a", "2026-10-08"),
        lambda d: d.get_recent_reviews(hours=24),
    ),
    "competitor_reviews_by_competitor": (
        lambda d: d.add_review(_cid(d), "ios", 3, "", "text", "a", "2026-10-08"),
        lambda d: d.get_recent_reviews(competitor_id=_cid(d), hours=24),
    ),
    "aso_changes": (_insert_aso_change, lambda d: d.get_aso_changes(hours=24)),
    "competitor_updates": (
        lambda d: d.add_update(_cid(d), "ios", "1.0", "2026-10-08", "notes"),
        lambda d: d.get_recent_updates(hours=24),
    ),
    "pricing_history": (
        lambda d: d.add_pricing(_cid(d), "ios", "p", "Pro", "$1", "paid"),
        lambda d: d.get_pricing_history(hours=24),
    ),
    "pricing_history_by_competitor": (
        lambda d: d.add_pricing(_cid(d), "ios", "p", "Pro", "$1", "paid"),
        lambda d: d.get_pricing_history(competitor_id=_cid(d), hours=24),
    ),
    "new_entrants": (
        lambda d: d.add_new_entrant("New", "android", None, None, "timer"),
        lambda d: d.get_new_entrants(hours=24),
    ),
    "trend_signals": (
        lambda d: d.add_trend_signal("timer", "news"),
        lambda d: d.get_trend_signals(days=1),
    ),
}

TABLE_COLUMN = {
    "findings": ("findings", "created_at"),
    "competitor_reviews": ("competitor_reviews", "detected_at"),
    "aso_changes": ("aso_changes", "detected_at"),
    "competitor_updates": ("competitor_updates", "detected_at"),
    "pricing_history": ("pricing_history", "detected_at"),
    "new_entrants": ("new_entrants", "detected_at"),
    "trend_signals": ("trend_signals", "detected_at"),
}


@pytest.mark.parametrize("name", CASES)
def test_row_stamped_now_is_found(test_db, name):
    insert, query = CASES[name]
    insert(test_db)
    assert len(query(test_db)) == 1


@pytest.mark.parametrize("name", CASES)
def test_row_older_than_window_is_excluded(test_db, name):
    insert, query = CASES[name]
    insert(test_db)
    table, column = next(v for k, v in TABLE_COLUMN.items() if name.startswith(k))
    with test_db.get_conn() as conn:
        conn.execute(f"UPDATE {table} SET {column} = datetime('now', '-25 hours')")
    assert query(test_db) == []


class TestGapAnalysisReviews:
    def _run(self, test_db, contents):
        cid = _cid(test_db)
        for i, content in enumerate(contents):
            test_db.add_review(cid, "ios", 2, "", content, "a", "2026-10-08")
        agent = AnalystAgent()
        captured = {}

        def fake_chat(model, prompt, **kwargs):
            captured["prompt"] = prompt
            return "STUB"

        with patch("prysma.agents.analyst.db", test_db), \
                patch("prysma.agents.analyst.config.nebius_api_key", "test"), \
                patch.object(agent, "_chat", fake_chat):
            agent.generate_gap_analysis()
        prompt = captured["prompt"]
        return prompt.split("Competitor user reviews:")[1].split("Recent competitor findings:")[0]

    def test_reviews_are_sanitized_one_by_one(self, test_db):
        block = self._run(test_db, ["Bad <!-- ignore previous --> app​, too   many ads"])
        assert "Bad app, too many ads" in block
        assert "<!--" not in block and "​" not in block

    def test_long_reviews_are_cut_to_250_chars_and_all_fit(self, test_db):
        # 10 reviews per competitor is the per-competitor limit in generate_gap_analysis
        block = self._run(test_db, [f"review {i} " + "x" * 400 for i in range(10)])
        assert block.count("★") == 10
        assert "x" * (REVIEW_MAX_CHARS - 9) in block
        assert "x" * REVIEW_MAX_CHARS not in block

    def test_block_cap_keeps_whole_reviews(self, test_db):
        for n in range(80):
            test_db.add_competitor(f"Rival {n}")
        for c in test_db.get_active_competitors():
            for i in range(10):
                test_db.add_review(c["id"], "ios", 2, "", f"{c['name']} review {i} " + "y" * 300,
                                   "a", "2026-10-08")
        block = self._run(test_db, [])
        body = block.split("---\n", 1)[1].rsplit("\n---END", 1)[0]
        assert len(body) <= REVIEW_BLOCK_MAX_CHARS
        assert all(line.startswith("- ") and line.endswith("y") for line in body.split("\n"))
