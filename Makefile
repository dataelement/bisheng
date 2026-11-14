# =============================================================================
# BiSheng (毕昇) — local development helpers
#
# One-command start of the whole local stack (middleware + backend + Celery +
# both SPAs), plus foreground targets when you want a single process in a
# terminal with live logs.
#
#   make up          # infra + backend + celery(knowledge/workflow/beat) + SPAs
#   make status      # what is listening / healthy
#   make down        # stop the app processes (infra keeps running)
#   make infra-down  # stop middleware containers too
#
# Background processes write logs to logs/dev/<name>.log and pid files to
# logs/dev/<name>.pid (both git-ignored).
# =============================================================================

SHELL := /bin/bash
ROOT  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

# --- paths -------------------------------------------------------------------
BACKEND_DIR  := $(ROOT)/src/backend
PLATFORM_DIR := $(ROOT)/src/frontend/platform
CLIENT_DIR   := $(ROOT)/src/frontend/client
DOCKER_DIR   := $(ROOT)/docker
RUN_DIR      := $(ROOT)/logs/dev

# --- native-dev process environment ------------------------------------------
# docker/.env.app holds per-developer secrets (e.g. PADDLE_OCR_TOKEN) that the
# backend processes read straight from the environment. It is sourced rather
# than merged into docker/.env on purpose: that file is compose's deployment
# env and carries keys the app itself honours (BISHENG_PRO,
# BISHENG_RUNTIME_CONTROL_SECRET, ...), so feeding it to a dev process would
# silently change platform behaviour. Missing file is fine — `set -a` over an
# empty source is a no-op.
APP_ENV      := $(DOCKER_DIR)/.env.app
APP_ENV_SRC  := set -a; . $(APP_ENV) 2>/dev/null || true; set +a;

# --- middleware (docker compose) ---------------------------------------------
# docker/.env holds the CR image tags + credentials and is picked up
# automatically (project directory = directory of the first -f file).
# The local-arm64 override swaps in Apple Silicon builds of every component.
COMPOSE := docker compose --env-file $(DOCKER_DIR)/.env --env-file $(DOCKER_DIR)/.env.local \
           -f $(DOCKER_DIR)/docker-compose.yml -f $(DOCKER_DIR)/docker-compose.local-arm64.yml

INFRA_CORE := mysql redis minio openfga          # backend cannot start without these
INFRA_RAG  := etcd milvus elasticsearch          # knowledge base / RAG only

# --- app commands (run with cwd = their own project dir) ---------------------
# Backend `.venv/bin` is used directly: it is the interpreter this workspace
# was synced into, and `uv run` would re-resolve/sync before every start.
UVICORN := .venv/bin/uvicorn
CELERY  := .venv/bin/celery
PYTHON  := .venv/bin/python

BACKEND_CMD   := env config=config.yaml $(UVICORN) bisheng.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log
KNOWLEDGE_CMD := env config=config.yaml $(CELERY) -A bisheng.worker.main worker -l info -c 20 -P threads -Q knowledge_celery -n knowledge@%h
WORKFLOW_CMD  := env config=config.yaml $(CELERY) -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery -n workflow@%h
BEAT_CMD      := env config=config.yaml $(CELERY) -A bisheng.worker.main beat -l info -s $(RUN_DIR)/celerybeat-schedule
# Default `celery` queue (telemetry, misc) and the optional Linsight worker are
# not part of `up` — start them on demand with the targets below.
DEFAULTQ_CMD  := env config=config.yaml $(CELERY) -A bisheng.worker.main worker -l info -c 100 -P threads -Q celery -n celery@%h
LINSIGHT_CMD  := env config=config.yaml $(PYTHON) bisheng/linsight/worker.py --worker_num 4 --max_concurrency 5
PLATFORM_CMD  := pnpm dev -- --host 0.0.0.0
CLIENT_CMD    := pnpm dev -- --host 0.0.0.0

# Extra args for `make wecom-sync*` (e.g. WECOM_SYNC_ARGS="--batch-size 500 --incremental")
WECOM_SYNC_ARGS ?=

