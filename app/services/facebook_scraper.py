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
from .fb_auto_login import load_login_accounts, login_on_page
from .fb_feed_scanner import scroll_and_process_posts
from .fb_login_verify import page_has_logged_in_reel_tab_link

logger = get_logger(__name__)

MAX_LOGIN_RETRIES = 2


class NoActiveCookieError(RuntimeError):
    """Raised when cookie-only mode has no valid logged-in session."""


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
        """
        Logged-in is strict: only true if the Reels tab link (/reel/?s=tab) exists in the DOM.
        Logged-out heuristics still help detect obvious login / checkpoint pages.
        """
        has_reel_tab = await page_has_logged_in_reel_tab_link(page)
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
                    const loggedOut =
                        hasLoginInputs ||
                        hasJoinCopy ||
                        (title.includes('page not found') && hasLoginButton);
                    return { loggedOut };
                }
                """
            )
            logged_out = bool(state.get("loggedOut"))
            return {
                "logged_out": logged_out,
                # User requirement: treat as logged in only when Reels tab nav link is present
                "logged_in": has_reel_tab and not logged_out,
            }
        except Exception as exc:
            logger.warning(f"Could not inspect auth state reliably: {exc}")
            return {"logged_out": False, "logged_in": False}

    async def _try_auto_login(self, stale_page: Optional[Page]) -> bool:
        """
        Rotate through accounts from config/accounts.json.

        Each attempt uses a **new** browser context with no cookies so Facebook
        shows the real login form. Reusing the stale session page would keep
        checkpoint redirects and hide #email for every account.
        """
        login_accounts = load_login_accounts()
        if not login_accounts:
            logger.error("Auto-login failed — no accounts in config/accounts.json")
            return False

        # Drop expired/checkpoint session so it cannot pollute login attempts
        if stale_page is not None:
            logger.info("Closing stale browser context before trying credentials...")
            await self.browser_manager.close_page_context(stale_page)
        self._current_page = None

        for i, account in enumerate(login_accounts):
            uid = account["uid"]
            logger.info(
                "Auto-login attempt %d/%d (UID: %s)",
                i + 1, len(login_accounts), uid,
            )
            trial_page: Optional[Page] = None
            try:
                trial_page = await self.browser_manager.create_fresh_page_for_login(uid)
                if await login_on_page(trial_page, account):
                    self._current_page = trial_page
                    self._current_account = account
                    logger.info("Auto-login succeeded with account %s", uid)
                    return True
            except Exception as exc:
                logger.warning("Auto-login error for %s: %s", uid, exc, exc_info=True)
            finally:
                if trial_page is not None and self._current_page is not trial_page:
                    await self.browser_manager.close_page_context(trial_page)

            logger.warning("Auto-login failed for account %s — trying next", uid)

        logger.error(
            "Auto-login exhausted all %d accounts — none could log in", len(login_accounts)
        )
        return False

    async def search_keyword(
        self,
        keyword: str,
        max_results: int = 10,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> int:
        """
        Search for a keyword and extract posts.

        If the session is expired at any point, automatically logs in
        using accounts from config/accounts.json and retries the keyword.
        """
        for attempt in range(MAX_LOGIN_RETRIES + 1):
            try:
                return await self._search_keyword_inner(keyword, max_results, should_stop)
            except NoActiveCookieError:
                if attempt >= MAX_LOGIN_RETRIES:
                    logger.error(
                        "Session expired for '%s' — exhausted %d login retries",
                        keyword, MAX_LOGIN_RETRIES,
                    )
                    raise
                logger.warning(
                    "Session expired for '%s' — auto-login attempt %d/%d",
                    keyword, attempt + 1, MAX_LOGIN_RETRIES,
                )
                stale = self._current_page
                if await self._try_auto_login(stale):
                    cur = self._current_page
                    if cur:
                        cur._kiro_has_loaded_cookies = True
                    logger.info("Auto-login succeeded — retrying keyword '%s'", keyword)
                    continue
                raise
        return 0

    async def _search_keyword_inner(
        self,
        keyword: str,
        max_results: int = 10,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> int:
        """Core search logic — raises NoActiveCookieError on expired session."""
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

            if not bool(getattr(self._current_page, "_kiro_has_loaded_cookies", False)):
                logger.warning("No saved cookie session — auto-login will be attempted")
                raise NoActiveCookieError("no active cookie")

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
                    logger.info("Already logged in (Reels tab link present)")
                    is_logged_in = True
                elif auth_state["logged_out"]:
                    logger.info("Login required (logged-out UI detected)")
                else:
                    logger.info(
                        "Not logged in for scraping: Reels tab link (/reel/?s=tab) not found on page"
                    )
            except Exception as e:
                logger.warning(f"Error checking login status: {e}")

            if not is_logged_in:
                logger.warning("Cookie session expired — auto-login will be attempted")
                raise NoActiveCookieError("no active cookie")

            logger.info("Cookie session verified (cookie-only mode)")

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

            auth_after_search = await self._inspect_auth_state(page)
            if auth_after_search["logged_out"] or not auth_after_search["logged_in"]:
                logger.warning(
                    "Not logged in on search page (Reels tab link missing or login UI) — auto-login will be attempted"
                )
                raise NoActiveCookieError("no active cookie")

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

        except NoActiveCookieError:
            raise
        except Exception as e:
            logger.error(f"Error searching for '{keyword}': {e}", exc_info=True)
            return 0
