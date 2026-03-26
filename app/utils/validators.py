import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..core.logging_config import get_logger

_logger = get_logger(__name__)


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


def clean_facebook_name(raw: Optional[str]) -> Optional[str]:
    """
    Sanitize a scraped Facebook display name down to FirstName LastName.
    - Strips numbers, emojis, special characters, URLs, email fragments
    - Keeps only alphabetic words (including accented/unicode letters)
    - Returns at most two name parts (first + last)
    - Returns None if nothing usable remains
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    text = text.replace("\xa0", " ")
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\S+@\S+", "", text)
    text = re.sub(r"[^\w\s'-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"[\d_]", " ", text)
    words = text.split()
    name_parts: list[str] = []
    for w in words:
        w = w.strip("'-")
        if not w:
            continue
        if re.fullmatch(r"[\W_]+", w, flags=re.UNICODE):
            continue
        if len(w) == 1 and w.lower() not in "aijo":
            continue
        name_parts.append(w.capitalize())
    if not name_parts:
        return None
    if len(name_parts) > 2:
        name_parts = [name_parts[0], name_parts[-1]]
    return " ".join(name_parts)


def clean_facebook_location(raw: Optional[str]) -> Optional[str]:
    """
    Clean Facebook profile location text.
    Handles multiple location entries separated by commas or newlines.
    Prefers 'Lives in' over 'From' when they point to different places.

    'Lives in Chicago, Illinois, From Tiffin, Ohio' → 'Chicago, Illinois'
    'Lives in Chicago, Illinois, From Chicago, Illinois' → 'Chicago, Illinois'
    'From Winnsboro, Louisiana' → 'Winnsboro, Louisiana'
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()

    _PREFIX = re.compile(r"(?i)^\s*(lives\s+in|moved\s+to|from)\s+", re.MULTILINE)

    chunks: list[str] = re.split(r"(?i)(?=lives\s+in|(?:,\s*)?from\s)", text)
    lives_in: list[str] = []
    from_loc: list[str] = []
    other: list[str] = []

    for chunk in chunks:
        chunk = chunk.strip().strip(",").strip()
        if not chunk:
            continue
        is_lives = bool(re.match(r"(?i)^lives\s+in\b", chunk))
        is_from = bool(re.match(r"(?i)^from\b", chunk))
        cleaned = _PREFIX.sub("", chunk).strip().strip(",").strip()
        if not cleaned:
            continue
        if is_lives:
            lives_in.append(cleaned)
        elif is_from:
            from_loc.append(cleaned)
        else:
            other.append(cleaned)

    best = lives_in or from_loc or other
    if not best:
        text_fallback = re.sub(r"(?i)\b(lives\s+in|moved\s+to|from)\b", ",", text)
        parts = [p.strip() for p in text_fallback.split(",") if p.strip()]
        return ", ".join(parts) if parts else None

    result = best[0]
    parts = [p.strip() for p in result.split(",") if p.strip()]
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


# ---------------------------------------------------------------------------
# Facebook date string → datetime parser
# ---------------------------------------------------------------------------

_SHORT_UNIT_RE = re.compile(r"^(\d+)\s*(s|m|h|d|w|mo|y)$", re.IGNORECASE)

_LONG_UNIT_RE = re.compile(
    r"^(?:about\s+)?(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago$",
    re.IGNORECASE,
)

_A_AN_UNIT_RE = re.compile(
    r"^(?:a|an)\s+(second|minute|hour|day|week|month|year)\s+ago$",
    re.IGNORECASE,
)

_UNIT_TO_HOURS = {
    "s": 0, "second": 0,
    "m": 1 / 60, "minute": 1 / 60,
    "h": 1, "hour": 1,
    "d": 24, "day": 24,
    "w": 168, "week": 168,
    "mo": 720, "month": 720,
    "y": 8760, "year": 8760,
}

_WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_WEEKDAY_AT_RE = re.compile(
    r"^(?:last\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?:,?\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)?)?$",
    re.IGNORECASE,
)

_MONTH_DAY_RE = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(\d{1,2})(?:,?\s+(\d{4}))?"
    r"(?:\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)?)?$",
    re.IGNORECASE,
)

_TOOLTIP_RE = re.compile(
    r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s+"
    r"(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(\d{1,2}),?\s+(\d{4})\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)",
    re.IGNORECASE,
)

_YESTERDAY_RE = re.compile(
    r"^yesterday(?:\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)?)?$",
    re.IGNORECASE,
)


def _parse_time_12h(hour: int, minute: int, ampm: Optional[str]) -> tuple:
    """Convert 12-hour time to 24-hour (hour, minute)."""
    if ampm:
        ap = ampm.lower()
        if ap == "pm" and hour != 12:
            hour += 12
        elif ap == "am" and hour == 12:
            hour = 0
    return hour, minute


