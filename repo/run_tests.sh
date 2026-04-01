#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
elif [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
fi

PYTHON="${PYTHON:-python3}"
echo "=== Unit Tests ===" && $PYTHON -m pytest unit_tests/ -v --tb=short
echo "=== API Tests ===" && $PYTHON -m pytest API_tests/ -v --tb=short
echo "=== Summary ===" && $PYTHON -m pytest unit_tests/ API_tests/ --tb=no -q
