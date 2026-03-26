"""
Comment extraction for Facebook search results.
When Comments button opens a dialog (hasDialog=True), extract from the dialog.
"""
import asyncio
import random
from typing import List, Dict
from playwright.async_api import Page

from ..core.logging_config import get_logger

logger = get_logger(__name__)

# Same extraction JS as in facebook_scraper _click_comments_and_extract_from_dialog
# Filter: Exclude notification/activity content (Unread, Mark as read, listed for, shared, etc.)
# FIX: Use innerText instead of textContent to bypass Facebook font obfuscation (scrambled chars).
# FIX: Only process actual comments (aria-label="Comment by X"), skip post header.
# FIX: Reject obfuscated text (dashes between letters, "Shared with Public", etc.)
EXTRACT_FROM_DIALOG_JS = """
(maxComments) => {
    const comments = [];
    const seen = new Set();

    function getText(el) {
        if (!el) return '';
        return (el.innerText || el.textContent || '').trim();
    }

    function isProfileUrl(url) {
        if (!url || !url.includes('facebook.com')) return false;
        if (url.includes('/groups/') || url.includes('/pages/') || url.includes('/events/')) return false;
        return true;
    }

    function isNotificationOrActivity(text) {
        if (!text || text.length < 10) return true;
        const t = text.toLowerCase();
        if (/unread|mark as read|see all|see it now|we noticed a new login|please review/i.test(t)) return true;
        if (/listed for \\$|price dropped|\\d+ saved|shared.*post|posted a new reel|shared \\d+ posts/i.test(t)) return true;
        if (/marketplace|ecoboost|hatchback|sedan|coupe|xle/i.test(t) && /\\$|saved|listed/i.test(t)) return true;
        return false;
    }

    function isObfuscatedOrMetadata(text) {
        if (!text || text.length < 10) return true;
        if (/shared with public/i.test(text)) return true;
        if (/february|january|march|april|may|june|july|august|september|october|november|december/i.test(text) && /at \\d|\\d+:\\d+/.test(text)) return true;
        if ((text.match(/-/g) || []).length > 3 && text.length < 80) return true;
        if (/^[^a-zA-Z]*[a-zA-Z]-+[a-zA-Z]-+[a-zA-Z]/.test(text)) return true;
        return false;
    }

    const SKIP = /^(Like|Reply|Share|Comment|Facebook|Anonymous participant|\\d+[smhd]|Just now|Yesterday|See more|\\d+ min|\\d+ hr|\\d+ (w|d|m|y))/i;
    const TIMESTAMP_ONLY = /^\\d+[smhdw]?$/i;
    function looksLikeAuthorNameOnly(text) {
        if (!text || text.length > 100) return false;
        if (/[.!?]/.test(text)) return false;
        const words = text.trim().split(/\\s+/);
        if (words.length > 4) return false;
        if (words.length <= 2 && text.length < 30) return true;
        if (/^[A-Z][a-z']+(\\s+[A-Z][a-z']+){0,2}$/.test(text.trim())) return true;
        return false;
    }

    function commentKey(authorName, authorUrl, commentText, timestamp) {
        const who = (authorUrl || authorName || '').trim().toLowerCase();
        const body = (commentText || '').trim().toLowerCase();
        const ts = (timestamp || '').trim().toLowerCase();
        return `${who}|${body}|${ts}`;
    }

    const allDialogs = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
    let dialog = document.body;
    for (const d of allDialogs) {
        const text = (d.innerText || d.textContent || '').toLowerCase();
        const profileBlocks = d.querySelectorAll('[data-ad-rendering-role="profile_name"]');
        if (text.includes('comment') || text.includes('leave a comment') || profileBlocks.length > 2) {
            dialog = d;
            break;
        }
    }
    if (allDialogs.length > 0 && dialog === document.body) dialog = allDialogs[0];

    function isAuthorProfileLink(a) {
        if (!a || !a.href) return false;
        const h = a.href;
        if (h.includes('comment_id=') || (h.includes('/posts/') && h.includes('comment'))) return false;
        if (!isProfileUrl(h)) return false;
        const txt = getText(a);
        if (TIMESTAMP_ONLY.test(txt) || SKIP.test(txt)) return false;
        return true;
    }

    const commentArticles = dialog.querySelectorAll('div[role="article"][aria-label^="Comment by"]');
    for (const container of commentArticles) {
        if (comments.length >= maxComments) break;

        let authorName = '';
        let authorUrl = null;
        const allLinks = container.querySelectorAll('a[href*="facebook.com"]');
        for (const a of allLinks) {
            if (isAuthorProfileLink(a)) {
                authorName = getText(a);
                authorUrl = a.href;
                break;
            }
        }
        if (!authorName && !authorUrl) {
            const anonSpan = container.querySelector('span, div');
            const anonText = getText(anonSpan);
            if (/Anonymous participant/i.test(anonText)) {
                authorName = 'Anonymous participant';
            } else {
                const pn = container.querySelector('[data-ad-rendering-role="profile_name"]');
                authorName = pn ? getText(pn) : '';
            }
        }
        if (!authorName || authorName.length < 2) continue;
        if (TIMESTAMP_ONLY.test(authorName) || SKIP.test(authorName) || isObfuscatedOrMetadata(authorName)) continue;

        let commentText = '';
        const msgBody = container.querySelector('[data-ad-rendering-role="story_message"], [data-ad-comet-preview="message"], div.x1lliihq.xjkvuk6.x1iorvi4');
        if (msgBody) {
            const dirAuto = msgBody.querySelector('div[dir="auto"][style*="text-align"], div[dir="auto"], span[dir="auto"]');
            if (dirAuto) commentText = getText(dirAuto);
            if (!commentText) commentText = getText(msgBody);
        }
        if (!commentText) {
            const textDivs = container.querySelectorAll('div[dir="auto"][style*="text-align"], div[dir="auto"], span[dir="auto"]');
            for (const d of textDivs) {
                const t = getText(d);
                if (t && t.length > 10 && t !== authorName && !SKIP.test(t) && !isObfuscatedOrMetadata(t) && !looksLikeAuthorNameOnly(t)) {
                    commentText = t;
                    break;
                }
            }
        }
        if (!commentText) {
            const lines = getText(container).split('\\n').map(l => l.trim()).filter(l => l.length > 10 && l !== authorName && !SKIP.test(l) && !isObfuscatedOrMetadata(l) && !looksLikeAuthorNameOnly(l));
            if (lines.length) commentText = lines[0];
        }
        if (!commentText || looksLikeAuthorNameOnly(commentText)) continue;

        let timestamp = null;
        for (const s of container.querySelectorAll('span, abbr')) {
            const t = getText(s);
            if (/\\d+[smhd]|Just now|Yesterday|\\d+ min|\\d+ hr|\\d+ (w|d|m|y)/i.test(t)) {
                timestamp = t;
                break;
            }
        }

        if (authorName && commentText && commentText.length > 5 && !isNotificationOrActivity(commentText) && !isObfuscatedOrMetadata(commentText) && !looksLikeAuthorNameOnly(commentText)) {
            const key = commentKey(authorName, authorUrl, commentText, timestamp || 'Unknown');
            if (seen.has(key)) continue;
            seen.add(key);
            comments.push({
                author_name: authorName,
                author_profile_url: authorUrl,
                comment_text: commentText,
                comment_timestamp: timestamp || 'Unknown'
            });
        }
    }

    if (comments.length > 0) return comments;

    const profileNameBlocks = dialog.querySelectorAll('[data-ad-rendering-role="profile_name"]');
    for (const block of profileNameBlocks) {
        if (comments.length >= maxComments) break;
        const container = block.closest('div[role="article"]') || block.closest('li') || block.closest('.x78zum5') || block.parentElement?.parentElement?.parentElement;
        if (!container) continue;
        if (container.getAttribute('aria-label') && !container.getAttribute('aria-label').startsWith('Comment by')) continue;

        let authorName = '';
        let authorUrl = null;
        const authorLink = block.querySelector('a[href*="facebook.com"]');
        if (authorLink && isAuthorProfileLink(authorLink)) {
            authorName = getText(authorLink);
            authorUrl = authorLink.href;
        } else {
            const anon = container.querySelector('span, div');
            const anonText = getText(anon);
            if (/Anonymous participant/i.test(anonText)) {
                authorName = 'Anonymous participant';
            } else {
                authorName = getText(block);
            }
        }
        if (!authorName || authorName.length < 2) continue;
        if (TIMESTAMP_ONLY.test(authorName) || SKIP.test(authorName) || isObfuscatedOrMetadata(authorName)) continue;

        let commentText = '';
        const storyMsg = container.querySelector('[data-ad-rendering-role="story_message"], [data-ad-comet-preview="message"]');
        if (storyMsg) {
            const dirAuto = storyMsg.querySelector('div[dir="auto"][style*="text-align"], div[dir="auto"], span[dir="auto"]');
            if (dirAuto) commentText = getText(dirAuto);
            if (!commentText) commentText = getText(storyMsg);
        }
        if (!commentText) {
            const textDivs = container.querySelectorAll('div[dir="auto"][style*="text-align"], div[dir="auto"], span[dir="auto"]');
            for (const d of textDivs) {
                const t = getText(d);
                if (t && t.length > 10 && t !== authorName && !SKIP.test(t) && !isObfuscatedOrMetadata(t) && !looksLikeAuthorNameOnly(t)) {
                    commentText = t;
                    break;
                }
            }
        }
        if (!commentText) {
            const lines = getText(container).split('\\n').map(l => l.trim()).filter(l => l.length > 10 && l !== authorName && !SKIP.test(l) && !isObfuscatedOrMetadata(l) && !looksLikeAuthorNameOnly(l));
            if (lines.length) commentText = lines[0];
        }
        if (!commentText || looksLikeAuthorNameOnly(commentText)) continue;

        let timestamp = null;
        for (const s of container.querySelectorAll('span, abbr')) {
            const t = getText(s);
            if (/\\d+[smhd]|Just now|Yesterday|\\d+ min|\\d+ hr|\\d+ (w|d|m|y)/i.test(t)) { timestamp = t; break; }
        }

        if (authorName && commentText && commentText.length > 5 && !isNotificationOrActivity(commentText) && !isObfuscatedOrMetadata(commentText) && !looksLikeAuthorNameOnly(commentText)) {
            const key = commentKey(authorName, authorUrl, commentText, timestamp || 'Unknown');
            if (seen.has(key)) continue;
            seen.add(key);
            comments.push({
                author_name: authorName,
                author_profile_url: authorUrl,
                comment_text: commentText,
                comment_timestamp: timestamp || 'Unknown'
            });
        }
    }

    if (comments.length > 0) return comments;

    const links = dialog.querySelectorAll('a[href*="facebook.com"]');
    for (const link of links) {
        if (comments.length >= maxComments) break;
        const parent = link.closest('div[role="article"]');
        if (!parent || !parent.getAttribute('aria-label') || !parent.getAttribute('aria-label').startsWith('Comment by')) continue;

        if (!isAuthorProfileLink(link)) continue;
        const authorName = getText(link);
        if (!authorName || authorName.length < 2) continue;
        if (TIMESTAMP_ONLY.test(authorName) || SKIP.test(authorName) || isObfuscatedOrMetadata(authorName)) continue;

        let commentText = '';
        const textDivs = parent.querySelectorAll('div[dir="auto"][style*="text-align"], div[dir="auto"], span[dir="auto"]');
        for (const d of textDivs) {
            const t = getText(d);
            if (t && t.length > 10 && t !== authorName && !SKIP.test(t) && !isObfuscatedOrMetadata(t) && !looksLikeAuthorNameOnly(t)) {
                commentText = t;
                break;
            }
        }
        if (!commentText) {
            const lines = getText(parent).split('\\n').map(l => l.trim()).filter(l => l.length > 10 && l !== authorName && !SKIP.test(l) && !isObfuscatedOrMetadata(l) && !looksLikeAuthorNameOnly(l));
            if (lines.length) commentText = lines[0];
        }
        if (!commentText || looksLikeAuthorNameOnly(commentText)) continue;

        let timestamp = null;
        for (const s of parent.querySelectorAll('span, abbr')) {
            const t = getText(s);
            if (/\\d+[smhd]|Just now|Yesterday|\\d+ min|\\d+ hr/i.test(t)) { timestamp = t; break; }
        }

        if (authorName && commentText && commentText.length > 5 && !isNotificationOrActivity(commentText) && !isObfuscatedOrMetadata(commentText) && !looksLikeAuthorNameOnly(commentText)) {
            const key = commentKey(authorName, link.href, commentText, timestamp || 'Unknown');
            if (seen.has(key)) continue;
            seen.add(key);
            comments.push({
                author_name: authorName,
                author_profile_url: link.href,
                comment_text: commentText,
                comment_timestamp: timestamp || 'Unknown'
            });
        }
    }
    return comments;
}
"""


