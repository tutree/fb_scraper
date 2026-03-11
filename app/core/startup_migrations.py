from sqlalchemy import text

from .database import engine
from .logging_config import get_logger

logger = get_logger(__name__)


def run_startup_migrations() -> None:
    """Run lightweight idempotent schema migrations on startup."""
    if engine.dialect.name != "postgresql":
        logger.info(
            "Skipping startup migrations for non-PostgreSQL dialect: %s",
            engine.dialect.name,
        )
        return

    statements = [
        (
            "search_results.post_date",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS post_date VARCHAR NULL;",
        ),
    ]

    try:
        with engine.begin() as conn:
            for name, sql in statements:
                conn.execute(text(sql))
                logger.info("Startup migration ensured: %s", name)
    except Exception as exc:
        logger.exception("Startup migrations failed: %s", exc)
        raise
