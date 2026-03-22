"""
Scroll helpers for Facebook search results when the feed virtualizes rows.
Shared by Share→Copy link and comment dialog flows (stale visible_index).
"""
import asyncio

from playwright.async_api import Page

from ..core.logging_config import get_logger

logger = get_logger(__name__)

# Find a search-result card whose author link matches profilePath; scroll it into view.
FIND_PROFILE_POST_CARD_IN_SEARCH_JS = """
(pathNorm) => {
    function norm(u) {
        try {
            const url = new URL(u, window.location.origin);
            return (url.origin + url.pathname).replace(/\\/$/, '').toLowerCase();
        } catch (_) {
            return (u || '').split('?')[0].replace(/\\/$/, '').toLowerCase();
        }
    }
    const target = norm(pathNorm);
    if (!target) return { ok: false };
    const main = document.querySelector('div[role="main"]') || document;
    const candidates = [];
    for (const el of main.querySelectorAll('div[role="article"]')) candidates.push(el);
    const feed = main.querySelector('div[role="feed"]');
    if (feed) {
        for (const el of feed.children) candidates.push(el);
    }
    for (const card of candidates) {
        for (const a of card.querySelectorAll('a[href*="facebook.com"]')) {
            const h = norm(a.href || '');
            if (h && (h.includes(target) || target.includes(h))) {
                try {
                    card.scrollIntoView({ block: 'center', behavior: 'instant' });
                } catch (_) {}
                return { ok: true, cardCount: candidates.length };
            }
        }
    }
    return { ok: false, cardCount: candidates.length };
}
"""


async def scroll_search_page_until_profile_card_visible(
    page: Page,
    profile_path: str,
    max_steps: int = 50,
) -> bool:
    """
    Scroll the search feed until a card containing this profile's link is mounted,
    then scroll that card into view. Needed when visible_index is stale after
    virtualization (e.g. only one feed child left while index was 9).
    """
    path = profile_path.split("?")[0].rstrip("/").lower()
    if "/search/" not in (page.url or "").lower():
        return True
    try:
        await page.evaluate("() => { window.scrollTo(0, 0); }")
        await asyncio.sleep(0.4)
    except Exception:
        pass

    for step in range(max_steps):
        try:
            r = await page.evaluate(FIND_PROFILE_POST_CARD_IN_SEARCH_JS, path)
            if isinstance(r, dict) and r.get("ok"):
                logger.info(
                    "  [SearchFeed] Profile post card in DOM after scroll (step=%d, cards=%s)",
                    step,
                    r.get("cardCount"),
                )
                await asyncio.sleep(0.5)
                return True
        except Exception as exc:
            logger.debug("  [SearchFeed] find card evaluate: %s", exc)
        try:
            await page.evaluate("window.scrollBy(0, 700)")
        except Exception:
            break
        await asyncio.sleep(0.35)

    logger.warning(
        "  [SearchFeed] Profile post card not found after %d scroll steps (virtualized feed?)",
        max_steps,
    )
    return False
