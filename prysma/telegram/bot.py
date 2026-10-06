"""Telegram bot interface for Prysma."""
import asyncio
import functools
import re
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from prysma.config import config
from prysma.security import (
    validate_telegram_command,
    check_rate_limit,
    sanitize_user_input
)
from prysma.storage.database import db


def authorized_only(handler):
    """Decorator: reject commands from users not in TELEGRAM_ALLOWED_USERS.

    Prevents unauthorized users from running costly Ultra-model analysis or
    accessing competitive intelligence through the bot.
    """
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user:
            return
        allowed = {int(uid.strip()) for uid in config.telegram_allowed_users.split(",") if uid.strip().isdigit()}
        if update.effective_user.id not in allowed:
            await update.message.reply_text("🚫 Unauthorized. This bot is private.")
            return
        return await handler(update, context)
    return wrapper


# Google Play package name (com.example.app) and App Store ID (id123456 or 123456)
ANDROID_PACKAGE_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$')
IOS_APP_ID_RE = re.compile(r'^(id)?(\d{5,12})$', re.IGNORECASE)


def parse_store_id_flags(args: list[str]) -> tuple[list[str], dict, Optional[str]]:
    """Split /watch args into name words and --android= / --ios= store IDs.

    Returns (name_args, store_ids, bad_flag). bad_flag is the first invalid
    flag, or None.
    """
    name_args, store_ids = [], {}
    for arg in args:
        # Some Telegram clients turn "--" into an em dash
        if arg.startswith('—'):
            arg = '--' + arg[1:]
        if arg.startswith('--android='):
            value = arg.split('=', 1)[1]
            if not ANDROID_PACKAGE_RE.match(value):
                return name_args, store_ids, arg
            store_ids['android'] = value
        elif arg.startswith('--ios='):
            match = IOS_APP_ID_RE.match(arg.split('=', 1)[1])
            if not match:
                return name_args, store_ids, arg
            store_ids['ios'] = f"id{match.group(2)}"
        elif arg.startswith('--'):
            return name_args, store_ids, arg
        else:
            name_args.append(arg)
    return name_args, store_ids, None


@authorized_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    welcome = (
        f"👋 Welcome to *Prysma*, {user.first_name}!\n\n"
        "I'm your personal market intelligence agent.\n\n"
        "*Commands:*\n"
        "/watch <name> --android=<pkg> --ios=<id> — Add competitor (store IDs optional)\n"
        "/unwatch <name> — Remove competitor\n"
        "/list — Show watched competitors\n"
        "/research <query> — Run research\n"
        "/tavily <query> — Web search via Tavily\n"
        "/analyze — Strategic analysis (Nemotron Ultra)\n"
        "/digest — Get today's digest\n"
        "/trends — Show trend report\n"
        "/dashboard — Visual dashboard\n"
        "/insights <name> — Actionable insights\n"
        "/report <name> — PDF report\n"
        "/eli5 <query> — Explain like I'm 5\n"
        "/actionplan — Weekly action plan\n"
        "/status — System status\n"
        "/help — Show help"
    )
    await update.message.reply_text(welcome, parse_mode='Markdown')


@authorized_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "📖 *Prysma Help*\n\n"
        "*Competitor Tracking:*\n"
        "/watch <name> — Add competitor (company or product)\n"
        "/watch <name> --android=<package> --ios=<app_id> — Add with app store IDs\n"
        "/unwatch <name> — Remove competitor\n"
        "/list — Show all watched competitors\n\n"
        "*Intelligence:*\n"
        "/research <query> — Run on-demand research\n"
        "/tavily <query> — Web search via Tavily\n"
        "/analyze — Market gaps, threats, actions (Nemotron Ultra)\n"
        "/digest — Get today's digest now\n"
        "/trends [vertical] — Show trends (tech/fitness/finance)\n"
        "/verticals — List available verticals\n"
        "/insights <name> — Actionable insights\n"
        "/eli5 <query> — Explain like I'm 5\n\n"
        "*Reports & Visuals:*\n"
        "/dashboard — Visual dashboard\n"
        "/report <name> — PDF report\n"
        "/actionplan — Weekly action plan\n\n"
        "*System:*\n"
        "/status — System status\n"
        "/help — Show this help"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')


