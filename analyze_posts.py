#!/usr/bin/env python3
"""
Batch analyzer for Facebook posts using Gemini AI.
Analyzes scraped posts to classify users as customers or tutors.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import SessionLocal
from app.core.logging_config import setup_logging, get_logger
from app.services.gemini_classifier import GeminiClassifier
from app.models.search_result import SearchResult, UserType

setup_logging(level="INFO")
logger = get_logger(__name__)


async def analyze_pending_posts(limit: int = None, force_reanalyze: bool = False):
    """
    Analyze posts that haven't been classified yet.
    
    Args:
        limit: Maximum number of posts to analyze (None = all)
        force_reanalyze: If True, re-analyze already analyzed posts
    """
    db = SessionLocal()
    
    try:
        logger.info("=" * 80)
        logger.info("STARTING GEMINI BATCH ANALYSIS")
        logger.info("=" * 80)
        
        # Initialize Gemini classifier
        classifier = GeminiClassifier()
        
        # Query posts to analyze
        query = db.query(SearchResult)
        
        if not force_reanalyze:
            query = query.filter(SearchResult.user_type == None)
        
        if limit:
            query = query.limit(limit)
        
        posts = query.all()
        
        if not posts:
            logger.info("No posts to analyze!")
            return
        
        logger.info(f"Found {len(posts)} posts to analyze")
        logger.info("")
        
        # Analyze each post
        analyzed_count = 0
        customer_count = 0
        tutor_count = 0
        unknown_count = 0
        
        for idx, post in enumerate(posts, 1):
            logger.info(f"[{idx}/{len(posts)}] Analyzing: {post.name}")
            logger.info(f"  Profile: {post.profile_url}")
            logger.info(f"  Keyword: {post.search_keyword}")
            
            if not post.post_content:
                logger.warning(f"  ⚠ No post content available, skipping")
                post.user_type = UserType.UNKNOWN
                post.confidence_score = 0.0
                post.analysis_message = "No post content"
                post.analyzed_at = datetime.now()
                unknown_count += 1
                continue

            # Classify with Gemini
            result = await classifier.classify_user(
                post_content=post.post_content,
                user_name=post.name
            )

            type_mapping = {
                "CUSTOMER": UserType.CUSTOMER,
                "TUTOR": UserType.TUTOR,
                "UNKNOWN": UserType.UNKNOWN
            }
            post.user_type = type_mapping.get(result["type"], UserType.UNKNOWN)
            post.confidence_score = result["confidence"]
            post.analysis_message = result.get("reason") or ""
            post.analyzed_at = datetime.now()
            
            # Update counts
            if post.user_type == UserType.CUSTOMER:
                customer_count += 1
                logger.info(f"  ✓ CUSTOMER (confidence: {result['confidence']:.2f})")
            elif post.user_type == UserType.TUTOR:
                tutor_count += 1
                logger.info(f"  ✓ TUTOR (confidence: {result['confidence']:.2f})")
            else:
                unknown_count += 1
                logger.info(f"  ✓ UNKNOWN (confidence: {result['confidence']:.2f})")
            
            logger.info(f"  Reason: {result.get('reason', 'N/A')}")
            logger.info("")
            
            analyzed_count += 1
            
            # Commit every 10 posts
            if analyzed_count % 10 == 0:
                db.commit()
                logger.info(f"Progress: {analyzed_count}/{len(posts)} analyzed")
                logger.info("")
        
        # Final commit
        db.commit()
        
        logger.info("=" * 80)
        logger.info("ANALYSIS COMPLETED")
        logger.info("=" * 80)
        logger.info(f"Total analyzed: {analyzed_count}")
        logger.info(f"Customers (looking for tutors): {customer_count}")
        logger.info(f"Tutors (offering services): {tutor_count}")
        logger.info(f"Unknown/Irrelevant: {unknown_count}")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


async def show_analysis_stats():
    """Show statistics of analyzed posts."""
    db = SessionLocal()
    
    try:
        total = db.query(SearchResult).count()
        analyzed = db.query(SearchResult).filter(SearchResult.user_type != None).count()
        pending = total - analyzed
        
        customers = db.query(SearchResult).filter(SearchResult.user_type == UserType.CUSTOMER).count()
        tutors = db.query(SearchResult).filter(SearchResult.user_type == UserType.TUTOR).count()
        unknown = db.query(SearchResult).filter(SearchResult.user_type == UserType.UNKNOWN).count()
        
        logger.info("=" * 80)
        logger.info("ANALYSIS STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Total posts in database: {total}")
        logger.info(f"Analyzed: {analyzed}")
        logger.info(f"Pending analysis: {pending}")
        logger.info("")
        logger.info(f"Customers (looking for tutors): {customers}")
        logger.info(f"Tutors (offering services): {tutors}")
        logger.info(f"Unknown/Irrelevant: {unknown}")
        logger.info("=" * 80)
        
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze Facebook posts with Gemini AI")
    parser.add_argument("--limit", type=int, help="Maximum number of posts to analyze")
    parser.add_argument("--force", action="store_true", help="Re-analyze already analyzed posts")
    parser.add_argument("--stats", action="store_true", help="Show analysis statistics only")
    
    args = parser.parse_args()
    
    if args.stats:
        asyncio.run(show_analysis_stats())
    else:
        asyncio.run(analyze_pending_posts(limit=args.limit, force_reanalyze=args.force))
