"""Alert Engine — turns material competitor changes into one-time Telegram alerts.

Quiet by default: only material changes become alerts, and the unique
(source_table, source_id) index on `alerts` stops a change from alerting twice.
"""
import os
import re
from collections import Counter
from typing import Optional

from prysma.agents.competitive_intel import CompetitiveIntelAgent
from prysma.agents.reporter import ReporterAgent
from prysma.config import config
from prysma.storage.database import db


SEVERITY_EMOJI = {'high': '🚨', 'medium': '⚠️', 'low': 'ℹ️'}
COMPLAINT_KEYWORDS = CompetitiveIntelAgent.OPPORTUNITY_KEYWORDS
CHANGE_LABELS = {'ratings_count': 'ratings count', 'release_date': 'release date'}
STORED_VALUE_LIMIT = 500  # Database.upsert_app_listing stores old/new values cut to this length


def _clean(value) -> str:
    """Normalise a stored value. None, empty, and the string 'None' all become ''."""
    text = '' if value is None else str(value).strip()
    return '' if text == 'None' else text


def _short(text: str, limit: int = 80) -> str:
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + '...'


def _number(text: str) -> Optional[float]:
    try:
        return float(text.replace(',', ''))
    except ValueError:
        return None


def _escape_markdown(text: str) -> str:
    """Escape Telegram legacy-Markdown characters so scraped text cannot break the send."""
    return re.sub(r'([_*`\[])', r'\\\1', text)


def _changed_part(old: str, new: str) -> tuple[str, str]:
    """Return the differing middle of two strings, without the shared prefix and suffix."""
    prefix = len(os.path.commonprefix([old, new]))
    suffix = len(os.path.commonprefix([old[prefix:][::-1], new[prefix:][::-1]]))
    return old[prefix:len(old) - suffix], new[prefix:len(new) - suffix]


def format_alert(alert: dict) -> str:
    """Telegram text for one alert."""
    emoji = SEVERITY_EMOJI.get(alert.get('severity'), 'ℹ️')
    title = _escape_markdown(alert.get('title') or '')
    message = _escape_markdown(alert.get('message') or '')
    return f"🚨 {emoji} {title}\n{message}"


