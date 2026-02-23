#!/usr/bin/env bash

USERNAME="32c770c8888277c1"
PASSWORD="1QZuS47U"
HOST="res.geonix.com"
URL="https://www.facebook.com"

for port in 10000 10001 10002 10003 10004; do
  echo "Testing port $port..."
  curl -s -m 15 \
    --proxy "http://$USERNAME:$PASSWORD@$HOST:$port" \
    -w "Port $port → HTTP: %{http_code} | Time: %{time_total}s | Exit IP: %{remote_ip}\n" \
    -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36" \
    $URL
  echo "----------------------------------------"
  sleep 2  # small delay to avoid rate limits
done
