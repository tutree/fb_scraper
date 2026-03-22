"""
Helpers for capturing a canonical post URL via the Share → Copy link flow.
"""
import asyncio
import random
from typing import Dict, Optional

from playwright.async_api import Page

from ..core.logging_config import get_logger
from .fb_search_feed_scroll import scroll_search_page_until_profile_card_visible

logger = get_logger(__name__)


def is_usable_post_url_for_permalink_flow(url: Optional[str]) -> bool:
    """
    True if we can open comments via page.goto(post_url) and the permalink dialog flow
    (avoids search-feed virtualization). Includes /share/p/ short links (redirect to /posts/).
    Excludes bare profile-only URLs.
    """
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if not u.startswith("http"):
        return False
    low = u.lower().split("?")[0]
    if "/posts/" in low or "/permalink/" in low:
        return True
    if "facebook.com/share/" in low or "/share/p/" in low:
        return True
    return False

# Match post card by author profile URL, then open Share (same idea as comment trigger).
_SHARE_CLICK_FOR_PROFILE_JS = """
(profileHref) => {
    function norm(u) {
        try {
            const url = new URL(u, window.location.origin);
            return (url.origin + url.pathname).replace(/\\/$/, '').toLowerCase();
        } catch (_) {
            return (u || '').split('?')[0].replace(/\\/$/, '').toLowerCase();
        }
    }
    const target = norm(profileHref || '');
    if (!target) return { ok: false, reason: 'no_target' };

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
            if (!h) continue;
            if (h.includes(target) || target.includes(h)) {
                try {
                    card.scrollIntoView({ block: 'center', behavior: 'instant' });
                } catch (_) {}

                const inner = card.querySelector('div[data-ad-rendering-role="share_button"]');
                let button = inner ? inner.closest('div[role="button"]') : null;

                if (!button) {
                    const cand = card.querySelectorAll('div[role="button"], span[role="button"], a[role="button"]');
                    for (const el of cand) {
                        const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                        const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                        if (
                            text === 'share' ||
                            aria.includes('send this to friends') ||
                            aria.includes('share')
                        ) {
                            button = el;
                            break;
                        }
                    }
                }

                if (!button) return { ok: false, reason: 'no_share_button', matched: true, cards: candidates.length };

                button.click();
                return { ok: true, matched: true, cards: candidates.length };
            }
        }
    }
    return { ok: false, reason: 'no_card', cards: candidates.length };
}
"""


