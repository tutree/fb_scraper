"""
Single-profile visit, extraction, and database persistence.
"""
import asyncio
import random
import re
from typing import Dict, List, Optional

from playwright.async_api import Page
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..core.config import settings
from ..core.logging_config import get_logger
from ..models.post_comment import PostComment
from ..models.search_result import ResultStatus, SearchResult
from ..utils.validators import clean_facebook_location, clean_facebook_name, clean_facebook_post_content
from .fb_comment_handler import extract_comments
from .fb_post_url import canonicalize_post_url

logger = get_logger(__name__)


def _update_existing_result(
    existing: "SearchResult",
    name: str,
    location: str | None,
    post_content: str | None,
    post_date: str | None,
    profile_url: str | None,
    keyword: str,
    db: "Session",
) -> None:
    """Update an existing SearchResult with freshly scraped attributes (skip comments)."""
    changed = []
    if name and name != "Unknown" and existing.name != name:
        existing.name = name
        changed.append("name")
    if location and not existing.location:
        existing.location = location
        changed.append("location")
    if post_content and (not existing.post_content or len(post_content) > len(existing.post_content or "")):
        existing.post_content = post_content
        changed.append("post_content")
    if post_date and not existing.post_date:
        existing.post_date = post_date
        changed.append("post_date")
    if profile_url and not existing.profile_url:
        existing.profile_url = profile_url
        changed.append("profile_url")

    if changed:
        try:
            db.commit()
            logger.info(
                "  Duplicate post_url — updated existing (ID: %s, fields: %s)",
                existing.id,
                ", ".join(changed),
            )
        except Exception as e:
            db.rollback()
            logger.warning("  Failed to update existing record %s: %s", existing.id, e)
    else:
        logger.info("  Duplicate post_url — no new data to update (existing ID: %s)", existing.id)


