#!/usr/bin/env python3
"""
Diagnostic script to test scraper components and database connectivity.
Run this to verify your setup before running the full scraper.
"""
import asyncio
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.logging_config import setup_logging, get_logger
from app.models.search_result import SearchResult, Base
from app.services.scraper import ScraperService

# Setup logging
setup_logging(level="INFO")
logger = get_logger(__name__)


def test_database_connection():
    """Test database connectivity."""
    logger.info("=" * 80)
    logger.info("TESTING DATABASE CONNECTION")
    logger.info("=" * 80)
    
    try:
        logger.info(f"Database URL: {settings.DATABASE_URL}")
        
        # Test connection
        with engine.connect() as conn:
            logger.info("✓ Database connection successful")
        
        # Check if tables exist
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        logger.info(f"✓ Found {len(tables)} tables: {tables}")
        
        # Test query
        db = SessionLocal()
        try:
            count = db.query(SearchResult).count()
            logger.info(f"✓ Current records in search_results: {count}")
        finally:
            db.close()
        
        return True
    except Exception as e:
        logger.error(f"✗ Database connection failed: {e}", exc_info=True)
        return False


def test_config_files():
    """Test configuration files."""
    logger.info("=" * 80)
    logger.info("TESTING CONFIGURATION FILES")
    logger.info("=" * 80)
    
    all_ok = True
    
    # Check keywords
    keywords_path = Path("config/keywords.json")
    if keywords_path.exists():
        logger.info(f"✓ Keywords file found: {keywords_path}")
        try:
            import json
            with open(keywords_path) as f:
                data = json.load(f)
                keywords = data.get("searchKeywords", [])
                logger.info(f"  Keywords: {keywords}")
        except Exception as e:
            logger.error(f"✗ Error reading keywords file: {e}")
            all_ok = False
    else:
        logger.warning(f"⚠ Keywords file not found: {keywords_path}")
        logger.info(f"  Will use defaults: {settings.DEFAULT_KEYWORDS}")
    
    # Check credentials
    credentials_path = Path("config/credentials.json")
    if credentials_path.exists():
        logger.info(f"✓ Credentials file found: {credentials_path}")
        try:
            import json
            with open(credentials_path) as f:
                data = json.load(f)
                accounts = data.get("facebook_accounts", [])
                active_accounts = [a for a in accounts if a.get("active")]
                logger.info(f"  Total accounts: {len(accounts)}")
                logger.info(f"  Active accounts: {len(active_accounts)}")
                for acc in active_accounts:
                    uid = acc.get("uid", "Unknown")
                    has_totp = "Yes" if acc.get("totp_secret") else "No"
                    logger.info(f"    - {uid} (2FA: {has_totp})")
        except Exception as e:
            logger.error(f"✗ Error reading credentials file: {e}")
            all_ok = False
    else:
        logger.warning(f"⚠ Credentials file not found: {credentials_path}")
        logger.info(f"  Will use environment variables")
        logger.info(f"  FACEBOOK_EMAIL: {settings.FACEBOOK_EMAIL or '(not set)'}")
        logger.info(f"  FACEBOOK_PASSWORD: {'(set)' if settings.FACEBOOK_PASSWORD else '(not set)'}")
    
    return all_ok


async def test_scraper_init():
    """Test scraper initialization."""
    logger.info("=" * 80)
    logger.info("TESTING SCRAPER INITIALIZATION")
    logger.info("=" * 80)
    
    try:
        db = SessionLocal()
        try:
            scraper = ScraperService(db)
            logger.info("✓ ScraperService initialized")
            
            keywords = await scraper.load_keywords()
            logger.info(f"✓ Loaded {len(keywords)} keywords: {keywords}")
            
            return True
        finally:
            db.close()
    except Exception as e:
        logger.error(f"✗ Scraper initialization failed: {e}", exc_info=True)
        return False


async def main():
    """Run all diagnostic tests."""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║" + " " * 20 + "SCRAPER DIAGNOSTIC TOOL" + " " * 35 + "║")
    logger.info("╚" + "=" * 78 + "╝")
    logger.info("\n")
    
    results = []
    
    # Test 1: Database
    results.append(("Database Connection", test_database_connection()))
    logger.info("\n")
    
    # Test 2: Config Files
    results.append(("Configuration Files", test_config_files()))
    logger.info("\n")
    
    # Test 3: Scraper Init
    results.append(("Scraper Initialization", await test_scraper_init()))
    logger.info("\n")
    
    # Summary
    logger.info("=" * 80)
    logger.info("DIAGNOSTIC SUMMARY")
    logger.info("=" * 80)
    
    all_passed = True
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"{status}: {test_name}")
        if not passed:
            all_passed = False
    
    logger.info("=" * 80)
    
    if all_passed:
        logger.info("✓ All tests passed! Your scraper is ready to run.")
        logger.info("\nTo start scraping, run:")
        logger.info("  python scrape.py")
        logger.info("\nOr use the API:")
        logger.info("  uvicorn app.main:app --reload")
        return 0
    else:
        logger.error("✗ Some tests failed. Please fix the issues above before running the scraper.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
