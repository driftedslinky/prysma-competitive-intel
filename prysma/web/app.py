"""FastAPI web dashboard for Prysma — exposes the competitive intelligence
backend through a browser URL for hackathon judges.

Run: python -m prysma.web --host 0.0.0.0 --port 8000
"""
import argparse
import asyncio
import html
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from prysma.config import config
from prysma.storage.database import db


app = FastAPI(title="Prysma", description="AI-Powered Competitive Intelligence Agent")

TEMPLATE_DIR = Path(__file__).parent / "templates"
INDEX_HTML = TEMPLATE_DIR / "index.html"
SCAN_HTML = TEMPLATE_DIR / "scan.html"


def _load_template(name: str) -> str:
    path = TEMPLATE_DIR / name
    return path.read_text(encoding="utf-8")


# --- API routes ---------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index():
    """Main dashboard — competitor list, recent findings, strategic analysis."""
    competitors = db.get_active_competitors()
    findings = db.get_recent_findings(hours=168)
    aso_changes = db.get_aso_changes(hours=168)
    new_entrants = db.get_new_entrants(hours=720)
    trend_reports = db.get_trend_reports(emerging_only=True)

    # Pre-render the strategic analysis from the latest digest if available
    strategic_html = ""
    digests = []
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM digests WHERE digest_type = 'research' ORDER BY created_at DESC LIMIT 1"
            ).fetchall()
            digests = db._rows_to_dicts(rows)
    except Exception:
        pass
    if digests:
        strategic_html = html.escape(digests[0].get("content", "")).replace("\n", "<br>\n")

    # Build findings table
    findings_rows = ""
    for f in findings[:20]:
        findings_rows += (
            f"<tr>"
            f"<td>{f.get('competitor_name', '—')}</td>"
            f"<td><span class='badge badge-{f.get('finding_type', 'change')}'>{f.get('finding_type', '—')}</span></td>"
            f"<td>{f.get('title', '—')[:80]}</td>"
            f"<td>{f.get('importance', '—')}</td>"
            f"<td>{f.get('created_at', '—')[:19]}</td>"
            f"</tr>\n"
        )

    # Build competitor cards
    comp_cards = ""
    for c in competitors:
        store_ids = c.get("store_ids", "") or ""
        # Names and descriptions now come from scraped listings via /api/watch, so escape them
        comp_cards += (
            f"<div class='card'>"
            f"<h3>{html.escape(c['name'])}</h3>"
            f"<p class='muted'>{html.escape(c.get('description', '') or '')}</p>"
            f"<p class='small'>Website: {html.escape(c.get('website', '—') or '—')}</p>"
            f"</div>\n"
        )

    # ASO changes
    aso_rows = ""
    for ac in aso_changes[:10]:
        aso_rows += (
            f"<tr>"
            f"<td>{ac.get('competitor_name', '—')}</td>"
            f"<td>{ac.get('platform', '—')}</td>"
            f"<td>{ac.get('change_type', '—')}</td>"
            f"<td>{str(ac.get('old_value', ''))[:30]}</td>"
            f"<td>{str(ac.get('new_value', ''))[:30]}</td>"
            f"</tr>\n"
        )

    # New entrants
    entrant_rows = ""
    for ne in new_entrants[:10]:
        entrant_rows += (
            f"<tr>"
            f"<td>{ne.get('app_name', '—')}</td>"
            f"<td>{ne.get('platform', '—')}</td>"
            f"<td>{ne.get('developer', '—')}</td>"
            f"<td>{ne.get('category', '—')}</td>"
            f"</tr>\n"
        )

    # Trend reports
    trend_rows = ""
    for tr in trend_reports[:10]:
        trend_rows += (
            f"<tr>"
            f"<td>{tr.get('title', '—')}</td>"
            f"<td>{tr.get('strength', '—')}/10</td>"
            f"<td>{'🔥 Emerging' if tr.get('is_emerging') else '📈 Trending'}</td>"
            f"</tr>\n"
        )

    template = _load_template("index.html")
    # Use replacement instead of .format() to avoid CSS brace conflicts
    replacements = {
        "{competitors_count}": str(len(competitors)),
        "{findings_count}": str(len(findings)),
        "{aso_count}": str(len(aso_changes)),
        "{comp_cards}": comp_cards,
        "{findings_rows}": findings_rows or "<tr><td colspan='5' class='muted'>No findings yet. Run a scan.</td></tr>",
        "{aso_rows}": aso_rows or "<tr><td colspan='5' class='muted'>No ASO changes detected.</td></tr>",
        "{entrant_rows}": entrant_rows or "<tr><td colspan='4' class='muted'>No new entrants detected.</td></tr>",
        "{trend_rows}": trend_rows or "<tr><td colspan='3' class='muted'>No trends detected.</td></tr>",
        "{strategic_html}": strategic_html or "<p class='muted'>No strategic analysis yet. Click <strong>Run Strategic Analysis</strong> below.</p>",
        "{last_updated}": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    for key, val in replacements.items():
        template = template.replace(key, val)
    return template


@app.get("/scan", response_class=HTMLResponse)
async def scan_page():
    """Scan results page."""
    template = _load_template("scan.html")
    return template.replace("{last_updated}", datetime.now().strftime("%Y-%m-%d %H:%M"))


@app.post("/api/scan")
def run_scan():
    """Trigger a scan cycle in a background thread."""
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
def run_analyze():
    """Trigger strategic analysis with Nemotron Ultra."""
    from prysma.agents.analyst import AnalystAgent

    def _run():
        try:
            analyst = AnalystAgent()
            analyst.generate_strategic_analysis()
            analyst.close()
        except Exception as e:
            print(f"Analysis error: {e}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return JSONResponse({"status": "started", "message": "Strategic analysis started. Check back in 2-3 minutes."})


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


@app.get("/api/tavily")
def tavily_search(query: str = Query(..., min_length=2)):
    """Run a Tavily web search."""
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


@app.post("/api/discover")
def discover(body: DiscoverRequest):
    """Find candidate competitors for an app, store link, or idea, then profile them."""
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
        )
        if competitor_id:
            added += 1
    return {"added": added}


@app.post("/api/gaps")
def gaps():
    """Run the market gap analysis with Nemotron Ultra and return the report."""
    from prysma.agents.analyst import AnalystAgent

    analyst = AnalystAgent()
    try:
        report = analyst.generate_gap_analysis()
    finally:
        analyst.close()
    return {"report": report}


def main():
    parser = argparse.ArgumentParser(description="Prysma web dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    args = parser.parse_args()

    print(f"🚀 Prysma web dashboard starting on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
