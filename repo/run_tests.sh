#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

if ! python3 -c "import pytest" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install -q -r requirements.txt
fi

echo "=== Unit Tests ===" && python3 -m pytest unit_tests/ -v --tb=short
echo "=== API Tests ===" && python3 -m pytest API_tests/ -v --tb=short
echo "=== Summary ===" && python3 -m pytest unit_tests/ API_tests/ --tb=no -q
