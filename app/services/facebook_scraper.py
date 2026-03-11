"""
Facebook scraper — thin orchestrator.

All heavy lifting is delegated to focused sub-modules:
  fb_account_loader  — credentials / cookie loading
  fb_login           — Playwright login flow
  fb_human_behavior  — mouse, scroll, session-warmup helpers
  fb_comment_handler — comment dialog interaction & extraction
  fb_post_url        — Share → Copy-link URL capture
  fb_feed_scanner    — search-results scroll + per-profile pipeline
  fb_profile_processor — single-profile visit & DB persistence
  facebook_selectors — centralised JS selector constants
  facebook_comment_fix — expand-comments helper
"""
import asyncio
import random
from typing import Callable, Dict, List, Optional
from urllib.parse import quote_plus

from playwright.async_api import Page
from sqlalchemy.orm import Session

from ..core.logging_config import get_logger
from .fb_account_loader import load_accounts
from .fb_feed_scanner import scroll_and_process_posts
from .fb_login import login

logger = get_logger(__name__)


class FacebookScraper:
    def __init__(self, db: Session, browser_manager):
        self.db = db
        self.browser_manager = browser_manager
        self.accounts = load_accounts()
        self.account_index = 0
        self._current_page: Optional[Page] = None
        self._current_account: Dict = {}

        logger.info(f"FacebookScraper initialized with {len(self.accounts)} accounts")
        if not self.accounts:
            logger.error("No Facebook accounts available! Scraping will fail.")
        else:
            logger.info(f"Using single account: {self.accounts[0].get('uid', 'Unknown')}")

    def _get_next_account(self) -> Dict:
        """Always use the first (and only) account — no rotation."""
        if not self.accounts:
            logger.error("No accounts available for selection")
            return {}
        account = self.accounts[0]
        logger.info(f"Using account: {account.get('uid', 'Unknown')}")
        return account

    def _resolve_comment_limit(self, max_comments: int) -> int:
        """Translate a user-facing max_comments to an extraction-safe upper bound."""
        return max_comments if max_comments and max_comments > 0 else 5000

    async def _sleep_with_stop(
        self,
        total_seconds: float,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Sleep in 1-second chunks, aborting early when *should_stop* returns True."""
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

    async def _inspect_auth_state(self, page: Page) -> Dict[str, bool]:
        """Return robust auth-state indicators from the current Facebook page."""
        try:
            state = await page.evaluate(
                """
                () => {
                    const body = (document.body?.innerText || '').toLowerCase();
                    const title = (document.title || '').toLowerCase();
                    const hasLoginInputs = !!document.querySelector(
                        'input[name="email"], input[name="pass"], #email, #pass'
                    );
                    const hasJoinCopy =
                        body.includes('join or log into facebook') ||
                        body.includes('forgot account?') ||
                        body.includes("this page isn't available");
                    const hasLoginButton =
                        body.includes('\\nlog in\\n') ||
                        body.includes('log in') ||
                        body.includes('sign up');
                    const hasNav = !!document.querySelector('div[role="navigation"]');
                    const hasFeed = !!document.querySelector('div[role="feed"]');
                    const hasProfileLink = !!document.querySelector(
                        'a[href*="/profile.php"], a[href*="/me/"]'
                    );
                    const hasSearchInput = !!document.querySelector(
                        'input[type="search"], input[placeholder*="Search"], input[aria-label*="Search"]'
                    );
                    const loggedOut =
                        hasLoginInputs ||
                        hasJoinCopy ||
                        (title.includes('page not found') && hasLoginButton);
                    const loggedIn =
                        !loggedOut &&
                        (hasNav || hasFeed || hasProfileLink || hasSearchInput);
                    return { loggedOut, loggedIn };
                }
                """
            )
            return {
                "logged_out": bool(state.get("loggedOut")),
                "logged_in": bool(state.get("loggedIn")),
            }
        except Exception as exc:
            logger.warning(f"Could not inspect auth state reliably: {exc}")
            return {"logged_out": False, "logged_in": False}

    async def search_keyword(
        self,
        keyword: str,
        max_results: int = 10,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> int:
        """Search for a keyword and extract posts."""
        if should_stop and should_stop():
            logger.warning("Stop requested before search start. Skipping keyword.")
            return 0

        logger.info(f"=== Starting search for keyword: '{keyword}' ===")
        logger.info(f"Max results target: {max_results}")

        if not hasattr(self, "_current_page") or self._current_page is None:
            account = self._get_next_account()
            self._current_account = account
            logger.info(f"Using account: {account.get('uid', 'Unknown')}")
            logger.info("Creating browser page...")
            self._current_page = await self.browser_manager.create_page_with_cookies(
                account.get("uid")
            )
            logger.info("Browser page created successfully")

            logger.info("Checking if already logged in...")
            try:
                await self._current_page.goto(
                    "https://www.facebook.com",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await asyncio.sleep(4)
            except Exception as e:
                logger.warning(f"Page load issue (continuing anyway): {e}")

            is_logged_in = False
            try:
                auth_state = await self._inspect_auth_state(self._current_page)
                if auth_state["logged_in"]:
                    logger.info("Already logged in (session restored from cookies)")
                    is_logged_in = True
                elif auth_state["logged_out"]:
                    logger.info("Login required (logged-out markers detected)")
                else:
                    logger.info("Auth state uncertain; will attempt explicit login")
            except Exception as e:
                logger.warning(f"Error checking login status: {e}")

            if not is_logged_in:
                logger.info("Not logged in, attempting login...")
                login_success = await login(self._current_page, account)
                if not login_success:
                    logger.error("Login failed, aborting search")
                    return 0
                logger.info("Login successful")
                logger.info("Saving session cookies for future use...")
                await self.browser_manager.save_cookies(self._current_page)
            else:
                logger.info("Skipping login (already authenticated)")

            logger.info("Skipping session warmup (using saved cookies)")
        else:
            logger.info("Reusing existing browser session")

        page = self._current_page

        try:
            delay = random.uniform(3, 7)
            logger.info(f"Waiting {delay:.1f}s before searching...")
            if await self._sleep_with_stop(delay, should_stop=should_stop):
                logger.warning("Stop requested before search navigation.")
                return 0

            current_url = page.url
            if not (
                current_url.startswith("https://www.facebook.com")
                or current_url.startswith("https://web.facebook.com")
            ):
                logger.info("Navigating to Facebook homepage...")
                await page.goto(
                    "https://www.facebook.com",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                if await self._sleep_with_stop(
                    random.uniform(2, 4), should_stop=should_stop
                ):
                    logger.warning("Stop requested after homepage navigation.")
                    return 0
            else:
                logger.info(f"Already on Facebook (URL: {current_url}), skipping navigation")

            search_url = f"https://www.facebook.com/search/posts/?q={quote_plus(keyword)}"
            logger.info(f"Navigating to search URL: {search_url}")
            try:
                await page.goto(search_url, wait_until="networkidle", timeout=120000)
            except Exception as e:
                logger.warning(f"networkidle wait failed, trying domcontentloaded: {e}")
                await page.goto(search_url, wait_until="domcontentloaded", timeout=120000)

            wait_time = 10
            logger.info(f"Waiting {wait_time}s for results to load...")
            if await self._sleep_with_stop(wait_time, should_stop=should_stop):
                logger.warning("Stop requested while waiting for results load.")
                return 0

            # Guard: if search landed on a logged-out page, re-login and retry
            auth_after_search = await self._inspect_auth_state(page)
            if auth_after_search["logged_out"]:
                logger.warning(
                    "Search page appears logged out. Attempting login and retrying..."
                )
                account = getattr(self, "_current_account", {}) or {}
                if not account.get("password"):
                    logger.error(
                        "Cannot auto-login for account %s: password missing.",
                        account.get("uid", "unknown"),
                    )
                    return 0

                login_success = await login(page, account)
                if not login_success:
                    logger.error("Login retry failed after logged-out search page.")
                    return 0

                await self.browser_manager.save_cookies(page)
                logger.info("Login retry succeeded, re-opening search URL...")
                await page.goto(search_url, wait_until="domcontentloaded", timeout=120000)
                if await self._sleep_with_stop(
                    random.uniform(3, 5), should_stop=should_stop
                ):
                    logger.warning("Stop requested while waiting after login retry.")
                    return 0

            logger.info("Waiting for post elements to appear...")
            try:
                await page.wait_for_selector(
                    'blockquote.html-blockquote, div[data-ad-rendering-role="story_message"], div[role="article"]',
                    timeout=10000,
                )
                logger.info("Post elements found, starting extraction...")
            except Exception as e:
                logger.warning(f"Standard selectors not found, trying anyway: {e}")
                if await self._sleep_with_stop(10, should_stop=should_stop):
                    logger.warning("Stop requested while waiting for post detection.")
                    return 0

            posts_processed = await scroll_and_process_posts(
                page,
                keyword=keyword,
                max_results=max_results,
                browser_manager=self.browser_manager,
                current_account=self._current_account,
                db=self.db,
                sleep_with_stop=self._sleep_with_stop,
                should_stop=should_stop,
            )

            logger.info(
                f"=== Search completed for '{keyword}': {posts_processed} posts processed ==="
            )
            return posts_processed

        except Exception as e:
            logger.error(f"Error searching for '{keyword}': {e}", exc_info=True)
            return 0
