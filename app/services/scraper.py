from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
import asyncio
import random
from datetime import datetime
import json
from pathlib import Path

from .browser_manager import BrowserManager
from .facebook_scraper import FacebookScraper
from .proxy_manager import ProxyManager
from ..models.search_result import SearchResult
from ..core.config import settings
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class ScraperService:
    def __init__(self, db: Session):
        self.db = db
        self.proxy_manager = ProxyManager(db)
        self.browser_manager = BrowserManager(self.proxy_manager)
        self.facebook_scraper = FacebookScraper(db, self.browser_manager)

    async def load_keywords(self) -> List[str]:
        """Load keywords from config file."""
        config_path = Path("config/keywords.json")
        logger.info(f"Loading keywords from: {config_path.absolute()}")
        
        if config_path.exists():
            with open(config_path) as f:
                data = json.load(f)
                keywords = data.get("searchKeywords", [])
                logger.info(f"Loaded {len(keywords)} keywords from config: {keywords}")
                return keywords
        else:
            logger.warning(f"Keywords file not found at {config_path}, using defaults")
            logger.info(f"Default keywords: {settings.DEFAULT_KEYWORDS}")
            return settings.DEFAULT_KEYWORDS

    async def run_search(
        self,
        keywords: Optional[List[str]] = None,
        max_results: int = 100,
    ) -> Dict[str, Any]:
        """Main search orchestration."""
        logger.info("=" * 80)
        logger.info("STARTING SCRAPER SERVICE")
        logger.info("=" * 80)
        
        if not keywords:
            keywords = await self.load_keywords()
        else:
            logger.info(f"Using provided keywords: {keywords}")

        if not keywords:
            logger.error("No keywords available for search!")
            return {
                "success": False,
                "error": "No keywords provided or loaded",
                "total_results": 0,
                "keywords_searched": 0,
            }

        all_results: List[Dict] = []
        logger.info(f"Will search {len(keywords)} keywords with max {max_results} results each")

        try:
            for idx, keyword in enumerate(keywords, 1):
                logger.info("=" * 80)
                logger.info(f"KEYWORD {idx}/{len(keywords)}: '{keyword}'")
                logger.info("=" * 80)

                # Search for this keyword
                results = await self.facebook_scraper.search_keyword(
                    keyword, max_results
                )
                all_results.extend(results)
                
                logger.info(f"Keyword '{keyword}' completed: {len(results)} results")
                logger.info(f"Total results so far: {len(all_results)}")

                # Longer random delay between searches (10-30 seconds)
                if idx < len(keywords):  # Don't wait after last keyword
                    delay = random.uniform(
                        max(settings.SCRAPE_DELAY_MIN, 10),
                        max(settings.SCRAPE_DELAY_MAX, 30),
                    )
                    logger.info(f"Waiting {delay:.1f}s before next keyword search...")
                    await asyncio.sleep(delay)

            logger.info("=" * 80)
            logger.info("SCRAPER SERVICE COMPLETED SUCCESSFULLY")
            logger.info(f"Total results collected: {len(all_results)}")
            logger.info(f"Keywords searched: {len(keywords)}")
            logger.info("=" * 80)
            
            return {
                "success": True,
                "total_results": len(all_results),
                "keywords_searched": len(keywords),
            }

        except Exception as e:
            logger.error("=" * 80)
            logger.error("SCRAPER SERVICE FAILED")
            logger.error(f"Error: {e}", exc_info=True)
            logger.error("=" * 80)
            return {
                "success": False,
                "error": str(e),
                "total_results": len(all_results),
                "keywords_searched": len(keywords),
            }
        finally:
            logger.info("Closing browser...")
            await self.browser_manager.close()
            logger.info("Browser closed")

    async def get_results(
        self,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[SearchResult]:
        """Get search results with filters."""
        query = self.db.query(SearchResult)

        if status:
            query = query.filter(SearchResult.status == status)

        if keyword:
            query = query.filter(SearchResult.search_keyword == keyword)

        return (
            query.order_by(SearchResult.scraped_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    async def update_result_status(
        self, result_id: str, status: str
    ) -> bool:
        """Update status of a search result."""
        result = (
            self.db.query(SearchResult)
            .filter(SearchResult.id == result_id)
            .first()
        )
        if result:
            result.status = status
            result.updated_at = datetime.now()
            self.db.commit()
            return True
        return False
