#!/bin/bash

# Start PostgreSQL with Docker
echo "Starting PostgreSQL database..."
docker-compose up -d postgres

if [ $? -ne 0 ]; then
    echo "Failed to start PostgreSQL. Make sure Docker is running."
    exit 1
fi

# Wait for database to be ready
echo "Waiting for database to be ready..."
sleep 5

# Start Backend API only (no scraping)
echo "Starting FastAPI backend..."
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload &
BACKEND_PID=$!

# Wait for backend to start
sleep 3

# Start Frontend Dashboard
echo "Starting React dashboard..."
cd admin-dashboard
npm run dev &
FRONTEND_PID=$!

echo ""
echo "================================"
echo "Services started successfully!"
echo "================================"
echo "PostgreSQL: localhost:5432"
echo "Backend API: http://localhost:5000"
echo "API Docs: http://localhost:5000/docs"
echo "Frontend Dashboard: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop backend and frontend"
echo "Then run: docker-compose down"
echo ""

# Wait for Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT
wait
