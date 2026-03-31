"""Dashboard tab → Facebook UID bindings (Account 1–4). Proxies come from PROXY_LIST in .env (comma-separated)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from ..core.config import account_scrape_slots_path, legacy_account_scrape_slots_path
from ..core.logging_config import get_logger

logger = get_logger(__name__)

SLOT_COUNT = 4


def _slots_read_path() -> Path:
    """Prefer configured path; if missing, fall back to bundled config/ (Docker migration)."""
    primary = account_scrape_slots_path()
    if primary.exists():
        return primary
    leg = legacy_account_scrape_slots_path()
    if leg.exists() and leg.resolve() != primary.resolve():
        return leg
    return primary


def _slots_write_path() -> Path:
    return account_scrape_slots_path()


def _pad_bindings(v: List[str]) -> List[str]:
    out = list(v)[:SLOT_COUNT]
    while len(out) < SLOT_COUNT:
        out.append("")
    return out


def load_scrape_slots() -> Dict[str, List[str]]:
    """bindings[i] = Facebook UID saved from Account tab i+1."""
    path = _slots_read_path()
    if not path.exists():
        return {"bindings": [""] * SLOT_COUNT}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"bindings": [""] * SLOT_COUNT}
        b = raw.get("bindings")
        if not isinstance(b, list):
            b = []
        return {"bindings": _pad_bindings([str(x).strip() if x is not None else "" for x in b])}
    except Exception as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return {"bindings": [""] * SLOT_COUNT}


def save_bindings_only(bindings: List[str]) -> None:
    path = _slots_write_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"bindings": _pad_bindings(list(bindings))}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Saved scrape slot bindings to %s", path)


def clear_uid_from_all_slots(uid: str) -> None:
    """Remove ``uid`` from every dashboard slot (e.g. expired cookie file deleted)."""
    u = str(uid).strip()
    if not u:
        return
    data = load_scrape_slots()
    bindings = _pad_bindings(list(data["bindings"]))
    changed = False
    for i in range(len(bindings)):
        if bindings[i] == u:
            bindings[i] = ""
            changed = True
    if changed:
        save_bindings_only(bindings)
        logger.info("Cleared uid=%s from scrape slot bindings", u)


def set_binding_slot(slot_index: int, uid: str) -> Dict[str, List[str]]:
    """slot_index 0..3 — which Facebook UID was saved from that dashboard tab."""
    data = load_scrape_slots()
    if not 0 <= slot_index < SLOT_COUNT:
        return data
    bindings = _pad_bindings(list(data["bindings"]))
    u = str(uid).strip()
    bindings[slot_index] = u if u else ""
    data["bindings"] = bindings
    save_bindings_only(bindings)
    return data
