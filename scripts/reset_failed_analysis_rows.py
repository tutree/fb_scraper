#!/usr/bin/env python3
"""
Reset search_results rows that were marked analyzed but the AI call actually failed
(parse errors, Groq retries exhausted, geo/classification errors in the reason text).

Clears analyzed_at, user_type, confidence_score, analysis_message so rows show as
pending analysis again (matches analyzed_at IS NULL / user_type IS NULL in the app).

Usage:
  python scripts/reset_failed_analysis_rows.py              # dry-run: count + sample
  python scripts/reset_failed_analysis_rows.py --execute     # apply UPDATE

Requires DATABASE_URL (e.g. from .env). Loads app settings like other scripts.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import or_

from app.core.database import SessionLocal
from app.models.search_result import SearchResult

# Substrings stored in analysis_message when the old classifier swallowed errors.
FAILURE_SNIPPETS = (
    "Failed to parse AI response",
    "Groq request failed",
    "Classification error:",
    "Comment classification error:",
    "Geo classification error:",
)


def _failure_filter():
    return or_(
        *[
            SearchResult.analysis_message.ilike(f"%{snippet}%")
            for snippet in FAILURE_SNIPPETS
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform UPDATE; omit for dry-run only.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = (
            db.query(SearchResult)
            .filter(SearchResult.archived.is_(False))
            .filter(SearchResult.analysis_message.isnot(None))
            .filter(_failure_filter())
        )
        n = q.count()
        sample = q.limit(15).all()

        print(f"Matching rows (non-archived, failed-analysis message): {n}")
        for row in sample:
            msg = (row.analysis_message or "")[:120]
            print(f"  {row.id} | {row.name!r} | {msg!r}")

        if not args.execute:
            print("\nDry-run only. Re-run with --execute to clear analysis fields on these rows.")
            return

        updated = (
            db.query(SearchResult)
            .filter(SearchResult.archived.is_(False))
            .filter(SearchResult.analysis_message.isnot(None))
            .filter(_failure_filter())
            .update(
                {
                    SearchResult.analyzed_at: None,
                    SearchResult.user_type: None,
                    SearchResult.confidence_score: None,
                    SearchResult.analysis_message: None,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        print(f"\nUpdated {updated} row(s). They are unanalyzed and eligible for re-analysis.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
