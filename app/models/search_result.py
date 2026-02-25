from sqlalchemy import Column, String, DateTime, Text, Enum, Integer, Index, Float, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
import enum
from ..core.database import Base


class ResultStatus(str, enum.Enum):
    PENDING = "pending"
    CONTACTED = "contacted"
    NOT_INTERESTED = "not_interested"
    INVALID = "invalid"


class UserType(str, enum.Enum):
    CUSTOMER = "customer"  # Looking for tutor
    TUTOR = "tutor"  # Offering tutoring
    UNKNOWN = "unknown"  # Unclear or irrelevant


class SearchResult(Base):
    __tablename__ = "search_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    location = Column(String, nullable=True)
    post_content = Column(Text, nullable=True)
    post_url = Column(String, nullable=True)  # Removed unique constraint
    search_keyword = Column(String, nullable=False)
    source = Column(String, default="facebook")
    status = Column(Enum(ResultStatus), default=ResultStatus.PENDING)
    profile_url = Column(String, nullable=True)
    
    # Gemini AI classification fields
    user_type = Column(Enum(UserType), nullable=True)
    gemini_analysis = Column(JSON, nullable=True)  # Full Gemini response
    confidence_score = Column(Float, nullable=True)  # 0-1 confidence
    analyzed_at = Column(DateTime(timezone=True), nullable=True)
    
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Indexes for better query performance
    __table_args__ = (
        Index("idx_search_results_scraped_at", scraped_at),
        Index("idx_search_results_status", status),
        Index("idx_search_results_keyword", search_keyword),
        Index("idx_search_results_user_type", user_type),
        Index("idx_search_results_analyzed_at", analyzed_at),
    )

