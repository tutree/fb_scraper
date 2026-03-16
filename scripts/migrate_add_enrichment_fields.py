#!/usr/bin/env python3
"""
Database migration to add EnformionGO contact enrichment fields to search_results.
Run this once to update the database schema.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import engine
from sqlalchemy import text


def migrate():
    migrations = [
        """
        ALTER TABLE search_results
        ADD COLUMN IF NOT EXISTS enriched_phones JSONB;
        """,
        """
        ALTER TABLE search_results
        ADD COLUMN IF NOT EXISTS enriched_emails JSONB;
        """,
        """
        ALTER TABLE search_results
        ADD COLUMN IF NOT EXISTS enriched_addresses JSONB;
        """,
        """
        ALTER TABLE search_results
        ADD COLUMN IF NOT EXISTS enriched_age VARCHAR;
        """,
        """
        ALTER TABLE search_results
        ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMP WITH TIME ZONE;
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_search_results_enriched_at
        ON search_results(enriched_at);
        """,
    ]

    with engine.connect() as conn:
        print("Running enrichment field migrations...")

        for idx, migration in enumerate(migrations, 1):
            try:
                print(f"  [{idx}/{len(migrations)}] Executing migration...")
                conn.execute(text(migration))
                conn.commit()
                print(f"  ✓ Migration {idx} completed")
            except Exception as e:
                print(f"  ✗ Migration {idx} failed: {e}")
                conn.rollback()

        print("\n✓ All enrichment migrations completed!")


if __name__ == "__main__":
    migrate()
