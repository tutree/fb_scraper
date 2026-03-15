from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from typing import Optional, List


class PostCommentUpdate(BaseModel):
    """All fields optional for partial updates."""
    author_name: Optional[str] = None
    author_profile_url: Optional[str] = None
    comment_text: Optional[str] = None
    comment_timestamp: Optional[str] = None
    user_type: Optional[str] = None  # customer, tutor, unknown
    confidence_score: Optional[float] = None
    analysis_message: Optional[str] = None


class PostCommentResponse(BaseModel):
    id: UUID
    search_result_id: UUID
    author_name: Optional[str] = None
    author_profile_url: Optional[str] = None
    comment_text: Optional[str] = None
    comment_timestamp: Optional[str] = None
    user_type: Optional[str] = None
    confidence_score: Optional[float] = None
    analysis_message: Optional[str] = None
    analyzed_at: Optional[datetime] = None
    scraped_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CommentListResponse(BaseModel):
    total: int
    items: List[PostCommentResponse]


class AnalyzeCommentItem(BaseModel):
    id: UUID
    success: bool
    message: str
    user_type: Optional[str] = None
    confidence_score: Optional[float] = None
    analyzed_at: Optional[datetime] = None


class AnalyzeCommentSingleResponse(BaseModel):
    item: AnalyzeCommentItem


class AnalyzeCommentBatchRequest(BaseModel):
    comment_ids: List[UUID]
    force_reanalyze: bool = True


class AnalyzeCommentBatchResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    skipped: int
    items: List[AnalyzeCommentItem]
