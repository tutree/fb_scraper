from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import cast, String
from typing import Optional, List
from uuid import UUID

from ...core.database import get_db
from ...services.scraper import ScraperService
from ...services.gemini_classifier import GeminiClassifier
from ...schemas.search_result import (
    SearchResultResponse,
    SearchResultList,
    SearchResultUpdate,
    AnalyzeBatchRequest,
    AnalyzeBatchResponse,
    AnalyzeSingleResponse,
    AnalyzeResultItem,
)
from ...schemas.post_comment import PostCommentResponse
from ...models.search_result import SearchResult, ResultStatus, UserType
from ...models.post_comment import PostComment

router = APIRouter(prefix="/results", tags=["results"])


def _format_analyze_item(
    result: SearchResult,
    success: bool,
    message: str,
) -> AnalyzeResultItem:
    return AnalyzeResultItem(
        id=result.id,
        success=success,
        message=message,
        user_type=result.user_type.value if result.user_type else None,
        confidence_score=result.confidence_score,
        analyzed_at=result.analyzed_at,
    )


async def _analyze_search_result(
    result: SearchResult,
    classifier: GeminiClassifier,
    force_reanalyze: bool,
) -> AnalyzeResultItem:
    if result.user_type is not None and not force_reanalyze:
        return _format_analyze_item(
            result=result,
            success=True,
            message="Skipped: already analyzed",
        )

    if not result.post_content or not result.post_content.strip():
        result.user_type = UserType.UNKNOWN
        result.confidence_score = 0.0
        result.analysis_message = "No post content available"
        result.analyzed_at = datetime.now(timezone.utc)
        return _format_analyze_item(
            result=result,
            success=True,
            message="Analyzed with fallback: no post content",
        )

    try:
        analysis = await classifier.classify_user(
            post_content=result.post_content,
            user_name=result.name or "",
        )

        user_type_map = {
            "CUSTOMER": UserType.CUSTOMER,
            "TUTOR": UserType.TUTOR,
            "UNKNOWN": UserType.UNKNOWN,
        }
        result.user_type = user_type_map.get(
            str(analysis.get("type", "UNKNOWN")).upper(),
            UserType.UNKNOWN,
        )
        result.confidence_score = max(
            0.0,
            min(1.0, float(analysis.get("confidence", 0.0))),
        )
        result.analysis_message = str(analysis.get("reason") or "")
        result.analyzed_at = datetime.now(timezone.utc)

        return _format_analyze_item(
            result=result,
            success=True,
            message="Analyzed successfully",
        )
    except Exception as exc:
        return _format_analyze_item(
            result=result,
            success=False,
            message=f"Analysis failed: {exc}",
        )


@router.get("/", response_model=SearchResultList)
async def get_results(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[ResultStatus] = None,
    keyword: Optional[str] = None,
    user_type: Optional[str] = None,
    analyzed: Optional[bool] = Query(
        None,
        description="Filter by analysis status: true (analyzed) or false (not analyzed)",
    ),
    sort_by: Optional[str] = Query(
        "scraped_at",
        description="Sort field: scraped_at, post_date, confidence_score, analyzed_at, name, status",
    ),
    sort_order: Optional[str] = Query(
        "desc",
        description="Sort order: asc or desc",
    ),
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
    if analyzed is True:
        query = query.filter(SearchResult.analyzed_at.isnot(None))
    elif analyzed is False:
        query = query.filter(SearchResult.analyzed_at.is_(None))

    sort_map = {
        "scraped_at": SearchResult.scraped_at,
        "post_date": SearchResult.post_date,
        "confidence_score": SearchResult.confidence_score,
        "analyzed_at": SearchResult.analyzed_at,
        "name": SearchResult.name,
        "status": SearchResult.status,
    }
    sort_col = sort_map.get((sort_by or "scraped_at").strip().lower(), SearchResult.scraped_at)
    order = (sort_order or "desc").strip().lower()
    if order == "asc":
        query = query.order_by(sort_col.asc().nullslast())
    else:
        query = query.order_by(sort_col.desc().nullslast())

    total = query.count()
    results = query.offset(skip).limit(limit).all()

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


@router.post("/{result_id}/analyze", response_model=AnalyzeSingleResponse)
async def analyze_single_result(
    result_id: UUID,
    force_reanalyze: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Analyze a single result using Gemini and persist the classification."""
    result = db.query(SearchResult).filter(SearchResult.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    try:
        classifier = GeminiClassifier()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    analyzed_item = await _analyze_search_result(
        result=result,
        classifier=classifier,
        force_reanalyze=force_reanalyze,
    )

    if analyzed_item.success:
        db.commit()
        db.refresh(result)
        analyzed_item = _format_analyze_item(
            result=result,
            success=True,
            message=analyzed_item.message,
        )
    else:
        db.rollback()

    return AnalyzeSingleResponse(item=analyzed_item)


@router.post("/analyze/batch", response_model=AnalyzeBatchResponse)
async def analyze_batch_results(
    request: AnalyzeBatchRequest,
    db: Session = Depends(get_db),
):
    """Analyze selected results in batch using Gemini."""
    if not request.result_ids:
        raise HTTPException(status_code=400, detail="result_ids is required")

    try:
        classifier = GeminiClassifier()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result_map = {
        item.id: item
        for item in db.query(SearchResult)
        .filter(SearchResult.id.in_(request.result_ids))
        .all()
    }

    items: List[AnalyzeResultItem] = []

    for result_id in request.result_ids:
        result = result_map.get(result_id)
        if not result:
            items.append(
                AnalyzeResultItem(
                    id=result_id,
                    success=False,
                    message="Result not found",
                )
            )
            continue

        analyzed_item = await _analyze_search_result(
            result=result,
            classifier=classifier,
            force_reanalyze=request.force_reanalyze,
        )
        items.append(analyzed_item)

    if any(item.success for item in items):
        db.commit()
        for item in items:
            refreshed = result_map.get(item.id)
            if refreshed:
                db.refresh(refreshed)
    else:
        db.rollback()

    normalized_items: List[AnalyzeResultItem] = []
    for item in items:
        result = result_map.get(item.id)
        if result:
            normalized_items.append(
                _format_analyze_item(
                    result=result,
                    success=item.success,
                    message=item.message,
                )
            )
        else:
            normalized_items.append(item)

    succeeded = sum(1 for item in normalized_items if item.success and item.message != "Skipped: already analyzed")
    skipped = sum(1 for item in normalized_items if item.success and item.message == "Skipped: already analyzed")
    failed = sum(1 for item in normalized_items if not item.success)

    return AnalyzeBatchResponse(
        total=len(normalized_items),
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        items=normalized_items,
    )


from pydantic import BaseModel

class BulkDeleteRequest(BaseModel):
    ids: List[str]

@router.post("/bulk-delete")
async def bulk_delete_results(request: BulkDeleteRequest, db: Session = Depends(get_db)):
    """Bulk delete search results."""
    # SQLite/PostgreSQL supports deleting with in_
    deleted_count = db.query(SearchResult).filter(SearchResult.id.in_(request.ids)).delete(synchronize_session=False)
    db.commit()
    return {"message": f"{deleted_count} results deleted successfully"}

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
