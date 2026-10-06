"""Scout Agent — Monitors competitors and collects data."""
import hashlib
import httpx
from bs4 import BeautifulSoup
from typing import Optional
from datetime import datetime

from prysma.storage.database import db
from prysma.security import sanitize_scraped_content, contains_suspicious_content
from prysma.config import config
from prysma.sources.tavily_search import TavilySource

# Keys accepted by db.add_finding
FINDING_DB_KEYS = ('competitor_id', 'finding_type', 'title', 'content', 'source_url', 'importance')


def _store_finding(finding: dict) -> int:
    """Save a finding dict, ignoring display-only keys such as competitor_name."""
    return db.add_finding(**{k: finding[k] for k in FINDING_DB_KEYS if k in finding})


class ScoutAgent:
    """Scouts the web for competitor updates and market intelligence."""

    def __init__(self):
        self.client = httpx.Client(
            timeout=30.0,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        self.tavily = TavilySource()

    def scan_all(self) -> dict:
        """Run a full scan of all watched competitors and sources."""
        results = {
            'changes_detected': 0,
            'new_findings': 0,
            'errors': 0,
            'details': []
        }

        competitors = db.get_active_competitors()
        for competitor in competitors:
            try:
                findings = self.scan_competitor(competitor)
                results['new_findings'] += len(findings)
                results['details'].extend(findings)
            except Exception as e:
                results['errors'] += 1
                results['details'].append({
                    'error': str(e),
                    'competitor': competitor['name']
                })

        return results

    def scan_competitor(self, competitor: dict) -> list:
        """Scan a single competitor for changes."""
        findings = []
        watch_items = db.get_watch_items(competitor['id'])

        for item in watch_items:
            try:
                finding = self.check_watch_item(item, competitor)
                if finding:
                    findings.append(finding)
            except Exception as e:
                findings.append({'error': str(e), 'item_id': item['id']})

        # Also check news if no specific watch items
        if not watch_items and competitor.get('website'):
            news_findings = self.check_news(competitor)
            findings.extend(news_findings)

        # Recent news and updates via Tavily
        findings.extend(self.tavily.search_competitor_news(competitor))

        return findings

    def check_watch_item(self, item: dict, competitor: dict) -> Optional[dict]:
        """Check a single watch item for changes."""
        response = self.client.get(item['url'])
        response.raise_for_status()

        content = response.text
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # Check if content changed
        if item['last_content_hash'] == content_hash:
            db.update_watch_item_hash(item['id'], content_hash)
            return None

        # Content changed — extract the diff
        db.update_watch_item_hash(item['id'], content_hash)
        db.mark_watch_item_changed(item['id'])

        # Parse and sanitize content
        soup = BeautifulSoup(content, 'lxml')
        text_content = soup.get_text(separator=' ', strip=True)
        sanitized = sanitize_scraped_content(text_content)

        # Check for suspicious content
        is_suspicious, pattern = contains_suspicious_content(sanitized)

        # Extract title
        title_tag = soup.find('title')
        page_title = title_tag.get_text() if title_tag else 'Page update'

        finding = {
            'competitor_id': competitor['id'],
            'competitor_name': competitor['name'],
            'finding_type': 'change',
            'title': f"Update detected: {page_title[:100]}",
            'content': sanitized[:2000],
            'source_url': item['url'],
            'importance': 3,
            'suspicious': is_suspicious
        }

        finding_id = _store_finding(finding)
        finding['id'] = finding_id

        return finding

    def check_news(self, competitor: dict) -> list:
        """Check for news about a competitor."""
        findings = []

        if not config.newsapi_key:
            return findings

        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                'q': competitor['name'],
                'sortBy': 'publishedAt',
                'language': 'en',
                'pageSize': 5,
                'apiKey': config.newsapi_key
            }

            response = self.client.get(url, params=params)
            data = response.json()

            if data.get('status') == 'ok':
                for article in data.get('articles', []):
                    content = f"{article.get('title', '')}\n{article.get('description', '')}"
                    sanitized = sanitize_scraped_content(content)

                    finding = {
                        'competitor_id': competitor['id'],
                        'competitor_name': competitor['name'],
                        'finding_type': 'news',
                        'title': article.get('title', 'News mention')[:200],
                        'content': sanitized[:1000],
                        'source_url': article.get('url'),
                        'importance': 2
                    }

                    finding_id = _store_finding(finding)
                    findings.append({**finding, 'id': finding_id})

        except Exception as e:
            findings.append({'error': str(e), 'source': 'news_api'})

        return findings

    def check_rss(self, competitor: dict, rss_url: str) -> list:
        """Check an RSS feed for updates."""
        import feedparser

        findings = []
        try:
            feed = feedparser.parse(rss_url)

            for entry in feed.entries[:5]:
                content = f"{entry.get('title', '')}\n{entry.get('summary', '')}"
                sanitized = sanitize_scraped_content(content)

                finding = {
                    'competitor_id': competitor['id'],
                    'competitor_name': competitor['name'],
                    'finding_type': 'change',
                    'title': entry.get('title', 'RSS update')[:200],
                    'content': sanitized[:1000],
                    'source_url': entry.get('link'),
                    'importance': 2
                }

                finding_id = _store_finding(finding)
                findings.append({**finding, 'id': finding_id})

        except Exception as e:
            findings.append({'error': str(e), 'source': 'rss'})

        return findings

    def close(self):
        self.client.close()
