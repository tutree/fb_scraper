"""
Comment extraction and dialog interaction helpers.
"""
import asyncio
import datetime
import os
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from playwright.async_api import Page
from sqlalchemy.orm import Session

from ..core.logging_config import get_logger
from ..models.post_comment import PostComment
from .facebook_comment_fix import expand_all_comments_in_dialog
from .facebook_selectors import (
    COMMENT_TRIGGER_FROM_PAGE_JS,
    COMMENT_TRIGGER_FOR_PROFILE_JS,
    DIALOG_DIAG_JS,
    EXTRACT_DIALOG_COMMENTS_JS,
    HAS_DIALOG_JS,
    POST_URL_FROM_DIALOG_JS,
)

logger = get_logger(__name__)

_SCREENSHOTS_DIR = Path(os.environ.get("LOGS_DIR", "logs")) / "screenshots"


async def _screenshot(page, label: str) -> None:
    """Save a PNG to logs/screenshots/<label>_HHMMSS.png, silently skip on error."""
    try:
        _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%H%M%S")
        path = _SCREENSHOTS_DIR / f"{label}_{ts}.png"
        await page.screenshot(path=str(path), full_page=False)
        logger.info("[Screenshot] %s", path)
    except Exception as exc:
        logger.warning("[Screenshot] failed (%s): %s", label, exc)


def resolve_comment_limit(max_comments: int) -> int:
    """Translate a user-facing max_comments to an extraction-safe upper bound."""
    return max_comments if max_comments and max_comments > 0 else 5000


async def expand_inline_comments(
    page: Page,
    max_cycles: int = 180,
    stall_limit: int = 14,
) -> int:
    """
    Expand visible inline "more comments/replies" controls on post pages.
    Waits for lazy rendering and stops when no growth is observed repeatedly.
    """
    no_progress_cycles = 0
    best_count = 0

    for _ in range(max_cycles):
        state = await page.evaluate(
            """
            () => {
                const root = document;
                const clickables = root.querySelectorAll('div[role="button"], span[role="button"], a[role="button"], a, span');
                const include = [
                    /view more comments?/i,
                    /view previous comments?/i,
                    /see more comments?/i,
                    /more comments?/i,
                    /view\\s+\\d+\\s+more\\s+repl/i,
                    /view more repl(?:y|ies)/i,
                    /more repl(?:y|ies)/i,
                ];
                const exclude = /(leave\\s*a\\s*comment|write\\s*a\\s*comment|comment\\s+as|most relevant|all comments|newest)/i;
                let clicked = 0;

                for (const el of clickables) {
                    const text = (el.innerText || el.textContent || '').trim();
                    if (!text || text.length > 120) continue;
                    if (exclude.test(text)) continue;
                    if (!include.some((rx) => rx.test(text))) continue;

                    const visible = !!(el.offsetParent || (el.getClientRects && el.getClientRects().length));
                    if (!visible) continue;

                    try {
                        el.click();
                        clicked += 1;
                    } catch (_) {}
                }

                const count = document.querySelectorAll('div[role="article"][aria-label^="Comment by"]').length;
                return { clicked, count };
            }
            """
        )

        clicked = int(state.get("clicked", 0))
        count = int(state.get("count", 0))

        if count > best_count:
            best_count = count
            no_progress_cycles = 0
        elif clicked == 0:
            no_progress_cycles += 1

        await page.evaluate("window.scrollBy(0, 900)")
        await asyncio.sleep(7)

        if no_progress_cycles >= stall_limit:
            break

    return best_count


async def extract_comments(
    page: Page,
    search_result_id: str,
    db: Session,
    max_comments: int = 0,
) -> int:
    """
    Extract comments from the current post page.
    If max_comments <= 0, attempt to load and extract all available comments.
    """
    try:
        limit = resolve_comment_limit(max_comments)
        logger.info(f"  Extracting comments (limit={limit if max_comments > 0 else 'ALL'})...")

        await asyncio.sleep(random.uniform(1.2, 2.2))

        comment_button_clicked = False
        try:
            logger.info("  Looking for 'Comment' button...")
            click_result = await page.evaluate(COMMENT_TRIGGER_FROM_PAGE_JS)
            if isinstance(click_result, dict):
                comment_button_clicked = bool(click_result.get("clicked"))
                logger.info("  Comment trigger method=%s", click_result.get("method"))
            else:
                comment_button_clicked = bool(click_result)
            if comment_button_clicked:
                await asyncio.sleep(10)
        except Exception as exc:
            logger.debug(f"  Could not click Comment button: {exc}")

        if comment_button_clicked:
            try:
                await page.wait_for_selector('[role="dialog"]', timeout=10000)
            except Exception:
                pass

        has_dialog = await page.evaluate(HAS_DIALOG_JS)

        if has_dialog:
            logger.info("  Comments opened in dialog, expanding all comments/replies...")
            await expand_all_comments_in_dialog(
                page, root_selector='[role="dialog"]', max_cycles=120, stall_limit=10
            )
            comments_data = await page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, limit)
        else:
            logger.info("  No comments dialog detected; skipping inline extraction")
            comments_data = []

        saved_count = 0
        for comment_data in comments_data:
            try:
                comment = PostComment(
                    search_result_id=search_result_id,
                    author_name=comment_data.get("author_name"),
                    author_profile_url=comment_data.get("author_profile_url"),
                    comment_text=comment_data.get("comment_text"),
                    comment_timestamp=comment_data.get("comment_timestamp"),
                )
                db.add(comment)
                saved_count += 1
            except Exception as exc:
                logger.warning(f"  Failed to save comment: {exc}")

        if saved_count > 0:
            db.commit()
            logger.info(f"  Saved {saved_count} comments")
        else:
            logger.info("  No comments found")

        if has_dialog:
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.4)
            except Exception:
                pass

        return saved_count
    except Exception as exc:
        logger.error(f"  Error extracting comments: {exc}")
        return 0


