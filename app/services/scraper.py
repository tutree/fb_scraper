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
        if config_path.exists():
            with open(config_path) as f:
                data = json.load(f)
                return data.get("searchKeywords", [])
        return settings.DEFAULT_KEYWORDS

    async def run_search(
        self,
        keywords: Optional[List[str]] = None,
        max_results: int = 100,
    ) -> Dict[str, Any]:
        """Main search orchestration."""
        if not keywords:
            keywords = await self.load_keywords()

        all_results: List[Dict] = []

        try:
            for keyword in keywords:
                logger.info(f"Searching for: {keyword}")

                # Search for this keyword
                results = await self.facebook_scraper.search_keyword(
                    keyword, max_results
                )
                all_results.extend(results)

                # Longer random delay between searches (10-30 seconds)
                delay = random.uniform(
                    max(settings.SCRAPE_DELAY_MIN, 10),
                    max(settings.SCRAPE_DELAY_MAX, 30),
                )
                logger.info(f"Waiting {delay:.1f}s before next search...")
                await asyncio.sleep(delay)

            return {
                "success": True,
                "total_results": len(all_results),
                "keywords_searched": len(keywords),
            }

        except Exception as e:
            logger.error(f"Error in run_search: {e}")
            return {
                "success": False,
                "error": str(e),
            }
        finally:
            await self.browser_manager.close()

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
