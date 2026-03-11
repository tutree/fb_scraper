"""
Human-like mouse, scroll, and session warmup helpers.
"""
import asyncio
import random

from playwright.async_api import Page

from ..core.logging_config import get_logger

logger = get_logger(__name__)


async def human_mouse_move(page: Page, x: int, y: int) -> None:
    """Move mouse along a curved path to appear human."""
    try:
        start_x = random.randint(200, 900)
        start_y = random.randint(200, 600)
        steps = random.randint(10, 25)
        for i in range(steps + 1):
            t = i / steps
            ease = t * t * (3 - 2 * t)
            cx = int(start_x + (x - start_x) * ease + random.randint(-3, 3))
            cy = int(start_y + (y - start_y) * ease + random.randint(-3, 3))
            await page.mouse.move(cx, cy)
            await asyncio.sleep(random.uniform(0.005, 0.020))
    except Exception:
        pass


async def human_scroll(page: Page, scrolls: int = None) -> None:
    """Simulate human-like scrolling behaviour."""
    if scrolls is None:
        scrolls = random.randint(3, 6)
    for _ in range(scrolls):
        scroll_amount = random.randint(300, 800)
        steps = random.randint(3, 8)
        per_step = scroll_amount // steps
        for _ in range(steps):
            await page.evaluate(f"window.scrollBy(0, {per_step + random.randint(-20, 20)})")
            await asyncio.sleep(random.uniform(0.05, 0.15))
        await asyncio.sleep(random.uniform(1.5, 4.0))
        if random.random() < 0.3:
            back_scroll = random.randint(100, 300)
            await page.evaluate(f"window.scrollBy(0, -{back_scroll})")
            await asyncio.sleep(random.uniform(0.5, 2.0))
        if random.random() < 0.4:
            await asyncio.sleep(random.uniform(2.0, 5.0))
        await human_mouse_move(page, random.randint(200, 1200), random.randint(200, 700))


async def warmup_session(page: Page) -> None:
    """Browse like a human before scraping to build session credibility."""
    try:
        logger.info("Starting session warmup...")
        await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=90000)
        await asyncio.sleep(random.uniform(3, 6))
        for _ in range(random.randint(4, 7)):
            await human_mouse_move(page, random.randint(100, 1300), random.randint(100, 700))
            await asyncio.sleep(random.uniform(0.4, 1.2))
        for _ in range(random.randint(3, 5)):
            await page.evaluate(f"window.scrollBy(0, {random.randint(150, 400)})")
            await asyncio.sleep(random.uniform(1.5, 3.5))
            await human_mouse_move(page, random.randint(300, 900), random.randint(200, 600))
            await asyncio.sleep(random.uniform(0.5, 1.5))
        if random.random() < 0.4:
            await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            await asyncio.sleep(random.uniform(1, 2.5))
        if random.random() < 0.35:
            try:
                await page.goto("https://www.facebook.com/notifications", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(random.uniform(3, 6))
                await human_mouse_move(page, random.randint(300, 800), random.randint(200, 500))
                await asyncio.sleep(random.uniform(1, 2))
            except Exception:
                pass
        logger.info("Session warmup completed")
    except Exception as e:
        logger.warning(f"Warmup session error (non-critical): {e}")
