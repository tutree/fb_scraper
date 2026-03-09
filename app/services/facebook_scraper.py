from playwright.async_api import Page
from typing import List, Dict, Optional, Callable
import asyncio
import random
import json
import pyotp
from pathlib import Path
from sqlalchemy.orm import Session
from ..models.search_result import SearchResult, ResultStatus
from ..models.post_comment import PostComment
from ..core.config import settings
from ..core.logging_config import get_logger
from tenacity import retry, stop_after_attempt, wait_exponential
from .facebook_comment_fix import EXTRACT_FROM_DIALOG_JS, expand_all_comments_in_dialog

logger = get_logger(__name__)


async def _human_mouse_move(page: Page, x: int, y: int) -> None:
    """Move mouse along a curved path to look human (not a straight teleport)."""
    try:
        # Current position unknown â€” start from a plausible location
        start_x = random.randint(200, 900)
        start_y = random.randint(200, 600)
        steps = random.randint(10, 25)
        for i in range(steps + 1):
            t = i / steps
            # Ease in/out curve + small jitter
            ease = t * t * (3 - 2 * t)
            cx = int(start_x + (x - start_x) * ease + random.randint(-3, 3))
            cy = int(start_y + (y - start_y) * ease + random.randint(-3, 3))
            await page.mouse.move(cx, cy)
            await asyncio.sleep(random.uniform(0.005, 0.020))
    except Exception:
        pass  # Non-critical


async def human_scroll(page: Page, scrolls: int = None) -> None:
    """Simulate human-like scrolling behavior."""
    if scrolls is None:
        scrolls = random.randint(3, 6)
    
    for _ in range(scrolls):
        # Random scroll distance â€” vary speed via multiple small steps
        scroll_amount = random.randint(300, 800)
        steps = random.randint(3, 8)
        per_step = scroll_amount // steps
        for _ in range(steps):
            await page.evaluate(f"window.scrollBy(0, {per_step + random.randint(-20, 20)})")
            await asyncio.sleep(random.uniform(0.05, 0.15))
        await asyncio.sleep(random.uniform(1.5, 4.0))
        
        # Sometimes scroll back up (humans do this)
        if random.random() < 0.3:
            back_scroll = random.randint(100, 300)
            await page.evaluate(f"window.scrollBy(0, -{back_scroll})")
            await asyncio.sleep(random.uniform(0.5, 2.0))
        
        # Random pause (reading content)
        if random.random() < 0.4:
            await asyncio.sleep(random.uniform(2.0, 5.0))
        
        # Move mouse while reading
        await _human_mouse_move(page, random.randint(200, 1200), random.randint(200, 700))


