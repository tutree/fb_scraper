from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session
from typing import List, Literal, Optional

from ...core.database import get_db
from ...models.search_result import SearchResult, UserType
from ...models.post_comment import PostComment
from ...services.background_jobs import (
    get_status,
    get_history,
    enable_auto_scrape,
    disable_auto_scrape,
    update_config,
    trigger_now,
    trigger_comment_analyze_now,
    trigger_geo_filter_now,
    request_background_scraper_stop,
    clear_background_scraper_stop,
    pause_analyze_worker_job,
    resume_analyze_worker_job,
    pause_enrich_worker_job,
    resume_enrich_worker_job,
)
from ...services.enformion_service import EnformionService

router = APIRouter(prefix="/automation", tags=["automation"])


class EnrichQueueItem(BaseModel):
    id: str
    fullname: str
    location: str


class JobInfo(BaseModel):
    running: bool = False
    interval_minutes: int = 0
    next_run: Optional[str] = None


class JobsInfo(BaseModel):
    scraper: JobInfo = JobInfo()
    analyzer: JobInfo = JobInfo()
    enrichment: JobInfo = JobInfo()
    comment_analyzer: JobInfo = JobInfo()
    geo_filter: JobInfo = JobInfo()


class AutomationStatus(BaseModel):
    scheduler_running: bool
    auto_scrape_enabled: bool
    interval_minutes: int
    auto_analyze: bool
    auto_enrich: bool
    try_credential_login: bool = False
    next_run: Optional[str] = None
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    is_running: bool = False
    current_step: Optional[str] = None
    scraper_stop_requested: bool = False
    analyzer_paused: bool = False
    enrichment_paused: bool = False
    analyze_queue_pending: int = 0
    analyze_queue_ids: List[str] = []
    enrich_queue_pending: int = 0
    enrich_queue_items: List[EnrichQueueItem] = []
    enrich_not_enrichable_count: int = 0
    jobs: JobsInfo = JobsInfo()


class JobHistoryEntry(BaseModel):
    id: str
    started_at: str
    finished_at: Optional[str] = None
    status: str
    trigger: str = "scheduled"
    scraped: int = 0
    new_records: int = 0
    analyzed: int = 0
    enriched: int = 0
    error: Optional[str] = None
    detail: Optional[str] = None


class AutomationUpdate(BaseModel):
    auto_scrape_enabled: Optional[bool] = None
    interval_minutes: Optional[int] = Field(None, ge=5, le=1440)
    auto_analyze: Optional[bool] = None
    auto_enrich: Optional[bool] = None
    try_credential_login: Optional[bool] = None


class JobControlBody(BaseModel):
    job: Literal["scraper", "analyzer", "enrichment"]


@router.get("/status", response_model=AutomationStatus)
async def automation_status():
    return AutomationStatus(**get_status())


@router.get("/history", response_model=List[JobHistoryEntry])
async def automation_history(
    limit: int = Query(20, ge=1, le=50),
):
    return [JobHistoryEntry(**e) for e in get_history(limit)]


@router.post("/update", response_model=AutomationStatus)
async def update_automation(body: AutomationUpdate):
    update_config(
        auto_analyze=body.auto_analyze,
        auto_enrich=body.auto_enrich,
        try_credential_login=body.try_credential_login,
    )

    if body.auto_scrape_enabled is True:
        enable_auto_scrape(body.interval_minutes)
    elif body.auto_scrape_enabled is False:
        disable_auto_scrape()
    elif body.interval_minutes is not None:
        enable_auto_scrape(body.interval_minutes)

    return AutomationStatus(**get_status())


@router.post("/trigger")
async def trigger_scrape_now():
    trigger_now()
    return {"message": "Scrape triggered — running in background"}


@router.post("/trigger-comment-analyze")
async def trigger_comment_analyze():
    trigger_comment_analyze_now()
    return {"message": "Comment analyzer triggered — running in background"}


