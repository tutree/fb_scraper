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

# Groq: global pacing via settings.GROQ_MIN_INTERVAL_SECONDS (default 3.5s).
_last_request_ts: float = 0.0
_request_lock = asyncio.Lock()

# Retry settings for 429 / transient errors
_MAX_RETRIES = 4
_BASE_BACKOFF = 5.0  # seconds — first retry wait before consulting retry-after
_MAX_BACKOFF = 60.0  # cap on any single wait


def _resolve_groq_keys(explicit: Optional[str]) -> List[str]:
    """Use a single explicit key, or all keys from settings (comma-separated)."""
    if explicit and str(explicit).strip():
        return [str(explicit).strip()]
    return list(settings.groq_api_keys)


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


def _parse_assistant_json(content: str) -> Dict[str, Any]:
    """Parse model output as JSON; tolerate leading/trailing prose via JSONDecoder.raw_decode."""
    text = _strip_json_fences(content)
    if not text:
        raise ValueError("empty assistant message")
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        idx = text.find("{")
        if idx < 0:
            raise ValueError("no JSON object in assistant message") from None
        try:
            out, _end = json.JSONDecoder().raw_decode(text, idx)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON in assistant message: {e}") from e
    if not isinstance(out, dict):
        raise ValueError("JSON root must be an object")
    return out


async def groq_chat_json(
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.2,
    use_json_object_mode: bool = True,
    debug_log_tag: Optional[str] = None,
) -> Dict[str, Any]:
    """Call Groq chat completions and parse the assistant message as JSON.

    Respects the 30 RPM rate limit by enforcing a minimum inter-request gap,
    and retries on 429 using the ``retry-after`` response header.

    If ``GROQ_API_KEY`` contains multiple comma-separated keys, the next key is
    used when Groq responds with 401/403 (expired or invalid key).
    """
    global _last_request_ts

    keys = _resolve_groq_keys(api_key)
    if not keys:
        raise ValueError("GROQ_API_KEY not configured")
    m = model or settings.GROQ_MODEL

    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    base_payload: Dict[str, Any] = {
        "model": m,
        "messages": messages,
        "temperature": temperature,
    }

    last_exc: Exception | None = None

    for key_index, key in enumerate(keys):
        key_label = f"{key_index + 1}/{len(keys)}"
        rotate_to_next_key = False
        for attempt in range(_MAX_RETRIES):
            # --- rate-limit pacing ---
            min_interval = float(settings.GROQ_MIN_INTERVAL_SECONDS)
            async with _request_lock:
                now = time.monotonic()
                gap = now - _last_request_ts
                if gap < min_interval:
                    await asyncio.sleep(min_interval - gap)
                _last_request_ts = time.monotonic()

            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    payload = dict(base_payload)
                    if use_json_object_mode:
                        payload["response_format"] = {"type": "json_object"}
                    resp = await client.post(
                        GROQ_CHAT_URL,
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    if resp.status_code == 400 and use_json_object_mode:
                        body = (resp.text or "")[:800]
                        logger.warning(
                            "Groq rejected json_object mode — retrying without (attempt %d): %s",
                            attempt + 1,
                            body,
                        )
                        resp = await client.post(
                            GROQ_CHAT_URL,
                            headers={
                                "Authorization": f"Bearer {key}",
                                "Content-Type": "application/json",
                            },
                            json=base_payload,
                        )

                    if resp.status_code in (401, 403):
                        body = (resp.text or "")[:500]
                        logger.warning(
                            "Groq API key %s rejected (HTTP %s): %s",
                            key_label,
                            resp.status_code,
                            body,
                        )
                        last_exc = httpx.HTTPStatusError(
                            f"HTTP {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )
                        rotate_to_next_key = True
                        break  # try next key

                    if resp.status_code == 429:
                        retry_after = float(
                            resp.headers.get("retry-after", _BASE_BACKOFF * (2**attempt))
                        )
                        wait = min(retry_after + 1.0, _MAX_BACKOFF)
                        logger.warning(
                            "Groq 429 rate-limited (key %s, attempt %d/%d) — waiting %.1fs before retry",
                            key_label,
                            attempt + 1,
                            _MAX_RETRIES,
                            wait,
                        )
                        await asyncio.sleep(wait)
                        last_exc = httpx.HTTPStatusError(
                            "429 Too Many Requests", request=resp.request, response=resp
                        )
                        continue

                    try:
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code in (401, 403):
                            body = (e.response.text or "")[:500]
                            logger.warning(
                                "Groq API key %s rejected (HTTP %s): %s",
                                key_label,
                                e.response.status_code,
                                body,
                            )
                            last_exc = e
                            rotate_to_next_key = True
                            break  # next key
                        body = (e.response.text or "")[:500]
                        logger.warning("Groq HTTP error %s: %s", e.response.status_code, body)
                        raise

                    data = resp.json()
                    choice0 = (data.get("choices") or [{}])[0]
                    msg = choice0.get("message") or {}
                    content = msg.get("content") or ""
                    finish_reason = choice0.get("finish_reason")
                    if not str(content).strip():
                        logger.warning(
                            "Groq empty assistant content (key %s, finish_reason=%s, attempt %d/%d)",
                            key_label,
                            finish_reason,
                            attempt + 1,
                            _MAX_RETRIES,
                        )
                        last_exc = ValueError("empty assistant content from Groq")
                        await asyncio.sleep(min(2.0 * (attempt + 1), 8.0))
                        continue
                    if debug_log_tag:
                        logger.info(
                            "[%s] groq HTTP response id=%r model=%r finish_reason=%r "
                            "raw_assistant_len=%d raw_assistant=%r",
                            debug_log_tag,
                            data.get("id"),
                            data.get("model"),
                            finish_reason,
                            len(content or ""),
                            (content or "")[:12_000],
                        )
                    try:
                        return _parse_assistant_json(content)
                    except ValueError as ve:
                        preview = (content or "")[:400].replace("\n", "\\n")
                        logger.warning(
                            "Groq JSON parse failed (%s) preview=%r — retrying",
                            ve,
                            preview,
                        )
                        last_exc = ve
                        await asyncio.sleep(min(1.5 * (attempt + 1), 6.0))
                        continue

            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code in (401, 403):
                    logger.warning(
                        "Groq API key %s rejected (HTTP %s): %s",
                        key_label,
                        e.response.status_code,
                        (e.response.text or "")[:500],
                    )
                    last_exc = e
                    rotate_to_next_key = True
                    break
                raise
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                wait = min(_BASE_BACKOFF * (2**attempt), _MAX_BACKOFF)
                logger.warning(
                    "Groq transport error (key %s, attempt %d/%d): %s — retrying in %.1fs",
                    key_label,
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    wait,
                )
                last_exc = exc
                await asyncio.sleep(wait)

        if rotate_to_next_key:
            continue
        # exhausted retries on this key without 401/403 (e.g. 429, empty body, parse errors)
        raise RuntimeError(
            f"Groq request failed after {_MAX_RETRIES} attempt(s) on key {key_label}"
        ) from last_exc

    raise RuntimeError(
        f"All {len(keys)} Groq API key(s) failed or were rejected (invalid/expired)"
    ) from last_exc
