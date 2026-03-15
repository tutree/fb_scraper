import re
from typing import Optional


def is_valid_facebook_url(url: str) -> bool:
    """Validate that a URL is a valid Facebook URL."""
    pattern = r"^https?://(www\.)?facebook\.com/.+"
    return bool(re.match(pattern, url))


_FB_UI_NOISE = re.compile(
    r"^("
    r"Facebook|Faceb\.{0,3}|Log\s*In|Sign\s*Up|See\s*more|"
    r"Like|Comment|Share|Send|"
    r"All\s*reactions[:\s]*\d*|"
    r"\d+\s*comments?|"
    r"\d+\s*shares?|"
    r"\d+\s*likes?|"
    r"Most\s*relevant|Newest\s*first|All\s*comments|"
    r"Write\s*a\s*comment.*|"
    r"Press\s*enter\s*to\s*post.*|"
    r"·|Follow|Suggested\s*for\s*you|"
    r"Sponsored|"
    r"Photo|Video|Reel|Live"
    r")$",
    re.IGNORECASE,
)

_FB_TIMESTAMP_NOISE = re.compile(
    r"^\d+\s*[smhdwy]$|"
    r"^just\s*now$|"
    r"^yesterday$|"
    r"^\d+\s*(?:min|mins|minutes?|hrs?|hours?|days?|weeks?|months?|years?)\s*(?:ago)?$",
    re.IGNORECASE,
)


def clean_facebook_post_content(text: Optional[str]) -> Optional[str]:
    """
    Strip Facebook UI chrome, repeated noise words, and navigation artifacts
    from scraped post content, returning only the actual user-written text.
    """
    if not text:
        return None

    text = text.replace("\x00", "")

    lines = [line.strip() for line in text.splitlines()]

    cleaned: list[str] = []
    prev_line = ""
    for line in lines:
        if not line:
            continue
        if _FB_UI_NOISE.match(line):
            continue
        if _FB_TIMESTAMP_NOISE.match(line):
            continue
        if line == prev_line:
            continue
        cleaned.append(line)
        prev_line = line

    result = " ".join(cleaned)
    result = re.sub(r"\s+", " ", result).strip()

    if not result:
        return None

    return result


def clean_facebook_location(raw: Optional[str]) -> Optional[str]:
    """
    Clean Facebook profile location text.
    'Lives in Chicago, Illinois, From Tiffin, Ohio' → 'Chicago, Illinois, Tiffin, Ohio'
    'From Winnsboro, Louisiana' → 'Winnsboro, Louisiana'
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    text = re.sub(r"(?i)\b(lives\s+in|moved\s+to|from)\b", ",", text)
    parts = [p.strip() for p in text.split(",") if p.strip()]
    seen: list[str] = []
    for p in parts:
        if p.lower() not in [s.lower() for s in seen]:
            seen.append(p)
    return ", ".join(seen) if seen else None


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
