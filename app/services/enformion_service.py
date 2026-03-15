"""
EnformionGO Contact Enrichment API integration.
Docs: https://enformiongo.readme.io/reference/contact-enrichment
"""
import json
import httpx
from typing import Dict, Optional, Tuple

from ..core.config import settings
from ..core.logging_config import get_logger
from ..utils.validators import clean_facebook_location

logger = get_logger(__name__)

ENFORMION_URL = "https://devapi.enformion.com/contact/enrich"

_HTTP_HEADERS_BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "EnformionClient/1.0",
}


class EnformionService:

    def __init__(
        self,
        ap_name: Optional[str] = None,
        ap_password: Optional[str] = None,
    ):
        self.ap_name = ap_name or settings.ENFORMION_AP_NAME
        self.ap_password = ap_password or settings.ENFORMION_AP_PASSWORD
        if not self.ap_name or not self.ap_password:
            raise ValueError(
                "EnformionGO credentials not configured. "
                "Set ENFORMION_AP_NAME and ENFORMION_AP_PASSWORD."
            )

    @staticmethod
    def split_name(full_name: str) -> Tuple[str, str, str]:
        """Split a full name into (first, middle, last)."""
        parts = full_name.strip().split()
        if len(parts) == 0:
            return "", "", ""
        if len(parts) == 1:
            return parts[0], "", parts[0]
        if len(parts) == 2:
            return parts[0], "", parts[1]
        return parts[0], " ".join(parts[1:-1]), parts[-1]

    @staticmethod
    def can_enrich(name: Optional[str], location: Optional[str]) -> Tuple[bool, str]:
        if not name or not name.strip():
            return False, "Cannot enrich: name is required"
        if not location or not location.strip():
            return False, "Cannot enrich: location is required alongside name for a reliable match"
        return True, "OK"

    def _build_request(self, name: str, location: str) -> Dict:
        first, middle, last = self.split_name(name)
        cleaned_location = clean_facebook_location(location) or location.strip()
        return {
            "FirstName": first,
            "MiddleName": middle,
            "LastName": last,
            "Dob": "",
            "Age": None,
            "Phone": "",
            "Email": "",
            "Address": {
                "AddressLine1": "",
                "AddressLine2": cleaned_location,
            },
            "Page": 1,
            "ResultsPerPage": 10,
        }

    async def enrich(self, name: str, location: str) -> Dict:
        """
        Call EnformionGO Contact Enrichment and return the parsed person data.
        Raises on HTTP/network errors.
        """
        payload = self._build_request(name, location)
        headers = {
            **_HTTP_HEADERS_BASE,
            "galaxy-ap-name": self.ap_name,
            "galaxy-ap-password": self.ap_password,
            "galaxy-search-type": "DevAPIContactEnrich",
        }

        logger.info(
            "EnformionGO enrichment request: name=%r location=%r payload=%s",
            name,
            location,
            payload,
        )

        async with httpx.AsyncClient(
            timeout=30.0,
            http1=True,
            http2=False,
            follow_redirects=True,
        ) as client:
            resp = await client.post(
                ENFORMION_URL,
                content=json.dumps(payload),
                headers=headers,
            )
            if resp.status_code >= 400:
                logger.error(
                    "EnformionGO API error %d: %s",
                    resp.status_code,
                    resp.text,
                )
                resp.raise_for_status()
            data = resp.json()

        person = data.get("person")
        if not person:
            logger.info("EnformionGO returned no match for %r", name)
            return {"matched": False}

        result = {
            "matched": True,
            "full_name": " ".join(
                filter(None, [
                    person.get("name", {}).get("firstName"),
                    person.get("name", {}).get("middleName"),
                    person.get("name", {}).get("lastName"),
                ])
            ),
            "age": person.get("age"),
            "phones": [
                {
                    "number": p.get("number"),
                    "type": p.get("type"),
                    "is_connected": p.get("isConnected"),
                }
                for p in (person.get("phones") or [])
            ],
            "emails": [
                e.get("email") for e in (person.get("emails") or [])
            ],
            "addresses": [
                {
                    "street": a.get("street"),
                    "unit": a.get("unit"),
                    "city": a.get("city"),
                    "state": a.get("state"),
                    "zip": a.get("zip"),
                }
                for a in (person.get("addresses") or [])
            ],
        }
        logger.info(
            "EnformionGO match: %s, phones=%d, emails=%d, addresses=%d",
            result["full_name"],
            len(result["phones"]),
            len(result["emails"]),
            len(result["addresses"]),
        )
        return result
