from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from typing import Optional, List
from ..models.search_result import ResultStatus


class SearchResultBase(BaseModel):
    name: str
    location: Optional[str] = None
    post_content: Optional[str] = None
    post_url: Optional[str] = None
    search_keyword: str
    profile_url: Optional[str] = None


class SearchResultCreate(SearchResultBase):
    pass


class SearchResultUpdate(BaseModel):
    status: Optional[ResultStatus] = None


class SearchResultResponse(SearchResultBase):
    id: UUID
    source: str
    status: ResultStatus
    scraped_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SearchResultList(BaseModel):
    total: int
    items: List[SearchResultResponse]
