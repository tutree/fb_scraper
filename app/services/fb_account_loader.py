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


def load_accounts() -> List[Dict]:
    """Load Facebook accounts from credentials.json, prioritising cookie-backed UIDs."""
    logger.info(f"Loading Facebook accounts from: {CREDENTIALS_PATH.absolute()}")
    if CREDENTIALS_PATH.exists():
        try:
            with open(CREDENTIALS_PATH, encoding="utf-8-sig") as f:
                data = json.load(f)
            all_accounts = data.get("facebook_accounts", [])
            active_accounts = [a for a in all_accounts if a.get("active")]
            cookie_uid_order = _cookie_uid_order()
            logger.info(f"Found {len(all_accounts)} total accounts, {len(active_accounts)} active")
            if cookie_uid_order:
                logger.info(f"Found cookie sessions for {len(cookie_uid_order)} account uid(s)")
            selected_accounts: List[Dict] = []
            if active_accounts:
                active_by_uid = {
                    str(a.get("uid", "")).strip(): a
                    for a in active_accounts
                    if str(a.get("uid", "")).strip()
                }
                ordered_active = [active_by_uid[uid] for uid in cookie_uid_order if uid in active_by_uid]
                if ordered_active:
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
            for acc in selected_accounts:
                logger.info("  - Account: %s, 2FA configured: %s", acc.get("uid", "Unknown"), "Yes" if acc.get("totp_secret") else "No")
            return selected_accounts
        except Exception as exc:
            logger.error("Failed to parse credentials file '%s': %s. Falling back to env.", CREDENTIALS_PATH, exc)
    else:
        logger.warning(f"Credentials file not found at {CREDENTIALS_PATH}, using environment variables")
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
        logger.info("Using freshest cookie uid for env fallback account: %s", env_uid)

    env_account = {
        "uid": env_uid,
        "password": settings.FACEBOOK_PASSWORD,
        "totp_secret": None,
    }
    logger.info(f"Using env account: {env_account['uid']}")
    return [env_account]


def generate_2fa_code(totp_secret: str) -> str:
    return pyotp.TOTP(totp_secret).now()
