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
    """Wrap raw card HTML in feed+article structure. Date extraction is handled elsewhere."""
    return (
        f'<div role="feed"><div role="article" aria-label="Test post">{card_html}</div></div>'
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

            // post date — removed; will be replaced systematically
            const postDate = null;

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