@authorized_only
async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /watch command — add competitor (company or product)."""
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    name_args, store_ids, bad_flag = parse_store_id_flags(context.args or [])
    if bad_flag:
        await update.message.reply_text(
            f"🚫 Invalid store ID: {sanitize_user_input(bad_flag)}\n"
            "Usage: /watch <name> --android=<package> --ios=<app_id>"
        )
        return

    query = ' '.join(name_args)
    is_valid, sanitized = validate_telegram_command(query)

    if not is_valid:
        await update.message.reply_text("🚫 Invalid competitor name.")
        return

    # Add as company (with optional website detection)
    website = None
    if '.' in sanitized and ' ' not in sanitized:
        # Looks like a domain name
        website = sanitized if sanitized.startswith('http') else f"https://{sanitized}"
        # Use domain name as company name
        from prysma.utils.helpers import extract_domain
        name = extract_domain(sanitized)
    else:
        name = sanitized

    competitor_id = db.add_competitor(name=name, website=website, description=None,
                                      store_ids=store_ids)

    if competitor_id:
        msg = f"✅ Now watching: *{name}*"
        if website:
            msg += f"\nWebsite: {website}"
        for platform, store_id in store_ids.items():
            msg += f"\n{platform.title()}: `{store_id}`"
        msg += "\n\nI'll monitor for:"
        msg += "\n• Product launches & feature updates"
        msg += "\n• Pricing changes"
        msg += "\n• News mentions"
        msg += "\n• Hiring activity"
        msg += "\n• Content & SEO changes"
        await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"⚠️ Could not add competitor: {sanitized}")


@authorized_only
async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unwatch command — remove competitor."""
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    query = ' '.join(context.args) if context.args else ""
    is_valid, sanitized = validate_telegram_command(query)

    if not is_valid:
        await update.message.reply_text("🚫 Invalid competitor name.")
        return

    success = db.remove_competitor(sanitized)

    if success:
        await update.message.reply_text(f"✅ Stopped watching: *{sanitized}*", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"⚠️ Competitor not found: {sanitized}")


@authorized_only
async def list_competitors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /list command — show all competitors."""
    competitors = db.get_active_competitors()

    if not competitors:
        await update.message.reply_text("📋 No competitors being watched. Use /watch <name> to add one.")
        return

    lines = ["📋 *Watched Competitors:*"]
    for c in competitors:
        lines.append(f"  • {c['name']}")

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


@authorized_only
async def research(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /research command — run on-demand research."""
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    query = ' '.join(context.args) if context.args else ""
    is_valid, sanitized = validate_telegram_command(query)

    if not is_valid:
        await update.message.reply_text("🚫 Query rejected for security reasons.")
        return

    await update.message.reply_text(f"🔍 Researching: {sanitized}...")

    # Run scout scan
    from prysma.agents.scout import ScoutAgent
    scout = ScoutAgent()

    # Add temporary competitor for research
    comp_id = db.add_competitor(name=sanitized, website=None, description="Research target")
    findings = scout.scan_competitor({'id': comp_id, 'name': sanitized})
    scout.close()

    if findings:
        for f in findings[:3]:
            if 'error' not in f:
                await update.message.reply_text(f"📌 {f['title']}\n\n{f.get('content', '')[:300]}")
    else:
        await update.message.reply_text("No new findings. Try again later.")


@authorized_only
async def digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /digest command — get daily digest."""
    from prysma.agents.reporter import ReporterAgent
    reporter = ReporterAgent()
    success = reporter.send_daily_digest(str(update.effective_chat.id))
    reporter.close()

    if not success:
        await update.message.reply_text("⚠️ Could not generate digest.")


@authorized_only
async def trends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /trends command — show trend report with optional vertical filter."""
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    # Check for vertical filter: /trends fitness
    vertical = None
    if context.args:
        v = context.args[0].lower()
        if v in ['tech', 'fitness', 'finance']:
            vertical = v

    from prysma.agents.reporter import ReporterAgent
    reporter = ReporterAgent()
    
    from prysma.agents.trend_radar import TrendRadar
    radar = TrendRadar()
    report = radar.generate_trend_report(vertical=vertical)
    radar.close()
    reporter.close()

    await update.message.reply_text(report, parse_mode='Markdown')


