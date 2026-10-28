"""The Google Play in-app purchase range: parsing, storage, migration, and the card."""
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from prysma.agents.competitive_intel import parse_play_iap_range
from prysma.storage.database import Database
from prysma.web import app as web_app


class TestParsePlayIapRange:
    """The page carries the target app's own range and the ranges of the apps in
    the "similar apps" carousel, and they are distinguishable only by the
    characters that precede them."""

    # The target app's own row: the range follows "],[2],[" directly.
    TARGET = ('<div>In-app purchases</div>["1,000,000+",1000000,1591094,"1M+"]'
              'null,null,null,null,[2],["£0.29 - £9.49 if billed through Play",[0]]')

    # A recommended app's row: "[2],null,[1,1,0],[" comes before the range.
    RECOMMENDED = ('["Install"],null,["CgYKBENBRT0="]]]],[2],null,[1,1,0],'
                   '["£0.59 - £114.99 if billed through Play",[0]]')

    def test_returns_the_target_apps_own_range(self):
        assert parse_play_iap_range(self.TARGET) == "£0.29 - £9.49 if billed through Play"

    def test_ignores_a_recommended_apps_range(self):
        assert parse_play_iap_range(self.RECOMMENDED) is None

    def test_prefers_the_target_over_the_carousel(self):
        # Both shapes on one page: the target's must win.
        assert parse_play_iap_range(self.RECOMMENDED + self.TARGET) == \
            "£0.29 - £9.49 if billed through Play"

    def test_the_carousel_order_does_not_change_the_answer(self):
        """The regression: Google varies the carousel between requests.

        An earlier version matched the first range anywhere on the page, so two
        consecutive fetches of the same app returned different prices, and for
        one app it returned a recommended app's range entirely.
        """
        carousel_a = self.RECOMMENDED
        carousel_b = ('["Install"],null,["TOKEN"]]]],[2],null,[1,1,0],'
                      '["£11.49 - £189.99 if billed through Play",[0]]')
        assert parse_play_iap_range(carousel_a + self.TARGET) == \
            parse_play_iap_range(carousel_b + self.TARGET) == \
            "£0.29 - £9.49 if billed through Play"

    def test_returns_none_without_a_range(self):
        assert parse_play_iap_range("<html>Free · Contains ads</html>") is None

    def test_other_currencies(self):
        assert parse_play_iap_range('[2],["$1.99 - $49.99 if billed through Play",[0]]') == \
            "$1.99 - $49.99 if billed through Play"
        assert parse_play_iap_range('[2],["€1,99 - €9,99 if billed through Play",[0]]') == \
            "€1,99 - €9,99 if billed through Play"


class TestIapRangeStorage:
    def test_upsert_stores_and_updates_the_range(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        database.add_competitor("Opal")
        cid = database.get_competitor_by_name("Opal")
        database.upsert_app_listing(cid, "android", "a.b", "Opal", price="Free",
                                    iap_range="£2.99 - £79.99 if billed through Play")
        database.upsert_app_listing(cid, "android", "a.b", "Opal", price="Free",
                                    iap_range="£2.99 - £89.99 if billed through Play")
        [listing] = database.get_app_listings(cid)
        assert listing["current_iap_range"] == "£2.99 - £89.99 if billed through Play"

    def test_migration_adds_the_column_and_keeps_rows(self, tmp_path):
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE competitors (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                website TEXT, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1);
            CREATE TABLE app_store_listings (id INTEGER PRIMARY KEY AUTOINCREMENT, competitor_id INTEGER,
                platform TEXT CHECK(platform IN ('ios', 'android')), store_id TEXT, app_name TEXT,
                developer TEXT, current_title TEXT, current_subtitle TEXT, current_description TEXT,
                current_price TEXT, current_rating REAL, current_ratings_count INTEGER,
                last_updated DATE, last_checked TIMESTAMP);
            INSERT INTO competitors (name) VALUES ('Old');
            INSERT INTO app_store_listings (competitor_id, platform, store_id, app_name, current_price, current_rating)
                VALUES (1, 'android', 'old.app', 'Old', 'Free', 4.6);
        """)
        conn.commit()
        conn.close()

        database = Database(path)
        [listing] = database.get_app_listings(1)
        assert listing["app_name"] == "Old" and listing["current_price"] == "Free"
        assert listing["current_rating"] == 4.6
        assert "current_iap_range" in listing and listing["current_iap_range"] is None
        Database(path)  # second init is a no-op, not an error
        assert len(Database(path).get_app_listings()) == 1


class TestCompetitorCardPrice:
    @pytest.fixture
    def test_db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        database.add_competitor("Timer A")
        return database

    @pytest.fixture
    def client(self, test_db):
        web_app._rate_hits.clear()
        with patch("prysma.web.app.db", test_db):
            yield TestClient(web_app.app)

    def test_card_shows_rating_price_and_iap_range(self, client, test_db):
        cid = test_db.get_competitor_by_name("Timer A")
        test_db.upsert_app_listing(cid, "android", "a.b", "A", price="Free", rating=4.6,
                                   iap_range="£0.59 - £114.99 if billed through Play")
        test_db.upsert_app_listing(cid, "ios", "123", "A", price="Free", rating=4.62)
        page = client.get("/").text
        card = page[page.index(f"id='comp-{cid}'"):]
        card = card[:card.index("</article>")]
        assert "<strong>Android</strong> 4.6★ Free · In-app purchases £0.59–£114.99" in card
        assert "<strong>iOS</strong> 4.6★ Free</p>" in card
        assert "This app's listing changes" in card  # the existing section stays
