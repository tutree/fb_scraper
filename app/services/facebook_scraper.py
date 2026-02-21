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


async def human_scroll(page: Page, scrolls: int = None) -> None:
    """Simulate human-like scrolling behavior."""
    if scrolls is None:
        scrolls = random.randint(3, 6)
    
    for _ in range(scrolls):
        # Random scroll distance
        scroll_amount = random.randint(300, 800)
        await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        await asyncio.sleep(random.uniform(1.5, 4.0))
        
        # Sometimes scroll back up (humans do this)
        if random.random() < 0.3:
            back_scroll = random.randint(100, 300)
            await page.evaluate(f"window.scrollBy(0, -{back_scroll})")
            await asyncio.sleep(random.uniform(0.5, 2.0))
        
        # Random pause (reading content)
        if random.random() < 0.4:
            await asyncio.sleep(random.uniform(2.0, 5.0))


async def warmup_session(page: Page) -> None:
    """Browse like a human before scraping to build session credibility."""
    try:
        logger.info("Starting session warmup...")
        
        # Go to homepage first
        await page.goto("https://www.facebook.com", wait_until="networkidle")
        await asyncio.sleep(random.uniform(3, 7))
        
        # Simulate reading by scrolling slowly
        for _ in range(random.randint(2, 4)):
            await page.evaluate(f"window.scrollBy(0, {random.randint(200, 500)})")
            await asyncio.sleep(random.uniform(2, 4))
        
        # Random mouse movements to simulate human behavior
        for _ in range(random.randint(3, 6)):
            await page.mouse.move(
                random.randint(100, 800), 
                random.randint(100, 600),
                steps=random.randint(5, 15)
            )
            await asyncio.sleep(random.uniform(0.3, 1.0))
        
        # Sometimes click on a safe element (like scrolling back to top)
        if random.random() < 0.3:
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(random.uniform(1, 3))
        
        logger.info("Session warmup completed")
    except Exception as e:
        logger.warning(f"Warmup session error (non-critical): {e}")

CREDENTIALS_PATH = Path("config/credentials.json")


