"""Pure URL helpers for Facebook (no Playwright)."""
import re
from typing import Optional

_GROUP_MEMBER_USER_RE = re.compile(r"/groups/[^/]+/user/(\d+)", re.IGNORECASE)


def profile_url_from_group_member_url(url: str) -> Optional[str]:
    """
    If *url* is a group-scoped member link like /groups/<gid>/user/<numeric_id>/,
    return https://www.facebook.com/profile.php?id=<numeric_id> for direct navigation.

    Facebook often omits or changes the "View profile" control on this overlay; the
    numeric id in the path still identifies the account.
    """
    if not url or not isinstance(url, str):
        return None
    path = url.split("?")[0].split("#")[0]
    m = _GROUP_MEMBER_USER_RE.search(path)
    if not m:
        return None
    return f"https://www.facebook.com/profile.php?id={m.group(1)}"
