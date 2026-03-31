from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from typing import List, Optional
import json


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://user:pass@localhost:5432/math_tutor_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Facebook Credentials
    FACEBOOK_EMAIL: str = ""
    FACEBOOK_PASSWORD: str = ""

    # Proxy Configuration (comma-separated). With multiple accounts, 1st URL → Account 1, 2nd → Account 2, …
    PROXY_LIST: str = ""

    # API Settings
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Math Tutor Scraper API"
    DEBUG: bool = False

    # Authentication Settings
    SECRET_KEY: str = "729cf1fb8ef4bacc9f4addba0bb8eb5b3eb2b03fb4053d2bb0a0cfb2e3ac115a"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Scraper Settings
    MAX_RESULTS_PER_KEYWORD: int = 60
    SCRAPE_DELAY_MIN: int = 3  # seconds
    SCRAPE_DELAY_MAX: int = 8
    MAX_RETRIES: int = 3
    # Facebook search /posts: toggle "Posts You've Seen" switch to reduce repeat posts in results
    FB_SEARCH_ENABLE_POSTS_SEEN_FILTER: bool = True
    # When False (default), only saved cookies are used; password/captcha login is never attempted.
    FB_TRY_CREDENTIAL_LOGIN: bool = False
    # Sort search results by "Most Recent" instead of Facebook's default "Top Posts"
    FB_SEARCH_RECENT_POSTS: bool = True

    # AI provider: groq (default) or gemini
    AI_PROVIDER: str = "groq"

    # Gemini API
    GEMINI_API_KEY: str = ""

    # Groq (OpenAI-compatible API): queue/API classification and immediate on-save analysis when key is set.
    # Comma-separated list — first key is used until Groq returns 401/403, then the next key is tried.
    GROQ_API_KEY: str = ""
    # llama-3.1-8b-instant: 14 400 RPD vs 1 000 RPD for the 70b model — much more headroom
    GROQ_MODEL: str = "llama-3.1-8b-instant"
    # Minimum seconds between Groq API calls (global lock). Raise if 429s persist (default 3.5 ≈ 17 RPM).
    GROQ_MIN_INTERVAL_SECONDS: float = Field(default=3.5, ge=0.5, le=120.0)

    @field_validator("GROQ_MODEL", mode="before")
    @classmethod
    def _fix_groq_model_typo(cls, v: str) -> str:
        """Auto-correct common typos like 'lama-' → 'llama-'."""
        if isinstance(v, str) and v.startswith("lama-"):
            return "l" + v  # 'lama-...' → 'llama-...'
        return v

    # EnformionGO Contact Enrichment
    ENFORMION_AP_NAME: str = ""
    ENFORMION_AP_PASSWORD: str = ""

    # 2Captcha (for Facebook login captcha solving)
    CAPTCHA_2CAPTCHA_API_KEY: str = ""

    # Optional: writable path to keywords.json (required in Docker if the image's config/ is read-only).
    # Example: KEYWORDS_FILE_PATH=/data/keywords.json with a volume mount.
    KEYWORDS_FILE_PATH: str = ""

    # Optional: writable path for dashboard slot→Facebook UID bindings (defaults to config/account_scrape_slots.json).
    # In Docker, set to e.g. /data/account_scrape_slots.json so uploads work when ./config is a root-owned bind mount.
    ACCOUNT_SCRAPE_SLOTS_PATH: str = ""

    # Optional: writable path for credentials.json (facebook_accounts). Default: project config/credentials.json.
    # In Docker use /data/credentials.json (named volume) when ./config bind mount is not writable by the API user.
    CREDENTIALS_JSON_PATH: str = ""

    # Background automation (uses config/keywords.json). Off by default — set AUTO_SCRAPE_ENABLED=true in .env.
    AUTO_SCRAPE_ENABLED: bool = False
    # When auto-scrape is enabled, run once immediately on API startup (in addition to the interval). Default false.
    AUTO_SCRAPE_RUN_ON_STARTUP: bool = False
    AUTO_SCRAPE_INTERVAL_MINUTES: int = 180
    AUTO_SCRAPE_MAX_RESULTS: int = 60
    AUTO_ANALYZE_AFTER_SCRAPE: bool = True
    AUTO_ENRICH_AFTER_ANALYZE: bool = True

    # Default Keywords (fallback)
    DEFAULT_KEYWORDS: List[str] = [
        "looking for math tutor",
        "need math help",
        "math tutor needed",
    ]

    HEADLESS: bool = False

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def proxies(self) -> List[str]:
        return [p.strip() for p in self.PROXY_LIST.split(",") if p.strip()]

    @property
    def groq_api_keys(self) -> List[str]:
        """Non-empty Groq API keys from ``GROQ_API_KEY`` (comma-separated)."""
        return [k.strip() for k in (self.GROQ_API_KEY or "").split(",") if k.strip()]


settings = Settings()


def _project_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "config"


def keywords_json_path() -> Path:
    """Resolved path for keywords.json (settings.KEYWORDS_FILE_PATH or project config/keywords.json)."""
    raw = (settings.KEYWORDS_FILE_PATH or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _project_config_dir() / "keywords.json"


def account_scrape_slots_path() -> Path:
    """Resolved path for account_scrape_slots.json (env or project config/)."""
    raw = (settings.ACCOUNT_SCRAPE_SLOTS_PATH or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _project_config_dir() / "account_scrape_slots.json"


def legacy_account_scrape_slots_path() -> Path:
    """Bundled config path (read fallback when ACCOUNT_SCRAPE_SLOTS_PATH points elsewhere)."""
    return _project_config_dir() / "account_scrape_slots.json"


def credentials_json_path() -> Path:
    """Primary (writable) path for credentials.json — set CREDENTIALS_JSON_PATH in Docker for /data/..."""
    raw = (settings.CREDENTIALS_JSON_PATH or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _project_config_dir() / "credentials.json"


def legacy_credentials_json_path() -> Path:
    """Bundled repo path (read fallback when primary file does not exist yet)."""
    return _project_config_dir() / "credentials.json"


def ensure_keywords_file_seeded() -> None:
    """If ``KEYWORDS_FILE_PATH`` points to a missing or empty file, copy from bundled ``config/keywords.json``.

    Docker uses e.g. ``/data/keywords.json`` (writable volume); the image still ships ``config/keywords.json``
    — without this, the keywords UI shows empty until the user re-adds everything manually.
    """
    from .logging_config import get_logger

    log = get_logger(__name__)
    if not (settings.KEYWORDS_FILE_PATH or "").strip():
        return
    target = keywords_json_path()
    seed = Path(__file__).resolve().parents[2] / "config" / "keywords.json"
    if not seed.is_file():
        return
    try:
        seed_obj = json.loads(seed.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Could not read seed keywords at %s: %s", seed, exc)
        return
    seed_kws = seed_obj.get("searchKeywords") if isinstance(seed_obj, dict) else None
    if not isinstance(seed_kws, list) or not seed_kws:
        return

    need = False
    if not target.exists():
        need = True
    else:
        try:
            cur = json.loads(target.read_text(encoding="utf-8"))
            cur_kws = cur.get("searchKeywords") if isinstance(cur, dict) else None
            if not isinstance(cur_kws, list) or len(cur_kws) == 0:
                need = True
        except Exception:
            need = True

    if not need:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"searchKeywords": [str(k).strip() for k in seed_kws if str(k).strip()]}
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info(
            "Seeded keywords file at %s from %s (%d keywords)",
            target,
            seed,
            len(payload["searchKeywords"]),
        )
    except Exception as exc:
        log.warning("Could not seed keywords at %s: %s", target, exc)
