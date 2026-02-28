from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import cast, String
from typing import Optional, List

from ...core.database import get_db
from ...services.scraper import ScraperService
from ...schemas.search_result import (
    SearchResultResponse,
    SearchResultList,
    SearchResultUpdate,
)
from ...schemas.post_comment import PostCommentResponse
from ...models.search_result import SearchResult, ResultStatus
from ...models.post_comment import PostComment

router = APIRouter(prefix="/results", tags=["results"])


@router.get("/", response_model=SearchResultList)
async def get_results(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[ResultStatus] = None,
    keyword: Optional[str] = None,
    user_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get search results with filters."""
    query = db.query(SearchResult)
    
    if status:
        query = query.filter(SearchResult.status == status)
    if keyword:
        query = query.filter(SearchResult.search_keyword.ilike(f"%{keyword}%"))
    if user_type:
        query = query.filter(cast(SearchResult.user_type, String) == user_type)
    
    total = query.count()
    results = query.order_by(SearchResult.scraped_at.desc()).offset(skip).limit(limit).all()

    return SearchResultList(
        total=total,
        items=[SearchResultResponse.model_validate(r) for r in results],
    )


@router.get("/{result_id}/comments", response_model=List[PostCommentResponse])
async def get_result_comments(result_id: str, db: Session = Depends(get_db)):
    """Get comments for a specific search result."""
    result = db.query(SearchResult).filter(SearchResult.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    comments = db.query(PostComment).filter(PostComment.search_result_id == result_id).order_by(PostComment.scraped_at.desc()).all()
    return [PostCommentResponse.model_validate(c) for c in comments]


@router.get("/{result_id}", response_model=SearchResultResponse)
async def get_result(result_id: str, db: Session = Depends(get_db)):
    """Get a specific search result."""
    result = (
        db.query(SearchResult)
        .filter(SearchResult.id == result_id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return result


@router.patch("/{result_id}", response_model=SearchResultResponse)
async def update_result(
    result_id: str,
    update: SearchResultUpdate,
    db: Session = Depends(get_db),
):
    """Update a search result's status."""
    scraper = ScraperService(db)
    success = await scraper.update_result_status(result_id, update.status)

    if not success:
        raise HTTPException(status_code=404, detail="Result not found")

    result = (
        db.query(SearchResult)
        .filter(SearchResult.id == result_id)
        .first()
    )
    return result


@router.delete("/{result_id}")
async def delete_result(result_id: str, db: Session = Depends(get_db)):
    """Delete a search result."""
    result = (
        db.query(SearchResult)
        .filter(SearchResult.id == result_id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    db.delete(result)
    db.commit()

    return {"message": "Result deleted successfully"}
