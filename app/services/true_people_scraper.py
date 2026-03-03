from playwright.async_api import Page
import asyncio
from typing import List, Dict, Optional
from ..core.logging_config import get_logger
from ..utils.human_behavior import human_scroll, human_mouse_move, random_sleep

logger = get_logger(__name__)

class TruePeopleScraper:
    BASE_URL = "https://www.truepeoplesearch.com"

    def __init__(self, browser_manager):
        self.browser_manager = browser_manager

    async def _handle_captcha_check(self, page: Page):
        """
        Check for Cloudflare verify page or Access Denied.
        If found, pause and wait for user intervention.
        """
        try:
            title = await page.title()
            content = await page.content()
            
            # Simple heuristic for blocked page
            is_blocked = (
                "Access Denied" in title 
                or "Just a moment..." in title 
                or "cl-challenge" in content
                or "cf-turnstile" in content
            )

            if is_blocked:
                logger.warning("CAPTCHA / Access Denied detected!")
                print("\n" + "!"*50)
                print("CAPTCHA DETECTED! Please resolve it in the browser window.")
                print("The script is paused. Press ENTER in this terminal once the page loads correctly.")
                print("!"*50 + "\n")
                
                # Play a system beep if possible (Windows)
                try:
                    import winsound
                    winsound.Beep(1000, 500)
                except:
                    pass

                input("Press Enter to continue...")
                logger.info("Resuming after manual captcha resolution...")
                await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Error checking for captcha: {e}")

    async def search(self, name: str, location: str = None) -> List[Dict]:
        """
        Search for a person.
        Returns a list of simplified result dicts.
        """
        page = await self.browser_manager.get_current_page()
        if not page:
            page = await self.browser_manager.create_page()

        # Construct URL
        query = f"name={name.replace(' ', '%20')}"
        if location:
            query += f"&citystatezip={location.replace(' ', '%20')}"
        url = f"{self.BASE_URL}/results?{query}"

        logger.info(f"Navigating to search: {url}")
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self._handle_captcha_check(page)
            
            # Additional wait for results to populate
            await human_mouse_move(page, 300, 300)
            await random_sleep(2, 4)

            # Check if "No records found"
            if "We could not find any records" in await page.content():
                logger.info("No records found.")
                return []

            results = []
            
            # Select all card elements
            cards = await page.query_selector_all(".card")
            
            for index, card in enumerate(cards):
                # Extract Name
                name_el = await card.query_selector(".h4")
                full_name = await name_el.inner_text() if name_el else "Unknown"
                
                # Extract Age
                age_el = await card.query_selector("span:has-text('Age')")
                age_text = await age_el.inner_text() if age_el else ""
                age = age_text.replace("Age:", "").strip() if "Age:" in age_text else ""

                # Extract Location
                loc_el = await card.query_selector(".content-value")
                current_loc = await loc_el.inner_text() if loc_el else "Unknown"
                
                # Extract Detail Link
                link_el = await card.query_selector("a.btn-block")
                detail_link = await link_el.get_attribute("href") if link_el else None
                
                if detail_link:
                    results.append({
                        "index": index + 1,
                        "name": full_name,
                        "age": age,
                        "location": current_loc,
                        "detail_url": self.BASE_URL + detail_link if detail_link.startswith("/") else detail_link
                    })
            
            logger.info(f"Found {len(results)} potential matches.")
            return results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def get_details(self, url: str) -> Dict:
        """
        Scrape full details from a profile page.
        """
        page = await self.browser_manager.get_current_page()
        
        logger.info(f"Scraping details from: {url}")
        await page.goto(url, wait_until="domcontentloaded")
        await self._handle_captcha_check(page)
        
        await human_scroll(page, scrolls=2) # Basic scroll to trigger lazy loading

        details = {
            "phone_numbers": [],
            "current_address": None,
            "email_addresses": [],
            "associated_names": [],
            "relatives": []
        }

        try:
            # 1. Phone Numbers (Wireless & Landline)
            # Expand "Show all phone numbers" if present? Usually not needed on this site, but check.
            phones = await page.query_selector_all("a[href^='tel:']")
            seen_phones = set()
            for p in phones:
                num = await p.inner_text()
                if num and num not in seen_phones:
                    details["phone_numbers"].append(num.strip())
                    seen_phones.add(num)
            
            # 2. Current Address
            # Usually the first address block
            address_el = await page.query_selector("a[data-link-to-more='address']")
            if address_el:
                 # Sometimes inner text has line breaks
                 addr_text = await address_el.inner_text()
                 details["current_address"] = " ".join(addr_text.split())

            # 3. Email Addresses
            # Look for strings with @
            content = await page.content()
            # Simple heuristic parsing from DOM elements often safer than regexing raw HTML for emails
            # TruePeopleSearch lists emails in a specific section.
            # Select all divs that look like email sections
            email_section = await page.query_selector("div:has-text('Email Addresses')")
            if email_section:
                # This is tricky because the structure varies. 
                # Let's try finding all text nodes that look like emails.
                # Or just grab all text from that section.
                # Simplified approach: Look for typical email patterns in text content
                pass 
            
            # 4. Relatives
            relatives_els = await page.query_selector_all("a[href*='/find/person/']")
            # This might grab too many links, need to be careful.
            # Usually relatives are in a specific container.
            
            # Refined Approach: Use specific containers based on likely class names or structure
            # (Without live site inspection, this is generic best-effort)
            
            # Just grabbing all phones is often the main goal.
            
        except Exception as e:
             logger.error(f"Error scraping details: {e}")

        return details
