# Deploy Facebook Scraper to US PC

## Quick Setup (5 minutes via AnyDesk)

### Step 1: Create folder on US PC
```powershell
mkdir C:\facebook-scraper
cd C:\facebook-scraper
```

### Step 2: Transfer these files via AnyDesk file transfer
- `requirements.txt`
- `run_scraper_direct.py`
- `app/` folder (entire directory)
- `config/` folder (credentials.json, keywords.json)
- `cookies/` folder (your session cookies)
- `.env` file

### Step 3: Install Python dependencies on US PC
```powershell
# Check Python version (need 3.11+)
python --version

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### Step 4: Update .env file for local execution
```env
# Database connection - point to your local PC via Tailscale
DATABASE_URL=postgresql://scraper:scraper123@100.98.179.12:5432/math_tutor_db

# No proxy needed - running directly on US PC!
PROXY_LIST=

# Gemini API key
GEMINI_API_KEY=your_key_here

# Facebook credentials (not needed if using cookies)
FACEBOOK_EMAIL=
FACEBOOK_PASSWORD=
```

### Step 5: Run the scraper
```powershell
python run_scraper_direct.py
```

## Benefits of Running on US PC

✅ **Zero latency** - Direct connection to Facebook (no proxy)
✅ **10x faster** - Pages load in 2-3 seconds instead of 60+ seconds
✅ **More reliable** - No timeout issues
✅ **Same database** - Still saves to your local PC database via Tailscale

## Alternative: Run as Windows Service

To run continuously in the background:

```powershell
# Install NSSM (service manager)
choco install nssm

# Create service
nssm install FacebookScraper "C:\Python311\python.exe" "C:\facebook-scraper\run_scraper_direct.py"
nssm set FacebookScraper AppDirectory "C:\facebook-scraper"

# Start service
nssm start FacebookScraper
```

## Monitoring from Local PC

You can still monitor logs via SSH:
```bash
ssh shakil@100.85.92.28 "tail -f C:\facebook-scraper\logs\scraper.log"
```

## Database Access

The scraper will connect to your local PC's database via Tailscale:
- Your local PC: `100.98.179.12:5432`
- US PC connects over Tailscale network
- Same 312ms latency, but only for database writes (not page loads!)
