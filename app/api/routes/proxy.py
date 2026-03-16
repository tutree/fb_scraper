from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models.proxy_log import ProxyLog
from ...services.proxy_manager import ProxyManager

router = APIRouter(prefix="/proxy", tags=["proxy"])


@router.get("/stats")
async def get_proxy_stats(db: Session = Depends(get_db)):
    """Get proxy usage statistics."""
    proxies = db.query(ProxyLog).all()
    return {
        "total_proxies": len(proxies),
        "active_proxies": sum(1 for p in proxies if p.is_active),
        "proxies": [
            {
                "url": p.proxy_url,
                "success_count": p.success_count,
                "fail_count": p.fail_count,
                "success_rate": (
                    p.success_count / (p.success_count + p.fail_count)
                    if (p.success_count + p.fail_count) > 0
                    else 0
                ),
                "is_active": p.is_active,
                "last_used": p.last_used,
            }
            for p in proxies
        ],
    }


@router.post("/rotate")
async def rotate_proxy(db: Session = Depends(get_db)):
    """Force proxy rotation."""
    proxy_manager = ProxyManager(db)
    next_proxy = proxy_manager.get_next_proxy()
    return {"next_proxy": next_proxy}
