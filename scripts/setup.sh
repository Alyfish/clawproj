#!/usr/bin/env bash
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
DIM='\033[2m'
NC='\033[0m'

# ── Resolve project root (where this script lives → ../.) ────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Banner ────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  ClawBot Setup${NC}"
echo -e "  ─────────────────────────────────"
echo ""

# ── Step 1: Check prerequisites ──────────────────────────────
echo -e "${BOLD}  Checking prerequisites...${NC}"
echo ""
MISSING=0

# Docker
if command -v docker &>/dev/null; then
  echo -e "  ${GREEN}ok${NC}  Docker"
else
  echo -e "  ${RED}--${NC}  Docker — install from https://docker.com"
  MISSING=1
fi

# Docker Compose v2
if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
  echo -e "  ${GREEN}ok${NC}  Docker Compose v2"
else
  echo -e "  ${RED}--${NC}  Docker Compose v2 — update Docker Desktop"
  MISSING=1
fi

# Docker daemon running
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
  echo -e "  ${GREEN}ok${NC}  Docker daemon running"
else
  echo -e "  ${RED}--${NC}  Docker daemon not running — start Docker Desktop"
  MISSING=1
fi

if [ "$MISSING" -eq 1 ]; then
  echo ""
  echo -e "  ${RED}Fix the above issues and re-run 'make setup'.${NC}"
  echo ""
  exit 1
fi

echo ""

# ── Step 2: API key configuration ────────────────────────────
echo -e "${BOLD}  API Key Configuration${NC}"
echo ""

SKIP_ENV=0
if [ -f .env ] && grep -q "^ANTHROPIC_API_KEY=sk-ant-" .env; then
  EXISTING_KEY=$(grep "^ANTHROPIC_API_KEY=" .env | cut -d= -f2 | head -c 20)
  echo -e "  Found existing key: ${DIM}${EXISTING_KEY}...${NC}"
  read -rp "  Keep existing .env? [Y/n] " KEEP_ENV
  if [[ "${KEEP_ENV:-Y}" =~ ^[Yy]?$ ]]; then
    echo -e "  ${GREEN}ok${NC}  Keeping existing .env"
    SKIP_ENV=1
  fi
fi

if [ "$SKIP_ENV" -eq 0 ]; then
  echo -e "  Get your key at: ${DIM}https://console.anthropic.com/settings/keys${NC}"
  echo ""
  while true; do
    read -rp "  ANTHROPIC_API_KEY: " API_KEY
    if [[ "$API_KEY" == sk-ant-* ]]; then
      break
    else
      echo -e "  ${RED}Key must start with 'sk-ant-'. Try again.${NC}"
    fi
  done

  # Generate .env from template
  cp .env.example .env
  if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${API_KEY}|" .env
  else
    sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${API_KEY}|" .env
  fi
  echo -e "  ${GREEN}ok${NC}  .env created"
fi

echo ""

# ── Step 3: Build containers ─────────────────────────────────
echo -e "${BOLD}  Building containers...${NC}"
echo -e "  ${DIM}This takes 1-3 minutes on first run.${NC}"
echo ""

docker compose build

echo ""

# ── Step 4: Start services ───────────────────────────────────
echo -e "${BOLD}  Starting services...${NC}"
echo ""

docker compose up -d

echo ""

# ── Step 5: Wait for health checks ───────────────────────────
echo -e "${BOLD}  Waiting for services to be healthy...${NC}"

GATEWAY_PORT="${GATEWAY_PORT:-8080}"
BROWSER_TOKEN="${BROWSER_TOKEN:-clawbot-dev}"
TIMEOUT=90
ELAPSED=0
INTERVAL=3

while [ $ELAPSED -lt $TIMEOUT ]; do
  GW_OK=0; SX_OK=0; BR_OK=0

  curl -sf "http://localhost:${GATEWAY_PORT}/health" >/dev/null 2>&1 && GW_OK=1
  curl -sf "http://localhost:8888/healthz" >/dev/null 2>&1 && SX_OK=1
  curl -sf "http://localhost:3000/json/version?token=${BROWSER_TOKEN}" >/dev/null 2>&1 && BR_OK=1

  if [ $GW_OK -eq 1 ] && [ $SX_OK -eq 1 ] && [ $BR_OK -eq 1 ]; then
    break
  fi

  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
  echo -n "."
done

echo ""
echo ""

if [ $GW_OK -eq 1 ] && [ $SX_OK -eq 1 ] && [ $BR_OK -eq 1 ]; then
  echo -e "${GREEN}${BOLD}  ClawBot is running!${NC}"
  echo -e "  ─────────────────────────────────"
  echo ""
  echo "  Gateway:     ws://localhost:${GATEWAY_PORT}"
  echo "  Health:      http://localhost:${GATEWAY_PORT}/health"
  echo "  SearXNG:     http://localhost:8888"
  echo "  Browser:     ws://localhost:3000"
  echo ""
  echo "  Next steps:"
  echo "    1. Open ios/ClawBot in Xcode and build to your device"
  echo "    2. The app connects to ws://localhost:${GATEWAY_PORT}"
  echo "    3. Run 'make logs' to see container output"
  echo "    4. Run 'make status' to check service health"
  echo ""
else
  echo -e "  ${RED}Some services failed to start within ${TIMEOUT}s.${NC}"
  echo ""
  [ $GW_OK -eq 0 ] && echo -e "  ${RED}--${NC}  Gateway not responding"
  [ $SX_OK -eq 0 ] && echo -e "  ${RED}--${NC}  SearXNG not responding"
  [ $BR_OK -eq 0 ] && echo -e "  ${RED}--${NC}  Browser not responding"
  echo ""
  echo "  Debug with: docker compose ps"
  echo "              docker compose logs"
  echo ""
  exit 1
fi
