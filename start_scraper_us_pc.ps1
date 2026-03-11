# Facebook Scraper - US PC Launcher (PowerShell)
# Run this on the US PC to start scraping

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "FACEBOOK SCRAPER - US PC MODE" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is installed
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ ERROR: Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host "  Please install Python 3.11+ from https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if virtual environment exists
if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
}

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"

# Install/update dependencies
Write-Host "Installing dependencies..." -ForegroundColor Yellow
pip install -q -r requirements.txt

# Install Playwright browsers if needed
Write-Host "Checking Playwright browsers..." -ForegroundColor Yellow
playwright install chromium

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "Starting scraper..." -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Run the scraper
python run_standalone.py

# Check exit code
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "================================================================================" -ForegroundColor Red
    Write-Host "ERROR: Scraper exited with error code $LASTEXITCODE" -ForegroundColor Red
    Write-Host "================================================================================" -ForegroundColor Red
    Read-Host "Press Enter to exit"
}
