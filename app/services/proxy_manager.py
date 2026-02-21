import random
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from datetime import datetime
from ..models.proxy_log import ProxyLog
from ..core.config import settings
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class ProxyManager:
    def __init__(self, db: Session):
        self.db = db
        self.proxies = settings.proxies
        self.current_index = 0

    def get_next_proxy(self) -> Optional[Dict]:
        """Get next working proxy in round-robin fashion."""
        if not self.proxies:
            return None

        # Try to find an active proxy
        for _ in range(len(self.proxies)):
            proxy_url = self.proxies[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.proxies)

            # Check if proxy is active in database
            proxy_log = (
                self.db.query(ProxyLog)
                .filter(ProxyLog.proxy_url == proxy_url)
                .first()
            )

            # If no log or proxy is active, use it
            if not proxy_log or proxy_log.is_active:
                logger.info(f"Using proxy: {proxy_url}")
                return self.parse_proxy_string(proxy_url)

        # If all proxies are inactive, reset and use the next one anyway
        logger.warning("All proxies inactive, forcing next proxy")
        return self.parse_proxy_string(self.proxies[self.current_index])

    def parse_proxy_string(self, proxy_string: str) -> Dict:
        """Parse proxy string into Playwright format.

        Supports:
          - protocol://user:pass@host:port
          - protocol://host:port
        """
        if "@" in proxy_string:
            protocol, rest = proxy_string.split("://")
            credentials, host = rest.split("@")
            username, password = credentials.split(":")
            return {
                "server": f"{protocol}://{host}",
                "username": username,
                "password": password,
            }
        else:
            return {"server": proxy_string}

    def report_proxy_result(self, proxy_url: str, success: bool) -> None:
        """Report proxy success/failure to update stats."""
        proxy_log = (
            self.db.query(ProxyLog)
            .filter(ProxyLog.proxy_url == proxy_url)
            .first()
        )

        if proxy_log:
            if success:
                proxy_log.success_count += 1
            else:
                proxy_log.fail_count += 1
                # Deactivate proxy if too many failures
                if proxy_log.fail_count > 10:
                    proxy_log.is_active = False
                    logger.warning(f"Proxy deactivated due to failures: {proxy_url}")
            proxy_log.last_used = datetime.now()
        else:
            proxy_log = ProxyLog(
                proxy_url=proxy_url,
                success_count=1 if success else 0,
                fail_count=0 if success else 1,
            )
            self.db.add(proxy_log)

        self.db.commit()
