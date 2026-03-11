.PHONY: setup up down logs logs-agent logs-gateway test status clean rebuild help

COMPOSE = docker compose

help: ## Show available commands
	@echo ""
	@echo "  ClawBot — make targets"
	@echo "  ─────────────────────────────────"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1;32m%-14s\033[0m %s\n", $$1, $$2}'
	@echo ""

setup: ## Interactive setup: prereqs, API key, build, start
	@bash scripts/setup.sh

up: ## Start all containers
	$(COMPOSE) up -d

down: ## Stop all containers
	$(COMPOSE) down

logs: ## Tail all container logs
	$(COMPOSE) logs -f

logs-agent: ## Tail agent logs only
	$(COMPOSE) logs -f agent

logs-gateway: ## Tail gateway logs only
	$(COMPOSE) logs -f gateway

test: ## Run all tests (Python + Node)
	@echo "=== Python Agent Tests ==="
	python3 -m pytest server/agent/tests/ -v
	@echo ""
	@echo "=== Gateway Tests ==="
	cd server/gateway && npx tsx --test src/__tests__/*.test.ts

status: ## Health check all services, show connection info
	@echo ""
	@echo "  ClawBot Service Status"
	@echo "  ─────────────────────────────────"
	@$(COMPOSE) ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || $(COMPOSE) ps
	@echo ""
	@echo "  Health Checks"
	@echo "  ─────────────────────────────────"
	@curl -sf http://localhost:$${GATEWAY_PORT:-8080}/health >/dev/null 2>&1 \
		&& echo "  Gateway:   \033[1;32mhealthy\033[0m" \
		|| echo "  Gateway:   \033[1;31mnot responding\033[0m"
	@curl -sf http://localhost:8888/healthz >/dev/null 2>&1 \
		&& echo "  SearXNG:   \033[1;32mhealthy\033[0m" \
		|| echo "  SearXNG:   \033[1;31mnot responding\033[0m"
	@curl -sf "http://localhost:3000/json/version?token=$${BROWSER_TOKEN:-clawbot-dev}" >/dev/null 2>&1 \
		&& echo "  Browser:   \033[1;32mhealthy\033[0m" \
		|| echo "  Browser:   \033[1;31mnot responding\033[0m"
	@echo ""
	@echo "  Connect iOS App"
	@echo "  ─────────────────────────────────"
	@echo "  WebSocket URL: ws://localhost:$${GATEWAY_PORT:-8080}"
	@echo ""

clean: ## Remove all containers and volumes
	$(COMPOSE) down -v --remove-orphans
	@echo ""
	@echo "  Containers and volumes removed."
	@echo "  Note: .env was NOT deleted. Run 'rm .env' manually if desired."
	@echo ""

rebuild: ## Force rebuild all containers
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d
