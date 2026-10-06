# Prysma — AI-Powered Competitive Intelligence Agent

**Nebius x NVIDIA Global AI Hackathon 2026**

Prysma is a multi-agent competitive intelligence platform that monitors your competitive landscape, detects market changes, and delivers actionable strategic analysis — powered by NVIDIA Nemotron models on Nebius Token Factory.

## What it does

Point Prysma at any app market (or any set of competitors) and it will:

- **Scout** — Monitors competitor websites, RSS feeds, and news via Tavily web search
- **Competitive Intel** — Tracks app store listings (Google Play + Apple App Store) for ASO changes, pricing moves, rating shifts, and new version releases
- **Trend Radar** — Scans GitHub, Reddit, and news for emerging trends before they peak
- **Analyst** — Uses NVIDIA Nemotron models to classify findings, generate per-finding analysis, and produce strategic synthesis
- **Reporter** — Delivers daily digests, competitive reports, and alerts to Telegram

## Nemotron model tiering

Prysma uses three tiers of NVIDIA Nemotron on Nebius Token Factory:

| Tier | Model | Role |
|------|-------|------|
| **Nano** | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Fast per-finding classification (pricing change, product launch, hiring, etc.) |
| **Super** | `nvidia/nemotron-3-super-120b-a12b` | Default per-finding analysis — what changed, why it matters, importance score |
| **Ultra** | `nvidia/Nemotron-3-Ultra-550b-a55b` | Deep strategic synthesis across all findings — market gaps, competitive threats, recommended actions |

This tiering keeps the app responsive and credits efficient: Nano handles the high-volume classification calls, Super handles the per-finding analysis, and Ultra is reserved for the `/analyze` strategic synthesis command.

## Tavily integration

Prysma uses [Tavily](https://tavily.com) for web search — the Scout agent queries Tavily for recent news and updates about each competitor, and the `/tavily` Telegram command lets you run ad-hoc market searches. Tavily results are sanitized through the same prompt injection defense layer as all other scraped content.

## Security

All external content is sanitized before reaching the AI:

- **Prompt injection defense** — Scraped content is checked against suspicious pattern lists (jailbreak attempts, instruction overrides, script injection) and isolated between delimiters in the model prompt
- **Content sanitization** — HTML comments, script tags, style tags, hidden elements, and zero-width characters are stripped
- **User input validation** — Telegram commands are length-limited and checked for injection patterns
- **Rate limiting** — Per-user request limits prevent abuse
- **Authorization** — Only users in `TELEGRAM_ALLOWED_USERS` can interact with the bot

## Quick start

```bash
# 1. Clone and install
git clone <repo-url>
cd prysma
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your API keys:
#   TELEGRAM_BOT_TOKEN    — from @BotFather
#   TELEGRAM_ALLOWED_USERS — your numeric Telegram user ID (from @userinfobot)
#   NEBIUS_API_KEY        — from https://tokenfactory.nebius.com/project/api-keys
#   TAVILY_API_KEY        — from https://tavily.com (optional but recommended)

# 3. Initialize database and seed default competitors
python -m prysma.storage.migrations --seed

# 4. Run a scan
python -m prysma.main --mode scan

# 5. Start the Telegram bot
python -m prysma.main --mode bot
```

## Usage

### Telegram commands

| Command | Description |
|---------|-------------|
| `/watch <name> --android=<pkg> --ios=<id>` | Add a competitor to monitor (store IDs optional) |
| `/unwatch <name>` | Stop monitoring a competitor |
| `/list` | Show all watched competitors |
| `/scan` | Run a scan cycle now |
| `/digest` | Get today's digest |
| `/analyze` | Strategic analysis using Nemotron Ultra (market gaps, threats, actions) |
| `/tavily <query>` | Web search via Tavily |
| `/trends [vertical]` | Show emerging trends (tech / fitness / finance) |
| `/insights <name>` | Actionable insights for a competitor |
| `/report <name>` | Generate and send a PDF report |
| `/dashboard` | Visual dashboard charts |
| `/eli5 <query>` | Explain like I'm 5 |
| `/actionplan` | Weekly action plan |
| `/status` | System status |
| `/help` | Show help |

### CLI modes

```bash
python -m prysma.main --mode scan        # Run a single scan cycle
python -m prysma.main --mode bot         # Start Telegram bot (polling)
python -m prysma.main --mode digest      # Send daily digest to Telegram
python -m prysma.main --mode competitive # Run competitive intelligence scan
python -m prysma.main --mode trends       # Generate trend report
python -m prysma.main --mode dashboard    # Generate dashboard charts
python -m prysma.main --mode report --target <name>  # Generate PDF report
python -m prysma.main --mode analyze      # Strategic analysis via Nemotron Ultra
```

## Architecture

```
┌─────────────┐    ┌──────────────┐    ┌───────────────┐    ┌─────────────┐
│  Tavily API │    │  Web / RSS   │    │  App Stores   │    │  GitHub     │
│  (search)   │    │  (scrape)    │    │  (Play/iOS)   │    │  Reddit     │
└──────┬──────┘    └──────┬───────┘    └──────┬────────┘    └──────┬──────┘
       │                  │                   │                   │
       ▼                  ▼                   ▼                   ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                        Scout Agent                                  │
  │  TavilySource  •  WebScraper  •  CompetitiveIntelAgent  •  RSS     │
  └────────────────────────────┬────────────────────────────────────────┘
                               │ findings
                               ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                    SQLite Database (prysma.db)                      │
  │  competitors • findings • trend_signals • app_store_listings •     │
  │  aso_changes • competitor_reviews • new_entrants • pricing_history  │
  └────────────────────────────┬────────────────────────────────────────┘
                               │
                               ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                    Analyst Agent                                     │
  │  Nano: classify  →  Super: analyze  →  Ultra: strategic synthesis   │
  │           (Nebius Token Factory API)                                │
  └────────────────────────────┬────────────────────────────────────────┘
                               │
                               ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                   Reporter Agent → Telegram                         │
  │  Daily digests • Competitive reports • Alerts • PDF reports         │
  └─────────────────────────────────────────────────────────────────────┘
```

## Project structure

```
prysma/
├── agents/
│   ├── scout.py              # Web monitoring + Tavily search
│   ├── analyst.py            # Nemotron tiering (Nano/Super/Ultra)
│   ├── competitive_intel.py # App store ASO, reviews, pricing, new entrants
│   ├── trend_radar.py        # Emerging trend detection (GitHub, Reddit, news)
│   └── reporter.py           # Telegram delivery
├── sources/
│   ├── base.py              # Base source class
│   ├── rss.py               # RSS feed source
│   └── tavily_search.py     # Tavily web search integration
├── storage/
│   ├── database.py          # SQLite schema + all queries
│   └── migrations.py         # DB init + seed data
├── telegram/
│   └── bot.py               # Telegram bot (authorized users only)
├── security.py              # Prompt injection defense + content sanitization
├── config.py                # Environment configuration
├── dashboard.py             # matplotlib charts
├── insights.py             # Actionable insights engine
├── reports.py               # PDF report generator
└── main.py                  # CLI entry point
```

## Nebius Token Factory

Prysma runs on [Nebius Token Factory](https://tokenfactory.nebius.com), which provides an OpenAI-compatible API for serving NVIDIA open source models. The base URL is:

```
https://api.tokenfactory.nebius.com/v1/
```

All model calls go through the `AnalystAgent._chat()` method, which handles:
- Standard chat completions
- Reasoning models that put output in a `reasoning` field instead of `content` (Nano)
- Fallback to keyword-based classification when the API is unavailable

## License

MIT
