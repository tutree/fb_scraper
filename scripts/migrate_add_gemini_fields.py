#!/usr/bin/env python3
"""
Database migration to add Gemini AI classification fields.
Run this once to update the database schema.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import engine
from sqlalchemy import text

def migrate():
    """Add new columns for Gemini classification."""
    
    migrations = [
        # Drop existing enum if it exists
        """
        DROP TYPE IF EXISTS usertype CASCADE;
        """,
        
        # Add user_type enum with lowercase values
        """
        CREATE TYPE usertype AS ENUM ('customer', 'tutor', 'unknown');
        """,
        
        # Add user_type column
        """
        ALTER TABLE search_results 
        ADD COLUMN IF NOT EXISTS user_type usertype;
        """,
        
        # Add gemini_analysis column
        """
        ALTER TABLE search_results 
        ADD COLUMN IF NOT EXISTS gemini_analysis JSONB;
        """,
        
        # Add confidence_score column
        """
        ALTER TABLE search_results 
        ADD COLUMN IF NOT EXISTS confidence_score FLOAT;
        """,
        
        # Add analyzed_at column
        """
        ALTER TABLE search_results 
        ADD COLUMN IF NOT EXISTS analyzed_at TIMESTAMP WITH TIME ZONE;
        """,
        
        # Add indexes
        """
        CREATE INDEX IF NOT EXISTS idx_search_results_user_type 
        ON search_results(user_type);
        """,
        
        """
        CREATE INDEX IF NOT EXISTS idx_search_results_analyzed_at 
        ON search_results(analyzed_at);
        """,
    ]
    
    with engine.connect() as conn:
        print("Running database migrations...")
        
        for idx, migration in enumerate(migrations, 1):
            try:
                print(f"  [{idx}/{len(migrations)}] Executing migration...")
                conn.execute(text(migration))
                conn.commit()
                print(f"  ✓ Migration {idx} completed")
            except Exception as e:
                print(f"  ✗ Migration {idx} failed: {e}")
                conn.rollback()
        
        print("\n✓ All migrations completed!")


if __name__ == "__main__":
    migrate()
