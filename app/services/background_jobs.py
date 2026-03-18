"""
Background automation: scheduled scraping, auto-analysis, auto-enrichment.
Uses APScheduler AsyncIOScheduler with Redis job store so schedules and
state survive container restarts.
"""
import asyncio
import json
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional, List

import httpx
import redis
from redis.asyncio import Redis as AsyncRedis
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..core.config import settings
from ..core.database import SessionLocal
from ..core.logging_config import get_logger
from ..models.search_result import SearchResult, UserType
from ..models.post_comment import PostComment
from ..services.gemini_classifier import GeminiClassifier
from ..services.enformion_service import EnformionService
from ..services.scraper import ScraperService
from ..services.facebook_cookie_manager import get_cookie_status
from ..utils.validators import clean_facebook_location, clean_facebook_name, parse_facebook_date, is_enrichable

logger = get_logger(__name__)

JOB_ID = "auto_scrape_job"
JOB_ID_ANALYZE_ENRICH = "auto_analyze_enrich_job"
JOB_ID_ENRICH = "auto_enrich_job"
JOB_ID_COMMENT_ANALYZE = "auto_comment_analyze_job"
REDIS_PREFIX = "autojob:"
REDIS_KEY_STATUS = f"{REDIS_PREFIX}status"
REDIS_KEY_LOCK = f"{REDIS_PREFIX}running_lock"
REDIS_KEY_HISTORY = f"{REDIS_PREFIX}history"
REDIS_KEY_CONFIG = f"{REDIS_PREFIX}config"
REDIS_KEY_ANALYZE_QUEUE = f"{REDIS_PREFIX}analyze_queue"
REDIS_KEY_ANALYZE_ENRICH_LOCK = f"{REDIS_PREFIX}analyze_enrich_lock"
REDIS_KEY_ENRICH_QUEUE = f"{REDIS_PREFIX}enrich_queue"
REDIS_KEY_ENRICH_LOCK = f"{REDIS_PREFIX}enrich_lock"
REDIS_KEY_COMMENT_ANALYZE_LOCK = f"{REDIS_PREFIX}comment_analyze_lock"
MAX_HISTORY = 50
ANALYZE_ENRICH_INTERVAL_MINUTES = 15
ENRICH_INTERVAL_MINUTES = 30
ENRICH_MAX_PER_MINUTE = 90
COMMENT_ANALYZE_INTERVAL_MINUTES = 60

_scheduler: Optional[AsyncIOScheduler] = None
_redis: Optional[redis.Redis] = None
_analyze_worker_task: Optional[asyncio.Task] = None
_enrich_worker_task: Optional[asyncio.Task] = None


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


def push_to_analyze_queue(record_id) -> None:
    """Push a new result id to the analyze queue so the background worker processes it."""
    try:
        _get_redis().rpush(REDIS_KEY_ANALYZE_QUEUE, str(record_id))
    except Exception as exc:
        logger.warning("Failed to push result id %s to analyze queue: %s", record_id, exc)


def push_to_enrich_queue(record_id) -> None:
    """Push a result id to the enrich queue so the enrich worker processes it."""
    try:
        _get_redis().rpush(REDIS_KEY_ENRICH_QUEUE, str(record_id))
    except Exception as exc:
        logger.warning("Failed to push result id %s to enrich queue: %s", record_id, exc)


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
    # Wipe any stale config in Redis — code defaults (config.py) are the source of truth
    try:
        _get_redis().delete(REDIS_KEY_CONFIG)
    except Exception:
        pass
    # Persist current code defaults so the UI and get_status() reflect them
    _save_config()
    logger.info(
        "Config loaded from code defaults: interval=%d min, enabled=%s",
        settings.AUTO_SCRAPE_INTERVAL_MINUTES,
        settings.AUTO_SCRAPE_ENABLED,
    )


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


def get_analyze_queue() -> dict:
    """Return current analyze queue size and up to 50 pending ids (for UI). Does not remove from queue."""
    try:
        r = _get_redis()
        pending_count = r.llen(REDIS_KEY_ANALYZE_QUEUE)
        pending_ids = r.lrange(REDIS_KEY_ANALYZE_QUEUE, 0, 49) or []
        return {"pending_count": pending_count, "pending_ids": [str(x) for x in pending_ids]}
    except Exception as exc:
        logger.debug("Could not read analyze queue: %s", exc)
        return {"pending_count": 0, "pending_ids": []}


