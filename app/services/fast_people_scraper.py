from playwright.async_api import Page
import asyncio
import re
from typing import List, Dict, Optional
from ..core.logging_config import get_logger
from ..utils.human_behavior import human_scroll, human_mouse_move, random_sleep

logger = get_logger(__name__)


class SiteBlockedError(RuntimeError):
    pass


class FastPeopleScraper:
    """
    Scraper for FastPeopleSearch.com
    Extracts: phone numbers, current address, previous addresses, age, relatives.
    Free — no account or API key required.
    """

    BASE_URL = "https://www.fastpeoplesearch.com"

    def __init__(self, browser_manager):
        self.browser_manager = browser_manager
        self._page: Optional[Page] = None

    async def _get_or_create_page(self) -> Page:
        if self._page is None:
            self._page = await self.browser_manager.create_page()
        return self._page

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _handle_block_check(self, page: Page):
        """
        Detect Cloudflare / bot-detection pages and pause for manual solve.
        """
        try:
            title = await page.title()
            content = await page.content()

            is_blocked = (
                "Access Denied" in title
                or "Just a moment" in title
                or "cf-challenge" in content
                or "cf-turnstile" in content
                or "Enable JavaScript" in content
                or "Please Wait" in title
                or "Sorry, you have been blocked" in content
                or "Cloudflare Ray ID" in content
            )

            if is_blocked:
                hard_blocked = (
                    "Sorry, you have been blocked" in content
                    or "Cloudflare Ray ID" in content
                )
                if hard_blocked:
                    logger.error("FastPeopleSearch hard-blocked this session/IP (Cloudflare block page).")
                    raise SiteBlockedError(
                        "FastPeopleSearch blocked this session/IP (Cloudflare). "
                        "Try later or use another source like TruePeopleSearch."
                    )

                logger.warning("Bot-detection page detected; manual solve may be required.")
                print("\n" + "!" * 60)
                print("BOT CHECK DETECTED!")
                print("Please resolve the CAPTCHA in the browser window,")
                print("then press ENTER in this terminal to continue.")
                print("!" * 60 + "\n")

                try:
                    import winsound
                    winsound.Beep(1000, 600)
                except Exception:
                    pass

                input("Press Enter once the page is accessible...")
                logger.info("Resuming after manual resolution...")
                await asyncio.sleep(2)

        except SiteBlockedError:
            raise
        except Exception as e:
            logger.error(f"Block check error: {e}")

    @staticmethod
    def _build_search_url(name: str, location: str = None) -> str:
        """
        Construct a FastPeopleSearch name search URL.
        Examples:
          /name/john-doe
          /name/john-doe_chicago-il
        """
        slug = name.strip().lower().replace(" ", "-")
        # Remove non-alphanumeric except hyphens
        slug = re.sub(r"[^a-z0-9\-]", "", slug)

        if location:
            loc_slug = location.strip().lower().replace(",", "").replace("  ", " ").replace(" ", "-")
            loc_slug = re.sub(r"[^a-z0-9\-]", "", loc_slug)
            return f"https://www.fastpeoplesearch.com/name/{slug}_{loc_slug}"

        return f"https://www.fastpeoplesearch.com/name/{slug}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(self, name: str, location: str = None) -> List[Dict]:
        """
        Search FastPeopleSearch for a person.
        Returns a list of result dicts with keys:
          index, name, age, location, detail_url
        """
        page = await self._get_or_create_page()

        url = self._build_search_url(name, location)
        logger.info(f"Navigating to: {url}")

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self._handle_block_check(page)
            await human_mouse_move(page, 400, 300)
            await random_sleep(2, 4)

            content = await page.content()

            # Common "no results" messages
            if any(phrase in content for phrase in [
                "No results found",
                "couldn't find",
                "We could not find",
                "no records",
            ]):
                logger.info("No records found on FastPeopleSearch.")
                return []

            results = []

            # --- Result cards ---
            # FastPeopleSearch wraps each result in a <div class="card-block">
            # Fallback to any .card if that changes.
            cards = await page.query_selector_all("div.card-block")
            if not cards:
                cards = await page.query_selector_all("div.card")

            for index, card in enumerate(cards):
                # Name — usually in an <h2> or element with class "h4"/"name"
                name_el = (
                    await card.query_selector("h2")
                    or await card.query_selector(".h4")
                    or await card.query_selector(".card-title")
                )
                full_name = (await name_el.inner_text()).strip() if name_el else "Unknown"

                # Age — look for "Age XX" text
                age = ""
                age_el = await card.query_selector(".age")
                if not age_el:
                    # Try to find a span/div containing "Age"
                    age_el = await card.query_selector("span:has-text('Age')")
                if age_el:
                    age_raw = (await age_el.inner_text()).strip()
                    age_match = re.search(r"\d{1,3}", age_raw)
                    age = age_match.group(0) if age_match else age_raw

                # Location — city/state line
                loc_el = (
                    await card.query_selector(".location")
                    or await card.query_selector(".content-value")
                    or await card.query_selector("p.card-text")
                )
                current_loc = (await loc_el.inner_text()).strip() if loc_el else "Unknown"

                # Detail link
                link_el = await card.query_selector("a[href*='/address/']")
                if not link_el:
                    link_el = await card.query_selector("a.btn")
                if not link_el:
                    link_el = await card.query_selector("a[href]")

                detail_link = await link_el.get_attribute("href") if link_el else None

                if detail_link:
                    full_url = (
                        self.BASE_URL + detail_link
                        if detail_link.startswith("/")
                        else detail_link
                    )
                    results.append({
                        "index": index + 1,
                        "name": full_name,
                        "age": age,
                        "location": current_loc,
                        "detail_url": full_url,
                    })

            logger.info(f"Found {len(results)} results for '{name}'.")
            return results

        except SiteBlockedError:
            raise
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def get_details(self, url: str) -> Dict:
        """
        Scrape a FastPeopleSearch profile detail page.
        Returns:
          phone_numbers   : list[str]
          current_address : str | None
          previous_addresses: list[str]
          relatives       : list[str]
          age             : str | None
        """
        page = await self._get_or_create_page()

        logger.info(f"Scraping detail page: {url}")

        details: Dict = {
            "phone_numbers": [],
            "current_address": None,
            "previous_addresses": [],
            "relatives": [],
            "age": None,
        }

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self._handle_block_check(page)
            await human_scroll(page, scrolls=3)
            await random_sleep(1, 3)

            # ── 1. Phone numbers ──────────────────────────────────────────────
            phone_links = await page.query_selector_all("a[href^='tel:']")
            seen = set()
            for link in phone_links:
                num = (await link.inner_text()).strip()
                if num and num not in seen:
                    details["phone_numbers"].append(num)
                    seen.add(num)

            # Fallback: scrape phone numbers from tel: href values
            if not details["phone_numbers"]:
                for link in phone_links:
                    href = await link.get_attribute("href") or ""
                    num = href.replace("tel:", "").strip()
                    if num and num not in seen:
                        details["phone_numbers"].append(num)
                        seen.add(num)

            # ── 2. Addresses ──────────────────────────────────────────────────
            # FastPeopleSearch typically puts addresses in elements that link
            # to Google Maps or have class "address" / "content-value".
            # The first address is considered "current".
            address_els = await page.query_selector_all("a[href*='maps.google']")
            if not address_els:
                # Try card sections labelled "Current Address" / "Past Addresses"
                address_els = await page.query_selector_all(".address-info a")
            if not address_els:
                address_els = await page.query_selector_all("div.detail-box a[href*='address']")

            addresses_found = []
            seen_addr = set()
            for a in address_els:
                addr_text = " ".join((await a.inner_text()).split())
                if addr_text and addr_text not in seen_addr and len(addr_text) > 5:
                    addresses_found.append(addr_text)
                    seen_addr.add(addr_text)

            if addresses_found:
                details["current_address"] = addresses_found[0]
                details["previous_addresses"] = addresses_found[1:]

            # Extra fallback — look for the labelled "Current Address" section
            if not details["current_address"]:
                cur_section = await page.query_selector("div:has-text('Current Address')")
                if cur_section:
                    raw = await cur_section.inner_text()
                    lines = [l.strip() for l in raw.splitlines() if l.strip()]
                    # Remove the label itself
                    addr_lines = [l for l in lines if "Current Address" not in l]
                    if addr_lines:
                        details["current_address"] = ", ".join(addr_lines[:2])

            # ── 3. Relatives ──────────────────────────────────────────────────
            # Usually links to other FastPeopleSearch profiles
            rel_links = await page.query_selector_all("a[href*='/name/']")
            seen_rel = set()
            for r in rel_links:
                rel_name = (await r.inner_text()).strip()
                if rel_name and rel_name not in seen_rel and len(rel_name) > 2:
                    details["relatives"].append(rel_name)
                    seen_rel.add(rel_name)

            # ── 4. Age ────────────────────────────────────────────────────────
            age_el = await page.query_selector(".age")
            if not age_el:
                age_el = await page.query_selector("span:has-text('Age')")
            if age_el:
                age_raw = (await age_el.inner_text()).strip()
                m = re.search(r"\d{1,3}", age_raw)
                details["age"] = m.group(0) if m else age_raw

        except SiteBlockedError:
            raise
        except Exception as e:
            logger.error(f"Error scraping detail page: {e}")

        logger.info(
            f"Details extracted — phones: {len(details['phone_numbers'])}, "
            f"address: {details['current_address']}, relatives: {len(details['relatives'])}"
        )
        return details
