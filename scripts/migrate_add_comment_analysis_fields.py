#!/usr/bin/env python3
"""
Database migration: add analysis fields to post_comments.
Requires usertype enum to exist (from migrate_add_gemini_fields.py).
Run from project root: python scripts/migrate_add_comment_analysis_fields.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import engine
from sqlalchemy import text


def migrate():
    migrations = [
        """
        ALTER TABLE post_comments
        ADD COLUMN IF NOT EXISTS user_type usertype NULL;
        """,
        """
        ALTER TABLE post_comments
        ADD COLUMN IF NOT EXISTS gemini_analysis JSONB NULL;
        """,
        """
        ALTER TABLE post_comments
        ADD COLUMN IF NOT EXISTS confidence_score FLOAT NULL;
        """,
        """
        ALTER TABLE post_comments
        ADD COLUMN IF NOT EXISTS analyzed_at TIMESTAMP WITH TIME ZONE NULL;
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_post_comments_user_type
        ON post_comments(user_type);
        """,
    ]
    with engine.connect() as conn:
        print("Running comment analysis migration...")
        for idx, sql in enumerate(migrations, 1):
            try:
                conn.execute(text(sql))
                conn.commit()
                print(f"  [{idx}] OK")
            except Exception as e:
                print(f"  [{idx}] Failed: {e}")
                conn.rollback()
        print("Done.")


if __name__ == "__main__":
    migrate()
