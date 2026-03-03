import asyncio
import sys
import os
import io

# Set stdout/stderr encoding to UTF-8 to handle special characters properly
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Ensure we can import from app
sys.path.append(os.getcwd())

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.services.proxy_manager import ProxyManager
from app.services.browser_manager import BrowserManager
from app.services.true_people_scraper import TruePeopleScraper
from app.models.person_details import PersonDetails
from app.core.logging_config import get_logger

logger = get_logger(__name__)

async def main():
    print("="*60)
    print(" TRUE PEOPLE SEARCH STANDALONE TOOL ")
    print("="*60)

    # 1. Database Session
    db: Session = SessionLocal()
    browser_manager = None
    
    try:
        # 2. Setup Services
        print("Initializing services...")
        try:
            db.execute("SELECT 1")
        except Exception as e:
            print(f"Database connection failed: {e}")
            return

        proxy_manager = ProxyManager(db)
        
        # Interactive mode: Visible browser for manual Captcha solving
        browser_manager = BrowserManager(proxy_manager, headless=False)
        scraper = TruePeopleScraper(browser_manager)

        while True:
            print("\n" + "-"*40)
            target_name = input("Enter Name to Search (or 'q' to quit): ").strip()
            if target_name.lower() in ('q', 'quit', 'exit'):
                break
            
            if not target_name:
                continue

            target_loc = input("Enter City/State (optional, Enter to skip): ").strip()
            
            print(f"\nSearching for '{target_name}' in '{target_loc}'...")
            try:
                # Run search
                results = await scraper.search(target_name, location=target_loc)
                
                if not results:
                    print("No results found.")
                    continue

                # Display Results
                print(f"\nFound {len(results)} matches:")
                for r in results:
                    print(f"  [{r['index']}] {r['name']} ({r['age']}) - {r['location']}")
                
                # Selection Loop
                while True:
                    choice = input("\nEnter # to scrape details, 'a' for all, or 's' to skip: ").strip().lower()
                    
                    if choice == 's':
                        break
                    
                    indices_to_scrape = []
                    if choice == 'a':
                        indices_to_scrape = [r['index'] for r in results]
                    elif choice.isdigit():
                        idx = int(choice)
                        if any(r['index'] == idx for r in results):
                            indices_to_scrape = [idx]
                        else:
                            print("Invalid index.")
                            continue
                    else:
                        print("Invalid input.")
                        continue
                    
                    # Scrape Details
                    for idx in indices_to_scrape:
                        target = next(r for r in results if r['index'] == idx)
                        print(f"\nScraping details for: {target['name']}...")
                        
                        try:
                            details = await scraper.get_details(target['detail_url'])
                            
                            # Check existence
                            existing = db.query(PersonDetails).filter(PersonDetails.profile_url == target['detail_url']).first()
                            
                            if existing:
                                print("  -> Updating existing record...")
                                existing.phone_numbers = details.get('phone_numbers')
                                existing.current_address = details.get('current_address') or target['location']
                                # existing.email = ... (if used)
                            else:
                                person = PersonDetails(
                                    full_name=target['name'],
                                    age=target['age'],
                                    current_address=details.get('current_address') or target['location'],
                                    phone_numbers=details.get('phone_numbers'),
                                    relatives=details.get('relatives'), 
                                    email=str(details.get('email_addresses', [])), 
                                    profile_url=target['detail_url']
                                )
                                db.add(person)
                                print("  -> Saved to DB.")
                            
                            db.commit()
                            
                            print(f"  Phones: {details.get('phone_numbers')}")
                            print(f"  Address: {details.get('current_address')}")

                        except Exception as e:
                            logger.error(f"Error saving {target['name']}: {e}")
                            print(f"  Error: {e}")
                    
                    if choice == 'a':
                        print("\nBatch scrape complete.")
                        break 
            
            except Exception as e:
                logger.error(f"Search flow error: {e}")
                print(f"Error: {e}")

    finally:
        print("\nClosing browser...")
        if browser_manager:
            # Cleanup if needed
            pass
        db.close()
        print("Done.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited by user.")
