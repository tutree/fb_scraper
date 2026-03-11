#!/bin/bash

set -x

source ./config.sh

NAME="true-search-scraper-$(echo $RANDOM|md5sum|head -c 8)"
URL="$1"

docker run --rm -it --name ${NAME} \
    --network proxy-pool \
    -e CHROME_URL="$CHROME_URL" \
    -e CHROME_TOKEN="$CHROME_TOKEN" \
    -e PROXY_IP="$PROXY_IP" \
    -e PROXY_USER="$PROXY_USER" \
    -e PROXY_PASS="$PROXY_PASS" \
    -e REDIS_HOST="$REDIS_HOST" \
    -e REDIS_PORT="$REDIS_PORT" \
    -e TWO_CAPTCHA_KEY="$TWO_CAPTCHA_KEY" \
    -e GOOGLE_SHEET_API_KEY="$GOOGLE_SHEET_API_KEY" \
    ${CONTAINER_NAME} yarn process-url $URL
