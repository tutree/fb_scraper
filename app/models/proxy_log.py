from sqlalchemy import Column, String, DateTime, Integer, Boolean
from sqlalchemy.sql import func
import uuid
from ..core.database import Base


class ProxyLog(Base):
    __tablename__ = "proxy_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    proxy_url = Column(String, unique=True, nullable=False)
    success_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    last_used = Column(DateTime(timezone=True), default=func.now())
    is_active = Column(Boolean, default=True)
