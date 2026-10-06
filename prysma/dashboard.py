"""Dashboard generator — Creates visual charts and graphs for Prysma."""
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

from prysma.storage.database import db


class DashboardGenerator:
    """Generates visual dashboard charts as PNG images."""

    def __init__(self, output_dir: str = "data/cache"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_trend_chart(self) -> Optional[str]:
        """Generate trend strength bar chart. Returns file path."""
        signals = db.get_trend_signals(days=30)
        if not signals:
            return None

        # Aggregate by keyword
        keyword_strength = {}
        for signal in signals:
            kw = signal['keyword'].lower()
            keyword_strength[kw] = keyword_strength.get(kw, 0) + signal['strength']

        # Sort and take top 10
        sorted_kw = sorted(keyword_strength.items(), key=lambda x: x[1], reverse=True)[:10]
        if not sorted_kw:
            return None

        keywords, strengths = zip(*sorted_kw)

        # Create chart
        fig, ax = plt.subplots(figsize=(10, 6))
        colors = plt.cm.viridis([s / max(strengths) for s in strengths])
        bars = ax.barh(keywords, strengths, color=colors)
        ax.set_xlabel('Signal Strength')
        ax.set_title('Trend Radar - Top Keywords (30 days)')
        ax.invert_yaxis()

        # Add value labels
        for bar, strength in zip(bars, strengths):
            ax.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height()/2,
                    str(strength), va='center', fontsize=10)

        plt.tight_layout()
        filepath = self.output_dir / "trend_chart.png"
        fig.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return str(filepath)

    def generate_findings_timeline(self, hours: int = 168) -> Optional[str]:
        """Generate findings timeline chart. Returns file path."""
        findings = db.get_recent_findings(hours=hours)
        if not findings:
            return None

        # Group by day and type
        daily_counts = {}
        for f in findings:
            day = f['created_at'][:10]  # YYYY-MM-DD
            ftype = f['finding_type']
            if day not in daily_counts:
                daily_counts[day] = {}
            daily_counts[day][ftype] = daily_counts[day].get(ftype, 0) + 1

        # Sort by date
        sorted_days = sorted(daily_counts.keys())
        types = sorted(set(t for d in daily_counts.values() for t in d.keys()))

        # Create stacked bar chart
        fig, ax = plt.subplots(figsize=(12, 6))
        x = range(len(sorted_days))
        width = 0.6

        bottom = [0] * len(sorted_days)
        colors = plt.cm.Set2.colors

        for i, ftype in enumerate(types):
            counts = [daily_counts[d].get(ftype, 0) for d in sorted_days]
            ax.bar(x, counts, width, label=ftype, bottom=bottom, color=colors[i % len(colors)])
            bottom = [b + c for b, c in zip(bottom, counts)]

        ax.set_xlabel('Date')
        ax.set_ylabel('Findings')
        ax.set_title(f'Findings Timeline (last {hours}h)')
        ax.set_xticks(x)
        ax.set_xticklabels(sorted_days, rotation=45, ha='right')
        ax.legend()

        plt.tight_layout()
        filepath = self.output_dir / "findings_timeline.png"
        fig.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return str(filepath)

    def generate_competitor_activity_chart(self) -> Optional[str]:
        """Generate competitor activity comparison. Returns file path."""
        competitors = db.get_active_competitors()
        if not competitors:
            return None

        # Count findings per competitor
        comp_counts = {}
        for comp in competitors:
            findings = db.get_recent_findings(hours=168)
            count = sum(1 for f in findings if f.get('competitor_id') == comp['id'])
            comp_counts[comp['name']] = count

        if not comp_counts:
            return None

        sorted_comp = sorted(comp_counts.items(), key=lambda x: x[1], reverse=True)[:8]
        names, counts = zip(*sorted_comp)

        fig, ax = plt.subplots(figsize=(10, 6))
        colors = plt.cm.Paired.colors
        bars = ax.bar(names, counts, color=colors[:len(names)])
        ax.set_ylabel('Findings (7 days)')
        ax.set_title('Competitor Activity')
        ax.set_xticklabels(names, rotation=45, ha='right')

        for bar, count in zip(bars, counts):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                    str(count), ha='center', fontsize=10)

        plt.tight_layout()
        filepath = self.output_dir / "competitor_activity.png"
        fig.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return str(filepath)

    def generate_sentiment_gauge(self, competitor_name: str) -> Optional[str]:
        """Generate sentiment gauge chart for a competitor. Returns file path."""
        # Simple gauge based on finding importance
        findings = db.get_recent_findings(hours=168)
        comp_findings = [f for f in findings if f.get('competitor_name', '').lower() == competitor_name.lower()]

        if not comp_findings:
            return None

        avg_importance = sum(f['importance'] for f in comp_findings) / len(comp_findings)

        # Create gauge
        fig, ax = plt.subplots(figsize=(8, 4))

        # Background bar
        ax.barh([0], [5], color='#e0e0e0', height=0.3)
        # Value bar
        color = '#4caf50' if avg_importance >= 3 else '#ff9800' if avg_importance >= 2 else '#f44336'
        ax.barh([0], [avg_importance], color=color, height=0.3)

        ax.set_xlim(0, 5)
        ax.set_yticks([])
        ax.set_xlabel('Average Importance (1-5)')
        ax.set_title(f'Sentiment: {competitor_name}')

        # Add value label
        ax.text(avg_importance + 0.1, 0, f'{avg_importance:.1f}', va='center', fontsize=14, fontweight='bold')

        plt.tight_layout()
        filepath = self.output_dir / f"sentiment_{competitor_name.lower().replace(' ', '_')}.png"
        fig.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return str(filepath)

    def generate_full_dashboard(self) -> list[str]:
        """Generate all dashboard charts. Returns list of file paths."""
        paths = []

        chart = self.generate_trend_chart()
        if chart:
            paths.append(chart)

        chart = self.generate_findings_timeline()
        if chart:
            paths.append(chart)

        chart = self.generate_competitor_activity_chart()
        if chart:
            paths.append(chart)

        return paths