# --- background spawn helper -------------------------------------------------
# $(call spawn,<name>,<dir>,<command>,<port>)
#   - skips (and adopts) a process that already listens on <port>
#   - otherwise starts it detached, logging to logs/dev/<name>.log
# Backend-directory processes get $(APP_ENV_SRC) prepended (see above); the SPAs
# do not need it and are left with the caller's environment untouched.
APP_ENV_FOR = $(if $(filter $(BACKEND_DIR),$(2)),$(APP_ENV_SRC),)
define spawn
	@mkdir -p $(RUN_DIR)
	@if [ -f $(RUN_DIR)/$(1).pid ] && kill -0 $$(cat $(RUN_DIR)/$(1).pid) 2>/dev/null; then \
		echo "  $(1): already running (pid $$(cat $(RUN_DIR)/$(1).pid))"; \
	elif [ -n "$(4)" ] && lsof -nP -iTCP:$(4) -sTCP:LISTEN >/dev/null 2>&1; then \
		lsof -nP -iTCP:$(4) -sTCP:LISTEN -t | head -1 > $(RUN_DIR)/$(1).pid; \
		echo "  $(1): port $(4) already in use — adopted pid $$(cat $(RUN_DIR)/$(1).pid) (make down will stop it)"; \
	else \
		$(call APP_ENV_FOR,$(1),$(2))( cd $(2) && exec nohup $(3) >>$(RUN_DIR)/$(1).log 2>&1 ) & \
		echo $$! > $(RUN_DIR)/$(1).pid; \
		echo "  $(1): started (pid $$(cat $(RUN_DIR)/$(1).pid)) → logs/dev/$(1).log"; \
	fi
endef

.PHONY: help up up-backend up-frontend down restart \
        infra-up infra-up-rag infra-down infra-status infra-logs infra-pull \
        backend worker-knowledge worker-workflow worker-beat worker-default worker-linsight \
        platform client frontend wecom-sync wecom-sync-apply \
        status wait logs clean-logs

# =============================================================================
# meta
# =============================================================================
help: ## Show available targets
	@echo "BiSheng local dev"
	@echo
	@echo "  make up              start middleware + backend + celery(knowledge/workflow/beat) + platform + client"
	@echo "  make up-backend      start backend + celery only"
	@echo "  make up-frontend     start platform (3001) + client (4001) only"
	@echo "  make down            stop all processes started by make"
	@echo "  make restart         down + up"
	@echo "  make status          pids, listening ports, /health, celery ping, infra ps"
	@echo "  make wait            block until backend /health and 2 celery workers are ready"
	@echo "  make logs            tail -f every process log (Ctrl-C to stop tailing)"
	@echo
	@echo "  infra:   make infra-up / infra-up-rag / infra-down / infra-status / infra-logs / infra-pull"
	@echo "  wecom:   make wecom-sync (dry-run) / wecom-sync-apply (push WeCom org chart)"
	@echo "  single foreground process (logs in terminal):"
	@echo "           make backend | worker-knowledge | worker-workflow | worker-beat"
	@echo "           make worker-linsight (optional) — worker-default now starts with 'up'"
	@echo "           make platform | client | frontend"
	@echo
	@echo "  logs:    logs/dev/<name>.log      pids: logs/dev/<name>.pid"

# =============================================================================
# aggregate
# =============================================================================
up: infra-up up-backend up-frontend ## Start everything in the background
	@echo
	@echo "all processes launched — run 'make status' or 'make logs'"

up-backend: ## Backend API + Celery workers + beat
	$(call spawn,backend,$(BACKEND_DIR),$(BACKEND_CMD),7860)
	$(call spawn,worker-knowledge,$(BACKEND_DIR),$(KNOWLEDGE_CMD),)
	$(call spawn,worker-workflow,$(BACKEND_DIR),$(WORKFLOW_CMD),)
	$(call spawn,worker-beat,$(BACKEND_DIR),$(BEAT_CMD),)
	# Default `celery` queue: telemetry + misc tasks, and the admin console's
	# manual org sync (系统管理 → 组织同步 → 立即同步).
	$(call spawn,worker-default,$(BACKEND_DIR),$(DEFAULTQ_CMD),)

