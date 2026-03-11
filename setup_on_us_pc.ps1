# Setup Script for US PC
# Run this script on the US PC after transferring files

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "FACEBOOK SCRAPER - US PC SETUP" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Get your local PC's Tailscale IP
Write-Host "Enter your LOCAL PC's Tailscale IP (default: 100.98.179.12):" -ForegroundColor Yellow
$localPcIp = Read-Host "IP Address"
if ([string]::IsNullOrWhiteSpace($localPcIp)) {
    $localPcIp = "100.98.179.12"
}

Write-Host "`nUpdating .env file..." -ForegroundColor Yellow

# Read current .env
$envContent = Get-Content .env -Raw

# Remove proxy configuration
$envContent = $envContent -replace 'PROXY_LIST=socks5://.*', 'PROXY_LIST='

# Update database URL to point to local PC
$envContent = $envContent -replace 'DATABASE_URL=postgresql://scraper:scraper123@[^:]+:5432', "DATABASE_URL=postgresql://scraper:scraper123@${localPcIp}:5432"

# Save updated .env
$envContent | Set-Content .env -NoNewline

Write-Host "✓ Updated .env file" -ForegroundColor Green
Write-Host "  - Removed proxy (running directly on US PC)" -ForegroundColor Gray
Write-Host "  - Database: postgresql://scraper:scraper123@${localPcIp}:5432/math_tutor_db" -ForegroundColor Gray

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "Testing database connection..." -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# Test database connection
$testResult = Test-NetConnection -ComputerName $localPcIp -Port 5432 -WarningAction SilentlyContinue

if ($testResult.TcpTestSucceeded) {
    Write-Host "✓ Database connection successful!" -ForegroundColor Green
} else {
    Write-Host "✗ Cannot connect to database at ${localPcIp}:5432" -ForegroundColor Red
    Write-Host "  Make sure:" -ForegroundColor Yellow
    Write-Host "  1. Tailscale is running on both PCs" -ForegroundColor Yellow
    Write-Host "  2. PostgreSQL is running on local PC" -ForegroundColor Yellow
    Write-Host "  3. PostgreSQL allows remote connections" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "To start the scraper, run:" -ForegroundColor Yellow
Write-Host "  .\start_scraper_us_pc.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "Or double-click:" -ForegroundColor Yellow
Write-Host "  scripts\\launchers\\start_scraper_us_pc.bat" -ForegroundColor Cyan
Write-Host ""

Read-Host "Press Enter to exit"
