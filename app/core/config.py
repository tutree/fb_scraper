from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import field_validator
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

    # Proxy Configuration
    PROXY_LIST: str = ""  # Comma-separated list of proxies

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

    # Background automation (runs automatically on startup, uses config/keywords.json)
    AUTO_SCRAPE_ENABLED: bool = True
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


def keywords_json_path() -> Path:
    """Resolved path for keywords.json (settings.KEYWORDS_FILE_PATH or project config/keywords.json)."""
    raw = (settings.KEYWORDS_FILE_PATH or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "config" / "keywords.json"
