"""Per-account proxy URLs (1:1 with Facebook UIDs). Stored in config/account_proxies.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from ..core.logging_config import get_logger

logger = get_logger(__name__)

ACCOUNT_PROXIES_PATH = Path("config/account_proxies.json")


def load_account_proxies() -> Dict[str, str]:
    """Return uid -> proxy URL string. Empty dict if file missing."""
    if not ACCOUNT_PROXIES_PATH.exists():
        return {}
    try:
        raw = json.loads(ACCOUNT_PROXIES_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, str] = {}
        for k, v in raw.items():
            ks = str(k).strip()
            vs = str(v).strip() if v is not None else ""
            if ks and vs:
                out[ks] = vs
        return out
    except Exception as exc:
        logger.warning("Could not read %s: %s", ACCOUNT_PROXIES_PATH, exc)
        return {}


def save_account_proxies(mapping: Dict[str, str]) -> None:
    """Write merged uid -> proxy map (overwrites file)."""
    ACCOUNT_PROXIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    clean = {str(k).strip(): str(v).strip() for k, v in mapping.items() if str(k).strip() and str(v).strip()}
    ACCOUNT_PROXIES_PATH.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    logger.info("Saved %d account proxy mapping(s) to %s", len(clean), ACCOUNT_PROXIES_PATH)


def merge_account_proxy(uid: str, proxy_url: str) -> Dict[str, str]:
    """Set one uid's proxy and return full map."""
    m = load_account_proxies()
    u = str(uid).strip()
    p = str(proxy_url).strip()
    if not u:
        return m
    if p:
        m[u] = p
    else:
        m.pop(u, None)
    save_account_proxies(m)
    return m
