#!/usr/bin/env python3
"""
Simple script to start scraping and view results
"""
import requests
import time
import json
from typing import Optional

API_BASE = "http://localhost:8001/api/v1"


def start_scraping(keywords: Optional[list] = None, max_results: int = 20):
    """Start a scraping task"""
    print("🚀 Starting scraping task...")
    
    payload = {
        "keywords": keywords or ["math tutor needed", "looking for math tutor"],
        "max_results": max_results
    }
    
    response = requests.post(f"{API_BASE}/search/start", json=payload)
    
    if response.status_code == 200:
        data = response.json()
        task_id = data.get("task_id")
        print(f"✅ Task started successfully!")
        print(f"📋 Task ID: {task_id}")
        print(f"📊 Status: {data.get('status')}")
        return task_id
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text)
        return None


def check_task_status(task_id: str):
    """Check the status of a scraping task"""
    response = requests.get(f"{API_BASE}/search/task/{task_id}")
    
    if response.status_code == 200:
        data = response.json()
        return data
    else:
        print(f"❌ Error checking task: {response.status_code}")
        return None


def get_results(limit: int = 10, status: Optional[str] = None):
    """Get scraped results from database"""
    print(f"\n📊 Fetching results (limit: {limit})...")
    
    params = {"limit": limit}
    if status:
        params["status"] = status
    
    response = requests.get(f"{API_BASE}/results", params=params)
    
    if response.status_code == 200:
        data = response.json()
        results = data.get('items', [])
        total = data.get('total', 0)
        
        print(f"✅ Found {len(results)} results (Total in DB: {total})\n")
        
        for i, result in enumerate(results, 1):
            print(f"{'='*80}")
            print(f"Result #{i}")
            print(f"{'='*80}")
            print(f"👤 Name: {result.get('name', 'N/A')}")
            print(f"📍 Location: {result.get('location', 'N/A')}")
            print(f"🔍 Keyword: {result.get('search_keyword', 'N/A')}")
            print(f"📝 Content: {result.get('post_content', 'N/A')[:200]}...")
            print(f"🔗 Post URL: {result.get('post_url', 'N/A')}")
            print(f"👤 Profile URL: {result.get('profile_url', 'N/A')}")
            print(f"📅 Scraped: {result.get('scraped_at', 'N/A')}")
            print(f"✅ Status: {result.get('status', 'N/A')}")
            print()
        
        return results
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text)
        return []


def export_to_json(filename: str = "scraped_results.json"):
    """Export all results to JSON file"""
    print(f"\n💾 Exporting results to {filename}...")
    
    response = requests.get(f"{API_BASE}/results", params={"limit": 1000})
    
    if response.status_code == 200:
        data = response.json()
        results = data.get('items', [])
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"✅ Exported {len(results)} results to {filename}")
    else:
        print(f"❌ Error: {response.status_code}")


def main():
    print("="*80)
    print("Facebook Scraper - Quick Start")
    print("="*80)
    
    # Check if API is running
    try:
        response = requests.get("http://localhost:8001/health")
        if response.status_code != 200:
            print("❌ API is not running.")
            print("   Start the API with: docker compose up -d")
            print("   Or run without API: python run_standalone.py")
            return
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to API.")
        print("   Start the API with: docker compose up -d")
        print("   Or run without API: python run_standalone.py")
        return
    
    print("\nWhat would you like to do?")
    print("1. Start new scraping task")
    print("2. View scraped results")
    print("3. Export results to JSON")
    print("4. Check task status")
    
    choice = input("\nEnter choice (1-4): ").strip()
    
    if choice == "1":
        keywords_input = input("\nEnter keywords (comma-separated) or press Enter for defaults: ").strip()
        keywords = [k.strip() for k in keywords_input.split(",")] if keywords_input else None
        
        max_results = input("Enter max results per keyword (default 20): ").strip()
        max_results = int(max_results) if max_results else 20
        
        task_id = start_scraping(keywords, max_results)
        
        if task_id:
            print("\n⏳ Monitoring task progress...")
            print("(This may take several minutes depending on results)")
            
            while True:
                time.sleep(10)
                status_data = check_task_status(task_id)
                if status_data:
                    status = status_data.get("status")
                    print(f"📊 Status: {status}")
                    
                    if status in ["completed", "failed"]:
                        if status == "completed":
                            print("\n✅ Scraping completed!")
                            print("\nFetching results...")
                            get_results(limit=10)
                        else:
                            print("\n❌ Scraping failed!")
                            if "error" in status_data:
                                print(f"Error: {status_data['error']}")
                        break
    
    elif choice == "2":
        limit = input("\nHow many results to show? (default 10): ").strip()
        limit = int(limit) if limit else 10
        
        filter_status = input("Filter by status? (pending/contacted/converted or press Enter for all): ").strip()
        filter_status = filter_status if filter_status else None
        
        get_results(limit, filter_status)
    
    elif choice == "3":
        filename = input("\nEnter filename (default: scraped_results.json): ").strip()
        filename = filename if filename else "scraped_results.json"
        export_to_json(filename)
    
    elif choice == "4":
        task_id = input("\nEnter task ID: ").strip()
        status_data = check_task_status(task_id)
        if status_data:
            print(f"\n📊 Task Status: {status_data.get('status')}")
            if "result" in status_data:
                print(f"Results: {json.dumps(status_data['result'], indent=2)}")
    
    else:
        print("Invalid choice")


if __name__ == "__main__":
    main()
