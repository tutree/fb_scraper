from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from typing import Any, Optional, List
from ..models.search_result import ResultStatus


class SearchResultBase(BaseModel):
    name: str
    location: Optional[str] = None
    post_content: Optional[str] = None
    post_url: Optional[str] = None
    post_date: Optional[str] = None
    post_date_timestamp: Optional[datetime] = None
    search_keyword: str
    profile_url: Optional[str] = None


class SearchResultCreate(SearchResultBase):
    pass


class SearchResultUpdate(BaseModel):
    """All fields optional for partial updates."""
    name: Optional[str] = None
    location: Optional[str] = None
    post_content: Optional[str] = None
    post_url: Optional[str] = None
    post_date: Optional[str] = None
    post_date_timestamp: Optional[datetime] = None
    search_keyword: Optional[str] = None
    profile_url: Optional[str] = None
    status: Optional[ResultStatus] = None
    user_type: Optional[str] = None  # customer, tutor, unknown
    confidence_score: Optional[float] = None
    analysis_message: Optional[str] = None


class SearchResultResponse(SearchResultBase):
    id: UUID
    source: str
    status: ResultStatus
    user_type: Optional[str] = None
    confidence_score: Optional[float] = None
    analysis_message: Optional[str] = None
    analyzed_at: Optional[datetime] = None
    enriched_phones: Optional[List[Any]] = None
    enriched_emails: Optional[List[str]] = None
    enriched_addresses: Optional[List[Any]] = None
    enriched_age: Optional[str] = None
    enriched_at: Optional[datetime] = None
    scraped_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SearchResultList(BaseModel):
    total: int
    items: List[SearchResultResponse]


class RecentProcessedItem(BaseModel):
    """Minimal fields for Jobs page 'Last processed' tables."""
    id: UUID
    name: str
    search_keyword: str
    post_url: Optional[str] = None
    location: Optional[str] = None
    user_type: Optional[str] = None
    scraped_at: Optional[datetime] = None
    analyzed_at: Optional[datetime] = None
    enriched_at: Optional[datetime] = None


# --- Analysis schemas ---

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


# --- Enrichment schemas ---

class EnrichResultItem(BaseModel):
    id: UUID
    success: bool
    message: str
    enriched_phones: Optional[List[Any]] = None
    enriched_emails: Optional[List[str]] = None
    enriched_addresses: Optional[List[Any]] = None
    enriched_age: Optional[str] = None
    enriched_at: Optional[datetime] = None


class EnrichSingleResponse(BaseModel):
    item: EnrichResultItem


class EnrichBatchRequest(BaseModel):
    result_ids: List[UUID]
    force_re_enrich: bool = False


class EnrichBatchResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    skipped: int
    items: List[EnrichResultItem]
