from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, String

from ...core.database import get_db
from ...models.search_result import SearchResult, ResultStatus, UserType

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Get dashboard statistics."""
    total = db.query(SearchResult).count()
    
    customers = db.query(SearchResult).filter(
        cast(SearchResult.user_type, String) == "customer"
    ).count()
    
    tutors = db.query(SearchResult).filter(
        cast(SearchResult.user_type, String) == "tutor"
    ).count()
    
    unknown = db.query(SearchResult).filter(
        cast(SearchResult.user_type, String) == "unknown"
    ).count()
    
    not_analyzed = db.query(SearchResult).filter(
        SearchResult.user_type.is_(None)
    ).count()
    
    pending = db.query(SearchResult).filter(
        SearchResult.status == ResultStatus.PENDING
    ).count()
    
    contacted = db.query(SearchResult).filter(
        SearchResult.status == ResultStatus.CONTACTED
    ).count()
    
    not_interested = db.query(SearchResult).filter(
        SearchResult.status == ResultStatus.NOT_INTERESTED
    ).count()
    
    invalid = db.query(SearchResult).filter(
        SearchResult.status == ResultStatus.INVALID
    ).count()
    
    return {
        "total": total,
        "customers": customers,
        "tutors": tutors,
        "unknown": unknown,
        "not_analyzed": not_analyzed,
        "pending": pending,
        "contacted": contacted,
        "not_interested": not_interested,
        "invalid": invalid
    }
