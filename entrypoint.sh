#!/bin/sh
# When HEADLESS=false, start virtual display so Chromium headed mode works.
if [ "$HEADLESS" = "false" ]; then
  # Clean up stale lock files from previous container runs
  rm -f /tmp/.X99-lock 2>/dev/null || true
  rm -f /tmp/.X11-unix/X99 2>/dev/null || true

  /usr/bin/Xvfb :99 -screen 0 1920x1080x24 &
  export DISPLAY=:99
  sleep 2
fi
exec "$@"