async def capture_post_url_via_share_button(
    page: Page,
    link: Dict,
) -> Optional[str]:
    """
    Open a post card's Share sheet and click "Copy link".
    Returns copied URL when available.

    Prefer matching the post card by profile URL (feed virtualizes; visible_index is often stale).
    Fall back to visible_index when profile match fails.
    """
    profile_href = (link.get("url") or "").strip()
    visible_index = link.get("visible_index")

    try:
        # Re-mount the correct row before Share (same issue as comment clicks).
        if profile_href and "/search/" in (page.url or "").lower():
            await scroll_search_page_until_profile_card_visible(page, profile_href)

        clicked_share = False
        if profile_href:
            share_res = await page.evaluate(_SHARE_CLICK_FOR_PROFILE_JS, profile_href)
            if isinstance(share_res, dict) and share_res.get("ok"):
                clicked_share = True
                logger.debug(
                    "  [PostURL] Share opened via profile match (cards=%s)",
                    share_res.get("cards"),
                )
            else:
                logger.debug(
                    "  [PostURL] Share profile-match failed: %s — trying visible_index",
                    share_res,
                )

        if not clicked_share:
            if visible_index is None:
                return None
            try:
                post_index = int(visible_index)
            except Exception:
                return None

            card_found = await page.evaluate(
                """
                (idx) => {
                    const main = document.querySelector('div[role="main"]') || document;
                    const articles = main.querySelectorAll('div[role="article"]');
                    const feed = main.querySelector('div[role="feed"]');
                    const cards = articles.length > 0 ? Array.from(articles) : (feed ? Array.from(feed.children) : []);
                    const card = cards[idx];
                    if (!card) return false;
                    card.scrollIntoView({ block: 'center', behavior: 'instant' });
                    return true;
                }
                """,
                post_index,
            )
            if not card_found:
                return None

            await asyncio.sleep(random.uniform(0.8, 1.5))

            clicked_share = await page.evaluate(
                """
                (idx) => {
                    const main = document.querySelector('div[role="main"]') || document;
                    const articles = main.querySelectorAll('div[role="article"]');
                    const feed = main.querySelector('div[role="feed"]');
                    const cards = articles.length > 0 ? Array.from(articles) : (feed ? Array.from(feed.children) : []);
                    const card = cards[idx];
                    if (!card) return false;

                    const inner = card.querySelector('div[data-ad-rendering-role="share_button"]');
                    let button = inner ? inner.closest('div[role="button"]') : null;

                    if (!button) {
                        const candidates = card.querySelectorAll('div[role="button"], span[role="button"], a[role="button"]');
                        for (const el of candidates) {
                            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                            const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                            if (
                                text === 'share' ||
                                aria.includes('send this to friends') ||
                                aria.includes('share')
                            ) {
                                button = el;
                                break;
                            }
                        }
                    }

                    if (!button) return false;
                    button.click();
                    return true;
                }
                """,
                post_index,
            )
            if not clicked_share:
                logger.debug("  [PostURL] Share button not found for card index %d", post_index)
                return None
        else:
            await asyncio.sleep(random.uniform(0.8, 1.5))

        logger.debug("  [PostURL] Share button clicked, waiting for share dialog...")
        await asyncio.sleep(random.uniform(1.1, 2.0))

        # Step 1: Try to extract URL directly from share dialog (no clipboard needed)
        direct_url = await page.evaluate(
            """
            () => {
                const dialog = document.querySelector('[role="dialog"]') || document;
                const inputs = dialog.querySelectorAll('input[type="text"], input[readonly], input');
                for (const input of inputs) {
                    const val = (input.value || '').trim();
                    if (val.startsWith('http') && val.includes('facebook.com')) {
                        return val.split('&__')[0];
                    }
                }
                const anchors = Array.from(dialog.querySelectorAll('a[href]'));
                for (const anchor of anchors) {
                    const href = (anchor.href || '').trim();
                    if (!href) continue;
                    if (href.includes('/share/p/')) {
                        return href.split('&__')[0];
                    }
                    try {
                        const url = new URL(href);
                        const textParam = url.searchParams.get('text');
                        if (!textParam) continue;
                        const decoded = decodeURIComponent(textParam);
                        const match = decoded.match(/https?:\\/\\/[^\\s]+/i);
                        if (match && match[0] && match[0].includes('facebook.com')) {
                            return match[0].replace(/([?&])fbclid=[^&]+/i, '');
                        }
                    } catch (_) {}
                }
                return '';
            }
            """
        )
        direct_url = str(direct_url or "").strip()
        if direct_url.startswith("http"):
            logger.debug("  [PostURL] Got URL from share dialog directly: %s", direct_url[:80])
            return direct_url

        # Step 2: Try clicking "Copy link" and reading clipboard
        copy_clicked = await page.evaluate(
            """
            () => {
                const dialog = document.querySelector('[role="dialog"]');
                if (!dialog) return false;

                const labels = Array.from(dialog.querySelectorAll('span, div')).filter((el) => {
                    const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                    return text === 'copy link';
                });
                for (const label of labels) {
                    const button = label.closest('div[role="button"], a[role="link"], span[role="button"]');
                    if (button) {
                        button.click();
                        return true;
                    }
                }

                const direct = Array.from(dialog.querySelectorAll('div[role="button"], a[role="link"]')).find((el) => {
                    const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                    return text.includes('copy link');
                });
                if (direct) {
                    direct.click();
                    return true;
                }
                return false;
            }
            """
        )
        if not copy_clicked:
            logger.debug("  [PostURL] 'Copy link' button not found in share dialog")
            return None

        await asyncio.sleep(random.uniform(0.3, 0.9))

        copied_url = await page.evaluate(
            """
            async () => {
                try {
                    if (navigator.clipboard && navigator.clipboard.readText) {
                        const value = await navigator.clipboard.readText();
                        return (value || '').trim();
                    }
                } catch (_) {}
                return '';
            }
            """
        )
        copied_url = str(copied_url or "").strip()
        if copied_url.startswith("http"):
            logger.debug("  [PostURL] Got URL from clipboard: %s", copied_url[:80])
            return copied_url

        logger.debug("  [PostURL] Clipboard read failed or empty, share flow exhausted")

    except Exception as exc:
        logger.debug("  [PostURL] Share -> Copy link flow failed: %s", exc)
    finally:
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.25)
        except Exception:
            pass

    return None
