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

        Returns:
            Dict with keys: type, confidence, reason
        """
        post_content = clean_facebook_post_content(post_content) or ""
        if not post_content.strip():
            return {
                "type": "UNKNOWN",
                "confidence": 0.0,
                "reason": "No post content available",
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
            logger.debug("Sending classification request for user: %s", user_name)
            result = await self._generate_json(prompt)
            logger.debug(
                "Classification result: %s (confidence: %.2f)",
                result["type"], result["confidence"],
            )
            return result

        except json.JSONDecodeError as e:
            logger.error("Failed to parse AI response as JSON: %s", e)
            return {
                "type": "UNKNOWN",
                "confidence": 0.0,
                "reason": f"Failed to parse AI response: {str(e)}",
            }
        except Exception as e:
            logger.error("AI classification error: %s", e, exc_info=True)
            return {
                "type": "UNKNOWN",
                "confidence": 0.0,
                "reason": f"Classification error: {str(e)}",
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

    async def classify_geo(
        self,
        location: str = "",
        post_content: str = "",
        user_name: str = "",
    ) -> Dict:
        """
        Determine whether a Facebook post is from a US-based user.

        Returns:
            Dict with keys: is_us (bool), confidence (float), reason (str)
        """
        post_content = clean_facebook_post_content(post_content) or ""

        if location and location.strip():
            prompt = f"""You are a geographic classifier. Given a Facebook user's location string, determine whether they are located in the United States.

Location: {location}
User: {user_name or "Unknown"}

Rules:
- If the location clearly refers to a US city, state, or territory → is_us = true
- If the location refers to a country outside the US (e.g. Philippines, Nigeria, India, UK, Canada, Pakistan, etc.) → is_us = false
- If the location is ambiguous (e.g. just a city name that exists in multiple countries), look at any post content for language clues
{f'Post content (for context): {post_content[:300]}' if post_content else ''}

Return ONLY valid JSON (no markdown):
{{"is_us": true, "confidence": 0.95, "reason": "Location is in Texas, USA"}}
"""
        elif post_content.strip():
            prompt = f"""You are a language and geographic classifier. This Facebook post has NO location information. Determine whether this post is likely from a US-based English-speaking user.

Post content: {post_content[:500]}
User: {user_name or "Unknown"}

Rules:
- If the post is written in English → is_us = true (likely US-based)
- If the post is written in a non-English language (Tagalog, Hindi, Urdu, French, Spanish from non-US context, Arabic, etc.) → is_us = false
- If the post mixes English with another language but is predominantly English → is_us = true
- If the post mentions non-US locations, currencies (PHP, INR, GBP, etc.), or clearly non-US context → is_us = false
- Short English posts with no geographic clues → is_us = true (benefit of the doubt)

Return ONLY valid JSON (no markdown):
{{"is_us": true, "confidence": 0.8, "reason": "Post is in English with no non-US indicators"}}
"""
        else:
            return {"is_us": True, "confidence": 0.3, "reason": "No location or content to classify"}

        try:
            if self.provider == "gemini":
                response = self.model.generate_content(prompt)
                response_text = response.text.strip()
            else:
                async with httpx.AsyncClient(timeout=120.0) as client:
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
            return {
                "is_us": bool(result.get("is_us", True)),
                "confidence": max(0.0, min(1.0, float(result.get("confidence", 0.5)))),
                "reason": str(result.get("reason", "")),
            }

        except Exception as e:
            logger.warning("Geo classification failed: %s", e)
            return {"is_us": True, "confidence": 0.0, "reason": f"Classification error: {e}"}

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
