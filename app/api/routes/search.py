from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from threading import Lock
import json
import uuid

from ...core.config import keywords_json_path, settings
from ...core.database import SessionLocal
from ...core.logging_config import get_recent_logs
from ...services.scraper import ScraperService
from ...services.facebook_cookie_manager import get_cookie_status, save_cookie_json_text
from ...core.logging_config import get_logger
from ...schemas.search import (
    CookieStatusResponse,
    CookieUpdateRequest,
    CookieUpdateResponse,
    ScraperHealthResponse,
    SearchRequest,
    SearchResponse,
    SearchTaskDetail,
    SearchStopResponse,
    SearchLogsResponse,
)
from ...services.scraper_state import get_scraper_health

router = APIRouter(prefix="/search", tags=["search"])
logger = get_logger(__name__)

# In-memory task store (swap for Redis in production)
tasks: Dict[str, Dict[str, Any]] = {}
current_task_id: Optional[str] = None
last_task_id: Optional[str] = None
tasks_lock = Lock()
ACTIVE_STATUSES = {"running", "stopping"}
TERMINAL_STATUSES = {"completed", "failed", "stopped"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_task_detail(task_id: Optional[str], task: Optional[Dict[str, Any]]) -> SearchTaskDetail:
    if not task_id or not task:
        return SearchTaskDetail(
            task_id=None,
            status="idle",
            message="No active scraper task",
        )

    status = str(task.get("status") or "idle")
    return SearchTaskDetail(
        task_id=task_id,
        status=status,
        message=f"Task status: {status}",
        created_at=task.get("created_at"),
        updated_at=task.get("updated_at"),
        stop_requested=bool(task.get("stop_requested", False)),
        requested_keywords=task.get("requested_keywords"),
        requested_max_results=task.get("requested_max_results"),
        result=task.get("result"),
        error=task.get("error"),
    )


@router.post("/start", response_model=SearchResponse)
async def start_search(
    request: SearchRequest,
    background_tasks: BackgroundTasks,
):
    """Start a new search task."""
    global current_task_id, last_task_id

    cookie_status = get_cookie_status()
    if not cookie_status.get("cookie_file") or int(cookie_status.get("cookie_count") or 0) <= 0:
        saved_uids = cookie_status.get("saved_cookie_uids", [])
        active_uids = cookie_status.get("active_account_uids", [])
        raise HTTPException(
            status_code=400,
            detail=(
                f"No active cookie session found. "
                f"Active account(s): {active_uids or 'none'}. "
                f"Saved cookie UID(s): {saved_uids or 'none'}. "
                f"Use the 'Update Facebook Cookie' button to paste a valid cookie."
            ),
        )

    with tasks_lock:
        if current_task_id:
            current = tasks.get(current_task_id)
            if current and current.get("status") in ACTIVE_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail=f"Task {current_task_id} is already {current.get('status')}",
                )

    task_id = str(uuid.uuid4())
    max_per_kw = (
        request.max_results
        if request.max_results is not None
        else settings.MAX_RESULTS_PER_KEYWORD
    )

    # Store task info
    now = _now_iso()
    with tasks_lock:
        tasks[task_id] = {
            "id": task_id,
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "stop_requested": False,
            "requested_keywords": request.keywords,
            "requested_max_results": max_per_kw,
            "result": None,
            "error": None,
        }
        current_task_id = task_id
        last_task_id = task_id

    # Run search in background
    background_tasks.add_task(
        run_search_task,
        task_id,
        request.keywords,
        max_per_kw,
    )

    return SearchResponse(
        task_id=task_id,
        message="Search started successfully",
        status="running",
    )


@router.get("/task/{task_id}", response_model=SearchResponse)
async def get_task_status(task_id: str):
    """Get status of a search task."""
    with tasks_lock:
        task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return SearchResponse(
        task_id=task_id,
        message=f"Task status: {task['status']}",
        status=task["status"],
    )


