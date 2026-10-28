"""The type filter above the Alerts and Findings tables on the Insights tab.

The filtering itself runs in the browser, and this suite has no browser. These
tests do not click anything. They check only the markup contract that the page
script relies on: the data-type on each row, the buttons and their counts, the
pressed state on load, and that the default render still shows every row.
"""
import re
from collections import Counter
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from prysma.storage.database import Database
from prysma.web import app as web_app
from prysma.web.app import INSIGHT_LABELS


@pytest.fixture
def test_db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.add_competitor("Timer A")
    return database


@pytest.fixture
def client(test_db):
    web_app._rate_hits.clear()
    web_app._jobs.clear()
    with patch("prysma.web.app.db", test_db):
        yield TestClient(web_app.app)
    web_app._jobs.clear()


@pytest.fixture
def insights(test_db):
    """Findings of type review (2) and news (1); alerts of type rating, listing and review."""
    cid = test_db.get_competitor_by_name("Timer A")
    review_id = test_db.add_finding(cid, "opportunity", "2 new negative reviews (Timer A)", importance=5)
    test_db.add_finding(cid, "sentiment", "Review mood dropped (Timer A)", importance=4)
    test_db.add_finding(cid, "news", "Timer A raises money", importance=2)
    test_db.add_alert(cid, "rating", "high", "Rating fell", "Timer A: rating fell.", "aso_changes", 1)
    test_db.add_alert(cid, "price", "high", "Price changed", "Timer A: price changed.", "aso_changes", 2)
    test_db.add_alert(cid, "opportunity", "high", "Negative reviews", "2 new negative reviews.", "findings", review_id)
    return cid


def _table(page: str, table_id: str) -> str:
    start = page.index(f'id="{table_id}"')
    return page[start:page.index("</table>", start)]


def _rows(page: str, table_id: str) -> list[str]:
    table = _table(page, table_id)
    return re.findall(r"<tr[ >].*?</tr>", table[table.index("<tbody>"):], re.S)


def _filter_bar(page: str, table_id: str) -> str:
    match = re.search(rf"<div class='type-filter'[^>]*data-filter-for='{table_id}'>.*?</div>", page, re.S)
    return match.group(0) if match else ""


def _buttons(bar: str) -> dict[str, str]:
    return {m.group(1): m.group(0)
            for m in re.finditer(r"<button[^>]*data-filter='(\w+)'.*?</button>", bar, re.S)}


TABLES = ["alerts-table", "findings-table"]


@pytest.mark.parametrize("table_id", TABLES)
def test_every_row_has_a_data_type_that_matches_its_badge(client, insights, table_id):
    rows = _rows(client.get("/").text, table_id)
    assert len(rows) == 3
    for row in rows:
        kind = re.match(r"<tr data-type='(\w+)'>", row).group(1)
        assert kind in INSIGHT_LABELS
        assert f"<span class='badge type-{kind}'>{INSIGHT_LABELS[kind]}</span>" in row


def test_a_button_for_each_type_present_and_none_for_absent_types(client, insights):
    page = client.get("/").text
    alerts = _buttons(_filter_bar(page, "alerts-table"))
    findings = _buttons(_filter_bar(page, "findings-table"))
    assert list(alerts) == ["all", "rating", "listing", "review"]
    assert list(findings) == ["all", "review", "news"]


@pytest.mark.parametrize("table_id", TABLES)
def test_each_button_count_equals_its_rows(client, insights, table_id):
    page = client.get("/").text
    kinds = Counter(re.match(r"<tr data-type='(\w+)'>", row).group(1) for row in _rows(page, table_id))
    for key, button in _buttons(_filter_bar(page, table_id)).items():
        expected = sum(kinds.values()) if key == "all" else kinds[key]
        assert f"<span class='filter-count'>({expected})</span>" in button, button
        assert f" {expected} " in re.search(r"aria-label='([^']*)'", button).group(1)


@pytest.mark.parametrize("table_id", TABLES)
def test_only_all_is_pressed_on_load(client, insights, table_id):
    buttons = _buttons(_filter_bar(client.get("/").text, table_id))
    pressed = [key for key, b in buttons.items() if "aria-pressed='true'" in b]
    assert pressed == ["all"]
    for button in buttons.values():
        assert button.startswith("<button type='button' class='filter-chip'")
        assert "aria-label='Show " in button


@pytest.mark.parametrize("table_id", TABLES)
def test_default_render_shows_every_row(client, insights, table_id):
    rows = _rows(client.get("/").text, table_id)
    assert len(rows) == 3
    assert not any("hidden" in row.split(">", 1)[0] for row in rows)


def test_dismissed_alert_leaves_the_count(client, test_db, insights):
    first = test_db.get_recent_alerts()[0]
    test_db.dismiss_alert(first["id"])
    page = client.get("/").text
    bar = _filter_bar(page, "alerts-table")
    assert "<span class='filter-count'>(2)</span>" in _buttons(bar)["all"]
    assert len(_rows(page, "alerts-table")) == 2


def test_empty_tables_have_no_filter_bar(client):
    page = client.get("/").text
    assert "class='type-filter'" not in page
    assert "{alert_filter}" not in page and "{findings_filter}" not in page
