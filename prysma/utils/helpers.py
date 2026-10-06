"""Utility functions for Prysma."""
import hashlib
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse


def hash_content(content: str) -> str:
    """Generate SHA256 hash of content."""
    return hashlib.sha256(content.encode()).hexdigest()


def normalize_url(url: str) -> str:
    """Normalize URL for consistent comparison."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip('/')


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    parsed = urlparse(url)
    return parsed.netloc


def truncate_text(text: str, max_length: int = 500, suffix: str = '...') -> str:
    """Truncate text to max length."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def format_timestamp(dt: datetime) -> str:
    """Format datetime for display."""
    return dt.strftime('%Y-%m-%d %H:%M')


def extract_mentions(text: str, keywords: list[str]) -> list[str]:
    """Extract keyword mentions from text."""
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def is_valid_url(url: str) -> bool:
    """Check if URL is valid."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False


def clean_text(text: str) -> str:
    """Clean text by removing extra whitespace."""
    return re.sub(r'\s+', ' ', text).strip()
