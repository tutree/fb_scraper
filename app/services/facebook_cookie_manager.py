import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .fb_account_loader import _cookie_uid_order, _extract_c_user_from_cookie_json, load_accounts


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


def _normalize_cookie(cookie: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = cookie.get("name")
    value = cookie.get("value")
    domain = cookie.get("domain")
    path = cookie.get("path") or "/"

    if not name or value is None or not domain:
        return None

    expires = cookie.get("expires")
    if expires is None:
        expires = cookie.get("expirationDate")
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
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "secure": bool(cookie.get("secure", True)),
        "sameSite": _normalize_same_site(cookie.get("sameSite")),
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


def parse_cookie_json_text(cookie_json: str) -> Dict[str, Any]:
    try:
        raw_data = json.loads(cookie_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc.msg}") from exc

    cookies: List[Dict[str, Any]]
    origins: List[Dict[str, Any]] = []

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
    saved_cookies = parsed["saved_cookies"]

    COOKIE_DIR.mkdir(exist_ok=True)
    cookie_path = COOKIE_DIR / f"{account_uid}.json"
    with open(cookie_path, "w", encoding="utf-8") as f:
        json.dump(saved_cookies, f, indent=2)

    updated_at = datetime.fromtimestamp(cookie_path.stat().st_mtime, tz=timezone.utc).isoformat()
    active_account_uids = [str(account.get("uid", "")).strip() for account in load_accounts() if str(account.get("uid", "")).strip()]

    return {
        "account_uid": account_uid,
        "cookie_file": str(cookie_path),
        "cookie_count": len(saved_cookies),
        "updated_at": updated_at,
        "active_account_uids": active_account_uids,
    }


def get_cookie_status() -> Dict[str, Any]:
    active_account_uids = [str(account.get("uid", "")).strip() for account in load_accounts() if str(account.get("uid", "")).strip()]
    saved_cookie_uids = _cookie_uid_order()
    latest_cookie_uid = saved_cookie_uids[0] if saved_cookie_uids else None

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