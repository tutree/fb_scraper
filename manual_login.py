#!/usr/bin/env python3
"""
Manual login script - Opens a browser for you to login manually.
After successful login, it saves the session cookies for automated use.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services.browser_manager import BrowserManager
from app.core.logging_config import setup_logging, get_logger
import json

setup_logging(level="INFO")
logger = get_logger(__name__)


async def manual_login(account_uid: str):
    """Open browser for manual login and save cookies."""
    
    logger.info("=" * 80)
    logger.info("MANUAL LOGIN - COOKIE SAVER")
    logger.info("=" * 80)
    logger.info(f"Account: {account_uid}")
    logger.info("")
    logger.info("Instructions:")
    logger.info("1. A browser window will open")
    logger.info("2. Login to Facebook manually")
    logger.info("3. Complete any 2FA or security checks")
    logger.info("4. Once logged in, press ENTER in this terminal")
    logger.info("5. Cookies will be saved for automated use")
    logger.info("=" * 80)
    logger.info("")
    
    browser_manager = BrowserManager(proxy_manager=None)
    
    try:
        # Create browser in NON-headless mode for manual interaction
        browser_manager.playwright = await asyncio.get_event_loop().run_in_executor(
            None, lambda: __import__('playwright.sync_api').sync_api.sync_playwright().start()
        )
        
        # Actually, let's use async properly
        from playwright.async_api import async_playwright
        
        playwright = await async_playwright().start()
        
        # Launch browser in headed mode
        logger.info("Launching browser (you will see the window)...")
        browser = await playwright.chromium.launch(
            headless=False,  # Show browser window
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        
        # Create context
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
        )
        
        # Add stealth scripts
        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            delete navigator.__proto__.webdriver;
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };
        """
        )
        
        page = await context.new_page()
        
        # Navigate to Facebook
        logger.info("Opening Facebook login page...")
        await page.goto("https://www.facebook.com/login")
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("BROWSER IS OPEN - Please login manually now")
        logger.info("=" * 80)
        logger.info("")
        
        # Wait for user to login
        input("Press ENTER after you have successfully logged in...")
        
        # Check if logged in
        logger.info("Checking if logged in...")
        await page.goto("https://www.facebook.com", wait_until="networkidle")
        
        nav = await page.query_selector('div[role="navigation"]')
        if not nav:
            logger.error("Login verification failed - navigation not found")
            logger.error("Please make sure you are logged in and try again")
            return False
        
        logger.info("✓ Login verified!")
        
        # Save cookies
        logger.info("Saving session cookies...")
        cookies_dir = Path("cookies")
        cookies_dir.mkdir(exist_ok=True)
        cookies_file = cookies_dir / f"{account_uid}.json"
        
        storage_state = await context.storage_state()
        
        with open(cookies_file, 'w') as f:
            json.dump(storage_state, f, indent=2)
        
        logger.info(f"✓ Cookies saved to: {cookies_file}")
        logger.info("")
        logger.info("=" * 80)
        logger.info("SUCCESS! You can now run the scraper without manual login")
        logger.info("=" * 80)
        logger.info("")
        logger.info("The scraper will automatically use these cookies.")
        logger.info("If Facebook logs you out, just run this script again.")
        
        # Close browser
        await browser.close()
        await playwright.stop()
        
        return True
        
    except Exception as e:
        logger.error(f"Error during manual login: {e}", exc_info=True)
        return False


async def main():
    """Main entry point."""
    
    # Load accounts from config
    from app.services.facebook_scraper import load_accounts
    accounts = load_accounts()
    
    if not accounts:
        logger.error("No accounts found in config/credentials.json")
        return 1
    
    logger.info("Available accounts:")
    for idx, acc in enumerate(accounts, 1):
        uid = acc.get('uid', 'Unknown')
        logger.info(f"  {idx}. {uid}")
    
    logger.info("")
    
    if len(accounts) == 1:
        account = accounts[0]
        logger.info(f"Using account: {account['uid']}")
    else:
        choice = input(f"Select account (1-{len(accounts)}): ").strip()
        try:
            account = accounts[int(choice) - 1]
        except (ValueError, IndexError):
            logger.error("Invalid selection")
            return 1
    
    logger.info("")
    success = await manual_login(account['uid'])
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
