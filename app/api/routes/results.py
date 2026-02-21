from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from ...core.database import get_db
from ...services.scraper import ScraperService
from ...schemas.search_result import (
    SearchResultResponse,
    SearchResultList,
    SearchResultUpdate,
)
from ...models.search_result import SearchResult, ResultStatus

router = APIRouter(prefix="/results", tags=["results"])


@router.get("/", response_model=SearchResultList)
async def get_results(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[ResultStatus] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get search results with filters."""
    scraper = ScraperService(db)
    results = await scraper.get_results(
        skip=skip,
        limit=limit,
        status=status,
        keyword=keyword,
    )

    total = db.query(SearchResult).count()

    return SearchResultList(
        total=total,
        items=[SearchResultResponse.model_validate(r) for r in results],
    )


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
