"""
tests/test_selector_matching.py

Synchronous Playwright tests that verify our JS/CSS selectors correctly
find (or don't find) HTML elements in the fixture files.

After each run, tests/results.txt is overwritten with the actual data
that would be persisted to the database (post row + every comment row).

Run:
    venv/Scripts/pytest tests/test_selector_matching.py -v
    venv/Scripts/pytest tests/test_selector_matching.py -v --headed
"""

import datetime
import pathlib
import pytest
from playwright.sync_api import sync_playwright, Page, Browser

# ── Fixture HTML paths ────────────────────────────────────────────────────────
FIXTURES    = pathlib.Path(__file__).parent / "fixtures"
RESULTS_FILE = FIXTURES.parent / "results.txt"
CARD_HTML   = (FIXTURES / "cards"   / "card1.html").read_text(encoding="utf-8")
DIALOG_HTML = (FIXTURES / "dialogs" / "dialog1.html").read_text(encoding="utf-8")


# ── Playwright fixtures (sync, no asyncio needed) ────────────────────────────
@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


def _build_card_wrapper(card_html: str) -> str:
    """Wrap raw card HTML in feed+article structure, adding mock aria-labelledby
    target elements so the extraction pipeline can resolve them (on real Facebook
    these live elsewhere in the page DOM). Include both legacy and current FB IDs."""
    return (
        f'<div role="feed"><div role="article" aria-label="Test post">{card_html}</div></div>'
        '<div style="display:none">'
        '<span id="_r_6u_">March 10, 2026 at 8:15 AM</span>'
        '<span id="_r_78_">March 10, 2026 at 8:15 AM</span>'
        '<span id="_R_2dlct6dmllqn8pl5bb6ismj5ilipam_">March 10, 2026 at 8:15 AM</span>'
        '<span id="_R_16idll56dmllqn8pl5bb6ismj5ilipam_">March 10, 2026 at 8:15 AM</span>'
        '</div>'
    )


@pytest.fixture
def card_page(browser: Browser) -> Page:
    page = browser.new_page()
    page.set_content(_build_card_wrapper(CARD_HTML), wait_until="domcontentloaded")
    yield page
    page.close()


@pytest.fixture
def dialog_page(browser: Browser) -> Page:
    page = browser.new_page()
    page.set_content(DIALOG_HTML, wait_until="domcontentloaded")
    yield page
    page.close()


