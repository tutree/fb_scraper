from pydantic_settings import BaseSettings
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
    MAX_RESULTS_PER_KEYWORD: int = 100
    SCRAPE_DELAY_MIN: int = 3  # seconds
    SCRAPE_DELAY_MAX: int = 8
    MAX_RETRIES: int = 3

    # AI provider
    AI_PROVIDER: str = "ollama"

    # Gemini API
    GEMINI_API_KEY: str = ""

    # Ollama
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "gemma3:4b"

    # EnformionGO Contact Enrichment
    ENFORMION_AP_NAME: str = ""
    ENFORMION_AP_PASSWORD: str = ""

    # Background automation (runs automatically on startup, uses config/keywords.json)
    AUTO_SCRAPE_ENABLED: bool = True
    AUTO_SCRAPE_INTERVAL_MINUTES: int = 60
    AUTO_SCRAPE_MAX_RESULTS: int = 20
    AUTO_ANALYZE_AFTER_SCRAPE: bool = True
    AUTO_ENRICH_AFTER_ANALYZE: bool = True

    # Default Keywords (fallback)
    DEFAULT_KEYWORDS: List[str] = [
        "looking for math tutor",
        "need math help",
        "math tutor needed",
    ]

    class Config:
        env_file = ".env"

    @property
    def proxies(self) -> List[str]:
        return [p.strip() for p in self.PROXY_LIST.split(",") if p.strip()]


settings = Settings()
