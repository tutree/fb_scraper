#!/bin/bash

# Facebook Scraper - Quick Start Script

echo "🚀 Starting Facebook Scraper..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Please run setup.sh first."
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "⚠️  Please edit .env with your credentials before running."
    exit 1
fi

# Check if config files exist
if [ ! -f "config/credentials.json" ]; then
    echo "⚠️  config/credentials.json not found. Copying from example..."
    cp config/credentials.json.example config/credentials.json
    echo "⚠️  Please edit config/credentials.json with your Facebook accounts."
    exit 1
fi

if [ ! -f "config/keywords.json" ]; then
    echo "⚠️  config/keywords.json not found. Copying from example..."
    cp config/keywords.json.example config/keywords.json
fi

# Check if PostgreSQL is running
if ! pg_isready -h localhost -p 5432 > /dev/null 2>&1; then
    echo "⚠️  PostgreSQL is not running. Starting with systemctl..."
    sudo systemctl start postgresql
fi

# Check if Redis is running
if ! redis-cli ping > /dev/null 2>&1; then
    echo "⚠️  Redis is not running. Starting with systemctl..."
    sudo systemctl start redis
fi

# Check if database is initialized
if ! psql -U scraper -d math_tutor_db -c "SELECT 1" > /dev/null 2>&1; then
    echo "📊 Initializing database..."
    python scripts/init_db.py
fi

# Start the application
echo "✅ Starting API server on http://localhost:8001"
echo "📚 API Documentation: http://localhost:8001/docs"
echo ""
echo "Press CTRL+C to stop the server"
echo ""

uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
