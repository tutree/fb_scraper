#!/usr/bin/env python3
"""
Archive duplicate rows in search_results (soft-hide from API).

Duplicates are identified by (trimmed name + trimmed location). NULL or blank
location is treated as empty string. Keeps the earliest row per pair (by scraped_at,
then id). Sets archived=true on duplicate leads and on their post_comments. Archived
rows are excluded from all dashboard/API queries.

Run from project root: python scripts/remove_duplicate_search_results.py
Or in Docker: docker compose run --rm api python scripts/remove_duplicate_search_results.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal
from app.models.search_result import SearchResult
from app.models.post_comment import PostComment


def archive_duplicates(dry_run: bool = True):
    """
    Archive duplicate search_results, keeping one per (name + location) pair.
    Keeps the earliest by scraped_at, then id. When dry_run is True, only print.
    """
    db = SessionLocal()
    try:
        dup_sql = """
            SELECT id FROM (
                SELECT id,
                    ROW_NUMBER() OVER (
                        PARTITION BY TRIM(name), TRIM(COALESCE(location, ''))
                        ORDER BY scraped_at ASC NULLS LAST, id
                    ) AS rn
                FROM search_results
                WHERE archived = false
                  AND name IS NOT NULL AND TRIM(name) != ''
            ) t WHERE rn > 1
        """
        if dry_run:
            result = db.execute(text(f"SELECT COUNT(*) FROM ({dup_sql}) x"))
            to_archive = result.scalar()
            dup_groups = db.execute(
                text(
                    """
                SELECT TRIM(name), TRIM(COALESCE(location, '')), COUNT(*) AS cnt
                FROM search_results
                WHERE archived = false
                  AND name IS NOT NULL AND TRIM(name) != ''
                GROUP BY TRIM(name), TRIM(COALESCE(location, ''))
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC
            """
                )
            ).fetchall()
            print("DRY RUN - no changes made")
            print(f"Duplicate name+location groups: {len(dup_groups)}")
            print(f"Rows that would be archived: {to_archive}")
            if dup_groups:
                print("\nSample duplicate groups (name + location, count):")
                for row in dup_groups[:10]:
                    print(f"  {row[2]}x  name={row[0]!r} | location={row[1]!r}")
            return to_archive

        ids_rows = db.execute(text(dup_sql)).fetchall()
        dup_ids = [row[0] for row in ids_rows]
        if not dup_ids:
            db.commit()
            print("No duplicate rows to archive.")
            return 0

        n_comments = (
            db.query(PostComment)
            .filter(
                PostComment.search_result_id.in_(dup_ids),
                PostComment.archived.is_(False),
            )
            .update({PostComment.archived: True}, synchronize_session=False)
        )
        n_results = (
            db.query(SearchResult)
            .filter(SearchResult.id.in_(dup_ids))
            .update({SearchResult.archived: True}, synchronize_session=False)
        )
        db.commit()
        print(f"Archived {n_results} duplicate lead(s) and {n_comments} comment row(s).")
        return n_results
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Archive duplicate search_results by name + location")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually archive duplicates (default is dry-run)",
    )
    args = parser.parse_args()
    archive_duplicates(dry_run=not args.execute)
