from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class SearchRequest(BaseModel):
    keywords: Optional[List[str]] = None  # If None, use default keywords
    max_results: Optional[int] = Field(
        default=None,
        ge=1,
        le=500,
        description="Max profiles per keyword; omit to use MAX_RESULTS_PER_KEYWORD from settings (default 30)",
    )
    use_proxy: bool = True


class SearchResponse(BaseModel):
    task_id: str
    message: str
    status: str


class SearchTaskDetail(BaseModel):
    task_id: Optional[str] = None
    status: str
    message: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    stop_requested: bool = False
    requested_keywords: Optional[List[str]] = None
    requested_max_results: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class SearchStopResponse(BaseModel):
    task_id: Optional[str] = None
    status: str
    message: str


class SearchLogsResponse(BaseModel):
    lines: List[str]


class CookieStatusResponse(BaseModel):
    active_account_uids: List[str] = []
    saved_cookie_uids: List[str] = []
    latest_cookie_uid: Optional[str] = None
    cookie_file: Optional[str] = None
    updated_at: Optional[str] = None
    cookie_count: int = 0
    has_valid_cookies: bool = False
    sessions_with_cookies: int = 0
    total_cookie_entries: int = 0


class ScraperHealthResponse(BaseModel):
    has_cookie_files: bool = False
    cookie_count: int = 0
    cookie_file_age_hours: Optional[float] = None
    all_cookies_failed: bool = False
    all_cookies_failed_at: Optional[str] = None
    last_cookie_ok_uid: Optional[str] = None
    last_cookie_ok_at: Optional[str] = None
    last_cookie_fail_reason: Optional[str] = None
    last_scrape_success: Optional[bool] = None
    last_scrape_error: Optional[str] = None
    level: str = "ok"
    message: str = "Scraper healthy"


class CookieUpdateRequest(BaseModel):
    cookie_json: str
    slot: Optional[int] = Field(
        None,
        ge=1,
        le=4,
        description="Dashboard Account tab 1–4: binds this UID to that slot for scrape order and proxy index",
    )


class ScrapeSlotsResponse(BaseModel):
    """bindings[i] = UID saved from Account tab i+1. Proxies: set PROXY_LIST in .env (comma-separated)."""

    bindings: List[str] = []


class CookieUpdateResponse(BaseModel):
    message: str
    account_uid: str
    cookie_file: str
    cookie_count: int
    updated_at: str
    active_account_uids: List[str] = []


class AccountProxiesResponse(BaseModel):
    """uid -> proxy URL (e.g. socks5://user:pass@host:port)."""

    proxies: Dict[str, str]


class AccountProxySetRequest(BaseModel):
    uid: str = Field(..., min_length=1)
    proxy_url: str = Field(
        "",
        description="Full proxy URL; empty string removes the mapping for this uid",
    )