def parse_facebook_date(raw: Optional[str], now: Optional[datetime] = None) -> Optional[datetime]:
    """
    Parse a Facebook relative/absolute date string into a UTC datetime.

    Handles:
      - Short codes: "3h", "2d", "1w", "5m", "1y", "30s"
      - Long relative: "3 hours ago", "a week ago", "about 2 months ago"
      - "Just now"
      - "Yesterday at 3:00 PM"
      - Weekday: "Tuesday at 9:00 AM"
      - Month day: "March 4 at 2:30 PM", "March 4, 2025 at 2:30 PM"
      - Tooltip format: "Tuesday, March 17, 2026 at 12:09 AM"

    Returns None if unparseable.
    """
    if not raw or not raw.strip():
        return None

    if now is None:
        now = datetime.now(timezone.utc)

    text = raw.strip()

    # "Just now"
    if text.lower() in ("just now", "now"):
        return now

    # Short codes: "3h", "2d", "1w", "45m", "10s"
    m = _SHORT_UNIT_RE.match(text)
    if m:
        count = int(m.group(1))
        unit = m.group(2).lower()
        hours = count * _UNIT_TO_HOURS.get(unit, 0)
        return now - timedelta(hours=hours)

    # "a week ago", "an hour ago"
    m = _A_AN_UNIT_RE.match(text)
    if m:
        unit = m.group(1).lower()
        hours = _UNIT_TO_HOURS.get(unit, 0)
        return now - timedelta(hours=hours)

    # "3 hours ago", "2 days ago", "about 2 months ago"
    m = _LONG_UNIT_RE.match(text)
    if m:
        count = int(m.group(1))
        unit = m.group(2).lower()
        hours = count * _UNIT_TO_HOURS.get(unit, 0)
        return now - timedelta(hours=hours)

    # "Yesterday" / "Yesterday at 3:00 PM"
    m = _YESTERDAY_RE.match(text)
    if m:
        yesterday = now - timedelta(days=1)
        if m.group(1):
            h, mi = _parse_time_12h(int(m.group(1)), int(m.group(2)), m.group(3))
            yesterday = yesterday.replace(hour=h, minute=mi, second=0, microsecond=0)
        return yesterday

    # Tooltip: "Tuesday, March 17, 2026 at 12:09 AM"
    m = _TOOLTIP_RE.search(text)
    if m:
        month = _MONTH_NAMES.get(m.group(2).lower())
        day = int(m.group(3))
        year = int(m.group(4))
        h, mi = _parse_time_12h(int(m.group(5)), int(m.group(6)), m.group(7))
        try:
            return datetime(year, month, day, h, mi, tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    # Weekday: "Tuesday at 9:00 AM"
    m = _WEEKDAY_AT_RE.match(text)
    if m:
        target_wd = _WEEKDAY_NAMES.get(m.group(1).lower())
        if target_wd is not None:
            current_wd = now.weekday()
            days_back = (current_wd - target_wd) % 7
            if days_back == 0:
                days_back = 7
            result = now - timedelta(days=days_back)
            if m.group(2):
                h, mi = _parse_time_12h(int(m.group(2)), int(m.group(3)), m.group(4))
                result = result.replace(hour=h, minute=mi, second=0, microsecond=0)
            return result

    # "March 4 at 2:30 PM" or "March 4, 2025 at 2:30 PM"
    m = _MONTH_DAY_RE.match(text)
    if m:
        month = _MONTH_NAMES.get(m.group(1).lower())
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        h, mi = 12, 0
        if m.group(4):
            h, mi = _parse_time_12h(int(m.group(4)), int(m.group(5)), m.group(6))
        try:
            result = datetime(year, month, day, h, mi, tzinfo=timezone.utc)
            if result > now and not m.group(3):
                result = result.replace(year=year - 1)
            return result
        except (ValueError, TypeError):
            pass

    _logger.debug("Could not parse Facebook date: %r", raw)
    return None


_US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
}

_US_STATE_ABBREVS = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
}

_US_KEYWORDS = {"united states", "usa", "u.s.a.", "u.s."}


def is_us_location(location: Optional[str]) -> bool:
    """Check if a Facebook location string refers to a US location."""
    if not location or not location.strip():
        return False
    loc = location.strip().lower()

    for kw in _US_KEYWORDS:
        if kw in loc:
            return True

    parts = [p.strip() for p in re.split(r"[,·\-/]", loc) if p.strip()]
    for part in parts:
        if part in _US_STATES or part in _US_STATE_ABBREVS:
            return True

    return False


def coerce_is_us_boolean(value) -> bool:
    """
    Normalize LLM/API ``is_us`` to bool. True = US-based.
    Missing or ambiguous values default to True (conservative: do not delete).
    String \"false\" / \"0\" must become False (``bool(\"false\")`` is True in Python).
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("false", "0", "no", "n"):
        return False
    if s in ("true", "1", "yes", "y"):
        return True
    return True


def is_enrichable(name: Optional[str], location: Optional[str]) -> bool:
    """Check if a result has a full name (2+ parts) and a US location."""
    if not name or not name.strip():
        return False
    if len(name.strip().split()) < 2:
        return False
    return is_us_location(location)
