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
        const key = authorUrl || authorName;
        if (seen.has(key)) continue;

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
        const key = authorUrl || authorName;
        if (seen.has(key)) continue;

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
        if (seen.has(link.href)) continue;

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
            seen.add(link.href);
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


async def extract_comments_from_post_on_search_page(
    page: Page,
    post_index: int,
    max_comments: int = 20,
) -> List[Dict]:
    """
    Scroll to post by index, click Comments, wait for dialog, extract comments, close with ESC.
    Fix: When hasDialog=True, comments ARE there - extract from dialog (don't fail on hasPanel).
    """
    comments_data: List[Dict] = []
    try:
        logger.info(f"  Extracting comments for post #{post_index} (max={max_comments})")

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
        await asyncio.sleep(random.uniform(1.5, 2.5))

        # Click "X comments" button - try feed children when articles=0
        clicked = await page.evaluate(
            """
            (idx) => {
                const feed = document.querySelector('div[role="feed"]');
                const articles = document.querySelectorAll('div[role="article"]');
                const containers = articles.length > 0 ? Array.from(articles) : (feed ? Array.from(feed.children) : []);
                const el = containers[idx];
                if (!el) return false;

                const buttons = el.querySelectorAll('div[role="button"]');
                for (const btn of buttons) {
                    const text = (btn.textContent || '').trim();
                    if (/\\d+\\s*comments?/i.test(text) && !/leave\\s*a\\s*comment/i.test(text)) {
                        btn.click();
                        return true;
                    }
                }
                const spans = el.querySelectorAll('span');
                for (const s of spans) {
                    const t = (s.textContent || '').trim();
                    if (/^\\d+\\s*comments?$/i.test(t) && s.offsetParent) {
                        s.click();
                        return true;
                    }
                }
                return false;
            }
            """,
            post_index,
        )

        if not clicked:
            logger.info("  Comment button not found for this post")
            return comments_data

        logger.info("  ✓ Comment button clicked, waiting for comments to appear...")

        await asyncio.sleep(random.uniform(2, 3))

        # Check for dialog OR panel - hasDialog=True means success!
        diag = await page.evaluate(
            """
            () => ({
                hasPanel: !!document.querySelector('[role="dialog"] [data-pagelet]'),
                hasDialog: !!document.querySelector('[role="dialog"]'),
                articleCount: document.querySelectorAll('div[role="article"]').length,
                bodySnippet: document.body ? document.body.innerText.slice(0, 400) : 'NO BODY'
            })
            """
        )

        # FIX: When hasDialog is True, the comments dialog opened - extract from it
        if diag.get("hasDialog"):
            logger.info("  ✓ Dialog opened, extracting comments...")
            try:
                view_more = await page.query_selector(
                    '[role="dialog"] div[role="button"]:has-text("View more comments"), '
                    '[role="dialog"] span:has-text("View more comments")'
                )
                if view_more:
                    await view_more.click()
                    await asyncio.sleep(random.uniform(1.5, 2.5))
            except Exception:
                pass

            comments_data = await page.evaluate(EXTRACT_FROM_DIALOG_JS, max_comments)
            logger.info(f"  ✓ Extracted {len(comments_data)} comments from dialog")
        else:
            logger.info("  ⚠ No dialog found after click - comments may not have loaded")
            logger.info(f"  Debug: {diag}")

    except Exception as e:
        logger.warning(f"  Error extracting comments: {e}")
    finally:
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        except Exception:
            pass

    return comments_data
