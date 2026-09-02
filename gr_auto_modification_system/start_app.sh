#!/bin/bash
# GR Auto Modification System - one-click launcher
#
# Starts the Flask app and automatically opens it in Chrome once the
# server is actually ready (so you never see "site can't be reached").
#
# You normally don't run this file directly - double-click the desktop
# icon created by create_desktop_shortcut.sh instead. To stop the app,
# close this terminal window or press Ctrl+C.

set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Use the project's virtual environment if one exists, otherwise fall
# back to whatever "python3" resolves to on this machine.
PYTHON_BIN="python3"
for candidate in "venv/bin/python" ".venv/bin/python" "env/bin/python"; do
  if [ -x "$DIR/$candidate" ]; then
    PYTHON_BIN="$DIR/$candidate"
    break
  fi
done

PORT="${PORT:-5000}"
URL="http://127.0.0.1:${PORT}/"

echo "GR Auto Modification System start ho raha hai..."
echo "Using: $PYTHON_BIN"
echo

# Start the Flask app in the background.
"$PYTHON_BIN" app.py &
APP_PID=$!

CLEANED_UP=0
cleanup() {
  if [ "$CLEANED_UP" -eq 1 ]; then
    return
  fi
  CLEANED_UP=1
  echo
  echo "App band ki jaa rahi hai..."
  kill "$APP_PID" 2>/dev/null
  wait "$APP_PID" 2>/dev/null
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

# Wait (up to ~30s) for the server to actually accept connections on
# $PORT before opening the browser - pure bash, no curl dependency.
echo "Server ready hone ka wait ho raha hai..."
ready=0
for i in $(seq 1 60); do
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo "App start nahi ho paayi. Neeche error dekho:"
    wait "$APP_PID"
    exit 1
  fi
  if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
    exec 3>&- 3<&-
    ready=1
    break
  fi
  sleep 0.5
done

if [ "$ready" -eq 1 ]; then
  echo "Server ready! Chrome me khol rahe hain: $URL"
  if command -v google-chrome >/dev/null 2>&1; then
    google-chrome "$URL" >/dev/null 2>&1 &
  elif command -v google-chrome-stable >/dev/null 2>&1; then
    google-chrome-stable "$URL" >/dev/null 2>&1 &
  elif command -v chromium-browser >/dev/null 2>&1; then
    chromium-browser "$URL" >/dev/null 2>&1 &
  elif command -v chromium >/dev/null 2>&1; then
    chromium "$URL" >/dev/null 2>&1 &
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
  else
    echo "Koi browser opener nahi mila - is link ko manually Chrome me kholo:"
    echo "  $URL"
  fi
else
  echo "Server 30 second me start nahi hua - is terminal me error check karo."
fi

echo
echo "=========================================================="
echo " App chal rahi hai. Is terminal window ko OPEN rehne do."
echo " Band karne ke liye: yahin Ctrl+C dabao, ya terminal band karo."
echo "=========================================================="
echo

wait "$APP_PID"