def get_enrich_queue() -> dict:
    """Return enrich queue size and up to 50 pending items with id, fullname, location (for UI). Does not remove from queue."""
    try:
        r = _get_redis()
        pending_count = r.llen(REDIS_KEY_ENRICH_QUEUE)
        raw_ids = r.lrange(REDIS_KEY_ENRICH_QUEUE, 0, 49) or []
        pending_ids = [str(x) for x in raw_ids]
        if not pending_ids:
            return {"pending_count": pending_count, "pending_items": []}
        db = SessionLocal()
        try:
            uuids = []
            for i in pending_ids:
                try:
                    uuids.append(uuid.UUID(i))
                except (ValueError, TypeError, AttributeError):
                    pass
            rows = db.query(SearchResult.id, SearchResult.name, SearchResult.location).filter(
                SearchResult.id.in_(uuids)
            ).all() if uuids else []
            id_to_row = {str(row.id): {"fullname": row.name or "—", "location": row.location or "—"} for row in rows}
            pending_items = [
                {"id": i, "fullname": id_to_row.get(i, {}).get("fullname", "—"), "location": id_to_row.get(i, {}).get("location", "—")}
                for i in pending_ids
            ]
            return {"pending_count": pending_count, "pending_items": pending_items}
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Could not read enrich queue: %s", exc)
        return {"pending_count": 0, "pending_items": []}


def get_enrich_not_enrichable_count() -> int:
    """Count records that are analyzed, not enriched, and flagged as not enrichable."""
    try:
        db = SessionLocal()
        try:
            return db.query(SearchResult.id).filter(
                SearchResult.analyzed_at.isnot(None),
                SearchResult.enriched_at.is_(None),
                SearchResult.enrichable == False,  # noqa: E712
            ).count()
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Could not count not-enrichable: %s", exc)
        return 0


def get_status() -> dict:
    scheduler = get_scheduler()
    job = scheduler.get_job(JOB_ID)
    persisted = _load_json(REDIS_KEY_STATUS)
    analyze_queue = get_analyze_queue()
    enrich_queue = get_enrich_queue()
    enrich_not_enrichable = get_enrich_not_enrichable_count()

    analyze_job = scheduler.get_job(JOB_ID_ANALYZE_ENRICH)
    enrich_job = scheduler.get_job(JOB_ID_ENRICH)
    comment_job = scheduler.get_job(JOB_ID_COMMENT_ANALYZE)

    analyze_worker_alive = _analyze_worker_task is not None and not _analyze_worker_task.done()
    enrich_worker_alive = _enrich_worker_task is not None and not _enrich_worker_task.done()

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
        "analyze_queue_pending": analyze_queue["pending_count"],
        "analyze_queue_ids": analyze_queue["pending_ids"],
        "enrich_queue_pending": enrich_queue["pending_count"],
        "enrich_queue_items": enrich_queue["pending_items"],
        "enrich_not_enrichable_count": enrich_not_enrichable,
        "jobs": {
            "scraper": {
                "running": _is_locked(),
                "interval_minutes": settings.AUTO_SCRAPE_INTERVAL_MINUTES,
                "next_run": str(job.next_run_time) if job and job.next_run_time else None,
            },
            "analyzer": {
                "running": analyze_worker_alive,
                "interval_minutes": ANALYZE_ENRICH_INTERVAL_MINUTES,
                "next_run": str(analyze_job.next_run_time) if analyze_job and analyze_job.next_run_time else None,
            },
            "enrichment": {
                "running": enrich_worker_alive,
                "interval_minutes": ENRICH_INTERVAL_MINUTES,
                "next_run": str(enrich_job.next_run_time) if enrich_job and enrich_job.next_run_time else None,
            },
            "comment_analyzer": {
                "running": bool(comment_job),
                "interval_minutes": COMMENT_ANALYZE_INTERVAL_MINUTES,
                "next_run": str(comment_job.next_run_time) if comment_job and comment_job.next_run_time else None,
            },
        },
    }


