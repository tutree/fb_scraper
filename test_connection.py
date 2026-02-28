"""
Connection diagnostic test script
Tests proxy speed, latency, and Facebook access
"""
import asyncio
import time
import httpx
from playwright.async_api import async_playwright
import sys

PROXY = "socks5://host.docker.internal:1080"

async def test_1_basic_proxy():
    """Test 1: Basic proxy connectivity"""
    print("\n" + "="*60)
    print("TEST 1: Basic Proxy Connectivity")
    print("="*60)
    
    try:
        start = time.time()
        async with httpx.AsyncClient(proxies=PROXY, timeout=10.0) as client:
            response = await client.get("https://api.ipify.org?format=json")
            elapsed = time.time() - start
            
            if response.status_code == 200:
                ip = response.json().get("ip")
                print(f"✓ Proxy working!")
                print(f"  Your IP through proxy: {ip}")
                print(f"  Response time: {elapsed:.2f}s")
                return True
            else:
                print(f"✗ Proxy returned status {response.status_code}")
                return False
    except Exception as e:
        print(f"✗ Proxy connection failed: {e}")
        return False


async def test_2_proxy_speed():
    """Test 2: Proxy download speed"""
    print("\n" + "="*60)
    print("TEST 2: Proxy Speed Test")
    print("="*60)
    
    try:
        # Download a small file to test speed
        url = "https://www.google.com"
        
        start = time.time()
        async with httpx.AsyncClient(proxies=PROXY, timeout=30.0) as client:
            response = await client.get(url)
            elapsed = time.time() - start
            
            size_kb = len(response.content) / 1024
            speed_kbps = size_kb / elapsed
            
            print(f"✓ Downloaded {size_kb:.1f} KB in {elapsed:.2f}s")
            print(f"  Speed: {speed_kbps:.1f} KB/s")
            
            if elapsed > 5:
                print(f"  ⚠ WARNING: Slow connection (>{elapsed:.1f}s for Google)")
            
            return True
    except Exception as e:
        print(f"✗ Speed test failed: {e}")
        return False


async def test_3_facebook_access():
    """Test 3: Facebook accessibility through proxy"""
    print("\n" + "="*60)
    print("TEST 3: Facebook Access Test")
    print("="*60)
    
    try:
        start = time.time()
        async with httpx.AsyncClient(proxies=PROXY, timeout=30.0, follow_redirects=True) as client:
            response = await client.get("https://www.facebook.com")
            elapsed = time.time() - start
            
            print(f"✓ Facebook accessible")
            print(f"  Status: {response.status_code}")
            print(f"  Response time: {elapsed:.2f}s")
            print(f"  Content length: {len(response.content)} bytes")
            
            if elapsed > 10:
                print(f"  ⚠ WARNING: Slow Facebook access (>{elapsed:.1f}s)")
            
            if "login" in response.text.lower():
                print(f"  ℹ Facebook login page detected (expected without cookies)")
            
            return True
    except Exception as e:
        print(f"✗ Facebook access failed: {e}")
        return False


async def test_4_playwright_proxy():
    """Test 4: Playwright with proxy"""
    print("\n" + "="*60)
    print("TEST 4: Playwright Browser with Proxy")
    print("="*60)
    
    try:
        async with async_playwright() as p:
            print("  Launching browser...")
            start = time.time()
            browser = await p.chromium.launch(
                headless=True,
                proxy={"server": PROXY}
            )
            launch_time = time.time() - start
            print(f"  ✓ Browser launched in {launch_time:.2f}s")
            
            context = await browser.new_context()
            page = await context.new_page()
            
            # Test navigation speed
            print("  Navigating to Facebook...")
            start = time.time()
            await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=30000)
            nav_time = time.time() - start
            
            print(f"  ✓ Page loaded in {nav_time:.2f}s")
            
            title = await page.title()
            print(f"  Page title: {title}")
            
            if nav_time > 15:
                print(f"  ⚠ WARNING: Slow page load (>{nav_time:.1f}s)")
            
            await browser.close()
            return True
            
    except Exception as e:
        print(f"✗ Playwright test failed: {e}")
        return False


async def test_5_profile_load_speed():
    """Test 5: Load a Facebook profile page"""
    print("\n" + "="*60)
    print("TEST 5: Facebook Profile Load Test")
    print("="*60)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy={"server": PROXY}
            )
            
            # Load cookies
            import json
            from pathlib import Path
            
            cookies_file = Path("cookies/61564929938453.json")
            if cookies_file.exists():
                with open(cookies_file) as f:
                    storage_state = json.load(f)
                context = await browser.new_context(storage_state=storage_state)
                print("  ✓ Cookies loaded")
            else:
                context = await browser.new_context()
                print("  ℹ No cookies found, testing without login")
            
            page = await context.new_page()
            
            # Test loading a public profile
            test_url = "https://www.facebook.com/zuck"  # Mark Zuckerberg's public profile
            
            print(f"  Loading profile: {test_url}")
            start = time.time()
            
            try:
                await page.goto(test_url, wait_until="domcontentloaded", timeout=30000)
                load_time = time.time() - start
                
                print(f"  ✓ Profile loaded in {load_time:.2f}s")
                
                if load_time > 20:
                    print(f"  ⚠ WARNING: Very slow profile load (>{load_time:.1f}s)")
                elif load_time > 10:
                    print(f"  ⚠ WARNING: Slow profile load (>{load_time:.1f}s)")
                else:
                    print(f"  ✓ Good speed!")
                
            except Exception as e:
                load_time = time.time() - start
                print(f"  ✗ Profile load timeout after {load_time:.2f}s")
                print(f"  Error: {e}")
            
            await browser.close()
            return True
            
    except Exception as e:
        print(f"✗ Profile load test failed: {e}")
        return False


async def main():
    print("\n" + "="*60)
    print("FACEBOOK SCRAPER CONNECTION DIAGNOSTICS")
    print("="*60)
    print(f"Testing proxy: {PROXY}")
    print(f"Expected: SSH tunnel to 100.85.92.28 (shakil@100.85.92.28)")
    
    results = {}
    
    # Run all tests
    results['basic_proxy'] = await test_1_basic_proxy()
    results['proxy_speed'] = await test_2_proxy_speed()
    results['facebook_access'] = await test_3_facebook_access()
    results['playwright_proxy'] = await test_4_playwright_proxy()
    results['profile_load'] = await test_5_profile_load_speed()
    
    # Summary
    print("\n" + "="*60)
    print("DIAGNOSTIC SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, passed_test in results.items():
        status = "✓ PASS" if passed_test else "✗ FAIL"
        print(f"  {test_name:20s}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All tests passed! Connection is good.")
        print("  → Problem is likely in the scraper code logic")
    elif results.get('basic_proxy') and results.get('facebook_access'):
        print("\n⚠ Connection works but is SLOW")
        print("  → Optimize SSH tunnel or use faster connection")
    else:
        print("\n✗ Connection issues detected")
        print("  → Check SSH tunnel: ssh -D 1080 shakil@100.85.92.28")
        print("  → Make sure the tunnel is running before testing")
    
    return passed == total


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
