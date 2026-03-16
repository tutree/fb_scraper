"""
Migration script to add post_comments table
Run with: docker-compose run --rm api python scripts/migrate_add_comments_table.py
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.core.database import engine
from app.core.logging_config import get_logger

logger = get_logger(__name__)


def migrate():
    """Add post_comments table to store comments from Facebook posts"""
    
    logger.info("Starting migration: Adding post_comments table")
    
    with engine.connect() as conn:
        # Create post_comments table
        logger.info("Creating post_comments table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS post_comments (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                search_result_id UUID NOT NULL REFERENCES search_results(id) ON DELETE CASCADE,
                author_name VARCHAR,
                author_profile_url VARCHAR,
                comment_text TEXT,
                comment_timestamp VARCHAR,
                scraped_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        conn.commit()
        logger.info("✓ post_comments table created")
        
        # Create indexes
        logger.info("Creating indexes...")
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_post_comments_search_result_id 
            ON post_comments(search_result_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_post_comments_scraped_at 
            ON post_comments(scraped_at)
        """))
        conn.commit()
        logger.info("✓ Indexes created")
        
        logger.info("Migration completed successfully!")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)
