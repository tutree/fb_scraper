#!/bin/bash

# Facebook Scraper - Setup Script

echo "🔧 Setting up Facebook Scraper..."

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "✅ Python version: $PYTHON_VERSION"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
else
    echo "✅ Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "📥 Installing Python dependencies..."
pip install -r requirements.txt

# Install Playwright browsers
echo "🌐 Installing Playwright browsers..."
playwright install chromium

# Create config files from examples
if [ ! -f ".env" ]; then
    echo "📝 Creating .env from example..."
    cp .env.example .env
    echo "⚠️  Please edit .env with your credentials"
fi

if [ ! -f "config/credentials.json" ]; then
    echo "📝 Creating config/credentials.json from example..."
    cp config/credentials.json.example config/credentials.json
    echo "⚠️  Please edit config/credentials.json with your Facebook accounts"
fi

if [ ! -f "config/keywords.json" ]; then
    echo "📝 Creating config/keywords.json from example..."
    cp config/keywords.json.example config/keywords.json
fi

# Create logs directory
mkdir -p logs

# Setup PostgreSQL
echo ""
echo "🗄️  Setting up PostgreSQL database..."
echo "This requires sudo access to create database user and database."
read -p "Do you want to setup PostgreSQL now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo -u postgres psql -c "CREATE USER scraper WITH PASSWORD 'scraper123';" 2>/dev/null || echo "User may already exist"
    sudo -u postgres psql -c "CREATE DATABASE math_tutor_db OWNER scraper;" 2>/dev/null || echo "Database may already exist"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE math_tutor_db TO scraper;" 2>/dev/null
    
    # Initialize database tables
    echo "📊 Initializing database tables..."
    python scripts/init_db.py
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env with your credentials"
echo "2. Edit config/credentials.json with your Facebook accounts"
echo "3. Edit config/keywords.json with your search keywords"
echo "4. Run: ./start.sh"
echo ""
