"""
FastPeopleSearch Standalone Tool
---------------------------------
Interactively search FastPeopleSearch.com for people scraped from Facebook.
Extracts: phone numbers, current/previous addresses, age, relatives.
Results are saved to the `person_details` table.

Usage:
    python run_fast_people_search.py

Options inside the tool:
    Enter a name  -> search
    Enter city/state (optional) -> narrows results
    Pick a result number, 'a' for all, or 's' to skip
    'q' to quit
"""

import asyncio
import sys
import os
import io

# UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

sys.path.append(os.getcwd())

from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.database import SessionLocal
from app.services.proxy_manager import ProxyManager
from app.services.browser_manager import BrowserManager
from app.services.fast_people_scraper import FastPeopleScraper, SiteBlockedError
from app.models.person_details import PersonDetails
from app.core.logging_config import get_logger

logger = get_logger(__name__)


def _print_details(details: dict):
    print(f"    Phones   : {details.get('phone_numbers') or 'None found'}")
    print(f"    Address  : {details.get('current_address') or 'None found'}")
    prev = details.get("previous_addresses", [])
    if prev:
        print(f"    Prev Addr: {prev}")
    print(f"    Relatives: {details.get('relatives') or 'None found'}")
    print(f"    Age      : {details.get('age') or 'Unknown'}")


async def main():
    print("=" * 60)
    print("   FAST PEOPLE SEARCH — CONTACT ENRICHMENT TOOL")
    print("=" * 60)

    db: Session = SessionLocal()
    browser_manager = None

    try:
        # Database connection verification
        try:
            db.execute(text("SELECT 1"))
            print("Database connected.")
        except Exception as e:
            print(f"Database connection failed: {e}")
            return

        # Check for SSH Proxy intent (SSH SOCKS proxy usually on 127.0.0.1:8080)
        use_ssh_proxy = os.getenv("USE_SSH_PROXY", "0").strip().lower() in {"1", "true", "yes", "on"}
        
        # Determine Proxy Strategy
        proxy_manager = None
        
        if use_ssh_proxy:
            # Create a simple static proxy manager for the SSH tunnel
            class StaticProxyManager:
                def get_next_proxy(self):
                    return {"server": "socks5://127.0.0.1:8080"}
            
            proxy_manager = StaticProxyManager()
            print("Proxy mode: SSH TUNNEL (socks5://127.0.0.1:8080)")
            
        else:
            use_db_proxy = os.getenv("USE_PROXY", "0").strip().lower() in {"1", "true", "yes", "on"}
            if use_db_proxy:
                proxy_manager = ProxyManager(db)
                print("Proxy mode: DB POOL (USE_PROXY enabled)")
            else:
                print("Proxy mode: DIRECT (no proxy)")

        # Headless=False so you can solve any CAPTCHA manually
        browser_manager = BrowserManager(proxy_manager, headless=False)

        scraper = FastPeopleScraper(browser_manager)

        while True:
            print("\n" + "-" * 50)
            target_name = input("Enter name to search (or 'q' to quit): ").strip()

            if target_name.lower() in ("q", "quit", "exit"):
                break

            if not target_name:
                continue

            target_loc = input("Enter City/State (optional, press Enter to skip): ").strip()

            print(f"\nSearching FastPeopleSearch for '{target_name}'"
                  + (f" in '{target_loc}'" if target_loc else "") + "...")

            try:
                results = await scraper.search(target_name, location=target_loc or None)
            except SiteBlockedError as e:
                print("\nFastPeopleSearch blocked this session/IP (Cloudflare).")
                print("Please try one of these:")
                print("  1) Wait and try again later")
                print("  2) Use a different network/IP")
                print("  3) Run: python run_true_people_search.py")
                print(f"Details: {e}")
                continue
            except Exception as e:
                logger.error(f"Search error: {e}")
                print(f"Search error: {e}")
                continue

            if not results:
                print("No results found.")
                continue

            # Display results
            print(f"\nFound {len(results)} match(es):")
            for r in results:
                age_str = f", Age {r['age']}" if r.get("age") else ""
                print(f"  [{r['index']}] {r['name']}{age_str} — {r['location']}")

            # Selection loop
            while True:
                choice = input(
                    "\nEnter result # to scrape, 'a' for all, or 's' to skip: "
                ).strip().lower()

                if choice == "s":
                    break

                indices_to_scrape: list[int] = []
                if choice == "a":
                    indices_to_scrape = [r["index"] for r in results]
                elif choice.isdigit():
                    idx = int(choice)
                    if any(r["index"] == idx for r in results):
                        indices_to_scrape = [idx]
                    else:
                        print(f"No result with index {idx}.")
                        continue
                else:
                    print("Invalid input — enter a number, 'a', or 's'.")
                    continue

                # Scrape each selected result
                for idx in indices_to_scrape:
                    target = next(r for r in results if r["index"] == idx)
                    print(f"\n  Scraping details for: {target['name']} ...")

                    try:
                        details = await scraper.get_details(target["detail_url"])

                        # Upsert into person_details
                        existing = (
                            db.query(PersonDetails)
                            .filter(PersonDetails.profile_url == target["detail_url"])
                            .first()
                        )

                        if existing:
                            print("  -> Updating existing record...")
                            existing.phone_numbers = details.get("phone_numbers") or existing.phone_numbers
                            existing.current_address = details.get("current_address") or existing.current_address
                            existing.relatives = details.get("relatives") or existing.relatives
                            if details.get("age"):
                                existing.age = details["age"]
                        else:
                            print("  -> Saving new record...")
                            person = PersonDetails(
                                full_name=target["name"],
                                age=details.get("age") or target.get("age"),
                                current_address=(
                                    details.get("current_address") or target.get("location")
                                ),
                                phone_numbers=details.get("phone_numbers"),
                                relatives=details.get("relatives"),
                                email=None,  # FastPeopleSearch doesn't expose emails
                                profile_url=target["detail_url"],
                            )
                            db.add(person)

                        db.commit()
                        print("  -> Saved to DB.")
                        _print_details(details)

                    except Exception as e:
                        db.rollback()
                        logger.error(f"Error saving {target['name']}: {e}")
                        print(f"  Error: {e}")

                if choice == "a":
                    print("\nBatch done.")
                    break

    finally:
        print("\nClosing...")
        db.close()
        print("Done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited by user.")
