from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from threading import Lock
import uuid

from ...core.database import SessionLocal
from ...core.logging_config import get_recent_logs
from ...services.scraper import ScraperService
from ...services.facebook_cookie_manager import get_cookie_status, save_cookie_json_text
from ...core.logging_config import get_logger
from ...schemas.search import (
    CookieStatusResponse,
    CookieUpdateRequest,
    CookieUpdateResponse,
    SearchRequest,
    SearchResponse,
    SearchTaskDetail,
    SearchStopResponse,
    SearchLogsResponse,
)

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
            "requested_max_results": request.max_results or 100,
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
        request.max_results or 100,
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
