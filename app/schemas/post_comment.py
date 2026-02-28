from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from typing import Optional, List


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
