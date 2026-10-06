"""PDF Report Generator — Creates professional competitor analysis reports."""
from pathlib import Path
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from prysma.storage.database import db
from prysma.insights import ActionableInsights
from prysma.dashboard import DashboardGenerator


class ReportGenerator:
    """Generates professional PDF reports for competitor analysis."""

    def __init__(self, output_dir: str = "data/cache"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.insights = ActionableInsights()
        self.dashboard = DashboardGenerator(output_dir)

    def generate_competitor_report(self, competitor_name: str) -> Optional[str]:
        """Generate full PDF report for a competitor. Returns file path."""
        findings = db.get_recent_findings(hours=168)
        comp_findings = [f for f in findings if f['competitor_name'].lower() == competitor_name.lower()]

        if not comp_findings:
            return None

        filepath = self.output_dir / f"report_{competitor_name.lower().replace(' ', '_')}.pdf"

        doc = SimpleDocTemplate(
            str(filepath),
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18
        )

        # Container for elements
        elements = []
        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a1a2e'),
            spaceAfter=30,
            alignment=TA_CENTER
        )

        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#16213e'),
            spaceAfter=12,
            spaceBefore=12
        )

        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['BodyText'],
            fontSize=11,
            leading=14,
            spaceAfter=8
        )

        # Title
        elements.append(Paragraph(f"Competitor Analysis Report", title_style))
        elements.append(Paragraph(f"{competitor_name}", title_style))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
        elements.append(Spacer(1, 20))

        # Executive Summary
        elements.append(Paragraph("Executive Summary", heading_style))
        avg_importance = sum(f['importance'] for f in comp_findings) / len(comp_findings)
        summary_text = f"""
        This report analyzes {len(comp_findings)} competitive signals detected over the past 7 days
        for <b>{competitor_name}</b>. The average importance score is {avg_importance:.1f}/5.0.
        """
        elements.append(Paragraph(summary_text, body_style))
        elements.append(Spacer(1, 12))

        # Key Findings
        elements.append(Paragraph("Key Findings", heading_style))

        # Group by category
        categories = {}
        for f in comp_findings:
            cat = self.insights.classify_finding(f)
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(f)

        for cat, findings_list in categories.items():
            template = self.insights.INSIGHT_TEMPLATES.get(cat, self.insights.INSIGHT_TEMPLATES['product_launch'])
            elements.append(Paragraph(f"{template['emoji']} {template['title']} ({len(findings_list)} items)", heading_style))

            for f in findings_list[:3]:
                elements.append(Paragraph(f"• <b>{f['title']}</b>", body_style))
                if f.get('content'):
                    content = f['content'][:200]
                    elements.append(Paragraph(f"  {content}", body_style))

            elements.append(Spacer(1, 8))

        # Strategic Recommendations
        elements.append(Paragraph("Strategic Recommendations", heading_style))

        recommendations = self._generate_recommendations(categories)
        for rec in recommendations:
            elements.append(Paragraph(f"→ {rec}", body_style))

        elements.append(Spacer(1, 12))

        # Charts
        elements.append(Paragraph("Visual Analysis", heading_style))

        # Add sentiment gauge
        chart_path = self.dashboard.generate_sentiment_gauge(competitor_name)
        if chart_path:
            elements.append(Image(chart_path, width=400, height=200))
            elements.append(Spacer(1, 12))

        # Build PDF
        doc.build(elements)

        return str(filepath)

    def generate_market_overview_report(self, query: str = "AI tools") -> Optional[str]:
        """Generate market overview PDF report. Returns file path."""
        findings = db.get_recent_findings(hours=168)

        if not findings:
            return None

        filepath = self.output_dir / f"market_overview_{query.lower().replace(' ', '_')}.pdf"

        doc = SimpleDocTemplate(
            str(filepath),
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18
        )

        elements = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a1a2e'),
            spaceAfter=30,
            alignment=TA_CENTER
        )

        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#16213e'),
            spaceAfter=12,
            spaceBefore=12
        )

        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['BodyText'],
            fontSize=11,
            leading=14,
            spaceAfter=8
        )

        # Title
        elements.append(Paragraph("Market Overview Report", title_style))
        elements.append(Paragraph(f"Query: {query}", title_style))
        elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
        elements.append(Spacer(1, 20))

        # Market Summary
        elements.append(Paragraph("Market Summary", heading_style))
        summary = f"""
        This report provides an overview of the <b>{query}</b> market based on
        {len(findings)} signals detected over the past week. The analysis covers
        competitor activities, emerging trends, and strategic opportunities.
        """
        elements.append(Paragraph(summary, body_style))
        elements.append(Spacer(1, 12))

        # Top Competitors
        competitors = db.get_active_competitors()
        if competitors:
            elements.append(Paragraph("Tracked Competitors", heading_style))
            for comp in competitors[:10]:
                comp_findings = [f for f in findings if f.get('competitor_id') == comp['id']]
                elements.append(Paragraph(f"• <b>{comp['name']}</b> — {len(comp_findings)} signals", body_style))

            elements.append(Spacer(1, 12))

        # Trend Analysis
        elements.append(Paragraph("Emerging Trends", heading_style))

        # Get trend signals
        trend_signals = db.get_trend_signals(days=7)
        if trend_signals:
            keyword_counts = {}
            for signal in trend_signals:
                kw = signal['keyword']
                keyword_counts[kw] = keyword_counts.get(kw, 0) + signal['strength']

            sorted_trends = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)[:10]

            for kw, strength in sorted_trends:
                elements.append(Paragraph(f"• {kw.title()} — strength: {strength}", body_style))

        elements.append(Spacer(1, 12))

        # Charts
        elements.append(Paragraph("Visual Analysis", heading_style))

        trend_chart = self.dashboard.generate_trend_chart()
        if trend_chart:
            elements.append(Image(trend_chart, width=450, height=270))
            elements.append(Spacer(1, 12))

        timeline_chart = self.dashboard.generate_findings_timeline()
        if timeline_chart:
            elements.append(Image(timeline_chart, width=450, height=225))

        # Build PDF
        doc.build(elements)

        return str(filepath)

    def _generate_recommendations(self, categories: dict) -> list[str]:
        """Generate strategic recommendations based on finding categories."""
        recommendations = []

        if 'pricing_change' in categories:
            recommendations.append("Review your pricing strategy — competitor price changes detected")
        if 'product_launch' in categories:
            recommendations.append("Accelerate your roadmap — competitors are shipping new features")
        if 'hiring' in categories:
            recommendations.append("Expect increased competition — competitors are growing their teams")
        if 'funding' in categories:
            recommendations.append("Prepare for aggressive moves — competitors have new funding")
        if 'negative_news' in categories:
            recommendations.append("Opportunity to capture dissatisfied customers")
        if 'partnership' in categories:
            recommendations.append("Evaluate partnership opportunities to maintain distribution parity")
        if 'content' in categories:
            recommendations.append("Invest in content marketing to compete for organic search traffic")

        if not recommendations:
            recommendations.append("Continue monitoring — no major competitive threats detected this week")

        return recommendations
