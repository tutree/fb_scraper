#!/usr/bin/env python3
"""
Direct scraper runner - runs scraping immediately and shows results
"""
import asyncio
import sys
from pathlib import Path

# Force unbuffered output immediately
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print("=" * 80, flush=True)
print("INITIALIZING SCRAPER...", flush=True)
print("=" * 80, flush=True)

sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import SessionLocal
from app.core.logging_config import setup_logging, get_logger
from app.services.scraper import ScraperService
from app.models.search_result import SearchResult

print("Setting up logging...", flush=True)
setup_logging(level="INFO")
logger = get_logger(__name__)
print("Logging configured", flush=True)


async def main():
    """Run scraper and display results."""
    db = SessionLocal()
    
    try:
        logger.info("=" * 80)
        logger.info("STARTING DIRECT SCRAPER RUN")
        logger.info("=" * 80)
        
        # Create scraper service
        scraper = ScraperService(db)
        
        # Load keywords from keywords.json
        keywords = await scraper.load_keywords()
        max_results = 10  # Get 10 users per keyword
        
        logger.info(f"Loaded keywords from config: {keywords}")
        logger.info(f"Max results per keyword: {max_results}")
        logger.info("")
        
        # Run the search
        result = await scraper.run_search(keywords=keywords, max_results=max_results)
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("SCRAPING COMPLETED")
        logger.info("=" * 80)
        logger.info(f"Success: {result.get('success')}")
        logger.info(f"Total results: {result.get('total_results', 0)}")
        logger.info(f"Keywords searched: {result.get('keywords_searched', 0)}")
        
        if not result.get('success'):
            logger.error(f"Error: {result.get('error')}")
            return 1
        
        # Query database to show what was saved
        logger.info("")
        logger.info("=" * 80)
        logger.info("DATABASE RESULTS")
        logger.info("=" * 80)
        
        total_count = db.query(SearchResult).count()
        logger.info(f"Total records in database: {total_count}")
        
        if total_count > 0:
            recent_results = (
                db.query(SearchResult)
                .order_by(SearchResult.scraped_at.desc())
                .limit(5)
                .all()
            )
            
            logger.info(f"\nShowing {len(recent_results)} most recent results:")
            logger.info("-" * 80)
            
            for idx, r in enumerate(recent_results, 1):
                logger.info(f"\n{idx}. {r.name}")
                logger.info(f"   Keyword: {r.search_keyword}")
                logger.info(f"   Location: {r.location or 'N/A'}")
                logger.info(f"   Content: {(r.post_content or '')[:100]}...")
                logger.info(f"   URL: {r.post_url or 'N/A'}")
                logger.info(f"   Scraped: {r.scraped_at}")
        else:
            logger.warning("No results found in database!")
        
        return 0
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
