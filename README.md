# Facebook Math Tutor Scraper

A sophisticated Facebook scraper designed to find potential math tutoring clients by searching for relevant posts. Built with anti-detection features to minimize the risk of being blocked.

## Features

- 🎭 Advanced anti-detection (randomized fingerprints, human-like behavior)
- 🔄 Multi-account rotation support
- 🔐 Automatic 2FA handling with TOTP
- 🌐 Proxy rotation support
- 📊 PostgreSQL database for storing results
- 🚀 FastAPI REST API
- 🔍 Customizable keyword search
- 📝 Comprehensive logging and diagnostics
- 🔧 Built-in diagnostic tools for troubleshooting

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL
- Redis

### Installation

1. **Clone the repository**:
```bash
git clone <your-repo-url>
cd fb_scrapper
```

2. **Create virtual environment**:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
playwright install chromium
```

4. **Configure environment**:
```bash
# Copy example files
cp .env.example .env
cp config/credentials.json.example config/credentials.json
cp config/keywords.json.example config/keywords.json

# Edit with your credentials
nano .env
nano config/credentials.json
nano config/keywords.json
```

5. **Setup database**:
```bash
# Create PostgreSQL user and database
sudo -u postgres psql -c "CREATE USER scraper WITH PASSWORD 'scraper123';"
sudo -u postgres psql -c "CREATE DATABASE math_tutor_db OWNER scraper;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE math_tutor_db TO scraper;"

# Initialize tables
python scripts/init_db.py
```

6. **Verify setup** (recommended):
```bash
# Run diagnostic to check everything is configured correctly
python test_scraper.py
```

This will verify:
- ✓ Database connectivity
- ✓ Configuration files
- ✓ Account setup
- ✓ Keyword loading

7. **Run the application**:
```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

8. **Access the API**:
- API: http://localhost:8001
- Interactive Docs: http://localhost:8001/docs

## Configuration

### Environment Variables (.env)

```env
DATABASE_URL=postgresql://scraper:scraper123@localhost:5432/math_tutor_db
REDIS_URL=redis://localhost:6379
FACEBOOK_EMAIL=your_facebook_uid
FACEBOOK_PASSWORD=your_password
PROXY_LIST=http://user:pass@ip:port
```

### Multiple Accounts (config/credentials.json)

```json
{
  "facebook_accounts": [
    {
      "uid": "61564814922126",
      "password": "your_password",
      "totp_secret": "YOUR2FASECRET",
      "active": true
    }
  ]
}
```

### Search Keywords (config/keywords.json)

```json
{
  "searchKeywords": [
    "math tutor needed",
    "looking for calculus help"
  ]
}
```

## API Endpoints

### Start Scraping
```bash
curl -X POST http://localhost:8001/api/search/run \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["math tutor"], "max_results": 50}'
```

### Get Results
```bash
curl http://localhost:8001/api/search/results?limit=10
```

### Check Status
```bash
curl http://localhost:8001/api/search/status
```

## Docker Deployment

```bash
# Build and run
docker compose up -d

# View logs
docker compose logs -f api

# Stop
docker compose down
```

## Anti-Detection Features

✅ Randomized browser fingerprints (viewport, user agent, timezone)  
✅ Human-like scrolling and mouse movements  
✅ Character-by-character typing with delays  
✅ Session warmup before scraping  
✅ Random pauses and reading breaks  
✅ Stealth scripts to hide automation  
✅ Proxy rotation support  
✅ Account rotation support  

## Best Practices

1. **Use Quality Proxies**: Residential proxies work best
2. **Limit Scraping**: 50-100 posts per session
3. **Take Breaks**: 30+ minutes between sessions
4. **Use Aged Accounts**: Accounts with activity history
5. **Enable 2FA**: Use TOTP for account security
6. **Monitor Logs**: Check for any detection warnings

## Project Structure

```
fb_scrapper/
├── app/
│   ├── api/          # API routes
│   ├── core/         # Config, database, logging
│   ├── models/       # Database models
│   ├── schemas/      # Pydantic schemas
│   ├── services/     # Business logic
│   └── utils/        # Utilities
├── config/           # Configuration files
├── logs/             # Application logs
├── scripts/          # Database initialization
└── requirements.txt  # Python dependencies
```

## Troubleshooting

### Port Already in Use
```bash
# Use a different port
uvicorn app.main:app --host 0.0.0.0 --port 8002
```

### Database Connection Error
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Verify credentials in .env
```

### Playwright Browser Issues
```bash
# Reinstall browsers
playwright install chromium --force
```

## Troubleshooting

### Scraper Not Collecting Data?

**Quick Diagnostic:**
```bash
python test_scraper.py
```

This will check:
- Database connectivity
- Configuration files
- Account setup
- Keyword loading

**Monitor Logs:**
```bash
# Watch logs in real-time
tail -f logs/app.log

# Search for errors
grep -i error logs/app.log

# Check if posts are being saved
grep -i "saved post" logs/app.log
```

**Common Issues:**

1. **No posts found:** Keywords might be too specific
2. **Login failed:** Check credentials in `config/credentials.json`
3. **Database errors:** Verify PostgreSQL is running and credentials are correct
4. **No keywords:** Copy `config/keywords.json.example` to `config/keywords.json`

**Detailed Guides:**
- 📖 [Quick Debug Guide](QUICK_DEBUG.md) - Fast problem resolution
- 📖 [Troubleshooting Guide](TROUBLESHOOTING.md) - Comprehensive solutions
- 📖 [Logging Documentation](LOGGING_IMPROVEMENTS.md) - Understanding logs

## Security Notes

⚠️ **Never commit sensitive data**:
- `.env` files
- `config/credentials.json`
- `config/keywords.json`
- Log files
- Screenshots

All sensitive files are in `.gitignore`.

## Legal Disclaimer

This tool is for educational purposes only. Ensure you comply with:
- Facebook's Terms of Service
- Local data protection laws (GDPR, CCPA, etc.)
- Ethical scraping practices

Use responsibly and at your own risk.

## License

MIT License - See LICENSE file for details

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## Support

For issues and questions, please open a GitHub issue.
