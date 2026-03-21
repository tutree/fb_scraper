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


class CookieUpdateRequest(BaseModel):
    cookie_json: str


class CookieUpdateResponse(BaseModel):
    message: str
    account_uid: str
    cookie_file: str
    cookie_count: int
    updated_at: str
    active_account_uids: List[str] = []
