from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from ...core.database import get_db
from ...models.search_result import SearchResult, ResultStatus, UserType

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Get dashboard statistics."""
    total = db.query(SearchResult).count()
    
    customers = db.query(SearchResult).filter(
        SearchResult.user_type == UserType.CUSTOMER.value
    ).count()
    
    tutors = db.query(SearchResult).filter(
        SearchResult.user_type == UserType.TUTOR.value
    ).count()
    
    unknown = db.query(SearchResult).filter(
        SearchResult.user_type == UserType.UNKNOWN.value
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
        "pending": pending,
        "contacted": contacted,
        "not_interested": not_interested,
        "invalid": invalid
    }
