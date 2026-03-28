"""
Facebook account loading and credential helpers.
"""
import json
import pyotp
from pathlib import Path
from typing import Dict, List, Optional

from ..core.config import settings
from ..core.logging_config import get_logger

logger = get_logger(__name__)

CREDENTIALS_PATH = Path("config/credentials.json")
ACCOUNTS_JSON_PATH = Path("config/accounts.json")

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


def remove_cookie_files_for_uid(uid: str) -> None:
    """Delete saved Playwright cookie JSON for ``uid`` from all known cookie dirs."""
    u = (uid or "").strip()
    if not u:
        return
    name = f"{u}.json"
    for directory in COOKIE_DIRS:
        path = directory / name
        if path.exists():
            try:
                path.unlink()
                logger.info("Removed stale cookie file (session invalid): %s", path)
            except OSError as exc:
                logger.warning("Could not remove cookie file %s: %s", path, exc)


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
    """Load accounts from config/accounts.json (flat list with uid/password/totp_secret)."""
    if not ACCOUNTS_JSON_PATH.exists():
        return []
    try:
        with open(ACCOUNTS_JSON_PATH, "r", encoding="utf-8") as f:
            accounts = json.load(f)
        valid = [a for a in accounts if a.get("uid") and a.get("password")]
        if valid and not _accounts_logged_once:
            logger.info("Loaded %d accounts from %s", len(valid), ACCOUNTS_JSON_PATH)
        return valid
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", ACCOUNTS_JSON_PATH, exc)
        return []


def load_accounts() -> List[Dict]:
    """Load Facebook accounts from credentials.json, prioritising cookie-backed UIDs.
    Falls back to config/accounts.json, then env variables."""
    global _accounts_logged_once
    verbose = not _accounts_logged_once

    if verbose:
        logger.info("Loading Facebook accounts from: %s", CREDENTIALS_PATH.absolute())
    if CREDENTIALS_PATH.exists():
        try:
            with open(CREDENTIALS_PATH, encoding="utf-8-sig") as f:
                data = json.load(f)
            all_accounts = data.get("facebook_accounts", [])
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
            logger.error("Failed to parse credentials file '%s': %s.", CREDENTIALS_PATH, exc)

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


def generate_2fa_code(totp_secret: str) -> str:
    return pyotp.TOTP(totp_secret).now()
