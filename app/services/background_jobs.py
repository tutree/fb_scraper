"""
Background automation: scheduled scraping, auto-analysis, auto-enrichment.
Uses APScheduler AsyncIOScheduler with Redis job store so schedules and
state survive container restarts.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, List

import redis
from redis.asyncio import Redis as AsyncRedis
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..core.config import settings
from ..core.database import SessionLocal
from ..core.logging_config import get_logger
from ..models.search_result import SearchResult, UserType
from ..services.gemini_classifier import GeminiClassifier
from ..services.enformion_service import EnformionService
from ..services.scraper import ScraperService
from ..services.facebook_cookie_manager import get_cookie_status
from ..utils.validators import clean_facebook_location, clean_facebook_name

logger = get_logger(__name__)

JOB_ID = "auto_scrape_job"
REDIS_PREFIX = "autojob:"
REDIS_KEY_STATUS = f"{REDIS_PREFIX}status"
REDIS_KEY_LOCK = f"{REDIS_PREFIX}running_lock"
REDIS_KEY_HISTORY = f"{REDIS_PREFIX}history"
REDIS_KEY_CONFIG = f"{REDIS_PREFIX}config"
REDIS_KEY_ANALYZE_QUEUE = f"{REDIS_PREFIX}analyze_queue"
MAX_HISTORY = 50

_scheduler: Optional[AsyncIOScheduler] = None
_redis: Optional[redis.Redis] = None
_analyze_worker_task: Optional[asyncio.Task] = None


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _save_json(key: str, data: dict):
    try:
        _get_redis().set(key, json.dumps(data))
    except Exception as exc:
        logger.warning("Redis write failed for %s: %s", key, exc)


def _load_json(key: str) -> dict:
    try:
        raw = _get_redis().get(key)
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning("Redis read failed for %s: %s", key, exc)
    return {}


def _push_history(entry: dict):
    try:
        r = _get_redis()
        r.lpush(REDIS_KEY_HISTORY, json.dumps(entry))
        r.ltrim(REDIS_KEY_HISTORY, 0, MAX_HISTORY - 1)
    except Exception as exc:
        logger.warning("Failed to push job history: %s", exc)


def get_history(limit: int = 20) -> List[dict]:
    try:
        raw_list = _get_redis().lrange(REDIS_KEY_HISTORY, 0, limit - 1)
        return [json.loads(r) for r in raw_list]
    except Exception as exc:
        logger.warning("Failed to read job history: %s", exc)
        return []


def _acquire_lock(ttl_seconds: int = 7200) -> bool:
    try:
        return bool(_get_redis().set(REDIS_KEY_LOCK, "1", nx=True, ex=ttl_seconds))
    except Exception:
        return True


def _release_lock():
    try:
        _get_redis().delete(REDIS_KEY_LOCK)
    except Exception:
        pass


def push_to_analyze_queue(record_id: int) -> None:
    """Push a new result id to the analyze queue so the background worker processes it."""
    try:
        _get_redis().rpush(REDIS_KEY_ANALYZE_QUEUE, str(record_id))
    except Exception as exc:
        logger.warning("Failed to push result id %s to analyze queue: %s", record_id, exc)


def _is_locked() -> bool:
    try:
        return bool(_get_redis().exists(REDIS_KEY_LOCK))
    except Exception:
        return False


def _save_config():
    _save_json(REDIS_KEY_CONFIG, {
        "auto_scrape_enabled": settings.AUTO_SCRAPE_ENABLED,
        "interval_minutes": settings.AUTO_SCRAPE_INTERVAL_MINUTES,
        "auto_analyze": settings.AUTO_ANALYZE_AFTER_SCRAPE,
        "auto_enrich": settings.AUTO_ENRICH_AFTER_ANALYZE,
    })


def _load_config():
    cfg = _load_json(REDIS_KEY_CONFIG)
    if cfg:
        settings.AUTO_SCRAPE_ENABLED = cfg.get("auto_scrape_enabled", settings.AUTO_SCRAPE_ENABLED)
        settings.AUTO_SCRAPE_INTERVAL_MINUTES = cfg.get("interval_minutes", settings.AUTO_SCRAPE_INTERVAL_MINUTES)
        settings.AUTO_ANALYZE_AFTER_SCRAPE = cfg.get("auto_analyze", settings.AUTO_ANALYZE_AFTER_SCRAPE)
        settings.AUTO_ENRICH_AFTER_ANALYZE = cfg.get("auto_enrich", settings.AUTO_ENRICH_AFTER_ANALYZE)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        jobstores = {
            "default": RedisJobStore(
                host=_get_redis().connection_pool.connection_kwargs.get("host", "redis"),
                port=_get_redis().connection_pool.connection_kwargs.get("port", 6379),
                db=_get_redis().connection_pool.connection_kwargs.get("db", 0),
            )
        }
        _scheduler = AsyncIOScheduler(jobstores=jobstores)
    return _scheduler


def get_status() -> dict:
    scheduler = get_scheduler()
    job = scheduler.get_job(JOB_ID)
    persisted = _load_json(REDIS_KEY_STATUS)
    return {
        "scheduler_running": scheduler.running,
        "auto_scrape_enabled": job is not None,
        "interval_minutes": settings.AUTO_SCRAPE_INTERVAL_MINUTES,
        "auto_analyze": settings.AUTO_ANALYZE_AFTER_SCRAPE,
        "auto_enrich": settings.AUTO_ENRICH_AFTER_ANALYZE,
        "next_run": str(job.next_run_time) if job and job.next_run_time else None,
        "last_run_at": persisted.get("last_run_at"),
        "last_run_status": persisted.get("last_run_status"),
        "is_running": _is_locked(),
        "current_step": persisted.get("current_step"),
    }


async def _auto_analyze_results(db, result_ids: list) -> int:
    try:
        classifier = GeminiClassifier()
    except ValueError as exc:
        logger.warning("Auto-analyze skipped — classifier not available: %s", exc)
        return 0

    analyzed = 0
    for rid in result_ids:
        result = db.query(SearchResult).filter(SearchResult.id == rid).first()
        if not result or result.user_type is not None:
            continue

        if result.name:
            cleaned_name = clean_facebook_name(result.name)
            if cleaned_name and cleaned_name != result.name:
                result.name = cleaned_name
        if result.location:
            cleaned_loc = clean_facebook_location(result.location)
            if cleaned_loc and cleaned_loc != result.location:
                result.location = cleaned_loc

        if not result.post_content or not result.post_content.strip():
            result.user_type = UserType.UNKNOWN
            result.confidence_score = 0.0
            result.analysis_message = "No post content available"
            result.analyzed_at = datetime.now(timezone.utc)
            analyzed += 1
            continue

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
                str(analysis.get("type", "UNKNOWN")).upper(), UserType.UNKNOWN
            )
            result.confidence_score = max(0.0, min(1.0, float(analysis.get("confidence", 0.0))))
            result.analysis_message = str(analysis.get("reason") or "")
            result.analyzed_at = datetime.now(timezone.utc)
            analyzed += 1
        except Exception as exc:
            logger.warning("Auto-analyze failed for %s: %s", rid, exc)

    if analyzed > 0:
        db.commit()
    return analyzed


async def _run_analyze_queue_worker() -> None:
    """Background worker: pop result ids from Redis and run analysis + enrichment."""
    try:
        client = AsyncRedis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as exc:
        logger.warning("Analyze queue worker not started (Redis): %s", exc)
        return
    logger.info("Analyze queue worker started")
    while True:
        try:
            # Block up to 5s; process one id at a time for immediate analysis
            result = await client.blpop(REDIS_KEY_ANALYZE_QUEUE, timeout=5)
            if not result:
                continue
            _, id_str = result
            try:
                rid = int(id_str)
            except (ValueError, TypeError):
                continue
            db = SessionLocal()
            try:
                if settings.AUTO_ANALYZE_AFTER_SCRAPE:
                    await _auto_analyze_results(db, [rid])
                if settings.AUTO_ENRICH_AFTER_ANALYZE:
                    await _auto_enrich_results(db, [rid])
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("Analyze queue worker cancelled")
            break
        except Exception as exc:
            logger.exception("Analyze queue worker error: %s", exc)
    try:
        await client.aclose()
    except Exception:
        pass


async def _auto_enrich_results(db, result_ids: list) -> int:
    try:
        service = EnformionService()
    except ValueError as exc:
        logger.warning("Auto-enrich skipped — EnformionGO not configured: %s", exc)
        return 0

    enriched = 0
    for rid in result_ids:
        result = db.query(SearchResult).filter(SearchResult.id == rid).first()
        if not result or result.enriched_at is not None:
            continue
        can, _ = EnformionService.can_enrich(result.name, result.location)
        if not can:
            continue

        try:
            data = await service.enrich(result.name, result.location)
            if data.get("matched"):
                result.enriched_phones = data.get("phones")
                result.enriched_emails = data.get("emails")
                result.enriched_addresses = data.get("addresses")
                result.enriched_age = data.get("age")
                result.enriched_at = datetime.now(timezone.utc)
                enriched += 1
        except Exception as exc:
            logger.warning("Auto-enrich failed for %s: %s", rid, exc)

    if enriched > 0:
        db.commit()
    return enriched


def _update_step(run_id: str, step: str, started_at: str):
    _save_json(REDIS_KEY_STATUS, {
        "last_run_at": started_at,
        "last_run_status": "running",
        "current_step": step,
        "run_id": run_id,
    })


async def run_scheduled_scrape():
    """The main scheduled job: scrape -> analyze -> enrich."""
    if not _acquire_lock():
        logger.info("Scheduled scrape skipped — previous run still active (Redis lock)")
        return

    run_id = str(uuid.uuid4())[:8]
    started_at = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": run_id,
        "started_at": started_at,
        "finished_at": None,
        "status": "running",
        "trigger": "scheduled",
        "scraped": 0,
        "new_records": 0,
        "analyzed": 0,
        "enriched": 0,
        "error": None,
    }

    _update_step(run_id, "starting", started_at)
    logger.info("=" * 60)
    logger.info("SCHEDULED AUTO-SCRAPE [%s] STARTING (keywords=config/keywords.json, limit=%d)", run_id, settings.AUTO_SCRAPE_MAX_RESULTS)
    logger.info("=" * 60)

    db = SessionLocal()
    try:
        cookie_status = get_cookie_status()
        if not cookie_status.get("cookie_file") or int(cookie_status.get("cookie_count") or 0) <= 0:
            logger.warning("Scheduled scrape skipped — no active cookie session")
            entry["status"] = "skipped"
            entry["error"] = "No active cookie session"
            entry["finished_at"] = datetime.now(timezone.utc).isoformat()
            _push_history(entry)
            _save_json(REDIS_KEY_STATUS, {
                "last_run_at": started_at,
                "last_run_status": "skipped: no cookie",
                "current_step": None,
            })
            return

        _update_step(run_id, "scraping", started_at)
        ids_before = set(r.id for r in db.query(SearchResult.id).all())

        scraper = ScraperService(db)
        # keywords=None → load from config/keywords.json
        result = await scraper.run_search(
            keywords=None,
            max_results=settings.AUTO_SCRAPE_MAX_RESULTS,
        )

        ids_after = set(r.id for r in db.query(SearchResult.id).all())
        new_ids = list(ids_after - ids_before)
        entry["scraped"] = result.get("total_results", 0)
        entry["new_records"] = len(new_ids)
        logger.info("Scrape done: %d results, %d new records (analysis handled by queue worker)", entry["scraped"], entry["new_records"])

        entry["status"] = "completed"
        entry["finished_at"] = datetime.now(timezone.utc).isoformat()

        status_msg = (
            f"scraped={entry['scraped']} new={entry['new_records']} (analyze/enrich via queue worker)"
        )
        _save_json(REDIS_KEY_STATUS, {
            "last_run_at": started_at,
            "last_run_status": status_msg,
            "current_step": None,
        })
        logger.info("Scheduled run complete: %s", status_msg)

    except Exception as exc:
        logger.exception("Scheduled scrape failed: %s", exc)
        entry["status"] = "failed"
        entry["error"] = str(exc)
        entry["finished_at"] = datetime.now(timezone.utc).isoformat()
        _save_json(REDIS_KEY_STATUS, {
            "last_run_at": started_at,
            "last_run_status": f"error: {exc}",
            "current_step": None,
        })
    finally:
        db.close()
        _release_lock()
        _push_history(entry)
        logger.info("=" * 60)
        logger.info("SCHEDULED AUTO-SCRAPE [%s] FINISHED", run_id)
        logger.info("=" * 60)


def start_analyze_worker() -> None:
    """Start the background task that consumes the analyze queue."""
    global _analyze_worker_task
    if _analyze_worker_task is not None and not _analyze_worker_task.done():
        return
    _analyze_worker_task = asyncio.create_task(_run_analyze_queue_worker())
    logger.info("Analyze queue worker task started")


def stop_analyze_worker() -> None:
    """Cancel the analyze queue worker task (call from shutdown; no await)."""
    global _analyze_worker_task
    if _analyze_worker_task is None:
        return
    _analyze_worker_task.cancel()
    _analyze_worker_task = None
    logger.info("Analyze queue worker task stopped")


def start_scheduler():
    scheduler = get_scheduler()
    if scheduler.running:
        return

    _load_config()

    if settings.AUTO_SCRAPE_ENABLED:
        scheduler.add_job(
            run_scheduled_scrape,
            trigger=IntervalTrigger(minutes=settings.AUTO_SCRAPE_INTERVAL_MINUTES),
            id=JOB_ID,
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Auto-scrape scheduler started (Redis-backed): every %d minutes",
            settings.AUTO_SCRAPE_INTERVAL_MINUTES,
        )
        # Run first scrape immediately; next runs follow the interval
        trigger_now()

    scheduler.start()
    # Always start the analyze queue worker (handles results from manual and scheduled scrapes)
    start_analyze_worker()


def stop_scheduler():
    stop_analyze_worker()
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")


def enable_auto_scrape(interval_minutes: Optional[int] = None):
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()

    minutes = interval_minutes or settings.AUTO_SCRAPE_INTERVAL_MINUTES
    settings.AUTO_SCRAPE_INTERVAL_MINUTES = minutes
    settings.AUTO_SCRAPE_ENABLED = True

    scheduler.add_job(
        run_scheduled_scrape,
        trigger=IntervalTrigger(minutes=minutes),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
    )
    _save_config()
    logger.info("Auto-scrape enabled: every %d minutes", minutes)


def disable_auto_scrape():
    scheduler = get_scheduler()
    job = scheduler.get_job(JOB_ID)
    if job:
        scheduler.remove_job(JOB_ID)
    settings.AUTO_SCRAPE_ENABLED = False
    _save_config()
    logger.info("Auto-scrape disabled")


def update_config(auto_analyze: Optional[bool] = None, auto_enrich: Optional[bool] = None):
    if auto_analyze is not None:
        settings.AUTO_ANALYZE_AFTER_SCRAPE = auto_analyze
    if auto_enrich is not None:
        settings.AUTO_ENRICH_AFTER_ANALYZE = auto_enrich
    _save_config()


def trigger_now():
    asyncio.ensure_future(run_scheduled_scrape())
