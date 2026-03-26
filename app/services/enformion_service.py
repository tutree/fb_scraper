"""
EnformionGO Contact Enrichment + Person Search API integration.
Docs:
  Contact Enrichment: https://enformiongo.readme.io/reference/contact-enrichment
  Person Search:      https://enformiongo.readme.io/reference/person-search
"""
import asyncio
import json
import httpx
from typing import Dict, Optional, Tuple

from ..core.config import settings
from ..core.logging_config import get_logger
from ..utils.validators import clean_facebook_location

logger = get_logger(__name__)

MAX_RETRIES = 1
RETRY_BACKOFF_SECONDS = [5]

ENFORMION_ENRICH_URL = "https://devapi.enformion.com/contact/enrich"
ENFORMION_PERSON_SEARCH_URL = "https://devapi.enformion.com/PersonSearch"

# Headers must match working curl: Content-Type, Accept, galaxy-* only (no User-Agent)
_HTTP_HEADERS_BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Keep old name as alias so nothing else breaks
ENFORMION_URL = ENFORMION_ENRICH_URL


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
        """Only call Enformion when we have first name + last name + location."""
        if not name or not name.strip():
            return False, "Cannot enrich: name is required"
        name_parts = name.strip().split()
        if len(name_parts) < 2:
            return False, "Cannot enrich: first name and last name required (at least two name parts)"
        if not location or not location.strip():
            return False, "Cannot enrich: location is required alongside name for a reliable match"
        return True, "OK"

    def _build_request(self, name: str, location: str) -> Dict:
        """Build payload exactly like working curl: FirstName, LastName, Address only."""
        first, _, last = self.split_name(name)
        cleaned_location = clean_facebook_location(location) or location.strip()
        return {
            "FirstName": first,
            "LastName": last,
            "Address": {
                "addressLine1": "",
                "addressLine2": cleaned_location,
            },
        }

    def _build_person_search_request(self, name: str, location: str) -> Dict:
        """Build Person Search payload: Addresses is an array with AddressLine2."""
        first, middle, last = self.split_name(name)
        cleaned_location = clean_facebook_location(location) or location.strip()
        payload: Dict = {
            "FirstName": first,
            "LastName": last,
            "Addresses": [{"AddressLine2": cleaned_location}],
            "Includes": ["Addresses", "PhoneNumbers", "EmailAddresses"],
            "Page": 1,
            "ResultsPerPage": 5,
        }
        if middle:
            payload["MiddleName"] = middle
        return payload

    async def _call(self, url: str, payload: Dict, search_type: str) -> Dict:
        """Low-level HTTP call with 429 retry logic. Returns parsed JSON body."""
        headers = {
            **_HTTP_HEADERS_BASE,
            "galaxy-ap-name": self.ap_name,
            "galaxy-ap-password": self.ap_password,
            "galaxy-search-type": search_type,
        }
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

        data = None
        for attempt in range(MAX_RETRIES + 1):
            async with httpx.AsyncClient(
                timeout=30.0,
                http1=True,
                http2=False,
                follow_redirects=True,
            ) as client:
                resp = await client.post(url, content=body, headers=headers)

            if resp.status_code == 429:
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait = max(wait, int(retry_after))
                        except (ValueError, TypeError):
                            pass
                    logger.warning(
                        "EnformionGO 429 rate-limited (attempt %d/%d). Sleeping %ds...",
                        attempt + 1, MAX_RETRIES + 1, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                else:
                    logger.error("EnformionGO 429 after %d retries — giving up", MAX_RETRIES + 1)
                    resp.raise_for_status()

            if resp.status_code >= 400:
                body_preview = (resp.text or "")[:500]
                logger.error("EnformionGO API error %d: %s", resp.status_code, body_preview)
                if resp.status_code == 444:
                    logger.error(
                        "HTTP 444 often means geo-block or auth error. "
                        "Check ENFORMION_AP_NAME / ENFORMION_AP_PASSWORD."
                    )
                resp.raise_for_status()

            data = resp.json()
            break

        return data or {}

    async def enrich(self, name: str, location: str) -> Dict:
        """
        Call EnformionGO Contact Enrichment (primary, cheaper).
        Returns parsed person data dict or {"matched": False}.
        Raises on HTTP/network errors.
        """
        payload = self._build_request(name, location)
        logger.info(
            "EnformionGO ContactEnrich request: name=%r location=%r payload=%s",
            name, location, payload,
        )
        data = await self._call(ENFORMION_ENRICH_URL, payload, "DevAPIContactEnrich")
        return self._parse_single_person(data, name)

    async def person_search(self, name: str, location: str) -> Dict:
        """
        Call EnformionGO Person Search (fallback, more powerful).
        Returns the best-matching person data dict or {"matched": False}.
        Raises on HTTP/network errors.
        """
        payload = self._build_person_search_request(name, location)
        logger.info(
            "EnformionGO PersonSearch fallback request: name=%r location=%r",
            name, location,
        )
        data = await self._call(ENFORMION_PERSON_SEARCH_URL, payload, "Person")

        # Person Search returns a list under "persons".
        persons = data.get("persons") or []
        if not persons:
            logger.info("EnformionGO PersonSearch: no match for %r", name)
            return {"matched": False}

        # Take first result (most-relevant match). Person Search uses different field names.
        return self._parse_person_search_result(persons[0], name)

    def _parse_person_search_result(self, person: Dict, name: str) -> Dict:
        """
        Parse a single entry from the PersonSearch `persons` array.
        PersonSearch uses different field names than ContactEnrich:
          phones  → phoneNumbers  (each: phoneNumber, phoneType, isConnected)
          emails  → emailAddresses (each: emailAddress)
          address → addresses     (each: fullAddress / city / state / zip)
        """
        if not person:
            return {"matched": False}

        name_obj = person.get("name") or {}
        full_name = " ".join(filter(None, [
            name_obj.get("firstName"),
            name_obj.get("middleName"),
            name_obj.get("lastName"),
        ]))

        phones = [
            {
                "number": p.get("phoneNumber"),
                "type": p.get("phoneType"),
                "is_connected": p.get("isConnected"),
            }
            for p in (person.get("phoneNumbers") or [])
            if p.get("phoneNumber")
        ]

        emails = [
            e.get("emailAddress")
            for e in (person.get("emailAddresses") or [])
            if e.get("emailAddress")
        ]

        addresses = []
        for a in (person.get("addresses") or []):
            full = a.get("fullAddress")
            if full:
                addresses.append({
                    "street": full,
                    "unit": None,
                    "city": a.get("city"),
                    "state": a.get("state"),
                    "zip": a.get("zip"),
                })

        result = {
            "matched": True,
            "full_name": full_name,
            "age": person.get("age"),
            "phones": phones,
            "emails": emails,
            "addresses": addresses,
        }
        logger.info(
            "EnformionGO PersonSearch match: %s, phones=%d, emails=%d, addresses=%d",
            result["full_name"],
            len(phones),
            len(emails),
            len(addresses),
        )
        return result

    def _parse_single_person(self, data: Dict, name: str) -> Dict:
        """Map a {person: ...} envelope to our standard enrichment dict."""
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