def load_accounts() -> List[Dict]:
    """Load Facebook accounts from credentials file."""
    if CREDENTIALS_PATH.exists():
        with open(CREDENTIALS_PATH) as f:
            data = json.load(f)
            return [a for a in data.get("facebook_accounts", []) if a.get("active")]
    # Fallback to env-based single account
    return [
        {
            "uid": settings.FACEBOOK_EMAIL,
            "password": settings.FACEBOOK_PASSWORD,
            "totp_secret": None,
        }
    ]


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

    def _get_next_account(self) -> Dict:
        """Round-robin account selection."""
        account = self.accounts[self.account_index]
        self.account_index = (self.account_index + 1) % len(self.accounts)
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

        try:
            await page.goto("https://www.facebook.com/login", wait_until="networkidle")
            
            # Human-like delay before interacting - look around first
            await asyncio.sleep(random.uniform(2.0, 4.0))
            
            # Random mouse movement before typing
            await page.mouse.move(
                random.randint(200, 400), 
                random.randint(200, 400),
                steps=random.randint(10, 20)
            )
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # Type email with human-like delays
            email_field = await page.query_selector("#email")
            if email_field:
                await email_field.click()
                await asyncio.sleep(random.uniform(0.3, 0.8))
                for char in uid:
                    await page.keyboard.type(char)
                    await asyncio.sleep(random.uniform(0.05, 0.15))
            
            await asyncio.sleep(random.uniform(0.8, 1.8))
            
            # Type password with human-like delays
            pass_field = await page.query_selector("#pass")
            if pass_field:
                await pass_field.click()
                await asyncio.sleep(random.uniform(0.3, 0.8))
                for char in password:
                    await page.keyboard.type(char)
                    await asyncio.sleep(random.uniform(0.05, 0.15))

            await asyncio.sleep(random.uniform(0.5, 1.2))

            # Click login button
            await page.click('button[name="login"]')

            # Wait for either dashboard or 2FA screen
            await page.wait_for_load_state("networkidle")

            # Handle 2FA checkpoint
            if await page.is_visible('input[name="approvals_code"]'):
                if not totp_secret:
                    logger.error(f"2FA required for {uid} but no TOTP secret configured")
                    return False

                code = generate_2fa_code(totp_secret)
                logger.info(f"Generated 2FA code for {uid}: {code}")

                await page.fill('input[name="approvals_code"]', code)
                await asyncio.sleep(0.5)

                # Click the submit/continue button
                submit_btn = await page.query_selector(
                    'button[type="submit"], #checkpointSubmitButton'
                )
                if submit_btn:
                    await submit_btn.click()
                    await page.wait_for_load_state("networkidle")

                # If "Save browser" prompt appears, click "Continue"
                continue_btn = await page.query_selector(
                    'button[name="submit[Continue]"], button#checkpointSubmitButton'
                )
                if continue_btn:
                    await continue_btn.click()
                    await page.wait_for_load_state("networkidle")

            # Verify we are logged in
            nav = await page.query_selector('div[role="navigation"]')
            if nav:
                logger.info(f"Successfully logged in as {uid}")
                return True

            logger.error(f"Login failed for {uid} - no navigation found")
            await page.screenshot(path=f"login_error_{uid}.png")
            return False

        except Exception as e:
            logger.error(f"Login exception for {uid}: {e}")
            await page.screenshot(path=f"login_error_{uid}.png")
            raise

    async def search_keyword(
        self, keyword: str, max_results: int = 100
    ) -> List[Dict]:
        """Search for a keyword and extract posts."""
        page = None
        account = self._get_next_account()

        try:
            page = await self.browser_manager.create_page()

            login_success = await self.login(page, account)
            if not login_success:
                return []
            
            # Warmup session to appear more human
            await warmup_session(page)

            # Navigate to search with human-like delay
            await asyncio.sleep(random.uniform(3, 7))
            
            # Type search query manually instead of URL parameter (more human-like)
            await page.goto("https://www.facebook.com", wait_until="networkidle")
            await asyncio.sleep(random.uniform(2, 4))
            
            # Find and click search box
            search_box = await page.query_selector('input[type="search"], input[placeholder*="Search"]')
            if search_box:
                await search_box.click()
                await asyncio.sleep(random.uniform(0.5, 1.5))
                
                # Type keyword character by character
                for char in keyword:
                    await page.keyboard.type(char)
                    await asyncio.sleep(random.uniform(0.1, 0.3))
                
                await asyncio.sleep(random.uniform(1, 2))
                await page.keyboard.press("Enter")
                await page.wait_for_load_state("networkidle")
                
                # Click on "Posts" tab if available
                await asyncio.sleep(random.uniform(2, 4))
                posts_tab = await page.query_selector('a[href*="/search/posts"]')
                if posts_tab:
                    await posts_tab.click()
                    await page.wait_for_load_state("networkidle")
            else:
                # Fallback to direct URL
                search_url = f"https://www.facebook.com/search/posts/?q={keyword}"
                await page.goto(search_url, wait_until="networkidle")
            
            # Wait and look around before scraping
            await asyncio.sleep(random.uniform(4, 8))
            await page.wait_for_selector('div[role="article"]', timeout=30000)

            posts = await self._scroll_and_extract(page, keyword, max_results)

            for post in posts:
                await self._save_post(post, keyword)

            logger.info(f"Found {len(posts)} results for keyword: '{keyword}'")
            return posts

        except Exception as e:
            logger.error(f"Error searching for '{keyword}': {e}")
            if page:
                await page.screenshot(path=f"error_{keyword}.png")
            return []
        finally:
            if page:
                await page.close()

    async def _scroll_and_extract(
        self, page: Page, keyword: str, max_results: int
    ) -> List[Dict]:
        """Scroll and extract posts with human-like behavior."""
        posts: List[Dict] = []
        last_height = 0
        no_new_content_count = 0

        while len(posts) < max_results:
            new_posts = await self._extract_posts(page, keyword)
            for post in new_posts:
                if post not in posts:
                    posts.append(post)

            # Human-like scrolling instead of jumping to bottom
            await human_scroll(page, scrolls=random.randint(2, 4))
            
            # Longer, more varied delays
            await asyncio.sleep(random.uniform(4, 8))

            new_height = await page.evaluate(
                "document.documentElement.scrollHeight"
            )
            
            if new_height == last_height:
                no_new_content_count += 1
                if no_new_content_count >= 3:
                    logger.info("No new content after 3 attempts, stopping scroll")
                    break
            else:
                no_new_content_count = 0
                
            last_height = new_height
            
            # Random break to "read" content
            if random.random() < 0.3:
                logger.info("Taking a reading break...")
                await asyncio.sleep(random.uniform(5, 10))

        return posts[:max_results]

    async def _extract_posts(self, page: Page, keyword: str) -> List[Dict]:
        """Extract post data from current view."""
        return await page.evaluate(
            """
            (searchKeyword) => {
                const posts = [];
                const postElements = document.querySelectorAll('div[role="article"]');

                postElements.forEach((post) => {
                    try {
                        const nameElement = post.querySelector(
                            'h4 span a, strong a, span a[role="link"]'
                        );
                        const name = nameElement ? nameElement.textContent.trim() : '';

                        const locationElement = post.querySelector(
                            'span[dir="auto"] span span'
                        );
                        const location = locationElement
                            ? locationElement.textContent.trim() : '';

                        const contentElement = post.querySelector(
                            'div[data-ad-preview="message"], div[dir="auto"]'
                        );
                        const content = contentElement
                            ? contentElement.textContent.trim() : '';

                        const linkElement = post.querySelector(
                            'a[href*="/posts/"], a[href*="/photo/"]'
                        );
                        const url = linkElement ? linkElement.href : '';

                        const profileLink = post.querySelector(
                            'a[href*="/profile.php"], a[href*="/people/"], h4 a'
                        );
                        const profileUrl = profileLink ? profileLink.href : '';

                        if (
                            content.toLowerCase().includes('math') ||
                            content.toLowerCase().includes('tutor') ||
                            content.toLowerCase().includes('calculus') ||
                            content.toLowerCase().includes('algebra') ||
                            content.toLowerCase().includes(searchKeyword.toLowerCase())
                        ) {
                            posts.push({
                                name: name || 'Unknown',
                                location: location,
                                content: content,
                                url: url,
                                profileUrl: profileUrl,
                            });
                        }
                    } catch (err) {
                        console.error('Error extracting post:', err);
                    }
                });

                return posts;
            }
        """,
            keyword,
        )

    async def _save_post(self, post: Dict, keyword: str) -> None:
        """Save post to database (skip duplicates by post_url)."""
        post_url = post.get("url")
        if post_url:
            existing = (
                self.db.query(SearchResult)
                .filter(SearchResult.post_url == post_url)
                .first()
            )
            if existing:
                return

        search_result = SearchResult(
            name=post.get("name", "Unknown"),
            location=post.get("location"),
            post_content=post.get("content"),
            post_url=post_url,
            profile_url=post.get("profileUrl"),
            search_keyword=keyword,
            status=ResultStatus.PENDING,
        )
        self.db.add(search_result)
        self.db.commit()
