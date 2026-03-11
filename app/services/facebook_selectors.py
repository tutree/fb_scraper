"""
Shared selector-driven JS snippets aligned with tests/test_selector_matching.py.
"""

COMMENT_TRIGGER_FROM_PAGE_JS = """
() => {
    function isVisible(el) { return !!el; }
    function clickEl(el) {
        if (!el || !isVisible(el)) return false;
        try { el.click(); return true; } catch (_) { return false; }
    }
    function clickCommentTrigger(card) {
        if (!card) return {clicked: false, method: null, reason: 'no_card'};
        // Strategy 1: [data-ad-rendering-role="comment_button"] — most reliable, opens dialog
        const marker = card.querySelector('[data-ad-rendering-role="comment_button"]');
        if (marker) {
            const btn = marker.closest('[role="button"], [role="link"]');
            if (clickEl(btn)) return {clicked: true, method: 'ad_rendering_role'};
        }
        // Strategy 2: aria-label "Leave a comment" / "Comment" — action button, opens dialog
        for (const el of card.querySelectorAll(
                'div[role="button"][aria-label], span[role="button"][aria-label], a[role="button"][aria-label]')) {
            const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
            if (aria && /leave\s*a\s*comment|\bcomment\b/i.test(aria) &&
                !/share|reaction|react/i.test(aria) && clickEl(el))
                return {clicked: true, method: 'aria_label'};
        }
        // Strategy 3: button text exactly "Comment" — action button, opens dialog
        for (const el of card.querySelectorAll(
                'div[role="button"], span[role="button"], a[role="button"]')) {
            const t = (el.innerText || el.textContent || '').trim().toLowerCase();
            if ((t === 'comment' || t === 'comments') && clickEl(el))
                return {clicked: true, method: 'action_button_text'};
        }
        // Strategy 4: fallback — click comment count (may only expand inline, not open dialog)
        for (const n of card.querySelectorAll(
                'div[role="button"], span[role="button"], a[role="button"], span, a')) {
            const t = (n.innerText || n.textContent || '').trim();
            if (!t || !isVisible(n)) continue;
            if (/^\d+[\s,.]*comments?$/i.test(t) && clickEl(n))
                return {clicked: true, method: 'count_text'};
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
"""

COMMENT_TRIGGER_FOR_PROFILE_JS = """
(payload) => {
    const profilePath = (payload && payload.profilePath) || '';
    const preferredIdx = payload && payload.preferredIdx;

    function normalizeUrl(u) {
        try {
            const url = new URL(u, window.location.origin);
            return (url.origin + url.pathname).replace(/\/$/, '').toLowerCase();
        } catch (_) {
            return (u || '').split('?')[0].replace(/\/$/, '').toLowerCase();
        }
    }

    function isVisible(el) { return !!el; }
    function clickEl(el) {
        if (!el || !isVisible(el)) return false;
        try { el.click(); return true; } catch (_) { return false; }
    }

    function clickCommentTrigger(card) {
        if (!card) return null;

        // Strategy 1: [data-ad-rendering-role="comment_button"] — opens dialog
        const marker = card.querySelector('[data-ad-rendering-role="comment_button"]');
        if (marker) {
            const btn = marker.closest('[role="button"], [role="link"]');
            if (clickEl(btn)) return 'ad_rendering_role';
        }

        // Strategy 2: aria-label "Leave a comment" / "Comment" — opens dialog
        const ariaButtons = card.querySelectorAll(
            'div[role="button"][aria-label], span[role="button"][aria-label], a[role="button"][aria-label]'
        );
        for (const el of ariaButtons) {
            const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
            if (!aria) continue;
            if (/leave\s*a\s*comment|\bcomment\b/i.test(aria) && !/share|reaction|react/i.test(aria)) {
                if (clickEl(el)) return 'aria_label';
            }
        }

        // Strategy 3: button text exactly "Comment" — opens dialog
        const actionButtons = card.querySelectorAll('div[role="button"], span[role="button"], a[role="button"]');
        for (const el of actionButtons) {
            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
            if ((text === 'comment' || text === 'comments') && clickEl(el)) return 'action_button_text';
        }

        // Strategy 4: fallback — click comment count (may only expand inline)
        const nodes = card.querySelectorAll(
            'div[role="button"], span[role="button"], a[role="button"], span, a'
        );
        for (const n of nodes) {
            const t = (n.innerText || n.textContent || '').trim();
            if (!t || !isVisible(n)) continue;
            if (/^\d+[\s,.]*comments?$/i.test(t)) {
                if (clickEl(n)) return 'count_text';
            }
        }

        return null;
    }

    const pathToMatch = normalizeUrl(profilePath);
    const main = document.querySelector('div[role="main"]') || document;
    const feed = main.querySelector('div[role="feed"]') || document.querySelector('div[role="feed"]');
    const articles = main.querySelectorAll('div[role="article"]');
    const containers = articles.length > 0 ? Array.from(articles) : (feed ? Array.from(feed.children) : []);

    const diag = {
        clicked: false,
        method: null,
        matchedIdx: -1,
        containersCount: containers.length,
        articlesCount: articles.length,
        hasFeed: !!feed,
        pageUrl: location.href.substring(0, 100),
    };

    if (typeof preferredIdx === 'number' && preferredIdx >= 0 && preferredIdx < containers.length) {
        const method = clickCommentTrigger(containers[preferredIdx]);
        if (method) {
            diag.clicked = true;
            diag.method = method;
            diag.matchedIdx = preferredIdx;
            return diag;
        }
    }

    for (let i = 0; i < containers.length; i++) {
        const article = containers[i];
        const anchors = article.querySelectorAll('a[href*="facebook.com"]');
        let match = false;
        for (const a of anchors) {
            const href = normalizeUrl(a.href || '');
            if (pathToMatch && href && (href.includes(pathToMatch) || pathToMatch.includes(href))) {
                match = true;
                break;
            }
        }
        if (!match) continue;
        const method = clickCommentTrigger(article);
        if (method) {
            diag.clicked = true;
            diag.method = method;
            diag.matchedIdx = i;
            return diag;
        }
    }

    for (let i = 0; i < Math.min(containers.length, 8); i++) {
        const method = clickCommentTrigger(containers[i]);
        if (method) {
            diag.clicked = true;
            diag.method = 'fallback_card_' + i;
            diag.matchedIdx = i;
            return diag;
        }
    }

    return diag;
}
"""

