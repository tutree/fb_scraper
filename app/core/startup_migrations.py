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
            "admin_users.role",
            "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role VARCHAR NOT NULL DEFAULT 'user';",
        ),
        (
            "admin_users.admin_role_for_admin",
            "UPDATE admin_users SET role = 'admin' WHERE username = 'admin' AND role = 'user';",
        ),
        (
            "search_results.post_date",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS post_date VARCHAR NULL;",
        ),
        (
            "search_results.post_date_timestamp",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS post_date_timestamp TIMESTAMP WITH TIME ZONE NULL;",
        ),
        (
            "search_results.enrichable",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS enrichable BOOLEAN NULL;",
        ),
        (
            "search_results.enriched_phones",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS enriched_phones JSONB NULL;",
        ),
        (
            "search_results.enriched_emails",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS enriched_emails JSONB NULL;",
        ),
        (
            "search_results.enriched_addresses",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS enriched_addresses JSONB NULL;",
        ),
        (
            "search_results.enriched_age",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS enriched_age VARCHAR NULL;",
        ),
        (
            "search_results.enriched_at",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMP WITH TIME ZONE NULL;",
        ),
        (
            "search_results.is_us",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS is_us BOOLEAN NULL;",
        ),
        (
            "search_results.geo_filtered_at",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS geo_filtered_at TIMESTAMP WITH TIME ZONE NULL;",
        ),
        (
            "search_results.archived",
            "ALTER TABLE search_results ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT false;",
        ),
        (
            "post_comments.archived",
            "ALTER TABLE post_comments ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT false;",
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
