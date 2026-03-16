from sqlalchemy import Column, String, Text, Integer, JSON, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from ..core.database import Base

class PersonDetails(Base):
    __tablename__ = "person_details"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String, nullable=False, index=True)
    age = Column(String, nullable=True)
    current_address = Column(Text, nullable=True)
    phone_numbers = Column(JSON, nullable=True)  # List of strings
    relatives = Column(JSON, nullable=True)      # List of strings
    email = Column(String, nullable=True)
    profile_url = Column(String, unique=True, index=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
