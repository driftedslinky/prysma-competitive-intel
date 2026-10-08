"""Main entry point for Prysma."""
import asyncio
import signal
import sys
from datetime import datetime

from prysma.config import config
from prysma.storage.database import db
from prysma.agents.scout import ScoutAgent
from prysma.agents.trend_radar import TrendRadar
from prysma.agents.reporter import ReporterAgent
from prysma.agents.competitive_intel import CompetitiveIntelAgent
from prysma.dashboard import DashboardGenerator
from prysma.insights import ActionableInsights
from prysma.reports import ReportGenerator
from prysma.telegram import bot as bot_module


def run_scan_cycle():
    """Run a single scan cycle (for cron scheduling)."""
    print(f"[{datetime.now()}] Starting scan cycle...")

    # Scout competitors
    scout = ScoutAgent()
    results = scout.scan_all()
    scout.close()
    print(f"  Scout: {results['new_findings']} findings, {results['errors']} errors")

    # Trend Radar
    radar = TrendRadar()
    trend_results = radar.scan_all_sources()
    radar.close()
    print(f"  Trend Radar: {trend_results['signals_detected']} signals, {trend_results['emerging_trends']} emerging")

    # Competitive Intelligence
    intel = CompetitiveIntelAgent()
    intel_results = intel.run_full_scan()
    intel.close()
    print(f"  Competitive Intel: {intel_results['listings_checked']} checked, {intel_results['changes_detected']} changes, {intel_results['new_reviews']} new reviews, {intel_results['new_entrants']} new entrants, {intel_results['errors']} errors")


def run_digest():
    """Send daily digest + competitive intelligence to configured Telegram user."""
    print(f"[{datetime.now()}] Sending daily digest...")
    reporter = ReporterAgent()
    
    # Send daily digest
    success = reporter.send_daily_digest("7988136313")
    if success:
        print("  ✅ Digest sent to 7988136313")
    else:
        print("  ❌ Failed to send digest")
    
    # Send competitive intel report
    comp_success = reporter.send_competitive_report("7988136313")
    if comp_success:
        print("  ✅ Competitive report sent to 7988136313")
    else:
        print("  ❌ Failed to send competitive report")
    
    reporter.close()


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description='Prysma - Personal Market Intelligence Agent')
    parser.add_argument('--mode', choices=['bot', 'scan', 'digest', 'trends', 'dashboard', 'report', 'insights', 'competitive', 'analyze'], default='bot',
                       help='Run mode: bot (Telegram), scan (one-time), digest (send), trends (report), dashboard (charts), report (PDF), insights (actionable), competitive (ASO/reviews/pricing), analyze (strategic analysis)')
    parser.add_argument('--target', type=str, default=None,
                       help='Target competitor name or query for report/insights modes')
    args = parser.parse_args()

    if args.mode == 'bot':
        print("🤖 Starting Prysma Telegram bot...")
        asyncio.run(bot_module.run_polling())

    elif args.mode == 'scan':
        run_scan_cycle()

    elif args.mode == 'digest':
        run_digest()

    elif args.mode == 'trends':
        radar = TrendRadar()
        results = radar.scan_all_sources()
        report = radar.generate_trend_report()
        radar.close()
        print(report)

    elif args.mode == 'dashboard':
        print("📊 Generating dashboard...")
        gen = DashboardGenerator()
        paths = gen.generate_full_dashboard()
        if paths:
            for p in paths:
                print(f"  📈 {p}")
        else:
            print("  No data to display yet.")

    elif args.mode == 'report':
        if not args.target:
            print("❌ --target required for report mode")
            return
        print(f"📄 Generating report for {args.target}...")
        gen = ReportGenerator()
        filepath = gen.generate_competitor_report(args.target)
        if filepath:
            print(f"  📄 Report saved: {filepath}")
        else:
            print("  ❌ No data available for report.")

    elif args.mode == 'insights':
        if not args.target:
            print("❌ --target required for insights mode")
            return
        print(f"📊 Generating insights for {args.target}...")
        engine = ActionableInsights()
        report = engine.generate_competitor_report(args.target)
        print(report)

    elif args.mode == 'analyze':
        from prysma.agents.analyst import AnalystAgent
        print("🧠 Running strategic analysis (Nemotron Ultra)...")
        analyst = AnalystAgent()
        print(analyst.generate_strategic_analysis())
        analyst.close()

    elif args.mode == 'competitive':
        print("🔍 Running competitive intelligence scan...")
        intel = CompetitiveIntelAgent()
        results = intel.run_full_scan()
        intel.close()
        report = intel.generate_competitive_report()
        print(report)


if __name__ == '__main__':
    main()
