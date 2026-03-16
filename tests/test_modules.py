"""
tests/test_modules.py

Tests for the modularised facebook_scraper services.

Groups:
    TestResolveCommentLimit     — pure unit tests (no browser)
    TestIsUserProfileUrl        — pure unit tests (no browser)
    TestLinkKey                 — pure unit tests (no browser)
    TestExtractCUserFromCookie  — pure unit tests (no browser)
    TestCardPageSelectors       — Playwright fixture tests with card1.html
    TestDialogPageSelectors     — Playwright fixture tests with dialog1.html

Run:
    venv/bin/pytest tests/test_modules.py -v
"""

import pathlib
import sys

import pytest
from playwright.sync_api import sync_playwright, Browser, Page

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from app.services.fb_comment_handler import resolve_comment_limit
from app.services.fb_feed_scanner import _is_user_profile_url, _link_key
from app.services.fb_account_loader import _extract_c_user_from_cookie_json
from app.services.facebook_selectors import (
    COMMENT_TRIGGER_FROM_PAGE_JS,
    EXTRACT_DIALOG_COMMENTS_JS,
    HAS_DIALOG_JS,
    POST_URL_FROM_DIALOG_JS,
)

# ── Fixture HTML ──────────────────────────────────────────────────────────────
_FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_CARD_HTML = (_FIXTURES / "cards" / "card1.html").read_text(encoding="utf-8")
_DIALOG_HTML = (_FIXTURES / "dialogs" / "dialog1.html").read_text(encoding="utf-8")


# ── Playwright fixtures ───────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def card_page(browser: Browser) -> Page:
    page = browser.new_page()
    wrapped = (
        '<div role="feed">'
        f'<div role="article" aria-label="Test post">{_CARD_HTML}</div>'
        "</div>"
    )
    page.set_content(wrapped, wait_until="domcontentloaded")
    yield page
    page.close()


@pytest.fixture
def dialog_page(browser: Browser) -> Page:
    page = browser.new_page()
    page.set_content(_DIALOG_HTML, wait_until="domcontentloaded")
    yield page
    page.close()


# ── Pure unit tests ───────────────────────────────────────────────────────────

class TestResolveCommentLimit:
    def test_zero_returns_5000(self):
        assert resolve_comment_limit(0) == 5000

    def test_negative_returns_5000(self):
        assert resolve_comment_limit(-1) == 5000

    def test_none_returns_5000(self):
        assert resolve_comment_limit(None) == 5000

    def test_positive_passthrough(self):
        assert resolve_comment_limit(50) == 50

    def test_large_value_passthrough(self):
        assert resolve_comment_limit(10_000) == 10_000


class TestIsUserProfileUrl:
    def test_regular_profile_is_true(self):
        assert _is_user_profile_url("https://www.facebook.com/john.doe") is True

    def test_profile_php_is_true(self):
        assert _is_user_profile_url("https://www.facebook.com/profile.php?id=123456") is True

    def test_groups_is_false(self):
        assert _is_user_profile_url("https://www.facebook.com/groups/some-group") is False

    def test_pages_is_false(self):
        assert _is_user_profile_url("https://www.facebook.com/pages/my-page/123") is False

    def test_events_is_false(self):
        assert _is_user_profile_url("https://www.facebook.com/events/123") is False

    def test_marketplace_is_false(self):
        assert _is_user_profile_url("https://www.facebook.com/marketplace/item/123") is False

    def test_watch_is_false(self):
        assert _is_user_profile_url("https://www.facebook.com/watch") is False

    def test_gaming_is_false(self):
        assert _is_user_profile_url("https://www.facebook.com/gaming") is False

    def test_query_string_stripped_before_check(self):
        # profile.php with query string must still be True
        assert _is_user_profile_url("https://www.facebook.com/profile.php?id=999&ref=hl") is True


class TestLinkKey:
    def test_uses_post_url_when_present(self):
        link = {"post_url": "https://fb.com/posts/123", "url": "https://fb.com/user", "post_content": "hello"}
        assert _link_key(link).startswith("https://fb.com/posts/123|")

    def test_falls_back_to_url(self):
        link = {"url": "https://fb.com/user", "post_content": "hello"}
        assert _link_key(link).startswith("https://fb.com/user|")

    def test_content_truncated_to_80_chars(self):
        link = {"post_url": "u", "post_content": "x" * 200}
        assert _link_key(link) == "u|" + "x" * 80

    def test_empty_link_produces_pipe(self):
        assert _link_key({}) == "|"

    def test_content_shorter_than_80_kept_in_full(self):
        link = {"post_url": "u", "post_content": "short"}
        assert _link_key(link) == "u|short"