@authorized_only
async def verticals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /verticals command — show available verticals."""
    text = (
        "📊 *Available Verticals*\n\n"
        "tech — AI, SaaS, crypto, devtools\n"
        "fitness — health, gym, wellness, nutrition\n"
        "finance — fintech, investing, banking, crypto\n\n"
        "Usage: `/trends fitness` or `/trends finance`"
    )
    await update.message.reply_text(text, parse_mode='Markdown')


@authorized_only
async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dashboard command — send visual dashboard charts."""
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    await update.message.reply_text("📊 Generating dashboard...")

    from prysma.dashboard import DashboardGenerator
    gen = DashboardGenerator()
    paths = gen.generate_full_dashboard()

    if paths:
        for path in paths:
            try:
                with open(path, 'rb') as f:
                    await update.message.reply_photo(photo=f)
            except Exception as e:
                await update.message.reply_text(f"⚠️ Could not send chart: {e}")
    else:
        await update.message.reply_text("📊 No data to display yet. Add competitors first!")


@authorized_only
async def insights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /insights command — send actionable insights."""
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    query = ' '.join(context.args) if context.args else ""
    is_valid, sanitized = validate_telegram_command(query)

    if not is_valid:
        await update.message.reply_text("🚫 Invalid competitor name.")
        return

    from prysma.insights import ActionableInsights
    insights_engine = ActionableInsights()
    report = insights_engine.generate_competitor_report(sanitized)

    # Split long messages
    if len(report) > 4096:
        parts = report.split('\n\n')
        current = ""
        for part in parts:
            if len(current) + len(part) + 2 > 4096:
                await update.message.reply_text(current, parse_mode='Markdown')
                current = part
            else:
                current += '\n\n' + part if current else part
        if current:
            await update.message.reply_text(current, parse_mode='Markdown')
    else:
        await update.message.reply_text(report, parse_mode='Markdown')


@authorized_only
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /report command — generate and send PDF report."""
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    query = ' '.join(context.args) if context.args else ""
    is_valid, sanitized = validate_telegram_command(query)

    if not is_valid:
        await update.message.reply_text("🚫 Invalid competitor name.")
        return

    await update.message.reply_text(f"📄 Generating report for {sanitized}...")

    from prysma.reports import ReportGenerator
    gen = ReportGenerator()
    filepath = gen.generate_competitor_report(sanitized)

    if filepath:
        try:
            with open(filepath, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    filename=f"Prysma_Report_{sanitized}.pdf",
                    caption=f"📊 Competitor Report: {sanitized}"
                )
        except Exception as e:
            await update.message.reply_text(f"⚠️ Could not send report: {e}")
    else:
        await update.message.reply_text("📄 No data available for report. Add competitors and wait for scans.")


