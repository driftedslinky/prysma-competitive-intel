"""Tests for the alert engine. Telegram and network calls are stubbed."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from prysma.agents.alerts import AlertEngine, format_alert
from prysma.config import config
from prysma.storage.database import Database


@pytest.fixture
def test_db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.add_competitor("AppBlock")
    with patch("prysma.agents.alerts.db", database):
        yield database


@pytest.fixture
def engine(test_db):
    return AlertEngine()


@pytest.fixture
def reporter():
    """Stub ReporterAgent; send_telegram succeeds unless a test changes it."""
    instance = MagicMock()
    instance.send_telegram.return_value = True
    with patch("prysma.agents.alerts.ReporterAgent", return_value=instance), \
         patch.object(config, "telegram_bot_token", "test-token"), \
         patch.object(config, "telegram_allowed_users", "111"):
        yield instance


def _add_change(db, change_type, old, new, competitor="AppBlock", platform="ios"):
    cid = db.get_competitor_by_name(competitor)
    with db.get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO aso_changes (competitor_id, platform, change_type, old_value, new_value) "
            "VALUES (?, ?, ?, ?, ?)",
            (cid, platform, change_type, old, new),
        )
        return cursor.lastrowid


def _add_alert(db, source_id, title="AppBlock: price changed"):
    return db.add_alert(db.get_competitor_by_name("AppBlock"), "price", "high", title,
                        "AppBlock: price changed from Free to $4.99.", "aso_changes", source_id)


class TestRules:
    def test_rating_drop_of_04_is_high(self, engine, test_db):
        _add_change(test_db, "rating", "4.3", "3.9")
        alerts = engine.build_alerts()
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "high"
        assert "dropped 4.3 -> 3.9" in alerts[0]["message"]

    def test_rating_change_of_005_is_ignored(self, engine, test_db):
        _add_change(test_db, "rating", "4.30", "4.25")
        assert engine.build_alerts() == []

    def test_rating_change_of_exactly_01_fires_medium(self, engine, test_db):
        _add_change(test_db, "rating", "4.4", "4.3")  # float diff is 0.0999999...
        alerts = engine.build_alerts()
        assert [a["severity"] for a in alerts] == ["medium"]

    def test_rating_alert_names_most_common_complaint(self, engine, test_db):
        cid = test_db.get_competitor_by_name("AppBlock")
        test_db.add_review(cid, "ios", 1, "", "Timer stops in background", "a", "2026-10-01")
        test_db.add_review(cid, "ios", 2, "", "Background sync is broken", "b", "2026-10-01")
        test_db.add_review(cid, "ios", 5, "", "Background mode fine", "c", "2026-10-01")
        _add_change(test_db, "rating", "4.3", "3.9")
        message = engine.build_alerts()[0]["message"]
        assert '2 recent negative reviews mention "background"' in message
        assert message.endswith('"background".')  # one sentence, clause appended

    def test_price_change_is_high_and_states_values(self, engine, test_db):
        _add_change(test_db, "price", "Free", "$4.99")
        alerts = engine.build_alerts()
        assert alerts[0]["severity"] == "high"
        assert alerts[0]["message"] == "AppBlock: price changed from Free to $4.99."

    def test_title_change_includes_old_and_new(self, engine, test_db):
        _add_change(test_db, "title", "AppBlock", "AppBlock: Focus Timer")
        alert = engine.build_alerts()[0]
        assert alert["severity"] == "high"
        assert '"AppBlock"' in alert["message"] and '"AppBlock: Focus Timer"' in alert["message"]

    def test_ratings_count_thresholds(self, engine, test_db):
        _add_change(test_db, "ratings_count", "1000", "1100")    # +10%, +100: quiet
        _add_change(test_db, "ratings_count", "1000", "1300")    # +30%: fires
        _add_change(test_db, "ratings_count", "100000", "100600")  # +600: fires
        alerts = engine.build_alerts()
        assert [a["severity"] for a in alerts] == ["medium", "medium"]
        assert any("1,000 -> 1,300" in a["message"] for a in alerts)

    def test_version_is_medium_and_other_is_low(self, engine, test_db):
        _add_change(test_db, "version", "2.0", "2.1")
        _add_change(test_db, "subtitle", "Block apps", "Block apps and sites")
        severities = {a["alert_type"]: a["severity"] for a in engine.build_alerts()}
        assert severities == {"version": "medium", "subtitle": "low"}

    def test_description_digit_only_change_is_ignored(self, engine, test_db):
        _add_change(test_db, "description", 'Great timer "ratingCount":"8612"', 'Great timer "ratingCount":"8613"')
        assert engine.build_alerts() == []

    def test_description_digit_change_that_shifts_500_char_cut_is_ignored(self, engine, test_db):
        # Real case: a longer number pushes the rest of the scraped text past the cut
        text = "x" * 460 +'"ratingValue":"{}","ratingCount":"2270245"'
        old = text.format("4.89103889465332")[:500]
        new = text.format("4.8908162117004395")[:500]
        _add_change(test_db, "description", old, new)
        assert engine.build_alerts() == []

    def test_description_text_change_is_low_and_quotes_change(self, engine, test_db):
        _add_change(test_db, "description", "Block apps.", "Block apps. Now with focus timer.")
        alert = engine.build_alerts()[0]
        assert alert["severity"] == "low"
        assert "Now with focus timer." in alert["message"]

    @pytest.mark.parametrize("old,new", [
        (None, None), ("", ""), (None, "4.5"), ("", "4.5"), ("4.5", None), ("None", "4.5"),
    ])
    def test_rating_with_missing_values_does_not_crash(self, engine, test_db, old, new):
        _add_change(test_db, "rating", old, new)
        assert engine.build_alerts() == []

    @pytest.mark.parametrize("change_type", ["price", "title", "description", "version", "ratings_count"])
    def test_none_or_empty_values_do_not_crash(self, engine, test_db, change_type):
        _add_change(test_db, change_type, None, "")
        _add_change(test_db, change_type, "", None)
        assert engine.build_alerts() == []

    def test_price_set_from_empty_still_says_what_changed(self, engine, test_db):
        _add_change(test_db, "price", None, "$2.99")
        assert engine.build_alerts()[0]["message"] == 'AppBlock: price set to "$2.99".'

    def test_important_findings_alert_but_aso_findings_do_not(self, engine, test_db):
        cid = test_db.get_competitor_by_name("AppBlock")
        test_db.add_finding(cid, "opportunity", "Negative review opportunity (AppBlock)",
                            "Timer stops in the background", importance=5)
        test_db.add_finding(cid, "news", "AppBlock raises prices", importance=4)
        test_db.add_finding(cid, "news", "Minor blog post", importance=3)
        test_db.add_finding(cid, "change", "ASO change: price (AppBlock)", "x", importance=4)
        alerts = engine.build_alerts()
        assert sorted(a["severity"] for a in alerts) == ["high", "medium"]
        assert all(a["alert_type"] == "finding" for a in alerts)
        assert any('"Timer stops in the background"' in a["message"] for a in alerts)


class TestDedupe:
    def test_add_alert_twice_inserts_once(self, test_db):
        assert _add_alert(test_db, 7) is not None
        assert _add_alert(test_db, 7) is None
        with test_db.get_conn() as conn:
            assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1

    def test_rebuilding_does_not_refire(self, engine, test_db):
        _add_change(test_db, "price", "Free", "$4.99")
        assert len(engine.build_alerts()) == 1
        assert engine.build_alerts() == []

    def test_recent_alerts_uses_sqlite_clock(self, test_db):
        _add_alert(test_db, 1)
        with test_db.get_conn() as conn:
            conn.execute("UPDATE alerts SET created_at = datetime('now', '-200 hours')")
        _add_alert(test_db, 2, title="new")
        recent = test_db.get_recent_alerts(hours=168)
        assert [a["title"] for a in recent] == ["new"]
        assert recent[0]["competitor_name"] == "AppBlock"


class TestSend:
    def test_sends_and_marks_sent(self, engine, test_db, reporter):
        _add_alert(test_db, 1)
        assert engine.send_alerts() == 1
        chat_id, text = reporter.send_telegram.call_args[0]
        assert chat_id == "111"
        assert text == "🚨 🚨 AppBlock: price changed\nAppBlock: price changed from Free to $4.99."
        assert test_db.get_unsent_alerts() == []

    def test_skips_already_sent_alerts(self, engine, test_db, reporter):
        sent_id = _add_alert(test_db, 1)
        test_db.mark_alert_sent(sent_id)
        _add_alert(test_db, 2)
        assert engine.send_alerts() == 1
        assert reporter.send_telegram.call_count == 1
        assert engine.send_alerts() == 0
        assert reporter.send_telegram.call_count == 1

    def test_no_alerts_sends_nothing(self, engine, test_db, reporter):
        assert engine.send_alerts() == 0
        reporter.send_telegram.assert_not_called()

    def test_failed_send_stays_unsent(self, engine, test_db, reporter):
        reporter.send_telegram.return_value = False
        _add_alert(test_db, 1)
        assert engine.send_alerts() == 0
        assert len(test_db.get_unsent_alerts()) == 1

    def test_missing_token_returns_zero(self, engine, test_db):
        _add_alert(test_db, 1)
        with patch("prysma.agents.alerts.ReporterAgent") as reporter_cls, \
             patch.object(config, "telegram_bot_token", ""):
            assert engine.send_alerts() == 0
            reporter_cls.assert_not_called()
        assert len(test_db.get_unsent_alerts()) == 1

    def test_format_escapes_markdown(self):
        text = format_alert({"severity": "low", "title": "my_app", "message": "*new* [beta]"})
        assert text == "🚨 ℹ️ my\\_app\n\\*new\\* \\[beta]"


class TestWiring:
    def test_telegram_alerts_command_is_authorized_only(self):
        from prysma.telegram import bot
        assert hasattr(bot.alerts, "__wrapped__")  # set by functools.wraps in authorized_only

    def test_template_has_no_double_braces(self):
        template = Path(__file__).parent.parent / "prysma" / "web" / "templates" / "index.html"
        text = template.read_text(encoding="utf-8")
        assert "{{" not in text and "}}" not in text
        assert "{alert_rows}" in text and "{alerts_count}" in text
