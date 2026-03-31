import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .fb_account_loader import (
    COOKIE_DIRS,
    _cookie_uid_order,
    _extract_c_user_from_cookie_json,
    ensure_accounts_json_entry_for_uid,
    ensure_credentials_json_entry_for_uid,
    load_accounts,
)

logger = logging.getLogger(__name__)

COOKIE_DIR = Path("cookies")


def _resolve_cookie_path_for_uid(uid: str) -> Optional[Path]:
    for directory in COOKIE_DIRS:
        candidate = directory / f"{uid.strip()}.json"
        if candidate.exists():
            return candidate
    return None


def _count_cookies_in_file(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw_data = json.load(f)
        if isinstance(raw_data, dict) and isinstance(raw_data.get("cookies"), list):
            return len(raw_data.get("cookies", []))
        if isinstance(raw_data, list):
            return len(raw_data)
    except Exception:
        return 0
    return 0


def _normalize_same_site(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if raw == "lax":
        return "Lax"
    if raw == "strict":
        return "Strict"
    return "None"


def _legacy_same_site(value: Optional[str]) -> Optional[str]:
    raw = (value or "").strip().lower()
    if raw == "lax":
        return "lax"
    if raw == "strict":
        return "strict"
    if raw in {"none", "no_restriction", "no restriction"}:
        return "no_restriction"
    return None


def _get_ci(cookie: Dict[str, Any], *keys: str, default=None):
    """Case-insensitive dict lookup across multiple possible key names."""
    lower_map = {k.lower(): v for k, v in cookie.items()}
    for key in keys:
        val = lower_map.get(key.lower())
        if val is not None:
            return val
    return default


def _normalize_cookie(cookie: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = _get_ci(cookie, "name")
    value = _get_ci(cookie, "value")
    domain = _get_ci(cookie, "domain", "host", "host_raw", "hostraw")
    path = _get_ci(cookie, "path") or "/"

    if not name or value is None or not domain:
        return None

    expires = _get_ci(cookie, "expires", "expirationdate", "expiry", "expiration")
    if expires is None:
        expires = -1

    try:
        expires = float(expires)
    except Exception:
        expires = -1

    return {
        "name": str(name),
        "value": str(value),
        "domain": str(domain),
        "path": str(path),
        "expires": expires,
        "httpOnly": bool(_get_ci(cookie, "httponly", "httpOnly", "http_only", default=False)),
        "secure": bool(_get_ci(cookie, "secure", "isSecure", default=True)),
        "sameSite": _normalize_same_site(_get_ci(cookie, "samesite", "sameSite", "same_site")),
    }


def _to_saved_cookie(cookie: Dict[str, Any]) -> Dict[str, Any]:
    domain = str(cookie.get("domain"))
    expires = cookie.get("expires", -1)
    try:
        expires = float(expires)
    except Exception:
        expires = -1.0

    session = bool(cookie.get("session", expires < 0))
    saved_cookie: Dict[str, Any] = {
        "domain": domain,
        "hostOnly": bool(cookie.get("hostOnly", not domain.startswith("."))),
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "name": str(cookie.get("name")),
        "path": str(cookie.get("path") or "/"),
        "sameSite": _legacy_same_site(cookie.get("sameSite")),
        "secure": bool(cookie.get("secure", True)),
        "session": session,
        "storeId": cookie.get("storeId", None),
        "value": str(cookie.get("value")),
    }
    if not session and expires >= 0:
        saved_cookie["expirationDate"] = expires
    return saved_cookie


def _parse_netscape_cookies(text: str) -> List[Dict[str, Any]]:
    """Parse Netscape/Mozilla tab-separated cookie format.
    Format: domain \\t includeSubdomains \\t path \\t isSecure \\t expiry \\t name \\t value
    Some exports have extra fields; we handle 7+ fields.
    """
    cookies = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain = parts[0]
        path = parts[2]
        secure = parts[3].upper() == "TRUE"
        try:
            expiry = float(parts[4])
        except (ValueError, TypeError):
            expiry = -1
        name = parts[5]
        value = parts[6]
        if not name or not domain:
            continue
        cookies.append({
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
            "secure": secure,
            "expires": expiry,
            "httpOnly": False,
        })
    return cookies


def parse_cookie_json_text(cookie_json: str) -> Dict[str, Any]:
    cookies: List[Dict[str, Any]]
    origins: List[Dict[str, Any]] = []
    raw_data = None

    try:
        raw_data = json.loads(cookie_json)
    except json.JSONDecodeError:
        pass

    if raw_data is not None:
        if isinstance(raw_data, dict) and isinstance(raw_data.get("cookies"), list):
            cookies = raw_data.get("cookies", [])
            maybe_origins = raw_data.get("origins")
            if isinstance(maybe_origins, list):
                origins = maybe_origins
        elif isinstance(raw_data, list):
            cookies = raw_data
        else:
            raise HTTPException(
                status_code=400,
                detail="Cookie JSON must be a raw cookie array or a Playwright storage_state object.",
            )
    else:
        cookies = _parse_netscape_cookies(cookie_json)
        if not cookies:
            raise HTTPException(
                status_code=400,
                detail="Could not parse cookies. Accepted formats: JSON cookie array, Playwright storage_state, or Netscape tab-separated.",
            )

    normalized = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        item = _normalize_cookie(cookie)
        if item:
            normalized.append(item)

    if not normalized:
        raise HTTPException(status_code=400, detail="No valid Facebook cookies were found in the pasted JSON.")

    c_user = _extract_c_user_from_cookie_json(normalized)
    if not c_user:
        raise HTTPException(status_code=400, detail="The pasted cookie JSON does not contain a c_user cookie.")

    return {
        "account_uid": c_user,
        "saved_cookies": [_to_saved_cookie(cookie) for cookie in normalized],
        "storage_state": {
            "cookies": normalized,
            "origins": origins,
        },
    }


def save_cookie_json_text(cookie_json: str) -> Dict[str, Any]:
    parsed = parse_cookie_json_text(cookie_json)
    account_uid = parsed["account_uid"]
    storage_state = parsed["storage_state"]

    COOKIE_DIR.mkdir(exist_ok=True)
    cookie_path = COOKIE_DIR / f"{account_uid}.json"

    logger.info(
        "Saving cookie session for account %s to %s (cookies=%d, origins=%d)",
        account_uid,
        cookie_path.absolute(),
        len(storage_state.get("cookies", [])),
        len(storage_state.get("origins", [])),
    )

    with open(cookie_path, "w", encoding="utf-8") as f:
        json.dump(storage_state, f, indent=2)

    if cookie_path.exists():
        logger.info("Cookie file written successfully: %s (%d bytes)", cookie_path, cookie_path.stat().st_size)
    else:
        logger.error("Cookie file NOT found after write: %s", cookie_path)

    logger.info(
        "[cookie-upload] uid=%s — syncing config (accounts.json + credentials.json paths below)",
        account_uid,
    )
    ensure_accounts_json_entry_for_uid(account_uid)
    ensure_credentials_json_entry_for_uid(account_uid)
    logger.info("[cookie-upload] uid=%s — config sync finished", account_uid)

    updated_at = datetime.fromtimestamp(cookie_path.stat().st_mtime, tz=timezone.utc).isoformat()
    active_account_uids = [str(account.get("uid", "")).strip() for account in load_accounts() if str(account.get("uid", "")).strip()]
    logger.info(
        "[cookie-upload] uid=%s — load_accounts() → %d account(s): %s",
        account_uid,
        len(active_account_uids),
        active_account_uids,
    )

    cookie_count = len(storage_state.get("cookies", []))

    return {
        "account_uid": account_uid,
        "cookie_file": str(cookie_path),
        "cookie_count": cookie_count,
        "updated_at": updated_at,
        "active_account_uids": active_account_uids,
    }


def get_cookie_status() -> Dict[str, Any]:
    saved_cookie_uids = _cookie_uid_order()
    latest_cookie_uid = saved_cookie_uids[0] if saved_cookie_uids else None

    # Per-UID counts (freshest-first order). The "latest" file alone can be empty/corrupt while older UIDs are valid.
    per_uid_counts: Dict[str, int] = {}
    for uid in saved_cookie_uids:
        p = _resolve_cookie_path_for_uid(uid)
        if p:
            per_uid_counts[uid] = _count_cookies_in_file(p)

    sessions_with_cookies = sum(1 for n in per_uid_counts.values() if n > 0)
    total_cookie_entries = sum(per_uid_counts.values())
    has_valid_cookies = sessions_with_cookies > 0

    # UI: sessions that actually have cookies (upload-managed); not only credential-configured UIDs.
    active_account_uids = [uid for uid in saved_cookie_uids if per_uid_counts.get(uid, 0) > 0]

    # Primary row for UI: first UID in freshness order that actually has cookies; else show latest file even if broken
    primary_uid: Optional[str] = None
    for uid in saved_cookie_uids:
        if per_uid_counts.get(uid, 0) > 0:
            primary_uid = uid
            break
    if primary_uid is None:
        primary_uid = latest_cookie_uid

    cookie_file = None
    updated_at = None
    cookie_count = 0
    if primary_uid:
        cookie_path = _resolve_cookie_path_for_uid(primary_uid)
        if cookie_path:
            cookie_file = str(cookie_path)
            updated_at = datetime.fromtimestamp(cookie_path.stat().st_mtime, tz=timezone.utc).isoformat()
            cookie_count = per_uid_counts.get(primary_uid, _count_cookies_in_file(cookie_path))

    logger.debug(
        "Cookie status: active=%s, saved_uids=%s, latest=%s, has_valid=%s, sessions=%s, total_entries=%s",
        active_account_uids,
        saved_cookie_uids,
        latest_cookie_uid,
        has_valid_cookies,
        sessions_with_cookies,
        total_cookie_entries,
    )

    return {
        "active_account_uids": active_account_uids,
        "saved_cookie_uids": saved_cookie_uids,
        "latest_cookie_uid": latest_cookie_uid,
        "cookie_file": cookie_file,
        "updated_at": updated_at,
        "cookie_count": cookie_count,
        "has_valid_cookies": has_valid_cookies,
        "sessions_with_cookies": sessions_with_cookies,
        "total_cookie_entries": total_cookie_entries,
    }