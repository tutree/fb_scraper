from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import uuid

from ...core.database import get_db
from ...services.scraper import ScraperService
from ...schemas.search import SearchRequest, SearchResponse

router = APIRouter(prefix="/search", tags=["search"])

# In-memory task store (swap for Redis in production)
tasks: dict = {}


@router.post("/start", response_model=SearchResponse)
async def start_search(
    request: SearchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start a new search task."""
    task_id = str(uuid.uuid4())

    # Store task info
    tasks[task_id] = {
        "id": task_id,
        "status": "running",
        "created_at": datetime.now().isoformat(),
    }

    # Run search in background
    background_tasks.add_task(
        run_search_task,
        task_id,
        request.keywords,
        request.max_results or 100,
        db,
    )

    return SearchResponse(
        task_id=task_id,
        message="Search started successfully",
        status="running",
    )


@router.get("/task/{task_id}", response_model=SearchResponse)
async def get_task_status(task_id: str):
    """Get status of a search task."""
    if task_id not in tasks:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    return SearchResponse(
        task_id=task_id,
        message=f"Task status: {task['status']}",
        status=task["status"],
    )


async def run_search_task(
    task_id: str,
    keywords: Optional[List[str]],
    max_results: int,
    db: Session,
) -> None:
    """Background task for searching."""
    try:
        scraper = ScraperService(db)
        result = await scraper.run_search(keywords, max_results)

        tasks[task_id]["status"] = (
            "completed" if result["success"] else "failed"
        )
        tasks[task_id]["result"] = result
    except Exception as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)
