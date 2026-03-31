"""
Facebook account loading and credential helpers.
"""
import json
import pyotp
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.config import credentials_json_path, legacy_credentials_json_path, settings
from ..core.logging_config import get_logger

logger = get_logger(__name__)

ACCOUNTS_JSON_PATH = Path("config/accounts.json")


def _read_merged_credentials_dict() -> Dict[str, Any]:
    """Merge ``facebook_accounts`` from primary (CREDENTIALS_JSON_PATH) and legacy ``config/credentials.json`` by uid."""
    primary = credentials_json_path()
    legacy = legacy_credentials_json_path()
    env_raw = (getattr(settings, "CREDENTIALS_JSON_PATH", None) or "").strip()
    logger.info(
        "[credentials] merge: CREDENTIALS_JSON_PATH env=%r → primary=%s (exists=%s) | legacy=%s (exists=%s)",
        env_raw or "(unset, using project config/)",
        primary.resolve(),
        primary.is_file(),
        legacy.resolve(),
        legacy.is_file(),
    )
    by_uid: Dict[str, Dict[str, Any]] = {}
    # Legacy first, primary last so CREDENTIALS_JSON_PATH wins on duplicate UIDs.
    for path in (legacy, primary):
        label = "legacy" if path.resolve() == legacy.resolve() else "primary"
        if not path.is_file():
            logger.info("[credentials] merge: skip %s (missing): %s", label, path.resolve())
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[credentials] merge: skip %s (unreadable) %s: %s", label, path.resolve(), exc)
            continue
        if not isinstance(raw, dict):
            logger.warning("[credentials] merge: skip %s (not an object): %s", label, path.resolve())
            continue
        fa = raw.get("facebook_accounts")
        if not isinstance(fa, list):
            logger.warning("[credentials] merge: skip %s (facebook_accounts not a list): %s", label, path.resolve())
            continue
        for a in fa:
            if isinstance(a, dict) and str(a.get("uid", "")).strip():
                uid = str(a["uid"]).strip()
                by_uid[uid] = a
        uids_here = [str(x.get("uid", "")).strip() for x in fa if isinstance(x, dict)]
        logger.info(
            "[credentials] merge: loaded %s from %s (%d row(s); UIDs=%s)",
            label,
            path.resolve(),
            len(fa),
            uids_here,
        )
    merged = list(by_uid.values())
    logger.info("[credentials] merge: result %d unique account(s); UIDs=%s", len(merged), [str(x.get("uid")) for x in merged])
    return {"facebook_accounts": merged}


def _write_credentials_payload_to_all_paths(payload: str) -> bool:
    """Write the same JSON to primary and legacy paths so Docker /data and bind-mounted config stay aligned."""
    primary = credentials_json_path()
    legacy = legacy_credentials_json_path()
    paths = [primary]
    if legacy.resolve() != primary.resolve():
        paths.append(legacy)
    logger.info(
        "[credentials] write: %d byte(s) JSON → %d path(s): %s",
        len(payload.encode("utf-8")),
        len(paths),
        [str(p.resolve()) for p in paths],
    )
    ok_any = False
    failed: List[str] = []
    for p in paths:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(payload, encoding="utf-8")
            sz = p.stat().st_size
            logger.info("[credentials] write: OK %s (%d bytes on disk)", p.resolve(), sz)
            ok_any = True
        except OSError as exc:
            failed.append(f"{p.resolve()} ({exc})")
            logger.error("[credentials] write: FAILED %s — %s", p.resolve(), exc)
    if ok_any and failed:
        logger.warning(
            "[credentials] write: partial success — OK on at least one path; failed: %s",
            "; ".join(failed),
        )
    elif not ok_any:
        logger.error("[credentials] write: all paths failed: %s", "; ".join(failed) or "none")
    return ok_any


_accounts_logged_once = False
COOKIE_DIRS = [Path("cookies"), Path("config/cookies")]