async def _auto_analyze_results(db, result_ids: list) -> int:
    """Run AI classification and parse post_date into post_date_timestamp."""
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
            result.enrichable = is_enrichable(result.name, result.location)
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
            result.enrichable = is_enrichable(result.name, result.location)

            if result.post_date and not result.post_date_timestamp:
                parsed_ts = parse_facebook_date(result.post_date)
                if parsed_ts:
                    result.post_date_timestamp = parsed_ts
                    logger.debug("Post %s: parsed '%s' → %s", rid, result.post_date, parsed_ts)

            analyzed += 1

            if result.user_type == UserType.CUSTOMER:
                deleted = db.query(PostComment).filter(PostComment.search_result_id == result.id).delete()
                if deleted:
                    logger.info("Deleted %d tutor comments from CUSTOMER post %s", deleted, rid)

        except Exception as exc:
            logger.warning("Auto-analyze failed for %s: %s", rid, exc)

    if analyzed > 0:
        db.commit()
    return analyzed


async def _run_enrich_queue_worker() -> None:
    """Background worker: pop result ids from Redis and run enrichment only.
    Never exits on its own — catches all errors and keeps the loop alive."""
    consecutive_429 = 0
    while True:
        client = None
        try:
            client = AsyncRedis.from_url(settings.REDIS_URL, decode_responses=True)
            logger.info("Enrich queue worker connected to Redis")

            while True:
                try:
                    result = await client.blpop(REDIS_KEY_ENRICH_QUEUE, timeout=5)
                    if not result:
                        continue
                    _, id_str = result
                    try:
                        rid = uuid.UUID(id_str)
                    except (ValueError, TypeError, AttributeError):
                        logger.warning("Enrich queue: invalid id %r, skipping", id_str)
                        continue

                    if not settings.AUTO_ENRICH_AFTER_ANALYZE:
                        continue

                    db = SessionLocal()
                    try:
                        await _auto_enrich_results(db, [rid])
                        consecutive_429 = 0
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code == 429:
                            consecutive_429 += 1
                            cooldown = min(300 * consecutive_429, 1800)
                            logger.warning(
                                "Enrich worker 429 (streak=%d) — re-queuing %s, pausing %ds (%dm)",
                                consecutive_429, rid, cooldown, cooldown // 60,
                            )
                            try:
                                await client.rpush(REDIS_KEY_ENRICH_QUEUE, str(rid))
                            except Exception:
                                pass
                            _enrich_timestamps.clear()
                            await asyncio.sleep(cooldown)
                        else:
                            logger.warning("Enrich worker HTTP error for %s: %s", rid, exc)
                    except Exception as exc:
                        logger.warning("Enrich worker item error for %s: %s", rid, exc)
                    finally:
                        db.close()
                except asyncio.CancelledError:
                    logger.info("Enrich queue worker cancelled")
                    return
                except Exception as exc:
                    logger.exception("Enrich queue worker loop error: %s", exc)
                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            logger.info("Enrich queue worker cancelled")
            return
        except Exception as exc:
            logger.error("Enrich queue worker Redis connection error: %s — reconnecting in 10s", exc)
            await asyncio.sleep(10)
        finally:
            if client:
                try:
                    await client.aclose()
                except Exception:
                    pass


async def _run_analyze_queue_worker() -> None:
    """Background worker: pop result ids from Redis and run analysis only.
    Never exits on its own — catches all errors and keeps the loop alive."""
    while True:
        client = None
        try:
            client = AsyncRedis.from_url(settings.REDIS_URL, decode_responses=True)
            logger.info("Analyze queue worker connected to Redis")

            while True:
                try:
                    result = await client.blpop(REDIS_KEY_ANALYZE_QUEUE, timeout=5)
                    if not result:
                        continue
                    _, id_str = result
                    try:
                        rid = uuid.UUID(id_str)
                    except (ValueError, TypeError, AttributeError):
                        logger.warning("Analyze queue: invalid id %r, skipping", id_str)
                        continue

                    if not settings.AUTO_ANALYZE_AFTER_SCRAPE:
                        continue

                    db = SessionLocal()
                    try:
                        await _auto_analyze_results(db, [rid])
                    except Exception as exc:
                        logger.warning("Analyze worker item error for %s: %s", rid, exc)
                    finally:
                        db.close()
                except asyncio.CancelledError:
                    logger.info("Analyze queue worker cancelled")
                    return
                except Exception as exc:
                    logger.exception("Analyze queue worker loop error: %s", exc)
                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            logger.info("Analyze queue worker cancelled")
            return
        except Exception as exc:
            logger.error("Analyze queue worker Redis connection error: %s — reconnecting in 10s", exc)
            await asyncio.sleep(10)
        finally:
            if client:
                try:
                    await client.aclose()
                except Exception:
                    pass