@router.get("/current", response_model=SearchTaskDetail)
async def get_current_task() -> SearchTaskDetail:
    """Get details of the current scraper task if any."""
    with tasks_lock:
        task_id = current_task_id or last_task_id
        task = tasks.get(task_id) if task_id else None
    return _to_task_detail(task_id, task)


@router.post("/stop", response_model=SearchStopResponse)
async def stop_search() -> SearchStopResponse:
    """Request stop for the currently running scraper task."""
    with tasks_lock:
        task_id = current_task_id
        task = tasks.get(task_id) if task_id else None

        if not task_id or not task:
            return SearchStopResponse(
                task_id=None,
                status="idle",
                message="No active scraper task",
            )

        status = str(task.get("status") or "idle")
        if status not in ACTIVE_STATUSES:
            return SearchStopResponse(
                task_id=task_id,
                status=status,
                message=f"Task is already {status}",
            )

        task["stop_requested"] = True
        task["status"] = "stopping"
        task["updated_at"] = _now_iso()

    return SearchStopResponse(
        task_id=task_id,
        status="stopping",
        message="Stop requested",
    )


@router.get("/logs", response_model=SearchLogsResponse)
async def get_search_logs(
    lines: int = Query(200, ge=1, le=2000),
) -> SearchLogsResponse:
    """Return recent application logs for scraper monitoring."""
    return SearchLogsResponse(lines=get_recent_logs(lines=lines))


@router.get("/cookies/status", response_model=CookieStatusResponse)
async def get_saved_cookie_status() -> CookieStatusResponse:
    """Return current cookie-session metadata for the scraper UI."""
    return CookieStatusResponse(**get_cookie_status())


@router.get("/scraper-health", response_model=ScraperHealthResponse)
async def scraper_health() -> ScraperHealthResponse:
    """Combined scraper health: cookie files + runtime session state."""
    cookie = get_cookie_status()
    health = get_scraper_health()

    has_files = bool(cookie.get("cookie_file"))
    count = int(cookie.get("cookie_count") or 0)

    age_hours = None
    if cookie.get("updated_at"):
        try:
            ts = datetime.fromisoformat(cookie["updated_at"])
            age_hours = round((datetime.now(timezone.utc) - ts).total_seconds() / 3600, 1)
        except Exception:
            pass

    all_failed = bool(health.get("all_cookies_failed"))
    no_cookies = not has_files or count == 0

    if all_failed:
        level, message = "error", "All cookies expired — upload fresh cookies"
    elif no_cookies:
        level, message = "error", "No cookie files found — upload cookies to start scraping"
    elif health.get("last_scrape_success") is False and health.get("last_scrape_error"):
        level, message = "warning", f"Last scrape failed: {health['last_scrape_error'][:120]}"
    elif age_hours is not None and age_hours > 72:
        level, message = "warning", f"Cookie file is {age_hours:.0f}h old — may be stale"
    else:
        level, message = "ok", "Scraper healthy"

    return ScraperHealthResponse(
        has_cookie_files=has_files,
        cookie_count=count,
        cookie_file_age_hours=age_hours,
        all_cookies_failed=all_failed,
        all_cookies_failed_at=health.get("all_cookies_failed_at"),
        last_cookie_ok_uid=health.get("last_cookie_ok_uid"),
        last_cookie_ok_at=health.get("last_cookie_ok_at"),
        last_cookie_fail_reason=health.get("last_cookie_fail_reason"),
        last_scrape_success=health.get("last_scrape_success"),
        last_scrape_error=health.get("last_scrape_error"),
        level=level,
        message=message,
    )


@router.post("/cookies", response_model=CookieUpdateResponse)
async def update_saved_cookie(request: CookieUpdateRequest) -> CookieUpdateResponse:
    """Validate and save pasted Facebook cookie JSON for scraper login reuse."""
    result = save_cookie_json_text(request.cookie_json)
    return CookieUpdateResponse(
        message=f"Saved cookie session for account {result['account_uid']}",
        account_uid=result["account_uid"],
        cookie_file=result["cookie_file"],
        cookie_count=result["cookie_count"],
        updated_at=result["updated_at"],
        active_account_uids=result["active_account_uids"],
    )