async def warmup_session(page: Page) -> None:
    """Browse like a human before scraping to build session credibility."""
    try:
        logger.info("Starting session warmup...")
        
        # Go to homepage first
        await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=90000)
        await asyncio.sleep(random.uniform(3, 6))
        
        # Move mouse around the page naturally before anything else
        for _ in range(random.randint(4, 7)):
            await _human_mouse_move(page, random.randint(100, 1300), random.randint(100, 700))
            await asyncio.sleep(random.uniform(0.4, 1.2))
        
        # Simulate reading the feed by scrolling slowly with pauses
        for _ in range(random.randint(3, 5)):
            await page.evaluate(f"window.scrollBy(0, {random.randint(150, 400)})")
            await asyncio.sleep(random.uniform(1.5, 3.5))
            # Move mouse as if hovering over a post
            await _human_mouse_move(page, random.randint(300, 900), random.randint(200, 600))
            await asyncio.sleep(random.uniform(0.5, 1.5))
        
        # Occasionally scroll back to top like a normal user
        if random.random() < 0.4:
            await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            await asyncio.sleep(random.uniform(1, 2.5))
        
        # Optionally visit one more safe page (notifications or own profile)
        if random.random() < 0.35:
            try:
                await page.goto("https://www.facebook.com/notifications", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(random.uniform(3, 6))
                await _human_mouse_move(page, random.randint(300, 800), random.randint(200, 500))
                await asyncio.sleep(random.uniform(1, 2))
            except Exception:
                pass
        
        logger.info("Session warmup completed")
    except Exception as e:
        logger.warning(f"Warmup session error (non-critical): {e}")

CREDENTIALS_PATH = Path("config/credentials.json")
COOKIE_DIRS = [Path("cookies"), Path("config/cookies")]


def _extract_c_user_from_cookie_json(data: object) -> Optional[str]:
    if isinstance(data, dict):
        cookies = data.get("cookies")
        if not isinstance(cookies, list):
            return None
    elif isinstance(data, list):
        cookies = data
    else:
        return None

    for cookie in cookies:
        if isinstance(cookie, dict) and cookie.get("name") == "c_user":
            value = cookie.get("value")
            if value:
                return str(value)
    return None


def _cookie_uid_order() -> List[str]:
    """Return cookie-backed account ids ordered by freshest cookie file first."""
    uid_mtime: Dict[str, float] = {}
    for directory in COOKIE_DIRS:
        if not directory.exists():
            continue
        for cookie_file in directory.glob("*.json"):
            try:
                mtime = cookie_file.stat().st_mtime
            except Exception:
                mtime = 0.0

            stem = cookie_file.stem.strip()
            if stem.isdigit():
                uid_mtime[stem] = max(uid_mtime.get(stem, 0.0), mtime)

            try:
                with open(cookie_file, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                c_user = _extract_c_user_from_cookie_json(data)
                if c_user:
                    uid_mtime[c_user] = max(uid_mtime.get(c_user, 0.0), mtime)
            except Exception:
                continue

    return [
        uid
        for uid, _ in sorted(uid_mtime.items(), key=lambda item: item[1], reverse=True)
    ]

def load_accounts() -> List[Dict]:
    """Load Facebook accounts from credentials file."""
    logger.info(f"Loading Facebook accounts from: {CREDENTIALS_PATH.absolute()}")
    
    if CREDENTIALS_PATH.exists():
        try:
            # utf-8-sig tolerates BOM-prefixed JSON files commonly produced on Windows.
            with open(CREDENTIALS_PATH, encoding="utf-8-sig") as f:
                data = json.load(f)

            all_accounts = data.get("facebook_accounts", [])
            active_accounts = [a for a in all_accounts if a.get("active")]
            cookie_uid_order = _cookie_uid_order()
            logger.info(f"Found {len(all_accounts)} total accounts, {len(active_accounts)} active")

            if cookie_uid_order:
                logger.info(f"Found cookie sessions for {len(cookie_uid_order)} account uid(s)")

            selected_accounts: List[Dict] = []
            if active_accounts:
                active_by_uid = {
                    str(account.get("uid", "")).strip(): account
                    for account in active_accounts
                    if str(account.get("uid", "")).strip()
                }
                ordered_active = [
                    active_by_uid[uid]
                    for uid in cookie_uid_order
                    if uid in active_by_uid
                ]
                if ordered_active:
                    logger.info(
                        "Prioritizing active accounts with freshest cookies: %s",
                        [a.get("uid") for a in ordered_active],
                    )
                merged = ordered_active + active_accounts
                deduped: List[Dict] = []
                seen = set()
                for account in merged:
                    uid = str(account.get("uid", "")).strip()
                    if not uid or uid in seen:
                        continue
                    seen.add(uid)
                    deduped.append(account)
                selected_accounts = deduped
            else:
                logger.warning("No active accounts found in credentials file")
                if cookie_uid_order:
                    account_by_uid = {
                        str(account.get("uid", "")).strip(): account
                        for account in all_accounts
                        if str(account.get("uid", "")).strip()
                    }
                    fallback_cookie_accounts = [
                        account_by_uid[uid]
                        for uid in cookie_uid_order
                        if uid in account_by_uid
                    ]
                    if fallback_cookie_accounts:
                        logger.warning(
                            "Falling back to cookie-backed accounts: %s",
                            [a.get("uid") for a in fallback_cookie_accounts],
                        )
                        selected_accounts = fallback_cookie_accounts

            for acc in selected_accounts:
                uid = acc.get("uid", "Unknown")
                has_totp = "Yes" if acc.get("totp_secret") else "No"
                logger.info(f"  - Account: {uid}, 2FA configured: {has_totp}")

            return selected_accounts
        except Exception as exc:
            logger.error(
                "Failed to parse credentials file '%s': %s. Falling back to environment variables.",
                CREDENTIALS_PATH,
                exc,
            )
    
    # Fallback to env-based single account
    if CREDENTIALS_PATH.exists():
        logger.warning("Using environment variables due to credentials file parse failure")
    else:
        logger.warning(f"Credentials file not found at {CREDENTIALS_PATH}, using environment variables")
    env_account = {
        "uid": settings.FACEBOOK_EMAIL,
        "password": settings.FACEBOOK_PASSWORD,
        "totp_secret": None,
    }
    logger.info(f"Using env account: {env_account['uid']}")
    return [env_account]


def generate_2fa_code(totp_secret: str) -> str:
    """Generate current TOTP 2FA code from secret key."""
    totp = pyotp.TOTP(totp_secret)
    return totp.now()


class FacebookScraper:
    def __init__(self, db: Session, browser_manager):
        self.db = db
        self.browser_manager = browser_manager
        self.accounts = load_accounts()
        self.account_index = 0
        
        logger.info(f"FacebookScraper initialized with {len(self.accounts)} accounts")
        if not self.accounts:
            logger.error("No Facebook accounts available! Scraping will fail.")
        else:
            # Use only the first account (no rotation)
            logger.info(f"Using single account: {self.accounts[0].get('uid', 'Unknown')}")

    def _get_next_account(self) -> Dict:
        """Get the first account (no rotation)."""
        if not self.accounts:
            logger.error("No accounts available for selection")
            return {}
            
        account = self.accounts[0]  # Always use first account
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
        """Sleep in short chunks and abort early when stop is requested."""
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
                    const hasLoginInputs = !!document.querySelector('input[name="email"], input[name="pass"], #email, #pass');
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
                    const hasProfileLink = !!document.querySelector('a[href*="/profile.php"], a[href*="/me/"]');
                    const hasSearchInput = !!document.querySelector('input[type="search"], input[placeholder*="Search"], input[aria-label*="Search"]');

                    const loggedOut = hasLoginInputs || hasJoinCopy || (title.includes('page not found') && hasLoginButton);
                    const loggedIn = !loggedOut && (hasNav || hasFeed || hasProfileLink || hasSearchInput);
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

    async def _expand_inline_comments(
        self,
        page: Page,
        max_cycles: int = 180,
        stall_limit: int = 14,
    ) -> int:
        """
        Expand visible inline "more comments/replies" controls on post pages.
        Waits for lazy rendering and stops when no growth is observed repeatedly.
        """
        no_progress_cycles = 0
        best_count = 0

        for _ in range(max_cycles):
            state = await page.evaluate(
                """
                () => {
                    const root = document;
                    const clickables = root.querySelectorAll('div[role="button"], span[role="button"], a[role="button"], a, span');
                    const include = [
                        /view more comments?/i,
                        /view previous comments?/i,
                        /see more comments?/i,
                        /more comments?/i,
                        /view\\s+\\d+\\s+more\\s+repl/i,
                        /view more repl(?:y|ies)/i,
                        /more repl(?:y|ies)/i,
                    ];
                    const exclude = /(leave\\s*a\\s*comment|write\\s*a\\s*comment|comment\\s+as|most relevant|all comments|newest)/i;
                    let clicked = 0;

                    for (const el of clickables) {
                        const text = (el.innerText || el.textContent || '').trim();
                        if (!text || text.length > 120) continue;
                        if (exclude.test(text)) continue;
                        if (!include.some((rx) => rx.test(text))) continue;

                        const visible = !!(el.offsetParent || (el.getClientRects && el.getClientRects().length));
                        if (!visible) continue;

                        try {
                            el.click();
                            clicked += 1;
                        } catch (_) {}
                    }

                    const count = document.querySelectorAll('div[role="article"][aria-label^="Comment by"]').length;
                    return { clicked, count };
                }
                """
            )

            clicked = int(state.get("clicked", 0))
            count = int(state.get("count", 0))

            if count > best_count:
                best_count = count
                no_progress_cycles = 0
            elif clicked == 0:
                no_progress_cycles += 1

            await page.evaluate("window.scrollBy(0, 900)")
            await asyncio.sleep(random.uniform(2.0, 4.0) if clicked > 0 else random.uniform(1.0, 2.2))

            if no_progress_cycles >= stall_limit:
                break

        return best_count

    async def _extract_comments(self, page: Page, search_result_id: str, max_comments: int = 0) -> int:
        """
        Extract comments from the current post page.
        If max_comments <= 0, attempt to load and extract all available comments.
        """
        try:
            limit = self._resolve_comment_limit(max_comments)
            logger.info(f"  Extracting comments (limit={limit if max_comments > 0 else 'ALL'})...")

            await asyncio.sleep(random.uniform(1.2, 2.2))

            try:
                logger.info("  Looking for 'Comment' button...")
                comment_button_selectors = [
                    'div[aria-label="Comment"]',
                    'div[role="button"]:has-text("Comment")',
                    'span:has-text("Comment")',
                    '[aria-label="Leave a comment"]',
                ]
                for selector in comment_button_selectors:
                    try:
                        if await page.is_visible(selector, timeout=2000):
                            await page.click(selector)
                            await asyncio.sleep(random.uniform(2.0, 3.2))
                            break
                    except Exception:
                        continue
            except Exception as exc:
                logger.debug(f"  Could not click Comment button: {exc}")

            has_dialog = await page.evaluate("() => !!document.querySelector('[role=\"dialog\"]')")

            if has_dialog:
                logger.info("  Comments opened in dialog, expanding all comments/replies...")
                await expand_all_comments_in_dialog(page, root_selector='[role="dialog"]', max_cycles=120, stall_limit=10)
                comments_data = await page.evaluate(EXTRACT_FROM_DIALOG_JS, limit)
            else:
                await self._expand_inline_comments(page, max_cycles=60, stall_limit=8)
                logger.info("  Extracting comment data from inline page comments...")
                comments_data = await page.evaluate(
                    """
                    (maxComments) => {
                        const comments = [];
                        const seen = new Set();

                        function getText(el) { return el ? (el.innerText || el.textContent || '').trim() : ''; }
                        function isObfuscated(text) {
                            if (!text || text.length < 10) return true;
                            if (/shared with public/i.test(text)) return true;
                            if (/february|january|march|april|may|june|july|august|september|october|november|december/i.test(text) && /at \\d|\\d+:\\d+/.test(text)) return true;
                            if ((text.match(/-/g) || []).length > 3 && text.length < 80) return true;
                            if (/^[^a-zA-Z]*[a-zA-Z]-+[a-zA-Z]-+[a-zA-Z]/.test(text)) return true;
                            return false;
                        }
                        const SKIP = /^(Like|Reply|Share|Comment|Facebook|Anonymous participant|\\d+[smhd]|Just now|Yesterday|See more|\\d+ min|\\d+ hr|\\d+ (w|d|m|y))/i;
                        function isProfileUrl(url) {
                            if (!url || !url.includes('facebook.com')) return false;
                            if (url.includes('/groups/') || url.includes('/pages/') || url.includes('/events/')) return false;
                            return true;
                        }
                        function commentKey(authorName, authorUrl, commentText, timestamp) {
                            const who = (authorUrl || authorName || '').trim().toLowerCase();
                            const body = (commentText || '').trim().toLowerCase();
                            const ts = (timestamp || '').trim().toLowerCase();
                            return `${who}|${body}|${ts}`;
                        }

                        const articles = document.querySelectorAll('div[role="article"][aria-label^="Comment by"]');
                        for (const parent of articles) {
                            if (comments.length >= maxComments) break;
                            const authorLink = parent.querySelector('a[href*="facebook.com"]');
                            if (!authorLink || !isProfileUrl(authorLink.href)) continue;
                            const authorName = getText(authorLink);
                            const authorUrl = authorLink.href;
                            if (!authorName || authorName.length < 2) continue;

                            let commentText = '';
                            const textDivs = parent.querySelectorAll('div[dir="auto"][style*="text-align"], div[dir="auto"], span[dir="auto"]');
                            for (const d of textDivs) {
                                const t = getText(d);
                                if (t && t.length > 10 && t !== authorName && !SKIP.test(t) && !isObfuscated(t)) {
                                    commentText = t;
                                    break;
                                }
                            }
                            if (!commentText) {
                                const lines = getText(parent).split('\\n').map((l) => l.trim()).filter((l) =>
                                    l.length > 10 && l !== authorName && !SKIP.test(l) && !isObfuscated(l)
                                );
                                if (lines.length) commentText = lines[0];
                            }

                            let timestamp = null;
                            for (const s of parent.querySelectorAll('span, abbr')) {
                                const t = getText(s);
                                if (/\\d+[smhd]|Just now|Yesterday|\\d+ min|\\d+ hr|\\d+ (w|d|m|y)/i.test(t)) {
                                    timestamp = t;
                                    break;
                                }
                            }

                            if (authorName && commentText && commentText.length > 5 && !isObfuscated(commentText)) {
                                const key = commentKey(authorName, authorUrl, commentText, timestamp || 'Unknown');
                                if (seen.has(key)) continue;
                                seen.add(key);
                                comments.push({
                                    author_name: authorName,
                                    author_profile_url: authorUrl,
                                    comment_text: commentText,
                                    comment_timestamp: timestamp || 'Unknown'
                                });
                            }
                        }
                        return comments;
                    }
                    """,
                    limit,
                )

            saved_count = 0
            for comment_data in comments_data:
                try:
                    comment = PostComment(
                        search_result_id=search_result_id,
                        author_name=comment_data.get('author_name'),
                        author_profile_url=comment_data.get('author_profile_url'),
                        comment_text=comment_data.get('comment_text'),
                        comment_timestamp=comment_data.get('comment_timestamp'),
                    )
                    self.db.add(comment)
                    saved_count += 1
                except Exception as exc:
                    logger.warning(f"  Failed to save comment: {exc}")

            if saved_count > 0:
                self.db.commit()
                logger.info(f"  Saved {saved_count} comments")
            else:
                logger.info("  No comments found")

            if has_dialog:
                try:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.4)
                except Exception:
                    pass

            return saved_count
        except Exception as exc:
            logger.error(f"  Error extracting comments: {exc}")
            return 0

    async def _click_comments_and_extract_from_dialog(
        self, page: Page, profile_url: str, max_comments: int = 0
    ) -> List[Dict]:
        """
        On the search results page: find the post containing this profile link,
        click its Comments button to open the dialog, extract comments, then close with ESC.
        Returns list of comment dicts (author_name, author_profile_url, comment_text, comment_timestamp).
        Caller should persist these after profile extraction and storage (when search_result_id is known).
        """
        comments_data = []
        try:
            limit = self._resolve_comment_limit(max_comments)
            # Normalize profile URL for matching (strip trailing slash, lowercase for comparison)
            profile_path = profile_url.split("?")[0].rstrip("/").lower()

            # Find the card containing this profile link and click its Comments button
            clicked = await page.evaluate(
                """
                (profilePath) => {
                    function normalizeUrl(u) {
                        try {
                            const url = new URL(u, window.location.origin);
                            return (url.origin + url.pathname).replace(/\\/$/, '').toLowerCase();
                        } catch (_) {
                            return (u || '').split('?')[0].replace(/\\/$/, '').toLowerCase();
                        }
                    }

                    const pathToMatch = normalizeUrl(profilePath);
                    const feed = document.querySelector('div[role="feed"]');
                    const articles = document.querySelectorAll('div[role="article"]');
                    const containers = articles.length > 0 ? Array.from(articles) : (feed ? Array.from(feed.children) : []);

                    for (const article of containers) {
                        const anchors = article.querySelectorAll('a[href*="facebook.com"]');
                        let match = false;
                        for (const a of anchors) {
                            const href = normalizeUrl(a.href || '');
                            if (pathToMatch && href && (href.includes(pathToMatch) || pathToMatch.includes(href))) {
                                match = true;
                                break;
                            }
                        }
                        if (!match) continue;

                        // Click "X comments" (e.g. "12 comments") - NOT "Comment" or "Leave a comment"
                        const buttons = article.querySelectorAll('div[role="button"], span[role="button"], a[role="button"]');
                        for (const btn of buttons) {
                            const text = (btn.textContent || '').trim();
                            if (/\\d+\\s*comments?/i.test(text) && !/leave\\s*a\\s*comment/i.test(text)) {
                                btn.click();
                                return true;
                            }
                        }
                        const spans = article.querySelectorAll('span');
                        for (const s of spans) {
                            const t = (s.textContent || '').trim();
                            if (/^\\d+\\s*comments?$/i.test(t) && s.offsetParent) {
                                s.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }
                """,
                profile_path,
            )

            if not clicked:
                logger.info("  Comments button not found for this post, skipping dialog extraction")
                return comments_data

            await asyncio.sleep(random.uniform(2.0, 3.5))  # Wait for dialog to open
            await expand_all_comments_in_dialog(page, root_selector='[role="dialog"]')

            # Extract comments from the dialog (innerText, Comment-by filter, obfuscation rejection)
            comments_data = await page.evaluate(EXTRACT_FROM_DIALOG_JS, limit)

            logger.info(f"  Extracted {len(comments_data)} comments from dialog")

        except Exception as e:
            logger.warning(f"  Could not extract comments from dialog: {e}")
        finally:
            # Always close dialog with ESC
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except Exception:
                pass

        return comments_data

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    async def login(self, page: Page, account: Dict) -> bool:
        """Login to Facebook with UID/password and handle 2FA automatically."""
        uid = account["uid"]
        password = account["password"]
        totp_secret = account.get("totp_secret")

        logger.info(f"=== Starting login process for: {uid} ===")
        
        try:
            logger.info("Navigating to Facebook login page...")
            await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=90000)
            logger.info("Login page loaded")
            
            # Human-like delay before interacting - look around first
            delay = random.uniform(2.0, 4.0)
            logger.info(f"Waiting {delay:.1f}s before interacting (human-like)...")
            await asyncio.sleep(delay)
            
            # Random mouse movement before typing
            logger.info("Performing random mouse movements...")
            await page.mouse.move(
                random.randint(200, 400), 
                random.randint(200, 400),
                steps=random.randint(10, 20)
            )
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # Type email with human-like delays
            logger.info("Looking for email field...")
            email_field = await page.query_selector("#email, input[name='email'], input[type='text'], input[type='email']")
            if email_field:
                logger.info("Email field found, typing email...")
                await email_field.click()
                await asyncio.sleep(random.uniform(0.3, 0.8))
                for char in uid:
                    await page.keyboard.type(char)
                    await asyncio.sleep(random.uniform(0.05, 0.15))
                logger.info("Email entered")
            else:
                logger.error("Email field not found!")
                return False
            
            await asyncio.sleep(random.uniform(0.8, 1.8))
            
            # Type password with human-like delays
            logger.info("Looking for password field...")
            pass_field = await page.query_selector("#pass, input[name='pass'], input[type='password']")
            if pass_field:
                logger.info("Password field found, typing password...")
                await pass_field.click()
                await asyncio.sleep(random.uniform(0.3, 0.8))
                for char in password:
                    await page.keyboard.type(char)
                    await asyncio.sleep(random.uniform(0.05, 0.15))
                logger.info("Password entered")
            else:
                logger.error("Password field not found!")
                return False

            await asyncio.sleep(random.uniform(0.5, 1.2))

            # Click login button
            logger.info("Clicking login button...")
            await page.click('button[name="login"]')

            # Wait for either dashboard or 2FA screen
            logger.info("Waiting for page to load after login...")
            await page.wait_for_load_state("domcontentloaded", timeout=90000)
            logger.info("Page loaded, checking for 2FA...")

            # Handle 2FA checkpoint
            if await page.is_visible('input[name="approvals_code"]'):
                logger.info("2FA checkpoint detected")
                if not totp_secret:
                    logger.error(f"2FA required for {uid} but no TOTP secret configured")
                    return False

                code = generate_2fa_code(totp_secret)
                logger.info(f"Generated 2FA code: {code}")

                logger.info("Entering 2FA code...")
                await page.fill('input[name="approvals_code"]', code)
                await asyncio.sleep(0.5)

                # Click the submit/continue button
                logger.info("Looking for 2FA submit button...")
                submit_btn = await page.query_selector(
                    'button[type="submit"], #checkpointSubmitButton'
                )
                if submit_btn:
                    logger.info("Clicking 2FA submit button...")
                    await submit_btn.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=90000)
                    logger.info("2FA submitted, page loaded")
                else:
                    logger.warning("2FA submit button not found")

                # If "Save browser" prompt appears, click "Continue"
                logger.info("Checking for 'Save browser' prompt...")
                continue_btn = await page.query_selector(
                    'button[name="submit[Continue]"], button#checkpointSubmitButton'
                )
                if continue_btn:
                    logger.info("'Save browser' prompt found, clicking Continue...")
                    await continue_btn.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=90000)
                    logger.info("Continued past save browser prompt")
                else:
                    logger.info("No 'Save browser' prompt found")
            else:
                logger.info("No 2FA checkpoint detected")

            # Verify we are logged in
            logger.info("Verifying login success...")
            nav = await page.query_selector('div[role="navigation"]')
            if nav:
                logger.info(f"âœ“ Successfully logged in as {uid}")
                return True

            logger.error(f"Login failed for {uid} - no navigation found")
            return False

        except Exception as e:
            logger.error(f"Login exception for {uid}: {e}", exc_info=True)
            raise

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

        # Reuse existing page or create new one
        if not hasattr(self, '_current_page') or self._current_page is None:
            account = self._get_next_account()
            self._current_account = account  # Persist for use in _scroll_and_process_posts
            logger.info(f"Using account: {account.get('uid', 'Unknown')}")
            logger.info("Creating browser page...")
            
            # Use the new method that loads cookies
            self._current_page = await self.browser_manager.create_page_with_cookies(account.get('uid'))
            logger.info("Browser page created successfully")

            # Check if already logged in by looking for navigation
            logger.info("Checking if already logged in...")
            try:
                await self._current_page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=60000)
                # Wait for page to fully render
                await asyncio.sleep(4)
            except Exception as e:
                logger.warning(f"Page load issue (continuing anyway): {e}")
            
            # Check for logged-in indicators - try multiple selectors
            is_logged_in = False
            try:
                auth_state = await self._inspect_auth_state(self._current_page)
                if auth_state["logged_in"]:
                    logger.info("âœ“ Already logged in (session restored from cookies)")
                    is_logged_in = True
                elif auth_state["logged_out"]:
                    logger.info("Login required (logged-out markers detected)")
                else:
                    logger.info("Auth state uncertain; will require explicit login to avoid false positives")
            except Exception as e:
                logger.warning(f"Error checking login status: {e}")
            
            if not is_logged_in:
                logger.info("Not logged in, attempting login...")
                login_success = await self.login(self._current_page, account)
                if not login_success:
                    logger.error("Login failed, aborting search")
                    return 0
                logger.info("Login successful")
                
                # Save cookies after successful login
                logger.info("Saving session cookies for future use...")
                await self.browser_manager.save_cookies(self._current_page)
            else:
                logger.info("Skipping login (already authenticated)")
            
            # Skip warmup - we have valid cookies and it's not necessary for stealth
            # The random delays and human-like behavior in the scraper are sufficient
            logger.info("Skipping session warmup (using saved cookies)")
        else:
            logger.info("Reusing existing browser session")

        page = self._current_page

        try:
            # Human-like delay before searching
            delay = random.uniform(3, 7)
            logger.info(f"Waiting {delay:.1f}s before searching...")
            if await self._sleep_with_stop(delay, should_stop=should_stop):
                logger.warning("Stop requested before search navigation.")
                return 0
            
            # Check if we're already on Facebook, if not navigate there
            current_url = page.url
            if not (
                current_url.startswith("https://www.facebook.com")
                or current_url.startswith("https://web.facebook.com")
            ):
                logger.info("Navigating to Facebook homepage...")
                await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=60000)
                if await self._sleep_with_stop(random.uniform(2, 4), should_stop=should_stop):
                    logger.warning("Stop requested after homepage navigation.")
                    return 0
            else:
                logger.info(f"Already on Facebook (URL: {current_url}), skipping navigation")
            
            # Use direct search URL instead of typing (faster and more reliable)
            from urllib.parse import quote_plus
            search_url = f"https://www.facebook.com/search/posts/?q={quote_plus(keyword)}"
            logger.info(f"Navigating to search URL: {search_url}")
            # Use networkidle for more reliable loading with high-latency proxy
            try:
                await page.goto(search_url, wait_until="networkidle", timeout=120000)
            except Exception as e:
                logger.warning(f"networkidle wait failed, trying domcontentloaded: {e}")
                await page.goto(search_url, wait_until="domcontentloaded", timeout=120000)
            
            # Wait and look around before scraping
            wait_time = random.uniform(4, 8)
            logger.info(f"Waiting {wait_time:.1f}s for results to load...")
            if await self._sleep_with_stop(wait_time, should_stop=should_stop):
                logger.warning("Stop requested while waiting for results load.")
                return 0

            # Guardrail: if search URL landed on logged-out/page-not-found login wall, login and retry once.
            auth_after_search = await self._inspect_auth_state(page)
            if auth_after_search["logged_out"]:
                logger.warning("Search page appears logged out. Attempting login and retrying search URL once...")
                account = getattr(self, "_current_account", {}) or {}
                if not account.get("password"):
                    logger.error(
                        "Cannot auto-login for account %s: password missing in credentials.",
                        account.get("uid", "unknown"),
                    )
                    return 0

                login_success = await self.login(page, account)
                if not login_success:
                    logger.error("Login retry failed after logged-out search page.")
                    return 0

                await self.browser_manager.save_cookies(page)
                logger.info("Login retry succeeded, re-opening search URL...")
                await page.goto(search_url, wait_until="domcontentloaded", timeout=120000)
                if await self._sleep_with_stop(random.uniform(3, 5), should_stop=should_stop):
                    logger.warning("Stop requested while waiting after login retry.")
                    return 0
            
            logger.info("Waiting for post elements to appear...")
            # Try multiple selectors for posts
            try:
                await page.wait_for_selector('blockquote.html-blockquote, div[data-ad-rendering-role="story_message"], div[role="article"]', timeout=30000)
                logger.info("âœ“ Post elements found, starting extraction...")
                
            except Exception as e:
                logger.warning(f"Standard selectors not found, trying alternative approach: {e}")
                # Wait a bit and try to extract anyway
                if await self._sleep_with_stop(5, should_stop=should_stop):
                    logger.warning("Stop requested while waiting for alternative post detection.")
                    return 0

            # Process posts one by one as we scroll
            posts_processed = await self._scroll_and_process_posts(page, keyword, max_results, should_stop=should_stop)
            logger.info(f"Processing completed. Processed {posts_processed} posts")

            logger.info(f"=== Search completed for '{keyword}': {posts_processed} posts processed ===")
            return posts_processed

        except Exception as e:
            logger.error(f"Error searching for '{keyword}': {e}", exc_info=True)
            return 0
        # Note: Don't close page here - reuse it for next keyword

    async def _scroll_and_process_posts(
        self,
        page: Page,
        keyword: str,
        max_results: int,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> int:
        """Scroll, extract author profile links semantically, visit profiles, save users to database."""
        logger.info(f"Starting extraction for keyword: '{keyword}' (target: {max_results} posts)")
        
        # Scroll repeatedly up-front so Facebook actually loads feed cards before extraction.
        logger.info("Preloading search feed with progressive scrolls...")
        for i in range(8):
            if should_stop and should_stop():
                logger.warning("Stop requested before scroll warmup completed.")
                return 0
            await page.evaluate("window.scrollBy(0, 1800)")
            if await self._sleep_with_stop(random.uniform(1.5, 2.8), should_stop=should_stop):
                logger.warning("Stop requested during scroll warmup delay.")
                return 0
            if i % 3 == 2:
                # Periodic longer pause gives FB time to hydrate newer cards.
                if await self._sleep_with_stop(random.uniform(2.5, 4.5), should_stop=should_stop):
                    logger.warning("Stop requested during extended warmup pause.")
                    return 0

        # Save a screenshot for debugging
        try:
            safe_kw = keyword[:30].replace(' ', '_').replace('/', '_')
            screenshot_path = f"/app/logs/debug_{safe_kw}.png"
            await page.screenshot(path=screenshot_path, full_page=False)
            logger.info(f"Screenshot saved: {screenshot_path}")
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")

        # Diagnostic: log current URL and page structure
        current_url = page.url
        logger.info(f"Current page URL: {current_url}")
        page_diag = await page.evaluate(
            """
            () => ({
                title: document.title,
                articles: document.querySelectorAll('div[role="article"]').length,
                feed: !!document.querySelector('div[role="feed"]'),
                totalAnchors: document.querySelectorAll('a[href]').length,
                bodySnippet: document.body ? document.body.innerText.slice(0, 300) : 'NO BODY',
            })
            """
        )
        logger.info(f"Page diagnostics: title={page_diag.get('title')!r}, "
                    f"articles={page_diag.get('articles')}, feed={page_diag.get('feed')}, "
                    f"anchors={page_diag.get('totalAnchors')}")
        logger.info(f"Page body snippet: {page_diag.get('bodySnippet')!r}")

        # Get current user ID from cookies to exclude own profile
        current_user_id = self._current_account.get('uid', '')
        logger.info(f"Current user ID (to exclude): {current_user_id}")

        # Extract author profile links â€” use a.href (resolved absolute URL by browser)
        # NOT a[href*="facebook.com"] which only matches the raw HTML attribute
        logger.info("Extracting author profile links and post content via semantic DOM traversal...")
        all_links = await page.evaluate(
            """
            (currentUserId) => {
                const results = [];
                const seen = new Set();
                const BASE = location.origin; // https://www.facebook.com

                const NON_PROFILE = new Set([
                    'pages', 'groups', 'events', 'marketplace', 'watch', 'gaming',
                    'ads', 'search', 'stories', 'notifications', 'messages',
                    'friends', 'bookmarks', 'memory', 'help', 'privacy', 'terms',
                    'hashtag', 'reel', 'reels', 'live', 'photo', 'photos', 'video',
                    'videos', 'login', 'recover', 'checkpoint', 'settings', 'composer',
                    'sharer', 'dialog', 'share', 'l.php', 'ajax', 'api'
                ]);

                // a.href is always the fully resolved absolute URL in the browser
                function isProfileHref(absoluteHref) {
                    if (!absoluteHref || !absoluteHref.includes('facebook.com')) return false;
                    
                    // Exclude current user's own profile
                    if (currentUserId && absoluteHref.includes(currentUserId)) return false;
                    
                    try {
                        const u = new URL(absoluteHref);
                        const parts = u.pathname.replace(/^\\//, '').replace(/\\/$/, '').split('/');
                        const slug = parts[0];
                        if (!slug) return false;
                        if (NON_PROFILE.has(slug.toLowerCase())) return false;
                        if (/^(groups|events|pages|hashtag|watch|gaming|marketplace|reel|reels|stories|live|photo|photos|video|videos|posts|permalink|story\\.php|share|sharer|composer|checkpoint|login|ajax)/.test(slug)) return false;
                        if (u.search.includes('comment_id=')) return false;
                        // profile.php is always personal
                        if (slug === 'profile.php') return true;
                        // Real slug: alphanumeric + dots/underscores/hyphens, no sub-path
                        return /^[A-Za-z0-9._-]{2,}$/.test(slug) && parts.length === 1;
                    } catch(e) { return false; }
                }

                function extractPostContent(article) {
                    // Try to find the post text content within the article
                    // Look for common post content selectors
                    const contentSelectors = [
                        'div[data-ad-rendering-role="story_message"]',
                        'div[data-ad-comet-preview="message"]',
                        'div[dir="auto"][style*="text-align"]',
                        'span[dir="auto"]'
                    ];
                    
                    for (const selector of contentSelectors) {
                        const elem = article.querySelector(selector);
                        if (elem && elem.textContent.trim().length > 20) {
                            return elem.textContent.trim();
                        }
                    }
                    
                    // Fallback: get all text from the article, but limit to first 500 chars
                    const text = article.textContent.trim();
                    return text.length > 500 ? text.substring(0, 500) + '...' : text;
                }

                function parseCount(raw) {
                    if (!raw) return null;
                    const text = String(raw).trim().toUpperCase();
                    const cleaned = text.replace(/,/g, '').replace(/\s+/g, '');
                    const m = cleaned.match(/^(\d+(?:\.\d+)?)([KMB])?$/);
                    if (!m) return null;
                    const num = parseFloat(m[1]);
                    const unit = m[2] || '';
                    if (!Number.isFinite(num)) return null;
                    if (unit === 'K') return Math.round(num * 1000);
                    if (unit === 'M') return Math.round(num * 1000000);
                    if (unit === 'B') return Math.round(num * 1000000000);
                    return Math.round(num);
                }

                function extractEngagementCounts(article) {
                    const result = { reactions: null, comments: null, shares: null };
                    const fullText = article.innerText || '';

                    // Examples: "23 comments", "2 shares", "1.2K comments"
                    const commentMatch = fullText.match(/(\d+(?:\.\d+)?\s*[KMB]?)\s+comments?/i);
                    const shareMatch = fullText.match(/(\d+(?:\.\d+)?\s*[KMB]?)\s+shares?/i);
                    if (commentMatch) result.comments = parseCount(commentMatch[1]);
                    if (shareMatch) result.shares = parseCount(shareMatch[1]);

                    // Reaction summary often appears in aria-label or compact text near footer.
                    const ariaNodes = article.querySelectorAll('[aria-label]');
                    for (const node of ariaNodes) {
                        const label = (node.getAttribute('aria-label') || '').trim();
                        if (!label) continue;

                        // Examples: "23 reactions", "1.2K people reacted to this"
                        const m =
                            label.match(/(\d+(?:\.\d+)?\s*[KMB]?)\s+reactions?/i) ||
                            label.match(/(\d+(?:\.\d+)?\s*[KMB]?)\s+people\s+reacted/i);
                        if (m) {
                            result.reactions = parseCount(m[1]);
                            break;
                        }
                    }

                    if (result.reactions == null) {
                        const reactionTextMatch = fullText.match(/(\d+(?:\.\d+)?\s*[KMB]?)\s+reactions?/i);
                        if (reactionTextMatch) {
                            result.reactions = parseCount(reactionTextMatch[1]);
                        }
                    }

                    return result;
                }

                function isPostUrl(href) {
                    if (!href) return false;
                    return (
                        href.includes('/posts/') ||
                        href.includes('/permalink/') ||
                        href.includes('story_fbid') ||
                        href.includes('/photo/')
                    );
                }

                function normalizeText(value) {
                    return (value || '').replace(/\\s+/g, ' ').trim();
                }

                function isLikelyPostDate(value) {
                    const text = normalizeText(value);
                    if (!text) return false;
                    if (/^(?:\\d+\\s*(?:s|m|min|h|hr|d|w|mo|y)|just now|yesterday)$/i.test(text)) return true;
                    if (/\\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december|today|yesterday)\\b/i.test(text)) return true;
                    if (/\\b\\d{1,2}:\\d{2}\\b/.test(text)) return true;
                    if (/\\b\\d+\\s*(?:mins?|minutes?|hrs?|hours?|days?|weeks?|months?|years?)\\b/i.test(text)) return true;
                    return false;
                }

                function readFromAriaLabelledBy(node) {
                    if (!node || !node.getAttribute) return null;
                    const labelledBy = node.getAttribute('aria-labelledby');
                    if (!labelledBy) return null;
                    for (const id of labelledBy.split(/\s+/).filter(Boolean)) {
                        const target = document.getElementById(id);
                        if (!target) continue;
                        const text = normalizeText(target.innerText || target.textContent || '');
                        if (isLikelyPostDate(text)) return text;
                    }
                    return null;
                }

                function extractPostDate(article, postUrl) {
                    const candidates = [];
                    const links = article.querySelectorAll('a[href]');
                    for (const link of links) {
                        const href = link.href || '';
                        if (!href) continue;
                        if (postUrl && href === postUrl) {
                            candidates.push(link);
                            continue;
                        }
                        if (isPostUrl(href) && !isProfileHref(href)) {
                            candidates.push(link);
                        }
                    }

                    function extractFromAnchor(anchor) {
                        if (!anchor) return null;

                        const directAria = normalizeText(anchor.getAttribute('aria-label') || '');
                        if (isLikelyPostDate(directAria)) return directAria;

                        const labelledByText = readFromAriaLabelledBy(anchor);
                        if (labelledByText) return labelledByText;

                        const labelledDesc = anchor.querySelector('[aria-labelledby]');
                        const labelledDescText = readFromAriaLabelledBy(labelledDesc);
                        if (labelledDescText) return labelledDescText;

                        const timeEl = anchor.querySelector('time[datetime]');
                        if (timeEl) {
                            const dt = normalizeText(timeEl.getAttribute('datetime') || '');
                            if (dt) return dt;
                        }

                        const abbrEl = anchor.querySelector('abbr[title], abbr[data-utime]');
                        if (abbrEl) {
                            const title = normalizeText(abbrEl.getAttribute('title') || '');
                            if (title) return title;
                            const abbrText = normalizeText(abbrEl.innerText || abbrEl.textContent || '');
                            if (isLikelyPostDate(abbrText)) return abbrText;
                        }

                        const visibleText = normalizeText(anchor.innerText || anchor.textContent || '');
                        if (isLikelyPostDate(visibleText)) return visibleText;
                        return null;
                    }

                    for (const anchor of candidates) {
                        const value = extractFromAnchor(anchor);
                        if (value) return value;
                    }

                    const fallbackTime = article.querySelector('time[datetime]');
                    if (fallbackTime) {
                        const dt = normalizeText(fallbackTime.getAttribute('datetime') || '');
                        if (dt) return dt;
                    }

                    const fallbackAbbr = article.querySelector('abbr[title], abbr[data-utime]');
                    if (fallbackAbbr) {
                        const title = normalizeText(fallbackAbbr.getAttribute('title') || '');
                        if (title) return title;
                        const abbrText = normalizeText(fallbackAbbr.innerText || fallbackAbbr.textContent || '');
                        if (isLikelyPostDate(abbrText)) return abbrText;
                    }

                    return null;
                }

                function addLink(absoluteHref, text, postContent, postUrl, postDate, engagement, visibleIndex = null) {
                    try {
                        const u = new URL(absoluteHref);
                        const key = `${postUrl || u.pathname.replace(/\/$/, '')}|${(postContent || '').slice(0, 80)}`;
                        if (seen.has(key)) return;
                        seen.add(key);
                        results.push({ 
                            url: absoluteHref, 
                            text: (text || '').trim(), 
                            type: 'direct',
                            post_content: postContent || null,
                            post_url: postUrl || null,
                            post_date: postDate || null,
                            post_reaction_count: engagement?.reactions ?? null,
                            post_comment_count: engagement?.comments ?? null,
                            post_share_count: engagement?.shares ?? null,
                            visible_index: visibleIndex,
                        });
                    } catch(e) {}
                }
                
                function extractPostUrl(article) {
                    // Look for timestamp link which usually points to the post
                    // Try multiple patterns
                    const selectors = [
                        'a[href*="/posts/"]',
                        'a[href*="/permalink/"]', 
                        'a[href*="story_fbid"]',
                        'a[href*="/photo/"]',
                        'a[role="link"][href*="facebook.com"]',
                        'span[id] a[href]'  // Timestamp links often have parent span with ID
                    ];
                    
                    for (const selector of selectors) {
                        const links = article.querySelectorAll(selector);
                        for (const link of links) {
                            const href = link.href;
                            // Avoid profile links, only get post/photo/story links
                            if (href && !isProfileHref(href) && isPostUrl(href)) {
                                return href;
                            }
                        }
                    }
                    
                    return null;
                }

                // Find the main search results container (exclude navigation/sidebar)
                const mainContent = document.querySelector('div[role="main"]') || document.body;

                // Strategy 1: first profile link inside each post article (within main content only)
                const articles = mainContent.querySelectorAll('div[role="article"]');
                articles.forEach((article, idx) => {
                    const postContent = extractPostContent(article);
                    const postUrl = extractPostUrl(article);
                    const postDate = extractPostDate(article, postUrl);
                    const engagement = extractEngagementCounts(article);
                    for (const a of article.querySelectorAll('a[href]')) {
                        if (isProfileHref(a.href)) { 
                            addLink(a.href, a.textContent, postContent, postUrl, postDate, engagement, idx); 
                            break; 
                        }
                    }
                });

                // Strategy 2: feed direct children (within main content only)
                if (results.length === 0) {
                    const feed = mainContent.querySelector('div[role="feed"]');
                    if (feed) {
                        Array.from(feed.children).forEach((child, idx) => {
                            const postContent = extractPostContent(child);
                            const postUrl = extractPostUrl(child);
                            const postDate = extractPostDate(child, postUrl);
                            const engagement = extractEngagementCounts(child);
                            for (const a of child.querySelectorAll('a[href]')) {
                                if (isProfileHref(a.href)) { 
                                    addLink(a.href, a.textContent, postContent, postUrl, postDate, engagement, idx); 
                                    break; 
                                }
                            }
                        });
                    }
                }

                // Strategy 3: search within main content only (not entire page)
                if (results.length === 0) {
                    mainContent.querySelectorAll('a[href]').forEach(a => {
                        if (isProfileHref(a.href)) {
                            // Try to find parent article for post content
                            let parent = a.closest('div[role="article"]');
                            const postContent = parent ? extractPostContent(parent) : null;
                            const postUrl = parent ? extractPostUrl(parent) : null;
                            const postDate = parent ? extractPostDate(parent, postUrl) : null;
                            const engagement = parent ? extractEngagementCounts(parent) : null;
                            addLink(a.href, a.textContent, postContent, postUrl, postDate, engagement, null);
                        }
                    });
                }

                return results;
            }
            """,
            current_user_id
        )

        logger.info(f"âœ“ Total extracted: {len(all_links)} profile links via semantic extraction")
        
        # Pre-filter: drop any link whose URL is a /groups/ page â€” those are never individual users
        import re as _re
        def _is_user_profile_url(url: str) -> bool:
            clean = url.split('?')[0].split('&')[0]
            if '/groups/' in clean:
                return False
            # profile.php?id=... is always a personal profile
            if 'profile.php' in url:
                return True
            # Must end with a slug that is not a known non-profile path
            non_profile = {'pages', 'events', 'marketplace', 'watch', 'gaming', 'ads'}
            match = _re.search(r'facebook\.com/([^/?#]+)', clean)
            if match and match.group(1).lower() in non_profile:
                return False
            return True

        user_links = [l for l in all_links if _is_user_profile_url(l['url'])]
        logger.info(f"After pre-filtering groups/pages: {len(user_links)} candidate user links (dropped {len(all_links) - len(user_links)})")

        def _link_key(link: Dict) -> str:
            base = str(link.get("post_url") or link.get("url") or "")
            content = str(link.get("post_content") or "")[:80]
            return f"{base}|{content}"

        seen_link_keys = {_link_key(link) for link in user_links}

        # Additional extraction rounds: keep scrolling and harvesting until we stall.
        if len(user_links) < max_results:
            logger.info(
                "Initial extraction below target (%d/%d). Continuing progressive scan...",
                len(user_links),
                max_results,
            )
            no_growth_rounds = 0
            for scan_round in range(1, 10):
                if should_stop and should_stop():
                    break

                await page.evaluate("window.scrollBy(0, 2500)")
                if await self._sleep_with_stop(random.uniform(2.0, 3.5), should_stop=should_stop):
                    break

                # Secondary broad extraction: less strict, catches feed cards that lack role=article.
                extra_links = await page.evaluate(
                    """
                    (currentUserId) => {
                        const out = [];
                        const seen = new Set();
                        const feed = document.querySelector('div[role="feed"]');
                        if (!feed) return out;

                        function isProfileHref(href) {
                            if (!href || !href.includes('facebook.com')) return false;
                            if (currentUserId && href.includes(currentUserId)) return false;
                            if (href.includes('/groups/') || href.includes('/events/') || href.includes('/pages/')) return false;
                            if (href.includes('/search/') || href.includes('/hashtag/')) return false;
                            return href.includes('profile.php') || /facebook\\.com\\/[A-Za-z0-9._-]{2,}(?:\\?|$)/.test(href);
                        }

                        function cardText(el) {
                            const t = (el.innerText || '').trim();
                            return t.length > 500 ? t.slice(0, 500) + '...' : t;
                        }

                        function normalizeText(value) {
                            return (value || '').replace(/\\s+/g, ' ').trim();
                        }

                        function isLikelyPostDate(value) {
                            const text = normalizeText(value);
                            if (!text) return false;
                            if (/^(?:\\d+\\s*(?:s|m|min|h|hr|d|w|mo|y)|just now|yesterday)$/i.test(text)) return true;
                            if (/\\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december|today|yesterday)\\b/i.test(text)) return true;
                            if (/\\b\\d{1,2}:\\d{2}\\b/.test(text)) return true;
                            if (/\\b\\d+\\s*(?:mins?|minutes?|hrs?|hours?|days?|weeks?|months?|years?)\\b/i.test(text)) return true;
                            return false;
                        }

                        function readFromAriaLabelledBy(node) {
                            if (!node || !node.getAttribute) return null;
                            const labelledBy = node.getAttribute('aria-labelledby');
                            if (!labelledBy) return null;
                            for (const id of labelledBy.split(/\s+/).filter(Boolean)) {
                                const target = document.getElementById(id);
                                if (!target) continue;
                                const text = normalizeText(target.innerText || target.textContent || '');
                                if (isLikelyPostDate(text)) return text;
                            }
                            return null;
                        }

                        function extractPostDate(card, postLinkEl) {
                            const candidateAnchors = [];
                            if (postLinkEl) candidateAnchors.push(postLinkEl);
                            for (const a of card.querySelectorAll('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"], a[href*="/photo/"]')) {
                                if (postLinkEl && a === postLinkEl) continue;
                                candidateAnchors.push(a);
                            }

                            for (const anchor of candidateAnchors) {
                                const directAria = normalizeText(anchor.getAttribute('aria-label') || '');
                                if (isLikelyPostDate(directAria)) return directAria;

                                const labelled = readFromAriaLabelledBy(anchor);
                                if (labelled) return labelled;

                                const nestedLabelled = anchor.querySelector('[aria-labelledby]');
                                const nestedLabelledText = readFromAriaLabelledBy(nestedLabelled);
                                if (nestedLabelledText) return nestedLabelledText;

                                const timeEl = anchor.querySelector('time[datetime]');
                                if (timeEl) {
                                    const dt = normalizeText(timeEl.getAttribute('datetime') || '');
                                    if (dt) return dt;
                                }

                                const abbrEl = anchor.querySelector('abbr[title], abbr[data-utime]');
                                if (abbrEl) {
                                    const title = normalizeText(abbrEl.getAttribute('title') || '');
                                    if (title) return title;
                                    const abbrText = normalizeText(abbrEl.innerText || abbrEl.textContent || '');
                                    if (isLikelyPostDate(abbrText)) return abbrText;
                                }

                                const visible = normalizeText(anchor.innerText || anchor.textContent || '');
                                if (isLikelyPostDate(visible)) return visible;
                            }

                            const fallbackTime = card.querySelector('time[datetime]');
                            if (fallbackTime) {
                                const dt = normalizeText(fallbackTime.getAttribute('datetime') || '');
                                if (dt) return dt;
                            }

                            const fallbackAbbr = card.querySelector('abbr[title], abbr[data-utime]');
                            if (fallbackAbbr) {
                                const title = normalizeText(fallbackAbbr.getAttribute('title') || '');
                                if (title) return title;
                                const abbrText = normalizeText(fallbackAbbr.innerText || fallbackAbbr.textContent || '');
                                if (isLikelyPostDate(abbrText)) return abbrText;
                            }

                            return null;
                        }

                        Array.from(feed.children).forEach((child, idx) => {
                            const postContent = cardText(child);
                            const postLink = child.querySelector('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"], a[href*="/photo/"]');
                            const postUrl = postLink ? postLink.href : null;
                            const postDate = extractPostDate(child, postLink);
                            const profileLink = Array.from(child.querySelectorAll('a[href]')).find((a) => isProfileHref(a.href));
                            if (!profileLink) return;
                            const key = `${postUrl || profileLink.href}|${(postContent || '').slice(0, 80)}`;
                            if (seen.has(key)) return;
                            seen.add(key);
                            out.push({
                                url: profileLink.href,
                                text: (profileLink.textContent || '').trim(),
                                type: 'direct',
                                post_content: postContent || null,
                                post_url: postUrl || null,
                                post_date: postDate || null,
                                post_reaction_count: null,
                                post_comment_count: null,
                                post_share_count: null,
                                visible_index: idx,
                            });
                        });
                        return out;
                    }
                    """,
                    current_user_id,
                )

                added = 0
                for link in extra_links:
                    if not _is_user_profile_url(link.get("url", "")):
                        continue
                    key = _link_key(link)
                    if key in seen_link_keys:
                        continue
                    seen_link_keys.add(key)
                    user_links.append(link)
                    added += 1

                if added == 0:
                    no_growth_rounds += 1
                    logger.info("Progressive scan round %d: no new links (%d/3)", scan_round, no_growth_rounds)
                else:
                    no_growth_rounds = 0
                    logger.info(
                        "Progressive scan round %d: +%d links (total=%d)",
                        scan_round,
                        added,
                        len(user_links),
                    )

                if len(user_links) >= max_results or no_growth_rounds >= 3:
                    break
        
        # Visit each profile and check if it's a user
        users_saved = 0
        
        filtered_links = user_links  # JS already deduplicates
        logger.info(f"Processing {len(filtered_links)} links sequentially (one at a time)")
        use_index_based_comments = (page_diag.get("articles", 0) == 0 and page_diag.get("feed"))

        # One loop per profile: scrape comments for THIS post â†’ visit THIS profile â†’ save to DB â†’ next
        for i, link in enumerate(filtered_links):
            if should_stop and should_stop():
                logger.warning("Stop requested while processing profiles. Exiting keyword early.")
                break

            if users_saved >= max_results:
                logger.info(f"Reached max_results ({max_results}), stopping")
                break

            logger.info(f"Processing link {i+1}/{len(filtered_links)}: {link.get('text', '') or link['url'][:50]}")

            # 1) Scrape comments for this post (on search page), then we'll save with this profile
            comments_data = []
            try:
                # Primary path: locate the correct card by profile URL and open its comments dialog.
                comments_data = await self._click_comments_and_extract_from_dialog(page, link["url"], max_comments=0)

                # Fallback for feed-only layouts where DOM changes can break URL matching.
                if not comments_data and use_index_based_comments:
                    from .facebook_comment_fix import extract_comments_from_post_on_search_page
                    post_index = int(link.get("visible_index", i))
                    comments_data = await extract_comments_from_post_on_search_page(
                        page,
                        post_index,
                        max_comments=0,
                    )
                if comments_data:
                    logger.info(f"  Scraped {len(comments_data)} comments (will save with this profile)")
            except Exception as e:
                logger.debug(f"  Comment extraction skipped: {e}")

            # 2) Fetch profile and store to DB (with the comments we just scraped)
            account_uid = getattr(self, '_current_account', {}).get('uid', '')
            new_page = await self.browser_manager.create_page_with_cookies(account_uid)
            try:
                result = await self._process_single_profile(new_page, link, keyword, i + 1, len(filtered_links), comments_data=comments_data)
                if result:  # Successfully saved
                    users_saved += 1
                    logger.info(f"âœ“ Progress: {users_saved}/{max_results} profiles saved")
            except Exception as e:
                logger.error(f"  âœ— Error processing profile: {e}")
            
            # Small delay between profiles to look more human
            if i < len(filtered_links) - 1 and users_saved < max_results:
                delay = random.uniform(3, 7)
                logger.info(f"Waiting {delay:.1f}s before next profile...")
                remaining = delay
                while remaining > 0:
                    if should_stop and should_stop():
                        logger.warning("Stop requested during profile delay.")
                        break
                    chunk = min(1.0, remaining)
                    await asyncio.sleep(chunk)
                    remaining -= chunk
                if should_stop and should_stop():
                    break
        
        logger.info(f"âœ“ Completed: {users_saved} users saved to database")
        return users_saved

    async def _process_single_profile(self, page, link, keyword, idx, total, comments_data: Optional[List[Dict]] = None):
        """Process a single profile and return True if saved successfully.
        If comments_data is provided (from search results dialog), they will be saved once the profile is stored."""
        link_url = link['url']
        name = link['text']
        link_type = link['type']
        
        logger.info(f"[{idx}/{total}] Checking {link_type} link: {name}")
        logger.info(f"  URL: {link_url}")
        
        # Store post fields from the search results page before navigating away
        post_content = link.get('post_content', None)
        post_url = link.get('post_url', None)  # Capture post URL if available
        post_date = link.get('post_date', None)
        post_reaction_count = link.get('post_reaction_count', None)
        post_comment_count = link.get('post_comment_count', None)
        post_share_count = link.get('post_share_count', None)
        
        try:
            # Handle group posts differently
            if link_type == 'group':
                logger.info(f"  Processing group post author...")
                # Navigate to the group user page
                await page.goto(link_url, wait_until="domcontentloaded", timeout=90000)
                await asyncio.sleep(random.uniform(2, 4))
                
                # Find the "View profile" link
                logger.info(f"  Looking for 'View profile' link...")
                view_profile_link = await page.query_selector('a[aria-label="View profile"]')
                
                if not view_profile_link:
                    logger.info(f"  âœ— 'View profile' link not found, skipping")
                    await page.close()
                    return False
                
                profile_url = await view_profile_link.get_attribute('href')
                logger.info(f"  Found profile URL: {profile_url}")
                
                # Navigate to the actual profile
                await page.goto(profile_url, wait_until="domcontentloaded", timeout=90000)
                await asyncio.sleep(random.uniform(2, 4))
            else:
                # Direct profile link
                profile_url = link_url
                # Visit the profile
                await page.goto(profile_url, wait_until="domcontentloaded", timeout=90000)
                await asyncio.sleep(random.uniform(2, 4))
            
            # Extract the actual user name from the profile page using the specific classes
            name_selector = 'div.x1i10hfl.x1qjc9v5.xjbqb8w.xjqpnuy.xc5r6h4.xqeqjp1.x1phubyo.x13fuv20.x18b5jzi.x1q0q8m5.x1t7ytsu.x972fbf.x10w94by.x1qhh985.x14e42zd.x9f619.x1ypdohk.xdl72j9.x2lah0s.x3ct3a4.xdj266r.x14z9mp.xat24cr.x1lziwak.x2lwn1j.xeuugli.xexx8yu.xyri2b.x18d9i69.x1c1uobl.x1n2onr6.x16tdsg8.x1hl2dhg.xggy1nq.x1ja2u2z.x1t137rt.x1fmog5m.xu25z0z.x140muxe.xo1y3bh.x3nfvp2.x1q0g3np.x87ps6o.x1lku1pv.x1a2a7pz'
            name_element = await page.query_selector(name_selector)
            
            actual_name = None
            if name_element:
                actual_name = await name_element.inner_text()
                # Clean up the name - remove &nbsp; and extra whitespace
                if actual_name:
                    actual_name = actual_name.replace('\xa0', ' ').strip()
            
            # Determine final name to use
            if actual_name and actual_name.strip():
                # Successfully extracted from profile page
                logger.info(f"  Extracted name from profile: {actual_name}")
                final_name = actual_name
            elif link_type == 'group' and name and name.strip():
                # For group posts, use the name from the search results
                logger.info(f"  Using name from group post: {name}")
                final_name = name
            else:
                # Fallback: extract username from URL
                import re
                url_match = re.search(r'facebook\.com/([^/?]+)', profile_url)
                if url_match:
                    username = url_match.group(1)
                    # Skip if it's profile.php (not a real username)
                    if username != 'profile.php':
                        # Clean up the username (replace dots and underscores with spaces, capitalize)
                        username_cleaned = username.replace('.', ' ').replace('_', ' ').title()
                        logger.info(f"  Extracted username from URL: {username_cleaned}")
                        final_name = username_cleaned
                    elif name and name.strip():
                        logger.info(f"  Using link text: {name}")
                        final_name = name
                    else:
                        logger.info(f"  Could not extract name, using 'Unknown'")
                        final_name = "Unknown"
                elif name and name.strip():
                    logger.info(f"  Using link text: {name}")
                    final_name = name
                else:
                    logger.info(f"  Could not extract name, using 'Unknown'")
                    final_name = "Unknown"
            
            # Try to find location using multiple methods
            # Method 1: JavaScript search for any span with location text
            location_info = await page.evaluate(
                """
                () => {
                    const locations = [];
                    const allSpans = document.querySelectorAll('span');
                    
                    for (const span of allSpans) {
                        const text = span.textContent.trim();
                        if (text.startsWith('From ') || text.startsWith('Lives in ') || text.startsWith('Moved to ')) {
                            locations.push(text);
                        }
                    }
                    
                    return {
                        found: locations.length > 0,
                        locations: locations
                    };
                }
                """
            )
            
            # Method 2: Try specific span class selector
            location_span_selector = 'span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.x1xmvt09.x6prxxf.xvq8zen.x1s688f.xzsf02u'
            location_elements = await page.query_selector_all(location_span_selector)
            
            specific_locations = []
            for elem in location_elements:
                text = await elem.inner_text()
                text = text.strip()
                if text and (text.startswith('From ') or text.startswith('Lives in ') or text.startswith('Moved to ')):
                    specific_locations.append(text)
            
            # Combine all found locations
            all_locations = []
            if location_info.get('found'):
                all_locations.extend(location_info.get('locations', []))
            all_locations.extend(specific_locations)
            
            # Remove duplicates while preserving order
            unique_locations = []
            seen = set()
            for loc in all_locations:
                if loc not in seen:
                    unique_locations.append(loc)
                    seen.add(loc)
            
            location_text = ', '.join(unique_locations) if unique_locations else None

            # Determine if this is a personal profile (not a group/page/page-like entity)
            is_personal_profile = await page.evaluate(
                """
                () => {
                    const text = document.body.innerText || '';
                    const html = document.body.innerHTML || '';
                    // Group indicators
                    if (html.includes('joinButton') || text.includes('Join group') ||
                        text.includes('Join Group') || html.includes('group_type')) {
                        return false;
                    }
                    // Strong page indicators
                    if (
                        text.includes('Like Page') ||
                        text.includes('Suggest Page') ||
                        text.includes('Follow Page') ||
                        text.includes('Page transparency') ||
                        text.includes('likes this') ||
                        text.includes('people like this') ||
                        text.includes('Page ·')
                    ) {
                        return false;
                    }

                    // Personal profile indicators (friend-centric controls)
                    const hasAddFriend = !!document.querySelector('[aria-label="Add friend"], [aria-label="Add Friend"]');
                    const hasFriends = !!document.querySelector('[aria-label="Friends"], [aria-label="Remove friend"], [aria-label="Edit friend list"]');
                    const hasMutualFriendsText = /mutual friends?/i.test(text);

                    // Message/Follow exist on pages too, so don't use them alone.
                    return hasAddFriend || hasFriends || hasMutualFriendsText;
                }
                """
            )

            if is_personal_profile:
                if location_text:
                    logger.info(f"  âœ“ Personal profile detected. Location: {location_text}")
                else:
                    logger.info(f"  âœ“ Personal profile detected (no public location)")
                
                try:
                    search_result = SearchResult(
                        name=final_name,
                        location=location_text,
                        post_content=post_content,  # Include post content
                        post_url=post_url,  # Include post URL (may be None)
                        post_date=post_date,
                        post_reaction_count=post_reaction_count,
                        post_comment_count=post_comment_count,
                        post_share_count=post_share_count,
                        profile_url=profile_url,
                        search_keyword=keyword,
                        status=ResultStatus.PENDING,
                    )
                    self.db.add(search_result)
                    self.db.commit()
                    logger.info(f"  âœ“ Saved to database (ID: {search_result.id})")

                    # Save comments from search results dialog (if we scraped them before visiting profile)
                    if comments_data:
                        try:
                            for c in comments_data:
                                pc = PostComment(
                                    search_result_id=search_result.id,
                                    author_name=c.get("author_name"),
                                    author_profile_url=c.get("author_profile_url"),
                                    comment_text=c.get("comment_text"),
                                    comment_timestamp=c.get("comment_timestamp"),
                                )
                                self.db.add(pc)
                            self.db.commit()
                            logger.info(f"  âœ“ Saved {len(comments_data)} comments from search results dialog")
                        except Exception as e:
                            logger.warning(f"  Failed to save dialog comments: {e}")
                            self.db.rollback()

                    # Extract comments from user's recent posts on their profile
                    # Since search results don't provide post URLs, we scrape from profile
                    try:
                        logger.info(f"  ðŸ“ Extracting comments from recent posts on profile...")
                        
                        # Find recent post links on the profile page
                        recent_posts = await page.evaluate(
                            """
                            () => {
                                const postLinks = [];
                                // Look for post/photo/permalink links
                                const links = document.querySelectorAll('a[href*="/posts/"], a[href*="/photo/"], a[href*="story_fbid"]');
                                for (const link of links) {
                                    if (postLinks.length >= 3) break;  // Get max 3 recent posts
                                    const href = link.href;
                                    if (href && !postLinks.includes(href)) {
                                        postLinks.push(href);
                                    }
                                }
                                return postLinks;
                            }
                            """
                        )
                        
                        if recent_posts and len(recent_posts) > 0:
                            logger.info(f"  Found {len(recent_posts)} recent posts, extracting comments...")
                            total_comments = 0
                            
                            for post_link in recent_posts[:2]:  # Visit max 2 posts to save time
                                try:
                                    logger.info(f"  Visiting post: {post_link[:80]}...")
                                    await page.goto(post_link, wait_until="commit", timeout=30000)
                                    await asyncio.sleep(random.uniform(2, 3))
                                    
                                    # Extract comments from this post
                                    comment_count = await self._extract_comments(page, search_result.id, max_comments=0)
                                    total_comments += comment_count
                                    
                                    if comment_count > 0:
                                        logger.info(f"  âœ“ Extracted {comment_count} comments from this post")
                                    
                                    # Small delay between posts
                                    await asyncio.sleep(random.uniform(1, 2))
                                except Exception as e:
                                    logger.warning(f"  âš  Could not extract comments from post: {e}")
                            
                            if total_comments > 0:
                                logger.info(f"  âœ“ Total comments extracted: {total_comments}")
                            else:
                                logger.info(f"  â„¹ No comments found in recent posts")
                        else:
                            logger.info(f"  â„¹ No recent posts found on profile")
                            
                    except Exception as e:
                        logger.warning(f"  âš  Could not extract comments from profile: {e}")
                    
                    await page.close()
                    return True
                except Exception as e:
                    logger.error(f"  âœ— Failed to save to database: {e}")
                    self.db.rollback()
                    await page.close()
                    return False
            else:
                logger.info(f"  âœ— Not a personal profile (group/page) â€” skipping")
                # Still save a SearchResult (INVALID) so we can attach scraped comments and not lose them
                if comments_data:
                    try:
                        search_result = SearchResult(
                            name=final_name or "Unknown",
                            location=location_text,
                            post_content=post_content,
                            post_url=post_url,
                            post_date=post_date,
                            post_reaction_count=post_reaction_count,
                            post_comment_count=post_comment_count,
                            post_share_count=post_share_count,
                            profile_url=profile_url,
                            search_keyword=keyword,
                            status=ResultStatus.INVALID,
                        )
                        self.db.add(search_result)
                        self.db.commit()
                        logger.info(f"  âœ“ Saved as INVALID (ID: {search_result.id}) to store {len(comments_data)} comments")
                        for c in comments_data:
                            pc = PostComment(
                                search_result_id=search_result.id,
                                author_name=c.get("author_name"),
                                author_profile_url=c.get("author_profile_url"),
                                comment_text=c.get("comment_text"),
                                comment_timestamp=c.get("comment_timestamp"),
                            )
                            self.db.add(pc)
                        self.db.commit()
                        logger.info(f"  âœ“ Saved {len(comments_data)} comments")
                    except Exception as e:
                        logger.warning(f"  Failed to save skipped profile + comments: {e}")
                        self.db.rollback()
                await page.close()
                return False
            
        except Exception as e:
            logger.error(f"  âœ— Error checking profile: {e}")
            try:
                await page.close()
            except:
                pass
            return False


        if post_url:
            existing = (
                self.db.query(SearchResult)
                .filter(SearchResult.post_url == post_url)
                .first()
            )
            if existing:
                logger.debug(f"Skipping duplicate post (URL already exists): {post_url}")
                return False

        try:
            search_result = SearchResult(
                name=post_name,
                location=post.get("location"),
                post_content=post.get("content"),
                post_url=post_url,
                post_date=post.get("post_date"),
                post_reaction_count=post.get("reaction_count"),
                post_comment_count=post.get("comment_count"),
                post_share_count=post.get("share_count"),
                profile_url=post.get("profileUrl"),
                search_keyword=keyword,
                status=ResultStatus.PENDING,
            )
            self.db.add(search_result)
            self.db.commit()
            logger.info(f"âœ“ Saved post to database: {post_name[:50]}... (ID: {search_result.id})")
            return True
        except Exception as e:
            logger.error(f"Failed to save post to database: {e}", exc_info=True)
            self.db.rollback()
            return False