async def click_comments_and_extract_from_dialog(
    page: Page,
    profile_url: str,
    max_comments: int = 0,
    visible_index: Optional[int] = None,
) -> Tuple[List[Dict], Optional[str]]:
    """
    On the search results page: find the post containing this profile link,
    click its Comments button to open the dialog, extract comments, then close with ESC.
    Returns (comments: List[Dict], post_url: Optional[str]).
    """
    comments_data: List[Dict] = []
    post_url_from_dialog: Optional[str] = None
    try:
        limit = resolve_comment_limit(max_comments)
        profile_path = profile_url.split("?")[0].rstrip("/").lower()

        logger.info(f"  [Comments] Starting comment extraction for profile: {profile_path}")
        logger.info(f"  [Comments] visible_index={visible_index}, limit={limit if max_comments > 0 else 'ALL'}")

        await _screenshot(page, f"02_before_comment_click_{profile_path.split('/')[-1][:20]}")

        click_result = await page.evaluate(
            COMMENT_TRIGGER_FOR_PROFILE_JS,
            {
                "profilePath": profile_path,
                "preferredIdx": int(visible_index) if isinstance(visible_index, int) else None,
            },
        )

        if isinstance(click_result, dict):
            clicked = bool(click_result.get("clicked"))
            logger.info(
                f"  [Comments click] clicked={clicked} | method={click_result.get('method')} | "
                f"matchedIdx={click_result.get('matchedIdx')} | containers={click_result.get('containersCount')} "
                f"(articles={click_result.get('articlesCount')}, hasFeed={click_result.get('hasFeed')}) | "
                f"pageUrl={click_result.get('pageUrl')}"
            )
        else:
            clicked = bool(click_result)
            logger.info(f"  [Comments click] clicked={clicked} (legacy bool result)")

        if not clicked:
            dom_diag = await page.evaluate(
                """
                () => ({
                    url: location.href.substring(0, 120),
                    roleMain: !!document.querySelector('[role="main"]'),
                    roleFeed: !!document.querySelector('[role="feed"]'),
                    roleArticle: document.querySelectorAll('[role="article"]').length,
                    commentButtonMarkers: document.querySelectorAll('[data-ad-rendering-role="comment_button"]').length,
                    leaveCommentBtns: document.querySelectorAll('[aria-label*="comment" i][role="button"]').length,
                })
                """
            )
            logger.warning(f"  [Comments click] FAILED - no comment button found. DOM state: {dom_diag}")
            return comments_data, post_url_from_dialog

        logger.info("  [Comments click] SUCCESS - waiting for dialog to open...")
        await _screenshot(page, f"03_after_click_{profile_path.split('/')[-1][:20]}")

        await asyncio.sleep(10)
        dialog_opened = False
        try:
            await page.wait_for_selector('[role="dialog"]', timeout=10000)
            dialog_opened = True
            logger.info("  [Comments] dialog selector appeared in DOM")
        except Exception:
            logger.warning("  [Comments] wait_for_selector('[role=dialog]') timed out after 10s")

        if dialog_opened:
            await _screenshot(page, f"04_dialog_opened_{profile_path.split('/')[-1][:20]}")
        else:
            await _screenshot(page, f"04_dialog_timeout_{profile_path.split('/')[-1][:20]}")

        dialog_diag = await page.evaluate(DIALOG_DIAG_JS)
        logger.info(
            "  [Comments dialog] hasDialog=%s | dialogs=%s | articles=%s | writeInput=%s",
            dialog_diag.get("hasDialog"),
            dialog_diag.get("dialogCount"),
            dialog_diag.get("articles"),
            dialog_diag.get("writeInput"),
        )

        has_dialog = bool(dialog_diag.get("hasDialog"))
        if not has_dialog:
            logger.warning("  [Comments] Comment click did NOT open a recognizable comments dialog")
            return comments_data, post_url_from_dialog

        logger.info("  [Comments] Dialog confirmed - expanding all comments/replies...")
        await expand_all_comments_in_dialog(page, root_selector='[role="dialog"]')

        comments_data = await page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, limit)
        logger.info(f"  [Comments] Extracted {len(comments_data)} comments from dialog")

        post_url_from_dialog = await page.evaluate(POST_URL_FROM_DIALOG_JS)
        if post_url_from_dialog:
            logger.info(f"  [PostURL] Extracted from dialog: {post_url_from_dialog}")
        else:
            logger.info("  [PostURL] No /posts/ link found in dialog")

    except Exception as e:
        logger.warning(f"  Could not extract comments from dialog: {e}")
    finally:
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        except Exception:
            pass

    return comments_data, post_url_from_dialog
