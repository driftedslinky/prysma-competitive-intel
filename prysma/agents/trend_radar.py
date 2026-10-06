"""Trend Radar — Detects emerging trends before they peak.

Scans multiple signal sources (GitHub, Reddit, news, search) to identify
trending topics, technologies, and market shifts early.
"""
import httpx
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from prysma.storage.database import db
from prysma.security import sanitize_scraped_content, contains_suspicious_content
from prysma.config import config


class TrendRadar:
    """Detects and tracks emerging trends across multiple data sources."""

    # Keywords that signal trending topics
    TREND_KEYWORDS = {
        'tech': [
            'ai', 'llm', 'agent', 'rag', 'mcp', 'multimodal', 'open source',
            'launch', 'announce', 'release', 'breakthrough', 'novel', 'new',
            'startup', 'funding', 'series', 'acquire', 'merge', 'ipo',
            'cryptocurrency', 'blockchain', 'web3', 'defi',
            'rust', 'typescript', 'python', 'golang',
            'saas', 'paas', 'devtool', 'developer', 'no-code', 'low-code',
            'autonomous', 'copilot', 'assistant', 'chatbot'
        ],
        'fitness': [
            'fitness', 'workout', 'exercise', 'gym', 'health', 'wellness',
            'nutrition', 'diet', 'weight loss', 'muscle', 'cardio', 'yoga',
            'pilates', 'crossfit', 'running', 'cycling', 'strength',
            'bodybuilding', 'personal training', 'fitness app', 'wearable',
            'smartwatch', 'fitness tracker', 'peloton', 'home gym',
            'meal prep', 'protein', 'supplement', 'recovery', 'sleep',
            'mental health', 'meditation', 'mindfulness', 'biohacking'
        ],
        'finance': [
            'finance', 'fintech', 'banking', 'investing', 'trading',
            'crypto', 'bitcoin', 'ethereum', 'defi', 'nft', 'stock',
            'market', 'ipo', 'funding', 'valuation', 'revenue', 'profit',
            'interest rate', 'inflation', 'recession', 'gdp', 'economy',
            'payment', 'lending', 'insurance', 'wealth', 'retirement',
            'budget', 'savings', 'credit', 'mortgage', 'tax', 'audit',
            'blockchain', 'token', 'wallet', 'exchange', 'regulation'
        ],
        'general': [
            'trending', 'viral', 'breaking', 'announcement', 'launch',
            'new product', 'startup', 'innovation', 'disruption'
        ]
    }

    # Subreddits per vertical
    SUBREDDITS = {
        'tech': ['startups', 'SaaS', 'MachineLearning', 'artificial', 'localllama'],
        'fitness': ['fitness', 'running', 'xxfitness', 'bodybuilding', 'nutrition', 'peloton'],
        'finance': ['personalfinance', 'investing', 'financialindependence', 'cryptocurrency', 'fintech'],
        'general': ['startups', 'business', 'technology']
    }

    def __init__(self):
        self.client = httpx.Client(
            timeout=30.0,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )

    def scan_all_sources(self) -> dict:
        """Run a full trend scan across all sources."""
        results = {
            'signals_detected': 0,
            'trends_identified': 0,
            'emerging_trends': 0,
            'details': []
        }

        # Scan each source
        self.scan_github_trends(results)
        self.scan_reddit_discussions(results)
        self.scan_news_trends(results)

        # Analyze accumulated signals
        trends = self.analyze_trends()
        results['trends_identified'] = len(trends)
        results['emerging_trends'] = sum(1 for t in trends if t.get('is_emerging'))

        return results

    def scan_github_trends(self, results: dict):
        """Scan GitHub for trending repositories and topics."""
        try:
            url = "https://api.github.com/search/repositories"
            params = {
                'q': 'created:>2026-08-01',  # Recent repos
                'sort': 'stars',
                'order': 'desc',
                'per_page': 20
            }

            if config.github_token:
                params['access_token'] = config.github_token

            response = self.client.get(url, params=params)
            data = response.json()

            for item in data.get('items', []):
                name = item.get('full_name', '')
                description = item.get('description', '') or ''
                stars = item.get('stargazers_count', 0)
                language = item.get('language', '') or ''
                topics = item.get('topics', [])

                # Build signal
                signal_text = f"{name} {description} {' '.join(topics)}"
                sanitized = sanitize_scraped_content(signal_text)

                # Detect keywords
                keywords = self._extract_keywords(sanitized)
                for keyword in keywords:
                    strength = min(stars // 100 + 1, 5)  # Scale by popularity
                    db.add_trend_signal(
                        keyword=keyword,
                        signal_type='github',
                        strength=strength,
                        source_url=item.get('html_url')
                    )
                    results['signals_detected'] += 1

        except Exception as e:
            results['details'].append({'error': str(e), 'source': 'github'})

    def scan_reddit_discussions(self, results: dict):
        """Scan Reddit for emerging discussions across all verticals."""
        for vertical, subreddits in self.SUBREDDITS.items():
            for subreddit in subreddits:
                try:
                    url = f"https://www.reddit.com/r/{subreddit}/hot.json"
                    params = {'limit': 15}

                    response = self.client.get(url, params=params)
                    data = response.json()

                    for post in data.get('data', {}).get('children', []):
                        post_data = post.get('data', {})
                        title = post_data.get('title', '')
                        score = post_data.get('score', 0)
                        selftext = post_data.get('selftext', '')[:500]

                        content = f"{title} {selftext}"
                        sanitized = sanitize_scraped_content(content)

                        keywords = self._extract_keywords(sanitized, vertical)
                        for keyword in keywords:
                            strength = min(score // 50 + 1, 5)
                            db.add_trend_signal(
                                keyword=f"{vertical}:{keyword}",
                                signal_type='reddit',
                                strength=strength,
                                source_url=f"https://reddit.com{post_data.get('permalink', '')}"
                            )
                            results['signals_detected'] += 1

                except Exception as e:
                    results['details'].append({'error': str(e), 'source': f'redit/r/{subreddit}'})

    def scan_news_trends(self, results: dict):
        """Scan news for trending topics across all verticals."""
        if not config.newsapi_key:
            return

        try:
            url = "https://newsapi.org/v2/top-headlines"
            
            # Search for each vertical
            for vertical in ['technology', 'health', 'business']:
                params = {
                    'category': vertical,
                    'language': 'en',
                    'pageSize': 10,
                    'apiKey': config.newsapi_key
                }

                response = self.client.get(url, params=params)
                data = response.json()

                for article in data.get('articles', []):
                    title = article.get('title', '')
                    description = article.get('description', '') or ''

                    content = f"{title} {description}"
                    sanitized = sanitize_scraped_content(content)

                    # Map category to vertical
                    vertical_map = {
                        'technology': 'tech',
                        'health': 'fitness',
                        'business': 'finance'
                    }
                    v = vertical_map.get(vertical, 'general')

                    keywords = self._extract_keywords(sanitized, v)
                    for keyword in keywords:
                        db.add_trend_signal(
                            keyword=f"{v}:{keyword}",
                            signal_type='news',
                            strength=2,
                            source_url=article.get('url')
                        )
                        results['signals_detected'] += 1

        except Exception as e:
            results['details'].append({'error': str(e), 'source': 'news_trends'})

    def analyze_trends(self, days: int = None) -> list[dict]:
        """Analyze accumulated trend signals and identify emerging trends."""
        signals = db.get_trend_signals(days=days)

        if not signals:
            return []

        # Group by keyword
        keyword_data: dict[str, dict] = {}
        for signal in signals:
            keyword = signal['keyword'].lower()
            if keyword not in keyword_data:
                keyword_data[keyword] = {
                    'keyword': keyword,
                    'total_strength': 0,
                    'signal_count': 0,
                    'sources': set(),
                    'recent_signals': []
                }

            keyword_data[keyword]['total_strength'] += signal['strength']
            keyword_data[keyword]['signal_count'] += 1
            keyword_data[keyword]['sources'].add(signal['signal_type'])
            keyword_data[keyword]['recent_signals'].append(signal)

        # Identify trends (keywords with sufficient signal)
        trends = []
        threshold = config.trend_signal_threshold

        for keyword, data in keyword_data.items():
            if data['total_strength'] >= threshold:
                is_emerging = (
                    data['total_strength'] >= threshold * 2 and
                    len(data['sources']) >= 2  # Multi-source trends are stronger
                )

                trend = {
                    'keyword': keyword,
                    'strength': min(data['total_strength'], 10),
                    'signal_count': data['signal_count'],
                    'sources': list(data['sources']),
                    'is_emerging': is_emerging,
                    'signals': ', '.join([s['signal_type'] for s in data['recent_signals'][:5]])
                }

                # Store report
                db.add_trend_report(
                    title=f"Trending: {keyword}",
                    description=f"Detected {data['signal_count']} signals across {len(data['sources'])} sources",
                    signals=trend['signals'],
                    strength=trend['strength'],
                    is_emerging=is_emerging
                )

                trends.append(trend)

        # Sort by strength
        trends.sort(key=lambda x: x['strength'], reverse=True)

        return trends

    def get_emerging_trends(self) -> list[dict]:
        """Get only emerging (strong) trends."""
        return db.get_trend_reports(emerging_only=True)

    def generate_trend_report(self, vertical: str = None) -> str:
        """Generate a formatted trend report for Telegram delivery."""
        trends = self.analyze_trends()

        if not trends:
            return "Trend Radar: No significant trends detected yet. Keep watching!"

        # Filter by vertical if specified
        if vertical:
            trends = [t for t in trends if t['keyword'].startswith(f"{vertical}:")]
            # Remove vertical prefix from keywords
            for t in trends:
                t['keyword'] = t['keyword'].replace(f"{vertical}:", "")

        if not trends:
            return f"Trend Radar: No trends found for '{vertical}'. Try: tech, fitness, finance"

        emerging = [t for t in trends if t['is_emerging']]
        strong = [t for t in trends if not t['is_emerging'] and t['strength'] >= 4]
        moderate = [t for t in trends if not t['is_emerging'] and t['strength'] < 4]

        lines = [f"Trend Radar Report", ""]

        if vertical:
            lines.append(f"Vertical: {vertical.title()}")
            lines.append("")

        if emerging:
            lines.append("Emerging Trends:")
            for t in emerging[:5]:
                sources = ', '.join(t['sources'])
                lines.append(f"  - {t['keyword'].upper()} (strength: {t['strength']}/10) - {sources}")
            lines.append("")

        if strong:
            lines.append("Strong Signals:")
            for t in strong[:5]:
                sources = ', '.join(t['sources'])
                lines.append(f"  - {t['keyword'].title()} (strength: {t['strength']}/10) - {sources}")
            lines.append("")

        if moderate:
            lines.append("Watch List:")
            for t in moderate[:5]:
                lines.append(f"  - {t['keyword'].title()} (strength: {t['strength']}/10)")
            lines.append("")

        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        return '\n'.join(lines)

    def _extract_keywords(self, text: str, vertical: str = None) -> list[str]:
        """Extract trend keywords from text. Optionally filter by vertical."""
        text_lower = text.lower()
        found = []

        if vertical and vertical in self.TREND_KEYWORDS:
            keywords = self.TREND_KEYWORDS[vertical]
        else:
            # Search all verticals
            keywords = []
            for v_keywords in self.TREND_KEYWORDS.values():
                keywords.extend(v_keywords)

        for keyword in keywords:
            if keyword in text_lower:
                found.append(keyword)

        return found

    def close(self):
        self.client.close()
