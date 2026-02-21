# Facebook Scraper - Anti-Detection Improvements

## Improvements Implemented

### 1. Enhanced Browser Fingerprinting
- **Randomized viewports**: 6 different screen resolutions to avoid consistent fingerprints
- **Randomized user agents**: 5 different browser user agents (Chrome, Firefox, Safari)
- **Randomized locales and timezones**: Varies between en-US, en-GB, en-CA and multiple timezones
- **Device scale factor randomization**: Simulates different display densities
- **Touch support randomization**: Sometimes enables touch to mimic different devices

### 2. Advanced Stealth Scripts
- Hides webdriver property completely
- Mocks realistic browser plugins
- Adds chrome runtime objects
- Mocks hardware concurrency (8 cores)
- Mocks device memory (8GB)
- Adds realistic network connection info (4g, 50ms rtt)
- Overrides toString to hide automation traces

### 3. Human-Like Behavior
- **Enhanced warmup session**: 
  - Scrolls homepage before searching
  - Random mouse movements with steps (10-20 steps)
  - Sometimes scrolls back to top
  - Longer delays (3-7 seconds)

- **Natural search behavior**:
  - Types search queries character by character (0.1-0.3s per char)
  - Clicks search box before typing
  - Presses Enter instead of direct URL navigation
  - Clicks "Posts" tab manually

- **Human-like scrolling**:
  - Variable scroll distances (300-800px)
  - Sometimes scrolls back up (30% chance)
  - Random reading pauses (2-5 seconds, 40% chance)
  - Longer delays between scrolls (4-8 seconds)

- **Login improvements**:
  - Mouse movement before typing (10-20 steps)
  - Character-by-character typing with delays
  - Realistic delays between fields (0.8-1.8s)

### 4. Additional Browser Arguments
- `--disable-infobars`
- `--start-maximized`
- `--disable-extensions`
- `--no-first-run`
- `--no-default-browser-check`
- `--disable-default-apps`

## Running the Application

### Local Setup (Recommended - Faster)

1. **Install dependencies**:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

2. **Setup database**:
```bash
# Create PostgreSQL user and database
sudo -u postgres psql -c "CREATE USER scraper WITH PASSWORD 'scraper123';"
sudo -u postgres psql -c "CREATE DATABASE math_tutor_db OWNER scraper;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE math_tutor_db TO scraper;"

# Initialize tables
python scripts/init_db.py
```

3. **Start the application**:
```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

4. **Access the API**:
- API: http://localhost:8001
- Docs: http://localhost:8001/docs

### Docker Setup (Alternative)

```bash
docker compose build
docker compose up
```

## API Endpoints

- `GET /` - API info
- `GET /docs` - Interactive API documentation
- `POST /api/search/run` - Start scraping
- `GET /api/search/results` - Get scraped results
- `GET /api/search/status` - Check scraping status

## Configuration

Edit `.env` file:
```env
DATABASE_URL=postgresql://scraper:scraper123@localhost:5432/math_tutor_db
REDIS_URL=redis://localhost:6379
FACEBOOK_EMAIL=your_uid_or_email
FACEBOOK_PASSWORD=your_password
PROXY_LIST=http://user:pass@ip:port,http://user:pass@ip:port
```

Edit `config/keywords.json` for search terms.

## Detection Risk Assessment

### Low Risk Factors ✅
- Randomized fingerprints make tracking harder
- Human-like timing and behavior patterns
- Proper stealth scripts hide automation
- Proxy rotation (if configured)
- Account rotation support

### Medium Risk Factors ⚠️
- Still using Playwright (detectable with advanced checks)
- Headless mode can be detected
- IP reputation matters (use quality proxies)

### Recommendations
1. Use residential proxies (not datacenter)
2. Limit scraping to 50-100 posts per session
3. Take breaks between sessions (30+ minutes)
4. Use aged Facebook accounts with activity history
5. Enable 2FA with TOTP for account security
6. Run in non-headless mode for better stealth
7. Don't scrape too frequently from same account

## Current Status
✅ Application running on port 8001
✅ Database initialized
✅ Anti-detection improvements implemented
✅ Ready to use
