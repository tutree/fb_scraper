from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import Optional, List

from ...core.config import settings
from ...services.background_jobs import (
    get_status,
    get_history,
    enable_auto_scrape,
    disable_auto_scrape,
    update_config,
    trigger_now,
)

router = APIRouter(prefix="/automation", tags=["automation"])


class EnrichQueueItem(BaseModel):
    id: str
    fullname: str
    location: str


class AutomationStatus(BaseModel):
    scheduler_running: bool
    auto_scrape_enabled: bool
    interval_minutes: int
    auto_analyze: bool
    auto_enrich: bool
    next_run: Optional[str] = None
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    is_running: bool = False
    current_step: Optional[str] = None
    analyze_queue_pending: int = 0
    analyze_queue_ids: List[str] = []
    enrich_queue_pending: int = 0
    enrich_queue_items: List[EnrichQueueItem] = []
    enrich_not_enrichable_count: int = 0


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


class AutomationUpdate(BaseModel):
    auto_scrape_enabled: Optional[bool] = None
    interval_minutes: Optional[int] = Field(None, ge=5, le=1440)
    auto_analyze: Optional[bool] = None
    auto_enrich: Optional[bool] = None


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
    update_config(auto_analyze=body.auto_analyze, auto_enrich=body.auto_enrich)

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
