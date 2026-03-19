#!/usr/bin/env python3
"""
Standalone Facebook Scraper - Runs directly on US PC without Docker
"""
import asyncio
import sys
import json
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import get_db
from app.services.browser_manager import BrowserManager
from app.services.proxy_manager import ProxyManager
from app.services.facebook_scraper import FacebookScraper, NoActiveCookieError
from app.core.logging_config import setup_logging, get_logger

# Setup logging
setup_logging()
logger = get_logger(__name__)


def load_keywords():
    """Load keywords from config file."""
    config_path = Path("config/keywords.json")
    logger.info(f"Loading keywords from: {config_path.absolute()}")
    
    if config_path.exists():
        with open(config_path) as f:
            data = json.load(f)
            keywords = data.get("searchKeywords", [])
            logger.info(f"Loaded {len(keywords)} keywords from config")
            return keywords
    else:
        logger.warning(f"Keywords file not found, using defaults")
        return ["math tutor", "tutor needed"]


async def main():
    """Main entry point for standalone scraper"""
    logger.info("=" * 80)
    logger.info("FACEBOOK SCRAPER - STANDALONE MODE (US PC)")
    logger.info("=" * 80)
    
    # Load keywords
    keywords = load_keywords()
    max_results = 10
    
    logger.info(f"Loaded {len(keywords)} keywords")
    logger.info(f"Max results per keyword: {max_results}")
    logger.info("")
    
    # Get database session (non-critical for standalone mode)
    db = None
    try:
        db = next(get_db())
        logger.info("Database connected")
    except Exception as e:
        logger.warning(f"Database unavailable (non-critical for standalone): {e}")
    
    # Initialize components
    proxy_manager = ProxyManager(db)
    if not proxy_manager.proxies:
        logger.info("No proxy configured - running with direct connection (US PC)")
        proxy_manager = None
    
    browser_manager = BrowserManager(proxy_manager=proxy_manager)
    
    auth_failed = False
    try:
        # Initialize scraper
        scraper = FacebookScraper(db=db, browser_manager=browser_manager)
        
        # Run searches
        total_results = 0
        for i, keyword in enumerate(keywords, 1):
            logger.info("=" * 80)
            logger.info(f"KEYWORD {i}/{len(keywords)}: '{keyword}'")
            logger.info("=" * 80)
            
            try:
                count = await scraper.search_keyword(keyword, max_results=max_results)
                logger.info(
                    "Keyword '%s' completed: %s profiles processed",
                    keyword,
                    count,
                )
                total_results += int(count or 0)
                logger.info(f"Total results so far: {total_results}")
                
                # Delay between keywords
                if i < len(keywords):
                    import random
                    delay = random.uniform(10, 30)
                    logger.info(f"Waiting {delay:.1f}s before next keyword search...")
                    await asyncio.sleep(delay)
                    
            except NoActiveCookieError as e:
                logger.error(
                    "Session invalid and auto-login failed for all accounts — stopping "
                    "(fix cookies or credentials, then retry). Detail: %s",
                    e,
                )
                auth_failed = True
                break
            except Exception as e:
                logger.error(f"Error searching keyword '{keyword}': {e}", exc_info=True)
                continue
        
        logger.info("=" * 80)
        if auth_failed:
            logger.error("SCRAPING STOPPED — authentication failed.")
        else:
            logger.info(f"SCRAPING COMPLETED - Total results: {total_results}")
        logger.info("=" * 80)
        
    finally:
        # Cleanup
        logger.info("Closing browser...")
        await browser_manager.close()
        if proxy_manager:
            proxy_manager.close()
        if db:
            db.close()
        logger.info("Cleanup complete")

    if auth_failed:
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nScraper interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