class AlertEngine:
    """Applies the materiality rules and delivers alerts."""

    def build_alerts(self, hours: int = 24) -> list[dict]:
        """Turn recent material changes into alerts. Returns the new alerts."""
        candidates = []

        for change in db.get_aso_changes(hours=hours):
            result = self._aso_alert(change, hours)
            if result:
                severity, message = result
                name = change.get('competitor_name') or 'Unknown competitor'
                label = CHANGE_LABELS.get(change['change_type'], change['change_type'])
                candidates.append({
                    'competitor_id': change.get('competitor_id'),
                    'alert_type': change['change_type'],
                    'severity': severity,
                    'title': f"{name}: {label} changed",
                    'message': message,
                    'source_table': 'aso_changes',
                    'source_id': change['id'],
                })

        for finding in db.get_recent_findings(hours=hours):
            alert = self._finding_alert(finding)
            if alert:
                candidates.append(alert)

        new_alerts = []
        for alert in candidates:
            alert_id = db.add_alert(**alert)
            if alert_id:  # None means this source row already has an alert
                new_alerts.append({'id': alert_id, **alert})
        return new_alerts

    def send_alerts(self) -> int:
        """Send unsent alerts to Telegram. Returns the number sent."""
        if not config.telegram_bot_token:
            return 0
        chat_ids = [uid.strip() for uid in config.telegram_allowed_users.split(',') if uid.strip()]
        alerts = db.get_unsent_alerts()
        if not alerts or not chat_ids:
            return 0  # Silence is the normal state

        reporter = ReporterAgent()
        sent = 0
        try:
            for alert in alerts:
                text = format_alert(alert)
                results = [reporter.send_telegram(chat_id, text) for chat_id in chat_ids]
                # Mark sent once anyone received it, so a retry never re-sends to them
                if any(results):
                    db.mark_alert_sent(alert['id'])
                    sent += 1
        finally:
            reporter.close()
        return sent

    # ── Rules ───────────────────────────────────────────────────────

    def _aso_alert(self, change: dict, hours: int) -> Optional[tuple[str, str]]:
        """Return (severity, message) for a material ASO change, else None."""
        change_type = change.get('change_type')
        old, new = _clean(change.get('old_value')), _clean(change.get('new_value'))
        if old == new or not change_type:
            return None
        name = change.get('competitor_name') or 'Unknown competitor'
        label = CHANGE_LABELS.get(change_type, change_type)

        if change_type == 'rating':
            old_num, new_num = _number(old), _number(new)
            if old_num is None or new_num is None:
                return None
            delta = round(new_num - old_num, 4)  # round off float noise such as 0.0999999
            if abs(delta) < 0.1:
                return None
            severity = 'high' if abs(delta) >= 0.3 else 'medium'
            direction = 'dropped' if delta < 0 else 'rose'
            message = f"{name}: rating {direction} {old_num:.1f} -> {new_num:.1f}"
            count = self._ratings_count(change)
            if count:
                message += f" across {count:,} ratings"
            return severity, message + self._complaint_clause(change, hours) + '.'

        if change_type == 'ratings_count':
            old_num, new_num = _number(old), _number(new)
            if not old_num or new_num is None:
                return None
            increase = int(new_num - old_num)
            if increase < 500 and increase / old_num < 0.25:
                return None
            message = (f"{name}: ratings count rose {int(old_num):,} -> {int(new_num):,} "
                       f"(+{increase / old_num:.0%})")
            return 'medium', message + self._complaint_clause(change, hours) + '.'

        if change_type == 'description':
            # Digit-only differences are counters scraped into the text, not copy changes.
            # Values are stored cut to 500 chars, so a longer number shifts the cut point:
            # compare only the shared length when a value was cut.
            old_shape, new_shape = re.sub(r'\d+', '#', old), re.sub(r'\d+', '#', new)
            if max(len(old), len(new)) >= STORED_VALUE_LIMIT:
                shared = min(len(old_shape), len(new_shape))
                old_shape, new_shape = old_shape[:shared], new_shape[:shared]
            if old_shape == new_shape:
                return None
            old_part, new_part = _changed_part(old, new)
            if not old_part:
                return 'low', f'{name}: description adds "{_short(new_part)}".'
            if not new_part:
                return 'low', f'{name}: description removes "{_short(old_part)}".'
            return 'low', f'{name}: description changed "{_short(old_part)}" to "{_short(new_part)}".'

        severity = {'price': 'high', 'title': 'high',
                    'version': 'medium', 'release_date': 'medium'}.get(change_type, 'low')
        if not old:
            return severity, f'{name}: {label} set to "{_short(new)}".'
        if not new:
            return severity, f'{name}: {label} removed (was "{_short(old)}").'
        if change_type in ('price', 'version', 'release_date'):
            return severity, f"{name}: {label} changed from {_short(old)} to {_short(new)}."
        return severity, f'{name}: {label} changed from "{_short(old)}" to "{_short(new)}".'

    def _finding_alert(self, finding: dict) -> Optional[dict]:
        """Alert for an importance 4-5 finding, else None."""
        importance = finding.get('importance') or 0
        title = _clean(finding.get('title'))
        # ASO changes also write a finding; aso_changes already alerts for them
        if importance < 4 or not title or title.startswith('ASO change:'):
            return None
        detail = _short(_clean(finding.get('content')), 200)
        prefix = f"{finding['competitor_name']}: " if finding.get('competitor_name') else ''
        if finding.get('finding_type') == 'opportunity' and detail:
            message = f'{prefix}new negative review says "{detail}"'
        else:
            message = f"{prefix}{title}" + (f" ({detail})" if detail else '')
        return {
            'competitor_id': finding.get('competitor_id'),
            'alert_type': 'finding',
            'severity': 'high' if importance == 5 else 'medium',
            'title': title,
            'message': message,
            'source_table': 'findings',
            'source_id': finding['id'],
        }

    def _ratings_count(self, change: dict) -> Optional[int]:
        if not change.get('competitor_id'):
            return None
        for listing in db.get_app_listings(change['competitor_id']):
            if listing.get('platform') == change.get('platform'):
                return listing.get('current_ratings_count')
        return None

    def _complaint_clause(self, change: dict, hours: int) -> str:
        """Clause naming the most common complaint keyword in recent negative reviews."""
        if not change.get('competitor_id'):
            return ''
        reviews = db.get_recent_reviews(competitor_id=change['competitor_id'], rating_max=2, hours=hours)
        counts = Counter()
        for review in reviews:
            text = f"{review.get('title') or ''} {review.get('content') or ''}".lower()
            counts.update(kw for kw in COMPLAINT_KEYWORDS if kw in text)
        if not counts:
            return ''
        keyword, n = counts.most_common(1)[0]
        verb = 'reviews mention' if n > 1 else 'review mentions'
        return f'; {n} recent negative {verb} "{keyword}"'
