from sqlalchemy import Column, String, DateTime, Text, Enum, Index, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
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
    post_date = Column(String, nullable=True)
    search_keyword = Column(String, nullable=False)
    source = Column(String, default="facebook")
    status = Column(Enum(ResultStatus), default=ResultStatus.PENDING)
    profile_url = Column(String, nullable=True)
    
    # AI classification fields
    user_type = Column(Enum(UserType, values_callable=lambda x: [e.value for e in x]), nullable=True)
    confidence_score = Column(Float, nullable=True)  # 0-1 confidence
    analysis_message = Column(Text, nullable=True)  # Reason text from AI (no raw JSON)
    analyzed_at = Column(DateTime(timezone=True), nullable=True)

    # EnformionGO contact enrichment fields
    enriched_phones = Column(JSONB, nullable=True)     # [{"number","type","is_connected"}]
    enriched_emails = Column(JSONB, nullable=True)     # ["email@example.com", ...]
    enriched_addresses = Column(JSONB, nullable=True)  # [{"street","city","state","zip","unit"}]
    enriched_age = Column(String, nullable=True)
    enriched_at = Column(DateTime(timezone=True), nullable=True)
    
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship to comments
    comments = relationship("PostComment", back_populates="search_result", cascade="all, delete-orphan")

    # Indexes for better query performance
    __table_args__ = (
        Index("idx_search_results_scraped_at", scraped_at),
        Index("idx_search_results_status", status),
        Index("idx_search_results_keyword", search_keyword),
        Index("idx_search_results_user_type", user_type),
        Index("idx_search_results_analyzed_at", analyzed_at),
    )

