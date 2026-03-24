import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .fb_account_loader import _cookie_uid_order, _extract_c_user_from_cookie_json, load_accounts

logger = logging.getLogger(__name__)

COOKIE_DIR = Path("cookies")


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

    updated_at = datetime.fromtimestamp(cookie_path.stat().st_mtime, tz=timezone.utc).isoformat()
    active_account_uids = [str(account.get("uid", "")).strip() for account in load_accounts() if str(account.get("uid", "")).strip()]

    cookie_count = len(storage_state.get("cookies", []))

    return {
        "account_uid": account_uid,
        "cookie_file": str(cookie_path),
        "cookie_count": cookie_count,
        "updated_at": updated_at,
        "active_account_uids": active_account_uids,
    }


def get_cookie_status() -> Dict[str, Any]:
    active_account_uids = [str(account.get("uid", "")).strip() for account in load_accounts() if str(account.get("uid", "")).strip()]
    saved_cookie_uids = _cookie_uid_order()
    latest_cookie_uid = saved_cookie_uids[0] if saved_cookie_uids else None

    logger.debug(
        "Cookie status check: active_accounts=%s, saved_uids=%s, latest=%s, cookie_dir=%s (exists=%s)",
        active_account_uids,
        saved_cookie_uids,
        latest_cookie_uid,
        COOKIE_DIR.absolute(),
        COOKIE_DIR.exists(),
    )

    cookie_file = None
    updated_at = None
    cookie_count = 0
    if latest_cookie_uid:
        cookie_path = COOKIE_DIR / f"{latest_cookie_uid}.json"
        if cookie_path.exists():
            cookie_file = str(cookie_path)
            updated_at = datetime.fromtimestamp(cookie_path.stat().st_mtime, tz=timezone.utc).isoformat()
            try:
                with open(cookie_path, "r", encoding="utf-8-sig") as f:
                    raw_data = json.load(f)
                if isinstance(raw_data, dict) and isinstance(raw_data.get("cookies"), list):
                    cookie_count = len(raw_data.get("cookies", []))
                elif isinstance(raw_data, list):
                    cookie_count = len(raw_data)
            except Exception:
                cookie_count = 0

    return {
        "active_account_uids": active_account_uids,
        "saved_cookie_uids": saved_cookie_uids,
        "latest_cookie_uid": latest_cookie_uid,
        "cookie_file": cookie_file,
        "updated_at": updated_at,
        "cookie_count": cookie_count,
    }