def _extract_c_user_from_cookie_json(data: object) -> Optional[str]:
    if isinstance(data, dict):
        cookies = data.get("cookies")
        if not isinstance(cookies, list):
            return None
    elif isinstance(data, list):
        cookies = data
    else:
        return None
    for cookie in cookies:
        if isinstance(cookie, dict) and cookie.get("name") == "c_user":
            value = cookie.get("value")
            if value:
                return str(value)
    return None


def on_cookie_session_removed(uid: str) -> None:
    """After deleting a session file: sync config (accounts.json, credentials.json) and dashboard slots."""
    u = (uid or "").strip()
    if not u:
        return
    remove_accounts_json_entry_if_cookie_only(u)
    remove_credentials_entry_for_uid(u)
    from .account_scrape_slots import clear_uid_from_all_slots

    clear_uid_from_all_slots(u)


def remove_cookie_files_for_uid(uid: str) -> None:
    """Delete saved Playwright cookie JSON for ``uid`` from all known cookie dirs."""
    u = (uid or "").strip()
    if not u:
        return
    name = f"{u}.json"
    removed = False
    for directory in COOKIE_DIRS:
        path = directory / name
        if path.exists():
            try:
                path.unlink()
                removed = True
                logger.info("Removed stale cookie file (session invalid): %s", path)
            except OSError as exc:
                logger.warning("Could not remove cookie file %s: %s", path, exc)
    if removed:
        on_cookie_session_removed(u)