_enrich_timestamps: deque = deque()
_MIN_REQUEST_GAP = 0.7  # ~85/min max, well under 120/min API limit


async def _enrich_rate_limit_wait():
    """Sleep if needed to stay under ENRICH_MAX_PER_MINUTE requests per rolling 60s window."""
    now = time.monotonic()

    # Enforce minimum gap between consecutive requests
    if _enrich_timestamps:
        elapsed_since_last = now - _enrich_timestamps[-1]
        if elapsed_since_last < _MIN_REQUEST_GAP:
            await asyncio.sleep(_MIN_REQUEST_GAP - elapsed_since_last)
            now = time.monotonic()

    # Discard timestamps older than 60s
    while _enrich_timestamps and _enrich_timestamps[0] <= now - 60:
        _enrich_timestamps.popleft()

    if len(_enrich_timestamps) >= ENRICH_MAX_PER_MINUTE:
        wait = 60 - (now - _enrich_timestamps[0]) + 1.0
        logger.info("Enrich rate limit: %d requests in last 60s, sleeping %.1fs", len(_enrich_timestamps), wait)
        await asyncio.sleep(wait)
        now = time.monotonic()
        while _enrich_timestamps and _enrich_timestamps[0] <= now - 60:
            _enrich_timestamps.popleft()

    _enrich_timestamps.append(time.monotonic())


async def _auto_enrich_results(db, result_ids: list) -> int:
    """Enrich from EnformionGO only. Re-raises 429 so the worker can pause and re-queue.
    Phase 1: bulk-copy enrichment data from same-name records already enriched.
    Phase 2: call API only for names that have no donor."""
    try:
        service = EnformionService()
    except ValueError as exc:
        logger.warning("Auto-enrich skipped — EnformionGO not configured: %s", exc)
        return 0

    results = db.query(SearchResult).filter(SearchResult.id.in_(result_ids)).all()
    pending = [r for r in results if r.enriched_at is None and r.enrichable]
    if not pending:
        return 0

    # Phase 1: one query to build a name→donor map from all already-enriched records
    enriched_donors = (
        db.query(SearchResult)
        .filter(SearchResult.enriched_at.isnot(None))
        .all()
    )
    donor_map: dict = {}
    for d in enriched_donors:
        if d.name and d.name.strip():
            key = d.name.strip().lower()
            if key not in donor_map:
                donor_map[key] = d

    copied = 0
    need_api = []
    for result in pending:
        name_key = (result.name or "").strip().lower()
        donor = donor_map.get(name_key) if name_key else None
        if donor:
            result.enriched_phones = donor.enriched_phones
            result.enriched_emails = donor.enriched_emails
            result.enriched_addresses = donor.enriched_addresses
            result.enriched_age = donor.enriched_age
            result.enriched_at = datetime.now(timezone.utc)
            copied += 1
        else:
            need_api.append(result)

    if copied > 0:
        db.commit()
        logger.info("Enrich phase 1: copied enrichment data for %d records from same-name donors", copied)

    # Phase 2: API calls only for truly new names
    api_enriched = 0
    for result in need_api:
        await _enrich_rate_limit_wait()
        try:
            data = await service.enrich(result.name, result.location)
            result.enriched_at = datetime.now(timezone.utc)
            if data.get("matched"):
                result.enriched_phones = data.get("phones")
                result.enriched_emails = data.get("emails")
                result.enriched_addresses = data.get("addresses")
                result.enriched_age = data.get("age")
                api_enriched += 1
                logger.info("Enriched %s — match found", result.id)
                donor_map[(result.name or "").strip().lower()] = result
            else:
                logger.info("Enriched %s — no match from API, marked as attempted", result.id)
                donor_map[(result.name or "").strip().lower()] = result
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                logger.warning("Auto-enrich 429 for %s — stopping batch and bubbling up", result.id)
                db.commit()
                raise
            logger.warning("Auto-enrich HTTP error for %s: %s", result.id, exc)
        except Exception as exc:
            logger.warning("Auto-enrich failed for %s: %s", result.id, exc)

    db.commit()
    return copied + api_enriched


