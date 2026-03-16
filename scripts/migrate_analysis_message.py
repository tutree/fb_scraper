#!/usr/bin/env python3
"""
Add analysis_message (TEXT) column only. No backfill (avoids long-running UPDATE/locks).
Run from project root: python scripts/migrate_analysis_message.py
Or in Docker: docker compose run --rm api python scripts/migrate_analysis_message.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import engine
from sqlalchemy import text


def migrate():
    steps = [
        ("Add analysis_message to search_results", "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS analysis_message TEXT NULL"),
        ("Add analysis_message to post_comments", "ALTER TABLE post_comments ADD COLUMN IF NOT EXISTS analysis_message TEXT NULL"),
    ]
    for name, sql in steps:
        try:
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            print(f"  OK: {name}")
        except Exception as e:
            print(f"  Failed: {name}: {e}")
    print("Done.")


if __name__ == "__main__":
    migrate()
