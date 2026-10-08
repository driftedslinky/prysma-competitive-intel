"""Database models and operations for Prysma."""
import hashlib
import json
import sqlite3
from typing import Optional
from contextlib import contextmanager

from prysma.config import config


# Seed data: default competitors (round/interval timer apps) and their store IDs.
# Load with `python -m prysma.storage.migrations --seed`. Add others via /watch.
DEFAULT_COMPETITOR_STORE_IDS = {
    "Interval Timer": {"android": "cc.dreamspark.intervaltimer"},
    "Tabata Timer": {"android": "com.evgeniysharafan.tabatatimer", "ios": "id1255964203"},
    "Seconds Interval Timer": {"android": "com.runloop.seconds.free", "ios": "id475816966"},
    "Intervals Pro": {"ios": "id957586938"},
    "Box Timer": {"ios": "id1547518531"},
    "SmartWOD": {"android": "net.smartwod.workouts", "ios": "id1317933303"},
    "Boxing Round Interval Timer": {"android": "kr.co.royzero.boxingtimer"},
    "PushPress Timer": {"ios": "id1554256831"},
}


class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.database_path
        self.init_db()

    @contextmanager
    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _rows_to_dicts(self, rows: list) -> list[dict]:
        """Convert sqlite3.Row objects to dicts."""
        return [dict(row) for row in rows]

    def init_db(self):
        """Initialize database schema."""
        with self.get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS competitors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    website TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS watch_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor_id INTEGER,
                    item_type TEXT CHECK(item_type IN ('website', 'blog', 'pricing', 'jobs', 'github', 'news', 'reddit')),
                    url TEXT,
                    css_selector TEXT,
                    last_content_hash TEXT,
                    last_checked TIMESTAMP,
                    last_changed TIMESTAMP,
                    FOREIGN KEY (competitor_id) REFERENCES competitors(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor_id INTEGER,
                    finding_type TEXT CHECK(finding_type IN ('change', 'news', 'sentiment', 'trend', 'opportunity', 'github', 'reddit', 'product_launch', 'pricing_change', 'hiring', 'funding', 'partnership', 'negative_news', 'content')),
                    title TEXT NOT NULL,
                    content TEXT,
                    source_url TEXT,
                    importance INTEGER CHECK(importance BETWEEN 1 AND 5),
                    is_read BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (competitor_id) REFERENCES competitors(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS digests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    digest_type TEXT CHECK(digest_type IN ('daily', 'weekly', 'alert', 'research', 'trend', 'competitive')),
                    content TEXT NOT NULL,
                    sent_via_telegram BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS trend_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    signal_type TEXT CHECK(signal_type IN ('github', 'reddit', 'news', 'search', 'social')),
                    strength INTEGER DEFAULT 1,
                    source_url TEXT,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_processed BOOLEAN DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS trend_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    signals TEXT,
                    strength INTEGER CHECK(strength BETWEEN 1 AND 10),
                    is_emerging BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS user_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    finding_id INTEGER,
                    feedback_type TEXT CHECK(feedback_type IN ('useful', 'not_useful', 'more_like_this')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (finding_id) REFERENCES findings(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_findings_created ON findings(created_at);
                CREATE INDEX IF NOT EXISTS idx_findings_type ON findings(finding_type);
                CREATE INDEX IF NOT EXISTS idx_trend_signals_keyword ON trend_signals(keyword);
                CREATE INDEX IF NOT EXISTS idx_trend_signals_detected ON trend_signals(detected_at);
                
                -- Competitive Intelligence tables
                CREATE TABLE IF NOT EXISTS app_store_listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor_id INTEGER,
                    platform TEXT CHECK(platform IN ('ios', 'android')),
                    store_id TEXT,
                    app_name TEXT,
                    developer TEXT,
                    current_title TEXT,
                    current_subtitle TEXT,
                    current_description TEXT,
                    current_price TEXT,
                    current_rating REAL,
                    current_ratings_count INTEGER,
                    last_updated DATE,
                    last_checked TIMESTAMP,
                    FOREIGN KEY (competitor_id) REFERENCES competitors(id) ON DELETE CASCADE
                );
                
                CREATE TABLE IF NOT EXISTS aso_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor_id INTEGER,
                    platform TEXT CHECK(platform IN ('ios', 'android')),
                    change_type TEXT CHECK(change_type IN ('title', 'subtitle', 'description', 'price', 'screenshots', 'icon', 'category', 'rating', 'ratings_count', 'release_date', 'version')),
                    old_value TEXT,
                    new_value TEXT,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (competitor_id) REFERENCES competitors(id) ON DELETE CASCADE
                );
                
                CREATE TABLE IF NOT EXISTS competitor_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor_id INTEGER,
                    platform TEXT CHECK(platform IN ('ios', 'android')),
                    rating INTEGER,
                    title TEXT,
                    content TEXT,
                    author TEXT,
                    review_date DATE,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (competitor_id) REFERENCES competitors(id) ON DELETE CASCADE
                );
                
                CREATE TABLE IF NOT EXISTS competitor_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor_id INTEGER,
                    platform TEXT CHECK(platform IN ('ios', 'android')),
                    version TEXT,
                    release_date DATE,
                    changelog TEXT,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (competitor_id) REFERENCES competitors(id) ON DELETE CASCADE
                );
                
                CREATE TABLE IF NOT EXISTS pricing_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor_id INTEGER,
                    platform TEXT CHECK(platform IN ('ios', 'android')),
                    product_id TEXT,
                    product_name TEXT,
                    price TEXT,
                    price_type TEXT CHECK(price_type IN ('free', 'paid', 'subscription', 'one_time')),
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (competitor_id) REFERENCES competitors(id) ON DELETE CASCADE
                );
                
                CREATE TABLE IF NOT EXISTS new_entrants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT NOT NULL,
                    platform TEXT CHECK(platform IN ('ios', 'android')),
                    developer TEXT,
                    store_url TEXT,
                    category TEXT,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_reviewed BOOLEAN DEFAULT 0
                );
                
                CREATE INDEX IF NOT EXISTS idx_aso_changes_detected ON aso_changes(detected_at);
                CREATE INDEX IF NOT EXISTS idx_competitor_reviews_date ON competitor_reviews(review_date);
                CREATE INDEX IF NOT EXISTS idx_competitor_updates_date ON competitor_updates(release_date);
                CREATE INDEX IF NOT EXISTS idx_pricing_history_date ON pricing_history(detected_at);
                CREATE INDEX IF NOT EXISTS idx_new_entrants_detected ON new_entrants(detected_at);

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor_id INTEGER,
                    alert_type TEXT,
                    severity TEXT CHECK(severity IN ('high','medium','low')),
                    title TEXT NOT NULL,
                    message TEXT,
                    source_table TEXT,
                    source_id INTEGER,
                    is_sent BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (competitor_id) REFERENCES competitors(id) ON DELETE CASCADE
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_source ON alerts(source_table, source_id);
            """)

            # Migration: per-competitor app store IDs as JSON {"android": ..., "ios": ...}
            columns = [row['name'] for row in conn.execute("PRAGMA table_info(competitors)")]
            if 'store_ids' not in columns:
                conn.execute("ALTER TABLE competitors ADD COLUMN store_ids TEXT")

            # Migration: review content hash for dedupe; backfill existing rows
            columns = [row['name'] for row in conn.execute("PRAGMA table_info(competitor_reviews)")]
            if 'content_hash' not in columns:
                conn.execute("ALTER TABLE competitor_reviews ADD COLUMN content_hash TEXT")
                rows = conn.execute("SELECT id, content FROM competitor_reviews").fetchall()
                conn.executemany(
                    "UPDATE competitor_reviews SET content_hash = ? WHERE id = ?",
                    [(self._review_hash(row['content']), row['id']) for row in rows]
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_competitor_reviews_hash "
                "ON competitor_reviews(competitor_id, content_hash)"
            )

    # Competitor operations
    def add_competitor(self, name: str, website: str = None, description: str = None,
                       store_ids: dict = None) -> int:
        """Add a competitor, or reactivate an existing one.

        Store IDs given here are merged into any IDs already saved.
        """
        with self.get_conn() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO competitors (name, website, description) VALUES (?, ?, ?)",
                (name, website, description)
            )
            competitor_id = cursor.lastrowid if cursor.rowcount else None
            if not competitor_id:
                conn.execute("UPDATE competitors SET is_active = 1 WHERE name = ?", (name,))
                row = conn.execute("SELECT id FROM competitors WHERE name = ?", (name,)).fetchone()
                competitor_id = row['id'] if row else None

        if competitor_id and store_ids:
            self.set_competitor_store_ids(competitor_id, store_ids)
        return competitor_id

    def get_competitor_store_ids(self, competitor: dict) -> dict:
        """Return {"android": ..., "ios": ...} for a competitor row."""
        raw = competitor.get('store_ids')
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return {k: v for k, v in data.items() if k in ('android', 'ios') and v}

    def set_competitor_store_ids(self, competitor_id: int, store_ids: dict):
        """Merge store IDs into a competitor's saved IDs. Ignores empty values."""
        with self.get_conn() as conn:
            row = conn.execute("SELECT store_ids FROM competitors WHERE id = ?", (competitor_id,)).fetchone()
            if not row:
                return
            current = self.get_competitor_store_ids(dict(row))
            current.update({k: v for k, v in store_ids.items() if k in ('android', 'ios') and v})
            conn.execute(
                "UPDATE competitors SET store_ids = ? WHERE id = ?",
                (json.dumps(current), competitor_id)
            )

    def seed_default_competitors(self, seed: dict = None) -> int:
        """Add the default competitors and their store IDs. Returns count added or updated."""
        seed = seed if seed is not None else DEFAULT_COMPETITOR_STORE_IDS
        for name, store_ids in seed.items():
            self.add_competitor(name=name, store_ids=store_ids)
        return len(seed)

    def get_competitor_by_name(self, name: str) -> Optional[int]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT id FROM competitors WHERE name = ?", (name,)).fetchone()
            return row['id'] if row else None

    def get_active_competitors(self) -> list[dict]:
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM competitors WHERE is_active = 1 ORDER BY created_at DESC"
            ).fetchall()
            return self._rows_to_dicts(rows)

    def remove_competitor(self, name: str) -> bool:
        with self.get_conn() as conn:
            cursor = conn.execute("UPDATE competitors SET is_active = 0 WHERE name = ?", (name,))
            return cursor.rowcount > 0

    # Watch items
    def add_watch_item(self, competitor_id: int, item_type: str, url: str, css_selector: str = None) -> int:
        with self.get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO watch_items (competitor_id, item_type, url, css_selector) VALUES (?, ?, ?, ?)",
                (competitor_id, item_type, url, css_selector)
            )
            return cursor.lastrowid

    def get_watch_items(self, competitor_id: int = None) -> list[dict]:
        with self.get_conn() as conn:
            if competitor_id:
                rows = conn.execute(
                    "SELECT * FROM watch_items WHERE competitor_id = ?", (competitor_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM watch_items").fetchall()
            return self._rows_to_dicts(rows)

    def update_watch_item_hash(self, item_id: int, content_hash: str):
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE watch_items SET last_content_hash = ?, last_checked = CURRENT_TIMESTAMP WHERE id = ?",
                (content_hash, item_id)
            )

    def mark_watch_item_changed(self, item_id: int):
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE watch_items SET last_changed = CURRENT_TIMESTAMP WHERE id = ?",
                (item_id,)
            )

    # Findings
    def add_finding(self, competitor_id: int, finding_type: str, title: str,
                    content: str = None, source_url: str = None, importance: int = 3) -> int:
        with self.get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO findings (competitor_id, finding_type, title, content, source_url, importance) VALUES (?, ?, ?, ?, ?, ?)",
                (competitor_id, finding_type, title, content, source_url, importance)
            )
            return cursor.lastrowid

    def finding_exists(self, competitor_id: int, source_url: str) -> bool:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM findings WHERE competitor_id = ? AND source_url = ? LIMIT 1",
                (competitor_id, source_url)
            ).fetchone()
            return row is not None

    def get_recent_findings(self, hours: int = 24, finding_type: str = None) -> list[dict]:
        cutoff = f"-{hours} hours"  # SQLite modifier; columns are UTC CURRENT_TIMESTAMP
        with self.get_conn() as conn:
            if finding_type:
                rows = conn.execute(
                    """SELECT f.*, c.name as competitor_name FROM findings f 
                       LEFT JOIN competitors c ON f.competitor_id = c.id
                       WHERE f.finding_type = ? AND f.created_at > datetime('now', ?) 
                       ORDER BY f.importance DESC""",
                    (finding_type, cutoff)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT f.*, c.name as competitor_name FROM findings f 
                       LEFT JOIN competitors c ON f.competitor_id = c.id
                       WHERE f.created_at > datetime('now', ?) ORDER BY f.importance DESC""",
                    (cutoff,)
                ).fetchall()
            return self._rows_to_dicts(rows)

    def get_unread_findings(self) -> list[dict]:
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT f.*, c.name as competitor_name FROM findings f 
                   LEFT JOIN competitors c ON f.competitor_id = c.id
                   WHERE f.is_read = 0 ORDER BY f.importance DESC"""
            ).fetchall()
            return self._rows_to_dicts(rows)

    def mark_finding_read(self, finding_id: int):
        with self.get_conn() as conn:
            conn.execute("UPDATE findings SET is_read = 1 WHERE id = ?", (finding_id,))

    def update_finding_type(self, finding_id: int, finding_type: str):
        with self.get_conn() as conn:
            conn.execute("UPDATE findings SET finding_type = ? WHERE id = ?", (finding_type, finding_id))

    # Digests
    def add_digest(self, digest_type: str, content: str) -> int:
        with self.get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO digests (digest_type, content) VALUES (?, ?)",
                (digest_type, content)
            )
            return cursor.lastrowid

    def mark_digest_sent(self, digest_id: int):
        with self.get_conn() as conn:
            conn.execute("UPDATE digests SET sent_via_telegram = 1 WHERE id = ?", (digest_id,))

    # Trend signals
    def add_trend_signal(self, keyword: str, signal_type: str, strength: int = 1, source_url: str = None) -> int:
        with self.get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO trend_signals (keyword, signal_type, strength, source_url) VALUES (?, ?, ?, ?)",
                (keyword, signal_type, strength, source_url)
            )
            return cursor.lastrowid

    def get_trend_signals(self, days: int = None, unprocessed_only: bool = False) -> list[dict]:
        days = days or config.trend_lookback_days
        cutoff = f"-{days} days"  # SQLite modifier; columns are UTC CURRENT_TIMESTAMP
        query = "SELECT * FROM trend_signals WHERE detected_at > datetime('now', ?)"
        params = [cutoff]

        if unprocessed_only:
            query += " AND is_processed = 0"

        with self.get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return self._rows_to_dicts(rows)

    def get_trend_strength(self, keyword: str, days: int = None) -> int:
        """Calculate total trend strength for a keyword."""
        signals = self.get_trend_signals(days=days)
        return sum(s['strength'] for s in signals if s['keyword'].lower() == keyword.lower())

    def mark_trend_processed(self, signal_ids: list[int]):
        with self.get_conn() as conn:
            placeholders = ','.join('?' * len(signal_ids))
            conn.execute(
                f"UPDATE trend_signals SET is_processed = 1 WHERE id IN ({placeholders})",
                signal_ids
            )

    # Trend reports
    def add_trend_report(self, title: str, description: str, signals: str, strength: int, is_emerging: bool = False) -> int:
        with self.get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO trend_reports (title, description, signals, strength, is_emerging) VALUES (?, ?, ?, ?, ?)",
                (title, description, signals, strength, is_emerging)
            )
            return cursor.lastrowid

    def get_trend_reports(self, emerging_only: bool = False) -> list[dict]:
        with self.get_conn() as conn:
            if emerging_only:
                rows = conn.execute(
                    "SELECT * FROM trend_reports WHERE is_emerging = 1 ORDER BY strength DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trend_reports ORDER BY strength DESC"
                ).fetchall()
            return self._rows_to_dicts(rows)

    # App Store Listing operations
    def upsert_app_listing(self, competitor_id: int, platform: str, store_id: str,
                           app_name: str, developer: str = None, title: str = None,
                           subtitle: str = None, description: str = None,
                           price: str = None, rating: float = None,
                           ratings_count: int = None, last_updated: str = None) -> dict:
        """Insert or update an app store listing. Returns dict with 'id' and 'changed' flag."""
        with self.get_conn() as conn:
            # Check if listing exists
            existing = conn.execute(
                "SELECT * FROM app_store_listings WHERE competitor_id = ? AND platform = ?",
                (competitor_id, platform)
            ).fetchone()
            
            if existing:
                # Check for changes
                changes = {}
                if title and title != existing['current_title']:
                    changes['title'] = (existing['current_title'], title)
                if subtitle and subtitle != existing['current_subtitle']:
                    changes['subtitle'] = (existing['current_subtitle'], subtitle)
                if description and description != existing['current_description']:
                    changes['description'] = (existing['current_description'], description)
                if price and price != existing['current_price']:
                    changes['price'] = (existing['current_price'], price)
                if rating and rating != existing['current_rating']:
                    changes['rating'] = (str(existing['current_rating']), str(rating))
                if ratings_count and ratings_count != existing['current_ratings_count']:
                    changes['ratings_count'] = (str(existing['current_ratings_count']), str(ratings_count))
                
                # Update
                conn.execute(
                    """UPDATE app_store_listings SET
                        app_name = ?, developer = ?, current_title = ?,
                        current_subtitle = ?, current_description = ?,
                        current_price = ?, current_rating = ?,
                        current_ratings_count = ?, last_updated = ?,
                        last_checked = CURRENT_TIMESTAMP
                       WHERE competitor_id = ? AND platform = ?""",
                    (app_name, developer, title, subtitle, description,
                     price, rating, ratings_count, last_updated,
                     competitor_id, platform)
                )
                
                # Record changes
                for change_type, (old_val, new_val) in changes.items():
                    conn.execute(
                        "INSERT INTO aso_changes (competitor_id, platform, change_type, old_value, new_value) VALUES (?, ?, ?, ?, ?)",
                        (competitor_id, platform, change_type, str(old_val)[:500], str(new_val)[:500])
                    )
                
                return {'id': existing['id'], 'changed': len(changes) > 0, 'changes': changes}
            else:
                # Insert new
                cursor = conn.execute(
                    """INSERT INTO app_store_listings
                        (competitor_id, platform, store_id, app_name, developer,
                         current_title, current_subtitle, current_description,
                         current_price, current_rating, current_ratings_count, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (competitor_id, platform, store_id, app_name, developer,
                     title, subtitle, description, price, rating, ratings_count, last_updated)
                )
                return {'id': cursor.lastrowid, 'changed': True, 'changes': {'new_listing': (None, app_name)}}

    def get_app_listings(self, competitor_id: int = None) -> list[dict]:
        with self.get_conn() as conn:
            if competitor_id:
                rows = conn.execute(
                    "SELECT * FROM app_store_listings WHERE competitor_id = ?", (competitor_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM app_store_listings").fetchall()
            return self._rows_to_dicts(rows)

    def get_aso_changes(self, hours: int = 24) -> list[dict]:
        cutoff = f"-{hours} hours"  # SQLite modifier; columns are UTC CURRENT_TIMESTAMP
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT ac.*, c.name as competitor_name FROM aso_changes ac
                   LEFT JOIN competitors c ON ac.competitor_id = c.id
                   WHERE ac.detected_at > datetime('now', ?) ORDER BY ac.detected_at DESC""",
                (cutoff,)
            ).fetchall()
            return self._rows_to_dicts(rows)

    # Competitor Reviews
    @staticmethod
    def _review_hash(content: str) -> str:
        return hashlib.sha256((content or '').strip().lower().encode('utf-8')).hexdigest()

    def review_exists(self, competitor_id: int, content: str) -> bool:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM competitor_reviews WHERE competitor_id = ? AND content_hash = ? LIMIT 1",
                (competitor_id, self._review_hash(content))
            ).fetchone()
            return row is not None

    def add_review(self, competitor_id: int, platform: str, rating: int,
                   title: str, content: str, author: str, review_date: str) -> int:
        with self.get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO competitor_reviews
                    (competitor_id, platform, rating, title, content, author, review_date, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (competitor_id, platform, rating, title, content, author, review_date,
                 self._review_hash(content))
            )
            return cursor.lastrowid

    def get_recent_reviews(self, competitor_id: int = None, rating_max: int = 5, hours: int = 24) -> list[dict]:
        cutoff = f"-{hours} hours"  # SQLite modifier; columns are UTC CURRENT_TIMESTAMP
        with self.get_conn() as conn:
            if competitor_id:
                rows = conn.execute(
                    """SELECT cr.*, c.name as competitor_name FROM competitor_reviews cr
                       LEFT JOIN competitors c ON cr.competitor_id = c.id
                       WHERE cr.competitor_id = ? AND cr.rating <= ? AND cr.detected_at > datetime('now', ?)
                       ORDER BY cr.detected_at DESC""",
                    (competitor_id, rating_max, cutoff)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT cr.*, c.name as competitor_name FROM competitor_reviews cr
                       LEFT JOIN competitors c ON cr.competitor_id = c.id
                       WHERE cr.rating <= ? AND cr.detected_at > datetime('now', ?)
                       ORDER BY cr.detected_at DESC""",
                    (rating_max, cutoff)
                ).fetchall()
            return self._rows_to_dicts(rows)

    # Competitor Updates
    def add_update(self, competitor_id: int, platform: str, version: str,
                   release_date: str, changelog: str) -> int:
        with self.get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO competitor_updates
                    (competitor_id, platform, version, release_date, changelog)
                   VALUES (?, ?, ?, ?, ?)""",
                (competitor_id, platform, version, release_date, changelog)
            )
            return cursor.lastrowid

    def get_recent_updates(self, hours: int = 168) -> list[dict]:
        cutoff = f"-{hours} hours"  # SQLite modifier; columns are UTC CURRENT_TIMESTAMP
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT cu.*, c.name as competitor_name FROM competitor_updates cu
                   LEFT JOIN competitors c ON cu.competitor_id = c.id
                   WHERE cu.detected_at > datetime('now', ?) ORDER BY cu.detected_at DESC""",
                (cutoff,)
            ).fetchall()
            return self._rows_to_dicts(rows)

    # Pricing History
    def add_pricing(self, competitor_id: int, platform: str, product_id: str,
                    product_name: str, price: str, price_type: str) -> int:
        with self.get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO pricing_history
                    (competitor_id, platform, product_id, product_name, price, price_type)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (competitor_id, platform, product_id, product_name, price, price_type)
            )
            return cursor.lastrowid

    def get_pricing_history(self, competitor_id: int = None, hours: int = 168) -> list[dict]:
        cutoff = f"-{hours} hours"  # SQLite modifier; columns are UTC CURRENT_TIMESTAMP
        with self.get_conn() as conn:
            if competitor_id:
                rows = conn.execute(
                    """SELECT ph.*, c.name as competitor_name FROM pricing_history ph
                       LEFT JOIN competitors c ON ph.competitor_id = c.id
                       WHERE ph.competitor_id = ? AND ph.detected_at > datetime('now', ?)
                       ORDER BY ph.detected_at DESC""",
                    (competitor_id, cutoff)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT ph.*, c.name as competitor_name FROM pricing_history ph
                       LEFT JOIN competitors c ON ph.competitor_id = c.id
                       WHERE ph.detected_at > datetime('now', ?) ORDER BY ph.detected_at DESC""",
                    (cutoff,)
                ).fetchall()
            return self._rows_to_dicts(rows)

    # New Entrants
    def add_new_entrant(self, app_name: str, platform: str, developer: str,
                        store_url: str, category: str) -> int:
        with self.get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO new_entrants (app_name, platform, developer, store_url, category)
                   VALUES (?, ?, ?, ?, ?)""",
                (app_name, platform, developer, store_url, category)
            )
            return cursor.lastrowid

    def get_new_entrants(self, hours: int = 168, unreviewed_only: bool = False) -> list[dict]:
        cutoff = f"-{hours} hours"  # SQLite modifier; columns are UTC CURRENT_TIMESTAMP
        query = "SELECT * FROM new_entrants WHERE detected_at > datetime('now', ?)"
        params = [cutoff]
        if unreviewed_only:
            query += " AND is_reviewed = 0"
        query += " ORDER BY detected_at DESC"
        with self.get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return self._rows_to_dicts(rows)

    # Alerts
    def add_alert(self, competitor_id: int, alert_type: str, severity: str, title: str,
                  message: str, source_table: str, source_id: int) -> Optional[int]:
        """Insert an alert. Returns the new id, or None if the source row already has one."""
        with self.get_conn() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO alerts
                    (competitor_id, alert_type, severity, title, message, source_table, source_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (competitor_id, alert_type, severity, title, message, source_table, source_id)
            )
            return cursor.lastrowid if cursor.rowcount else None

    def get_unsent_alerts(self) -> list[dict]:
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT a.*, c.name as competitor_name FROM alerts a
                   LEFT JOIN competitors c ON a.competitor_id = c.id
                   WHERE a.is_sent = 0 ORDER BY a.id"""
            ).fetchall()
            return self._rows_to_dicts(rows)

    def mark_alert_sent(self, alert_id: int):
        with self.get_conn() as conn:
            conn.execute("UPDATE alerts SET is_sent = 1 WHERE id = ?", (alert_id,))

    def get_recent_alerts(self, hours: int = 168, limit: int = 50) -> list[dict]:
        cutoff = f"-{hours} hours"  # SQLite modifier; columns are UTC CURRENT_TIMESTAMP
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT a.*, c.name as competitor_name FROM alerts a
                   LEFT JOIN competitors c ON a.competitor_id = c.id
                   WHERE a.created_at > datetime('now', ?)
                   ORDER BY a.created_at DESC, a.id DESC LIMIT ?""",
                (cutoff, limit)
            ).fetchall()
            return self._rows_to_dicts(rows)


db = Database()
