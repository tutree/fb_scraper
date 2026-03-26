"""
Immediate combined analysis: geo filter → post classification → comment classification (Groq).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import asc
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.logging_config import get_logger
from ..models.post_comment import PostComment
from ..models.search_result import SearchResult, UserType
from ..utils.validators import (
    clean_facebook_location,
    clean_facebook_name,
    clean_facebook_post_content,
    is_enrichable,
    parse_facebook_date,
)
from .classification_prompts import (
    COMMENT_AUTHOR_STRICT_RULES,
    POST_AUTHOR_STRICT_RULES,
)
from .groq_client import groq_chat_json

logger = get_logger(__name__)

_TYPE_MAP = {
    "CUSTOMER": UserType.CUSTOMER,
    "TUTOR": UserType.TUTOR,
    "UNKNOWN": UserType.UNKNOWN,
}


def _norm_user_type(raw: Any) -> UserType:
    return _TYPE_MAP.get(str(raw or "").upper().strip(), UserType.UNKNOWN)


def _clamp_confidence(x: Any) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


async def _classify_geo_groq(
    location: str,
    post_content: str,
    user_name: str,
) -> Dict[str, Any]:
    """
    Determine whether this post is from a US-based user.

    Strategy:
      - If a location string is present → classify by location.
      - If no location → classify by post language / content signals.
      - If neither → assume US (benefit of the doubt, low confidence).

    Returns: {"is_us": bool, "confidence": float, "reason": str}
    """
    location = (location or "").strip()
    post_content = clean_facebook_post_content(post_content) or ""

    if location:
        prompt = f"""You are a geographic classifier. Given a Facebook user's location string, determine whether they are in the United States.

Location: {location}
User: {user_name or "Unknown"}

Rules:
- US city, state, territory, or zip code → is_us = true
- Any country outside the US (Philippines, Nigeria, India, UK, Canada, Pakistan, Australia, etc.) → is_us = false
- Ambiguous city name that exists in multiple countries: use post content for clues if provided
{f'Post content (context only): {post_content[:300]}' if post_content else ''}

Also: if the location or post content explicitly mentions a more specific US location (e.g. city + state), set extracted_location to that. Otherwise set extracted_location to null.

Return ONLY valid JSON (no markdown):
{{"is_us": true, "confidence": 0.95, "reason": "Location is in Texas, USA", "extracted_location": null}}"""

    elif post_content.strip():
        prompt = f"""You are a language and geographic classifier. This Facebook post has NO location. Determine if it is from a US-based English-speaking user based on language and content signals.

Post content: {post_content[:600]}
User: {user_name or "Unknown"}

Rules:
- Written in English → is_us = true (likely US-based)
- Written in Tagalog, Hindi, Urdu, French, Arabic, Spanish (non-US context), or any non-English language → is_us = false
- Predominantly English with minor code-switching → is_us = true
- Mentions non-US currencies (PHP, INR, GBP, AED, etc.) or clearly non-US locations → is_us = false
- Short English post with no geographic clues → is_us = true (benefit of the doubt)

Also: if the post explicitly mentions a US city, state, or region (e.g. "in Austin TX", "near Dallas", "Los Angeles area"), extract it as extracted_location. Otherwise set extracted_location to null.

Return ONLY valid JSON (no markdown):
{{"is_us": true, "confidence": 0.8, "reason": "Post is in English with no non-US indicators", "extracted_location": "Austin, TX"}}"""

    else:
        return {"is_us": True, "confidence": 0.3, "reason": "No location or content to classify"}

    data = await groq_chat_json(prompt)
    return {
        "is_us": bool(data.get("is_us", True)),
        "confidence": _clamp_confidence(data.get("confidence", 0.5)),
        "reason": str(data.get("reason") or ""),
        "extracted_location": data.get("extracted_location") or None,
    }


async def _classify_post_groq(post_content: str, user_name: str) -> Dict[str, Any]:
    post_content = clean_facebook_post_content(post_content) or ""
    if not post_content.strip():
        return {
            "type": "UNKNOWN",
            "confidence": 0.0,
            "reason": "No post content available",
        }

    prompt = f"""You are analyzing a Facebook post scraped from a search results page. The raw text may contain Facebook UI artifacts ("Facebook", "Like", "Comment", "Share", reaction counts, timestamps). Extract only the real user-written message; ignore UI noise.

User: {user_name if user_name else "Unknown"}
Raw scraped text: {post_content}

Classify the POST AUTHOR using these rules:

