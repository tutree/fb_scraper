"""
Gemini AI service for extracting structured data from HTML content.
"""
import google.generativeai as genai
from typing import List, Dict, Optional
import json
from ..core.config import settings
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class GeminiExtractor:
    def __init__(self):
        """Initialize Gemini API."""
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set, AI extraction will fail")
        else:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
            logger.info("Gemini AI initialized successfully with gemini-2.5-flash")

    async def extract_posts_from_html(self, full_html: str, keyword: str) -> List[Dict]:
        """
        Extract structured post data from entire HTML page using Gemini AI.
        
        Args:
            full_html: Complete HTML string from the page
            keyword: The search keyword for context
            
        Returns:
            List of extracted post dictionaries
        """
        if not settings.GEMINI_API_KEY:
            logger.error("Cannot extract posts: GEMINI_API_KEY not configured")
            return []
        
        logger.info(f"Sending HTML to Gemini AI for extraction (keyword: '{keyword}')...")
        
        prompt = f"""You are analyzing Facebook search results HTML for the keyword: "{keyword}"

I will provide you with the complete HTML from a Facebook search results page. Extract ALL posts that are relevant to the keyword "{keyword}".

For each post, extract:
1. **name**: The author's name (person or page who posted)
2. **content**: The main text content of the post
3. **post_url**: URL to the post (look for links with /posts/, /permalink/, /story.php)
4. **profile_url**: URL to the author's profile

CRITICAL RULES:
- Extract ALL relevant posts from the HTML
- Only include posts related to "{keyword}"
- If a field is not found, use null
- Return ONLY valid JSON array format
- Do not include markdown formatting or explanations

Expected JSON format:
[
  {{
    "name": "John Doe",
    "content": "Looking for a math tutor in St. Louis...",
    "post_url": "https://facebook.com/posts/123",
    "profile_url": "https://facebook.com/john.doe"
  }},
  {{
    "name": "Jane Smith",
    "content": "Need help with calculus...",
    "post_url": "https://facebook.com/posts/456",
    "profile_url": "https://facebook.com/jane.smith"
  }}
]

HTML Content:
{full_html}

Return ONLY the JSON array:"""

        try:
            logger.info("Calling Gemini API...")
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            logger.debug(f"Gemini response (first 500 chars): {response_text[:500]}")
            
            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            # Parse JSON
            posts = json.loads(response_text)
            
            if not isinstance(posts, list):
                logger.error(f"Expected list, got {type(posts)}")
                return []
            
            logger.info(f"✓ Gemini extracted {len(posts)} posts")
            
            # Validate and clean posts
            cleaned_posts = []
            for idx, post in enumerate(posts, 1):
                if isinstance(post, dict) and post.get('content'):
                    cleaned_post = {
                        'name': post.get('name') or 'Unknown',
                        'content': post.get('content', ''),
                        'url': post.get('post_url'),
                        'profileUrl': post.get('profile_url'),
                        'location': None
                    }
                    cleaned_posts.append(cleaned_post)
                    logger.debug(f"  Post {idx}: {cleaned_post['name'][:30]}...")
            
            logger.info(f"✓ Cleaned and validated {len(cleaned_posts)} posts")
            return cleaned_posts
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}")
            logger.debug(f"Response was: {response_text[:1000]}")
            return []
        except Exception as e:
            logger.error(f"Error calling Gemini API: {e}", exc_info=True)
            return []