def _read_keywords_file() -> dict:
    path = keywords_json_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"searchKeywords": []}


def _write_keywords_file(data: dict) -> None:
    path = keywords_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.exception("Failed to write keywords file at %s", path)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Cannot write keywords file at {path}: {e}. "
                "Set KEYWORDS_FILE_PATH to a writable path and mount a volume in Docker (e.g. /data/keywords.json)."
            ),
        ) from e


class AddKeywordsRequest(BaseModel):
    keywords: List[str]


@router.get("/keywords")
async def get_keywords():
    """Return current keywords from config/keywords.json (or KEYWORDS_FILE_PATH)."""
    data = _read_keywords_file()
    return {"keywords": data.get("searchKeywords", [])}


@router.post("/keywords")
async def add_keywords(request: AddKeywordsRequest):
    """Add new keywords to keywords file (deduplicates)."""
    new_kws = [kw.strip() for kw in request.keywords if kw.strip()]
    if not new_kws:
        raise HTTPException(status_code=400, detail="No valid keywords provided")

    data = _read_keywords_file()
    existing = data.get("searchKeywords", [])
    existing_lower = {k.lower() for k in existing}
    added = [kw for kw in new_kws if kw.lower() not in existing_lower]
    existing.extend(added)
    data["searchKeywords"] = existing

    _write_keywords_file(data)
    logger.info("Keywords updated: added %d, total %d", len(added), len(existing))

    return {"added": added, "total": len(existing), "keywords": existing}


@router.delete("/keywords")
async def remove_keyword(keyword: str = Query(...)):
    """Remove a single keyword from keywords file."""
    data = _read_keywords_file()
    if not data.get("searchKeywords") and not keywords_json_path().exists():
        raise HTTPException(status_code=404, detail="Keywords file not found")

    existing = data.get("searchKeywords", [])
    keyword_lower = keyword.lower().strip()
    updated = [kw for kw in existing if kw.lower().strip() != keyword_lower]

    if len(updated) == len(existing):
        raise HTTPException(status_code=404, detail=f"Keyword '{keyword}' not found")

    data["searchKeywords"] = updated
    _write_keywords_file(data)
    logger.info("Keyword removed: '%s', total %d", keyword, len(updated))

    return {"removed": keyword, "total": len(updated), "keywords": updated}


async def run_search_task(
    task_id: str,
    keywords: Optional[List[str]],
    max_results: int,
) -> None:
    """Background task for searching."""
    global current_task_id

    def should_stop() -> bool:
        with tasks_lock:
            task = tasks.get(task_id)
            return bool(task and task.get("stop_requested"))

    db = SessionLocal()
    try:
        logger.info("Background scraper task %s started", task_id)
        scraper = ScraperService(db)
        result = await scraper.run_search(
            keywords,
            max_results,
            should_stop=should_stop,
        )

        if result.get("stopped"):
            final_status = "stopped"
        else:
            final_status = "completed" if result.get("success") else "failed"

        with tasks_lock:
            if task_id in tasks:
                tasks[task_id]["status"] = final_status
                tasks[task_id]["result"] = result
                tasks[task_id]["updated_at"] = _now_iso()
        logger.info("Background scraper task %s finished with status=%s", task_id, final_status)
    except Exception as e:
        logger.exception("Background scraper task %s failed: %s", task_id, e)
        with tasks_lock:
            if task_id in tasks:
                tasks[task_id]["status"] = "failed"
                tasks[task_id]["error"] = str(e)
                tasks[task_id]["updated_at"] = _now_iso()
    finally:
        db.close()
        with tasks_lock:
            if current_task_id == task_id:
                task = tasks.get(task_id)
                if not task or task.get("status") in TERMINAL_STATUSES:
                    current_task_id = None
