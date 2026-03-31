"""
Lightweight in-memory tracker for scraper runtime health.

Other modules call the ``report_*`` helpers; the ``/search/scraper-health``
endpoint reads the state via ``get_scraper_health()``.
"""
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_lock = threading.Lock()

_state: Dict[str, Any] = {
    "last_cookie_ok_uid": None,
    "last_cookie_ok_at": None,
    "last_cookie_fail_uid": None,
    "last_cookie_fail_at": None,
    "last_cookie_fail_reason": None,
    "all_cookies_failed": False,
    "all_cookies_failed_at": None,
    "last_scrape_started_at": None,
    "last_scrape_finished_at": None,
    "last_scrape_success": None,
    "last_scrape_error": None,
    "active_keyword": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def report_cookie_ok(uid: str) -> None:
    with _lock:
        _state["last_cookie_ok_uid"] = uid
        _state["last_cookie_ok_at"] = _now()
        _state["all_cookies_failed"] = False
        _state["all_cookies_failed_at"] = None


def report_cookie_fail(uid: str, reason: str = "") -> None:
    with _lock:
        _state["last_cookie_fail_uid"] = uid
        _state["last_cookie_fail_at"] = _now()
        _state["last_cookie_fail_reason"] = reason


def report_all_cookies_failed() -> None:
    with _lock:
        _state["all_cookies_failed"] = True
        _state["all_cookies_failed_at"] = _now()


def clear_all_cookies_failed() -> None:
    """Reset stale 'all sessions failed' when valid cookie files exist again."""
    with _lock:
        _state["all_cookies_failed"] = False
        _state["all_cookies_failed_at"] = None


def report_scrape_start(keyword: Optional[str] = None) -> None:
    with _lock:
        _state["last_scrape_started_at"] = _now()
        _state["active_keyword"] = keyword


def report_scrape_finish(success: bool, error: Optional[str] = None) -> None:
    with _lock:
        _state["last_scrape_finished_at"] = _now()
        _state["last_scrape_success"] = success
        _state["last_scrape_error"] = error
        _state["active_keyword"] = None


def get_scraper_health() -> Dict[str, Any]:
    """Return a snapshot of the current scraper health state."""
    with _lock:
        return dict(_state)
