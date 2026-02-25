import google.generativeai as genai
import json
from typing import Dict, Optional
from ..core.config import settings
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class GeminiClassifier:
    """
    Gemini AI classifier for analyzing Facebook posts to determine
    if users are looking for tutors (customers) or offering tutoring (tutors).
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not configured")
        
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        logger.info("GeminiClassifier initialized with gemini-2.5-flash-latest model")
    
    async def classify_user(self, post_content: str, user_name: str = "") -> Dict:
        """
        Classify a user based on their post content.
        
        Args:
            post_content: The text content of the Facebook post
            user_name: Optional user name for context
            
        Returns:
            Dict with keys: type, confidence, reason
        """
        if not post_content or not post_content.strip():
            return {
                "type": "UNKNOWN",
                "confidence": 0.0,
                "reason": "No post content available"
            }
        
        prompt = f"""
Analyze this Facebook post about math tutoring and classify the user.

User: {user_name if user_name else "Unknown"}
Post: {post_content}

Classification Rules:
- CUSTOMER: User is looking for a math tutor, needs help with math, asking for tutoring recommendations
- TUTOR: User is offering tutoring services, advertising their tutoring business, promoting their teaching
- UNKNOWN: Post is unclear, irrelevant, or doesn't clearly indicate either category

Return ONLY valid JSON in this exact format (no markdown, no extra text):
{{"type": "CUSTOMER", "confidence": 0.95, "reason": "User explicitly asks for math tutor"}}

Analyze now:
"""
        
        try:
            logger.debug(f"Sending classification request for user: {user_name}")
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            result = json.loads(response_text)
            
            # Validate response structure
            if "type" not in result or "confidence" not in result:
                raise ValueError("Invalid response structure")
            
            # Normalize type to uppercase
            result["type"] = result["type"].upper()
            
            # Ensure confidence is between 0 and 1
            result["confidence"] = max(0.0, min(1.0, float(result["confidence"])))
            
            logger.info(f"Classification result: {result['type']} (confidence: {result['confidence']:.2f})")
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}")
            logger.error(f"Response text: {response_text if 'response_text' in locals() else 'N/A'}")
            return {
                "type": "UNKNOWN",
                "confidence": 0.0,
                "reason": f"Failed to parse AI response: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Gemini classification error: {e}", exc_info=True)
            return {
                "type": "UNKNOWN",
                "confidence": 0.0,
                "reason": f"Classification error: {str(e)}"
            }
    
    async def batch_classify(self, posts: list) -> list:
        """
        Classify multiple posts in batch.
        
        Args:
            posts: List of dicts with 'post_content' and optionally 'user_name'
            
        Returns:
            List of classification results
        """
        results = []
        for post in posts:
            result = await self.classify_user(
                post.get('post_content', ''),
                post.get('user_name', '')
            )
            results.append(result)
        
        return results