{POST_AUTHOR_STRICT_RULES}

Return ONLY valid JSON (no markdown). type must be CUSTOMER, TUTOR, or UNKNOWN. confidence 0.0–1.0. reason must cite explicit evidence from the post or explain why UNKNOWN:
{{"type": "UNKNOWN", "confidence": 0.6, "reason": "..."}}"""

    data = await groq_chat_json(prompt)
    data["type"] = str(data.get("type", "UNKNOWN")).upper()
    data["confidence"] = _clamp_confidence(data.get("confidence"))
    data["reason"] = str(data.get("reason") or "")
    return data


async def _classify_comments_groq(
    post_result: Dict[str, Any],
    cleaned_post: str,
    search_keyword: str,
    comments: List[Tuple[Any, Optional[str], Optional[str]]],
) -> List[Dict[str, Any]]:
    if not comments:
        return []

    lines: List[str] = []
    for i, (_cid, author, text) in enumerate(comments):
        lines.append(f'{i}. author={author or "Unknown"} | text={text or ""}')

    prompt = f"""You are analyzing Facebook comments. The post was already classified; use that plus the post text as context.

POST AUTHOR CLASSIFICATION: {post_result.get("type", "UNKNOWN")}
Reason: {post_result.get("reason", "")}
Confidence: {post_result.get("confidence", 0)}

Cleaned post text (may omit UI noise):
{cleaned_post[:1800]}

Search keyword that surfaced this post: {search_keyword or "(none)"}

COMMENTS (index is stable — you must output one classification per index):
{chr(10).join(lines)}

For EACH comment, classify the COMMENT AUTHOR using the rules below.

{COMMENT_AUTHOR_STRICT_RULES}

Return ONLY valid JSON (no markdown):
{{"comments": [{{"index": 0, "type": "UNKNOWN", "confidence": 0.5, "reason": "brief"}}, ...]}}