async def process_single_profile(
    page: Page,
    link: Dict,
    keyword: str,
    idx: int,
    total: int,
    db: Session,
    comments_data: Optional[List[Dict]] = None,
) -> bool:
    """
    Visit a single profile, determine if it's a personal account, and persist to the DB.
    If *comments_data* is provided (scraped from the search results dialog before navigation),
    those comments are saved along with the new SearchResult record.
    Returns True if a PENDING record was saved successfully.
    """
    link_url = link["url"]
    name = link["text"]
    link_type = link["type"]

    logger.info(f"[{idx}/{total}] Checking {link_type} link: {name}")
    logger.info(f"  URL: {link_url}")

    post_content = clean_facebook_post_content(link.get("post_content"))
    post_url = canonicalize_post_url(link.get("post_url"))
    post_date = link.get("post_date")
    if post_date is None or (isinstance(post_date, str) and not post_date.strip()):
        logger.info("Post has no date from feed (url=%s) — date extraction may have failed on this card", (link_url or "")[:80])

    try:
        if link_type == "group":
            logger.info("  Processing group post author...")
            await page.goto(link_url, wait_until="domcontentloaded", timeout=90000)
            await asyncio.sleep(random.uniform(1.5, 2.5))

            view_profile_link = await page.query_selector('a[aria-label="View profile"]')
            if not view_profile_link:
                logger.info("  'View profile' link not found, skipping")
                await page.close()
                return False

            profile_url = await view_profile_link.get_attribute("href")
            logger.info(f"  Found profile URL: {profile_url}")
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=90000)
            await asyncio.sleep(random.uniform(1.5, 2.5))
        else:
            profile_url = link_url
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=90000)
            await asyncio.sleep(random.uniform(1.5, 2.5))

        # -- Name extraction --
        # Priority order:
        #   1. div[data-ad-rendering-role="profile_name"] → link or h3  (search-result cards)
        #   2. Profile cover h1 (direct profile page visit)
        #   3. og:title meta tag (most reliable on direct visits; strip "| Facebook")
        #   4. document.title (same strip)
        #   5. First h1/h2/h3 on page
        name_pick = await page.evaluate(
            """
            () => {
                const clean = (s) => (s || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
                const UI_NOISE = /^(Follow|Add friend|Add Friend|Message|See options|Like|Comment|Share|Reels|Photos|Videos|About|Friends|More)$/i;
                const FB_SUFFIX = /\\s*[|·]\\s*(Facebook|FB)\\s*$/i;

                const normalizeCandidate = (text) => {
                    const t = clean(text).replace(FB_SUFFIX, '').trim();
                    if (!t || UI_NOISE.test(t)) return null;
                    return t;
                };

                // 1. Search-result card block
                const profileNameRoot = document.querySelector('div[data-ad-rendering-role="profile_name"]');
                if (profileNameRoot) {
                    const link = profileNameRoot.querySelector('a[href*="facebook.com"]');
                    const lt = normalizeCandidate(link?.textContent);
                    if (lt) return { name: lt, source: 'profile_name_link' };

                    const h3 = profileNameRoot.querySelector('h3');
                    const h3t = normalizeCandidate(h3?.textContent);
                    if (h3t) return { name: h3t.split(/\\s+[·|]\\s+/)[0].trim(), source: 'profile_name_h3' };
                }

                // 2. Cover/intro h1 on a direct profile page.
                //    The actual name is often inside h1 > span > div[role="button"] as a text node,
                //    NOT spread across inner decorative divs like div[role="none"].
                //    Extract only the raw text-node content from the name button, then fall back to
                //    the full h1 textContent as a last resort.
                const h1 = document.querySelector('h1');
                if (h1) {
                    // Preferred: grab every text node directly inside div[role="button"] in h1.
                    const nameBtn = h1.querySelector('div[role="button"]') || h1;
                    let rawText = '';
                    nameBtn.childNodes.forEach(node => {
                        // Only real text nodes and non-decorative spans (not role="none" divs)
                        if (node.nodeType === Node.TEXT_NODE) {
                            rawText += node.textContent;
                        } else if (node.nodeName === 'SPAN' && !node.getAttribute('role') && !node.getAttribute('data-visualcompletion')) {
                            rawText += node.textContent;
                        }
                    });
                    const t = normalizeCandidate(rawText) || normalizeCandidate(h1.textContent);
                    if (t) return { name: t, source: 'profile_h1' };
                }

                // 3. og:title meta tag — most stable across profile page variants
                const ogTitle = document.querySelector('meta[property="og:title"]');
                if (ogTitle) {
                    const t = normalizeCandidate(ogTitle.getAttribute('content'));
                    if (t) return { name: t, source: 'og_title' };
                }

                // 4. <title> tag (format: "Name | Facebook")
                const titleTag = normalizeCandidate(document.title);
                if (titleTag) return { name: titleTag, source: 'title_tag' };

                // 5. First h2/h3
                const heading = document.querySelector('h2, h3');
                const ht = normalizeCandidate(heading?.textContent);
                if (ht) return { name: ht.split(/\\s+[·|]\\s+/)[0].trim(), source: 'page_heading' };

                return { name: null, source: null };
            }
            """
        )

        actual_name = None
        name_source = None
        if isinstance(name_pick, dict):
            actual_name = name_pick.get("name")
            name_source = name_pick.get("source")

        if actual_name and str(actual_name).strip():
            final_name = str(actual_name).strip()
            logger.info(
                "  Extracted name from profile (source=%s): %s",
                name_source or "?",
                final_name,
            )
        elif link_type == "group" and name and name.strip():
            final_name = name
            logger.info(f"  Using name from group post: {final_name}")
        else:
            url_match = re.search(r"facebook\.com/([^/?]+)", profile_url)
            if url_match:
                username = url_match.group(1)
                if username != "profile.php":
                    final_name = username.replace(".", " ").replace("_", " ").title()
                    logger.info(f"  Extracted username from URL: {final_name}")
                elif name and name.strip():
                    final_name = name
                    logger.info(f"  Using link text: {final_name}")
                else:
                    final_name = "Unknown"
            elif name and name.strip():
                final_name = name
            else:
                final_name = "Unknown"

        # -- Location extraction --
        location_info = await page.evaluate(
            """
            () => {
                const locations = [];
                for (const span of document.querySelectorAll('span')) {
                    const text = span.textContent.trim();
                    if (
                        text.startsWith('From ') ||
                        text.startsWith('Lives in ') ||
                        text.startsWith('Moved to ')
                    ) {
                        locations.push(text);
                    }
                }
                return { found: locations.length > 0, locations };
            }
            """
        )

        location_span_selector = (
            "span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.x1xmvt09.x6prxxf"
            ".xvq8zen.x1s688f.xzsf02u"
        )
        location_elements = await page.query_selector_all(location_span_selector)
        specific_locations = []
        for elem in location_elements:
            text = (await elem.inner_text()).strip()
            if text and (
                text.startswith("From ")
                or text.startswith("Lives in ")
                or text.startswith("Moved to ")
            ):
                specific_locations.append(text)

        all_locations = list(location_info.get("locations", [])) + specific_locations
        seen_locs: set = set()
        unique_locations = []
        for loc in all_locations:
            if loc not in seen_locs:
                unique_locations.append(loc)
                seen_locs.add(loc)

        location_text = clean_facebook_location(", ".join(unique_locations)) if unique_locations else None

        # -- Personal-profile check --
        is_personal_profile = await page.evaluate(
            """
            () => {
                const text = document.body.innerText || '';
                const html = document.body.innerHTML || '';
                if (
                    html.includes('joinButton') ||
                    text.includes('Join group') ||
                    text.includes('Join Group') ||
                    html.includes('group_type')
                ) return false;
                if (
                    text.includes('Like Page') ||
                    text.includes('Suggest Page') ||
                    text.includes('Follow Page') ||
                    text.includes('Page transparency') ||
                    text.includes('likes this') ||
                    text.includes('people like this') ||
                    text.includes('Page ·')
                ) return false;
                const hasAddFriend = !!document.querySelector(
                    '[aria-label="Add friend"], [aria-label="Add Friend"]'
                );
                const hasFriends = !!document.querySelector(
                    '[aria-label="Friends"], [aria-label="Remove friend"], [aria-label="Edit friend list"]'
                );
                const hasMutualFriendsText = /mutual friends?/i.test(text);
                return hasAddFriend || hasFriends || hasMutualFriendsText;
            }
            """
        )

        final_name = clean_facebook_name(final_name) or final_name or "Unknown"

        if is_personal_profile:
            if location_text:
                logger.info(f"  Personal profile detected. Location: {location_text}")
            else:
                logger.info("  Personal profile detected (no public location)")

            try:
                if post_url:
                    existing = (
                        db.query(SearchResult)
                        .filter(
                            SearchResult.post_url == post_url,
                            SearchResult.archived.is_(False),
                        )
                        .first()
                    )
                    if existing:
                        _update_existing_result(
                            existing, final_name, location_text, post_content,
                            post_date, profile_url, keyword, db,
                        )
                        search_result = existing
                        # Run Groq analysis even on updated duplicate rows
                        if (settings.GROQ_API_KEY or "").strip() and existing.analyzed_at is None:
                            try:
                                from .groq_analyzer import apply_immediate_groq_analysis
                                await apply_immediate_groq_analysis(db, existing.id)
                            except Exception as groq_exc:
                                logger.warning("  Immediate Groq analysis failed (dup update): %s", groq_exc)
                        await page.close()
                        return True

                search_result = SearchResult(
                    name=final_name,
                    location=location_text,
                    post_content=post_content,
                    post_url=post_url,
                    post_date=post_date,
                    profile_url=profile_url,
                    search_keyword=keyword,
                    status=ResultStatus.PENDING,
                )
                db.add(search_result)
                try:
                    db.commit()
                    logger.info(f"  Saved to database (ID: {search_result.id})")
                except IntegrityError:
                    db.rollback()
                    if post_url:
                        existing = (
                            db.query(SearchResult)
                            .filter(
                                SearchResult.post_url == post_url,
                                SearchResult.archived.is_(False),
                            )
                            .first()
                        )
                        if existing:
                            _update_existing_result(
                                existing, final_name, location_text, post_content,
                                post_date, profile_url, keyword, db,
                            )
                            # Run Groq on the recovered row too
                            if (settings.GROQ_API_KEY or "").strip() and existing.analyzed_at is None:
                                try:
                                    from .groq_analyzer import apply_immediate_groq_analysis
                                    await apply_immediate_groq_analysis(db, existing.id)
                                except Exception as groq_exc:
                                    logger.warning("  Immediate Groq analysis failed (integrity dup): %s", groq_exc)
                            await page.close()
                            return True
                    raise
                if comments_data:
                    try:
                        for c in comments_data:
                            pc = PostComment(
                                search_result_id=search_result.id,
                                author_name=c.get("author_name"),
                                author_profile_url=c.get("author_profile_url"),
                                comment_text=c.get("comment_text"),
                                comment_timestamp=c.get("comment_timestamp"),
                            )
                            db.add(pc)
                        db.commit()
                        logger.info(f"  Saved {len(comments_data)} comments from search results dialog")
                    except Exception as e:
                        logger.warning(f"  Failed to save dialog comments: {e}")
                        db.rollback()

                # Extract comments from recent profile posts
                try:
                    logger.info("  Extracting comments from recent posts on profile...")
                    recent_posts = await page.evaluate(
                        """
                        () => {
                            const postLinks = [];
                            const links = document.querySelectorAll(
                                'a[href*="/posts/pfbid"], a[href*="/posts/"], a[href*="/photo/"], a[href*="story_fbid"]'
                            );
                            for (const link of links) {
                                if (postLinks.length >= 3) break;
                                const href = link.href;
                                if (href && !postLinks.includes(href)) postLinks.push(href);
                            }
                            return postLinks;
                        }
                        """
                    )

                    if recent_posts:
                        logger.info(f"  Found {len(recent_posts)} recent posts, extracting comments...")
                        total_comments = 0
                        for post_link in recent_posts[:2]:
                            try:
                                logger.info(f"  Visiting post: {post_link[:80]}...")
                                await page.goto(post_link, wait_until="commit", timeout=30000)
                                await asyncio.sleep(random.uniform(1, 2))
                                count = await extract_comments(page, search_result.id, db, max_comments=0)
                                total_comments += count
                                if count > 0:
                                    logger.info(f"  Extracted {count} comments from this post")
                                await asyncio.sleep(random.uniform(0.5, 1))
                            except Exception as e:
                                logger.warning(f"  Could not extract comments from post: {e}")

                        if total_comments > 0:
                            logger.info(f"  Total comments extracted: {total_comments}")
                        else:
                            logger.info("  No comments found in recent posts")
                    else:
                        logger.info("  No recent posts found on profile")
                except Exception as e:
                    logger.warning(f"  Could not extract comments from profile: {e}")

                # Run Groq combined post+comments analysis immediately after all comments are saved
                if (settings.GROQ_API_KEY or "").strip():
                    try:
                        from .groq_analyzer import apply_immediate_groq_analysis
                        logger.info("  Running immediate Groq analysis for %s...", search_result.id)
                        await apply_immediate_groq_analysis(db, search_result.id)
                    except Exception as groq_exc:
                        logger.warning("  Immediate Groq analysis failed: %s", groq_exc)
                else:
                    logger.info("  Skipping immediate Groq analysis — GROQ_API_KEY not set")

                await page.close()
                return True
            except Exception as e:
                logger.error(f"  Failed to save to database: {e}")
                db.rollback()
                await page.close()
                return False
        else:
            logger.info("  Not a personal profile (group/page) — skipping")
            if post_url:
                existing = (
                    db.query(SearchResult)
                    .filter(
                        SearchResult.post_url == post_url,
                        SearchResult.archived.is_(False),
                    )
                    .first()
                )
                if existing:
                    logger.info(f"  Duplicate post_url for non-personal — skipping (ID: {existing.id})")
                    await page.close()
                    return False
            if comments_data:
                try:
                    search_result = SearchResult(
                        name=final_name or "Unknown",
                        location=location_text,
                        post_content=post_content,
                        post_url=post_url,
                        post_date=post_date,
                        profile_url=profile_url,
                        search_keyword=keyword,
                        status=ResultStatus.INVALID,
                    )
                    db.add(search_result)
                    db.commit()
                    logger.info(
                        f"  Saved as INVALID (ID: {search_result.id}) to store {len(comments_data)} comments"
                    )
                    for c in comments_data:
                        pc = PostComment(
                            search_result_id=search_result.id,
                            author_name=c.get("author_name"),
                            author_profile_url=c.get("author_profile_url"),
                            comment_text=c.get("comment_text"),
                            comment_timestamp=c.get("comment_timestamp"),
                        )
                        db.add(pc)
                    db.commit()
                    logger.info(f"  Saved {len(comments_data)} comments")
                    if (settings.GROQ_API_KEY or "").strip():
                        try:
                            from .groq_analyzer import apply_immediate_groq_analysis

                            await apply_immediate_groq_analysis(db, search_result.id)
                        except Exception as groq_exc:
                            logger.warning("  Immediate Groq analysis failed: %s", groq_exc)
                except Exception as e:
                    logger.warning(f"  Failed to save skipped profile + comments: {e}")
                    db.rollback()
            await page.close()
            return False

    except Exception as e:
        logger.error(f"  Error checking profile: {e}")
        try:
            await page.close()
        except Exception:
            pass
        return False
