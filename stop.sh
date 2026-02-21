#!/bin/bash

# Facebook Scraper - Stop Script

echo "🛑 Stopping Facebook Scraper..."

# Find and kill uvicorn process
PIDS=$(ps aux | grep "uvicorn app.main:app" | grep -v grep | awk '{print $2}')

if [ -z "$PIDS" ]; then
    echo "✅ No scraper process found running"
else
    echo "Found process(es): $PIDS"
    for PID in $PIDS; do
        echo "Killing process $PID..."
        kill -9 $PID
    done
    echo "✅ Scraper stopped successfully"
fi

# Also check for any Python processes running the app
PYTHON_PIDS=$(ps aux | grep "python.*app.main" | grep -v grep | awk '{print $2}')
if [ ! -z "$PYTHON_PIDS" ]; then
    echo "Found additional Python processes: $PYTHON_PIDS"
    for PID in $PYTHON_PIDS; do
        echo "Killing process $PID..."
        kill -9 $PID
    done
fi

echo "✅ All scraper processes stopped"
