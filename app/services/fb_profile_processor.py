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

logger = get_logger(__name__)


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
    post_url = link.get("post_url")
    post_date = link.get("post_date")
    if post_date is None or (isinstance(post_date, str) and not post_date.strip()):
        logger.info("Post has no date from feed (url=%s) — date extraction may have failed on this card", (link_url or "")[:80])

    try:
        if link_type == "group":
            logger.info("  Processing group post author...")
            await page.goto(link_url, wait_until="domcontentloaded", timeout=90000)
            await asyncio.sleep(random.uniform(2, 4))

            view_profile_link = await page.query_selector('a[aria-label="View profile"]')
            if not view_profile_link:
                logger.info("  'View profile' link not found, skipping")
                await page.close()
                return False

            profile_url = await view_profile_link.get_attribute("href")
            logger.info(f"  Found profile URL: {profile_url}")
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=90000)
            await asyncio.sleep(random.uniform(2, 4))
        else:
            profile_url = link_url
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=90000)
            await asyncio.sleep(random.uniform(2, 4))

        # -- Name extraction --
        name_selector = (
            "div.x1i10hfl.x1qjc9v5.xjbqb8w.xjqpnuy.xc5r6h4.xqeqjp1.x1phubyo"
            ".x13fuv20.x18b5jzi.x1q0q8m5.x1t7ytsu.x972fbf.x10w94by.x1qhh985"
            ".x14e42zd.x9f619.x1ypdohk.xdl72j9.x2lah0s.x3ct3a4.xdj266r.x14z9mp"
            ".xat24cr.x1lziwak.x2lwn1j.xeuugli.xexx8yu.xyri2b.x18d9i69.x1c1uobl"
            ".x1n2onr6.x16tdsg8.x1hl2dhg.xggy1nq.x1ja2u2z.x1t137rt.x1fmog5m"
            ".xu25z0z.x140muxe.xo1y3bh.x3nfvp2.x1q0g3np.x87ps6o.x1lku1pv.x1a2a7pz"
        )
        name_element = await page.query_selector(name_selector)
        actual_name = None
        if name_element:
            raw = await name_element.inner_text()
            if raw:
                actual_name = raw.replace("\xa0", " ").strip()

        if actual_name and actual_name.strip():
            final_name = actual_name
            logger.info(f"  Extracted name from profile: {final_name}")
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
                existing = db.query(SearchResult).filter(SearchResult.post_url == post_url).first() if post_url else None
                if existing:
                    existing.name = final_name
                    existing.location = location_text
                    existing.post_content = post_content
                    existing.post_date = post_date or existing.post_date
                    existing.profile_url = profile_url
                    existing.search_keyword = keyword
                    db.commit()
                    search_result = existing
                    logger.info(f"  Updated existing record (ID: {search_result.id})")
                else:
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
                        existing = db.query(SearchResult).filter(SearchResult.post_url == post_url).first()
                        if existing:
                            existing.name = final_name
                            existing.location = location_text
                            existing.post_content = post_content
                            existing.post_date = post_date or existing.post_date
                            existing.profile_url = profile_url
                            existing.search_keyword = keyword
                            db.commit()
                            search_result = existing
                            logger.info(f"  Updated existing record after conflict (ID: {search_result.id})")
                        else:
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
                                'a[href*="/posts/"], a[href*="/photo/"], a[href*="story_fbid"]'
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
                                await asyncio.sleep(random.uniform(2, 3))
                                count = await extract_comments(page, search_result.id, db, max_comments=0)
                                total_comments += count
                                if count > 0:
                                    logger.info(f"  Extracted {count} comments from this post")
                                await asyncio.sleep(random.uniform(1, 2))
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

                await page.close()
                return True
            except Exception as e:
                logger.error(f"  Failed to save to database: {e}")
                db.rollback()
                await page.close()
                return False
        else:
            logger.info("  Not a personal profile (group/page) — skipping")
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
