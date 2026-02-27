@echo off
echo Starting PostgreSQL database, FastAPI backend, and React dashboard...
echo.

REM Check if PostgreSQL is already running
docker ps | findstr postgres >nul 2>&1
if %errorlevel% equ 0 (
    echo PostgreSQL is already running.
) else (
    echo Starting PostgreSQL database...
    docker-compose up -d postgres
    if %errorlevel% neq 0 (
        echo Failed to start PostgreSQL. Make sure Docker is running.
        pause
        exit /b 1
    )
    echo Waiting for database to be ready...
    ping 127.0.0.1 -n 6 >nul
)

REM Start backend in a new window
start "Backend API" cmd /k "venv\Scripts\activate && uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload"

REM Wait a bit for backend to start
ping 127.0.0.1 -n 4 >nul

REM Start frontend in a new window
start "Frontend Dashboard" cmd /k "cd admin-dashboard && npm run dev"

echo.
echo ================================
echo Services started successfully!
echo ================================
echo PostgreSQL: localhost:5432
echo Backend API: http://localhost:5000
echo API Docs: http://localhost:5000/docs
echo Frontend Dashboard: http://localhost:5173
echo.
echo To stop:
echo - Close the terminal windows for backend and frontend
echo - Run: docker-compose down
echo.
pause
