"""Configuration loader for Prysma."""
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

DEFAULT_MODEL_NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
DEFAULT_MODEL_SUPER = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_MODEL_ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"
DEFAULT_NEW_ENTRANT_KEYWORDS = "round timer,boxing timer,HIIT timer,interval timer,Tabata timer,workout timer"

class Config(BaseModel):
    telegram_bot_token: str = ""
    telegram_allowed_users: str = ""
    nebius_api_key: str = ""
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    nebius_model: str = DEFAULT_MODEL_SUPER
    nebius_model_nano: str = DEFAULT_MODEL_NANO
    nebius_model_super: str = DEFAULT_MODEL_SUPER
    nebius_model_ultra: str = DEFAULT_MODEL_ULTRA
    tavily_api_key: str = ""
    newsapi_key: str = ""
    github_token: str = ""
    database_path: str = "data/prysma.db"
    new_entrant_keywords: list[str] = []
    scan_interval_hours: int = 6
    max_content_length: int = 5000
    max_findings_per_digest: int = 10
    trend_signal_threshold: int = 3
    trend_lookback_days: int = 30
    max_requests_per_minute: int = 10

config = Config(
    telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
    telegram_allowed_users=os.getenv("TELEGRAM_ALLOWED_USERS", ""),
    nebius_api_key=os.getenv("NEBIUS_API_KEY", ""),
    nebius_base_url=os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1").rstrip("/"),
    nebius_model=os.getenv("NEBIUS_MODEL", DEFAULT_MODEL_SUPER),
    nebius_model_nano=os.getenv("NEBIUS_MODEL_NANO", DEFAULT_MODEL_NANO),
    nebius_model_super=os.getenv("NEBIUS_MODEL_SUPER", DEFAULT_MODEL_SUPER),
    nebius_model_ultra=os.getenv("NEBIUS_MODEL_ULTRA", DEFAULT_MODEL_ULTRA),
    tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
    newsapi_key=os.getenv("NEWSAPI_KEY", ""),
    github_token=os.getenv("GITHUB_TOKEN", ""),
    database_path=os.getenv("DATABASE_PATH", "data/prysma.db"),
    new_entrant_keywords=[
        k.strip()
        for k in os.getenv("NEW_ENTRANT_KEYWORDS", DEFAULT_NEW_ENTRANT_KEYWORDS).split(",")
        if k.strip()
    ],
    scan_interval_hours=int(os.getenv("SCAN_INTERVAL_HOURS", "6")),
    max_content_length=int(os.getenv("MAX_CONTENT_LENGTH", "5000")),
    max_findings_per_digest=int(os.getenv("MAX_FINDINGS_PER_DIGEST", "10")),
    trend_signal_threshold=int(os.getenv("TREND_SIGNAL_THRESHOLD", "3")),
    trend_lookback_days=int(os.getenv("TREND_LOOKBACK_DAYS", "30")),
    max_requests_per_minute=int(os.getenv("MAX_REQUESTS_PER_MINUTE", "10")),
)