def _cookie_uid_order() -> List[str]:
    """Return cookie-backed account IDs ordered by freshest file first."""
    uid_mtime: Dict[str, float] = {}
    for directory in COOKIE_DIRS:
        if not directory.exists():
            continue
        for cookie_file in directory.glob("*.json"):
            try:
                mtime = cookie_file.stat().st_mtime
            except Exception:
                mtime = 0.0
            stem = cookie_file.stem.strip()
            if stem.isdigit():
                uid_mtime[stem] = max(uid_mtime.get(stem, 0.0), mtime)
            try:
                with open(cookie_file, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                c_user = _extract_c_user_from_cookie_json(data)
                if c_user:
                    uid_mtime[c_user] = max(uid_mtime.get(c_user, 0.0), mtime)
            except Exception:
                continue
    return [uid for uid, _ in sorted(uid_mtime.items(), key=lambda item: item[1], reverse=True)]


def _load_accounts_json() -> List[Dict]:
    """Load all account rows from config/accounts.json (uid required; password optional for cookie-only)."""
    if not ACCOUNTS_JSON_PATH.exists():
        return []
    try:
        with open(ACCOUNTS_JSON_PATH, "r", encoding="utf-8") as f:
            accounts = json.load(f)
        if not isinstance(accounts, list):
            return []
        valid: List[Dict] = []
        for a in accounts:
            if not isinstance(a, dict):
                continue
            uid = str(a.get("uid", "")).strip()
            if uid:
                valid.append(a)
        if valid and not _accounts_logged_once:
            logger.info("Loaded %d account row(s) from %s", len(valid), ACCOUNTS_JSON_PATH)
        return valid
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", ACCOUNTS_JSON_PATH, exc)
        return []


def _count_cookies_in_uid_file(uid: str) -> int:
    """Non-zero means this session file has exportable cookies (scrape-ready)."""
    u = (uid or "").strip()
    if not u:
        return 0
    for directory in COOKIE_DIRS:
        p = directory / f"{u}.json"
        if not p.is_file():
            continue
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and isinstance(raw.get("cookies"), list):
                return len(raw["cookies"])
            if isinstance(raw, list):
                return len(raw)
        except Exception:
            return 0
    return 0


def _cookie_uids_with_valid_cookie_files() -> List[str]:
    """UIDs with at least one cookie entry, freshest-first (same order as _cookie_uid_order)."""
    return [uid for uid in _cookie_uid_order() if _count_cookies_in_uid_file(uid) > 0]


def _merge_cookie_only_accounts(accounts: List[Dict]) -> List[Dict]:
    """Append minimal account dicts for UIDs that only exist as uploaded cookie files (no credentials row)."""
    seen = {str(a.get("uid", "")).strip() for a in accounts if str(a.get("uid", "")).strip()}
    out = list(accounts)
    for uid in _cookie_uids_with_valid_cookie_files():
        if uid not in seen:
            out.append({"uid": uid, "password": "", "totp_secret": None})
            seen.add(uid)
    return out


def ensure_accounts_json_entry_for_uid(uid: str) -> None:
    """After dashboard cookie upload: ensure accounts.json lists this UID (cookie-only row if new)."""
    u = str(uid).strip()
    if not u:
        return
    existing: List[Dict] = []
    if ACCOUNTS_JSON_PATH.exists():
        try:
            raw = json.loads(ACCOUNTS_JSON_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error(
                "Cannot update accounts.json — invalid JSON (%s). Fix %s manually, then upload again.",
                exc,
                ACCOUNTS_JSON_PATH,
            )
            return
        if not isinstance(raw, list):
            logger.error("accounts.json must be a JSON array — skipped ensure for uid %s", u)
            return
        existing = [a for a in raw if isinstance(a, dict) and str(a.get("uid", "")).strip()]
    if any(str(a.get("uid", "")).strip() == u for a in existing):
        logger.info(
            "[accounts.json] uid=%s already present (%d row(s)) — no change (%s)",
            u,
            len(existing),
            ACCOUNTS_JSON_PATH.resolve(),
        )
        return
    existing.append({"uid": u, "password": "", "totp_secret": None})
    ACCOUNTS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ACCOUNTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    logger.info(
        "[accounts.json] ADDED uid=%s → %s (now %d row(s))",
        u,
        ACCOUNTS_JSON_PATH.resolve(),
        len(existing),
    )


def ensure_credentials_json_entry_for_uid(uid: str) -> None:
    """After dashboard cookie upload: merge uid into ``facebook_accounts`` and write to all credential paths."""
    u = str(uid).strip()
    if not u:
        return
    logger.info("[credentials] ensure: start uid=%s", u)
    data = _read_merged_credentials_dict()
    accounts = [a for a in (data.get("facebook_accounts") or []) if isinstance(a, dict)]
    had_uid = any(str(a.get("uid", "")).strip() == u for a in accounts)
    if not had_uid:
        accounts.append(
            {
                "uid": u,
                "password": "",
                "totp_secret": None,
                "active": True,
            }
        )
        logger.info("[credentials] ensure: appended new facebook_accounts row for uid=%s", u)
    else:
        logger.info(
            "[credentials] ensure: uid=%s already in merged list — rewriting files to sync (%d account(s))",
            u,
            len(accounts),
        )
    data["facebook_accounts"] = accounts
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if not _write_credentials_payload_to_all_paths(payload):
        logger.error(
            "[credentials] ensure: FAILED uid=%s — check permissions or set CREDENTIALS_JSON_PATH=/data/credentials.json",
            u,
        )
    else:
        logger.info(
            "[credentials] ensure: DONE uid=%s — facebook_accounts count=%d (active UIDs=%s)",
            u,
            len(accounts),
            [str(x.get("uid")) for x in accounts],
        )


def remove_credentials_entry_for_uid(uid: str) -> None:
    """Remove ``uid`` from merged ``facebook_accounts`` and write to all credential paths."""
    u = str(uid).strip()
    if not u:
        return
    data = _read_merged_credentials_dict()
    accounts = [a for a in (data.get("facebook_accounts") or []) if isinstance(a, dict)]
    new_accounts = [a for a in accounts if str(a.get("uid", "")).strip() != u]
    if len(new_accounts) == len(accounts):
        return
    data["facebook_accounts"] = new_accounts
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    _write_credentials_payload_to_all_paths(payload)
    logger.info("Removed uid=%s from credentials (facebook_accounts)", u)


def remove_accounts_json_entry_if_cookie_only(uid: str) -> None:
    """When an uploaded session dies: drop passwordless row; keep rows that have a password (credential login)."""
    u = str(uid).strip()
    if not u or not ACCOUNTS_JSON_PATH.exists():
        return
    try:
        raw = json.loads(ACCOUNTS_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(raw, list):
        return
    changed = False
    new_list: List[Dict] = []
    for a in raw:
        if not isinstance(a, dict):
            new_list.append(a)
            continue
        if str(a.get("uid", "")).strip() != u:
            new_list.append(a)
            continue
        pwd = str(a.get("password") or "").strip()
        if pwd:
            new_list.append(a)
        else:
            changed = True
    if changed:
        ACCOUNTS_JSON_PATH.write_text(json.dumps(new_list, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        logger.info("Removed cookie-only account row for uid=%s from accounts.json", u)


def _load_accounts_inner() -> List[Dict]:
    """Resolve accounts from credentials / accounts.json / env (before cookie-file merge)."""
    global _accounts_logged_once
    verbose = not _accounts_logged_once

    cred_primary = credentials_json_path()
    cred_legacy = legacy_credentials_json_path()
    if verbose:
        logger.info(
            "Loading Facebook accounts (merged credentials): primary=%s legacy=%s",
            cred_primary.resolve(),
            cred_legacy.resolve(),
        )
    if cred_primary.is_file() or cred_legacy.is_file():
        try:
            data = _read_merged_credentials_dict()
            all_accounts = data.get("facebook_accounts") or []
            active_accounts = [a for a in all_accounts if a.get("active")]
            cookie_uid_order = _cookie_uid_order()
            if verbose:
                logger.info("Found %d total accounts, %d active", len(all_accounts), len(active_accounts))
                if cookie_uid_order:
                    logger.info("Found cookie sessions for %d account uid(s)", len(cookie_uid_order))
            selected_accounts: List[Dict] = []
            if active_accounts:
                active_by_uid = {
                    str(a.get("uid", "")).strip(): a
                    for a in active_accounts
                    if str(a.get("uid", "")).strip()
                }
                ordered_active = [active_by_uid[uid] for uid in cookie_uid_order if uid in active_by_uid]
                if ordered_active and verbose:
                    logger.info("Prioritizing active accounts with freshest cookies: %s", [a.get("uid") for a in ordered_active])
                merged = ordered_active + active_accounts
                deduped: List[Dict] = []
                seen: set = set()
                for account in merged:
                    uid = str(account.get("uid", "")).strip()
                    if not uid or uid in seen:
                        continue
                    seen.add(uid)
                    deduped.append(account)
                selected_accounts = deduped
            else:
                logger.warning("No active accounts found in credentials file")
                if cookie_uid_order:
                    account_by_uid = {
                        str(a.get("uid", "")).strip(): a
                        for a in all_accounts
                        if str(a.get("uid", "")).strip()
                    }
                    fallback = [account_by_uid[uid] for uid in cookie_uid_order if uid in account_by_uid]
                    if fallback:
                        logger.warning("Falling back to cookie-backed accounts: %s", [a.get("uid") for a in fallback])
                        selected_accounts = fallback
            if selected_accounts:
                if verbose:
                    for acc in selected_accounts:
                        logger.info("  - Account: %s, 2FA: %s", acc.get("uid", "Unknown"), "Yes" if acc.get("totp_secret") else "No")
                    _accounts_logged_once = True
                return selected_accounts
        except Exception as exc:
            logger.error("Failed to merge/parse credentials files: %s", exc)

    accounts_json = _load_accounts_json()
    if accounts_json:
        cookie_uid_order = _cookie_uid_order()
        if cookie_uid_order:
            by_uid = {str(a["uid"]).strip(): a for a in accounts_json}
            ordered = [by_uid[uid] for uid in cookie_uid_order if uid in by_uid]
            rest = [a for a in accounts_json if str(a["uid"]).strip() not in {str(o["uid"]).strip() for o in ordered}]
            accounts_json = ordered + rest
        if verbose:
            for acc in accounts_json:
                logger.info("  - Account: %s, 2FA: %s", acc.get("uid", "Unknown"), "Yes" if acc.get("totp_secret") else "No")
            _accounts_logged_once = True
        return accounts_json

    logger.warning("No credentials.json or accounts.json found, using environment variables")
    cookie_uid_order = _cookie_uid_order()
    env_uid = str(settings.FACEBOOK_EMAIL or "").strip()

    if env_uid and cookie_uid_order and env_uid not in cookie_uid_order:
        logger.warning(
            "FACEBOOK_EMAIL=%s has no saved cookie session. "
            "Switching to freshest cookie-backed account: %s",
            env_uid,
            cookie_uid_order[0],
        )
        env_uid = cookie_uid_order[0]
    elif not env_uid and cookie_uid_order:
        env_uid = cookie_uid_order[0]
        if verbose:
            logger.info("Using freshest cookie uid for env fallback account: %s", env_uid)

    env_account = {
        "uid": env_uid,
        "password": settings.FACEBOOK_PASSWORD,
        "totp_secret": None,
    }
    if verbose:
        logger.info("Using env account: %s", env_account["uid"])
    _accounts_logged_once = True
    return [env_account]


def load_accounts() -> List[Dict]:
    """Load Facebook accounts: credentials / accounts.json / env, plus any UID that only has an uploaded cookie file."""
    return _merge_cookie_only_accounts(_load_accounts_inner())


def generate_2fa_code(totp_secret: str) -> str:
    return pyotp.TOTP(totp_secret).now()


def list_accounts_with_cookie_files(accounts: List[Dict]) -> List[Dict]:
    """Keep only accounts that have a saved cookie JSON on disk (scrape-ready)."""
    cookie_uids = set(_cookie_uid_order())
    out: List[Dict] = []
    seen: set = set()
    for a in accounts:
        uid = str(a.get("uid", "")).strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        if uid in cookie_uids:
            out.append(a)
    return out


def ordered_accounts_with_proxy_slots() -> List[Tuple[Dict, Optional[int]]]:
    """(account dict, proxy_slot_index 0..3 or None).

    When ``config/account_scrape_slots.json`` has any non-empty **bindings** (UID per dashboard tab),
    scrape order follows slots 1→4. Each lane uses ``PROXY_LIST`` from .env by index: 1st account → 1st URL, etc.

    If no bindings are set, falls back to credential order via ``list_accounts_with_cookie_files``
    (proxy_slot_index None → per-UID ``account_proxies.json`` or ``PROXY_LIST`` round-robin).
    """
    from .account_scrape_slots import SLOT_COUNT, load_scrape_slots

    slots = load_scrape_slots()
    bindings = slots.get("bindings", [])
    cookie_uids = set(_cookie_uid_order())
    accounts_list = load_accounts()
    by_uid = {
        str(a.get("uid", "")).strip(): a
        for a in accounts_list
        if str(a.get("uid", "")).strip()
    }

    any_binding = False
    for i in range(min(SLOT_COUNT, len(bindings))):
        if (bindings[i] or "").strip():
            any_binding = True
            break

    out: List[Tuple[Dict, Optional[int]]] = []
    if any_binding:
        for i in range(min(SLOT_COUNT, len(bindings))):
            uid = (bindings[i] or "").strip()
            if not uid:
                continue
            if uid not in cookie_uids:
                continue
            acc = by_uid.get(uid)
            if not acc:
                acc = {"uid": uid, "password": "", "totp_secret": None}
            out.append((acc, i))
        if out:
            return out

    loose = list_accounts_with_cookie_files(accounts_list)
    return [(a, None) for a in loose]


def active_facebook_accounts_from_credentials() -> List[Dict]:
    """Active accounts from credentials.json (same rules as load_accounts ordering)."""
    return load_accounts()
