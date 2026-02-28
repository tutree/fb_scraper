@echo off
REM Facebook Scraper - US PC Launcher
REM Run this on the US PC to start scraping

echo ================================================================================
echo FACEBOOK SCRAPER - US PC MODE
echo ================================================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install/update dependencies
echo Installing dependencies...
pip install -q -r requirements.txt

REM Install Playwright browsers if needed
echo Checking Playwright browsers...
playwright install chromium

echo.
echo ================================================================================
echo Starting scraper...
echo ================================================================================
echo.

REM Run the scraper
python run_standalone.py

REM Keep window open if there's an error
if errorlevel 1 (
    echo.
    echo ================================================================================
    echo ERROR: Scraper exited with error code %errorlevel%
    echo ================================================================================
    pause
)
