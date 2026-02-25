#!/usr/bin/env python3
"""Quick test of Gemini classification on posts with content."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import SessionLocal
from app.models.search_result import SearchResult
from app.services.gemini_classifier import GeminiClassifier

async def test():
    db = SessionLocal()
    classifier = GeminiClassifier()
    
    # Get posts with content that haven't been analyzed
    posts = db.query(SearchResult).filter(
        SearchResult.post_content != None,
        SearchResult.user_type == None
    ).limit(3).all()
    
    print(f"Found {len(posts)} posts with content to analyze\n")
    
    for i, post in enumerate(posts, 1):
        print(f"[{i}/{len(posts)}] {post.name}")
        print(f"  Content: {post.post_content[:150]}...")
        
        result = await classifier.classify_user(post.post_content, post.name)
        
        print(f"  Result: {result['type']} (confidence: {result['confidence']:.2f})")
        print(f"  Reason: {result.get('reason', 'N/A')}\n")
    
    db.close()

if __name__ == "__main__":
    asyncio.run(test())
