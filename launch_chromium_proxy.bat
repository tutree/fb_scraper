@echo off
setlocal
cd /d "%~dp0"
REM Facebook session for scraper: --one --fb-session --url https://www.facebook.com
REM Clipboard on close (Ctrl+V). Save anywhere: --save-storage path.json
REM Restore: --load-storage-state path.json
python scripts\launch_chromium_proxy.py %*
if errorlevel 1 pause
