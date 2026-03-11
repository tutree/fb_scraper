from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import cast, String
from typing import Optional, List
from uuid import UUID

from ...core.database import get_db
from ...schemas.post_comment import (
    PostCommentResponse,
    CommentListResponse,
    AnalyzeCommentBatchRequest,
    AnalyzeCommentBatchResponse,
    AnalyzeCommentSingleResponse,
    AnalyzeCommentItem,
)
from ...models.post_comment import PostComment
from ...models.search_result import SearchResult, UserType
from ...services.gemini_classifier import GeminiClassifier

router = APIRouter(prefix="/comments", tags=["comments"])


def _format_comment_item(
    comment: PostComment,
    success: bool,
    message: str,
) -> AnalyzeCommentItem:
    return AnalyzeCommentItem(
        id=comment.id,
        success=success,
        message=message,
        user_type=comment.user_type.value if comment.user_type else None,
        confidence_score=comment.confidence_score,
        analyzed_at=comment.analyzed_at,
    )


async def _analyze_comment(
    comment: PostComment,
    classifier: GeminiClassifier,
    force_reanalyze: bool,
    post_context: str = "",
    search_keyword: str = "",
) -> AnalyzeCommentItem:
    if comment.user_type is not None and not force_reanalyze:
        return _format_comment_item(comment, True, "Skipped: already analyzed")

    if not comment.comment_text or not comment.comment_text.strip():
        comment.user_type = UserType.UNKNOWN
        comment.confidence_score = 0.0
        comment.analysis_message = "No comment text"
        comment.analyzed_at = datetime.now(timezone.utc)
        return _format_comment_item(comment, True, "Analyzed with fallback: no comment text")

    try:
        result = await classifier.classify_comment_user(
            comment_text=comment.comment_text,
            author_name=comment.author_name or "",
            post_context=post_context,
            search_keyword=search_keyword,
        )
        type_mapping = {
            "CUSTOMER": UserType.CUSTOMER,
            "TUTOR": UserType.TUTOR,
            "UNKNOWN": UserType.UNKNOWN,
        }
        comment.user_type = type_mapping.get(str(result.get("type", "UNKNOWN")).upper(), UserType.UNKNOWN)
        comment.confidence_score = max(0.0, min(1.0, float(result.get("confidence", 0.0))))
        comment.analysis_message = str(result.get("reason") or "")
        comment.analyzed_at = datetime.now(timezone.utc)
        return _format_comment_item(comment, True, "Analyzed successfully")
    except Exception as exc:
        return _format_comment_item(comment, False, f"Analysis failed: {exc}")


@router.get("", response_model=CommentListResponse)
async def list_comments(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_type: Optional[str] = Query(None, description="Filter by user_type: customer, tutor, unknown"),
    search_result_id: Optional[str] = Query(None, description="Filter by post/result ID"),
    analyzed: Optional[bool] = Query(
        None,
        description="Filter by analysis status: true (analyzed) or false (not analyzed)",
    ),
    db: Session = Depends(get_db),
):
    """List all comments with pagination and optional filters."""
    query = db.query(PostComment)
    if user_type:
        query = query.filter(cast(PostComment.user_type, String) == user_type)
    if search_result_id:
        query = query.filter(PostComment.search_result_id == search_result_id)
    if analyzed is True:
        query = query.filter(PostComment.analyzed_at.isnot(None))
    elif analyzed is False:
        query = query.filter(PostComment.analyzed_at.is_(None))
    total = query.count()
    comments = (
        query.order_by(PostComment.confidence_score.desc().nulls_last(), PostComment.scraped_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return CommentListResponse(
        total=total,
        items=[PostCommentResponse.model_validate(c) for c in comments],
    )


@router.post("/{comment_id}/analyze", response_model=AnalyzeCommentSingleResponse)
async def analyze_single_comment(
    comment_id: UUID,
    force_reanalyze: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Analyze a single comment author with Gemini and persist classification."""
    comment = db.query(PostComment).filter(PostComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    try:
        classifier = GeminiClassifier()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    post = db.query(SearchResult).filter(SearchResult.id == comment.search_result_id).first()
    post_context = post.post_content if post and post.post_content else ""
    search_keyword = post.search_keyword if post and post.search_keyword else ""

    item = await _analyze_comment(
        comment,
        classifier,
        force_reanalyze,
        post_context=post_context,
        search_keyword=search_keyword,
    )
    if item.success:
        db.commit()
        db.refresh(comment)
        item = _format_comment_item(comment, True, item.message)
    else:
        db.rollback()

    return AnalyzeCommentSingleResponse(item=item)


@router.post("/analyze/batch", response_model=AnalyzeCommentBatchResponse)
async def analyze_batch_comments(
    request: AnalyzeCommentBatchRequest,
    db: Session = Depends(get_db),
):
    """Analyze selected comments in batch using Gemini."""
    if not request.comment_ids:
        raise HTTPException(status_code=400, detail="comment_ids is required")

    try:
        classifier = GeminiClassifier()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    comment_map = {
        item.id: item
        for item in db.query(PostComment)
        .filter(PostComment.id.in_(request.comment_ids))
        .all()
    }
    search_result_ids = {c.search_result_id for c in comment_map.values()}
    result_map = {
        r.id: r
        for r in db.query(SearchResult).filter(SearchResult.id.in_(search_result_ids)).all()
    }

    items: List[AnalyzeCommentItem] = []
    for comment_id in request.comment_ids:
        comment = comment_map.get(comment_id)
        if not comment:
            items.append(
                AnalyzeCommentItem(
                    id=comment_id,
                    success=False,
                    message="Comment not found",
                )
            )
            continue
        post = result_map.get(comment.search_result_id)
        post_context = post.post_content if post and post.post_content else ""
        search_keyword = post.search_keyword if post and post.search_keyword else ""
        items.append(
            await _analyze_comment(
                comment,
                classifier,
                request.force_reanalyze,
                post_context=post_context,
                search_keyword=search_keyword,
            )
        )

    if any(item.success for item in items):
        db.commit()
        for item in items:
            refreshed = comment_map.get(item.id)
            if refreshed:
                db.refresh(refreshed)
    else:
        db.rollback()

    normalized_items: List[AnalyzeCommentItem] = []
    for item in items:
        comment = comment_map.get(item.id)
        if comment:
            normalized_items.append(_format_comment_item(comment, item.success, item.message))
        else:
            normalized_items.append(item)

    succeeded = sum(1 for item in normalized_items if item.success and item.message != "Skipped: already analyzed")
    skipped = sum(1 for item in normalized_items if item.success and item.message == "Skipped: already analyzed")
    failed = sum(1 for item in normalized_items if not item.success)

    return AnalyzeCommentBatchResponse(
        total=len(normalized_items),
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        items=normalized_items,
    )
