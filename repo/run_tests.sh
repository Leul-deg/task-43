#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE="sports-hub-test"

echo "Building test image..."
docker build -t "$IMAGE" "$SCRIPT_DIR"

TEST_ENV=(
  -e SECRET_KEY=test-secret-key-for-testing
  -e JWT_SECRET_KEY=test-jwt-secret-for-testing
  -e HMAC_SECRET=test-hmac-secret
  -e ADMIN_PASSWORD=SecureTestPass123!
)

echo "=== Unit Tests ==="
docker run --rm "${TEST_ENV[@]}" "$IMAGE" \
  python -m pytest unit_tests/ -v --tb=short

echo "=== API Tests ==="
docker run --rm "${TEST_ENV[@]}" "$IMAGE" \
  python -m pytest API_tests/ -v --tb=short

echo "=== Summary ==="
docker run --rm "${TEST_ENV[@]}" "$IMAGE" \
  python -m pytest unit_tests/ API_tests/ --tb=no -q
