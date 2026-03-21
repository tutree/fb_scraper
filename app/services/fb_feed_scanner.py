"""
Scroll-and-process pipeline: extracts author profile links from the Facebook
search results feed and orchestrates per-profile scraping.
"""
import asyncio
import os
import random
import re as _re
from pathlib import Path
from typing import Callable, Dict, List, Optional

from playwright.async_api import Page
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.logging_config import get_logger
from .fb_account_loader import _cookie_uid_order
from .fb_comment_handler import click_comments_and_extract_from_dialog
from .fb_post_url import capture_post_url_via_share_button
from .fb_profile_processor import process_single_profile

logger = get_logger(__name__)

_SCREENSHOTS_DIR = Path(os.environ.get("LOGS_DIR", "logs")) / "screenshots"

# Tooltip text varies: full weekday line, short month, day-first, ISO, etc.
_TOOLTIP_DATE_RE = _re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,\s*"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"\d{1,2}\s*,\s*\d{4}(?:\s+at\s+\d{1,2}:\d{2}\s*(?:AM|PM))?",
    _re.IGNORECASE,
)
_TOOLTIP_DATE_SHORT_MONTH_RE = _re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|June|"
    r"July|August|September|October|November|December)\s+"
    r"\d{1,2}\s*,\s*\d{4}(?:\s+at\s+\d{1,2}:\d{2}\s*(?:AM|PM))?",
    _re.IGNORECASE,
)
_TOOLTIP_DATE_DAY_FIRST_RE = _re.compile(
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|"
    r"June|July|August|September|October|November|December)\s+\d{4}"
    r"(?:\s+at\s+\d{1,2}:\d{2}\s*(?:AM|PM))?",
    _re.IGNORECASE,
)
_TOOLTIP_DATE_ISO_RE = _re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _parse_tooltip_date(raw: Optional[str]) -> Optional[str]:
    """Best-effort parse of Facebook date tooltip body (format changes often)."""
    if not raw:
        return None
    text = " ".join(str(raw).split())
    for pat in (
        _TOOLTIP_DATE_RE,
        _TOOLTIP_DATE_SHORT_MONTH_RE,
        _TOOLTIP_DATE_DAY_FIRST_RE,
    ):
        m = pat.search(text)
        if m:
            return m.group(0).strip()
    m = _TOOLTIP_DATE_ISO_RE.search(text)
    if m:
        return m.group(0).strip()
    return None


# Injected into page.evaluate: return link indices for an article, highest-first (date link likely).
_JS_DATE_LINK_HOVER_ORDER = """
(article) => {
    const links = Array.from(article.querySelectorAll('a[href]'));
    function isPostUrl(href) {
        if (!href) return false;
        const h = String(href).toLowerCase();
        return (
            h.includes('/posts/') || h.includes('/permalink/') || h.includes('story_fbid') ||
            h.includes('/photo/') || h.includes('/share/') || h.includes('/watch') ||
            h.includes('/reel/') || h.includes('/videos/') || h.includes('story.php') ||
            h.includes('watch?v=')
        );
    }
    function score(i) {
        const a = links[i];
        const href = (a.href || '') + (a.getAttribute('href') || '');
        let s = 0;
        if (isPostUrl(href)) s += 100;
        if (a.querySelector('span[style*="display:flex"], span[style*="display: flex"]')) s += 80;
        if (a.hasAttribute('attributionsrc')) s += 40;
        const al = (a.getAttribute('aria-label') || '').toLowerCase();
        if (/min|hour|day|mar|jan|feb|apr|may|jun|jul|aug|sep|oct|nov|dec|ago|yesterday|today|\\d{4}/.test(al)) s += 50;
        const txt = (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim();
        if (txt.length > 0 && txt.length < 40 && /\\d|ago|yesterday|today|min|hour/i.test(txt)) s += 30;
        return s;
    }
    const indices = links.map((_, i) => i);
    indices.sort((a, b) => {
        const sa = score(a);
        const sb = score(b);
        if (sb !== sa) return sb - sa;
        return a - b;
    });
    return indices;
}
"""


async def enable_search_posts_seen_filter(page: Page) -> bool:
    """
    Turn ON the Facebook search posts filter switch labeled "Posts You've Seen"
    (role=switch checkbox).  When active, FB tends to hide or de-prioritize posts you
    already opened, which cuts down duplicate cards when scrolling the same keyword.

    If your locale inverts the switch (checked = show only seen), set
    FB_SEARCH_ENABLE_POSTS_SEEN_FILTER=false in .env.
    """
    switch = None
    try:
        by_role = page.get_by_role(
            "switch", name=_re.compile(r"posts you'?ve seen", _re.I)
        )
        if await by_role.count() > 0:
            switch = by_role.first
    except Exception:
        pass
    if switch is None:
        for sel in (
            'input[role="switch"][aria-label="Posts You\'ve Seen"]',
            'input[type="checkbox"][role="switch"][aria-label*="Posts You"][aria-label*="Seen"]',
        ):
            loc = page.locator(sel).first
            try:
                if await loc.count() > 0:
                    switch = loc
                    break
            except Exception:
                continue
    if switch is None:
        logger.info("Posts You've Seen filter control not in DOM — skipping")
        return False

    try:
        await switch.scroll_into_view_if_needed(timeout=10000)
        await asyncio.sleep(0.4)
        checked = (await switch.get_attribute("aria-checked") or "").strip().lower()
        if checked == "true":
            logger.info("Posts You've Seen filter already enabled (aria-checked=true)")
            return True
        await switch.click(timeout=10000, force=True)
        await asyncio.sleep(1.0)
        checked2 = (await switch.get_attribute("aria-checked") or "").strip().lower()
        if checked2 != "true":
            await switch.click(timeout=10000, force=True)
            await asyncio.sleep(0.8)
            checked2 = (await switch.get_attribute("aria-checked") or "").strip().lower()
        logger.info(
            "Posts You've Seen filter toggled (aria-checked was %r -> %r)",
            checked,
            checked2,
        )
        return True
    except Exception as exc:
        logger.warning("Could not toggle Posts You've Seen filter: %s", exc)
        return False