You MUST include exactly {len(comments)} objects with index 0 through {len(comments) - 1}."""

    data = await groq_chat_json(prompt)
    raw_list = data.get("comments")
    if not isinstance(raw_list, list):
        return []

    by_index: Dict[int, Dict[str, Any]] = {}
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        by_index[idx] = item

    out: List[Dict[str, Any]] = []
    for i in range(len(comments)):
        item = by_index.get(i, {})
        out.append(
            {
                "index": i,
                "type": str(item.get("type", "UNKNOWN")).upper(),
                "confidence": _clamp_confidence(item.get("confidence")),
                "reason": str(item.get("reason") or ""),
            }
        )
    return out


async def analyze_post_then_comments(
    post_content: str,
    user_name: str,
    search_keyword: str,
    comments: List[Tuple[Any, Optional[str], Optional[str]]],
) -> Dict[str, Any]:
    """
    Run post classification, then comment classification with post context.

    comments: list of (comment_id, author_name, comment_text) in DB order.
    Returns: {"post": {type, confidence, reason}, "comments": [{index, type, confidence, reason}, ...]}
    """
    cleaned = clean_facebook_post_content(post_content) or ""
    post_result = await _classify_post_groq(post_content, user_name)

    if post_result.get("type") == "CUSTOMER":
        return {"post": post_result, "comments": []}

    comment_results = await _classify_comments_groq(
        post_result, cleaned, search_keyword, comments
    )
    return {"post": post_result, "comments": comment_results}


async def apply_immediate_groq_analysis(db: Session, search_result_id: UUID) -> None:
    """
    Geo-filter → post classification → comment classification, all via Groq.

    Steps:
      1. Geo check: if not US-based → delete result + all comments, done.
      2. Post classification.
      3. If CUSTOMER → delete comments, done.
      4. Comment classification with post context.
    """
    if not (settings.GROQ_API_KEY or "").strip():
        return

    result = (
        db.query(SearchResult)
        .filter(SearchResult.id == search_result_id, SearchResult.archived.is_(False))
        .first()
    )
    if not result:
        return

    if result.name:
        cn = clean_facebook_name(result.name)
        if cn and cn != result.name:
            result.name = cn
    if result.location:
        cl = clean_facebook_location(result.location)
        if cl and cl != result.location:
            result.location = cl

    short_id = str(search_result_id)[:8]
    logger.info(
        "Groq analysis starting — id=%s name=%r location=%r",
        short_id,
        result.name or "",
        result.location or "",
    )

    try:
        # ── Step 1: Geo classification ────────────────────────────────────────
        logger.info("Groq geo classification running — id=%s", short_id)
        geo = await _classify_geo_groq(
            result.location or "",
            result.post_content or "",
            result.name or "",
        )
        logger.info(
            "Groq geo result — id=%s is_us=%s confidence=%.2f reason=%r",
            short_id,
            geo["is_us"],
            geo["confidence"],
            geo["reason"],
        )

        if not geo["is_us"]:
            deleted_comments = (
                db.query(PostComment)
                .filter(PostComment.search_result_id == result.id)
                .delete(synchronize_session=False)
            )
            db.delete(result)
            db.commit()
            logger.info(
                "Groq geo: non-US — deleted result + %d comments — id=%s (%s)",
                deleted_comments,
                short_id,
                geo["reason"],
            )
            return

        # Mark geo as checked so the background geo-filter job skips this row
        result.is_us = True
        result.geo_filtered_at = datetime.now(timezone.utc)

        # If the profile has no location but the post text reveals a US one, use it
        extracted_loc = geo.get("extracted_location")
        if extracted_loc and isinstance(extracted_loc, str) and extracted_loc.strip():
            if not (result.location or "").strip():
                result.location = extracted_loc.strip()
                logger.info(
                    "Groq geo: extracted location from post — id=%s location=%r",
                    short_id,
                    result.location,
                )

        # ── Step 2: Load comments ─────────────────────────────────────────────
        rows = (
            db.query(PostComment)
            .filter(
                PostComment.search_result_id == search_result_id,
                PostComment.archived.is_(False),
            )
            .order_by(asc(PostComment.scraped_at), asc(PostComment.id))
            .all()
        )
        triples = [(r.id, r.author_name, r.comment_text) for r in rows]

        # ── Step 3: Post + comment classification ─────────────────────────────
        logger.info(
            "Groq post+comment classification running — id=%s comments=%d",
            short_id,
            len(triples),
        )
        bundle = await analyze_post_then_comments(
            result.post_content or "",
            result.name or "",
            result.search_keyword or "",
            triples,
        )

    except Exception as exc:
        # Any Groq failure (rate-limit, network, parse error) — leave analyzed_at
        # and geo_filtered_at as NULL so the background jobs will retry this row.
        logger.warning(
            "Groq analysis failed for id=%s — will be retried by background job: %s",
            short_id,
            exc,
        )
        db.rollback()
        return

    pr = bundle.get("post") or {}
    result.user_type = _norm_user_type(pr.get("type"))
    result.confidence_score = _clamp_confidence(pr.get("confidence"))
    result.analysis_message = str(pr.get("reason") or "")
    result.analyzed_at = datetime.now(timezone.utc)
    result.enrichable = is_enrichable(result.name, result.location)

    if result.post_date and not result.post_date_timestamp:
        parsed_ts = parse_facebook_date(result.post_date)
        if parsed_ts:
            result.post_date_timestamp = parsed_ts

    if result.user_type == UserType.CUSTOMER:
        deleted = (
            db.query(PostComment)
            .filter(
                PostComment.search_result_id == result.id,
                PostComment.archived.is_(False),
            )
            .delete(synchronize_session=False)
        )
        if deleted:
            logger.info(
                "Groq: deleted %d comments from CUSTOMER post — id=%s",
                deleted,
                short_id,
            )
        db.commit()
        logger.info(
            "Groq analysis saved — id=%s post=%s (CUSTOMER, no comments classified)",
            short_id,
            result.user_type.value if result.user_type else None,
        )
        return

    fresh_rows = (
        db.query(PostComment)
        .filter(
            PostComment.search_result_id == search_result_id,
            PostComment.archived.is_(False),
        )
        .order_by(asc(PostComment.scraped_at), asc(PostComment.id))
        .all()
    )

    comment_results = bundle.get("comments") or []
    for i, row in enumerate(fresh_rows):
        item = comment_results[i] if i < len(comment_results) else {}
        if not row.comment_text or not str(row.comment_text).strip():
            row.user_type = UserType.UNKNOWN
            row.confidence_score = 0.0
            row.analysis_message = "No comment text"
        else:
            row.user_type = _norm_user_type(item.get("type"))
            row.confidence_score = _clamp_confidence(item.get("confidence"))
            row.analysis_message = str(item.get("reason") or "")
        row.analyzed_at = datetime.now(timezone.utc)

    db.commit()
    logger.info(
        "Groq analysis saved — id=%s post=%s %d comments classified",
        short_id,
        result.user_type.value if result.user_type else None,
        len(fresh_rows),
    )