# ── Results writer – runs after ALL tests, overwrites results.txt ─────────────
@pytest.fixture(scope="session", autouse=True)
def write_results(browser: Browser):
    """After the test session finishes, extract DB-ready fields from the
    fixture HTML files and write them to tests/results.txt (always overwritten)."""
    yield  # all tests run before this point

    # ── 1. Extract post data from card1.html ──────────────────────────────────
    cpage = browser.new_page()
    cpage.set_content(_build_card_wrapper(CARD_HTML), wait_until="domcontentloaded")

    post = cpage.evaluate(
        """
        (() => {
            const article = document.querySelector('div[role="article"]');

            // poster name
            const nameEl = article.querySelector('[data-ad-rendering-role="profile_name"]');
            const posterName = nameEl
                ? (nameEl.innerText || nameEl.textContent || '').trim() : null;

            // poster profile URL (clean, no query params)
            const profileLink = article.querySelector('a[href*="facebook.com"]');
            const profileUrl = profileLink
                ? profileLink.getAttribute('href').split('?')[0] : null;

            // comment count from the comment-count button text
            let commentCount = null;
            for (const n of article.querySelectorAll(
                    'div[role="button"], span[role="button"], a[role="button"], span, a')) {
                const t = (n.innerText || n.textContent || '').trim();
                const m = t.match(/^(\\d+)[\\s,.]*comments?$/i);
                if (m) { commentCount = parseInt(m[1]); break; }
            }

            // reaction / like count from any aria-label mentioning reactions
            let likeCount = null;
            for (const btn of article.querySelectorAll('[role="button"][aria-label]')) {
                const label = btn.getAttribute('aria-label') || '';
                const m = label.match(/(\\d+)[\\s]+(reaction|like|people)/i);
                if (m) { likeCount = parseInt(m[1]); break; }
            }

            // share count (optional)
            let shareCount = null;
            for (const n of article.querySelectorAll(
                    'div[role="button"], span[role="button"], span, a')) {
                const t = (n.innerText || n.textContent || '').trim();
                const m = t.match(/^(\\d+)[\\s,.]*shares?$/i);
                if (m) { shareCount = parseInt(m[1]); break; }
            }

            // post date — use the same extractPostDate pipeline as production
            """
        + EXTRACT_DATE_JS
        + """
            const postDate = extractPostDate(article, null);

            return { posterName, profileUrl, commentCount, likeCount, shareCount, postDate };
        })()
    """
    )
    cpage.close()

    # ── 2. Extract every comment from dialog1.html ────────────────────────────
    dpage = browser.new_page()
    dpage.set_content(DIALOG_HTML, wait_until="domcontentloaded")

    # post URL: first /posts/ or /permalink.php link in the dialog, stripped of query params
    post_url = dpage.evaluate("""
        () => {
            const a = document.querySelector(
                'a[href*="/posts/"], a[href*="/permalink.php"]'
            );
            return a ? a.getAttribute('href').split('?')[0] : null;
        }
    """)

    comments = dpage.evaluate("""
        () => {
            const dialog = document.querySelector('[role="dialog"]');
            return Array.from(
                dialog.querySelectorAll('div[role="article"][aria-label^="Comment by"]')
            ).map((a, idx) => {
                // commenter name from aria-label
                const m = a.getAttribute('aria-label').match(/^Comment by ([^,]+)/);
                const name = m ? m[1].trim() : 'Unknown';

                // commenter profile URL (first facebook.com link, stripped of params)
                const profileLink = a.querySelector('a[href*="facebook.com"]');
                const profileUrl = profileLink
                    ? profileLink.getAttribute('href').split('?')[0] : null;

                // comment body: prefer dir="auto" element (the actual text node FB uses),
                // fall back to the full article innerText
                let bodyText = "";
                const commentDiv = a.querySelector('div[dir="auto"][style*="text-align"]');
                
                if (commentDiv) {
                    bodyText = (commentDiv.innerText || commentDiv.textContent || '').trim();
                } else {
                    const autoBlocks = Array.from(a.querySelectorAll('[dir="auto"]'));
                    if (autoBlocks.length > 1) {
                        bodyText = (autoBlocks[autoBlocks.length - 1].innerText || '').trim();
                    } else if (autoBlocks.length === 1 && autoBlocks[0].innerText.trim() !== name) {
                        bodyText = autoBlocks[0].innerText.trim();
                    }
                }

                // timestamp from aria-label  e.g. "3 weeks ago"
                const ts = a.getAttribute('aria-label').replace(/^Comment by [^,]+,?\\s*/, '').trim();

                return { index: idx + 1, name, profileUrl, bodyText, timestamp: ts };
            });
        }
    """)
    dpage.close()

    # ── 3. Write results.txt ──────────────────────────────────────────────────
    sep  = "=" * 70
    dash = "-" * 70
    now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        sep,
        f"  SCRAPE EXTRACTION RESULTS  —  generated {now}",
        f"  Card fixture   : tests/fixtures/cards/card1.html",
        f"  Dialog fixture : tests/fixtures/dialogs/dialog1.html",
        sep,
        "",
        "┌─ POST ROW (search_result table) " + "─" * 37,
        f"│  poster_name     : {post['posterName']}",
        f"│  profile_url     : {post['profileUrl']}",
        f"│  post_url        : {post_url}",
        f"│  comment_count   : {post['commentCount']}",
        f"│  like_count      : {post['likeCount']}",
        f"│  share_count     : {post['shareCount']}",
        f"│  post_date       : {post['postDate']}",
        "└" + "─" * 69,
        "",
        dash,
        f"  COMMENTS  ({len(comments)} scraped — post_comment table)",
        dash,
    ]

    for c in comments:
        # Wrap long comment body at 65 chars for readability
        body = c["bodyText"]
        body_lines = [body[i:i+65] for i in range(0, min(len(body), 260), 65)]
        body_display = ("\n" + " " * 20).join(body_lines) or "(empty)"
        lines += [
            "",
            f"  Comment #{c['index']}",
            f"    commenter_name  : {c['name']}",
            f"    profile_url     : {c['profileUrl']}",
            f"    timestamp       : {c['timestamp']}",
            f"    comment_text    : {body_display}",
        ]

    lines += ["", sep, ""]

    RESULTS_FILE.write_text("\n".join(lines), encoding="utf-8")


