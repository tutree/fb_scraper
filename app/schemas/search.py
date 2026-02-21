from pydantic import BaseModel
from typing import List, Optional


class SearchRequest(BaseModel):
    keywords: Optional[List[str]] = None  # If None, use default keywords
    max_results: Optional[int] = 100
    use_proxy: bool = True


class SearchResponse(BaseModel):
    task_id: str
    message: str
    status: str
