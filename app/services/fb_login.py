"""
Facebook login flow (password + optional TOTP 2FA).
"""
import asyncio
import random
from typing import Dict

from playwright.async_api import Page
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.logging_config import get_logger
from .fb_account_loader import generate_2fa_code

logger = get_logger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
)
async def login(page: Page, account: Dict) -> bool:
    """Login to Facebook with UID/password and handle 2FA automatically."""
    uid = account["uid"]
    password = account["password"]
    totp_secret = account.get("totp_secret")

    logger.info(f"=== Starting login process for: {uid} ===")

    try:
        logger.info("Navigating to Facebook login page...")
        await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=90000)
        logger.info("Login page loaded")

        # If cookies were valid, Facebook redirects to feed/home instead of showing the login form.
        current_url = page.url
        logger.info(f"Post-navigation URL: {current_url}")
        if "/login" not in current_url:
            # We were redirected — check whether we actually landed on a logged-in page.
            nav = await page.query_selector('div[role="navigation"]')
            feed = await page.query_selector('div[role="feed"]')
            if nav or feed:
                logger.info(f"Cookie session already active (redirected to {current_url}), skipping form login")
                return True
            logger.info("Redirected away from /login but no nav/feed found — will still try form")

        delay = random.uniform(2.0, 4.0)
        logger.info(f"Waiting {delay:.1f}s before interacting (human-like)...")
        await asyncio.sleep(delay)

        logger.info("Performing random mouse movements...")
        await page.mouse.move(
            random.randint(200, 400),
            random.randint(200, 400),
            steps=random.randint(10, 20),
        )
        await asyncio.sleep(random.uniform(0.5, 1.5))

        logger.info("Looking for email field...")
        email_field = await page.query_selector(
            "#email, input[name='email'], input[type='text'], input[type='email']"
        )
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

        logger.info("Looking for password field...")
        pass_field = await page.query_selector(
            "#pass, input[name='pass'], input[type='password']"
        )
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

        logger.info("Clicking login button...")
        await page.click('button[name="login"]')

        logger.info("Waiting for page to load after login...")
        await page.wait_for_load_state("domcontentloaded", timeout=90000)
        logger.info("Page loaded, checking for 2FA...")

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
            logger.info("No 2FA checkpoint detected")

        logger.info("Verifying login success...")
        nav = await page.query_selector('div[role="navigation"]')
        if nav:
            logger.info(f"Successfully logged in as {uid}")
            return True

        logger.error(f"Login failed for {uid} - no navigation found")
        return False

    except Exception as e:
        logger.error(f"Login exception for {uid}: {e}", exc_info=True)
        raise
