"""Groq OpenAI-compatible chat API helper (JSON responses)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from ..core.config import settings
from ..core.logging_config import get_logger

logger = get_logger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


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
    """Call Groq chat completions and parse the assistant message as JSON."""
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

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            GROQ_CHAT_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
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
