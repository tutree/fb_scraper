"""
Strict logged-in check for Facebook: session is treated as logged in only if the
logged-in UI exposes the Reels tab link (same entry point as in the main nav).

See: https://www.facebook.com/reel/?s=tab
"""
from playwright.async_api import Page


async def page_has_logged_in_reel_tab_link(page: Page) -> bool:
    """
    True if the page DOM contains an anchor whose resolved URL is the Reels tab
    (path under /reel/ and query includes s=tab).
    """
    try:
        return await page.evaluate(
            """
            () => {
                const anchors = document.querySelectorAll('a[href]');
                for (const a of anchors) {
                    try {
                        const raw = a.getAttribute('href') || '';
                        const u = new URL(raw, location.origin);
                        const host = (u.hostname || '').toLowerCase();
                        if (!host.includes('facebook.com')) continue;
                        const path = (u.pathname || '').toLowerCase();
                        const search = (u.search || '').toLowerCase();
                        if (!path.startsWith('/reel')) continue;
                        if (search.includes('s=tab') || search === '?s=tab' || '&s=tab' in search) {
                            return true;
                        }
                    } catch (e) {
                        continue;
                    }
                }
                return false;
            }
            """
        )
    except Exception:
        return False
