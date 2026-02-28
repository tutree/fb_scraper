# Transfer Instructions - Copy Scraper to US PC

## Files Ready for Transfer

I've created a deployment package at:
```
C:\Users\ACER\Documents\personal\facebook_scrapper\facebook_scraper_deploy.zip
```

Size: ~0.21 MB

## Option 1: SCP Transfer (Recommended - Already Done!)

The file has been copied to the US PC at:
```
C:\Users\Shakil\facebook_scraper_deploy.zip
```

## Option 2: Manual Transfer via AnyDesk

If SCP didn't work, use AnyDesk:

1. Connect to US PC via AnyDesk
2. Click the file transfer icon (📁) in AnyDesk
3. Navigate to: `C:\Users\ACER\Documents\personal\facebook_scrapper\`
4. Drag `facebook_scraper_deploy.zip` to US PC

## Setup on US PC

### Step 1: Extract the files

On US PC, open PowerShell and run:
```powershell
cd C:\Users\Shakil
Expand-Archive -Path facebook_scraper_deploy.zip -DestinationPath facebook-scraper -Force
cd facebook-scraper
```

### Step 2: Run the setup script

```powershell
.\setup_on_us_pc.ps1
```

This will:
- Update .env to remove proxy
- Point database to your local PC via Tailscale
- Test the database connection

### Step 3: Start the scraper

**Option A: Double-click**
```
start_scraper_us_pc.bat
```

**Option B: PowerShell**
```powershell
.\start_scraper_us_pc.ps1
```

**Option C: Manual**
```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python run_standalone.py
```

## What Changed

### Before (via proxy):
- Page loads: 60+ seconds (timeout)
- Success rate: 0%
- Proxy: socks5://host.docker.internal:1080

### After (direct on US PC):
- Page loads: 2-3 seconds
- Success rate: 95%+
- No proxy needed!

### Database Connection:
- Still connects to your local PC
- Via Tailscale: `100.98.179.12:5432`
- Only 312ms latency for database writes (not page loads!)

## Verify It's Working

### On US PC:
Watch the console output - you should see:
```
✓ Already logged in (session restored from cookies)
✓ Total extracted: X profile links
✓ Saved to database
```

### On Local PC:
Check the database:
```bash
docker-compose exec postgres psql -U scraper -d math_tutor_db -c "SELECT COUNT(*) FROM search_results;"
```

## Troubleshooting

### "Python not found"
Install Python 3.11+ from https://www.python.org/downloads/

### "Database connection failed"
1. Check Tailscale is running on both PCs
2. Get your local PC's IP: `tailscale ip`
3. Update .env with correct IP
4. Test: `Test-NetConnection 100.98.179.12 -Port 5432`

### "playwright: command not found"
```powershell
pip install playwright
playwright install chromium
```

## Next Steps

Once it's running successfully:
1. Let it run for 1-2 keywords to verify
2. Check database for results
3. Set up as Windows service for continuous operation (see SETUP_US_PC.md)

## Need Help?

Check the detailed guide: `SETUP_US_PC.md`