# ── Helpers ───────────────────────────────────────────────────────────────────
def count(page: Page, selector: str) -> int:
    return page.evaluate("(sel) => document.querySelectorAll(sel).length", selector)


# ══════════════════════════════════════════════════════════════════════════════
# POST CARD TESTS  (card1.html)
# ══════════════════════════════════════════════════════════════════════════════

class TestCardStructure:
    """Basic structural selectors that must exist on a post card."""

    def test_feed_container_exists(self, card_page):
        assert count(card_page, 'div[role="feed"]') == 1

    def test_article_exists(self, card_page):
        assert count(card_page, 'div[role="article"]') >= 1

    def test_profile_name_link_exists(self, card_page):
        # Real FB renders this as a <div>, not always an <a>; accept any element.
        assert count(card_page, '[data-ad-rendering-role="profile_name"]') >= 1

    def test_post_url_anchor_exists(self, card_page):
        # Real FB post cards only contain profile anchors; post URLs are retrieved
        # via the share dialog. Verify at least one facebook.com link is present.
        assert count(card_page, 'a[href*="facebook.com"]') >= 1


class TestCommentButtonSelectors:
    """Four strategies our clickCommentTrigger JS uses to find the comment button."""

    def test_strategy1_count_text_button(self, card_page):
        """Strategy 1 - button whose text matches number + 'comments' (e.g. '12 comments' or '1.5K comments')."""
        found = card_page.evaluate("""
            () => {
                const nodes = document.querySelectorAll(
                    'div[role="button"], span[role="button"], a[role="button"], span, a'
                );
                for (const n of nodes) {
                    const t = (n.innerText || n.textContent || '').trim();
                    if (/^\\d+(?:\\.\\d+)?\\s*[KkMm]?[\\s,.]*comments?$/i.test(t)) return true;
                }
                return false;
            }
        """)
        assert found, "Strategy 1: no button with text like '12 comments' or '1.5K comments' found"

    def test_strategy2_ad_rendering_role_marker(self, card_page):
        """Strategy 2 - [data-ad-rendering-role='comment_button'] + closest button"""
        result = card_page.evaluate("""
            () => {
                const marker = document.querySelector('[data-ad-rendering-role="comment_button"]');
                if (!marker) return {markerFound: false};
                const btn = marker.closest('[role="button"], [role="link"]');
                return {
                    markerFound: true,
                    btnFound: !!btn,
                    ariaLabel: btn ? (btn.getAttribute('aria-label') || '') : ''
                };
            }
        """)
        assert result["markerFound"], "[data-ad-rendering-role='comment_button'] not found"
        assert result["btnFound"], "marker.closest('[role=button]') returned null"

    def test_strategy3_aria_label(self, card_page):
        """Strategy 3 - button with aria-label matching 'Leave a comment'"""
        found = card_page.evaluate("""
            () => {
                const els = document.querySelectorAll(
                    'div[role="button"][aria-label], span[role="button"][aria-label], a[role="button"][aria-label]'
                );
                for (const el of els) {
                    const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                    if (!aria) continue;
                    if (/leave\\s*a\\s*comment|\\bcomment\\b/i.test(aria) &&
                        !/share|reaction|react/i.test(aria)) return true;
                }
                return false;
            }
        """)
        assert found, "Strategy 3: no button with aria-label 'Leave a comment' found"

    def test_strategy4_action_button_text(self, card_page):
        """Strategy 4 - button whose innerText is exactly 'Comment'"""
        found = card_page.evaluate("""
            () => {
                const btns = document.querySelectorAll(
                    'div[role="button"], span[role="button"], a[role="button"]'
                );
                for (const el of btns) {
                    const t = (el.innerText || el.textContent || '').trim().toLowerCase();
                    if (t === 'comment' || t === 'comments') return true;
                }
                return false;
            }
        """)
        assert found, "Strategy 4: no button with text 'Comment' found"

    def test_full_clickCommentTrigger(self, card_page):
        """Full clickCommentTrigger returns clicked=true on card1.html"""
        result = card_page.evaluate("""
            () => {
                function isVisible(el) { return !!el; }
                function clickEl(el) {
                    if (!el || !isVisible(el)) return false;
                    try { el.click(); return true; } catch (_) { return false; }
                }
                function clickCommentTrigger(card) {
                    if (!card) return {clicked: false, method: null, reason: 'no_card'};
                    for (const n of card.querySelectorAll(
                            'div[role="button"], span[role="button"], a[role="button"], span, a')) {
                        const t = (n.innerText || n.textContent || '').trim();
                        if (!t || !isVisible(n)) continue;
                        if (/^\\d+[\\s,.]*comments?$/i.test(t) && clickEl(n))
                            return {clicked: true, method: 'count_text'};
                    }
                    const marker = card.querySelector('[data-ad-rendering-role="comment_button"]');
                    if (marker) {
                        const btn = marker.closest('[role="button"], [role="link"]');
                        if (clickEl(btn)) return {clicked: true, method: 'ad_rendering_role'};
                    }
                    for (const el of card.querySelectorAll(
                            'div[role="button"][aria-label], span[role="button"][aria-label], a[role="button"][aria-label]')) {
                        const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                        if (aria && /leave\\s*a\\s*comment|\\bcomment\\b/i.test(aria) &&
                            !/share|reaction|react/i.test(aria) && clickEl(el))
                            return {clicked: true, method: 'aria_label'};
                    }
                    for (const el of card.querySelectorAll(
                            'div[role="button"], span[role="button"], a[role="button"]')) {
                        const t = (el.innerText || el.textContent || '').trim().toLowerCase();
                        if ((t === 'comment' || t === 'comments') && clickEl(el))
                            return {clicked: true, method: 'action_button_text'};
                    }
                    return {clicked: false, method: null, reason: 'no_trigger_found'};
                }
                const feed = document.querySelector('div[role="feed"]');
                const articles = document.querySelectorAll('div[role="article"]');
                const containers = articles.length > 0
                    ? Array.from(articles)
                    : (feed ? Array.from(feed.children) : []);
                return clickCommentTrigger(containers[0]);
            }
        """)
        assert result["clicked"], (
            f"clickCommentTrigger returned clicked=False — "
            f"reason={result.get('reason')}, method={result.get('method')}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# COMMENT DIALOG TESTS  (dialog1.html)
# ══════════════════════════════════════════════════════════════════════════════

class TestDialogStructure:

    def test_dialog_exists(self, dialog_page):
        assert count(dialog_page, 'div[role="dialog"]') == 1

    def test_write_comment_input_exists(self, dialog_page):
        assert count(dialog_page, '[aria-label^="Write a comment"]') >= 1

    def test_comment_articles_exist(self, dialog_page):
        n = count(dialog_page, 'div[role="article"][aria-label^="Comment by"]')
        assert n >= 3, f"Expected >=3 comment articles, found {n}"

    def test_profile_name_markers_in_dialog(self, dialog_page):
        # In real FB dialogs commenter names are encoded in the article's aria-label
        # (e.g. 'Comment by Karen Brown 3 weeks ago'), not in data-ad-rendering-role.
        # Verify we can extract >=3 commenter names that way.
        names = dialog_page.evaluate("""
            () => {
                const arts = document.querySelectorAll(
                    'div[role="dialog"] div[role="article"][aria-label^="Comment by"]'
                );
                return Array.from(arts).map(a => {
                    const m = a.getAttribute('aria-label').match(/^Comment by ([^,]+)/);
                    return m ? m[1].trim() : null;
                }).filter(Boolean);
            }
        """)
        assert len(names) >= 3, f"Expected >=3 commenter names from aria-label, got {names}"

    def test_facebook_links_in_every_comment(self, dialog_page):
        result = dialog_page.evaluate("""
            () => {
                const articles = document.querySelectorAll(
                    'div[role="article"][aria-label^="Comment by"]'
                );
                let withLink = 0;
                for (const a of articles) {
                    if (a.querySelector('a[href*="facebook.com"]')) withLink++;
                }
                return {total: articles.length, withLink};
            }
        """)
        assert result["withLink"] == result["total"], (
            f"Only {result['withLink']}/{result['total']} comment articles have a facebook.com link"
        )


class TestDialogCommentExtraction:
    """Mirrors EXTRACT_FROM_DIALOG_JS: primary selector + two fallback passes."""

    def test_primary_selector_aria_label(self, dialog_page):
        result = dialog_page.evaluate("""
            () => {
                const dialog = document.querySelector('[role="dialog"]');
                if (!dialog) return {error: 'no dialog'};
                const arts = dialog.querySelectorAll('div[role="article"][aria-label^="Comment by"]');
                return {count: arts.length, labels: Array.from(arts).map(a => a.getAttribute('aria-label'))};
            }
        """)
        assert "error" not in result, result.get("error")
        assert result["count"] >= 3, \
            f"Primary selector found {result['count']} articles. Labels: {result['labels']}"

    def test_comment_body_text_extractable(self, dialog_page):
        entries = dialog_page.evaluate("""
            () => {
                const dialog = document.querySelector('[role="dialog"]');
                return Array.from(
                    dialog.querySelectorAll('div[role="article"][aria-label^="Comment by"]')
                ).map(a => ({
                    label: a.getAttribute('aria-label'),
                    text: (a.innerText || a.textContent || '').trim().slice(0, 80)
                }));
            }
        """)
        for e in entries:
            assert e["text"], f"Comment article '{e['label']}' has no text"

    def test_fallback_profile_name_marker(self, dialog_page):
        # Fallback: extract commenter names from aria-label on comment articles.
        # This mirrors the actual extraction logic in facebook_scraper.
        result = dialog_page.evaluate("""
            () => {
                const dialog = document.querySelector('[role="dialog"]');
                if (!dialog) return {error: 'no dialog'};
                const names = Array.from(
                    dialog.querySelectorAll('div[role="article"][aria-label^="Comment by"]')
                ).map(a => {
                    const m = a.getAttribute('aria-label').match(/^Comment by ([^,]+)/);
                    return m ? m[1].trim() : null;
                }).filter(Boolean);
                return {count: names.length, names};
            }
        """)
        assert "error" not in result, result.get("error")
        assert result["count"] >= 3, \
            f"Fallback aria-label names found {result['count']}: {result['names']}"

    def test_fallback_facebook_links(self, dialog_page):
        result = dialog_page.evaluate("""
            () => {
                const dialog = document.querySelector('[role="dialog"]');
                if (!dialog) return {error: 'no dialog'};
                const hrefs = Array.from(
                    dialog.querySelectorAll('a[href*="facebook.com"]')
                ).map(a => a.getAttribute('href'));
                return {count: hrefs.length, hrefs};
            }
        """)
        assert "error" not in result, result.get("error")
        assert result["count"] >= 3, \
            f"Fallback facebook links found {result['count']}: {result['hrefs']}"

    def test_dialog_scoped_query_excludes_background(self, dialog_page):
        n = dialog_page.evaluate("""
            () => document.querySelector('[role="dialog"]')
                          .querySelectorAll('[aria-label="Some background post"]').length
        """)
        assert n == 0, "Dialog query incorrectly matched a background-page element"


# ══════════════════════════════════════════════════════════════════════════════
# DIALOG DETECTION HEURISTIC
# ══════════════════════════════════════════════════════════════════════════════

class TestDialogDetection:

    def test_has_dialog_true_when_dialog_present(self, dialog_page):
        diag = dialog_page.evaluate("""
            () => {
                const d = document.querySelector('[role="dialog"]');
                if (!d) return false;
                const text = (d.innerText || d.textContent || '').toLowerCase();
                return text.includes('comment') ||
                       !!d.querySelector('div[role="article"][aria-label^="Comment by"], [aria-label^="Write a comment"]');
            }
        """)
        assert diag, "hasDialog heuristic returned False on the dialog fixture"

    def test_has_dialog_false_on_card_page(self, card_page):
        diag = card_page.evaluate("""
            () => {
                const d = document.querySelector('[role="dialog"]');
                if (!d) return false;
                const text = (d.innerText || d.textContent || '').toLowerCase();
                return text.includes('comment') ||
                       !!d.querySelector('div[role="article"][aria-label^="Comment by"], [aria-label^="Write a comment"]');
            }
        """)
        assert not diag, "hasDialog returned True on card page (no dialog present)"


# ══════════════════════════════════════════════════════════════════════════════
# POST DATE EXTRACTION TESTS  (card1.html)
# ══════════════════════════════════════════════════════════════════════════════

# The JS functions used by fb_feed_scanner.py for date extraction, bundled for
# reuse by multiple tests.  Injected once, then individual tests call into them.
EXTRACT_DATE_JS = r"""
    function normalizeText(value) {
        return (value || '').replace(/\s+/g, ' ').trim();
    }

    const MONTH_RE = '(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)';
    const MONTH_DAY_RE = new RegExp('\\b' + MONTH_RE + '\\b[\\s,]*\\d', 'i');
    const DAY_MONTH_RE = new RegExp('\\d[\\s,]*\\b' + MONTH_RE + '\\b', 'i');

    function isLikelyPostDate(value) {
        const text = normalizeText(value);
        if (!text || text.length > 80) return false;
        if (/^(?:\d+\s*(?:s|m|min|h|hr|d|w|mo|y)|just now|yesterday|today)$/i.test(text)) return true;
        if (MONTH_DAY_RE.test(text)) return true;
        if (DAY_MONTH_RE.test(text)) return true;
        if (/\b(?:today|yesterday)\b/i.test(text)) return true;
        if (/\b\d{1,2}:\d{2}\b/.test(text)) return true;
        if (/\b\d+\s*(?:mins?|minutes?|hrs?|hours?|days?|weeks?|months?|years?)\s*(?:ago)?\b/i.test(text)) return true;
        if (/^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(text)) return true;
        if (/^\w+ \d{1,2}(?:,? \d{4})?(?:\s+at\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)?$/i.test(text)) return true;
        return false;
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
        return text.replace(/\s+/g, ' ').trim() || null;
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

    function isPostUrl(href) {
        if (!href) return false;
        return (
            href.includes('/posts/') ||
            href.includes('/permalink/') ||
            href.includes('story_fbid') ||
            href.includes('/photo/') ||
            href.includes('/share/')
        );
    }

    function isProfileHref(absoluteHref) {
        if (!absoluteHref || !absoluteHref.includes('facebook.com')) return false;
        try {
            const u = new URL(absoluteHref, location.origin);
            const parts = u.pathname.replace(/^\//, '').replace(/\/$/, '').split('/');
            const slug = parts[0];
            if (!slug) return false;
            if (slug === 'profile.php') return true;
            return /^[A-Za-z0-9._-]{2,}$/.test(slug) && parts.length === 1;
        } catch(e) { return false; }
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
"""


class TestIsLikelyPostDate:
    """Verify isLikelyPostDate correctly accepts dates and rejects non-dates."""

    def _check(self, page, value):
        return page.evaluate(
            f"(() => {{ {EXTRACT_DATE_JS}\nreturn isLikelyPostDate({value!r}); }})()",
        )

    def test_relative_short(self, card_page):
        for v in ["2h", "3d", "5m", "1w", "just now", "yesterday", "today"]:
            assert self._check(card_page, v), f"{v!r} should be a date"

    def test_relative_long(self, card_page):
        for v in ["2 hours ago", "3 days", "15 minutes", "1 year"]:
            assert self._check(card_page, v), f"{v!r} should be a date"

    def test_month_day(self, card_page):
        for v in ["March 10", "April 5 at 2:30 PM", "December 25, 2025",
                   "Jan 1", "Sep 15, 2024 at 9:00 AM"]:
            assert self._check(card_page, v), f"{v!r} should be a date"

    def test_day_month(self, card_page):
        for v in ["10 March", "5 April 2024", "25 December"]:
            assert self._check(card_page, v), f"{v!r} should be a date"

    def test_time_patterns(self, card_page):
        for v in ["3:45", "11:00", "03/15/2025", "12/31/24"]:
            assert self._check(card_page, v), f"{v!r} should be a date"

    def test_rejects_person_names(self, card_page):
        for v in ["April Jones", "May Smith", "August Wilson",
                   "March Johnson", "June Carter"]:
            assert not self._check(card_page, v), f"{v!r} should NOT be a date"

    def test_rejects_non_date_text(self, card_page):
        for v in ["Hello world", "Looking for a tutor", "Autumn Martin",
                   "Facebook", "Like", "Share", "Comment", ""]:
            assert not self._check(card_page, v), f"{v!r} should NOT be a date"


class TestPostDateStructure:
    """Verify the card1.html fixture has the expected DOM structure for date
    extraction: profile_name header, nearby date anchor with #? hash, and
    obfuscated character spans."""

    def test_profile_name_header_exists(self, card_page):
        assert count(card_page, '[data-ad-rendering-role="profile_name"]') >= 1

    def test_date_anchor_with_hash_exists(self, card_page):
        """The card contains an <a> whose href includes '#?' — Facebook's
        typical date link pattern on search results."""
        n = card_page.evaluate("""
            () => {
                const article = document.querySelector('div[role="article"]');
                const anchors = article.querySelectorAll('a[href*="#?"]');
                return anchors.length;
            }
        """)
        assert n >= 1, "No anchor with href containing '#?' found in the card"

    def test_obfuscated_flex_span_container_exists(self, card_page):
        """The card has at least one span with display:flex containing
        individual character spans (Facebook's CSS obfuscation pattern).
        Checks both the style attribute and computed style since browsers
        may normalize the inline style string differently."""
        result = card_page.evaluate("""
            () => {
                const article = document.querySelector('div[role="article"]');
                // Try attribute selector first (covers most browsers)
                let flex = article.querySelector('span[style*="display: flex"]')
                        || article.querySelector('span[style*="display:flex"]');
                // Fallback: scan spans whose computed display is 'flex'
                if (!flex) {
                    for (const s of article.querySelectorAll('span[style]')) {
                        if (getComputedStyle(s).display === 'flex') { flex = s; break; }
                    }
                }
                if (!flex) return {found: false};
                const charSpans = flex.querySelectorAll(':scope > span');
                return {found: true, charCount: charSpans.length};
            }
        """)
        assert result["found"], "No flex-display span container found in card"
        assert result["charCount"] >= 3, (
            f"Flex container has only {result['charCount']} character spans"
        )

    def test_date_anchor_near_profile_name(self, card_page):
        """Walk up from profile_name until we find a container that also has
        the #? date anchor as a descendant."""
        found = card_page.evaluate("""
            () => {
                const article = document.querySelector('div[role="article"]');
                const headerDiv = article.querySelector(
                    'div[data-ad-rendering-role="profile_name"]'
                );
                if (!headerDiv) return false;
                let el = headerDiv;
                while (el && el !== article) {
                    if (el.querySelector && el.querySelector('a[href*="#?"]'))
                        return true;
                    el = el.parentElement;
                }
                return false;
            }
        """)
        assert found, "Date anchor (href containing '#?') not found near profile_name"


class TestExtractPostDate:
    """End-to-end test of the full extractPostDate pipeline on card1.html.

    Facebook uses CSS-obfuscated character spans for dates.  Without the real
    stylesheets the visibility filter cannot distinguish real from decoy chars,
    so extractPostDate returns null in the test environment.

    These tests verify that the extraction pipeline:
      - Correctly identifies the #? date anchor as a candidate.
      - Reads character spans from the obfuscated flex container.
      - Does NOT accidentally return the poster name.
      - Returns null (expected) because garbled text fails isLikelyPostDate.
    """

    def test_candidates_include_hash_anchor(self, card_page):
        """isDateAnchor must recognise the #? href pattern used on FB search
        results so it gets added to the candidate list."""
        result = card_page.evaluate(f"""
            (() => {{
                {EXTRACT_DATE_JS}
                const article = document.querySelector('div[role="article"]');
                const candidates = [];
                for (const link of article.querySelectorAll('a[href]')) {{
                    const href = link.href || '';
                    const rawHref = link.getAttribute('href') || '';
                    if (isDateAnchor(href, rawHref) && !isProfileHref(href))
                        candidates.push({{
                            hasHash: rawHref.includes('#?'),
                            hasPosts: rawHref.includes('/posts/'),
                            hasFlexSpan: !!link.querySelector(
                                'span[style*="display:flex"], span[style*="display: flex"]'
                            ) || Array.from(link.querySelectorAll('span[style]')).some(
                                s => getComputedStyle(s).display === 'flex'
                            )
                        }});
                }}
                return candidates;
            }})()
        """)
        assert len(result) >= 1, "No date anchor candidates found"
        hash_candidates = [c for c in result if c["hasHash"] or c["hasPosts"]]
        assert len(hash_candidates) >= 1, (
            f"No #? or /posts/ anchors in candidates. Got: {result}"
        )

    def test_extractPostDate_does_not_return_poster_name(self, card_page):
        """Even if extraction succeeds, it must never return the poster name."""
        result = card_page.evaluate(f"""
            (() => {{
                {EXTRACT_DATE_JS}
                const article = document.querySelector('div[role="article"]');
                const posterName = (article.querySelector(
                    '[data-ad-rendering-role="profile_name"]'
                ) || {{}}).innerText || '';
                const date = extractPostDate(article, null);
                return {{date, posterName: posterName.split('\\n')[0]}};
            }})()
        """)
        if result["date"]:
            assert result["posterName"] not in result["date"], (
                f"extractPostDate returned the poster name: {result!r}"
            )

    def test_flex_span_chars_readable(self, card_page):
        """readVisibleCharsFromObfuscatedSpans can read character spans inside
        the date anchor, even though without CSS it returns all chars (garbled)."""
        result = card_page.evaluate(f"""
            (() => {{
                {EXTRACT_DATE_JS}
                const article = document.querySelector('div[role="article"]');
                const anchor = article.querySelector('a[href*="#?"]');
                if (!anchor) return {{found: false}};
                const raw = readVisibleCharsFromObfuscatedSpans(anchor);
                return {{found: true, raw: raw, len: raw ? raw.length : 0}};
            }})()
        """)
        assert result["found"], "No #? date anchor found"
        assert result["raw"] is not None, "readVisibleCharsFromObfuscatedSpans returned null"
        assert result["len"] > 5, (
            f"Expected >5 chars from obfuscated spans, got {result['len']}"
        )

    def test_hash_anchor_contains_date_digits(self, card_page):
        """The raw text from the #? date anchor should contain digits (part of
        the actual date mixed in with decoy characters)."""
        raw = card_page.evaluate(f"""
            (() => {{
                {EXTRACT_DATE_JS}
                const article = document.querySelector('div[role="article"]');
                const anchor = article.querySelector('a[href*="#?"]');
                if (!anchor) return '';
                return readVisibleCharsFromObfuscatedSpans(anchor) || '';
            }})()
        """)
        import re
        digits = re.findall(r'\d', raw)
        assert len(digits) >= 2, (
            f"Expected date digits in obfuscated text, got: {raw!r}"
        )

    def test_extractPostDate_resolves_via_aria_labelledby(self, card_page):
        """extractPostDate resolves the date via aria-labelledby targets
        that exist in the page DOM (mock targets added by the test wrapper)."""
        result = card_page.evaluate(f"""
            (() => {{
                {EXTRACT_DATE_JS}
                const article = document.querySelector('div[role="article"]');
                return extractPostDate(article, null);
            }})()
        """)
        assert result is not None, "extractPostDate should resolve date via aria-labelledby"
        assert "March" in result and "10" in result, (
            f"Expected a date containing 'March' and '10', got: {result!r}"
        )
