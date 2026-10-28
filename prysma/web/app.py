"""FastAPI web dashboard for Prysma — exposes the competitive intelligence
backend through a browser URL for hackathon judges.

Run: python -m prysma.web --host 0.0.0.0 --port 8000
"""
import argparse
import asyncio
import html
import re
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from prysma.config import config
from prysma.storage.database import WATCH_LIST_NAME_MAX, db
from prysma.web.markdown import render_report


@asynccontextmanager
async def _lifespan(_app):
    """Give the seeded watch lists content on a fresh database. Existing rows are untouched."""
    db.seed_watch_lists()
    yield


app = FastAPI(
    lifespan=_lifespan,
    title="Prysma",
    description="AI-Powered Competitive Intelligence Agent",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Per-IP hourly limit for the endpoints that spend Nebius and Tavily credits.
RATE_LIMIT_PER_HOUR = 20
RATE_LIMIT_WINDOW_SECONDS = 3600
# Cap on distinct clients tracked at once, so the bucket map cannot grow without
# bound. Far more than a real audience needs, and cheap to prune.
RATE_LIMIT_MAX_CLIENTS = 4096
_rate_hits: dict[str, deque] = {}
_rate_lock = threading.Lock()


def _rate_limited(request: Request) -> Optional[JSONResponse]:
    """Record a hit for this client IP. Return a 429 response if it is over the cap."""
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_lock:
        # Bound the map: an attacker (or a large audience) could otherwise grow
        # it without limit. The new client is inserted below, so prune to
        # strictly below the cap first, and only when this client is new --
        # otherwise a returning client could evict itself.
        if ip not in _rate_hits and len(_rate_hits) >= RATE_LIMIT_MAX_CLIENTS:
            # Drop fully-expired buckets.
            for key in [k for k, v in _rate_hits.items()
                        if not v or now - v[-1] >= RATE_LIMIT_WINDOW_SECONDS]:
                del _rate_hits[key]
            # Still full: drop the least recently seen.
            while len(_rate_hits) >= RATE_LIMIT_MAX_CLIENTS and _rate_hits:
                oldest = min(_rate_hits, key=lambda k: _rate_hits[k][-1] if _rate_hits[k] else 0)
                del _rate_hits[oldest]

        hits = _rate_hits.setdefault(ip, deque())
        while hits and now - hits[0] >= RATE_LIMIT_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= RATE_LIMIT_PER_HOUR:
            return JSONResponse({"error": "Rate limit reached for now. Try again later."}, status_code=429)
        hits.append(now)
    return None

TEMPLATE_DIR = Path(__file__).parent / "templates"
INDEX_HTML = TEMPLATE_DIR / "index.html"
SCAN_HTML = TEMPLATE_DIR / "scan.html"


def _load_template(name: str) -> str:
    path = TEMPLATE_DIR / name
    return path.read_text(encoding="utf-8")


# --- API routes ---------------------------------------------------------


# Time windows the dashboard shows. The KPI labels are built from these, so a
# label always states the window of the table it links to.
FINDINGS_HOURS = 168
ASO_HOURS = 168
# Alerts are low-frequency by design (quiet by default), so a month reads
# better than a week: a 7-day window is usually empty even when the tool works.
ALERT_HOURS = 720
ENTRANTS_HOURS = 720
REVIEW_HOURS = 720

# Report headers the analyst writes. They tell the two kinds of research digest apart.
STRATEGIC_PREFIX = "🧠 *Strategic Analysis*"
GAPS_PREFIX = "🕳 *Market Gap Analysis*"

# Background analysis runs, keyed by (kind, watch list). In memory only: a
# restart forgets them, and the saved digest stays the source of the result.
_jobs: dict[tuple[str, str], dict] = {}
_jobs_lock = threading.Lock()


def _watch_list(value: Optional[str]) -> str:
    """The requested watch list, or the default one for a missing or unknown key."""
    return value if db.watch_list_exists(value) else db.default_watch_list()


def _job_start(kind: str, watch_list: str) -> bool:
    """Mark a run as started. Returns False if the same run is already going."""
    with _jobs_lock:
        job = _jobs.get((kind, watch_list))
        if job and job["state"] == "running":
            return False
        _jobs[(kind, watch_list)] = {"state": "running", "started": time.time(), "message": ""}
        return True


def _job_finish(kind: str, watch_list: str, report: str, prefix: str):
    """Record the result. The analyst returns a plain message instead of a report on failure."""
    ok = isinstance(report, str) and report.startswith(prefix)
    with _jobs_lock:
        job = _jobs.setdefault((kind, watch_list), {"started": time.time()})
        job.update(state="done" if ok else "error", finished=time.time(),
                   message="" if ok else str(report or "No result.")[:500])


def _job_view(kind: str, watch_list: str) -> dict:
    with _jobs_lock:
        job = dict(_jobs.get((kind, watch_list)) or {"state": "idle"})
    if "started" in job:
        job["elapsed_seconds"] = int((job.get("finished") or time.time()) - job.pop("started"))
    job.pop("finished", None)
    return job


def _report_html(report: str) -> str:
    return render_report(report)


def _esc(value, fallback: str = "—") -> str:
    """Escape a value for HTML. Scraped and model text reaches every table."""
    text = "" if value is None else str(value)
    return html.escape(text) if text else fallback


def _store_links(store_ids: dict) -> str:
    """Links to the store pages of a competitor, built from the saved store IDs."""
    links = []
    android = store_ids.get("android")
    if android and re.fullmatch(r"[A-Za-z0-9_.]{1,200}", android):
        links.append(f"<a href='https://play.google.com/store/apps/details?id={android}' "
                     f"target='_blank' rel='noopener'>Google Play ↗</a>")
    ios = re.sub(r"^id", "", str(store_ids.get("ios") or ""))
    if re.fullmatch(r"\d{1,15}", ios):
        links.append(f"<a href='https://apps.apple.com/app/id{ios}' "
                     f"target='_blank' rel='noopener'>App Store ↗</a>")
    return " · ".join(links)


def _price_lines(listings: list[dict]) -> str:
    """One line per platform: star rating, base price, and in-app purchase range."""
    by_platform = {listing.get("platform"): listing for listing in listings}
    lines = []
    for platform, label in (("android", "Android"), ("ios", "iOS")):
        listing = by_platform.get(platform)
        if not listing:
            continue
        rating = listing.get("current_rating")
        parts = [f"{float(rating):.1f}★" if rating is not None else "no rating",
                 html.escape(listing.get("current_price") or "price unknown")]
        line = f"<strong>{label}</strong> " + " ".join(parts)
        iap = re.sub(r"\s*if billed through Play$", "", listing.get("current_iap_range") or "")
        if iap:
            iap = re.sub(r"\s*-\s*", "–", iap)
            line += f" · In-app purchases {html.escape(iap)}"
        lines.append(line)
    return f"<p class='prices'>{'<br>'.join(lines)}</p>" if lines else ""


def _empty_row(colspan: int, text: str) -> str:
    return f"<tr><td colspan='{colspan}' class='empty'>{text}</td></tr>"


_TIMESTAMP = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(:\d{2})?")


def _when(value) -> str:
    """A UTC database timestamp as a <time> element.

    The text is a readable UTC fallback; the page script rewrites it in the
    reader's own time zone ("Today, 14:05" or "3 days ago").
    """
    match = _TIMESTAMP.match(str(value or ""))
    if not match:
        return "—"
    day, clock, seconds = match.group(1), match.group(2), match.group(3) or ":00"
    stamp = datetime.strptime(day, "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")
    return f"<time class='when' datetime='{day}T{clock}{seconds}Z'>{stamp}, {clock} UTC</time>"


# Insight types. The dashboard shows one of these four for every alert and
# finding, mapped from data the detectors already write. There is no severity.
INSIGHT_LABELS = {
    "rating": "Rating change",
    "listing": "Listing change",
    "review": "Negative review",
    "news": "Competitor news",
}
_RATING_CHANGES = {"rating", "ratings_count"}
# 'opportunity' is the negative-review finding. 'sentiment' is review mood.
_REVIEW_FINDINGS = {"opportunity", "sentiment"}


def insight_type(source_table: Optional[str], kind: Optional[str], title: str = "") -> str:
    """Map a stored change to one of the four insight types.

    source_table is "aso_changes" (kind is the change_type) or "findings"
    (kind is the finding_type). A website "change" finding has no closer
    type than "listing"; reddit, github, trend and content findings are
    shown as news, the closest of the four.
    """
    if source_table == "aso_changes":
        return "rating" if kind in _RATING_CHANGES else "listing"
    if kind in _REVIEW_FINDINGS:
        return "review"
    if kind == "change":
        # ASO findings name the field: "ASO change: rating (Tabata Timer)"
        field = re.match(r"ASO change: (\w+)", title or "")
        return "rating" if field and field.group(1) in _RATING_CHANGES else "listing"
    return "news"


# What users ask for, by the complaint keyword the review scan matched.
USER_ASKS = {
    "screen off": "keep running with the screen off",
    "background": "keep running in the background",
    "stops": "keep running without stopping",
    "ads": "fewer ads",
    "subscription": "a one-off price instead of a subscription",
    "expensive": "a lower price",
    "too many": "fewer interruptions",
    "doesn't work": "an app that works reliably",
    "crash": "an app that does not crash",
    "bug": "fewer bugs",
    "slow": "a faster app",
    "ugly": "a better-looking design",
    "confusing": "a simpler, clearer design",
    "complicated": "a simpler, clearer design",
}
_COMPLAINT = re.compile(r'Most common complaint: "([^"]+)" \((\d+) of (\d+)')


def _complaint_html(content: Optional[str]) -> Optional[str]:
    """The complaint and the user ask in a negative-review finding, as escaped HTML."""
    match = _COMPLAINT.search(content or "")
    if not match:
        return None
    keyword, hits, total = match.groups()
    noun = "review" if total == "1" else "reviews"
    text = f"<strong>Complaint:</strong> “{html.escape(keyword)}” in {hits} of {total} {noun}."
    ask = USER_ASKS.get(keyword)
    if ask:
        text += f"<br><strong>Users ask for:</strong> {html.escape(ask)}."
    return text


def _insight_actions(kind: str, competitor_id, list_key: str, source_url: Optional[str]) -> str:
    """Links from an insight to its reviews, its competitor, or its source."""
    links = []
    if competitor_id and kind in ("review", "rating"):
        links.append(f"<a href='/reviews/{int(competitor_id)}'>Read the reviews</a>")
    if kind == "news" and isinstance(source_url, str) and re.match(r"https?://", source_url):
        links.append(f"<a href='{html.escape(source_url, quote=True)}' target='_blank' rel='noopener'>Read the source ↗</a>")
    if competitor_id:
        links.append(f"<a href='?list={html.escape(list_key, quote=True)}&amp;c={int(competitor_id)}#competitors'>Open competitor</a>")
    return "".join(f"<span>{link}</span>" for link in links)


def _type_badge(kind: str) -> str:
    return f"<span class='badge type-{kind}'>{INSIGHT_LABELS[kind]}</span>"


# ASO change labels for the competitor cards
CHANGE_LABELS = {
    "title": "Title", "subtitle": "Subtitle", "description": "Description", "price": "Price",
    "screenshots": "Screenshots", "icon": "Icon", "category": "Category", "rating": "Rating",
    "ratings_count": "Number of ratings", "release_date": "Release date", "version": "Version",
}
CARD_CHANGES_SHOWN = 5


def _drop_structured_data_repairs(changes: list[dict]) -> list[dict]:
    """Remove JSON-LD repair rows, so the KPI and the cards count the same rows.

    An older scraper stored the page's JSON-LD payload as the app description.
    Correcting that registers as a description change, but it is a data repair,
    not a competitor move. The alert engine skips the same rows, and it gates on
    change_type first, so this does too: a title or version that merely contains
    a quote must stay visible.
    """
    from prysma.agents.alerts import _looks_like_structured_data

    return [
        ac for ac in changes
        if not (
            ac.get("change_type") == "description"
            and (_looks_like_structured_data(str(ac.get("old_value") or ""))
                 or _looks_like_structured_data(str(ac.get("new_value") or "")))
        )
    ]


def _card_changes(changes: list[dict]) -> str:
    """The ASO change list under one competitor card, newest first."""
    if not changes:
        return f"<p class='changes-none'>No listing changes in the last {ASO_HOURS // 24} days.</p>"
    items = ""
    for ac in changes[:CARD_CHANGES_SHOWN]:
        label = CHANGE_LABELS.get(ac.get("change_type"), ac.get("change_type") or "Change")
        old = _esc(str(ac.get("old_value") or "")[:80], "(empty)")
        new = _esc(str(ac.get("new_value") or "")[:80], "(empty)")
        items += (
            f"<li><div class='change-head'><strong>{_esc(label)}</strong>"
            f"<span class='muted'>{_esc(ac.get('platform'), '')} · {_when(ac.get('detected_at'))}</span></div>"
            f"<div class='change-diff'><span class='muted'>Was:</span> {old}</div>"
            f"<div class='change-diff'><span class='muted'>Now:</span> {new}</div></li>"
        )
    more = len(changes) - CARD_CHANGES_SHOWN
    tail = f"<p class='muted small'>And {more} older change{'s' if more > 1 else ''}.</p>" if more > 0 else ""
    return f"<ol class='changes'>{items}</ol>{tail}"


@app.get("/", response_class=HTMLResponse)
async def index(list_key: Optional[str] = Query(None, alias="list")):
    """Main dashboard, scoped to one watch list."""
    watch_list = _watch_list(list_key)
    competitors = db.get_active_competitors(watch_list=watch_list)
    findings = db.get_recent_findings(hours=FINDINGS_HOURS, watch_list=watch_list)
    # Drop JSON-LD repair rows once, here, so the KPI count and the cards agree.
    aso_changes = _drop_structured_data_repairs(
        db.get_aso_changes(hours=ASO_HOURS, watch_list=watch_list))
    alerts = db.get_recent_alerts(hours=ALERT_HOURS, watch_list=watch_list)
    # New entrants and trends come from keyword searches, not from a competitor,
    # so they cannot belong to one watch list. The page says so.
    new_entrants = db.get_new_entrants(hours=ENTRANTS_HOURS)
    trend_reports = db.get_trend_reports(emerging_only=True)

    strategic = db.get_latest_digest("research", STRATEGIC_PREFIX, watch_list)
    gaps_report = db.get_latest_digest("research", GAPS_PREFIX, watch_list)

    # Every table lists all the rows its KPI card counts, so the two always agree.
    findings_rows = ""
    for f in findings:
        kind = insight_type("findings", f.get("finding_type"), f.get("title") or "")
        what = _esc((f.get("title") or "")[:160])
        if kind == "review":
            complaint = _complaint_html(f.get("content"))
            if complaint:
                what += f"<div class='detail'>{complaint}</div>"
        findings_rows += (
            f"<tr>"
            f"<td>{_type_badge(kind)}</td>"
            f"<td>{_esc(f.get('competitor_name'))}</td>"
            f"<td>{what}</td>"
            f"<td class='when-col'>{_when(f.get('created_at'))}</td>"
            f"<td class='actions'>{_insight_actions(kind, f.get('competitor_id'), watch_list, f.get('source_url'))}</td>"
            f"</tr>\n"
        )

    changes_by_competitor: dict[int, list] = {}
    for ac in aso_changes:  # already newest first
        changes_by_competitor.setdefault(ac.get("competitor_id"), []).append(ac)

    listings_by_competitor: dict[int, list] = {}
    for listing in db.get_app_listings():
        listings_by_competitor.setdefault(listing.get("competitor_id"), []).append(listing)

    comp_cards = ""
    for c in competitors:
        links = _store_links(db.get_competitor_store_ids(c))
        description = c.get("description") or ""
        comp_cards += (
            f"<article class='card comp' id='comp-{int(c['id'])}'>"
            f"<div class='comp-head'><h3>{html.escape(c['name'])}</h3>"
            f"<button type='button' class='btn-link' data-unwatch='{html.escape(c['name'], quote=True)}'>Unwatch</button></div>"
            + (f"<p class='muted'>{html.escape(description)}</p>" if description else "")
            + f"<p class='stores'>{links or '<span class=muted>No store IDs yet</span>'}</p>"
            + _price_lines(listings_by_competitor.get(c["id"], []))
            + f"<section class='comp-changes' aria-label='Listing changes for {html.escape(c['name'], quote=True)}'>"
            f"<h4>This app's listing changes ({ASO_HOURS // 24}d)</h4>"
            f"{_card_changes(changes_by_competitor.get(c['id'], []))}</section>"
            f"</article>\n"
        )

    entrant_rows = "".join(
        f"<tr>"
        f"<td>{_esc(ne.get('app_name'))}</td>"
        f"<td>{_esc(ne.get('platform'))}</td>"
        f"<td>{_esc(ne.get('developer'))}</td>"
        f"<td>{_esc(ne.get('category'))}</td>"
        f"</tr>\n"
        for ne in new_entrants
    )

    trends_section = ""
    if trend_reports:
        trend_rows = "".join(
            f"<tr><td>{_esc(tr.get('title'))}</td><td class='num'>{_esc(tr.get('strength'))}/10</td></tr>\n"
            for tr in trend_reports[:10]
        )
        trends_section = (
            "<section class='block'><div class='block-head'><h2>Emerging trends</h2>"
            "<span class='muted small'>All markets · from keyword signals</span></div>"
            "<div class='table-wrap'><table><thead><tr><th>Trend</th><th class='num'>Strength</th></tr></thead>"
            f"<tbody>{trend_rows}</tbody></table></div></section>"
        )

    # Alert messages carry scraped store text, so everything is escaped
    alert_rows = ""
    for a in alerts:
        if a.get("source_table") == "aso_changes":
            kind = insight_type("aso_changes", a.get("alert_type"))
        else:
            kind = insight_type("findings", a.get("finding_type"), a.get("title") or "")
        what = (kind == "review" and _complaint_html(a.get("finding_content"))) or _esc(a.get("message") or a.get("title"), "")
        alert_rows += (
            f"<tr>"
            f"<td>{_type_badge(kind)}</td>"
            f"<td>{_esc(a.get('competitor_name'))}</td>"
            f"<td>{what}</td>"
            f"<td class='when-col'>{_when(a.get('created_at'))}</td>"
            f"<td class='actions'>{_insight_actions(kind, a.get('competitor_id'), watch_list, a.get('source_url'))}"
            f"<span><button type='button' class='btn-link' data-dismiss='{int(a['id'])}'>Dismiss</button></span></td>"
            f"</tr>\n"
        )

    watch_lists = db.get_watch_lists()
    current_label = next((w["label"] for w in watch_lists if w["key"] == watch_list), "")
    list_options = "".join(
        f"<li class='list-pill'>"
        f"<a href='?list={html.escape(w['key'], quote=True)}' data-list='{html.escape(w['key'], quote=True)}'"
        + (" aria-current='page'" if w["key"] == watch_list else "")
        + f">{html.escape(w['label'])}</a>"
        f"<button type='button' class='pill-edit' data-edit-list='{html.escape(w['key'], quote=True)}' "
        f"data-label='{html.escape(w['label'], quote=True)}' "
        f"aria-label='Rename or delete {html.escape(w['label'], quote=True)}'>Edit</button>"
        f"</li>"
        for w in watch_lists
    )

    template = _load_template("index.html")
    # Use replacement instead of .format() to avoid CSS brace conflicts
    replacements = {
        "{watch_list}": watch_list,
        "{watch_list_label}": html.escape(current_label),
        "{list_name_max}": str(WATCH_LIST_NAME_MAX),
        "{list_options}": list_options,
        "{findings_window}": f"{FINDINGS_HOURS // 24}d",
        "{aso_window}": f"{ASO_HOURS // 24}d",
        "{alerts_window}": f"{ALERT_HOURS // 24}d",
        "{entrants_window}": f"{ENTRANTS_HOURS // 24}d",
        "{competitors_count}": str(len(competitors)),
        "{findings_count}": str(len(findings)),
        "{aso_count}": str(len(aso_changes)),
        "{alerts_count}": str(len(alerts)),
        "{comp_cards}": comp_cards or "<p class='empty'>No competitors in this list. Add some from <a href='#overview'>Find your market</a>.</p>",
        "{findings_rows}": findings_rows or _empty_row(5, "No findings in this window. Run a scan."),
        "{entrant_rows}": entrant_rows or _empty_row(4, "No new entrants detected."),
        "{trends_section}": trends_section,
        "{strategic_html}": _report_html(strategic["content"]) if strategic else "",
        "{gaps_html}": _report_html(gaps_report["content"]) if gaps_report else "",
        "{last_updated}": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "{alert_rows}": alert_rows or _empty_row(5, "No material changes detected. That's the quiet, normal state."),
    }
    # One pass over the template only, so placeholder-like text inside scraped
    # values is never replaced. Unknown {tokens} (CSS and JS braces) stay as they are.
    return re.sub(r"\{\w+\}", lambda m: replacements.get(m.group(0), m.group(0)), template)


@app.get("/scan", response_class=HTMLResponse)
async def scan_page():
    """Scan results page."""
    template = _load_template("scan.html")
    return template.replace("{last_updated}", datetime.now().strftime("%Y-%m-%d %H:%M"))


@app.post("/api/scan")
def run_scan(request: Request):
    """Trigger a scan cycle in a background thread."""
    if limited := _rate_limited(request):
        return limited
    from prysma.main import run_scan_cycle

    # One scan at a time. A second click while a scan is going used to start a
    # second thread, so two cycles scraped the same apps and raced on writes.
    scan_key = _watch_list(None)
    if not _job_start("scan", scan_key):
        return JSONResponse(
            {"error": "A scan is already running. Check back in a minute."},
            status_code=409,
        )

    def _run():
        try:
            run_scan_cycle()
            _job_finish("scan", scan_key, "Scan finished", "Scan finished")
        except Exception as e:
            print(f"Scan error: {e}")
            _job_finish("scan", scan_key, f"Scan failed: {e}", "Scan finished")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return JSONResponse({"status": "started", "message": "Scan started in background. Check back in a minute."})


@app.post("/api/analyze")
def run_analyze(request: Request, list_key: Optional[str] = Query(None, alias="list")):
    """Trigger strategic analysis with Nemotron Ultra, for one watch list when given."""
    if limited := _rate_limited(request):
        return limited
    from prysma.agents.analyst import AnalystAgent

    # No list means the old behaviour: every finding, tracked under the default list.
    scope = list_key if db.watch_list_exists(list_key) else None
    job_list = _watch_list(list_key)
    if not _job_start("analyze", job_list):
        return JSONResponse({"status": "running", "message": "Strategic analysis is already running."})

    def _run():
        report = ""
        try:
            analyst = AnalystAgent()
            report = analyst.generate_strategic_analysis(watch_list=scope)
            analyst.close()
        except Exception as e:
            print(f"Analysis error: {e}")
            report = "Strategic analysis failed."
        _job_finish("analyze", job_list, report, STRATEGIC_PREFIX)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return JSONResponse({"status": "started", "message": "Strategic analysis started. Check back in 2-3 minutes."})


@app.get("/api/analysis")
def analysis_status(list_key: Optional[str] = Query(None, alias="list")):
    """Run state and latest reports of the two Ultra analyses for one watch list.

    The dashboard polls this while a run is going, so it never waits on a long request.
    """
    watch_list = _watch_list(list_key)

    def latest(prefix):
        row = db.get_latest_digest("research", prefix, watch_list)
        if not row:
            return None
        return {"id": row["id"], "content": row["content"], "created_at": row["created_at"],
                "html": render_report(row["content"])}

    return {
        "watch_list": watch_list,
        "analyze": {**_job_view("analyze", watch_list), "report": latest(STRATEGIC_PREFIX)},
        "gaps": {**_job_view("gaps", watch_list), "report": latest(GAPS_PREFIX)},
    }


@app.get("/api/status")
async def status():
    """Quick status JSON for health checks."""
    competitors = db.get_active_competitors()
    findings = db.get_recent_findings(hours=24)
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "competitors": len(competitors),
        "findings_24h": len(findings),
        "database": config.database_path,
    }


