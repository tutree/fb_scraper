from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import cast, String
from typing import Optional

from ...core.database import get_db
from ...schemas.post_comment import PostCommentResponse, CommentListResponse
from ...models.post_comment import PostComment

router = APIRouter(prefix="/comments", tags=["comments"])


@router.get("", response_model=CommentListResponse)
async def list_comments(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_type: Optional[str] = Query(None, description="Filter by user_type: customer, tutor, unknown"),
    search_result_id: Optional[str] = Query(None, description="Filter by post/result ID"),
    db: Session = Depends(get_db),
):
    """List all comments with pagination and optional filters."""
    query = db.query(PostComment)
    if user_type:
        query = query.filter(cast(PostComment.user_type, String) == user_type)
    if search_result_id:
        query = query.filter(PostComment.search_result_id == search_result_id)
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
