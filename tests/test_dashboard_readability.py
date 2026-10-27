"""The readability pass: user-named watch lists, insight types, ASO changes on
the competitor cards, and the safe Markdown renderer for analysis reports."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from prysma.storage.database import DEFAULT_WATCH_LIST, WATCH_LIST_NAME_MAX, WATCH_LISTS, Database
from prysma.web import app as web_app
from prysma.web.app import INSIGHT_LABELS, insight_type
from prysma.web.markdown import render_report

BLOCKERS = "app-blockers"


@pytest.fixture
def test_db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.add_competitor("Timer A")
    database.add_competitor("Blocker B", watch_list=BLOCKERS)
    return database


@pytest.fixture
def client(test_db):
    web_app._rate_hits.clear()
    web_app._jobs.clear()
    with patch("prysma.web.app.db", test_db):
        yield TestClient(web_app.app)
    web_app._jobs.clear()


def _keys(database):
    return [w["key"] for w in database.get_watch_lists()]


class TestWatchListStore:
    def test_seeded_lists_are_migrated_with_their_keys(self, test_db):
        assert test_db.get_watch_lists() == [
            {"key": key, "label": meta["label"]} for key, meta in WATCH_LISTS.items()
        ]

    def test_create_trims_and_returns_a_new_key(self, test_db):
        created = test_db.create_watch_list("   Video   games  ")
        assert created["label"] == "Video games"
        assert created["key"].startswith("list-")
        assert _keys(test_db)[-1] == created["key"]
        assert test_db.get_active_competitors(watch_list=created["key"]) == []

    @pytest.mark.parametrize("name", ["", "   ", None, "x" * (WATCH_LIST_NAME_MAX + 1)])
    def test_create_rejects_empty_and_long_names(self, test_db, name):
        with pytest.raises(ValueError):
            test_db.create_watch_list(name)
        assert len(test_db.get_watch_lists()) == 2

    def test_name_collision_ignores_case_and_spacing(self, test_db):
        with pytest.raises(ValueError, match="already exists"):
            test_db.create_watch_list("  interval   TIMERS ")

    def test_rename_keeps_the_key_and_the_data(self, test_db):
        assert test_db.rename_watch_list(BLOCKERS, "Focus apps")
        assert {"key": BLOCKERS, "label": "Focus apps"} in test_db.get_watch_lists()
        assert [c["name"] for c in test_db.get_active_competitors(watch_list=BLOCKERS)] == ["Blocker B"]

    def test_rename_rejects_a_taken_name_and_an_unknown_key(self, test_db):
        with pytest.raises(ValueError):
            test_db.rename_watch_list(BLOCKERS, "Interval timers")
        assert test_db.rename_watch_list("nope", "Fine") is False

    def test_rename_to_own_name_in_new_case_is_allowed(self, test_db):
        assert test_db.rename_watch_list(BLOCKERS, "APP BLOCKERS")

    def test_delete_unwatches_its_competitors_and_keys_are_not_reused(self, test_db):
        first = test_db.create_watch_list("Games")
        test_db.add_competitor("Game A", watch_list=first["key"])
        assert test_db.delete_watch_list(first["key"])
        assert first["key"] not in _keys(test_db)
        assert test_db.get_competitor_by_name("Game A")  # history stays
        assert "Game A" not in [c["name"] for c in test_db.get_active_competitors()]
        second = test_db.create_watch_list("Games")
        assert second["key"] != first["key"]
        assert test_db.get_active_competitors(watch_list=second["key"]) == []

    def test_last_list_cannot_be_deleted(self, test_db):
        assert test_db.delete_watch_list(BLOCKERS)
        with pytest.raises(ValueError):
            test_db.delete_watch_list(DEFAULT_WATCH_LIST)
        assert test_db.delete_watch_list("nope") is False

    def test_deleted_seed_list_stays_deleted_after_restart(self, tmp_path):
        path = str(tmp_path / "t.db")
        database = Database(path)
        database.delete_watch_list(BLOCKERS)
        database = Database(path)
        assert _keys(database) == [DEFAULT_WATCH_LIST]
        database.seed_watch_lists()
        assert database.get_active_competitors(watch_list=BLOCKERS) == []

    def test_default_moves_when_the_default_list_is_deleted(self, test_db):
        test_db.delete_watch_list(DEFAULT_WATCH_LIST)
        assert test_db.default_watch_list() == BLOCKERS


class TestWatchListRoutes:
    def test_create_switch_and_scope(self, client, test_db):
        created = client.post("/api/lists", json={"name": "Video games"}).json()
        assert created["label"] == "Video games"
        client.post("/api/watch", json={"candidates": [{"name": "Game A"}], "watch_list": created["key"]})
        page = client.get("/", params={"list": created["key"]}).text
        assert "Game A" in page and "Timer A" not in page and "Blocker B" not in page
        assert "Watched competitors · Video games" in page
        assert "Game A" not in client.get("/").text

    def test_list_routes_report_errors(self, client):
        assert client.post("/api/lists", json={"name": "  "}).status_code == 400
        resp = client.post("/api/lists", json={"name": "App blockers"})
        assert resp.status_code == 400 and "already exists" in resp.json()["error"]
        assert client.post("/api/lists/nope/rename", json={"name": "X"}).status_code == 404
        assert client.post("/api/lists/nope/delete").status_code == 404

    def test_rename_and_delete_routes(self, client, test_db):
        assert client.post(f"/api/lists/{BLOCKERS}/rename", json={"name": "Focus"}).json()["label"] == "Focus"
        assert client.post(f"/api/lists/{BLOCKERS}/delete").json() == {"deleted": BLOCKERS, "next": DEFAULT_WATCH_LIST}
        assert client.get("/api/lists").json()["lists"] == [{"key": DEFAULT_WATCH_LIST, "label": "Interval timers"}]
        assert client.post(f"/api/lists/{DEFAULT_WATCH_LIST}/delete").status_code == 400

    def test_list_name_is_escaped_everywhere(self, client):
        key = client.post("/api/lists", json={"name": "<b onmouseover=x>{alert_rows}"}).json()["key"]
        page = client.get("/", params={"list": key}).text
        assert "<b onmouseover" not in page
        assert "&lt;b onmouseover=x&gt;{alert_rows}" in page

    def test_every_list_has_an_edit_control_and_add_new_is_last(self, client):
        page = client.get("/").text
        assert page.count("data-edit-list=") == 2
        assert page.index("data-edit-list='app-blockers'") < page.index("data-action=\"add-list\"")


@pytest.mark.parametrize("source, kind, title, expected", [
    ("aso_changes", "rating", "", "rating"),
    ("aso_changes", "ratings_count", "", "rating"),
    ("aso_changes", "description", "", "listing"),
    ("aso_changes", "title", "", "listing"),
    ("aso_changes", "price", "", "listing"),
    ("findings", "opportunity", "3 new negative reviews (X)", "review"),
    ("findings", "sentiment", "", "review"),
    ("findings", "change", "ASO change: rating (X)", "rating"),
    ("findings", "change", "ASO change: description (X)", "listing"),
    ("findings", "change", "Pricing page changed", "listing"),
    ("findings", "news", "", "news"),
    ("findings", "negative_news", "", "news"),
    ("findings", "funding", "", "news"),
    ("findings", "reddit", "", "news"),
    ("findings", None, "", "news"),
])
def test_insight_type_mapping(source, kind, title, expected):
    assert insight_type(source, kind, title) == expected


class TestInsightsAndCards:
    def test_insights_show_type_and_no_severity(self, client, test_db):
        cid = test_db.get_competitor_by_name("Timer A")
        fid = test_db.add_finding(cid, "opportunity", "2 new negative reviews (Timer A)",
                                  'Most common complaint: "ads" (2 of 2 reviews). Example: "too many ads"', None, 5)
        test_db.add_alert(cid, "finding", "high", "t", "m", "findings", fid)
        page = client.get("/").text
        assert ">Severity<" not in page and "badge-sev" not in page and ">high<" not in page
        assert "<th>Type</th>" in page and INSIGHT_LABELS["review"] in page
        assert "<strong>Complaint:</strong> “ads” in 2 of 2 reviews." in page
        assert "<strong>Users ask for:</strong> fewer ads." in page
        assert f"href='/reviews/{cid}'" in page
        assert f"c={cid}#competitors" in page
        assert "<time class='when' datetime='" in page

    def test_reviews_page_shows_full_text_escaped(self, client, test_db):
        cid = test_db.get_competitor_by_name("Timer A")
        test_db.add_review(cid, "android", 1, "Bad", "<script>x</script> {reviews} full text", "Al", "2026-10-01")
        page = client.get(f"/reviews/{cid}").text
        assert "&lt;script&gt;x&lt;/script&gt; {reviews} full text" in page and "<script>x" not in page
        assert client.get("/reviews/99999").status_code == 404

    def test_competitor_card_lists_its_own_aso_changes(self, client, test_db):
        cid = test_db.get_competitor_by_name("Timer A")
        test_db.upsert_app_listing(cid, "android", "a.b", "A", title="Old <i>name</i>")
        test_db.upsert_app_listing(cid, "android", "a.b", "A", title="New name")
        page = client.get("/").text
        assert "This app's listing changes (7d)" in page
        card = page[page.index(f"id='comp-{cid}'"):]
        card = card[:card.index("</article>")]
        assert "Old &lt;i&gt;name&lt;/i&gt;" in card and "New name" in card
        assert "ASO changes (7d)" in page  # the KPI card stays
        assert "h-aso" not in page  # the standalone table is gone

    def test_card_without_changes_says_so(self, client):
        assert "No listing changes in the last 7 days." in client.get("/").text

    def test_overview_order(self, client):
        page = client.get("/").text
        order = [page.index(marker) for marker in
                 ('id="h-lists"', 'id="h-market"', 'id="h-summary"', 'id="h-actions"', 'id="h-news"')]
        assert order == sorted(order)


HOSTILE = (
    "## Threats <script>alert(1)</script>\n"
    "- **Bold** <img src=x onerror=alert(1)>\n"
    "- {alert_rows} {strategic_html} \" ' onclick=\n"
    "<a href=\"javascript:alert(1)\">x</a>"
)


class TestReportRenderer:
    def test_renders_headings_bold_lists_and_paragraphs(self):
        out = render_report("🧠 *Strategic Analysis*\n\n# Top\n## Mid\n### Low\n"
                            "**Competitive Threats**\n- **ASO velocity**: 8+ apps\n  - nested\n- next\n"
                            "1. one\n2. two\n\nPara one\nline two")
        assert "<p>🧠 <strong>Strategic Analysis</strong></p>" in out
        assert "<h2>Top</h2>" in out and "<h3>Mid</h3>" in out and "<h4>Low</h4>" in out
        assert "<p><strong>Competitive Threats</strong></p>" in out
        assert "<ul><li>\n<strong>ASO velocity</strong>: 8+ apps\n<ul><li>\nnested\n</li></ul>\n</li><li>\nnext\n</li></ul>" in out
        assert "<ol><li>\none\n</li><li>\ntwo\n</li></ol>" in out
        assert "<p>Para one<br>line two</p>" in out
        assert "**" not in out

    def test_hostile_report_renders_inert(self):
        out = render_report(HOSTILE)
        for raw in ("<script", "<img", "<a ", "onerror=alert(1)>", "\" ' onclick"):
            assert raw not in out
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
        assert "&lt;img src=x onerror=alert(1)&gt;" in out
        assert "{alert_rows}" in out

    def test_renders_italic_metadata_and_ignores_underscores_in_words(self):
        out = render_report("_2026-10-08 · 8 competitors · 336h_\n"
                            "a snake_case identifier and file_name_here stay plain")
        assert "<em>2026-10-08 · 8 competitors · 336h</em>" in out
        assert "snake_case" in out and "file_name_here" in out
        assert "<em>case" not in out

    def test_only_known_tags_are_emitted(self):
        import re
        tags = set(re.findall(r"</?([a-z0-9]+)", render_report(HOSTILE + "\n`code` ---\n---")))
        assert tags <= {"p", "br", "strong", "em", "code", "h2", "h3", "h4", "ul", "ol", "li", "hr"}

    def test_hostile_report_is_inert_on_the_dashboard_and_api(self, client, test_db):
        test_db.add_digest("research", "🧠 *Strategic Analysis*\n" + HOSTILE, watch_list=DEFAULT_WATCH_LIST)
        page = client.get("/").text
        start = page.index('id="analyze-report">')
        report = page[start:page.index("</div>", start)]
        assert "<script" not in report and "<img" not in report and "<a " not in report
        # The placeholder in the report is shown as text, never filled
        assert "{alert_rows}" in report and "No material changes" not in report
        rendered = client.get("/api/analysis").json()["analyze"]["report"]
        assert rendered["content"].endswith(HOSTILE)  # the old field is unchanged
        assert "<script" not in rendered["html"] and "<img" not in rendered["html"]
