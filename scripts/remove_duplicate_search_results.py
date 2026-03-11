#!/usr/bin/env python3
"""
Remove duplicate rows from search_results (scraped posts table).
Duplicates are identified by full name match; keeps the earliest row per name (by scraped_at, then id).
Rows with NULL or empty name are left unchanged.
Run from project root: python scripts/remove_duplicate_search_results.py
Or in Docker: docker compose run --rm api python scripts/remove_duplicate_search_results.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal


def remove_duplicates(dry_run: bool = True):
    """
    Delete duplicate search_results, keeping one per name (full name match).
    Keeps the earliest by scraped_at, then id. When dry_run is True, only print; no changes.
    """
    db = SessionLocal()
    try:
        # Ids to delete: duplicate name rows that are not the one we keep (rn > 1).
        ids_to_delete_sql = """
            SELECT id FROM (
                SELECT id,
                    ROW_NUMBER() OVER (
                        PARTITION BY TRIM(name)
                        ORDER BY scraped_at ASC NULLS LAST, id
                    ) AS rn
                FROM search_results
                WHERE name IS NOT NULL AND TRIM(name) != ''
            ) t
            WHERE rn > 1
        """
        if dry_run:
            result = db.execute(text(f"SELECT COUNT(*) FROM ({ids_to_delete_sql}) x"))
            to_delete = result.scalar()
            dup_groups = db.execute(text("""
                SELECT TRIM(name), COUNT(*) AS cnt
                FROM search_results
                WHERE name IS NOT NULL AND TRIM(name) != ''
                GROUP BY TRIM(name)
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC
            """)).fetchall()
            print("DRY RUN - no changes made")
            print(f"Duplicate name groups: {len(dup_groups)}")
            print(f"Rows that would be deleted: {to_delete}")
            if dup_groups:
                print("\nSample duplicate groups (name, count):")
                for row in dup_groups[:10]:
                    print(f"  {row[1]}x  {row[0]!r}")
            return to_delete

        result = db.execute(text(f"DELETE FROM search_results WHERE id IN ({ids_to_delete_sql})"))
        deleted = result.rowcount
        db.commit()
        print(f"Deleted {deleted} duplicate row(s).")
        return deleted
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Remove duplicate search_results by full name")
    parser.add_argument("--execute", action="store_true", help="Actually delete (default is dry-run)")
    args = parser.parse_args()
    remove_duplicates(dry_run=not args.execute)
