"""Base class for all data sources."""
from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime

from prysma.storage.database import db


class BaseSource(ABC):
    """Abstract base class for data sources."""

    def __init__(self, competitor_id: int = None):
        self.competitor_id = competitor_id

    @abstractmethod
    def check(self) -> list:
        """Check for new data. Returns list of findings."""
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """Return source name."""
        pass


class WebSource(BaseSource):
    """Generic web page monitor with change detection."""

    def __init__(self, url: str, css_selector: str = None, competitor_id: int = None):
        super().__init__(competitor_id)
        self.url = url
        self.css_selector = css_selector
        self.last_hash = None

    def check(self) -> list:
        """Check web page for changes."""
        import httpx
        from bs4 import BeautifulSoup
        import hashlib

        findings = []

        try:
            client = httpx.Client(timeout=30.0, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response = client.get(self.url)
            response.raise_for_status()

            content = response.text
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            if self.last_hash == content_hash:
                client.close()
                return findings

            self.last_hash = content_hash

            soup = BeautifulSoup(content, 'lxml')

            if self.css_selector:
                elements = soup.select(self.css_selector)
                text = ' '.join(e.get_text() for e in elements)
            else:
                text = soup.get_text(separator=' ', strip=True)

            title_tag = soup.find('title')
            page_title = title_tag.get_text() if title_tag else 'Page update'

            from prysma.security import sanitize_scraped_content
            sanitized = sanitize_scraped_content(text)

            finding = {
                'competitor_id': self.competitor_id,
                'finding_type': 'change',
                'title': f"Web update: {page_title[:100]}",
                'content': sanitized[:2000],
                'source_url': self.url,
                'importance': 3
            }

            finding_id = db.add_finding(**finding)
            findings.append({**finding, 'id': finding_id})

            client.close()

        except Exception as e:
            findings.append({'error': str(e), 'url': self.url})

        return findings

    def get_source_name(self) -> str:
        return f"web:{self.url}"


class GitHubSource(BaseSource):
    """Monitors GitHub repositories for activity."""

    def __init__(self, repo: str, competitor_id: int = None):
        super().__init__(competitor_id)
        self.repo = repo

    def check(self) -> list:
        """Check GitHub repo for recent activity."""
        import httpx
        from prysma.config import config
        from prysma.security import sanitize_scraped_content

        findings = []

        try:
            url = f"https://api.github.com/repos/{self.repo}/events"
            headers = {'Accept': 'application/vnd.github.v3+json'}

            if config.github_token:
                headers['Authorization'] = f'token {config.github_token}'

            client = httpx.Client(timeout=30.0)
            response = client.get(url, headers=headers)
            data = response.json()

            for event in data[:10]:
                event_type = event.get('type', 'Unknown')
                actor = event.get('actor', {}).get('login', 'unknown')
                created = event.get('created_at', '')

                title = f"{event_type} by {actor}"
                content = f"Event: {event_type}\nActor: {actor}\nDate: {created}"
                sanitized = sanitize_scraped_content(content)

                finding = {
                    'competitor_id': self.competitor_id,
                    'finding_type': 'github',
                    'title': title[:200],
                    'content': sanitized[:500],
                    'source_url': f"https://github.com/{self.repo}",
                    'importance': 2
                }

                finding_id = db.add_finding(**finding)
                findings.append({**finding, 'id': finding_id})

            client.close()

        except Exception as e:
            findings.append({'error': str(e), 'repo': self.repo})

        return findings

    def get_source_name(self) -> str:
        return f"github:{self.repo}"


class NewsSource(BaseSource):
    """Monitors news via NewsAPI."""

    def __init__(self, query: str, competitor_id: int = None):
        super().__init__(competitor_id)
        self.query = query

    def check(self) -> list:
        """Check news for mentions."""
        import httpx
        from prysma.config import config
        from prysma.security import sanitize_scraped_content

        findings = []

        if not config.newsapi_key:
            return findings

        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                'q': self.query,
                'sortBy': 'publishedAt',
                'language': 'en',
                'pageSize': 5,
                'apiKey': config.newsapi_key
            }

            client = httpx.Client(timeout=30.0)
            response = client.get(url, params=params)
            data = response.json()

            for article in data.get('articles', []):
                title = article.get('title', '')
                description = article.get('description', '') or ''

                content = f"{title} {description}"
                sanitized = sanitize_scraped_content(content)

                finding = {
                    'competitor_id': self.competitor_id,
                    'finding_type': 'news',
                    'title': title[:200],
                    'content': sanitized[:1000],
                    'source_url': article.get('url'),
                    'importance': 2
                }

                finding_id = db.add_finding(**finding)
                findings.append({**finding, 'id': finding_id})

            client.close()

        except Exception as e:
            findings.append({'error': str(e), 'query': self.query})

        return findings

    def get_source_name(self) -> str:
        return f"news:{self.query}"


class RedditSource(BaseSource):
    """Monitors Reddit for mentions."""

    def __init__(self, subreddit: str, query: str, competitor_id: int = None):
        super().__init__(competitor_id)
        self.subreddit = subreddit
        self.query = query

    def check(self) -> list:
        """Check Reddit for mentions."""
        import httpx
        from prysma.security import sanitize_scraped_content

        findings = []

        try:
            url = f"https://www.reddit.com/r/{self.subreddit}/search.json"
            params = {
                'q': self.query,
                'sort': 'new',
                'restrict_sr': 'on',
                'limit': 10
            }

            client = httpx.Client(timeout=30.0, headers={
                'User-Agent': 'Prysma/1.0'
            })
            response = client.get(url, params=params)
            data = response.json()

            for post in data.get('data', {}).get('children', []):
                post_data = post.get('data', {})
                title = post_data.get('title', '')
                selftext = post_data.get('selftext', '')[:500]
                score = post_data.get('score', 0)

                content = f"{title} {selftext}"
                sanitized = sanitize_scraped_content(content)

                finding = {
                    'competitor_id': self.competitor_id,
                    'finding_type': 'reddit',
                    'title': title[:200],
                    'content': sanitized[:1000],
                    'source_url': f"https://reddit.com{post_data.get('permalink', '')}",
                    'importance': min(score // 50 + 1, 5)
                }

                finding_id = db.add_finding(**finding)
                findings.append({**finding, 'id': finding_id})

            client.close()

        except Exception as e:
            findings.append({'error': str(e), 'subreddit': self.subreddit})

        return findings

    def get_source_name(self) -> str:
        return f"reddit:r/{self.subreddit}"
