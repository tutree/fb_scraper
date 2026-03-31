from typing import List, Optional, Dict, Any, Callable
from sqlalchemy.orm import Session
import asyncio
import random
from datetime import datetime
import json
from . import scraper_state
from .browser_manager import BrowserManager
from .fb_errors import CookieExpiredDuringProfileScrape
from .facebook_scraper import FacebookScraper, NoActiveCookieError
from .proxy_manager import ProxyManager
from .fb_account_loader import load_accounts, ordered_accounts_with_proxy_slots
from ..models.search_result import SearchResult
from ..core.config import keywords_json_path, settings
from ..core.database import SessionLocal
from ..core.logging_config import get_logger

logger = get_logger(__name__)


def split_keywords_across_accounts(keywords: List[str], n: int) -> List[List[str]]:
    """Round-robin split: account i gets keywords i, i+n, i+2n, ..."""
    if n <= 0:
        return []
    chunks: List[List[str]] = [[] for _ in range(n)]
    for i, kw in enumerate(keywords):
        chunks[i % n].append(kw)
    return chunks


class ScraperService:
    def __init__(self, db: Session):
        self.db = db
        self.proxy_manager = ProxyManager(db)
        self.browser_manager = BrowserManager(self.proxy_manager)
        self.facebook_scraper = FacebookScraper(db, self.browser_manager)

    async def _run_parallel_account_lanes(
        self,
        accounts: List[Dict],
        slot_indices: List[Optional[int]],
        keywords: List[str],
        max_results: int,
        should_stop: Optional[Callable[[], bool]],
    ) -> Dict[str, Any]:
        """One asyncio task per account; each has its own DB session + browser + proxy context."""
        n = len(accounts)
        if len(slot_indices) != n:
            slot_indices = [None] * n
        chunks = split_keywords_across_accounts(keywords, n)
        lanes = [
            (accounts[i], chunks[i], slot_indices[i])
            for i in range(n)
            if chunks[i]
        ]

        if not lanes:
            return {
                "success": True,
                "stopped": False,
                "total_results": 0,
                "keywords_searched": 0,
                "parallel": True,
                "lane_results": [],
                "error": None,
            }

        logger.info(
            "Parallel scrape: %d lane(s), accounts=%s",
            len(lanes),
            [acc.get("uid") for acc, _kws, _slot in lanes],
        )

        async def one_lane(
            lane_idx: int,
            account: Dict,
            kws: List[str],
            proxy_slot_idx: Optional[int],
        ) -> Dict[str, Any]:
            db = SessionLocal()
            bm: Optional[BrowserManager] = None
            total_results_count = 0
            try:
                pm = ProxyManager(db)
                bm = BrowserManager(pm)
                fs = FacebookScraper(
                    db, bm, accounts=[account], proxy_slot_index=proxy_slot_idx
                )
                uid = str(account.get("uid", ""))
                stopped = False
                for idx, keyword in enumerate(kws, 1):
                    if should_stop and should_stop():
                        logger.warning(
                            "[Lane %s uid=%s] Stop requested before keyword %s",
                            lane_idx,
                            uid,
                            keyword,
                        )
                        stopped = True
                        break
                    logger.info(
                        "=" * 40
                        + f" [Lane {lane_idx} uid={uid} KEYWORD {idx}/{len(kws)}: '{keyword}'] "
                        + "=" * 40
                    )
                    try:
                        processed_count = await fs.search_keyword(
                            keyword, max_results, should_stop=should_stop
                        )
                        total_results_count += int(processed_count or 0)
                    except CookieExpiredDuringProfileScrape as ce:
                        logger.error(
                            "[Lane %s] Cookie expired on '%s': %s",
                            lane_idx,
                            keyword,
                            ce,
                        )
                        return {
                            "success": False,
                            "stopped": False,
                            "uid": uid,
                            "total": total_results_count,
                            "error": str(ce),
                            "lane": lane_idx,
                        }
                    except NoActiveCookieError:
                        logger.error(
                            "[Lane %s] No active cookie for keyword '%s'",
                            lane_idx,
                            keyword,
                        )
                        scraper_state.report_all_cookies_failed()
                        return {
                            "success": False,
                            "stopped": False,
                            "uid": uid,
                            "total": total_results_count,
                            "error": "no active cookie",
                            "lane": lane_idx,
                        }
                    if idx < len(kws):
                        delay = random.uniform(
                            max(settings.SCRAPE_DELAY_MIN, 10),
                            max(settings.SCRAPE_DELAY_MAX, 30),
                        )
                        logger.info(
                            "[Lane %s] Waiting %.1fs before next keyword...",
                            lane_idx,
                            delay,
                        )
                        if await self._sleep_with_stop(delay, should_stop):
                            stopped = True
                            break
                if stopped:
                    return {
                        "success": False,
                        "stopped": True,
                        "uid": uid,
                        "total": total_results_count,
                        "error": None,
                        "lane": lane_idx,
                    }
                return {
                    "success": True,
                    "stopped": False,
                    "uid": uid,
                    "total": total_results_count,
                    "error": None,
                    "lane": lane_idx,
                }
            except Exception as e:
                logger.exception("[Lane %s] failed: %s", lane_idx, e)
                return {
                    "success": False,
                    "stopped": False,
                    "uid": str(account.get("uid", "")),
                    "total": total_results_count,
                    "error": str(e),
                    "lane": lane_idx,
                }
            finally:
                if bm:
                    await bm.close()
                db.close()

        tasks = [
            one_lane(i, acc, kws, slot_idx)
            for i, (acc, kws, slot_idx) in enumerate(lanes)
        ]
        lane_out = await asyncio.gather(*tasks)
        total = sum(int(r.get("total") or 0) for r in lane_out)
        any_stopped = any(r.get("stopped") for r in lane_out)
        any_fail = any(
            not r.get("success") and not r.get("stopped") for r in lane_out
        )
        err_msgs = [r.get("error") for r in lane_out if r.get("error")]
        combined_error = "; ".join(str(x) for x in err_msgs if x) if err_msgs else None

        return {
            "success": not any_fail and not any_stopped,
            "stopped": any_stopped,
            "total_results": total,
            "keywords_searched": len(keywords),
            "parallel": True,
            "lane_results": lane_out,
            "error": combined_error,
        }

    async def load_keywords(self) -> List[str]:
        """Load keywords from keywords.json (same path as API: keywords_json_path())."""
        config_path = keywords_json_path()
        logger.info("Loading keywords from: %s", config_path)

        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
                keywords = data.get("searchKeywords", [])
                logger.info(f"Loaded {len(keywords)} keywords from config: {keywords}")
                return keywords
        logger.warning("Keywords file not found at %s, using defaults", config_path)
        logger.info(f"Default keywords: {settings.DEFAULT_KEYWORDS}")
        return settings.DEFAULT_KEYWORDS

    async def run_search(
        self,
        keywords: Optional[List[str]] = None,
        max_results: Optional[int] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """Main search orchestration."""
        if max_results is None:
            max_results = settings.MAX_RESULTS_PER_KEYWORD

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

        scraper_state.report_scrape_start()
        logger.info(f"Will search {len(keywords)} keywords with max {max_results} results each")

        ordered = ordered_accounts_with_proxy_slots()
        accounts = [t[0] for t in ordered]
        slot_indices = [t[1] for t in ordered]

        if not accounts:
            logger.error("No Facebook accounts with cookie files — cannot run search.")
            return {
                "success": False,
                "error": "No accounts with saved cookie sessions",
                "total_results": 0,
                "keywords_searched": 0,
            }

        if len(accounts) > 1:
            logger.info(
                "Multi-account mode: %d accounts with cookie files — parallel lanes",
                len(accounts),
            )
            try:
                result = await self._run_parallel_account_lanes(
                    accounts, slot_indices, keywords, max_results, should_stop
                )
                if result.get("stopped"):
                    scraper_state.report_scrape_finish(
                        success=False, error="Stop requested"
                    )
                elif result.get("success"):
                    scraper_state.report_scrape_finish(success=True)
                else:
                    scraper_state.report_scrape_finish(
                        success=False,
                        error=result.get("error") or "Parallel scrape had failures",
                    )
                return result
            except Exception as e:
                logger.error("Parallel scrape failed: %s", e, exc_info=True)
                scraper_state.report_scrape_finish(success=False, error=str(e))
                return {
                    "success": False,
                    "stopped": False,
                    "error": str(e),
                    "total_results": 0,
                    "keywords_searched": len(keywords),
                    "parallel": True,
                }
            finally:
                logger.info("Closing idle shared browser manager (parallel mode)...")
                await self.browser_manager.close()

        total_results_count = 0
        single_fs = FacebookScraper(
            self.db,
            self.browser_manager,
            accounts=[accounts[0]],
            proxy_slot_index=slot_indices[0],
        )
        try:
            for idx, keyword in enumerate(keywords, 1):
                if should_stop and should_stop():
                    logger.warning("Stop requested before next keyword. Ending scraper run.")
                    return {
                        "success": False,
                        "stopped": True,
                        "total_results": total_results_count,
                        "keywords_searched": idx - 1,
                    }

                logger.info("=" * 80)
                logger.info(f"KEYWORD {idx}/{len(keywords)}: '{keyword}'")
                logger.info("=" * 80)

                try:
                    processed_count = await single_fs.search_keyword(
                        keyword, max_results, should_stop=should_stop
                    )
                    processed_count = int(processed_count or 0)
                    total_results_count += processed_count
                    logger.info(f"Keyword '{keyword}' completed: {processed_count} results")
                    logger.info(f"Total results so far: {total_results_count}")
                except CookieExpiredDuringProfileScrape as ce:
                    logger.error(
                        "Cookie expired mid-scrape — stopping run (keyword '%s'): %s",
                        keyword,
                        ce,
                    )
                    scraper_state.report_scrape_finish(
                        success=False,
                        error="Cookie session expired — profile showed Facebook login instead of a real name",
                    )
                    return {
                        "success": False,
                        "stopped": False,
                        "error": str(ce),
                        "total_results": total_results_count,
                        "keywords_searched": idx - 1,
                    }
                except NoActiveCookieError:
                    logger.error(
                        "All auto-login attempts failed for keyword '%s' — skipping to next keyword",
                        keyword,
                    )
                    scraper_state.report_all_cookies_failed()
                    continue

                # Longer random delay between searches (10-30 seconds)
                if idx < len(keywords):  # Don't wait after last keyword
                    delay = random.uniform(
                        max(settings.SCRAPE_DELAY_MIN, 10),
                        max(settings.SCRAPE_DELAY_MAX, 30),
                    )
                    logger.info(f"Waiting {delay:.1f}s before next keyword search...")
                    if await self._sleep_with_stop(delay, should_stop):
                        logger.warning("Stop requested during keyword delay. Ending scraper run.")
                        return {
                            "success": False,
                            "stopped": True,
                            "total_results": total_results_count,
                            "keywords_searched": idx,
                        }

            logger.info("=" * 80)
            logger.info("SCRAPER SERVICE COMPLETED SUCCESSFULLY")
            logger.info(f"Total results collected: {total_results_count}")
            logger.info(f"Keywords searched: {len(keywords)}")
            logger.info("=" * 80)
            
            scraper_state.report_scrape_finish(success=True)
            return {
                "success": True,
                "stopped": False,
                "total_results": total_results_count,
                "keywords_searched": len(keywords),
            }

        except Exception as e:
            logger.error("=" * 80)
            logger.error("SCRAPER SERVICE FAILED")
            logger.error(f"Error: {e}", exc_info=True)
            logger.error("=" * 80)
            scraper_state.report_scrape_finish(success=False, error=str(e))
            return {
                "success": False,
                "stopped": False,
                "error": str(e),
                "total_results": total_results_count,
                "keywords_searched": len(keywords),
            }
        finally:
            logger.info("Closing browser...")
            await self.browser_manager.close()
            logger.info("Browser closed")

    async def _sleep_with_stop(
        self,
        total_seconds: float,
        should_stop: Optional[Callable[[], bool]],
    ) -> bool:
        """Sleep in short intervals and return True if stop is requested."""
        if not should_stop:
            await asyncio.sleep(total_seconds)
            return False

        remaining = max(0.0, float(total_seconds))
        while remaining > 0:
            if should_stop():
                return True
            chunk = min(1.0, remaining)
            await asyncio.sleep(chunk)
            remaining -= chunk
        return should_stop()

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
