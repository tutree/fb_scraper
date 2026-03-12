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
    const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).find(isCommentDialog);
    if (!dialog) return [];
    const limit = (typeof maxComments === 'number' && maxComments > 0) ? maxComments : Number.MAX_SAFE_INTEGER;
    const articles = Array.from(
        dialog.querySelectorAll('div[role="article"][aria-label^="Comment by"]')
    );
    const out = [];
    for (let idx = 0; idx < articles.length && out.length < limit; idx++) {
        const a = articles[idx];
        const label = a.getAttribute('aria-label') || '';
        const m = label.match(/^Comment by ([^,]+)/);
        const name = m ? m[1].trim() : 'Unknown';

        const profileLink = a.querySelector('a[href*="facebook.com"]');
        const profileUrl = profileLink
            ? profileLink.getAttribute('href').split('?')[0]
            : null;

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

        const ts = label.replace(/^Comment by [^,]+,?\s*/, '').trim();

        out.push({
            author_name: name,
            author_profile_url: profileUrl,
            comment_text: bodyText,
            comment_timestamp: ts,
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