async def expand_all_comments_in_dialog(
    page: Page,
    root_selector: str = '[role="dialog"]',
    max_cycles: int = 160,
    stall_limit: int = 12,
) -> None:
    """
    Expand visible "more comments/replies" controls and wait for lazy loading.
    Stops after *stall_limit* consecutive cycles with no new comments and no expand clicks.
    """
    no_progress_cycles = 0
    best_count = 0

    for _ in range(max_cycles):
        state = await page.evaluate(
            """
            (rootSelector) => {
                function isCommentDialog(d) {
                    if (d.querySelector('[aria-label^="Write a comment"], [placeholder*="comment" i]')) return true;
                    if (d.querySelectorAll('div[role="article"][aria-label^="Comment by"]').length > 0) return true;
                    const t = (d.innerText || d.textContent || '').toLowerCase();
                    return t.includes('write a comment') || t.includes('leave a comment');
                }
                const root = Array.from(document.querySelectorAll('[role="dialog"]')).find(isCommentDialog)
                    || document.querySelector(rootSelector)
                    || document;
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

                const count = root.querySelectorAll('div[role="article"][aria-label^="Comment by"]').length;
                return { clicked, count };
            }
            """,
            root_selector,
        )

        clicked = int(state.get("clicked", 0))
        count = int(state.get("count", 0))
        if count > best_count:
            best_count = count
            no_progress_cycles = 0
        elif clicked == 0:
            no_progress_cycles += 1

        await page.evaluate(
            """
            (rootSelector) => {
                function isCommentDialog(d) {
                    if (d.querySelector('[aria-label^="Write a comment"], [placeholder*="comment" i]')) return true;
                    if (d.querySelectorAll('div[role="article"][aria-label^="Comment by"]').length > 0) return true;
                    const t = (d.innerText || d.textContent || '').toLowerCase();
                    return t.includes('write a comment') || t.includes('leave a comment');
                }
                const root = Array.from(document.querySelectorAll('[role="dialog"]')).find(isCommentDialog)
                    || document.querySelector(rootSelector);
                if (root) root.scrollTop = root.scrollHeight;
                else window.scrollBy(0, 900);
            }
            """,
            root_selector,
        )
        await asyncio.sleep(7)

        if no_progress_cycles >= stall_limit:
            break


