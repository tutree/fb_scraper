import google.generativeai as genai
import json
from typing import Dict, Optional

import httpx

from ..core.config import settings
from ..core.logging_config import get_logger
from ..utils.validators import clean_facebook_post_content

logger = get_logger(__name__)


class GeminiClassifier:
    """
    Gemini AI classifier for analyzing Facebook posts to determine
    if users are looking for tutors (customers) or offering tutoring (tutors).
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.provider = (settings.AI_PROVIDER or "gemini").strip().lower()
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.ollama_base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.ollama_model = settings.OLLAMA_MODEL

        if self.provider == "gemini":
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY not configured")
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel("gemini-2.5-flash")
            logger.info("AI classifier using provider=gemini model=gemini-2.5-flash")
        elif self.provider == "ollama":
            self.model = None
            logger.info(
                "AI classifier using provider=ollama model=%s base_url=%s",
                self.ollama_model,
                self.ollama_base_url,
            )
        else:
            raise ValueError(f"Unsupported AI_PROVIDER: {self.provider}")

    async def _generate_json(self, prompt: str) -> Dict:
        if self.provider == "gemini":
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
        else:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(
                    f"{self.ollama_base_url}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )
                response.raise_for_status()
                data = response.json()
                response_text = (data.get("response") or "").strip()

        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        result = json.loads(response_text)
        if "type" not in result or "confidence" not in result:
            raise ValueError("Invalid response structure")
        result["type"] = result["type"].upper()
        result["confidence"] = max(0.0, min(1.0, float(result["confidence"])))
        return result
    
    async def classify_user(self, post_content: str, user_name: str = "") -> Dict:
        """
        Classify a user based on their post content.
        
        Args:
            post_content: The text content of the Facebook post
            user_name: Optional user name for context
            
        Returns:
            Dict with keys: type, confidence, reason
        """
        post_content = clean_facebook_post_content(post_content) or ""
        if not post_content.strip():
            return {
                "type": "UNKNOWN",
                "confidence": 0.0,
                "reason": "No post content available"
            }
        
        prompt = f"""You are analyzing a Facebook post scraped from a search results page. The raw text may contain Facebook UI artifacts such as repeated words like "Facebook", navigation labels ("Like", "Comment", "Share"), reaction counts, or timestamps mixed into the post body. Your first task is to mentally extract only the actual user-written post content, ignoring all UI noise.

User: {user_name if user_name else "Unknown"}
Raw scraped text: {post_content}

After extracting the real post content, classify the user:
- CUSTOMER: User is looking for a tutor, needs help, asking for tutoring recommendations, seeking educational services
- TUTOR: User is offering tutoring services, advertising their tutoring business, promoting their teaching
- UNKNOWN: Post is unclear, irrelevant, only contains UI noise with no real content, or doesn't clearly indicate either category

Return ONLY valid JSON in this exact format (no markdown, no extra text):
{{"type": "CUSTOMER", "confidence": 0.95, "reason": "User explicitly asks for a tutor"}}
"""
        
        try:
            logger.debug(f"Sending classification request for user: {user_name}")
            result = await self._generate_json(prompt)
            logger.debug(f"Classification result: {result['type']} (confidence: {result['confidence']:.2f})")
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            return {
                "type": "UNKNOWN",
                "confidence": 0.0,
                "reason": f"Failed to parse AI response: {str(e)}"
            }
        except Exception as e:
            logger.error(f"AI classification error: {e}", exc_info=True)
            return {
                "type": "UNKNOWN",
                "confidence": 0.0,
                "reason": f"Classification error: {str(e)}"
            }

    async def classify_comment_user(
        self,
        comment_text: str,
        author_name: str = "",
        post_context: str = "",
        search_keyword: str = "",
    ) -> Dict:
        """
        Classify a comment author as potential customer or tutor.
        post_context and search_keyword are used so the model understands
        what the commenter is replying to — a comment like "Yes please!"
        means something very different depending on the post it appears on.
        """
        if not comment_text or not comment_text.strip():
            return {"type": "UNKNOWN", "confidence": 0.0, "reason": "No comment text"}

        post_context = clean_facebook_post_content(post_context) or ""

        context_block = ""
        if search_keyword:
            context_block += f"Search keyword that found this post: {search_keyword}\n"
        if post_context:
            context_block += f"Post the comment appears on:\n{post_context[:600]}\n"

        prompt = f"""You are analyzing Facebook comments to find people who are looking for a tutor (CUSTOMER) or people offering tutoring services (TUTOR).

NOTE: The post context below was scraped from Facebook and may contain UI artifacts (repeated "Facebook" words, "Like", "Comment", "Share" buttons, reaction counts, timestamps). Ignore all such noise and focus on the actual user-written content.

{context_block}
Comment author: {author_name or "Unknown"}
Comment: {comment_text}

Classification rules:
- CUSTOMER: The commenter is looking for a tutor, asking for help, recommending someone, or expressing a need for tutoring.
- TUTOR: The commenter is offering tutoring, advertising services, or promoting their own teaching.
- UNKNOWN: The comment is a generic reply, off-topic, or impossible to classify reliably without more context.

Important context rule:
- If the post context is clearly from a tutor offering tutoring services, then short greeting or intent-to-connect comments (e.g. "hi", "hello", "interested", "dm", "inbox", "message me", "check dm") should usually be treated as CUSTOMER rather than UNKNOWN.
- Only classify as UNKNOWN for greetings when the post context is unclear or unrelated to tutoring.

Consider the post context when interpreting ambiguous comments like "Yes please!", "Me too", "DM sent", etc.

Return ONLY valid JSON, no markdown:
{{"type": "CUSTOMER", "confidence": 0.9, "reason": "Short explanation"}}
"""
        try:
            result = await self._generate_json(prompt)
            return result
        except (json.JSONDecodeError, ValueError, Exception) as e:
            logger.debug(f"Comment classification failed: {e}")
            return {"type": "UNKNOWN", "confidence": 0.0, "reason": str(e)[:200]}

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