@authorized_only
async def eli5(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /eli5 command — explain like I'm 5."""
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    query = ' '.join(context.args) if context.args else ""
    is_valid, sanitized = validate_telegram_command(query)

    if not is_valid:
        await update.message.reply_text("🚫 Query rejected for security reasons.")
        return

    await update.message.reply_text(f"🤔 Breaking this down simply...")

    # Get recent findings related to query
    findings = db.get_recent_findings(hours=168)
    related = [f for f in findings if sanitized.lower() in f.get('title', '').lower() or 
               sanitized.lower() in f.get('content', '').lower()]

    if related:
        # Use the most important finding
        best = max(related, key=lambda x: x['importance'])
        from prysma.insights import ActionableInsights
        engine = ActionableInsights()
        insight = engine.generate_insight(best)
        await update.message.reply_text(insight, parse_mode='Markdown')
    else:
        await update.message.reply_text(
            f"🤔 *Explain Like I'm 5: {sanitized}*\n\n"
            f"I don't have enough data yet to explain this simply.\n"
            f"Try /research {sanitized} first, then ask me to explain!"
        )


@authorized_only
async def actionplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /actionplan command — weekly action plan."""
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    from prysma.insights import ActionableInsights
    engine = ActionableInsights()
    plan = engine.generate_weekly_action_plan()

    await update.message.reply_text(plan, parse_mode='Markdown')


async def reply_long(update: Update, text: str):
    """Send text in 4096-char chunks. Falls back to plain text when the
    Markdown from model output does not parse."""
    for i in range(0, len(text), 4096):
        chunk = text[i:i + 4096]
        try:
            await update.message.reply_text(chunk, parse_mode='Markdown')
        except Exception:
            await update.message.reply_text(chunk)


@authorized_only
async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /analyze command — strategic analysis with Nemotron Ultra."""
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    await update.message.reply_text("🧠 Running strategic analysis (Nemotron Ultra). This can take a minute...")

    from prysma.agents.analyst import AnalystAgent
    analyst = AnalystAgent()
    try:
        result = await asyncio.to_thread(analyst.generate_strategic_analysis)
    finally:
        analyst.close()

    await reply_long(update, result)


@authorized_only
async def tavily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tavily command — run a Tavily web search."""
    user_id = update.effective_user.id

    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Too many requests. Please wait a minute.")
        return

    query = ' '.join(context.args) if context.args else ""
    is_valid, sanitized = validate_telegram_command(query)

    if not is_valid:
        await update.message.reply_text("🚫 Query rejected for security reasons.")
        return

    if not config.tavily_api_key:
        await update.message.reply_text("⚠️ Tavily search needs TAVILY_API_KEY.")
        return

    await update.message.reply_text(f"🌐 Searching: {sanitized}...")

    from prysma.sources.tavily_search import TavilySource
    try:
        results = await asyncio.to_thread(TavilySource().search, sanitized)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Tavily search failed: {e}")
        return

    if not results:
        await update.message.reply_text("No results found.")
        return

    lines = [f"🌐 Tavily results: {sanitized}", ""]
    for r in results:
        lines.append(f"• {r['title']}")
        lines.append(f"  {r['content'][:200]}")
        lines.append(f"  {r['url']}")
        lines.append("")
    # Plain text: titles and URLs often contain Markdown characters
    text = '\n'.join(lines)
    for i in range(0, len(text), 4096):
        await update.message.reply_text(text[i:i + 4096], disable_web_page_preview=True)


@authorized_only
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command — show system status."""
    competitors = db.get_active_competitors()
    findings = db.get_recent_findings(hours=24)
    unread = db.get_unread_findings()

    status_text = (
        "📊 *Prysma Status*\n\n"
        f"Competitors watched: {len(competitors)}\n"
        f"Findings (24h): {len(findings)}\n"
        f"Unread findings: {len(unread)}\n"
        f"Database: {config.database_path}"
    )

    await update.message.reply_text(status_text, parse_mode='Markdown')


def create_application() -> Application:
    """Create and configure the Telegram bot application."""
    app = Application.builder().token(config.telegram_bot_token).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("watch", watch))
    app.add_handler(CommandHandler("unwatch", unwatch))
    app.add_handler(CommandHandler("list", list_competitors))
    app.add_handler(CommandHandler("research", research))
    app.add_handler(CommandHandler("digest", digest))
    app.add_handler(CommandHandler("trends", trends))
    app.add_handler(CommandHandler("verticals", verticals))
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("insights", insights))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("eli5", eli5))
    app.add_handler(CommandHandler("actionplan", actionplan))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("tavily", tavily))
    app.add_handler(CommandHandler("status", status))

    return app


async def run_polling():
    """Run the bot with polling."""
    app = create_application()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("🤖 Prysma Telegram bot is running...")
    # Keep running
    await asyncio.Event().wait()
