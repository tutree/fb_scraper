#!/usr/bin/env python3
"""
Batch analyzer for Facebook post comments using the configured AI provider.
Classifies comment authors as potential customers or tutors (with score).
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import SessionLocal
from app.core.logging_config import setup_logging, get_logger
from app.services.gemini_classifier import AnalysisInvocationError, GeminiClassifier
from app.models.post_comment import PostComment
from app.models.search_result import SearchResult, UserType

setup_logging(level="INFO")
logger = get_logger(__name__)


async def analyze_pending_comments(limit: int = None, force_reanalyze: bool = False):
    """
    Analyze comments that haven't been classified yet.
    """
    db = SessionLocal()
    try:
        logger.info("=" * 80)
        logger.info("STARTING COMMENT ANALYSIS")
        logger.info("=" * 80)

        classifier = GeminiClassifier()
        query = db.query(PostComment)

        analyzed_count = 0
        customer_count = 0
        tutor_count = 0
        unknown_count = 0

        if not force_reanalyze:
            query = query.filter(PostComment.user_type == None)

        if limit:
            query = query.limit(limit)

        comments = query.all()
        if not comments:
            total = db.query(PostComment).count()
            if total == 0:
                logger.info("No comments to analyze! (post_comments table is empty)")
            else:
                logger.info("No pending comments (all %d already have user_type). Use --force to re-analyze all.", total)
            return

        # Pre-load post context (post_content + keyword) keyed by search_result_id
        search_result_ids = list({c.search_result_id for c in comments})
        post_contexts = {
            str(sr.id): (sr.post_content or "", sr.search_keyword or "")
            for sr in db.query(SearchResult).filter(SearchResult.id.in_(search_result_ids))
        }

        for idx, comment in enumerate(comments, 1):
            logger.info(f"[{idx}/{len(comments)}] {comment.author_name or 'Unknown'}")

            if not comment.comment_text or not comment.comment_text.strip():
                comment.user_type = UserType.UNKNOWN
                comment.confidence_score = 0.0
                comment.analysis_message = "No comment text"
                comment.analyzed_at = datetime.now()
                unknown_count += 1
                analyzed_count += 1
                continue

            post_content, search_keyword = post_contexts.get(str(comment.search_result_id), ("", ""))

            try:
                result = await classifier.classify_comment_user(
                    comment_text=comment.comment_text,
                    author_name=comment.author_name or "",
                    post_context=post_content,
                    search_keyword=search_keyword,
                )
            except AnalysisInvocationError as e:
                logger.warning(
                    "  ⚠ Comment analysis failed (left un-analyzed): %s",
                    e,
                )
                continue

            type_mapping = {
                "CUSTOMER": UserType.CUSTOMER,
                "TUTOR": UserType.TUTOR,
                "UNKNOWN": UserType.UNKNOWN,
            }
            comment.user_type = type_mapping.get(result["type"], UserType.UNKNOWN)
            comment.confidence_score = result["confidence"]
            comment.analysis_message = result.get("reason") or ""
            comment.analyzed_at = datetime.now()

            if comment.user_type == UserType.CUSTOMER:
                customer_count += 1
                logger.info(f"  ✓ CUSTOMER (score: {result['confidence']:.2f})")
            elif comment.user_type == UserType.TUTOR:
                tutor_count += 1
                logger.info(f"  ✓ TUTOR (score: {result['confidence']:.2f})")
            else:
                unknown_count += 1
                logger.info(f"  ✓ UNKNOWN (score: {result['confidence']:.2f})")
            logger.info(f"  Reason: {result.get('reason', 'N/A')}")
            logger.info("")

            analyzed_count += 1
            if analyzed_count % 10 == 0:
                db.commit()
                logger.info(f"Progress: {analyzed_count}/{len(comments)} analyzed")
                logger.info("")

        db.commit()
        logger.info("=" * 80)
        logger.info("COMMENT ANALYSIS COMPLETED")
        logger.info("=" * 80)
        logger.info(f"Total analyzed: {analyzed_count}")
        logger.info(f"Potential customers: {customer_count}")
        logger.info(f"Tutors: {tutor_count}")
        logger.info(f"Unknown: {unknown_count}")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"Comment analysis failed: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


async def show_comment_stats():
    """Show statistics of analyzed comments."""
    db = SessionLocal()
    try:
        total = db.query(PostComment).count()
        analyzed = db.query(PostComment).filter(PostComment.user_type != None).count()
        pending = total - analyzed
        customers = db.query(PostComment).filter(PostComment.user_type == UserType.CUSTOMER).count()
        tutors = db.query(PostComment).filter(PostComment.user_type == UserType.TUTOR).count()
        unknown = db.query(PostComment).filter(PostComment.user_type == UserType.UNKNOWN).count()

        logger.info("=" * 80)
        logger.info("COMMENT ANALYSIS STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Total comments: {total}")
        logger.info(f"Analyzed: {analyzed}")
        logger.info(f"Pending: {pending}")
        logger.info(f"Potential customers: {customers}")
        logger.info(f"Tutors: {tutors}")
        logger.info(f"Unknown: {unknown}")
        logger.info("=" * 80)
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze Facebook comments with the configured AI provider")
    parser.add_argument("--limit", type=int, help="Maximum number of comments to analyze")
    parser.add_argument("--force", action="store_true", help="Re-analyze already analyzed comments")
    parser.add_argument("--stats", action="store_true", help="Show comment analysis statistics only")
    args = parser.parse_args()

    if args.stats:
        asyncio.run(show_comment_stats())
    else:
        asyncio.run(analyze_pending_comments(limit=args.limit, force_reanalyze=args.force))