async def _auto_analyze_comments(db, batch_size: int = 50) -> int:
    """Classify un-analyzed comments. Skips comments on CUSTOMER posts (those get deleted)."""
    try:
        classifier = GeminiClassifier()
    except ValueError as exc:
        logger.warning("Comment auto-analyze skipped — classifier not available: %s", exc)
        return 0

    comments = (
        db.query(PostComment)
        .filter(PostComment.analyzed_at.is_(None))
        .limit(batch_size)
        .all()
    )
    if not comments:
        return 0

    logger.info("Comment auto-analyze batch: processing %d comments", len(comments))

    result_ids = list({c.search_result_id for c in comments})
    parents = {
        r.id: r
        for r in db.query(SearchResult).filter(SearchResult.id.in_(result_ids)).all()
    }

    analyzed = 0
    for i, comment in enumerate(comments):
        parent = parents.get(comment.search_result_id)
        post_context = (parent.post_content or "") if parent else ""
        search_keyword = (parent.search_keyword or "") if parent else ""

        if not comment.comment_text or not comment.comment_text.strip():
            comment.user_type = UserType.UNKNOWN
            comment.confidence_score = 0.0
            comment.analysis_message = "No comment text"
            comment.analyzed_at = datetime.now(timezone.utc)
            analyzed += 1
            db.commit()
            continue

        try:
            result = await classifier.classify_comment_user(
                comment_text=comment.comment_text,
                author_name=comment.author_name or "",
                post_context=post_context,
                search_keyword=search_keyword,
            )
            type_mapping = {
                "CUSTOMER": UserType.CUSTOMER,
                "TUTOR": UserType.TUTOR,
                "UNKNOWN": UserType.UNKNOWN,
            }
            comment.user_type = type_mapping.get(
                str(result.get("type", "UNKNOWN")).upper(), UserType.UNKNOWN
            )
            comment.confidence_score = max(0.0, min(1.0, float(result.get("confidence", 0.0))))
            comment.analysis_message = str(result.get("reason") or "")
            comment.analyzed_at = datetime.now(timezone.utc)
            analyzed += 1
            db.commit()
            if analyzed % 10 == 0:
                logger.info("Comment auto-analyze: %d/%d done in this batch", analyzed, len(comments))
        except Exception as exc:
            logger.warning("Comment auto-analyze failed for comment %s: %s", comment.id, exc)
            db.rollback()

    return analyzed


async def run_scheduled_comment_analyze():
    """Periodically analyze un-analyzed comments from DB."""
    logger.info("Comment analyzer job triggered")
    try:
        if not _get_redis().set(REDIS_KEY_COMMENT_ANALYZE_LOCK, "1", nx=True, ex=3600):
            logger.warning("Scheduled comment analyze skipped — previous run still active (lock exists)")
            return
    except Exception as exc:
        logger.warning("Comment analyze lock check failed: %s — proceeding anyway", exc)

    logger.info("Comment analyzer job started (lock acquired)")
    try:
        db = SessionLocal()
        try:
            pending = db.query(PostComment).filter(PostComment.analyzed_at.is_(None)).count()
            logger.info("Comment analyzer: %d un-analyzed comments in DB", pending)
            if pending == 0:
                return

            total = 0
            while True:
                batch = await _auto_analyze_comments(db, batch_size=50)
                if batch == 0:
                    break
                total += batch
                logger.info("Comment analyze progress: %d/%d analyzed", total, pending)
            logger.info("Scheduled comment analyze complete: %d comments analyzed", total)
        finally:
            db.close()
    except Exception as exc:
        logger.exception("Comment analyzer job failed: %s", exc)
    finally:
        try:
            _get_redis().delete(REDIS_KEY_COMMENT_ANALYZE_LOCK)
        except Exception:
            pass
        logger.info("Comment analyzer job finished (lock released)")


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
    """Start the background task that consumes the analyze queue.
    Safe to call multiple times — restarts if previous task died."""
    global _analyze_worker_task
    if _analyze_worker_task is not None and not _analyze_worker_task.done():
        logger.debug("Analyze queue worker already running")
        return
    if _analyze_worker_task is not None and _analyze_worker_task.done():
        exc = _analyze_worker_task.exception() if not _analyze_worker_task.cancelled() else None
        if exc:
            logger.warning("Previous analyze worker died with: %s — restarting", exc)
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


