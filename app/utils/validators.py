import re
from typing import Optional


def is_valid_facebook_url(url: str) -> bool:
    """Validate that a URL is a valid Facebook URL."""
    pattern = r"^https?://(www\.)?facebook\.com/.+"
    return bool(re.match(pattern, url))


def sanitize_text(text: Optional[str]) -> Optional[str]:
    """Clean and sanitize scraped text content."""
    if not text:
        return None
    # Remove excessive whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Remove null bytes
    text = text.replace("\x00", "")
    return text


def truncate_text(text: Optional[str], max_length: int = 5000) -> Optional[str]:
    """Truncate text to a maximum length."""
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."
