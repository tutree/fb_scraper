#!/bin/sh
# When HEADLESS=false, start virtual display so Chromium headed mode (hover tooltips) works like local.
if [ "$HEADLESS" = "false" ]; then
  /usr/bin/Xvfb :99 -screen 0 1920x1080x24 &
  export DISPLAY=:99
  sleep 2
fi
exec "$@"