def start_enrich_worker() -> None:
    """Start the background task that consumes the enrich queue.
    Safe to call multiple times — restarts if previous task died."""
    global _enrich_worker_task
    if _enrich_worker_task is not None and not _enrich_worker_task.done():
        logger.debug("Enrich queue worker already running")
        return
    if _enrich_worker_task is not None and _enrich_worker_task.done():
        exc = _enrich_worker_task.exception() if not _enrich_worker_task.cancelled() else None
        if exc:
            logger.warning("Previous enrich worker died with: %s — restarting", exc)
    _enrich_worker_task = asyncio.create_task(_run_enrich_queue_worker())
    logger.info("Enrich queue worker task started")


def stop_enrich_worker() -> None:
    """Cancel the enrich queue worker task (call from shutdown; no await)."""
    global _enrich_worker_task
    if _enrich_worker_task is None:
        return
    _enrich_worker_task.cancel()
    _enrich_worker_task = None
    logger.info("Enrich queue worker task stopped")


def start_scheduler():
    scheduler = get_scheduler()
    if scheduler.running:
        return

    _load_config()

    # Clear any stale lock from a previous process/container so the first scrape and analyze/enrich can run
    _release_lock()
    try:
        _get_redis().delete(REDIS_KEY_ANALYZE_ENRICH_LOCK)
        _get_redis().delete(REDIS_KEY_ENRICH_LOCK)
        _get_redis().delete(REDIS_KEY_COMMENT_ANALYZE_LOCK)
    except Exception:
        pass

    if settings.AUTO_SCRAPE_ENABLED:
        # Remove any persisted job first so stale triggers don't survive
        try:
            scheduler.remove_job(JOB_ID)
        except Exception:
            pass
        scheduler.add_job(
            run_scheduled_scrape,
            trigger=IntervalTrigger(minutes=settings.AUTO_SCRAPE_INTERVAL_MINUTES),
            id=JOB_ID,
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Auto-scrape scheduler started: every %d minutes",
            settings.AUTO_SCRAPE_INTERVAL_MINUTES,
        )
        trigger_now()

    # Periodic feeder: push un-analyzed DB entries to analyze queue
    scheduler.add_job(
        run_scheduled_analyze_enrich,
        trigger=IntervalTrigger(minutes=ANALYZE_ENRICH_INTERVAL_MINUTES),
        id=JOB_ID_ANALYZE_ENRICH,
        replace_existing=True,
        max_instances=1,
    )
    logger.info(
        "Auto analyze feeder scheduled: every %d minutes",
        ANALYZE_ENRICH_INTERVAL_MINUTES,
    )

    # Periodic feeder: push analyzed-but-not-enriched DB entries to enrich queue (independent job)
    scheduler.add_job(
        run_scheduled_enrich,
        trigger=IntervalTrigger(minutes=ENRICH_INTERVAL_MINUTES),
        id=JOB_ID_ENRICH,
        replace_existing=True,
        max_instances=1,
    )
    logger.info(
        "Auto enrich feeder scheduled: every %d minutes",
        ENRICH_INTERVAL_MINUTES,
    )

    # Periodic job: analyze un-analyzed comments every hour
    scheduler.add_job(
        run_scheduled_comment_analyze,
        trigger=IntervalTrigger(minutes=COMMENT_ANALYZE_INTERVAL_MINUTES),
        id=JOB_ID_COMMENT_ANALYZE,
        replace_existing=True,
        max_instances=1,
    )
    logger.info(
        "Auto comment analyze job scheduled: every %d minutes",
        COMMENT_ANALYZE_INTERVAL_MINUTES,
    )

    scheduler.start()
    trigger_analyze_enrich_now()
    asyncio.ensure_future(_safe_run(run_scheduled_comment_analyze(), "comment-analyze-startup"))
    start_analyze_worker()
    start_enrich_worker()
    logger.info("Enrich feeder deferred — first run in %d minutes (scheduled)", ENRICH_INTERVAL_MINUTES)


