# Usage Guide

## Quick Start

### First Time Setup

```bash
# 1. Run setup script
./setup.sh

# 2. Configure your credentials
nano .env
nano config/credentials.json
nano config/keywords.json

# 3. Start the application
./start.sh
```

### Daily Usage

```bash
# Start the application
./start.sh

# Or manually
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

## API Usage Examples

### 1. Start a Scraping Job

**Using curl:**
```bash
curl -X POST http://localhost:8001/api/search/run \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": ["math tutor needed", "calculus help"],
    "max_results": 50
  }'
```

**Using Python:**
```python
import requests

response = requests.post(
    "http://localhost:8001/api/search/run",
    json={
        "keywords": ["math tutor needed"],
        "max_results": 50
    }
)
print(response.json())
```

**Response:**
```json
{
  "success": true,
  "total_results": 45,
  "keywords_searched": 2
}
```

### 2. Get Scraped Results

**Get all results:**
```bash
curl http://localhost:8001/api/search/results
```

**Get with filters:**
```bash
# Get first 10 results
curl "http://localhost:8001/api/search/results?limit=10&skip=0"

# Filter by status
curl "http://localhost:8001/api/search/results?status=pending"

# Filter by keyword
curl "http://localhost:8001/api/search/results?keyword=math%20tutor"
```

**Using Python:**
```python
import requests

response = requests.get(
    "http://localhost:8001/api/search/results",
    params={"limit": 10, "status": "pending"}
)
results = response.json()

for result in results:
    print(f"Name: {result['name']}")
    print(f"Content: {result['post_content'][:100]}...")
    print(f"URL: {result['post_url']}")
    print("---")
```

### 3. Update Result Status

```bash
curl -X PUT http://localhost:8001/api/search/results/{result_id}/status \
  -H "Content-Type: application/json" \
  -d '{"status": "contacted"}'
```

### 4. Check System Status

```bash
curl http://localhost:8001/api/search/status
```

## Interactive API Documentation

Visit http://localhost:8001/docs for interactive API documentation where you can:
- See all available endpoints
- Test API calls directly in the browser
- View request/response schemas
- Download OpenAPI specification

## Configuration Tips

### Multiple Facebook Accounts

Edit `config/credentials.json`:
```json
{
  "facebook_accounts": [
    {
      "uid": "account1_uid",
      "password": "password1",
      "totp_secret": "2FA_SECRET_1",
      "active": true
    },
    {
      "uid": "account2_uid",
      "password": "password2",
      "totp_secret": null,
      "active": true
    }
  ]
}
```

The scraper will rotate between active accounts automatically.

### Search Keywords

Edit `config/keywords.json`:
```json
{
  "searchKeywords": [
    "math tutor needed",
    "looking for calculus help",
    "need algebra tutor",
    "physics tutor wanted",
    "statistics help needed"
  ]
}
```

### Proxy Configuration

Edit `.env`:
```env
# Single proxy
PROXY_LIST=http://user:pass@proxy.example.com:8080

# Multiple proxies (comma-separated)
PROXY_LIST=http://user:pass@proxy1.com:8080,http://user:pass@proxy2.com:8080
```

## Best Practices

### 1. Rate Limiting
```python
# Don't scrape too frequently
# Wait 30-60 minutes between sessions
import time

for keyword in keywords:
    scrape(keyword)
    time.sleep(1800)  # 30 minutes
```

### 2. Result Limits
```python
# Limit results per session to avoid detection
max_results = 50  # Recommended: 50-100
```

### 3. Account Rotation
- Use 2-3 accounts minimum
- Rotate accounts between sessions
- Don't use same account within 1 hour

### 4. Proxy Usage
- Use residential proxies (not datacenter)
- Rotate proxies for each account
- Check proxy health regularly

### 5. Monitoring
```bash
# Check logs for errors
tail -f logs/app.log

# Check for detection warnings
grep -i "error\|warning\|blocked" logs/app.log
```

## Troubleshooting

### Application Won't Start

```bash
# Check if port is in use
lsof -i :8001

# Kill existing process
kill -9 $(lsof -t -i:8001)

# Use different port
uvicorn app.main:app --host 0.0.0.0 --port 8002
```

### Database Connection Error

```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Restart PostgreSQL
sudo systemctl restart postgresql

# Test connection
psql -U scraper -d math_tutor_db -c "SELECT 1"
```

### Login Failures

1. Check credentials in `config/credentials.json`
2. Verify 2FA secret is correct (if using)
3. Check if account is locked/restricted
4. Try logging in manually first
5. Check proxy is working

### No Results Found

1. Check keywords are relevant
2. Verify Facebook search returns results manually
3. Check logs for errors: `tail -f logs/app.log`
4. Try different search terms
5. Increase `max_results` parameter

### Detection/Blocking

If you get blocked:
1. Stop scraping immediately
2. Wait 24-48 hours
3. Use different account
4. Use better proxies
5. Reduce scraping frequency
6. Increase delays between actions

## Advanced Usage

### Custom Search Script

```python
import asyncio
from app.core.database import SessionLocal
from app.services.scraper import ScraperService

async def custom_scrape():
    db = SessionLocal()
    scraper = ScraperService(db)
    
    keywords = ["math tutor", "calculus help"]
    results = await scraper.run_search(keywords, max_results=30)
    
    print(f"Found {results['total_results']} results")
    db.close()

if __name__ == "__main__":
    asyncio.run(custom_scrape())
```

### Export Results to CSV

```python
import csv
import requests

response = requests.get("http://localhost:8001/api/search/results?limit=1000")
results = response.json()

with open('results.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['name', 'location', 'post_content', 'post_url', 'profile_url'])
    writer.writeheader()
    writer.writerows(results)

print(f"Exported {len(results)} results to results.csv")
```

### Scheduled Scraping (Cron)

```bash
# Edit crontab
crontab -e

# Add this line to scrape every 6 hours
0 */6 * * * cd /path/to/fb_scrapper && ./venv/bin/python -c "import requests; requests.post('http://localhost:8001/api/search/run', json={'max_results': 50})"
```

## Support

For issues:
1. Check logs: `tail -f logs/app.log`
2. Review this guide
3. Check README.md
4. Open GitHub issue

## Safety Reminders

⚠️ **Important:**
- Respect Facebook's Terms of Service
- Don't scrape personal data without consent
- Use for legitimate business purposes only
- Comply with GDPR/CCPA regulations
- Don't spam or harass users
- Use responsibly and ethically
