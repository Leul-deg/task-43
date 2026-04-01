#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
elif [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

echo "=== Unit Tests ===" && python -m pytest unit_tests/ -v --tb=short
echo "=== API Tests ===" && python -m pytest API_tests/ -v --tb=short
echo "=== Summary ===" && python -m pytest unit_tests/ API_tests/ --tb=no -q
