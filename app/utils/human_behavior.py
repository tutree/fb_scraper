from playwright.async_api import Page
import asyncio
import random

async def human_mouse_move(page: Page, x: int, y: int) -> None:
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
        await human_mouse_move(page, random.randint(200, 1200), random.randint(200, 700))

async def random_sleep(min_sec: float = 1.0, max_sec: float = 3.0) -> None:
    """Sleep for a random interval to mimic human hesitation."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))