def stop_scheduler():
    stop_analyze_worker()
    stop_enrich_worker()
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


async def _safe_run(coro, label: str):
    """Wrapper that logs any exception from a fire-and-forget coroutine."""
    try:
        await coro
    except Exception:
        logger.exception("Background task '%s' failed with unhandled exception", label)


def trigger_now():
    asyncio.ensure_future(run_scheduled_scrape())


def trigger_analyze_enrich_now():
    """Run analyze/enrich job once on startup to process backlog immediately."""
    asyncio.ensure_future(_safe_run(run_scheduled_analyze_enrich(), "analyze-enrich-startup"))


def trigger_comment_analyze_now():
    """Manually trigger comment analyzer."""
    asyncio.ensure_future(_safe_run(run_scheduled_comment_analyze(), "comment-analyze-manual"))


async def run_scheduled_analyze_enrich():
    """Periodically fetch un-analyzed entries from DB and push their ids to the analyze queue. Analyze worker processes the queue."""
    try:
        if not _get_redis().set(REDIS_KEY_ANALYZE_ENRICH_LOCK, "1", nx=True, ex=1800):
            logger.debug("Scheduled analyze feeder skipped — previous run still active")
            return
    except Exception:
        pass

    try:
        db = SessionLocal()
        try:
            if not settings.AUTO_ANALYZE_AFTER_SCRAPE:
                return
            unanalyzed = db.query(SearchResult.id).filter(SearchResult.analyzed_at.is_(None)).all()
            to_push = [r.id for r in unanalyzed]
            if not to_push:
                logger.info("Scheduled analyze feeder: no un-analyzed entries in DB")
                return
            for rid in to_push:
                push_to_analyze_queue(rid)
            logger.info("Scheduled analyze feeder: pushed %d ids to analyze queue", len(to_push))
        finally:
            db.close()
    finally:
        try:
            _get_redis().delete(REDIS_KEY_ANALYZE_ENRICH_LOCK)
        except Exception:
            pass


async def run_scheduled_enrich():
    """Periodically fetch enrichable-but-not-enriched entries from DB and push to queue."""
    try:
        if not _get_redis().set(REDIS_KEY_ENRICH_LOCK, "1", nx=True, ex=1800):
            logger.debug("Scheduled enrich feeder skipped — previous run still active")
            return
    except Exception:
        pass

    try:
        db = SessionLocal()
        try:
            if not settings.AUTO_ENRICH_AFTER_ANALYZE:
                return

            unchecked = db.query(SearchResult).filter(
                SearchResult.analyzed_at.isnot(None),
                SearchResult.enrichable.is_(None),
            ).all()
            if unchecked:
                for r in unchecked:
                    r.enrichable = is_enrichable(r.name, r.location)
                db.commit()
                logger.info("Enrich feeder: evaluated %d records with NULL enrichable flag", len(unchecked))

            enrichable_ids = db.query(SearchResult.id).filter(
                SearchResult.analyzed_at.isnot(None),
                SearchResult.enrichable == True,  # noqa: E712
                SearchResult.enriched_at.is_(None),
            ).all()
            if not enrichable_ids:
                logger.info("Scheduled enrich feeder: no enrichable un-enriched entries in DB")
                return

            for row in enrichable_ids:
                push_to_enrich_queue(row.id)

            logger.info(
                "Scheduled enrich feeder: pushed %d enrichable items to queue",
                len(enrichable_ids),
            )

            start_enrich_worker()
        finally:
            db.close()
    finally:
        try:
            _get_redis().delete(REDIS_KEY_ENRICH_LOCK)
        except Exception:
            pass
