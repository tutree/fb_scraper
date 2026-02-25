from playwright.async_api import Page
from typing import List, Dict, Optional
import asyncio
import random
import json
import pyotp
from pathlib import Path
from sqlalchemy.orm import Session
from ..models.search_result import SearchResult, ResultStatus
from ..core.config import settings
from ..core.logging_config import get_logger
from tenacity import retry, stop_after_attempt, wait_exponential

logger = get_logger(__name__)


async def _human_mouse_move(page: Page, x: int, y: int) -> None:
    """Move mouse along a curved path to look human (not a straight teleport)."""
    try:
        # Current position unknown — start from a plausible location
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
        # Random scroll distance — vary speed via multiple small steps
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


def load_accounts() -> List[Dict]:
    """Load Facebook accounts from credentials file."""
    logger.info(f"Loading Facebook accounts from: {CREDENTIALS_PATH.absolute()}")
    
    if CREDENTIALS_PATH.exists():
        with open(CREDENTIALS_PATH) as f:
            data = json.load(f)
            all_accounts = data.get("facebook_accounts", [])
            active_accounts = [a for a in all_accounts if a.get("active")]
            logger.info(f"Found {len(all_accounts)} total accounts, {len(active_accounts)} active")
            
            if not active_accounts:
                logger.warning("No active accounts found in credentials file")
            else:
                for acc in active_accounts:
                    uid = acc.get("uid", "Unknown")
                    has_totp = "Yes" if acc.get("totp_secret") else "No"
                    logger.info(f"  - Account: {uid}, 2FA configured: {has_totp}")
            
            return active_accounts
    
    # Fallback to env-based single account
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
                logger.info(f"✓ Successfully logged in as {uid}")
                return True

            logger.error(f"Login failed for {uid} - no navigation found")
            return False

        except Exception as e:
            logger.error(f"Login exception for {uid}: {e}", exc_info=True)
            raise

    async def search_keyword(
        self, keyword: str, max_results: int = 10
    ) -> List[Dict]:
        """Search for a keyword and extract posts."""
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
            await self._current_page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=60000)
            
            # Check for logged-in indicators
            is_logged_in = False
            try:
                nav = await self._current_page.query_selector('div[role="navigation"]')
                if nav:
                    logger.info("✓ Already logged in (session restored from cookies)")
                    is_logged_in = True
            except:
                pass
            
            if not is_logged_in:
                logger.info("Not logged in, attempting login...")
                login_success = await self.login(self._current_page, account)
                if not login_success:
                    logger.error("Login failed, aborting search")
                    return []
                logger.info("Login successful")
                
                # Save cookies after successful login
                logger.info("Saving session cookies for future use...")
                await self.browser_manager.save_cookies(self._current_page)
            else:
                logger.info("Skipping login (already authenticated)")
            
            # Warmup session to appear more human (only on first keyword)
            logger.info("Starting session warmup...")
            await warmup_session(self._current_page)
            logger.info("Session warmup completed")
        else:
            logger.info("Reusing existing browser session")

        page = self._current_page

        try:
            # Human-like delay before searching
            delay = random.uniform(3, 7)
            logger.info(f"Waiting {delay:.1f}s before searching...")
            await asyncio.sleep(delay)
            
            # Type search query manually instead of URL parameter (more human-like)
            logger.info("Navigating to Facebook homepage...")
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=90000)
            await asyncio.sleep(random.uniform(2, 4))
            
            # Find and click search box
            logger.info("Looking for search box...")
            search_box = await page.query_selector('input[type="search"], input[placeholder*="Search"]')
            if search_box:
                logger.info("Search box found, typing keyword...")
                # Hover first, then click — like a real user
                bbox = await search_box.bounding_box()
                if bbox:
                    target_x = int(bbox['x'] + bbox['width'] * random.uniform(0.3, 0.7))
                    target_y = int(bbox['y'] + bbox['height'] * random.uniform(0.3, 0.7))
                    await _human_mouse_move(page, target_x, target_y)
                    await asyncio.sleep(random.uniform(0.3, 0.7))
                await search_box.click()
                await asyncio.sleep(random.uniform(0.5, 1.5))
                
                # Type keyword with human-like cadence (faster mid-word, slower at start/end)
                for i, char in enumerate(keyword):
                    await page.keyboard.type(char)
                    # Vary delay: slower at start/end, faster in middle
                    if i < 3 or i > len(keyword) - 4:
                        await asyncio.sleep(random.uniform(0.12, 0.28))
                    else:
                        await asyncio.sleep(random.uniform(0.05, 0.18))
                    # Occasional longer pause (thinking/hesitation)
                    if random.random() < 0.07:
                        await asyncio.sleep(random.uniform(0.3, 0.8))
                
                await asyncio.sleep(random.uniform(1, 2))
                logger.info("Pressing Enter to search...")
                await page.keyboard.press("Enter")
                await page.wait_for_load_state("domcontentloaded", timeout=90000)
                logger.info("Search results page loaded")
                
                # Click on "Posts" tab if available
                await asyncio.sleep(random.uniform(2, 4))
                logger.info("Looking for Posts tab...")
                posts_tab = await page.query_selector('a[href*="/search/posts"]')
                if posts_tab:
                    logger.info("Posts tab found, clicking...")
                    bbox = await posts_tab.bounding_box()
                    if bbox:
                        await _human_mouse_move(page,
                            int(bbox['x'] + bbox['width'] * 0.5),
                            int(bbox['y'] + bbox['height'] * 0.5))
                        await asyncio.sleep(random.uniform(0.2, 0.5))
                    await posts_tab.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=90000)
                    logger.info("Posts tab loaded")
                else:
                    logger.warning("Posts tab not found, staying on current page")
            else:
                # Fallback to direct URL
                logger.warning("Search box not found, using direct URL")
                from urllib.parse import quote_plus
                search_url = f"https://www.facebook.com/search/posts/?q={quote_plus(keyword)}"
                logger.info(f"Navigating to: {search_url}")
                await page.goto(search_url, wait_until="domcontentloaded", timeout=90000)
            
            # Wait and look around before scraping
            wait_time = random.uniform(4, 8)
            logger.info(f"Waiting {wait_time:.1f}s before scraping...")
            await asyncio.sleep(wait_time)
            
            logger.info("Waiting for post elements to appear...")
            # Try multiple selectors for posts
            try:
                await page.wait_for_selector('blockquote.html-blockquote, div[data-ad-rendering-role="story_message"], div[role="article"]', timeout=30000)
                logger.info("✓ Post elements found, starting extraction...")
                
            except Exception as e:
                logger.warning(f"Standard selectors not found, trying alternative approach: {e}")
                # Wait a bit and try to extract anyway
                await asyncio.sleep(5)

            # Process posts one by one as we scroll
            posts_processed = await self._scroll_and_process_posts(page, keyword, max_results)
            logger.info(f"Processing completed. Processed {posts_processed} posts")

            logger.info(f"=== Search completed for '{keyword}': {posts_processed} posts processed ===")
            return []  # Return empty since we save as we go

        except Exception as e:
            logger.error(f"Error searching for '{keyword}': {e}", exc_info=True)
            return []
        # Note: Don't close page here - reuse it for next keyword

    async def _scroll_and_process_posts(
        self, page: Page, keyword: str, max_results: int
    ) -> int:
        """Scroll, extract author profile links semantically, visit profiles, save users to database."""
        logger.info(f"Starting extraction for keyword: '{keyword}' (target: {max_results} posts)")
        
        # Scroll a few times to load more posts
        logger.info("Scrolling to load posts...")
        for i in range(2):
            await human_scroll(page, scrolls=2)
            await asyncio.sleep(random.uniform(3, 5))

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

        # Extract author profile links — use a.href (resolved absolute URL by browser)
        # NOT a[href*="facebook.com"] which only matches the raw HTML attribute
        logger.info("Extracting author profile links and post content via semantic DOM traversal...")
        all_links = await page.evaluate(
            """
            () => {
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
                    try {
                        const u = new URL(absoluteHref);
                        const parts = u.pathname.replace(/^\//, '').replace(/\/$/, '').split('/');
                        const slug = parts[0];
                        if (!slug) return false;
                        if (NON_PROFILE.has(slug.toLowerCase())) return false;
                        if (/^(groups|events|pages|hashtag|watch|gaming|marketplace|reel|reels|stories|live|photo|photos|video|videos|posts|permalink|story\.php|share|sharer|composer|checkpoint|login|ajax)/.test(slug)) return false;
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

                function addLink(absoluteHref, text, postContent) {
                    try {
                        const u = new URL(absoluteHref);
                        const key = u.pathname.replace(/\/$/, '');
                        if (seen.has(key)) return;
                        seen.add(key);
                        results.push({ 
                            url: absoluteHref, 
                            text: (text || '').trim(), 
                            type: 'direct',
                            post_content: postContent || null
                        });
                    } catch(e) {}
                }

                // Strategy 1: first profile link inside each post article
                const articles = document.querySelectorAll('div[role="article"]');
                articles.forEach(article => {
                    const postContent = extractPostContent(article);
                    for (const a of article.querySelectorAll('a[href]')) {
                        if (isProfileHref(a.href)) { 
                            addLink(a.href, a.textContent, postContent); 
                            break; 
                        }
                    }
                });

                // Strategy 2: feed direct children
                if (results.length === 0) {
                    const feed = document.querySelector('div[role="feed"]');
                    if (feed) {
                        Array.from(feed.children).forEach(child => {
                            const postContent = extractPostContent(child);
                            for (const a of child.querySelectorAll('a[href]')) {
                                if (isProfileHref(a.href)) { 
                                    addLink(a.href, a.textContent, postContent); 
                                    break; 
                                }
                            }
                        });
                    }
                }

                // Strategy 3: every anchor on the page (a.href = absolute, always works)
                if (results.length === 0) {
                    document.querySelectorAll('a[href]').forEach(a => {
                        if (isProfileHref(a.href)) {
                            // Try to find parent article for post content
                            let parent = a.closest('div[role="article"]');
                            const postContent = parent ? extractPostContent(parent) : null;
                            addLink(a.href, a.textContent, postContent);
                        }
                    });
                }

                return results;
            }
            """
        )

        logger.info(f"✓ Total extracted: {len(all_links)} profile links via semantic extraction")
        
        # Pre-filter: drop any link whose URL is a /groups/ page — those are never individual users
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
        
        # Visit each profile and check if it's a user
        # Process in batches for parallel execution
        users_saved = 0
        batch_size = 3  # Process 3 profiles simultaneously
        
        filtered_links = user_links  # JS already deduplicates
        logger.info(f"Processing {len(filtered_links)} links in batches of {batch_size}")
        
        # Process links in batches
        for batch_start in range(0, len(filtered_links), batch_size):
            if users_saved >= max_results:
                logger.info(f"Reached max_results ({max_results}), stopping")
                break
            
            batch_end = min(batch_start + batch_size, len(filtered_links))
            batch = filtered_links[batch_start:batch_end]
            
            logger.info(f"Processing batch {batch_start//batch_size + 1}: links {batch_start+1} to {batch_end}")
            
            # Create separate pages for each profile in the batch
            tasks = []
            for i, link in enumerate(batch):
                if users_saved >= max_results:
                    break
                # Create a new page for each parallel task
                account_uid = getattr(self, '_current_account', {}).get('uid', '')
                new_page = await self.browser_manager.create_page_with_cookies(account_uid)
                task = self._process_single_profile(new_page, link, keyword, batch_start + i + 1, len(filtered_links))
                tasks.append(task)
            
            # Execute batch in parallel
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Count successful saves and close pages
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"  ✗ Batch processing error: {result}")
                elif result:  # Successfully saved
                    users_saved += 1
            
            logger.info(f"Batch completed. Total users saved so far: {users_saved}")
            
            # Small delay between batches
            if batch_end < len(filtered_links) and users_saved < max_results:
                await asyncio.sleep(random.uniform(1, 2))
        
        logger.info(f"✓ Completed: {users_saved} users saved to database")
        return users_saved

    async def _process_single_profile(self, page, link, keyword, idx, total):
        """Process a single profile and return True if saved successfully."""
        link_url = link['url']
        name = link['text']
        link_type = link['type']
        
        logger.info(f"[{idx}/{total}] Checking {link_type} link: {name}")
        logger.info(f"  URL: {link_url}")
        
        # Store the post content from the search results page before navigating away
        post_content = link.get('post_content', None)
        
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
                    logger.info(f"  ✗ 'View profile' link not found, skipping")
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

            # Determine if this is a personal profile (not a group/page)
            # Check for personal profile indicators: Add Friend, Message, or Follow buttons
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
                    // Page indicators
                    if (text.includes('Like Page') || text.includes('Suggest Page')) {
                        return false;
                    }
                    // Personal profile indicators
                    const hasAddFriend = !!document.querySelector('[aria-label="Add friend"], [aria-label="Add Friend"]');
                    const hasMessage = !!document.querySelector('[aria-label="Message"]');
                    const hasFollow = !!document.querySelector('[aria-label="Follow"]');
                    return hasAddFriend || hasMessage || hasFollow;
                }
                """
            )

            if is_personal_profile:
                if location_text:
                    logger.info(f"  ✓ Personal profile detected. Location: {location_text}")
                else:
                    logger.info(f"  ✓ Personal profile detected (no public location)")
                
                try:
                    search_result = SearchResult(
                        name=final_name,
                        location=location_text,
                        post_content=post_content,  # Include post content
                        post_url=None,
                        profile_url=profile_url,
                        search_keyword=keyword,
                        status=ResultStatus.PENDING,
                    )
                    self.db.add(search_result)
                    self.db.commit()
                    logger.info(f"  ✓ Saved to database (ID: {search_result.id})")
                    await page.close()
                    return True
                except Exception as e:
                    logger.error(f"  ✗ Failed to save to database: {e}")
                    self.db.rollback()
                    await page.close()
                    return False
            else:
                logger.info(f"  ✗ Not a personal profile (group/page) — skipping")
                await page.close()
                return False
            
        except Exception as e:
            logger.error(f"  ✗ Error checking profile: {e}")
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
                profile_url=post.get("profileUrl"),
                search_keyword=keyword,
                status=ResultStatus.PENDING,
            )
            self.db.add(search_result)
            self.db.commit()
            logger.info(f"✓ Saved post to database: {post_name[:50]}... (ID: {search_result.id})")
            return True
        except Exception as e:
            logger.error(f"Failed to save post to database: {e}", exc_info=True)
            self.db.rollback()
            return False
