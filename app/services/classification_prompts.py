"""
Shared, strict definitions for CUSTOMER vs TUTOR used by Groq (immediate analysis)
and GeminiClassifier (queue/API). Single source of truth so behavior stays aligned.
"""
from typing import Any, Dict

# What “we” care about: leads who need tutoring vs providers who sell tutoring.

BUSINESS_CONTEXT = """Context: We run a tutoring business. We need accurate labels:
• CUSTOMER = someone who needs to RECEIVE tutoring (they want to hire, find, or get one-on-one academic help from a tutor).
• TUTOR = someone who PROVIDES or OFFERS tutoring/teaching to others (they sell, advertise, or deliver sessions as the instructor).
Be strict: label CUSTOMER or TUTOR only when the user’s role is explicit; otherwise use UNKNOWN. Do not default to CUSTOMER."""

POST_AUTHOR_STRICT_RULES = f"""{BUSINESS_CONTEXT}

How to read the post (ignore Facebook UI junk: “Like”, “Share”, reaction counts, repeated “Facebook”, timestamps).

CUSTOMER — Use ONLY if the post author clearly shows they (or their child) are SEEKING tutoring or one-on-one academic help from someone else. Examples: “looking for a math tutor”, “need a tutor for…”, “any recommendations for a tutor”, “hiring a tutor”, “DM me if you tutor…”, parent asking for a tutor. They are the party who wants to buy or receive tutoring.

TUTOR — Use ONLY if the post author clearly OFFERS or PROMOTES tutoring/teaching they deliver: “I tutor…”, rates, subjects taught, “book a session”, “my tutoring business”, recruiting students for their own teaching. They are the party who sells or provides tutoring.

UNKNOWN — Use when:
• Intent is unclear, off-topic, spam, memes, or only noise.
• General school/grades/homework talk without clearly seeking a tutor or clearly offering tutoring.
• Someone says they “teach” or work at a school but does not offer private tutoring in the post.
• You would be guessing between CUSTOMER and TUTOR.

Do NOT label CUSTOMER just because the post mentions education, kids, or stress. Do NOT label TUTOR just because someone sounds knowledgeable — they must clearly offer tutoring services.

Prefer UNKNOWN over a wrong CUSTOMER/TUTOR when evidence is weak.

TUTORING RELEVANCE (required JSON field tutoring_related):
• tutoring_related = true — The post is substantively about tutoring or private one-on-one academic help: seeking a tutor, offering tutoring, asking for/recommending tutors, or clearly discussing hiring or providing tutoring.
• tutoring_related = false — The post is NOT about tutoring: unrelated topics, spam, politics, selling non-tutoring goods, pure venting, generic school memes, job posts unrelated to tutoring, or noise with no real tutoring intent.

If the post is not about tutoring at all, set tutoring_related to false (type will usually be UNKNOWN). You MUST include tutoring_related in every JSON response alongside type, confidence, and reason."""

COMMENT_AUTHOR_STRICT_RULES = f"""{BUSINESS_CONTEXT}

You see a comment on a Facebook post (and the post text + prior post classification). Classify the COMMENT AUTHOR only.

CUSTOMER — The commenter clearly seeks tutoring or responds as a prospective student/client: wants the poster’s help as a tutor, asks to book, asks for a tutor, “looking for someone to tutor my kid”, “are you available”, “how much for lessons”, “interested” / “DM” ONLY when the post is clearly someone offering tutoring and the commenter is inquiring as a client. Short replies like “interested” or “DM” count as CUSTOMER only when the post is unambiguously a tutoring offer and the commenter is clearly responding as someone wanting that service.

TUTOR — The commenter promotes their own tutoring/teaching services in the thread (competing offer, “I also tutor…”, link to their page).

UNKNOWN — Generic (“thanks”, “lol”), unrelated, unclear, two people chatting without a clear seek/offer role, or you cannot tell if they need tutoring vs are just engaging. When the post context is not clearly a tutoring offer, do not infer CUSTOMER from vague short replies — use UNKNOWN.

Do NOT treat every friendly or vague comment as CUSTOMER. Be strict."""


def normalize_post_classification_fields(data: Dict[str, Any]) -> None:
    """
    Ensure tutoring_related is a bool. If the model omits it, default True (keep row)
    so we only remove rows when the model explicitly sets tutoring_related to false.
    Mutates data in place.
    """
    tr = data.get("tutoring_related")
    if tr is None:
        data["tutoring_related"] = True
    elif isinstance(tr, str):
        data["tutoring_related"] = tr.strip().lower() in ("true", "yes", "1")
    else:
        data["tutoring_related"] = bool(tr)


def should_remove_not_tutoring_related(data: Dict[str, Any]) -> bool:
    """True if analysis explicitly marks this post as not tutoring-related (delete row)."""
    if not isinstance(data, dict):
        return False
    normalize_post_classification_fields(data)
    return data.get("tutoring_related") is False
