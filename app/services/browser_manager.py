from playwright.async_api import async_playwright, Browser, Page
from typing import Optional
import random
from tenacity import retry, stop_after_attempt, wait_exponential
from ..services.proxy_manager import ProxyManager
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class BrowserManager:
    def __init__(self, proxy_manager: Optional[ProxyManager] = None):
        self.proxy_manager = proxy_manager
        self.browser: Optional[Browser] = None
        self.playwright = None
        
        # Randomized viewports for fingerprint diversity
        self.viewports = [
            {"width": 1920, "height": 1080},
            {"width": 1366, "height": 768},
            {"width": 1536, "height": 864},
            {"width": 1440, "height": 900},
            {"width": 1600, "height": 900},
            {"width": 1280, "height": 720},
        ]
        
        # Randomized user agents
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        ]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    async def get_browser(self) -> Browser:
        """Get or create browser instance with proxy."""
        if not self.browser:
            self.playwright = await async_playwright().start()

            launch_options = {
                "headless": False,  # Set to True for production
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-site-isolation-trials",
                    # Additional stealth args
                    "--disable-infobars",
                    "--window-size=1920,1080",
                    "--start-maximized",
                    "--disable-extensions",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-default-apps",
                ],
            }

            # Add proxy if available
            if self.proxy_manager:
                proxy_config = self.proxy_manager.get_next_proxy()
                if proxy_config:
                    launch_options["proxy"] = proxy_config

            self.browser = await self.playwright.chromium.launch(**launch_options)
            logger.info("Browser launched successfully")

        return self.browser

    async def create_page(self) -> Page:
        """Create a new page with enhanced stealth settings."""
        browser = await self.get_browser()
        
        # Randomize viewport and user agent
        viewport = random.choice(self.viewports)
        user_agent = random.choice(self.user_agents)
        
        # Randomize locale and timezone for more diversity
        locales = ["en-US", "en-GB", "en-CA"]
        timezones = ["America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London"]
        
        context = await browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
            locale=random.choice(locales),
            timezone_id=random.choice(timezones),
            # Add more realistic browser features
            has_touch=random.choice([True, False]),
            is_mobile=False,
            device_scale_factor=random.choice([1, 1.5, 2]),
        )

        # Enhanced stealth scripts with more comprehensive evasion
        await context.add_init_script(
            """
            // Hide webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Delete automation indicators
            delete navigator.__proto__.webdriver;
            
            // Mock plugins with realistic data
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Mock languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            
            // Mock platform
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32'
            });
            
            // Mock hardware concurrency
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 8
            });
            
            // Mock device memory
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8
            });
            
            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({state: Notification.permission}) :
                    originalQuery(parameters)
            );
            
            // Mock chrome object with more properties
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };
            
            // Hide automation
            Object.defineProperty(navigator, 'maxTouchPoints', {
                get: () => 1
            });
            
            // Mock connection
            Object.defineProperty(navigator, 'connection', {
                get: () => ({
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10,
                    saveData: false
                })
            });
            
            // Override toString to hide proxy
            const originalToString = Function.prototype.toString;
            Function.prototype.toString = function() {
                if (this === navigator.permissions.query) {
                    return 'function query() { [native code] }';
                }
                return originalToString.call(this);
            };
        """
        )

        return await context.new_page()

    async def close(self) -> None:
        """Close browser and playwright."""
        if self.browser:
            await self.browser.close()
            self.browser = None
            logger.info("Browser closed")
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
