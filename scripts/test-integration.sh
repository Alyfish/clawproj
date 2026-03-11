#!/bin/bash
set -e

echo "=== ClawBot Integration Tests ==="

echo "Starting SearXNG container..."
docker compose up -d searxng

echo "Waiting for SearXNG healthcheck..."
for i in $(seq 1 30); do
  curl -sf http://localhost:8888/healthz > /dev/null 2>&1 && break || sleep 1
done

curl -sf http://localhost:8888/healthz > /dev/null || { echo "SearXNG failed to start"; exit 1; }

echo "SearXNG ready."
echo ""

echo "Running v2 integration tests..."
python3 -m pytest server/agent/tools/tests/test_integration_v2.py -v -m integration

echo ""
echo "Running context optimization tests..."
python3 -m pytest server/agent/tests/test_context_optimization.py -v -m integration

echo ""
echo "Running unit tests..."
python3 -m pytest server/agent/ -v \
  --ignore=server/agent/tools/tests/test_integration_v2.py \
  --ignore=server/agent/tests/test_context_optimization.py

echo ""
echo "All tests passed"
