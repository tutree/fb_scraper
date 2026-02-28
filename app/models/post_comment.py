from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Index, Enum, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from ..core.database import Base
from .search_result import UserType


class PostComment(Base):
    __tablename__ = "post_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_result_id = Column(UUID(as_uuid=True), ForeignKey('search_results.id', ondelete='CASCADE'), nullable=False)
    
    author_name = Column(String, nullable=True)
    author_profile_url = Column(String, nullable=True)
    comment_text = Column(Text, nullable=True)
    comment_timestamp = Column(String, nullable=True)  # Facebook's relative time like "2h" or "3d"
    
    # Analysis: classify comment author as potential customer or tutor (set by analyzer)
    user_type = Column(Enum(UserType, values_callable=lambda x: [e.value for e in x]), nullable=True)
    confidence_score = Column(Float, nullable=True)  # 0-1
    analysis_message = Column(Text, nullable=True)  # Reason text from Gemini (no raw JSON)
    analyzed_at = Column(DateTime(timezone=True), nullable=True)
    
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship back to search result
    search_result = relationship("SearchResult", back_populates="comments")

    # Indexes for better query performance
    __table_args__ = (
        Index("idx_post_comments_search_result_id", search_result_id),
        Index("idx_post_comments_scraped_at", scraped_at),
        Index("idx_post_comments_user_type", user_type),
    )
