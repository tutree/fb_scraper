#!/usr/bin/env python3
"""
Database migration: drop obsolete post engagement fields from search_results.
Run from project root:
    python scripts/migrate_drop_post_engagement_fields.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.core.database import engine


def migrate():
    migrations = [
        "ALTER TABLE search_results DROP COLUMN IF EXISTS post_reaction_count;",
        "ALTER TABLE search_results DROP COLUMN IF EXISTS post_comment_count;",
        "ALTER TABLE search_results DROP COLUMN IF EXISTS post_share_count;",
    ]

    with engine.connect() as conn:
        print("Dropping obsolete post engagement columns...")
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