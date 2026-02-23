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
            await page.goto("https://www.facebook.com/login", wait_until="networkidle")
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
            await page.wait_for_load_state("networkidle")
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
                    await page.wait_for_load_state("networkidle")
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
                    await page.wait_for_load_state("networkidle")
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
            await page.goto("https://www.facebook.com", wait_until="networkidle")
            await asyncio.sleep(random.uniform(2, 4))
            
            # Find and click search box
            logger.info("Looking for search box...")
            search_box = await page.query_selector('input[type="search"], input[placeholder*="Search"]')
            if search_box:
                logger.info("Search box found, typing keyword...")
                await search_box.click()
                await asyncio.sleep(random.uniform(0.5, 1.5))
                
                # Type keyword character by character
                for char in keyword:
                    await page.keyboard.type(char)
                    await asyncio.sleep(random.uniform(0.1, 0.3))
                
                await asyncio.sleep(random.uniform(1, 2))
                logger.info("Pressing Enter to search...")
                await page.keyboard.press("Enter")
                await page.wait_for_load_state("networkidle")
                logger.info("Search results page loaded")
                
                # Click on "Posts" tab if available
                await asyncio.sleep(random.uniform(2, 4))
                logger.info("Looking for Posts tab...")
                posts_tab = await page.query_selector('a[href*="/search/posts"]')
                if posts_tab:
                    logger.info("Posts tab found, clicking...")
                    await posts_tab.click()
                    await page.wait_for_load_state("networkidle")
                    logger.info("Posts tab loaded")
                else:
                    logger.warning("Posts tab not found, staying on current page")
            else:
                # Fallback to direct URL
                logger.warning("Search box not found, using direct URL")
                search_url = f"https://www.facebook.com/search/posts/?q={keyword}"
                logger.info(f"Navigating to: {search_url}")
                await page.goto(search_url, wait_until="networkidle")
            
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
        """Scroll, extract links from span.xjp7ctv > a, visit profiles, check if user, save to database."""
        logger.info(f"Starting extraction for keyword: '{keyword}' (target: {max_results} posts)")
        
        # Scroll a few times to load more posts
        logger.info("Scrolling to load posts...")
        for i in range(2):
            await human_scroll(page, scrolls=2)
            await asyncio.sleep(random.uniform(3, 5))
        
        # Extract entire page HTML
        logger.info("Extracting full page HTML...")
        full_html = await page.content()
        logger.info(f"Extracted HTML ({len(full_html)} characters)")
        
        # Extract links from span.xjp7ctv > a (direct profile links)
        logger.info("Extracting direct profile links from span.xjp7ctv > a...")
        direct_links = await page.evaluate(
            """
            () => {
                const links = [];
                
                // Find all span tags with class xjp7ctv
                const spans = document.querySelectorAll('span.xjp7ctv');
                console.log(`Found ${spans.length} span.xjp7ctv elements`);
                
                spans.forEach((span, index) => {
                    // Find the a tag inside
                    const aTag = span.querySelector('a');
                    if (aTag && aTag.href) {
                        const href = aTag.href;
                        const text = aTag.textContent.trim();
                        
                        links.push({
                            url: href,
                            text: text,
                            type: 'direct'
                        });
                        
                        if (index < 10) {
                            console.log(`Direct link ${index + 1}: ${text} -> ${href}`);
                        }
                    }
                });
                
                console.log(`Extracted ${links.length} direct links`);
                return links;
            }
            """
        )
        
        # Extract group post author links
        logger.info("Extracting group post author links...")
        group_links = await page.evaluate(
            """
            () => {
                const links = [];
                
                // Find all a tags that contain the specific span for group post authors
                const aTags = document.querySelectorAll('a');
                
                aTags.forEach((aTag, index) => {
                    // Check if this a tag has the specific span child
                    const span = aTag.querySelector('span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.x1xmvt09.x1nxh6w3.x1sibtaa.x1s688f.xi81zsa');
                    if (span && aTag.href && aTag.href.includes('/groups/')) {
                        const href = aTag.href;
                        const text = span.textContent.trim();
                        
                        links.push({
                            url: href,
                            text: text,
                            type: 'group'
                        });
                        
                        if (index < 10) {
                            console.log(`Group link ${index + 1}: ${text} -> ${href}`);
                        }
                    }
                });
                
                console.log(`Extracted ${links.length} group post author links`);
                return links;
            }
            """
        )
        
        # Combine both types of links
        all_links = direct_links + group_links
        logger.info(f"✓ Total extracted: {len(direct_links)} direct + {len(group_links)} group = {len(all_links)} links")
        logger.info(f"Filtering to odd indices only (1, 3, 5...) to avoid duplicates")
        
        # Visit each profile and check if it's a user
        # Process in batches for parallel execution
        users_saved = 0
        batch_size = 3  # Process 3 profiles simultaneously
        
        # Filter to odd indices only to avoid duplicates
        filtered_links = [link for idx, link in enumerate(all_links, 1) if idx % 2 != 0]
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
                new_page = await self.browser_manager.create_page_with_cookies(account['uid'])
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
        
        try:
            # Handle group posts differently
            if link_type == 'group':
                logger.info(f"  Processing group post author...")
                # Navigate to the group user page
                await page.goto(link_url, wait_until="networkidle", timeout=30000)
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
                await page.goto(profile_url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(random.uniform(2, 4))
            else:
                # Direct profile link
                profile_url = link_url
                # Visit the profile
                await page.goto(profile_url, wait_until="networkidle", timeout=30000)
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
            
            if unique_locations:
                # This is a user (not channel/group)
                # Concatenate multiple locations with comma
                location_text = ', '.join(unique_locations)
                logger.info(f"  ✓ User detected! Location: {location_text}")
                
                # Try to extract post content from the original search page
                # For now, we'll save what we have
                post_content = None  # Will be extracted later if needed
                
                # Save to database
                try:
                    search_result = SearchResult(
                        name=final_name,
                        location=location_text,
                        post_content=post_content,
                        post_url=None,  # We don't have the specific post URL yet
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
                logger.info(f"  ✗ Not a user (channel/group) - location not found")
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
