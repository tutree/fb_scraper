"""Hard-delete SearchResult rows and dependent comments (same behavior as geo / relevance removal)."""
from sqlalchemy.orm import Session

from ..models.post_comment import PostComment
from ..models.search_result import SearchResult


def delete_search_result_and_comments(db: Session, result: SearchResult) -> int:
    """
    Delete all comments for this result, then the result row.
    Returns the number of comment rows deleted.
    """
    rid = result.id
    n = (
        db.query(PostComment)
        .filter(PostComment.search_result_id == rid)
        .delete(synchronize_session=False)
    )
    db.delete(result)
    return n