HAS_DIALOG_JS = """
() => {
    function isCommentDialog(d) {
        if (d.querySelector('[aria-label^="Write a comment"], [placeholder*="comment" i]')) return true;
        if (d.querySelectorAll('div[role="article"][aria-label^="Comment by"]').length > 0) return true;
        const text = (d.innerText || d.textContent || '').toLowerCase();
        return text.includes('write a comment') || text.includes('leave a comment');
    }
    return Array.from(document.querySelectorAll('[role="dialog"]')).some(isCommentDialog);
}
"""

DIALOG_DIAG_JS = """
() => {
    function isCommentDialog(d) {
        if (d.querySelector('[aria-label^="Write a comment"], [placeholder*="comment" i]')) return true;
        if (d.querySelectorAll('div[role="article"][aria-label^="Comment by"]').length > 0) return true;
        const text = (d.innerText || d.textContent || '').toLowerCase();
        return text.includes('write a comment') || text.includes('leave a comment');
    }
    const allDialogs = Array.from(document.querySelectorAll('[role="dialog"]'));
    const dialog = allDialogs.find(isCommentDialog) || null;
    if (!dialog) return {hasDialog: false, dialogCount: allDialogs.length, articles: 0, writeInput: false};
    const articles = dialog.querySelectorAll('div[role="article"][aria-label^="Comment by"]').length;
    const writeInput = !!dialog.querySelector('[aria-label^="Write a comment"]');
    return {
        hasDialog: true,
        dialogCount: allDialogs.length,
        articles,
        writeInput
    };
}
"""

