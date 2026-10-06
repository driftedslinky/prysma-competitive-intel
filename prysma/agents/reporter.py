"""Reporter Agent — Delivers digests and alerts to Telegram."""
import httpx
from datetime import datetime
from typing import Optional

from prysma.storage.database import db
from prysma.config import config


class ReporterAgent:
    """Manages report generation and Telegram delivery."""

    def __init__(self):
        self.client = httpx.Client(timeout=30.0)
        self.bot_token = config.telegram_bot_token

    def send_telegram(self, chat_id: str, text: str) -> bool:
        """Send a message via Telegram bot."""
        if not self.bot_token:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }

        try:
            response = self.client.post(url, json=payload)
            return response.status_code == 200
        except Exception:
            return False

    def send_daily_digest(self, chat_id: str) -> bool:
        """Generate and send daily digest."""
        from prysma.agents.analyst import AnalystAgent
        analyst = AnalystAgent()
        digest = analyst.generate_digest(hours=24)
        analyst.close()

        # Store in database
        digest_id = db.add_digest('daily', digest)

        # Send via Telegram
        success = self.send_telegram(chat_id, digest)
        if success:
            db.mark_digest_sent(digest_id)

        return success

    def send_trend_report(self, chat_id: str) -> bool:
        """Generate and send trend report."""
        from prysma.agents.trend_radar import TrendRadar
        radar = TrendRadar()
        report = radar.generate_trend_report()
        radar.close()

        # Store in database
        digest_id = db.add_digest('trend', report)

        # Send via Telegram
        success = self.send_telegram(chat_id, report)
        if success:
            db.mark_digest_sent(digest_id)

        return success

    def send_alert(self, chat_id: str, title: str, content: str) -> bool:
        """Send immediate alert."""
        alert = f"🚨 *ALERT*\n\n*{title}*\n\n{content}"
        return self.send_telegram(chat_id, alert)

    def send_weekly_deep_dive(self, chat_id: str) -> bool:
        """Generate and send weekly deep-dive report."""
        findings = db.get_recent_findings(hours=168)  # 7 days

        if not findings:
            return self.send_telegram(chat_id, "📊 Weekly Deep-Dive: No updates this week.")

        # Group by competitor
        by_competitor = {}
        for f in findings:
            name = f.get('competitor_name', 'Unknown')
            if name not in by_competitor:
                by_competitor[name] = []
            by_competitor[name].append(f)

        lines = [f"📊 *Weekly Deep-Dive*", f"_{datetime.now().strftime('%Y-%m-%d')}_", ""]

        for competitor, items in by_competitor.items():
            lines.append(f"🔍 *{competitor}* ({len(items)} updates)")
            for f in items[:3]:
                lines.append(f"  • {f['title']}")
            lines.append("")

        digest_id = db.add_digest('weekly', '\n'.join(lines))
        success = self.send_telegram(chat_id, '\n'.join(lines))
        if success:
            db.mark_digest_sent(digest_id)

        return success

    def send_competitive_report(self, chat_id: str) -> bool:
        """Generate and send competitive intelligence report."""
        from prysma.agents.competitive_intel import CompetitiveIntelAgent
        intel = CompetitiveIntelAgent()
        report = intel.generate_competitive_report()
        intel.close()

        # Store in database
        digest_id = db.add_digest('competitive', report)

        # Send via Telegram
        success = self.send_telegram(chat_id, report)
        if success:
            db.mark_digest_sent(digest_id)

        return success

    def send_competitive_alert(self, chat_id: str, alert_type: str, message: str) -> bool:
        """Send a competitive intelligence alert."""
        text = f"🚨 *Competitive Alert: {alert_type}*\n\n{message}"
        return self.send_telegram(chat_id, text)

    def close(self):
        self.client.close()