@router.post("/trigger-geo-filter")
async def trigger_geo_filter():
    trigger_geo_filter_now()
    return {"message": "Geo-filter triggered — scanning for non-US posts in background"}


@router.post("/stop-job", response_model=AutomationStatus)
async def stop_background_job(body: JobControlBody):
    """Request cooperative stop (scraper) or pause queue processing (analyzer / enrichment)."""
    if body.job == "scraper":
        request_background_scraper_stop()
    elif body.job == "analyzer":
        pause_analyze_worker_job()
    else:
        pause_enrich_worker_job()
    return AutomationStatus(**get_status())


@router.post("/resume-job", response_model=AutomationStatus)
async def resume_background_job(body: JobControlBody):
    """Clear scraper stop flag or resume paused analyzer / enrichment workers."""
    if body.job == "scraper":
        clear_background_scraper_stop()
    elif body.job == "analyzer":
        resume_analyze_worker_job()
    else:
        resume_enrich_worker_job()
    return AutomationStatus(**get_status())


# ---------------------------------------------------------------------------
# Job statistics / visualizations
# ---------------------------------------------------------------------------

class HourlyStat(BaseModel):
    hour: str
    count: int


class JobStats(BaseModel):
    # Scraper
    scraper_total: int = 0
    scraper_today: int = 0
    scraper_hourly: List[HourlyStat] = []

    # Post analyzer
    post_analyze_done: int = 0
    post_analyze_pending: int = 0
    post_analyze_customer: int = 0
    post_analyze_tutor: int = 0
    post_analyze_unknown: int = 0
    post_analyze_hourly: List[HourlyStat] = []

    # Comment analyzer
    comment_analyze_done: int = 0
    comment_analyze_pending: int = 0
    comment_analyze_customer: int = 0
    comment_analyze_tutor: int = 0
    comment_analyze_unknown: int = 0
    comment_analyze_hourly: List[HourlyStat] = []

    # Enrichment
    enrich_done: int = 0
    enrich_pending: int = 0
    enrich_not_enrichable: int = 0
    enrich_hourly: List[HourlyStat] = []

    # Geo-filter
    geo_filter_us: int = 0
    geo_filter_non_us: int = 0
    geo_filter_pending: int = 0
    geo_filter_hourly: List[HourlyStat] = []