@app.get("/api/alerts")
def alerts(hours: int = Query(168, ge=1, le=8760)):
    """Recent alerts, newest first."""
    return {"alerts": db.get_recent_alerts(hours=hours)}


@app.post("/api/alerts/run")
def run_alerts(request: Request):
    """Build alerts from recent changes and send the unsent ones."""
    if limited := _rate_limited(request):
        return limited
    from prysma.agents.alerts import AlertEngine

    engine = AlertEngine()
    built = engine.build_alerts()
    sent = engine.send_alerts()
    return {"built": len(built), "sent": sent}


@app.get("/api/tavily")
def tavily_search(request: Request, query: str = Query(..., min_length=2)):
    """Run a Tavily web search."""
    if limited := _rate_limited(request):
        return limited
    if not config.tavily_api_key:
        return JSONResponse({"error": "TAVILY_API_KEY not configured"}, status_code=400)
    from prysma.sources.tavily_search import TavilySource

    source = TavilySource()
    results = source.search(query, max_results=5)
    return {"query": query, "results": results}


class DiscoverRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)


class WatchRequest(BaseModel):
    candidates: list[dict] = Field(..., max_length=50)
    watch_list: Optional[str] = Field(None, max_length=50)


class UnwatchRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


@app.post("/api/discover")
def discover(request: Request, body: DiscoverRequest):
    """Find candidate competitors for an app, store link, or idea, then profile them."""
    if limited := _rate_limited(request):
        return limited
    from prysma.agents.discovery import DiscoveryAgent

    agent = DiscoveryAgent()
    try:
        candidates = agent.discover(body.query)
    finally:
        agent.close()
    return {"query": body.query, "candidates": candidates}


