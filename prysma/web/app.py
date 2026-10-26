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
from prysma.storage.database import DEFAULT_WATCH_LIST, WATCH_LISTS, db


@asynccontextmanager
async def _lifespan(_app):
    """Give both watch lists content on a fresh database. Existing rows are untouched."""
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
_rate_hits: dict[str, deque] = {}
_rate_lock = threading.Lock()


def _rate_limited(request: Request) -> Optional[JSONResponse]:
    """Record a hit for this client IP. Return a 429 response if it is over the cap."""
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_lock:
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

# Report headers the analyst writes. They tell the two kinds of research digest apart.
STRATEGIC_PREFIX = "🧠 *Strategic Analysis*"
GAPS_PREFIX = "🕳 *Market Gap Analysis*"

# Background analysis runs, keyed by (kind, watch list). In memory only: a
# restart forgets them, and the saved digest stays the source of the result.
_jobs: dict[tuple[str, str], dict] = {}
_jobs_lock = threading.Lock()


def _watch_list(value: Optional[str]) -> str:
    """The requested watch list, or the default one for a missing or unknown key."""
    return value if value in WATCH_LISTS else DEFAULT_WATCH_LIST


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
    return html.escape(report).replace("\n", "<br>\n")


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


def _empty_row(colspan: int, text: str) -> str:
    return f"<tr><td colspan='{colspan}' class='empty'>{text}</td></tr>"


@app.get("/", response_class=HTMLResponse)
async def index(list_key: Optional[str] = Query(None, alias="list")):
    """Main dashboard, scoped to one watch list."""
    watch_list = _watch_list(list_key)
    competitors = db.get_active_competitors(watch_list=watch_list)
    findings = db.get_recent_findings(hours=FINDINGS_HOURS, watch_list=watch_list)
    aso_changes = db.get_aso_changes(hours=ASO_HOURS, watch_list=watch_list)
    alerts = db.get_recent_alerts(hours=ALERT_HOURS, watch_list=watch_list)
    # New entrants and trends come from keyword searches, not from a competitor,
    # so they cannot belong to one watch list. The page says so.
    new_entrants = db.get_new_entrants(hours=ENTRANTS_HOURS)
    trend_reports = db.get_trend_reports(emerging_only=True)

    strategic = db.get_latest_digest("research", STRATEGIC_PREFIX, watch_list)
    gaps_report = db.get_latest_digest("research", GAPS_PREFIX, watch_list)

    # Every table lists all the rows its KPI card counts, so the two always agree.
    findings_rows = "".join(
        f"<tr>"
        f"<td>{_esc(f.get('competitor_name'))}</td>"
        f"<td><span class='badge badge-{_esc(f.get('finding_type'), 'change')}'>{_esc(f.get('finding_type'))}</span></td>"
        f"<td>{_esc((f.get('title') or '')[:120])}</td>"
        f"<td class='num'>{_esc(f.get('importance'))}</td>"
        f"<td class='num'>{_esc(str(f.get('created_at') or '')[:16])}</td>"
        f"</tr>\n"
        for f in findings
    )

    comp_cards = ""
    for c in competitors:
        links = _store_links(db.get_competitor_store_ids(c))
        description = c.get("description") or ""
        comp_cards += (
            f"<article class='card comp'>"
            f"<div class='comp-head'><h3>{html.escape(c['name'])}</h3>"
            f"<button type='button' class='btn-link' data-unwatch='{html.escape(c['name'], quote=True)}'>Unwatch</button></div>"
            + (f"<p class='muted'>{html.escape(description)}</p>" if description else "")
            + f"<p class='stores'>{links or '<span class=muted>No store IDs yet</span>'}</p>"
            f"</article>\n"
        )

    aso_rows = "".join(
        f"<tr>"
        f"<td>{_esc(ac.get('competitor_name'))}</td>"
        f"<td>{_esc(ac.get('platform'))}</td>"
        f"<td>{_esc(ac.get('change_type'))}</td>"
        f"<td class='clip'>{_esc(str(ac.get('old_value') or '')[:60])}</td>"
        f"<td class='clip'>{_esc(str(ac.get('new_value') or '')[:60])}</td>"
        f"<td class='num'>{_esc(str(ac.get('detected_at') or '')[:16])}</td>"
        f"</tr>\n"
        for ac in aso_changes
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
        severity = a.get("severity") if a.get("severity") in ("high", "medium", "low") else "low"
        alert_rows += (
            f"<tr>"
            f"<td><span class='badge badge-sev-{severity}'>{severity}</span></td>"
            f"<td>{_esc(a.get('competitor_name'))}</td>"
            f"<td>{_esc(a.get('message') or a.get('title'), '')}</td>"
            f"<td class='num'>{_esc(str(a.get('created_at') or '')[:16])}</td>"
            f"<td class='num'><button type='button' class='btn-link' data-dismiss='{int(a['id'])}'>Dismiss</button></td>"
            f"</tr>\n"
        )

    list_options = "".join(
        f"<a class='seg' href='?list={key}' data-list='{key}'"
        + (" aria-current='true'" if key == watch_list else "")
        + f">{html.escape(meta['label'])}</a>"
        for key, meta in WATCH_LISTS.items()
    )

    template = _load_template("index.html")
    # Use replacement instead of .format() to avoid CSS brace conflicts
    replacements = {
        "{watch_list}": watch_list,
        "{watch_list_label}": html.escape(WATCH_LISTS[watch_list]["label"]),
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
        "{aso_rows}": aso_rows or _empty_row(6, "No ASO changes detected."),
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

    def _run():
        try:
            run_scan_cycle()
        except Exception as e:
            print(f"Scan error: {e}")

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
    scope = list_key if list_key in WATCH_LISTS else None
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
        return {"id": row["id"], "content": row["content"], "created_at": row["created_at"]} if row else None

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

    scope = list_key if list_key in WATCH_LISTS else None
    job_list = _watch_list(list_key)
    _job_start("gaps", job_list)
    report = "Gap analysis failed."
    analyst = AnalystAgent()
    try:
        report = analyst.generate_gap_analysis(watch_list=scope)
    finally:
        analyst.close()
        _job_finish("gaps", job_list, report, GAPS_PREFIX)
    return {"report": report}


def main():
    parser = argparse.ArgumentParser(description="Prysma web dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    args = parser.parse_args()

    print(f"🚀 Prysma web dashboard starting on http://{args.host}:{args.port}")
    # Traefik fronts this app, so without these every request appears to come
    # from the proxy's address and the per-IP rate limit becomes one global
    # bucket. The container port is not published to the host, so only Traefik
    # can reach the app and trusting X-Forwarded-For is safe here.
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
