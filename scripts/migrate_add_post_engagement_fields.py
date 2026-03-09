#!/usr/bin/env python3
"""
Database migration: add post engagement/date fields to search_results.
Run from project root:
    python scripts/migrate_add_post_engagement_fields.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import engine


def migrate():
    migrations = [
        """
        ALTER TABLE search_results
        ADD COLUMN IF NOT EXISTS post_reaction_count INTEGER NULL;
        """,
        """
        ALTER TABLE search_results
        ADD COLUMN IF NOT EXISTS post_comment_count INTEGER NULL;
        """,
        """
        ALTER TABLE search_results
        ADD COLUMN IF NOT EXISTS post_share_count INTEGER NULL;
        """,
        """
        ALTER TABLE search_results
        ADD COLUMN IF NOT EXISTS post_date VARCHAR NULL;
        """,
    ]

    with engine.connect() as conn:
        print("Running post engagement migration...")
        for idx, sql in enumerate(migrations, 1):
            try:
                conn.execute(text(sql))
                conn.commit()
                print(f"  [{idx}] OK")
            except Exception as exc:
                print(f"  [{idx}] Failed: {exc}")
                conn.rollback()
        print("Done.")


if __name__ == "__main__":
    migrate()