up-frontend: ## platform (3001) + client (4001)
	$(call spawn,platform,$(PLATFORM_DIR),$(PLATFORM_CMD),3001)
	$(call spawn,client,$(CLIENT_DIR),$(CLIENT_CMD),4001)

down: ## Stop backend/worker/frontend processes started by make
	@for pidfile in $(RUN_DIR)/*.pid; do \
		[ -e "$$pidfile" ] || continue; \
		name=$$(basename "$$pidfile" .pid); \
		pid=$$(cat "$$pidfile"); \
		if kill -0 "$$pid" 2>/dev/null; then \
			kill "$$pid" 2>/dev/null && echo "  $$name: stopped (pid $$pid)"; \
		else \
			echo "  $$name: not running"; \
		fi; \
		rm -f "$$pidfile"; \
	done
	@echo "waiting for graceful shutdown..."
	@sleep 3

restart: down up ## Restart every app process

# =============================================================================
# middleware
# =============================================================================
infra-up: ## Start core middleware (mysql, redis, minio, openfga) with arm64 images
	@test -f $(DOCKER_DIR)/.env || { echo "missing $(DOCKER_DIR)/.env — copy .env.example and fill it in"; exit 1; }
	@$(COMPOSE) up -d $(INFRA_CORE)
	@$(COMPOSE) ps $(INFRA_CORE)

infra-up-rag: infra-up ## Also start etcd + milvus + elasticsearch (knowledge / RAG)
	@$(COMPOSE) up -d $(INFRA_RAG)
	@$(COMPOSE) ps $(INFRA_RAG)

infra-down: ## Stop and remove the middleware containers
	@$(COMPOSE) down
	@echo "note: data volumes under docker/ are kept"

infra-status: ## Show middleware container status
	@$(COMPOSE) ps

infra-logs: ## Tail middleware logs (SVC=mysql|redis|... to narrow)
	@$(COMPOSE) logs -f --tail=100 $(SVC)

infra-pull: ## Pull the arm64 images (slow on a fresh machine)
	@$(COMPOSE) pull $(INFRA_CORE)

# =============================================================================
# single foreground processes (Ctrl-C to stop)
# =============================================================================
backend: ## Run API server in the foreground
	@$(APP_ENV_SRC) cd $(BACKEND_DIR) && exec $(BACKEND_CMD)

worker-knowledge: ## Run knowledge_celery worker in the foreground
	@$(APP_ENV_SRC) cd $(BACKEND_DIR) && exec $(KNOWLEDGE_CMD)

worker-workflow: ## Run workflow_celery worker in the foreground
	@$(APP_ENV_SRC) cd $(BACKEND_DIR) && exec $(WORKFLOW_CMD)

worker-beat: ## Run Celery beat in the foreground
	@mkdir -p $(RUN_DIR)
	@$(APP_ENV_SRC) cd $(BACKEND_DIR) && exec $(BEAT_CMD)

worker-default: ## Run the default `celery` queue worker (telemetry) in the background
	$(call spawn,worker-default,$(BACKEND_DIR),$(DEFAULTQ_CMD),)

worker-linsight: ## Run the optional Linsight agent worker in the background
	$(call spawn,worker-linsight,$(BACKEND_DIR),$(LINSIGHT_CMD),)

platform: ## Run platform SPA (3001) in the foreground
	@cd $(PLATFORM_DIR) && exec $(PLATFORM_CMD)

client: ## Run client SPA (4001) in the foreground
	@cd $(CLIENT_DIR) && exec $(CLIENT_CMD)

frontend: ## Run both SPAs in the background
	@$(MAKE) --no-print-directory up-frontend

# =============================================================================
# WeCom org sync (no Gateway) — see sso_sync.md / src/backend/scripts/wecom_org_sync.py
# =============================================================================
wecom-sync: ## Fetch the WeCom org chart and report (dry-run, no writes)
	@cd $(BACKEND_DIR) && env config=config.yaml $(PYTHON) scripts/wecom_org_sync.py $(WECOM_SYNC_ARGS)

wecom-sync-apply: ## Push the WeCom org chart (archives absent depts, disables absent users)
	@cd $(BACKEND_DIR) && env config=config.yaml $(PYTHON) scripts/wecom_org_sync.py --apply $(WECOM_SYNC_ARGS)

# =============================================================================
# observability
# =============================================================================
status: ## Show pids, ports, health and infra status
	@echo "== processes =="
	@found=0; for pidfile in $(RUN_DIR)/*.pid; do \
		[ -e "$$pidfile" ] || continue; \
		found=1; \
		name=$$(basename "$$pidfile" .pid); \
		pid=$$(cat "$$pidfile"); \
		if kill -0 "$$pid" 2>/dev/null; then echo "  $$name: running (pid $$pid)"; else echo "  $$name: DEAD (stale pid file)"; fi; \
	done; [ $$found = 1 ] || echo "  (none started by make)"
	@echo "== ports =="
	@lsof -nP -iTCP:7860 -iTCP:3001 -iTCP:4001 -sTCP:LISTEN 2>/dev/null | awk 'NR>1{printf "  %-10s pid %-7s %s\n", $$1, $$2, $$9}' || true
	@echo "== http =="
	@printf "  backend  /health : "; curl -s -m 3 -w " (%{http_code})\n" http://127.0.0.1:7860/health || echo "down"
	@printf "  platform :3001   : "; curl -s -o /dev/null -m 3 -w "%{http_code}\n" http://127.0.0.1:3001/ || echo "down"
	@printf "  client   :4001   : "; curl -s -o /dev/null -m 3 -w "%{http_code}\n" http://127.0.0.1:4001/workspace/ || echo "down"
	@echo "== celery =="
	@cd $(BACKEND_DIR) && env config=config.yaml $(CELERY) -A bisheng.worker.main inspect ping 2>/dev/null | grep -E "OK$$|online" | sed 's/^/  /' || echo "  (no workers responding)"
	@echo "== middleware =="
	@$(COMPOSE) ps --format 'table {{.Service}}\t{{.Status}}' 2>/dev/null | sed 's/^/  /'

wait: ## Block until backend /health and both celery workers answer
	@printf "waiting for backend /health "
	@ok=0; for i in $$(seq 1 90); do code=$$(curl -s -m 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:7860/health); \
		if [ "$$code" = "200" ]; then ok=1; break; fi; sleep 1; done; \
	[ $$ok = 1 ] && echo "✓" || { echo "✗ (see logs/dev/backend.log)"; exit 1; }
	@printf "waiting for celery workers "
	@ok=0; for i in $$(seq 1 60); do \
		out=$$( cd $(BACKEND_DIR) && env config=config.yaml $(CELERY) -A bisheng.worker.main inspect ping 2>/dev/null ); \
		echo "$$out" | grep -q "2 nodes" && { ok=1; break; }; sleep 2; done; \
	[ $$ok = 1 ] && echo "✓ (2 nodes online)" || { echo "✗ (see logs/dev/worker-*.log)"; exit 1; }
	@printf "waiting for SPAs "
	@ok=0; for i in $$(seq 1 60); do \
		p=$$(curl -s -o /dev/null -m 2 -w '%{http_code}' http://127.0.0.1:3001/); \
		c=$$(curl -s -o /dev/null -m 2 -w '%{http_code}' http://127.0.0.1:4001/workspace/); \
		[ "$$p" = "200" ] && [ "$$c" = "200" ] && { ok=1; break; }; sleep 1; done; \
	[ $$ok = 1 ] && echo "✓ (3001 + 4001)" || echo "· not up (only needed for `make frontend`)"

logs: ## Tail all process logs
	@mkdir -p $(RUN_DIR); \
	files=$$(ls $(RUN_DIR)/*.log 2>/dev/null); \
	if [ -z "$$files" ]; then echo "no logs yet — run 'make up' first"; else tail -n 50 -f $$files; fi

clean-logs: ## Remove logs/dev
	@rm -rf $(RUN_DIR)
	@echo "removed logs/dev"
