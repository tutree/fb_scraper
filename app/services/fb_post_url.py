"""
Helpers for capturing a canonical post URL via the Share → Copy link flow.
"""
import asyncio
import random
from typing import Dict, Optional

from playwright.async_api import Page

from ..core.logging_config import get_logger

logger = get_logger(__name__)


async def capture_post_url_via_share_button(
    page: Page,
    link: Dict,
) -> Optional[str]:
    """
    Open a post card's Share sheet and click "Copy link".
    Returns copied URL when available.
    """
    visible_index = link.get("visible_index")
    if visible_index is None:
        return None

    try:
        post_index = int(visible_index)
    except Exception:
        return None

    try:
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
