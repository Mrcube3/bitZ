#!/bin/bash
set -e
echo ""
echo "====================================="
echo "      RETAIL AUTOPSY ENGINE"
echo "      Starting up..."
echo "====================================="
echo ""

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
  echo "Add your Bitget API keys to .env before using trade features"
fi

mkdir -p data

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

cd backend
echo "Installing dependencies..."
../.venv/bin/pip install -r requirements.txt -q

echo "Starting server on http://127.0.0.1:8000"
echo ""
../.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
