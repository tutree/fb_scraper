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
    post_date: Optional[str] = None
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
    user_type: Optional[str] = None
    confidence_score: Optional[float] = None
    analysis_message: Optional[str] = None
    analyzed_at: Optional[datetime] = None
    scraped_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SearchResultList(BaseModel):
    total: int
    items: List[SearchResultResponse]


class AnalyzeResultItem(BaseModel):
    id: UUID
    success: bool
    message: str
    user_type: Optional[str] = None
    confidence_score: Optional[float] = None
    analyzed_at: Optional[datetime] = None


class AnalyzeSingleResponse(BaseModel):
    item: AnalyzeResultItem


class AnalyzeBatchRequest(BaseModel):
    result_ids: List[UUID]
    force_reanalyze: bool = True


class AnalyzeBatchResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    skipped: int
    items: List[AnalyzeResultItem]
