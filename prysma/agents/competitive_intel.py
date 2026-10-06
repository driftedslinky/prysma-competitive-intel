"""Competitive Intelligence Agent — Tracks ASO, reviews, pricing, and updates."""

import hashlib
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from prysma.storage.database import db
from prysma.security import sanitize_scraped_content
from prysma.config import config


class CompetitiveIntelAgent:
    """Tracks competitor app store listings, ASO changes, reviews, and pricing."""

    # Store IDs (package names / App Store IDs) come from the competitors table.
    # New-entrant search keywords come from config (NEW_ENTRANT_KEYWORDS).

    def __init__(self):
        self.client = httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )
        self.results = {
            "listings_checked": 0,
            "changes_detected": 0,
            "new_reviews": 0,
            "new_updates": 0,
            "new_entrants": 0,
            "errors": 0,
            "details": [],
        }

    def run_full_scan(self) -> dict:
        """Run complete competitive intelligence scan."""
        self.results = {
            "listings_checked": 0,
            "changes_detected": 0,
            "new_reviews": 0,
            "new_updates": 0,
            "new_entrants": 0,
            "errors": 0,
            "details": [],
        }

        # Scan app store listings
        self._scan_app_listings()

        # Scan for negative reviews (opportunity detection)
        self._scan_negative_reviews()

        # Scan for new entrants
        self._scan_new_entrants()

        return self.results

    # ── App Store Listing Scanning ──────────────────────────────────

    def _scan_app_listings(self):
        """Check competitor app stores for ASO changes."""
        competitors = db.get_active_competitors()
        for competitor in competitors:
            store_ids = db.get_competitor_store_ids(competitor)

            # Android
            if store_ids.get("android"):
                try:
                    listing = self._scrape_google_play(
                        store_ids["android"], competitor
                    )
                    if listing:
                        self._process_listing(competitor, "android", listing)
                except Exception as e:
                    self.results["errors"] += 1
                    self.results["details"].append(
                        {"error": str(e), "competitor": competitor["name"], "platform": "android"}
                    )

            # iOS
            if store_ids.get("ios"):
                try:
                    listing = self._scrape_app_store(store_ids["ios"], competitor)
                    if listing:
                        self._process_listing(competitor, "ios", listing)
                except Exception as e:
                    self.results["errors"] += 1
                    self.results["details"].append(
                        {"error": str(e), "competitor": competitor["name"], "platform": "ios"}
                    )

    def _scrape_google_play(
        self, package_name: str, competitor: dict
    ) -> Optional[dict]:
        """Scrape a Google Play Store listing using regex on embedded JSON."""
        url = f"https://play.google.com/store/apps/details?id={package_name}&hl=en"
        resp = self.client.get(url)
        resp.raise_for_status()

        text = resp.text
        
        # Extract data from embedded JSON using regex
        # Google Play stores data in JSON within script tags
        
        # App name - look for the app title pattern
        app_name = competitor["name"]
        name_match = re.search(r'"name":"([^"]+)"', text)
        if name_match:
            app_name = name_match.group(1)
        
        # Also try h1
        soup = BeautifulSoup(text, "lxml")
        h1 = soup.find("h1")
        if h1:
            app_name = h1.get_text(strip=True)

        # Rating
        rating = None
        rating_match = re.search(r'"ratingValue":(\d+\.\d+)', text)
        if not rating_match:
            rating_match = re.search(r'(\d+\.\d+)\s*star', text)
        if rating_match:
            try:
                rating = float(rating_match.group(1))
            except (ValueError, TypeError):
                pass

        # Ratings count
        ratings_count = None
        count_match = re.search(r'"ratingCount":(\d+)', text)
        if not count_match:
            count_match = re.search(r'([\d,.]+)\s*reviews', text)
        if count_match:
            ratings_count = self._parse_count_string(count_match.group(1))

        # Description
        description = None
        desc_match = re.search(r'"description":"(.{100,2000})"', text)
        if desc_match:
            description = desc_match.group(1).replace('\\n', '\n').replace('\\"', '"')

        # Last updated
        updated = None
        updated_match = re.search(r'"datePublished":"([^"]+)"', text)
        if updated_match:
            updated = updated_match.group(1)

        # Price
        price = "Free"
        price_match = re.search(r'"price":"?(\d+\.?\d*)"?', text)
        if price_match and price_match.group(1) != "0":
            price = f"${price_match.group(1)}"

        # Developer
        developer = None
        dev_match = re.search(r'"author":\{[^}]*"name":"([^"]+)"', text)
        if dev_match:
            developer = dev_match.group(1)

        return {
            "app_name": app_name,
            "developer": developer,
            "rating": rating,
            "ratings_count": ratings_count,
            "description": description,
            "last_updated": updated,
            "price": price,
        }

    def _scrape_app_store(
        self, app_id: str, competitor: dict
    ) -> Optional[dict]:
        """Scrape an Apple App Store listing via iTunes lookup API."""
        # The lookup API wants the numeric ID; store IDs are kept as "id123..."
        numeric_id = app_id[2:] if app_id.lower().startswith("id") else app_id
        url = f"https://itunes.apple.com/lookup?id={numeric_id}&country=gb"
        resp = self.client.get(url)
        resp.raise_for_status()

        data = resp.json()
        results_list = data.get("results", [])
        if not results_list:
            return None

        app = results_list[0]

        return {
            "app_name": app.get("trackName", competitor["name"]),
            "developer": app.get("sellerName"),
            "rating": app.get("averageUserRating"),
            "ratings_count": app.get("userRatingCount"),
            "description": app.get("description", "")[:2000],
            "last_updated": app.get("currentVersionReleaseDate", "")[:10],
            "price": app.get("formattedPrice", "Free"),
            "version": app.get("version"),
            "subtitle": app.get("subtitle", ""),
        }

    def _process_listing(
        self, competitor: dict, platform: str, listing: dict
    ):
        """Process a listing — check for changes and update database."""
        self.results["listings_checked"] += 1

        # Get store ID
        store_id = db.get_competitor_store_ids(competitor).get(platform, "")

        # Upsert listing
        result = db.upsert_app_listing(
            competitor_id=competitor["id"],
            platform=platform,
            store_id=store_id,
            app_name=listing.get("app_name", competitor["name"]),
            developer=listing.get("developer"),
            title=listing.get("app_name"),
            subtitle=listing.get("subtitle"),
            description=listing.get("description"),
            price=listing.get("price"),
            rating=listing.get("rating"),
            ratings_count=listing.get("ratings_count"),
            last_updated=listing.get("last_updated"),
        )

        if result["changed"]:
            self.results["changes_detected"] += len(result["changes"])
            self.results["details"].append({
                "competitor": competitor["name"],
                "platform": platform,
                "changes": result["changes"],
            })

            # Create finding for significant changes
            for change_type, (old_val, new_val) in result["changes"].items():
                db.add_finding(
                    competitor_id=competitor["id"],
                    finding_type="change",
                    title=f"ASO change: {change_type} ({competitor['name']})",
                    content=f"Changed from '{old_val}' to '{new_val}'",
                    importance=4 if change_type in ("title", "price") else 3,
                )

    # ── Negative Review Monitoring ──────────────────────────────────

    def _scan_negative_reviews(self):
        """Scan for new negative reviews across competitors."""
        competitors = db.get_active_competitors()
        for competitor in competitors:
            store_ids = db.get_competitor_store_ids(competitor)
            if store_ids.get("android"):
                try:
                    self._scan_play_reviews(competitor, store_ids["android"])
                except Exception as e:
                    self.results["errors"] += 1

    def _scan_play_reviews(self, competitor: dict, package_name: str):
        """Scan Google Play reviews for a competitor."""
        url = f"https://play.google.com/store/apps/details?id={package_name}&hl=en&showAllReviews=true"
        resp = self.client.get(url)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        # Look for review sections
        review_blocks = soup.find_all("div", class_="UD7Dzf")
        for block in review_blocks[:20]:  # Limit to first 20
            # Rating
            rating_tag = block.find_previous("div", class_="pf5lIe")
            rating = 5
            if rating_tag:
                aria = rating_tag.get("aria-label", "")
                match = re.search(r"Rated (\d)", aria)
                if match:
                    rating = int(match.group(1))

            # Only track negative reviews (1-2 stars)
            if rating > 2:
                continue

            content_tag = block.find("span", jsname="fbQN7e")
            if not content_tag:
                content_tag = block.find("span", class_="review-body")

            content = content_tag.get_text(strip=True) if content_tag else ""
            if not content or len(content) < 20:
                continue

            # Check for common opportunity keywords
            opportunity_keywords = [
                "screen off",
                "stops",
                "background",
                "ads",
                "subscription",
                "expensive",
                "too many",
                "doesn't work",
                "crash",
                "bug",
                "slow",
                "ugly",
                "confusing",
                "complicated",
            ]

            content_lower = content.lower()
            is_opportunity = any(kw in content_lower for kw in opportunity_keywords)

            # Add to database
            db.add_review(
                competitor_id=competitor["id"],
                platform="android",
                rating=rating,
                title="",
                content=content[:500],
                author="User",
                review_date=datetime.now().strftime("%Y-%m-%d"),
            )

            self.results["new_reviews"] += 1

            # Create finding for opportunity keywords
            if is_opportunity:
                db.add_finding(
                    competitor_id=competitor["id"],
                    finding_type="opportunity",
                    title=f"Negative review opportunity ({competitor['name']})",
                    content=content[:300],
                    importance=5,
                )

    # ── New Entrant Detection ───────────────────────────────────────

    def _scan_new_entrants(self):
        """Search app stores for new apps matching the configured keywords."""
        for keyword in config.new_entrant_keywords:
            try:
                self._search_new_apps(keyword, "android")
            except Exception as e:
                self.results["errors"] += 1

    def _search_new_apps(self, keyword: str, platform: str):
        """Search for new apps matching keyword on Google Play."""
        if platform != "android":
            return

        url = f"https://play.google.com/store/search?q={quote_plus(keyword)}&c=apps"
        resp = self.client.get(url)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        app_cards = soup.find_all("div", class_="ImZGtf")
        if not app_cards:
            app_cards = soup.find_all("div", class_="VfPpkd-WsjYwc")

        for card in app_cards[:10]:
            title_tag = card.find("div", class_="WsMG1c")
            if not title_tag:
                continue

            app_name = title_tag.get_text(strip=True)

            # Skip if it's a known competitor
            known_names = [c["name"] for c in db.get_active_competitors()]
            if app_name in known_names:
                continue

            # Check if already tracked
            existing = db.get_new_entrants(hours=720)  # 30 days
            already_tracked = any(e["app_name"] == app_name for e in existing)
            if already_tracked:
                continue

            dev_tag = card.find("div", class_="KoLSrc")
            developer = dev_tag.get_text(strip=True) if dev_tag else None

            link_tag = card.find("a", href=True)
            store_url = (
                f"https://play.google.com{link_tag['href']}" if link_tag else None
            )

            db.add_new_entrant(
                app_name=app_name,
                platform="android",
                developer=developer,
                store_url=store_url,
                category=keyword,
            )

            self.results["new_entrants"] += 1
            self.results["details"].append({
                "new_entrant": app_name,
                "keyword": keyword,
            })

    # ── Report Generation ───────────────────────────────────────────

    def generate_competitive_report(self, hours: int = 24) -> str:
        """Generate a competitive intelligence report for Telegram."""
        lines = [f"📊 *Prysma Competitive Report*", ""]

        # ASO Changes
        aso_changes = db.get_aso_changes(hours=hours)
        if aso_changes:
            lines.append(f"🏷 *ASO Changes ({len(aso_changes)} detected):*")
            for change in aso_changes[:5]:
                ct = change["change_type"]
                old = str(change.get("old_value", ""))[:40]
                new = str(change.get("new_value", ""))[:40]
                lines.append(
                    f"  • {change['competitor_name']}: {ct} '{old}' → '{new}'"
                )
            lines.append("")

        # New Negative Reviews (Opportunities)
        negative_reviews = db.get_recent_reviews(rating_max=2, hours=hours)
        if negative_reviews:
            lines.append(f"💡 *Review Opportunities ({len(negative_reviews)} negative):*")
            for review in negative_reviews[:3]:
                content = review.get("content", "")[:100]
                lines.append(f"  • {review['competitor_name']}: \"{content}\"")
            lines.append("")

        # New Entrants
        new_entrants = db.get_new_entrants(hours=hours)
        if new_entrants:
            lines.append(f"🆕 *New Entrants ({len(new_entrants)}):*")
            for entrant in new_entrants[:5]:
                lines.append(f"  • {entrant['app_name']} ({entrant['platform']})")
            lines.append("")

        # Recent Updates
        recent_updates = db.get_recent_updates(hours=hours * 7)
        if recent_updates:
            lines.append(f"🔄 *Recent Updates ({len(recent_updates)}):*")
            for update in recent_updates[:5]:
                lines.append(
                    f"  • {update['competitor_name']} v{update['version']}"
                )
            lines.append("")

        if len(lines) <= 3:
            lines.append(
                "No significant competitive changes in the last "
                f"{hours}h. All quiet on the competitive front."
            )
        else:
            lines.append(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")

        return "\n".join(lines)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_count_string(text: str) -> Optional[int]:
        """Parse rating count from string like '269,842' or '269K'."""
        text = text.strip().replace(",", "").replace(" ", "")
        if text.endswith("K"):
            try:
                return int(float(text[:-1]) * 1000)
            except ValueError:
                return None
        if text.endswith("M"):
            try:
                return int(float(text[:-1]) * 1_000_000)
            except ValueError:
                return None
        try:
            return int(text)
        except ValueError:
            return None

    def close(self):
        self.client.close()
