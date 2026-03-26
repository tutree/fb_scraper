"""Groq OpenAI-compatible chat API helper (JSON responses)."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import httpx

from ..core.config import settings
from ..core.logging_config import get_logger

logger = get_logger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

# Groq free-tier: 30 RPM for all models.
# Enforcing a minimum gap of 2.5 s between calls keeps us at ≤24 RPM,
# well inside the limit even when multiple workers run concurrently.
_MIN_REQUEST_INTERVAL = 2.5  # seconds
_last_request_ts: float = 0.0
_request_lock = asyncio.Lock()

# Retry settings for 429 / transient errors
_MAX_RETRIES = 4
_BASE_BACKOFF = 5.0   # seconds — first retry wait before consulting retry-after
_MAX_BACKOFF = 60.0   # cap on any single wait


def _strip_json_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) >= 2:
            t = parts[1]
            if t.lstrip().startswith("json"):
                t = t.lstrip()[4:]
            t = t.strip()
    return t


async def groq_chat_json(
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """Call Groq chat completions and parse the assistant message as JSON.

    Respects the 30 RPM rate limit by enforcing a minimum inter-request gap,
    and retries on 429 using the ``retry-after`` response header.
    """
    global _last_request_ts

    key = api_key or settings.GROQ_API_KEY
    if not key:
        raise ValueError("GROQ_API_KEY not configured")
    m = model or settings.GROQ_MODEL

    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    payload: Dict[str, Any] = {
        "model": m,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        # --- rate-limit pacing ---
        async with _request_lock:
            now = time.monotonic()
            gap = now - _last_request_ts
            if gap < _MIN_REQUEST_INTERVAL:
                await asyncio.sleep(_MIN_REQUEST_INTERVAL - gap)
            _last_request_ts = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    GROQ_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("retry-after", _BASE_BACKOFF * (2 ** attempt)))
                wait = min(retry_after + 1.0, _MAX_BACKOFF)
                logger.warning(
                    "Groq 429 rate-limited (attempt %d/%d) — waiting %.1fs before retry",
                    attempt + 1, _MAX_RETRIES, wait,
                )
                await asyncio.sleep(wait)
                last_exc = httpx.HTTPStatusError(
                    f"429 Too Many Requests", request=resp.request, response=resp
                )
                continue

            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = (e.response.text or "")[:500]
                logger.warning("Groq HTTP error %s: %s", e.response.status_code, body)
                raise

            data = resp.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            text = _strip_json_fences(content)
            return json.loads(text)

        except httpx.HTTPStatusError:
            raise
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            wait = min(_BASE_BACKOFF * (2 ** attempt), _MAX_BACKOFF)
            logger.warning(
                "Groq transport error (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1, _MAX_RETRIES, exc, wait,
            )
            last_exc = exc
            await asyncio.sleep(wait)

    raise RuntimeError(f"Groq request failed after {_MAX_RETRIES} attempts") from last_exc
