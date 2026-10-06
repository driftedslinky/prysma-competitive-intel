"""RSS feed monitor source."""
import feedparser
from typing import Optional
from datetime import datetime

from prysma.storage.database import db
from prysma.security import sanitize_scraped_content


class RSSSource:
    """Monitors RSS/Atom feeds for updates."""

    def __init__(self, feed_url: str, competitor_id: int = None):
        self.feed_url = feed_url
        self.competitor_id = competitor_id

    def check(self) -> list:
        """Check feed for new entries."""
        findings = []

        try:
            feed = feedparser.parse(self.feed_url)

            for entry in feed.entries[:10]:  # Check latest 10 entries
                title = entry.get('title', 'No title')
                summary = entry.get('summary', '') or entry.get('description', '')
                link = entry.get('link', '')

                # Parse published date
                published = entry.get('published_parsed') or entry.get('updated_parsed')
                if published:
                    pub_date = datetime(*published[:6])
                    # Skip entries older than 7 days
                    if (datetime.now() - pub_date).days > 7:
                        continue

                content = f"{title} {summary}"
                sanitized = sanitize_scraped_content(content)

                finding = {
                    'competitor_id': self.competitor_id,
                    'finding_type': 'change',
                    'title': title[:200],
                    'content': sanitized[:1000],
                    'source_url': link,
                    'importance': 2
                }

                finding_id = db.add_finding(**finding)
                findings.append({**finding, 'id': finding_id})

        except Exception as e:
            findings.append({'error': str(e), 'source': self.feed_url})

        return findings
