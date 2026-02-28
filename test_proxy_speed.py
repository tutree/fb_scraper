#!/usr/bin/env python3
"""
Test proxy speed with and without resource blocking.
This demonstrates the dramatic speed improvement from blocking images/CSS/fonts.
"""
import asyncio
import time
from playwright.async_api import async_playwright


async def test_full_page_load():
    """Load Facebook with all resources (slow)"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy={'server': 'socks5://host.docker.internal:1080'}
        )
        context = await browser.new_context()
        page = await context.new_page()
        
        start = time.time()
        try:
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=60000)
            elapsed = time.time() - start
            print(f"✓ Full page load: {elapsed:.2f}s")
            
            # Count resources loaded
            resources = await page.evaluate("() => performance.getEntriesByType('resource').length")
            print(f"  Resources loaded: {resources}")
            
        except Exception as e:
            elapsed = time.time() - start
            print(f"✗ Full page load failed after {elapsed:.2f}s: {e}")
        
        await browser.close()
        return elapsed


async def test_blocked_resources():
    """Load Facebook with images/CSS/fonts blocked (fast)"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            proxy={'server': 'socks5://host.docker.internal:1080'}
        )
        context = await browser.new_context()
        
        # Block unnecessary resources
        async def block_resources(route, request):
            resource_type = request.resource_type
            if resource_type in ["image", "media", "font", "stylesheet"]:
                await route.abort()
            else:
                await route.continue_()
        
        await context.route("**/*", block_resources)
        
        page = await context.new_page()
        
        start = time.time()
        try:
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=60000)
            elapsed = time.time() - start
            print(f"✓ Blocked resources load: {elapsed:.2f}s")
            
            # Count resources loaded
            resources = await page.evaluate("() => performance.getEntriesByType('resource').length")
            print(f"  Resources loaded: {resources}")
            
        except Exception as e:
            elapsed = time.time() - start
            print(f"✗ Blocked resources load failed after {elapsed:.2f}s: {e}")
        
        await browser.close()
        return elapsed


async def main():
    print("=" * 80)
    print("PROXY SPEED TEST - Resource Blocking Comparison")
    print("=" * 80)
    print()
    
    print("Test 1: Full page load (all resources)")
    print("-" * 80)
    full_time = await test_full_page_load()
    print()
    
    print("Test 2: Blocked resources (HTML + JS only)")
    print("-" * 80)
    blocked_time = await test_blocked_resources()
    print()
    
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Full page load:      {full_time:.2f}s")
    print(f"Blocked resources:   {blocked_time:.2f}s")
    if full_time > 0 and blocked_time > 0:
        speedup = full_time / blocked_time
        print(f"Speed improvement:   {speedup:.1f}x faster")
        print(f"Time saved:          {full_time - blocked_time:.2f}s ({((full_time - blocked_time) / full_time * 100):.0f}%)")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