def _hourly_counts(db: Session, model, ts_column, hours: int = 24) -> List[HourlyStat]:
    """Return per-hour counts for the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(
            sa_func.date_trunc("hour", ts_column).label("h"),
            sa_func.count().label("c"),
        )
        .filter(ts_column >= cutoff)
        .group_by("h")
        .order_by("h")
        .all()
    )
    return [HourlyStat(hour=r.h.isoformat(), count=r.c) for r in rows]


@router.get("/job-stats", response_model=JobStats)
async def job_stats(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # -- Scraper --
    scraper_total = db.query(sa_func.count(SearchResult.id)).scalar() or 0
    scraper_today = (
        db.query(sa_func.count(SearchResult.id))
        .filter(SearchResult.scraped_at >= today_start)
        .scalar() or 0
    )
    scraper_hourly = _hourly_counts(db, SearchResult, SearchResult.scraped_at)

    # -- Post analyzer --
    post_analyze_done = (
        db.query(sa_func.count(SearchResult.id))
        .filter(SearchResult.analyzed_at.isnot(None))
        .scalar() or 0
    )
    post_analyze_pending = (
        db.query(sa_func.count(SearchResult.id))
        .filter(SearchResult.analyzed_at.is_(None))
        .scalar() or 0
    )
    post_analyze_customer = (
        db.query(sa_func.count(SearchResult.id))
        .filter(SearchResult.user_type == UserType.CUSTOMER)
        .scalar() or 0
    )
    post_analyze_tutor = (
        db.query(sa_func.count(SearchResult.id))
        .filter(SearchResult.user_type == UserType.TUTOR)
        .scalar() or 0
    )
    post_analyze_unknown = (
        db.query(sa_func.count(SearchResult.id))
        .filter(SearchResult.user_type == UserType.UNKNOWN)
        .scalar() or 0
    )
    post_analyze_hourly = _hourly_counts(db, SearchResult, SearchResult.analyzed_at)

    # -- Comment analyzer --
    comment_analyze_done = (
        db.query(sa_func.count(PostComment.id))
        .filter(PostComment.analyzed_at.isnot(None))
        .scalar() or 0
    )
    comment_analyze_pending = (
        db.query(sa_func.count(PostComment.id))
        .filter(PostComment.analyzed_at.is_(None))
        .scalar() or 0
    )
    comment_analyze_customer = (
        db.query(sa_func.count(PostComment.id))
        .filter(PostComment.user_type == UserType.CUSTOMER)
        .scalar() or 0
    )
    comment_analyze_tutor = (
        db.query(sa_func.count(PostComment.id))
        .filter(PostComment.user_type == UserType.TUTOR)
        .scalar() or 0
    )
    comment_analyze_unknown = (
        db.query(sa_func.count(PostComment.id))
        .filter(PostComment.user_type == UserType.UNKNOWN)
        .scalar() or 0
    )
    comment_analyze_hourly = _hourly_counts(db, PostComment, PostComment.analyzed_at)

    # -- Enrichment --
    enrich_done = (
        db.query(sa_func.count(SearchResult.id))
        .filter(SearchResult.enriched_at.isnot(None))
        .scalar() or 0
    )
    enrich_pending = (
        db.query(sa_func.count(SearchResult.id))
        .filter(
            SearchResult.analyzed_at.isnot(None),
            SearchResult.enriched_at.is_(None),
            SearchResult.enrichable == True,  # noqa: E712
        )
        .scalar() or 0
    )
    enrich_not_enrichable = (
        db.query(sa_func.count(SearchResult.id))
        .filter(
            SearchResult.analyzed_at.isnot(None),
            SearchResult.enriched_at.is_(None),
            SearchResult.enrichable == False,  # noqa: E712
        )
        .scalar() or 0
    )
    enrich_hourly = _hourly_counts(db, SearchResult, SearchResult.enriched_at)

    # -- Geo-filter --
    geo_filter_us = (
        db.query(sa_func.count(SearchResult.id))
        .filter(SearchResult.is_us == True)  # noqa: E712
        .scalar() or 0
    )
    geo_filter_non_us = (
        db.query(sa_func.count(SearchResult.id))
        .filter(SearchResult.is_us == False)  # noqa: E712
        .scalar() or 0
    )
    geo_filter_pending = (
        db.query(sa_func.count(SearchResult.id))
        .filter(SearchResult.geo_filtered_at.is_(None))
        .scalar() or 0
    )
    geo_filter_hourly = _hourly_counts(db, SearchResult, SearchResult.geo_filtered_at)

    return JobStats(
        scraper_total=scraper_total,
        scraper_today=scraper_today,
        scraper_hourly=scraper_hourly,
        post_analyze_done=post_analyze_done,
        post_analyze_pending=post_analyze_pending,
        post_analyze_customer=post_analyze_customer,
        post_analyze_tutor=post_analyze_tutor,
        post_analyze_unknown=post_analyze_unknown,
        post_analyze_hourly=post_analyze_hourly,
        comment_analyze_done=comment_analyze_done,
        comment_analyze_pending=comment_analyze_pending,
        comment_analyze_customer=comment_analyze_customer,
        comment_analyze_tutor=comment_analyze_tutor,
        comment_analyze_unknown=comment_analyze_unknown,
        comment_analyze_hourly=comment_analyze_hourly,
        enrich_done=enrich_done,
        enrich_pending=enrich_pending,
        enrich_not_enrichable=enrich_not_enrichable,
        enrich_hourly=enrich_hourly,
        geo_filter_us=geo_filter_us,
        geo_filter_non_us=geo_filter_non_us,
        geo_filter_pending=geo_filter_pending,
        geo_filter_hourly=geo_filter_hourly,
    )