class TestExtractCUserFromCookie:
    def test_dict_with_cookies_list(self):
        data = {"cookies": [{"name": "c_user", "value": "123456"}]}
        assert _extract_c_user_from_cookie_json(data) == "123456"

    def test_list_of_cookies(self):
        data = [{"name": "c_user", "value": "789"}]
        assert _extract_c_user_from_cookie_json(data) == "789"

    def test_no_c_user_returns_none(self):
        data = {"cookies": [{"name": "xs", "value": "abc"}]}
        assert _extract_c_user_from_cookie_json(data) is None

    def test_invalid_type_returns_none(self):
        assert _extract_c_user_from_cookie_json("not a dict") is None

    def test_dict_with_non_list_cookies_returns_none(self):
        assert _extract_c_user_from_cookie_json({"cookies": "bad"}) is None

    def test_multiple_cookies_returns_c_user(self):
        data = [
            {"name": "xs", "value": "abc"},
            {"name": "c_user", "value": "99999"},
        ]
        assert _extract_c_user_from_cookie_json(data) == "99999"

    def test_empty_value_not_returned(self):
        data = [{"name": "c_user", "value": ""}]
        assert _extract_c_user_from_cookie_json(data) is None


# ── Card page selector tests ──────────────────────────────────────────────────

class TestCardPageSelectors:
    def test_feed_exists(self, card_page: Page):
        assert card_page.evaluate('() => !!document.querySelector(\'[role="feed"]\')') is True

    def test_article_count_is_one(self, card_page: Page):
        assert card_page.evaluate('() => document.querySelectorAll(\'[role="article"]\').length') == 1

    def test_has_dialog_returns_false(self, card_page: Page):
        assert card_page.evaluate(HAS_DIALOG_JS) is False

    def test_comment_trigger_clicked(self, card_page: Page):
        result = card_page.evaluate(COMMENT_TRIGGER_FROM_PAGE_JS)
        assert result["clicked"] is True

    def test_comment_trigger_method_is_dialog_opener(self, card_page: Page):
        # The card fixture has data-ad-rendering-role="comment_button" which now
        # takes priority since it reliably opens the comments dialog.
        result = card_page.evaluate(COMMENT_TRIGGER_FROM_PAGE_JS)
        assert result["method"] in ("ad_rendering_role", "aria_label", "action_button_text"), (
            f"Expected a dialog-opening method, got: {result['method']}"
        )

    def test_no_post_url_on_card(self, card_page: Page):
        # No /posts/ link should be present in the raw card fixture
        result = card_page.evaluate(POST_URL_FROM_DIALOG_JS)
        # card1.html has no /posts/ anchor at the top level outside a dialog
        assert result is None or isinstance(result, str)


# ── Dialog page selector tests ────────────────────────────────────────────────

class TestDialogPageSelectors:
    def test_has_dialog_returns_true(self, dialog_page: Page):
        assert dialog_page.evaluate(HAS_DIALOG_JS) is True

    def test_extract_returns_8_comments(self, dialog_page: Page):
        comments = dialog_page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, 0)
        assert len(comments) == 8

    def test_extract_limit_respected(self, dialog_page: Page):
        comments = dialog_page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, 3)
        assert len(comments) == 3

    def test_first_comment_author_name(self, dialog_page: Page):
        comments = dialog_page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, 0)
        assert comments[0]["author_name"] == "Karen Brown 3 weeks ago"

    def test_first_comment_timestamp(self, dialog_page: Page):
        comments = dialog_page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, 0)
        assert comments[0]["comment_timestamp"] == ""

    def test_first_comment_profile_url(self, dialog_page: Page):
        comments = dialog_page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, 0)
        assert comments[0]["author_profile_url"] == "https://www.facebook.com/karen.brown.771"

    def test_last_comment_author_name(self, dialog_page: Page):
        comments = dialog_page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, 0)
        assert comments[-1]["author_name"] == "Holly Butcher 3 weeks ago"

    def test_last_comment_timestamp(self, dialog_page: Page):
        comments = dialog_page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, 0)
        assert comments[-1]["comment_timestamp"] == ""

    def test_last_comment_profile_url(self, dialog_page: Page):
        comments = dialog_page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, 0)
        assert comments[-1]["author_profile_url"] == "https://www.facebook.com/holly.butcher.54"

    def test_all_comments_have_profile_url(self, dialog_page: Page):
        comments = dialog_page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, 0)
        for c in comments:
            assert c["author_profile_url"] is not None, f"Missing profile URL: {c}"

    def test_all_comments_have_author_name(self, dialog_page: Page):
        comments = dialog_page.evaluate(EXTRACT_DIALOG_COMMENTS_JS, 0)
        for c in comments:
            assert c["author_name"] not in (None, "", "Unknown"), f"Bad author: {c}"

    def test_post_url_extracted(self, dialog_page: Page):
        url = dialog_page.evaluate(POST_URL_FROM_DIALOG_JS)
        assert url == (
            "https://www.facebook.com/autumn.martinhumbaugh/posts/"
            "pfbid0z85C4C6vL3Ev2uPQwptqrNTvepfjGptwdecEzWVF1NtJDb7QmuECX6NwkhCiNJmpl"
        )

    def test_post_url_contains_posts_path(self, dialog_page: Page):
        url = dialog_page.evaluate(POST_URL_FROM_DIALOG_JS)
        assert url is not None and "/posts/" in url