async def _screenshot(page, label: str) -> None:
    """Save a PNG to logs/screenshots/<label>_HHMMSS.png, silently skip on error."""
    import datetime
    try:
        _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%H%M%S")
        path = _SCREENSHOTS_DIR / f"{label}_{ts}.png"
        await page.screenshot(path=str(path), full_page=False)
        logger.info("[Screenshot] %s", path)
    except Exception as exc:
        logger.warning("[Screenshot] failed (%s): %s", label, exc)



def _is_user_profile_url(url: str) -> bool:
    clean = url.split("?")[0].split("&")[0]
    if "/groups/" in clean:
        return False
    if "profile.php" in url:
        return True
    non_profile = {"pages", "events", "marketplace", "watch", "gaming", "ads"}
    match = _re.search(r"facebook\.com/([^/?#]+)", clean)
    if match and match.group(1).lower() in non_profile:
        return False
    return True


def _link_key(link: Dict) -> str:
    base = str(link.get("post_url") or link.get("url") or "")
    content = str(link.get("post_content") or "")[:80]
    return f"{base}|{content}"


async def _extract_dates_via_tooltip_hover(
    page: Page,
    article_count: int,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Dict[int, str]:
    """
    For each article, hover every <a> tag inside it and check whether a
    date tooltip appears.  No DOM guessing — just brute-force hover and check.
    Returns dict: article_index -> date string.
    """
    date_by_index: Dict[int, str] = {}
    articles_loc = page.locator("div[role='main'] div[role='article']")
    try:
        n = await articles_loc.count()
    except Exception:
        n = 0
    if n == 0:
        return date_by_index

    end = min(article_count, n)
    extracted = 0

    for i in range(end):
        if should_stop and should_stop():
            break
        try:
            article = articles_loc.nth(i)
            links = article.locator("a[href]")
            link_count = await links.count()

            hover_order: List[int] = list(range(link_count))
            try:
                order_js = await article.evaluate(_JS_DATE_LINK_HOVER_ORDER)
                if (
                    isinstance(order_js, list)
                    and len(order_js) == link_count
                    and set(order_js) == set(range(link_count))
                ):
                    hover_order = [int(x) for x in order_js]
            except Exception:
                pass

            found_date = False
            for j in hover_order:
                if found_date:
                    break
                link = links.nth(j)

                try:
                    if not await link.is_visible(timeout=500):
                        continue
                except Exception:
                    continue

                try:
                    await link.scroll_into_view_if_needed(timeout=1500)
                except Exception:
                    pass

                try:
                    await link.hover(timeout=2000)
                except Exception:
                    continue
                await asyncio.sleep(0.45)

                tooltip = page.locator('[role="tooltip"]')
                try:
                    await tooltip.first.wait_for(state="visible", timeout=1500)
                except Exception:
                    await page.mouse.move(0, 0)
                    await asyncio.sleep(0.08)
                    continue

                raw = await tooltip.first.text_content()
                await page.mouse.move(0, 0)
                await asyncio.sleep(0.1)

                if raw:
                    parsed = _parse_tooltip_date(raw)
                    if parsed:
                        date_by_index[i] = parsed
                        extracted += 1
                        found_date = True

        except Exception as e:
            logger.debug("Tooltip date extraction for article %s: %s", i, e)
        try:
            await page.mouse.move(0, 0)
        except Exception:
            pass

    logger.info(
        "Tooltip date hover: %d/%d articles got dates", extracted, end,
    )
    return date_by_index


async def scroll_and_process_posts(
    page: Page,
    keyword: str,
    max_results: int,
    browser_manager,
    current_account: Dict,
    db: Session,
    sleep_with_stop: Callable,
    should_stop: Optional[Callable[[], bool]] = None,
) -> int:
    """
    Scroll the search results feed, extract author profile links,
    then for each link: scrape comments → visit profile → save to DB.
    Returns the number of personal profiles saved.
    """
    logger.info(f"Starting extraction for keyword: '{keyword}' (target: {max_results} posts)")

    # Initial warmup: more scrolls so first extraction sees more posts (needed for 100+ per keyword)
    warmup_scrolls = min(15, max(8, max_results // 8))
    logger.info("Preloading search feed with %d progressive scrolls...", warmup_scrolls)
    for i in range(warmup_scrolls):
        if should_stop and should_stop():
            logger.warning("Stop requested before scroll warmup completed.")
            return 0
        await page.evaluate("window.scrollBy(0, 1800)")
        if await sleep_with_stop(8, should_stop=should_stop):
            logger.warning("Stop requested during scroll warmup delay.")
            return 0

    # await _screenshot(page, f"01_results_loaded_{keyword[:30].replace(' ', '_')}")

    current_url = page.url
    logger.info(f"Current page URL: {current_url}")
    page_diag = await page.evaluate(
        """
        () => ({
            title: document.title,
            articles: document.querySelectorAll('div[role="article"]').length,
            feed: !!document.querySelector('div[role="feed"]'),
            totalAnchors: document.querySelectorAll('a[href]').length,
            bodySnippet: document.body ? document.body.innerText.slice(0, 300) : 'NO BODY',
        })
        """
    )
    logger.info(
        f"Page diagnostics: title={page_diag.get('title')!r}, "
        f"articles={page_diag.get('articles')}, feed={page_diag.get('feed')}, "
        f"anchors={page_diag.get('totalAnchors')}"
    )
    logger.info(f"Page body snippet: {page_diag.get('bodySnippet')!r}")

    exclude_uids = set()
    account_uid = current_account.get("uid", "")
    if account_uid:
        exclude_uids.add(account_uid)
    env_uid = str(settings.FACEBOOK_EMAIL or "").strip()
    if env_uid:
        exclude_uids.add(env_uid)
    for uid in _cookie_uid_order():
        exclude_uids.add(uid)
    exclude_uids.discard("")
    exclude_uids_list = list(exclude_uids)
    logger.info(f"Account UIDs to exclude from results: {exclude_uids_list}")

    logger.info("Extracting author profile links via semantic DOM traversal...")
    all_links = await page.evaluate(
        """
        (excludeUids) => {
            const results = [];
            const seen = new Set();
            const BASE = location.origin;

            const NON_PROFILE = new Set([
                'pages', 'groups', 'events', 'marketplace', 'watch', 'gaming',
                'ads', 'search', 'stories', 'notifications', 'messages',
                'friends', 'bookmarks', 'memory', 'help', 'privacy', 'terms',
                'hashtag', 'reel', 'reels', 'live', 'photo', 'photos', 'video',
                'videos', 'login', 'recover', 'checkpoint', 'settings', 'composer',
                'sharer', 'dialog', 'share', 'l.php', 'ajax', 'api'
            ]);

            function isProfileHref(absoluteHref) {
                if (!absoluteHref || !absoluteHref.includes('facebook.com')) return false;
                for (const uid of excludeUids) {
                    if (uid && absoluteHref.includes(uid)) return false;
                }
                try {
                    const u = new URL(absoluteHref);
                    const parts = u.pathname.replace(/^\\//, '').replace(/\\/$/, '').split('/');
                    const slug = parts[0];
                    if (!slug) return false;
                    if (NON_PROFILE.has(slug.toLowerCase())) return false;
                    if (/^(groups|events|pages|hashtag|watch|gaming|marketplace|reel|reels|stories|live|photo|photos|video|videos|posts|permalink|story\\.php|share|sharer|composer|checkpoint|login|ajax)/.test(slug)) return false;
                    if (u.search.includes('comment_id=')) return false;
                    if (slug === 'profile.php') return true;
                    return /^[A-Za-z0-9._-]{2,}$/.test(slug) && parts.length === 1;
                } catch(e) { return false; }
            }

            function extractPostContent(article) {
                const contentSelectors = [
                    'div[data-ad-rendering-role="story_message"]',
                    'div[data-ad-comet-preview="message"]',
                    'div[dir="auto"][style*="text-align"]',
                    'span[dir="auto"]'
                ];
                for (const selector of contentSelectors) {
                    const elem = article.querySelector(selector);
                    if (elem && elem.textContent.trim().length > 20) {
                        return elem.textContent.trim();
                    }
                }
                const dirAutoAll = article.querySelectorAll('[dir="auto"]');
                const fragments = [];
                const seen = new Set();
                for (const el of dirAutoAll) {
                    const t = el.textContent.trim();
                    if (t.length > 15 && !seen.has(t) && !/^(Facebook|Like|Comment|Share|Send|Follow|Suggested for you|Sponsored)$/i.test(t)) {
                        seen.add(t);
                        fragments.push(t);
                    }
                }
                if (fragments.length > 0) {
                    const joined = fragments.join(' ');
                    return joined.length > 500 ? joined.substring(0, 500) + '...' : joined;
                }
                return null;
            }

            function isPostUrl(href) {
                if (!href) return false;
                const h = String(href).toLowerCase();
                return (
                    h.includes('/posts/') ||
                    h.includes('/permalink/') ||
                    h.includes('story_fbid') ||
                    h.includes('/photo/') ||
                    h.includes('/share/') ||
                    h.includes('/watch') ||
                    h.includes('/reel/') ||
                    h.includes('/videos/') ||
                    h.includes('story.php') ||
                    h.includes('watch?v=')
                );
            }

            function normalizeText(value) {
                return (value || '').replace(/\\s+/g, ' ').trim();
            }

            const MONTH_RE = '(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)';
            const MONTH_DAY_RE = new RegExp('\\\\b' + MONTH_RE + '\\\\b[\\\\s,]*\\\\d', 'i');
            const DAY_MONTH_RE = new RegExp('\\\\d[\\\\s,]*\\\\b' + MONTH_RE + '\\\\b', 'i');
            function isLikelyPostDate(value) {
                const text = normalizeText(value);
                if (!text || text.length > 80) return false;
                if (/^(?:\\d+\\s*(?:s|m|min|h|hr|d|w|mo|y)|just now|yesterday|today)$/i.test(text)) return true;
                if (MONTH_DAY_RE.test(text)) return true;
                if (DAY_MONTH_RE.test(text)) return true;
                if (/\\b(?:today|yesterday)\\b/i.test(text)) return true;
                if (/\\b\\d{1,2}:\\d{2}\\b/.test(text)) return true;
                if (/\\b\\d+\\s*(?:mins?|minutes?|hrs?|hours?|days?|weeks?|months?|years?)\\s*(?:ago)?\\b/i.test(text)) return true;
                if (/^\\d{1,2}\\/\\d{1,2}\\/\\d{2,4}$/.test(text)) return true;
                if (/^\\w+ \\d{1,2}(?:,? \\d{4})?(?:\\s+at\\s+\\d{1,2}:\\d{2}\\s*(?:AM|PM)?)?$/i.test(text)) return true;
                return false;
            }

            function readVisibleCharsFromObfuscatedSpans(container) {
                const wrapper = container.querySelector('span[style*="display: flex"], span[style*="display:flex"]');
                const parent = wrapper || container;
                const charSpans = parent.querySelectorAll(':scope > span');
                if (charSpans.length < 3) return null;
                let text = '';
                for (const span of charSpans) {
                    if (span.children.length > 0) continue;
                    const ch = span.textContent;
                    if (!ch) continue;
                    const rect = span.getBoundingClientRect();
                    if (rect.width === 0 && rect.height === 0) continue;
                    const cs = getComputedStyle(span);
                    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                    if (parseFloat(cs.opacity) === 0) continue;
                    if (cs.position === 'absolute' && cs.clip && cs.clip !== 'auto') continue;
                    if (parseFloat(cs.fontSize) === 0) continue;
                    if (cs.color === cs.backgroundColor && cs.color !== '') continue;
                    text += ch;
                }
                return text.replace(/\\s+/g, ' ').trim() || null;
            }

            function readFromAriaLabelledBy(node) {
                if (!node || !node.getAttribute) return null;
                const labelledBy = node.getAttribute('aria-labelledby');
                if (!labelledBy) return null;
                for (const id of labelledBy.split(' ').filter(Boolean)) {
                    const target = document.getElementById(id);
                    if (!target) continue;
                    const text = normalizeText(target.innerText || target.textContent || '');
                    if (text && text.length > 0) return text;
                }
                return null;
            }

            function extractDateFromElement(el) {
                if (!el) return null;
                const ariaLabel = normalizeText(el.getAttribute('aria-label') || '');
                if (isLikelyPostDate(ariaLabel)) return ariaLabel;

                for (const child of el.querySelectorAll('[aria-labelledby]')) {
                    const labelText = readFromAriaLabelledBy(child);
                    if (labelText && isLikelyPostDate(labelText)) return labelText;
                }

                const obfuscatedContainers = el.querySelectorAll('span[aria-labelledby]');
                for (const oc of obfuscatedContainers) {
                    const ariaText = readFromAriaLabelledBy(oc);
                    if (ariaText && isLikelyPostDate(ariaText)) return ariaText;
                    const visible = readVisibleCharsFromObfuscatedSpans(oc);
                    if (visible && isLikelyPostDate(visible)) return visible;
                }

                const flexSpans = el.querySelectorAll('span[style*="display: flex"], span[style*="display:flex"]');
                for (const fs of flexSpans) {
                    const container = fs.parentElement || fs;
                    const visible = readVisibleCharsFromObfuscatedSpans(container);
                    if (visible && isLikelyPostDate(visible)) return visible;
                }

                const timeEl = el.querySelector('time[datetime]');
                if (timeEl) {
                    const dt = normalizeText(timeEl.getAttribute('datetime') || '');
                    if (dt) return dt;
                }
                const abbrEl = el.querySelector('abbr[title], abbr[data-utime]');
                if (abbrEl) {
                    const title = normalizeText(abbrEl.getAttribute('title') || '');
                    if (title) return title;
                }
                const visibleText = normalizeText(el.innerText || el.textContent || '');
                if (isLikelyPostDate(visibleText)) return visibleText;
                return null;
            }

            function isDateAnchor(href, rawHref) {
                if (!href && !rawHref) return false;
                if (isPostUrl(href) || isPostUrl(rawHref)) return true;
                if ((rawHref || '').includes('#?') || (href || '').includes('#?')) return true;
                return false;
            }

            function extractPostDate(article, postUrl) {
                const candidates = [];
                for (const link of article.querySelectorAll('a[href]')) {
                    const href = link.href || '';
                    const rawHref = link.getAttribute('href') || '';
                    if (!href && !rawHref) continue;
                    if (postUrl && href === postUrl) { candidates.push(link); continue; }
                    if (isDateAnchor(href, rawHref) && !isProfileHref(href)) candidates.push(link);
                }

                for (const anchor of candidates) {
                    const value = extractDateFromElement(anchor);
                    if (value) return value;
                }

                const headerDiv = article.querySelector('div[data-ad-rendering-role="profile_name"]');
                if (headerDiv) {
                    let ancestor = headerDiv;
                    for (let i = 0; i < 8 && ancestor && ancestor !== article; i++) {
                        ancestor = ancestor.parentElement;
                        if (!ancestor) break;
                        for (const child of ancestor.children) {
                            for (const a of child.querySelectorAll('a[href]')) {
                                const rawH = a.getAttribute('href') || '';
                                if (isDateAnchor(a.href || '', rawH) && !isProfileHref(a.href || '')) {
                                    const val = extractDateFromElement(a);
                                    if (val) return val;
                                }
                            }
                        }
                    }
                }

                const allObfuscated = article.querySelectorAll('span[aria-labelledby]');
                for (const oc of allObfuscated) {
                    const closestLink = oc.closest('a[href]');
                    if (closestLink && isProfileHref(closestLink.href || '')) continue;
                    const ariaText = readFromAriaLabelledBy(oc);
                    if (ariaText && isLikelyPostDate(ariaText)) return ariaText;
                    const visible = readVisibleCharsFromObfuscatedSpans(oc);
                    if (visible && isLikelyPostDate(visible)) return visible;
                }

                const allFlexSpans = article.querySelectorAll('span[style*="display: flex"], span[style*="display:flex"]');
                for (const fs of allFlexSpans) {
                    const closestLink = fs.closest('a[href]');
                    if (closestLink && isProfileHref(closestLink.href || '')) continue;
                    const container = fs.parentElement || fs;
                    const visible = readVisibleCharsFromObfuscatedSpans(container);
                    if (visible && isLikelyPostDate(visible)) return visible;
                }

                const fallbackTime = article.querySelector('time[datetime]');
                if (fallbackTime) {
                    const dt = normalizeText(fallbackTime.getAttribute('datetime') || '');
                    if (dt) return dt;
                }
                const fallbackAbbr = article.querySelector('abbr[title], abbr[data-utime]');
                if (fallbackAbbr) {
                    const title = normalizeText(fallbackAbbr.getAttribute('title') || '');
                    if (title) return title;
                }

                for (const a of article.querySelectorAll('a[href]')) {
                    if (isProfileHref(a.href || '')) continue;
                    const linkText = normalizeText(a.innerText || a.textContent || '');
                    if (linkText && linkText.length < 40 && isLikelyPostDate(linkText)) return linkText;
                    const ariaL = normalizeText(a.getAttribute('aria-label') || '');
                    if (ariaL && ariaL.length < 40 && isLikelyPostDate(ariaL)) return ariaL;
                }

                for (const span of article.querySelectorAll('span')) {
                    if (span.children.length > 3) continue;
                    const st = normalizeText(span.innerText || span.textContent || '');
                    if (st && st.length > 2 && st.length < 30 && isLikelyPostDate(st)) return st;
                }
                return null;
            }

            function addLink(absoluteHref, text, postContent, postUrl, postDate, visibleIndex = null) {
                try {
                    const u = new URL(absoluteHref);
                    const key = `${postUrl || u.pathname.replace(/\\/$/, '')}|${(postContent || '').slice(0, 80)}`;
                    if (seen.has(key)) return;
                    seen.add(key);
                    results.push({
                        url: absoluteHref,
                        text: (text || '').trim(),
                        type: 'direct',
                        post_content: postContent || null,
                        post_url: postUrl || null,
                        post_date: postDate || null,
                        visible_index: visibleIndex,
                    });
                } catch(e) {}
            }

            function extractPostUrl(article) {
                const selectors = [
                    'a[href*="/posts/"]', 'a[href*="/permalink/"]',
                    'a[href*="story_fbid"]', 'a[href*="/photo/"]',
                    'a[href*="/watch"]', 'a[href*="/reel/"]', 'a[href*="/videos/"]',
                    'a[href*="watch?v="]',
                    'a[role="link"][href*="facebook.com"]', 'span[id] a[href]'
                ];
                for (const selector of selectors) {
                    for (const link of article.querySelectorAll(selector)) {
                        const href = link.href;
                        if (href && !isProfileHref(href) && isPostUrl(href)) return href;
                    }
                }
                return null;
            }

            const mainContent = document.querySelector('div[role="main"]') || document.body;

            // Strategy 1: role="article" elements
            const articles = mainContent.querySelectorAll('div[role="article"]');
            articles.forEach((article, idx) => {
                const postContent = extractPostContent(article);
                const postUrl = extractPostUrl(article);
                const postDate = extractPostDate(article, postUrl);
                for (const a of article.querySelectorAll('a[href]')) {
                    if (isProfileHref(a.href)) {
                        addLink(a.href, a.textContent, postContent, postUrl, postDate, idx);
                        break;
                    }
                }
            });

            // Strategy 2: feed direct children
            if (results.length === 0) {
                const feed = mainContent.querySelector('div[role="feed"]');
                if (feed) {
                    Array.from(feed.children).forEach((child, idx) => {
                        const postContent = extractPostContent(child);
                        const postUrl = extractPostUrl(child);
                        const postDate = extractPostDate(child, postUrl);
                        for (const a of child.querySelectorAll('a[href]')) {
                            if (isProfileHref(a.href)) {
                                addLink(a.href, a.textContent, postContent, postUrl, postDate, idx);
                                break;
                            }
                        }
                    });
                }
            }

            // Strategy 3: full main-content scan
            if (results.length === 0) {
                mainContent.querySelectorAll('a[href]').forEach(a => {
                    if (isProfileHref(a.href)) {
                        const parent = a.closest('div[role="article"]');
                        const postContent = parent ? extractPostContent(parent) : null;
                        const postUrl = parent ? extractPostUrl(parent) : null;
                        const postDate = parent ? extractPostDate(parent, postUrl) : null;
                        addLink(a.href, a.textContent, postContent, postUrl, postDate, null);
                    }
                });
            }

            return results;
        }
        """,
        exclude_uids_list,
    )

    # Hover obfuscated date elements to read tooltip and fill post_date
    try:
        article_count = await page.locator("div[role='main'] div[role='article']").count()
        if article_count > 0:
            date_by_index = await _extract_dates_via_tooltip_hover(
                page, article_count, should_stop=should_stop
            )
            for link in all_links:
                idx = link.get("visible_index")
                if idx is not None and idx in date_by_index:
                    link["post_date"] = date_by_index[idx]
    except Exception as e:
        logger.debug("Tooltip date extraction (initial): %s", e)

    logger.info(f"Total extracted: {len(all_links)} profile links")
    for link in all_links:
        logger.info(
            "  Extracted link: url=%s post_date=%r",
            link.get("url", "")[:60],
            link.get("post_date"),
        )

    user_links = [l for l in all_links if _is_user_profile_url(l["url"])]
    logger.info(
        f"After pre-filtering: {len(user_links)} candidate user links "
        f"(dropped {len(all_links) - len(user_links)})"
    )

    seen_link_keys = {_link_key(link) for link in user_links}

    max_scan_rounds = min(25, max(10, (max_results // 4) + 5))
    no_growth_threshold = 3
    if len(user_links) < max_results:
        logger.info(
            "Initial extraction below target (%d/%d). Continuing progressive scan (max %d rounds, stop after %d no-growth)...",
            len(user_links),
            max_results,
            max_scan_rounds,
            no_growth_threshold,
        )
        no_growth_rounds = 0
        for scan_round in range(1, max_scan_rounds + 1):
            if should_stop and should_stop():
                break

            await page.evaluate("window.scrollBy(0, 2500)")
            if await sleep_with_stop(8, should_stop=should_stop):
                break

            extra_links = await page.evaluate(
                """
                (excludeUids) => {
                    const out = [];
                    const seen = new Set();
                    const feed = document.querySelector('div[role="feed"]');
                    if (!feed) return out;

                    function isProfileHref(href) {
                        if (!href || !href.includes('facebook.com')) return false;
                        for (const uid of excludeUids) {
                            if (uid && href.includes(uid)) return false;
                        }
                        if (href.includes('/groups/') || href.includes('/events/') || href.includes('/pages/')) return false;
                        if (href.includes('/search/') || href.includes('/hashtag/')) return false;
                        return href.includes('profile.php') || /facebook\\.com\\/[A-Za-z0-9._-]{2,}(?:\\?|$)/.test(href);
                    }

                    function cardText(el) {
                        const selectors = [
                            'div[data-ad-rendering-role="story_message"]',
                            'div[data-ad-comet-preview="message"]',
                            'div[dir="auto"][style*="text-align"]',
                            'span[dir="auto"]'
                        ];
                        for (const sel of selectors) {
                            const found = el.querySelector(sel);
                            if (found && found.textContent.trim().length > 20) {
                                return found.textContent.trim();
                            }
                        }
                        const dirAutoAll = el.querySelectorAll('[dir="auto"]');
                        const fragments = [];
                        const seen = new Set();
                        for (const node of dirAutoAll) {
                            const t = node.textContent.trim();
                            if (t.length > 15 && !seen.has(t) && !/^(Facebook|Like|Comment|Share|Send|Follow|Suggested for you|Sponsored)$/i.test(t)) {
                                seen.add(t);
                                fragments.push(t);
                            }
                        }
                        if (fragments.length > 0) {
                            const joined = fragments.join(' ');
                            return joined.length > 500 ? joined.slice(0, 500) + '...' : joined;
                        }
                        return null;
                    }

                    function normalizeText(value) {
                        return (value || '').replace(/\\s+/g, ' ').trim();
                    }

                    const MONTH_RE2 = '(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)';
                    const MONTH_DAY_RE2 = new RegExp('\\\\b' + MONTH_RE2 + '\\\\b[\\\\s,]*\\\\d', 'i');
                    const DAY_MONTH_RE2 = new RegExp('\\\\d[\\\\s,]*\\\\b' + MONTH_RE2 + '\\\\b', 'i');
                    function isLikelyPostDate(value) {
                        const text = normalizeText(value);
                        if (!text || text.length > 80) return false;
                        if (/^(?:\\d+\\s*(?:s|m|min|h|hr|d|w|mo|y)|just now|yesterday|today)$/i.test(text)) return true;
                        if (MONTH_DAY_RE2.test(text)) return true;
                        if (DAY_MONTH_RE2.test(text)) return true;
                        if (/\\b(?:today|yesterday)\\b/i.test(text)) return true;
                        if (/\\b\\d{1,2}:\\d{2}\\b/.test(text)) return true;
                        if (/\\b\\d+\\s*(?:mins?|minutes?|hrs?|hours?|days?|weeks?|months?|years?)\\s*(?:ago)?\\b/i.test(text)) return true;
                        if (/^\\d{1,2}\\/\\d{1,2}\\/\\d{2,4}$/.test(text)) return true;
                        if (/^\\w+ \\d{1,2}(?:,? \\d{4})?(?:\\s+at\\s+\\d{1,2}:\\d{2}\\s*(?:AM|PM)?)?$/i.test(text)) return true;
                        return false;
                    }

                    function readVisibleCharsFromObfuscatedSpans(container) {
                        const wrapper = container.querySelector('span[style*="display: flex"], span[style*="display:flex"]');
                        const parent = wrapper || container;
                        const charSpans = parent.querySelectorAll(':scope > span');
                        if (charSpans.length < 3) return null;
                        let text = '';
                        for (const span of charSpans) {
                            if (span.children.length > 0) continue;
                            const ch = span.textContent;
                            if (!ch) continue;
                            const rect = span.getBoundingClientRect();
                            if (rect.width === 0 && rect.height === 0) continue;
                            const cs = getComputedStyle(span);
                            if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                            if (parseFloat(cs.opacity) === 0) continue;
                            if (cs.position === 'absolute' && cs.clip && cs.clip !== 'auto') continue;
                            if (parseFloat(cs.fontSize) === 0) continue;
                            if (cs.color === cs.backgroundColor && cs.color !== '') continue;
                            text += ch;
                        }
                        return text.replace(/\\s+/g, ' ').trim() || null;
                    }

                    function readFromAriaLabelledBy(node) {
                        if (!node || !node.getAttribute) return null;
                        const labelledBy = node.getAttribute('aria-labelledby');
                        if (!labelledBy) return null;
                        for (const id of labelledBy.split(' ').filter(Boolean)) {
                            const target = document.getElementById(id);
                            if (!target) continue;
                            const text = normalizeText(target.innerText || target.textContent || '');
                            if (text && text.length > 0) return text;
                        }
                        return null;
                    }

                    function extractDateFromElement(el) {
                        if (!el || typeof el.getAttribute !== 'function') return null;
                        const ariaLabel = normalizeText(el.getAttribute('aria-label') || '');
                        if (isLikelyPostDate(ariaLabel)) return ariaLabel;

                        for (const child of el.querySelectorAll('[aria-labelledby]')) {
                            const labelText = readFromAriaLabelledBy(child);
                            if (labelText && isLikelyPostDate(labelText)) return labelText;
                        }

                        const obfuscatedContainers = el.querySelectorAll('span[aria-labelledby]');
                        for (const oc of obfuscatedContainers) {
                            const ariaText = readFromAriaLabelledBy(oc);
                            if (ariaText && isLikelyPostDate(ariaText)) return ariaText;
                            const visible = readVisibleCharsFromObfuscatedSpans(oc);
                            if (visible && isLikelyPostDate(visible)) return visible;
                        }

                        const flexSpans = el.querySelectorAll('span[style*="display: flex"], span[style*="display:flex"]');
                        for (const fs of flexSpans) {
                            const container = fs.parentElement || fs;
                            const visible = readVisibleCharsFromObfuscatedSpans(container);
                            if (visible && isLikelyPostDate(visible)) return visible;
                        }

                        const timeEl = el.querySelector('time[datetime]');
                        if (timeEl) {
                            const dt = normalizeText(timeEl.getAttribute('datetime') || '');
                            if (dt) return dt;
                        }
                        const abbrEl = el.querySelector('abbr[title], abbr[data-utime]');
                        if (abbrEl) {
                            const title = normalizeText(abbrEl.getAttribute('title') || '');
                            if (title) return title;
                        }
                        const visibleText = normalizeText(el.innerText || el.textContent || '');
                        if (isLikelyPostDate(visibleText)) return visibleText;
                        return null;
                    }

                    function isPostUrl2(href) {
                        if (!href) return false;
                        const h = String(href).toLowerCase();
                        return (
                            h.includes('/posts/') ||
                            h.includes('/permalink/') ||
                            h.includes('story_fbid') ||
                            h.includes('/photo/') ||
                            h.includes('/share/') ||
                            h.includes('/watch') ||
                            h.includes('/reel/') ||
                            h.includes('/videos/') ||
                            h.includes('story.php') ||
                            h.includes('watch?v=')
                        );
                    }

                    function isDateAnchor2(href, rawHref) {
                        if (!href && !rawHref) return false;
                        if (isPostUrl2(href) || isPostUrl2(rawHref)) return true;
                        if ((rawHref || '').includes('#?') || (href || '').includes('#?')) return true;
                        return false;
                    }

                    function isProfileHref2(absoluteHref) {
                        if (!absoluteHref || !absoluteHref.includes('facebook.com')) return false;
                        try {
                            const u = new URL(absoluteHref, location.origin);
                            const parts = u.pathname.replace(/^\\//, '').replace(/\\/$/, '').split('/');
                            const slug = parts[0];
                            if (!slug) return false;
                            if (slug === 'profile.php') return true;
                            return /^[A-Za-z0-9._-]{2,}$/.test(slug) && parts.length === 1;
                        } catch(e) { return false; }
                    }

                    function extractPostDate(card, postLinkEl) {
                        const candidateAnchors = [];
                        if (postLinkEl) candidateAnchors.push(postLinkEl);
                        for (const a of card.querySelectorAll('a[href]')) {
                            if (postLinkEl && a === postLinkEl) continue;
                            const href = a.href || '';
                            const rawHref = a.getAttribute('href') || '';
                            if (!href && !rawHref) continue;
                            if (isDateAnchor2(href, rawHref) && !isProfileHref2(href)) {
                                candidateAnchors.push(a);
                            }
                        }

                        for (const anchor of candidateAnchors) {
                            const value = extractDateFromElement(anchor);
                            if (value) return value;
                        }

                        const headerDiv = card.querySelector('div[data-ad-rendering-role="profile_name"]');
                        if (headerDiv) {
                            let ancestor = headerDiv;
                            for (let i = 0; i < 8 && ancestor && ancestor !== card; i++) {
                                ancestor = ancestor.parentElement;
                                if (!ancestor) break;
                                for (const child of ancestor.children) {
                                    for (const a of child.querySelectorAll('a[href]')) {
                                        const rawH = a.getAttribute('href') || '';
                                        if (isDateAnchor2(a.href || '', rawH) && !isProfileHref2(a.href || '')) {
                                            const val = extractDateFromElement(a);
                                            if (val) return val;
                                        }
                                    }
                                }
                            }
                        }

                        const allObfuscated = card.querySelectorAll('span[aria-labelledby]');
                        for (const oc of allObfuscated) {
                            const closestLink = oc.closest('a[href]');
                            if (closestLink && isProfileHref2(closestLink.href || '')) continue;
                            const ariaText = readFromAriaLabelledBy(oc);
                            if (ariaText && isLikelyPostDate(ariaText)) return ariaText;
                            const visible = readVisibleCharsFromObfuscatedSpans(oc);
                            if (visible && isLikelyPostDate(visible)) return visible;
                        }

                        const allFlexSpans = card.querySelectorAll('span[style*="display: flex"], span[style*="display:flex"]');
                        for (const fs of allFlexSpans) {
                            const closestLink = fs.closest('a[href]');
                            if (closestLink && isProfileHref2(closestLink.href || '')) continue;
                            const container = fs.parentElement || fs;
                            const visible = readVisibleCharsFromObfuscatedSpans(container);
                            if (visible && isLikelyPostDate(visible)) return visible;
                        }

                        const fallbackTime = card.querySelector('time[datetime]');
                        if (fallbackTime) {
                            const dt = normalizeText(fallbackTime.getAttribute('datetime') || '');
                            if (dt) return dt;
                        }
                        const fallbackAbbr = card.querySelector('abbr[title], abbr[data-utime]');
                        if (fallbackAbbr) {
                            const title = normalizeText(fallbackAbbr.getAttribute('title') || '');
                            if (title) return title;
                        }

                        for (const a of card.querySelectorAll('a[href]')) {
                            if (isProfileHref2(a.href || '')) continue;
                            const linkText = normalizeText(a.innerText || a.textContent || '');
                            if (linkText && linkText.length < 40 && isLikelyPostDate(linkText)) return linkText;
                            const ariaL = normalizeText(a.getAttribute('aria-label') || '');
                            if (ariaL && ariaL.length < 40 && isLikelyPostDate(ariaL)) return ariaL;
                        }

                        for (const span of card.querySelectorAll('span')) {
                            if (span.children.length > 3) continue;
                            const st = normalizeText(span.innerText || span.textContent || '');
                            if (st && st.length > 2 && st.length < 30 && isLikelyPostDate(st)) return st;
                        }
                        return null;
                    }

                    Array.from(feed.children).forEach((child, idx) => {
                        const postContent = cardText(child);
                        const postLink = child.querySelector(
                            'a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"], a[href*="/photo/"], ' +
                            'a[href*="/watch"], a[href*="/reel/"], a[href*="/videos/"], a[href*="watch?v="]'
                        );
                        const postUrl = postLink ? postLink.href : null;
                        const postDate = extractPostDate(child, postLink);
                        const profileLink = Array.from(child.querySelectorAll('a[href]'))
                            .find((a) => isProfileHref(a.href));
                        if (!profileLink) return;
                        const key = `${postUrl || profileLink.href}|${(postContent || '').slice(0, 80)}`;
                        if (seen.has(key)) return;
                        seen.add(key);
                        out.push({
                            url: profileLink.href,
                            text: (profileLink.textContent || '').trim(),
                            type: 'direct',
                            post_content: postContent || null,
                            post_url: postUrl || null,
                            post_date: postDate || null,
                            visible_index: idx,
                        });
                    });
                    return out;
                }
                """,
                exclude_uids_list,
            )

            # Hover tooltip date extraction for progressive-scan results
            try:
                article_count = await page.locator("div[role='main'] div[role='article']").count()
                if article_count > 0:
                    date_by_index = await _extract_dates_via_tooltip_hover(
                        page, article_count, should_stop=should_stop
                    )
                    for link in extra_links:
                        idx = link.get("visible_index")
                        if idx is not None and idx in date_by_index:
                            link["post_date"] = date_by_index[idx]
            except Exception as e:
                logger.debug("Tooltip date extraction (progressive): %s", e)

            added = 0
            for link in extra_links:
                if not _is_user_profile_url(link.get("url", "")):
                    continue
                key = _link_key(link)
                if key in seen_link_keys:
                    continue
                seen_link_keys.add(key)
                user_links.append(link)
                added += 1

            if added == 0:
                no_growth_rounds += 1
                logger.info(
                    "Progressive scan round %d: no new links (%d/%d)",
                    scan_round,
                    no_growth_rounds,
                    no_growth_threshold,
                )
            else:
                no_growth_rounds = 0
                logger.info(
                    "Progressive scan round %d: +%d links (total=%d)",
                    scan_round,
                    added,
                    len(user_links),
                )

            if len(user_links) >= max_results or no_growth_rounds >= no_growth_threshold:
                break

    users_saved = 0
    # No deduplication by profile/user ID here — same user can have multiple posts.
    # Deduplication is only by post_url when saving (in fb_profile_processor).
    filtered_links: List[Dict] = user_links
    logger.info(f"Processing {len(filtered_links)} links sequentially")

    for i, link in enumerate(filtered_links):
        if should_stop and should_stop():
            logger.warning("Stop requested while processing profiles.")
            break

        if users_saved >= max_results:
            logger.info(f"Reached max_results ({max_results}), stopping")
            break

        logger.info(
            f"Processing link {i+1}/{len(filtered_links)}: "
            f"{link.get('text', '') or link['url'][:50]}"
        )

        # 1) Capture canonical post URL via Share → Copy link
        extracted_post_url = link.get("post_url")
        logger.info(f"  [PostURL] JS-extracted post_url={extracted_post_url!r}")
        try:
            shared_post_url = await capture_post_url_via_share_button(page, link)
            if shared_post_url:
                link["post_url"] = shared_post_url
                logger.info(f"  [PostURL] Captured via Share->CopyLink: {shared_post_url[:80]}")
            else:
                logger.info(f"  [PostURL] Share->CopyLink returned nothing; keeping: {extracted_post_url!r}")
        except Exception as e:
            logger.debug("  [PostURL] Share link capture error: %s", e)

        # 2) Scrape comments from the search page dialog
        comments_data: List[Dict] = []
        try:
            comments_data, dialog_post_url = await click_comments_and_extract_from_dialog(
                page,
                link["url"],
                max_comments=0,
                visible_index=link.get("visible_index"),
            )
            if dialog_post_url:
                link["post_url"] = dialog_post_url
                logger.info(f"  [PostURL] Set from dialog: {dialog_post_url}")
            elif not link.get("post_url"):
                logger.info("  [PostURL] Dialog gave no URL and share button also failed — post_url will be None")

            if comments_data:
                logger.info(f"  [Comments] Final count: {len(comments_data)}")
            else:
                logger.info("  [Comments] No comments scraped for this post")
        except Exception as e:
            logger.warning(f"  [Comments] Comment extraction error: {e}")

        # 3) Visit profile and store to DB
        account_uid = current_account.get("uid", "")
        new_page = await browser_manager.create_page_with_cookies(account_uid)
        try:
            result = await process_single_profile(
                new_page, link, keyword, i + 1, len(filtered_links), db, comments_data
            )
            if result:
                users_saved += 1
                logger.info(f"Progress: {users_saved}/{max_results} profiles saved")
        except Exception as e:
            logger.error(f"  Error processing profile: {e}")

        if i < len(filtered_links) - 1 and users_saved < max_results:
            delay = random.uniform(3, 7)
            logger.info(f"Waiting {delay:.1f}s before next profile...")
            remaining = delay
            while remaining > 0:
                if should_stop and should_stop():
                    logger.warning("Stop requested during profile delay.")
                    break
                chunk = min(1.0, remaining)
                await asyncio.sleep(chunk)
                remaining -= chunk
            if should_stop and should_stop():
                break

    logger.info(f"Completed: {users_saved} users saved to database")
    return users_saved
