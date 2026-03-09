from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class SearchRequest(BaseModel):
    keywords: Optional[List[str]] = None  # If None, use default keywords
    max_results: Optional[int] = 100
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
