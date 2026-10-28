#!/bin/bash
# Local Files Tagger launcher for macOS. Double-click it (the first time: right-click > Open).
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
  echo "First run: setting up Local Files Tagger (takes a minute, only happens once)..."

  PY=""
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1; then
      PY="$c"
      break
    fi
  done
  if [ -z "$PY" ]; then
    echo
    echo "Python wasn't found. Install it from python.org (the macOS installer), then run this again."
    open "https://www.python.org/downloads/macos/"
    read -n 1 -s -r -p "Press any key to close."
    exit 1
  fi

  if ! "$PY" -m venv .venv; then
    echo "Couldn't create the Python environment."
    read -n 1 -s -r -p "Press any key to close."
    exit 1
  fi
  .venv/bin/python -m pip install --upgrade pip
  if ! .venv/bin/python -m pip install -r requirements.txt; then
    echo "Installing the tagging libraries failed. Check your internet and run this again."
    rm -rf .venv
    read -n 1 -s -r -p "Press any key to close."
    exit 1
  fi
  # the app window; if this fails the tagger opens in your browser instead
  .venv/bin/python -m pip install pywebview
  echo "Done."
fi

nohup .venv/bin/python app.py >/dev/null 2>&1 &
disown
echo "Local Files Tagger is opening. You can close this Terminal window."