def _clean_store_url(url) -> Optional[str]:
    """Keep only Google Play and App Store https links."""
    if isinstance(url, str) and re.match(r"https://(play\.google\.com|apps\.apple\.com)/", url):
        return url[:500]
    return None


@app.post("/api/watch")
def watch(body: WatchRequest):
    """Add the selected candidates to the competitor list."""
    added = 0
    for cand in body.candidates:
        name = str(cand.get("name") or "").strip()[:100]
        if not name:
            continue
        store_ids = {}
        package = cand.get("package")
        if isinstance(package, str) and re.fullmatch(r"[A-Za-z0-9_.]{1,200}", package):
            store_ids["android"] = package
        ios_id = cand.get("ios_id")
        if ios_id is not None and re.fullmatch(r"\d{1,15}", str(ios_id)):
            store_ids["ios"] = str(ios_id)

        competitor_id = db.add_competitor(
            name=name,
            website=_clean_store_url(cand.get("store_url")),
            description=str(cand.get("summary") or "")[:300] or None,
            store_ids=store_ids,
            watch_list=_watch_list(body.watch_list),
        )
        if competitor_id:
            added += 1
    return {"added": added}


@app.post("/api/unwatch")
def unwatch(body: UnwatchRequest):
    """Stop watching a competitor. Its history stays; watching it again restores it."""
    return {"removed": db.remove_competitor(body.name)}