EXTRACT_DIALOG_COMMENTS_JS = """
(maxComments) => {
    function isCommentDialog(d) {
        if (d.querySelector('[aria-label^="Write a comment"], [placeholder*="comment" i]')) return true;
        if (d.querySelectorAll('div[role="article"][aria-label^="Comment by"]').length > 0) return true;
        const text = (d.innerText || d.textContent || '').toLowerCase();
        return text.includes('write a comment') || text.includes('leave a comment');
    }

    function getText(el) {
        if (!el) return '';
        return (el.innerText || el.textContent || '').trim();
    }

    function isProfileUrl(url) {
        if (!url || !url.includes('facebook.com')) return false;
        if (url.includes('/groups/') || url.includes('/pages/') || url.includes('/events/')) return false;
        return true;
    }

    const SKIP = /^(Like|Reply|Share|Comment|Facebook|Anonymous participant|\d+[smhdw]|Just now|Yesterday|See more|\d+ min|\d+ hr|\d+ (w|d|m|y))/i;
    const TIMESTAMP_RE = /^(\d+[smhdw]?|Just now|Yesterday|\d+ min|\d+ hr|\d+ (w|d|m|y))$/i;

    function looksLikeAuthorNameOnly(text) {
        if (!text || text.length > 100) return false;
        if (/[.!?]/.test(text)) return false;
        const words = text.trim().split(/\s+/);
        if (words.length > 4) return false;
        if (/^[A-Z][a-z']+(\s+[A-Z][a-z']+){0,3}$/.test(text.trim())) return true;
        return words.length <= 3 && text.length < 40;
    }

    function isAuthorProfileLink(a) {
        if (!a || !a.href) return false;
        if (!isProfileUrl(a.href)) return false;
        const text = getText(a);
        if (!text || TIMESTAMP_RE.test(text) || SKIP.test(text)) return false;
        return true;
    }

    function extractTimestamp(container, label) {
        for (const s of container.querySelectorAll('span, abbr, a')) {
            const text = getText(s);
            if (TIMESTAMP_RE.test(text)) return text;
        }
        const cleaned = (label || '').replace(/^Comment by\s+/i, '').trim();
        const tsMatch = cleaned.match(/(Just now|Yesterday|\d+\s*(?:min|hr|[smhdwmy]))$/i);
        return tsMatch ? tsMatch[1].trim() : '';
    }

    function extractAuthor(container, label) {
        for (const a of container.querySelectorAll('a[href*="facebook.com"]')) {
            if (isAuthorProfileLink(a)) {
                return {
                    name: getText(a),
                    url: a.getAttribute('href').split('?')[0],
                };
            }
        }

        const fromLabel = (label || '').match(/^Comment by\s+(.+?)(?:,\s*|\s+(?:Just now|Yesterday|\d+\s*(?:min|hr|[smhdwmy]))$)/i);
        if (fromLabel) {
            return { name: fromLabel[1].trim(), url: null };
        }

        const pn = container.querySelector('[data-ad-rendering-role="profile_name"]');
        const fallbackName = getText(pn);
        return { name: fallbackName || 'Unknown', url: null };
    }

    function extractBody(container, authorName) {
        const selectors = [
            '[data-ad-rendering-role="story_message"]',
            '[data-ad-comet-preview="message"]',
            'div.x1lliihq.xjkvuk6.x1iorvi4'
        ];

        for (const selector of selectors) {
            const root = container.querySelector(selector);
            if (!root) continue;
            const candidates = root.querySelectorAll('div[dir="auto"], span[dir="auto"], div[data-ad-preview="message"]');
            for (const node of candidates) {
                const text = getText(node);
                if (text && text !== authorName && !SKIP.test(text) && !looksLikeAuthorNameOnly(text)) {
                    return text;
                }
            }
            const rootText = getText(root);
            if (rootText && rootText !== authorName && !looksLikeAuthorNameOnly(rootText)) {
                return rootText;
            }
        }

        const candidates = container.querySelectorAll('div[dir="auto"], span[dir="auto"]');
        for (const node of candidates) {
            const text = getText(node);
            if (!text || text === authorName || SKIP.test(text) || looksLikeAuthorNameOnly(text)) continue;
            if (TIMESTAMP_RE.test(text)) continue;
            return text;
        }

        const lines = getText(container)
            .split('\\n')
            .map((line) => line.trim())
            .filter((line) => line && line !== authorName && !SKIP.test(line) && !TIMESTAMP_RE.test(line) && !looksLikeAuthorNameOnly(line));
        return lines.length ? lines[0] : '';
    }

    const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).find(isCommentDialog);
    if (!dialog) return [];

    const limit = (typeof maxComments === 'number' && maxComments > 0) ? maxComments : Number.MAX_SAFE_INTEGER;
    const articles = Array.from(dialog.querySelectorAll('div[role="article"][aria-label^="Comment by"]'));
    const out = [];
    const seen = new Set();

    for (let idx = 0; idx < articles.length && out.length < limit; idx++) {
        const article = articles[idx];
        const label = article.getAttribute('aria-label') || '';
        const author = extractAuthor(article, label);
        const timestamp = extractTimestamp(article, label);
        const bodyText = extractBody(article, author.name);

        if (!author.name || !bodyText) continue;

        const key = `${(author.url || author.name).toLowerCase()}|${bodyText.toLowerCase()}|${timestamp.toLowerCase()}`;
        if (seen.has(key)) continue;
        seen.add(key);

        out.push({
            author_name: author.name,
            author_profile_url: author.url,
            comment_text: bodyText,
            comment_timestamp: timestamp || null,
        });
    }

    return out;
}
"""

POST_URL_FROM_DIALOG_JS = """
() => {
    const a = document.querySelector('a[href*="/posts/"], a[href*="/permalink.php"]');
    return a ? a.getAttribute('href').split('?')[0] : null;
}
"""
