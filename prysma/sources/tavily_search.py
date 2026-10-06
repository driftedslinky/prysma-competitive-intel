"""Tavily search source — competitor news, updates, and market trends."""
from typing import Optional

from tavily import TavilyClient

from prysma.config import config
from prysma.security import sanitize_scraped_content, contains_suspicious_content
from prysma.sources.base import BaseSource
from prysma.storage.database import db


class TavilySource(BaseSource):
    """Searches the web via Tavily for competitor news and market trends."""

    def __init__(self, query: str = None, competitor_id: int = None):
        super().__init__(competitor_id)
        self.query = query
        self.client = TavilyClient(api_key=config.tavily_api_key) if config.tavily_api_key else None

    def search(self, query: str, topic: str = "general", time_range: Optional[str] = None,
               max_results: int = 5) -> list[dict]:
        """Run a Tavily search. Returns sanitized results: title, url, content, score."""
        if not self.client:
            return []

        response = self.client.search(
            query=query,
            topic=topic,
            time_range=time_range,
            max_results=max_results,
        )

        results = []
        for item in response.get("results", []):
            content = sanitize_scraped_content(item.get("content", "") or "")
            is_suspicious, _ = contains_suspicious_content(content)
            results.append({
                "title": sanitize_scraped_content(item.get("title", "") or "")[:200],
                "url": item.get("url"),
                "content": content[:1000],
                "score": item.get("score", 0),
                "suspicious": is_suspicious,
            })
        return results

    def search_competitor_news(self, competitor: dict, time_range: str = "week",
                               max_results: int = 5) -> list[dict]:
        """Search recent news and updates about a competitor and store new findings."""
        query = f"{competitor['name']} app news updates"
        findings = []

        try:
            results = self.search(query, topic="news", time_range=time_range, max_results=max_results)
        except Exception as e:
            return [{"error": str(e), "source": "tavily"}]

        for result in results:
            if not result["url"] or db.finding_exists(competitor["id"], result["url"]):
                continue

            finding = {
                "competitor_id": competitor["id"],
                "finding_type": "news",
                "title": result["title"] or f"News mention: {competitor['name']}",
                "content": result["content"],
                "source_url": result["url"],
                "importance": 3 if result["score"] >= 0.7 else 2,
            }
            finding_id = db.add_finding(**finding)
            findings.append({**finding, "id": finding_id, "competitor_name": competitor["name"]})

        return findings

    def search_market_trends(self, topic_query: str, time_range: str = "month",
                             max_results: int = 5) -> list[dict]:
        """Search for market trends on a topic. Does not store findings."""
        return self.search(f"{topic_query} market trends", topic="general",
                           time_range=time_range, max_results=max_results)

    def check(self) -> list:
        """Search news for this source's query and competitor."""
        if not self.query or not self.competitor_id:
            return []
        return self.search_competitor_news({"id": self.competitor_id, "name": self.query})

    def get_source_name(self) -> str:
        return f"tavily:{self.query}"
