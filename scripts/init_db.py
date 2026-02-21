"""Database initialization script.

Creates all tables defined by SQLAlchemy models.
Run: python scripts/init_db.py
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine, Base
from app.models.search_result import SearchResult  # noqa: F401
from app.models.proxy_log import ProxyLog  # noqa: F401


def init_db():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully!")


if __name__ == "__main__":
    init_db()