@app.post("/api/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: int):
    """Hide an alert from the dashboard. A rebuild does not bring it back."""
    return {"dismissed": db.dismiss_alert(alert_id)}


@app.post("/api/gaps")
def gaps(request: Request, list_key: Optional[str] = Query(None, alias="list")):
    """Run the market gap analysis with Nemotron Ultra and return the report.

    The run is also tracked, so a reloaded dashboard still shows it in progress.
    """
    if limited := _rate_limited(request):
        return limited
    from prysma.agents.analyst import AnalystAgent

    scope = list_key if db.watch_list_exists(list_key) else None
    job_list = _watch_list(list_key)
    # _job_start already refuses a second concurrent run; the return value used to
    # be discarded, so the guard did nothing and two Ultra calls could run at once.
    if not _job_start("gaps", job_list):
        return JSONResponse(
            {"error": "A gap analysis is already running for this watch list. Check back shortly."},
            status_code=409,
        )
    report = "Gap analysis failed."
    analyst = AnalystAgent()
    try:
        report = analyst.generate_gap_analysis(watch_list=scope)
    finally:
        analyst.close()
        _job_finish("gaps", job_list, report, GAPS_PREFIX)
    return {"report": report}


class ListNameRequest(BaseModel):
    name: str = Field(..., max_length=200)


def _list_error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


@app.get("/api/lists")
def list_watch_lists():
    """Every watch list, oldest first."""
    return {"lists": db.get_watch_lists()}


@app.post("/api/lists")
def create_watch_list(body: ListNameRequest):
    """Create an empty, user-named watch list."""
    try:
        return db.create_watch_list(body.name)
    except ValueError as e:
        return _list_error(str(e))


@app.post("/api/lists/{key}/rename")
def rename_watch_list(key: str, body: ListNameRequest):
    """Rename a watch list. The key, and so every link to the list, stays."""
    try:
        if not db.rename_watch_list(key, body.name):
            return _list_error("That list does not exist.", 404)
    except ValueError as e:
        return _list_error(str(e))
    return {"key": key, "label": " ".join(body.name.split())}


@app.post("/api/lists/{key}/delete")
def delete_watch_list(key: str):
    """Delete a watch list and stop watching its competitors. Their history stays."""
    try:
        if not db.delete_watch_list(key):
            return _list_error("That list does not exist.", 404)
    except ValueError as e:
        return _list_error(str(e))
    return {"deleted": key, "next": db.default_watch_list()}


@app.get("/reviews/{competitor_id}", response_class=HTMLResponse)
def reviews_page(competitor_id: int):
    """The full text of one competitor's recent low-rated reviews."""
    competitor = db.get_competitor(competitor_id)
    if not competitor:
        return HTMLResponse("Competitor not found.", status_code=404)
    reviews = db.get_recent_reviews(competitor_id=competitor_id, rating_max=2, hours=REVIEW_HOURS)
    items = "".join(
        f"<article class='review'>"
        f"<div class='review-head'><span class='stars'>{_esc(r.get('rating'))} of 5 stars</span>"
        f"<span class='muted'>{_esc(r.get('platform'), '')} · {_when(r.get('detected_at'))}</span></div>"
        + (f"<h2>{_esc(r.get('title'))}</h2>" if r.get("title") else "")
        + f"<p>{_esc(r.get('content'), '')}</p>"
        f"<p class='muted small'>{_esc(r.get('author'), 'Anonymous')}</p>"
        f"</article>\n"
        for r in reviews
    ) or f"<p class='muted'>No 1 or 2 star reviews in the last {REVIEW_HOURS // 24} days.</p>"
    replacements = {
        "{name}": html.escape(competitor["name"]),
        "{list}": html.escape(competitor.get("watch_list") or "", quote=True),
        "{competitor_id}": str(int(competitor_id)),
        "{days}": str(REVIEW_HOURS // 24),
        "{count}": str(len(reviews)),
        "{reviews}": items,
    }
    template = _load_template("reviews.html")
    return re.sub(r"\{\w+\}", lambda m: replacements.get(m.group(0), m.group(0)), template)


def main():
    parser = argparse.ArgumentParser(description="Prysma web dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    args = parser.parse_args()

    print(f"🚀 Prysma web dashboard starting on http://{args.host}:{args.port}")
    # Traefik fronts this app, so without proxy headers every request appears to
    # come from the proxy and the per-IP rate limit becomes one global bucket.
    # But trusting "*" is not the fix: uvicorn then returns the LEFTMOST
    # X-Forwarded-For value, which the caller supplies, so anyone could mint a new
    # bucket per request. Name the proxy's network instead.
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips=config.web_trusted_proxies,
    )


if __name__ == "__main__":
    main()
