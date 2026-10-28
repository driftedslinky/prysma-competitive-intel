"""The sortable Findings table on the Insights tab.

The sorting itself runs in the browser, and this suite has no browser. These
tests do not click anything. They check only the markup contract that the page
script relies on: the data-sort values, the server order, and the accessible
header controls.
"""
import re
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


def _findings_table(page: str) -> str:
    start = page.index('id="findings-table"')
    return page[start:page.index("</table>", start)]


def _body_rows(table: str) -> list[str]:
    body = table[table.index("<tbody>"):]
    return re.findall(r"<tr[ >].*?</tr>", body, re.S)


@pytest.fixture
def three_findings(test_db):
    cid = test_db.get_competitor_by_name("Timer A")
    test_db.add_finding(cid, "news", "Timer A raises money", importance=2)
    test_db.add_finding(cid, "opportunity", "2 new negative reviews (Timer A)", importance=5)
    test_db.add_finding(cid, "change", "Pricing page changed", importance=3)
    return cid


def test_every_time_cell_has_one_iso_data_sort(client, three_findings):
    rows = _body_rows(_findings_table(client.get("/").text))
    assert len(rows) == 3
    for row in rows:
        stamps = re.findall(r"data-sort='([^']*)'", row)
        assert len(stamps) == 1, row
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamps[0])
        assert f"<td class='when-col' data-sort='{stamps[0]}'>" in row


def test_default_order_is_still_most_important_first(client, three_findings):
    page = client.get("/").text
    rows = _body_rows(_findings_table(page))
    assert INSIGHT_LABELS["review"] in rows[0]
    assert INSIGHT_LABELS["listing"] in rows[1]
    assert INSIGHT_LABELS["news"] in rows[2]
    assert '<span class="sub" id="findings-order">Most important first</span>' in page


def test_headers_carry_aria_sort_and_a_focusable_button(client):
    head = _findings_table(client.get("/").text)
    head = head[:head.index("</thead>")]
    headers = re.findall(r"<th[ >].*?</th>", head, re.S)
    assert len(headers) == 5
    for th in headers:
        assert th.startswith('<th aria-sort="none">'), th
        assert '<button type="button" class="sort-btn"' in th
        assert '<span class="sort-arrow" aria-hidden="true"></span>' in th
    assert "data-sort-time" in headers[3]


def test_empty_table_keeps_the_empty_row(client):
    rows = _body_rows(_findings_table(client.get("/").text))
    assert len(rows) == 1 and "No findings in this window." in rows[0]