async def extract_comments_from_post_on_search_page(
    page: Page,
    post_index: int,
    max_comments: int = 0,
):
    """
    Scroll to post by index, click Comments, wait for dialog, extract comments, close with ESC.
    Returns (comments: List[Dict], post_url: Optional[str]).
    post_url is the canonical /posts/ URL read from the dialog.
    Fix: When hasDialog=True, comments ARE there - extract from dialog (don't fail on hasPanel).
    """
    comments_data: List[Dict] = []
    post_url_from_dialog = None
    try:
        limit = max_comments if max_comments and max_comments > 0 else 5000
        logger.info(f"  Extracting comments for post #{post_index} (limit={limit if max_comments > 0 else 'ALL'})")

        # Scroll to post to make it visible
        logger.info(f"  Scrolling to post #{post_index} to make it visible...")
        await page.evaluate(
            """
            (idx) => {
                const feed = document.querySelector('div[role="feed"]');
                if (feed && feed.children[idx]) {
                    feed.children[idx].scrollIntoView({ behavior: 'smooth' });
                }
            }
            """,
            post_index,
        )
        await asyncio.sleep(8)

        # Click a comments trigger (count summary or action button) for this post.
        clicked = await page.evaluate(
            """
            (idx) => {
                const feed = document.querySelector('div[role="feed"]');
                const articles = document.querySelectorAll('div[role="article"]');
                const containers = articles.length > 0 ? Array.from(articles) : (feed ? Array.from(feed.children) : []);

                function isVisible(el) {
                    return !!(el && (el.offsetParent || (el.getClientRects && el.getClientRects().length)));
                }

                function clickEl(el) {
                    if (!el || !isVisible(el)) return false;
                    try {
                        el.click();
                        return true;
                    } catch (_) {
                        return false;
                    }
                }

                function clickCommentTrigger(card) {
                    if (!card) return {clicked: false, method: null, reason: 'no_card'};

                    const summaryNodes = card.querySelectorAll('div[role="button"], span[role="button"], a[role="button"], span, a');
                    for (const node of summaryNodes) {
                        const text = (node.innerText || node.textContent || '').trim();
                        if (!text || !isVisible(node)) continue;
                        if (/^\\d+[\\s,.]*comments?$/i.test(text)) {
                            if (clickEl(node)) return {clicked: true, method: 'count_text'};
                        }
                    }

                    const marker = card.querySelector('[data-ad-rendering-role="comment_button"]');
                    if (marker) {
                        const btn = marker.closest('[role="button"], [role="link"]');
                        if (clickEl(btn)) return {clicked: true, method: 'ad_rendering_role'};
                    }

                    const ariaButtons = card.querySelectorAll('div[role="button"][aria-label], span[role="button"][aria-label], a[role="button"][aria-label]');
                    for (const el of ariaButtons) {
                        const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                        if (!aria) continue;
                        if (/leave\\s*a\\s*comment|\\bcomment\\b/i.test(aria) && !/share|reaction|react/i.test(aria)) {
                            if (clickEl(el)) return {clicked: true, method: 'aria_label'};
                        }
                    }

                    const actionButtons = card.querySelectorAll('div[role="button"], span[role="button"], a[role="button"]');
                    for (const el of actionButtons) {
                        const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if ((text === 'comment' || text === 'comments') && clickEl(el)) return {clicked: true, method: 'action_button_text'};
                    }

                    return {clicked: false, method: null, reason: 'no_trigger_found'};
                }

                const el = containers[idx];
                if (!el) return {clicked: false, method: null, reason: 'no_container_at_idx', containersCount: containers.length, articlesCount: articles.length, hasFeed: !!feed};
                const result = clickCommentTrigger(el);
                result.containersCount = containers.length;
                result.articlesCount = articles.length;
                result.hasFeed = !!feed;
                return result;
            }
            """,
            post_index,
        )

        click_ok = bool(clicked.get("clicked")) if isinstance(clicked, dict) else bool(clicked)
        logger.info(
            "  [fix click] post_index=%d clicked=%s | method=%s | containers=%s articles=%s hasFeed=%s | reason=%s",
            post_index,
            click_ok,
            clicked.get("method") if isinstance(clicked, dict) else "n/a",
            clicked.get("containersCount") if isinstance(clicked, dict) else "n/a",
            clicked.get("articlesCount") if isinstance(clicked, dict) else "n/a",
            clicked.get("hasFeed") if isinstance(clicked, dict) else "n/a",
            clicked.get("reason", "") if isinstance(clicked, dict) else "",
        )
        if not click_ok:
            logger.info("  [fix] Comment button not found for post #%d", post_index)
            return comments_data

        logger.info("  [fix] Comment button clicked via method=%s, waiting for dialog...", clicked.get("method") if isinstance(clicked, dict) else "unknown")

        await asyncio.sleep(10)
        try:
            await page.wait_for_selector('[role="dialog"]', timeout=10000)
        except Exception:
            pass

        # Check for dialog OR panel - hasDialog=True means success!
        diag = await page.evaluate(
            """
            () => ({
                hasPanel: !!document.querySelector('[role="dialog"] [data-pagelet]'),
                hasDialog: (() => {
                    const dialog = document.querySelector('[role="dialog"]');
                    if (!dialog) return false;
                    const text = (dialog.innerText || dialog.textContent || '').toLowerCase();
                    return (
                        text.includes('comment') ||
                        !!dialog.querySelector('div[role="article"][aria-label^="Comment by"], [aria-label^="Write a comment"]')
                    );
                })(),
                articleCount: document.querySelectorAll('div[role="article"]').length,
                bodySnippet: document.body ? document.body.innerText.slice(0, 400) : 'NO BODY'
            })
            """
        )

        # FIX: When hasDialog is True, the comments dialog opened - extract from it
        if diag.get("hasDialog"):
            logger.info("  Dialog opened, expanding all comments/replies...")
            await expand_all_comments_in_dialog(page, root_selector='[role="dialog"]')
            comments_data = await page.evaluate(EXTRACT_FROM_DIALOG_JS, limit)
            logger.info(f"  Extracted {len(comments_data)} comments from dialog")

            # Extract the canonical post URL — every comment timestamp link contains it.
            post_url_from_dialog = await page.evaluate(
                """
                () => {
                    const a = document.querySelector(
                        'a[href*="/posts/pfbid"], a[href*="/posts/"], a[href*="/permalink.php"]'
                    );
                    return a ? a.getAttribute('href').split('?')[0] : null;
                }
                """
            )
            if post_url_from_dialog:
                logger.info(f"  [PostURL] Extracted from dialog: {post_url_from_dialog}")
        else:
            logger.info("  \u26a0  No dialog found after click - comments may not have loaded")
            logger.info(f"  Debug: {diag}")

    except Exception as e:
        logger.warning(f"  Error extracting comments: {e}")
    finally:
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        except Exception:
            pass

    return comments_data, post_url_from_dialog

