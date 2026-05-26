# Backend Reference

Auto-loaded when Claude reads files in `src/backend/`. Complements root `AGENTS.md`.
P0 rules (DDD, dual-DB, permissions, API conventions) live in `AGENTS.md`.

---

## Commands (cwd: `src/backend/`)

```bash
# Dependencies (uv, lockfile = uv.lock, Python must be 3.10.x)
uv sync --frozen --python uv run python

# Tests
uv run pytest test/                               # all
uv run pytest test/<module>/test_xxx.py::test_fn  # single test
uv run pytest test/ -k "keyword"                  # filter by keyword
uv run pytest test/ -m "not e2e"                  # exclude e2e
# New tests go under test/<module>/ (e.g. test/approval/), not test/ root
# asyncio_mode=auto — no @pytest.mark.asyncio needed on async functions

# Format / Lint (matches PostToolUse hook)
uv run ruff format <file_or_dir>
uv run ruff check --fix <file_or_dir>

# Start API (port 7860; config must be a filename relative to the bisheng package dir)
export config=config.yaml
uv run uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log

# Celery (one terminal per queue)
uv run celery -A bisheng.worker.main worker -l info -c 20  -P threads -Q knowledge_celery -n knowledge@%h
uv run celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery  -n workflow@%h
uv run celery -A bisheng.worker.main beat -l info

# Linsight Worker (optional)
uv run python bisheng/linsight/worker.py --worker_num 4 --max_concurrency 5

# DB migration (alembic.ini in src/backend/)
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "msg"   # autogen only reflects MySQL accurately; review DM8 compatibility manually
```

---

## Module Map

### DDD Domain Modules (own top-level dir + `api/` + `domain/`)

| Module | Path | Responsibility |
|--------|------|----------------|
| knowledge | `knowledge/` | Knowledge base management, RAG document pipeline |
| workflow | `workflow/` | Workflow DAG execution engine (LangGraph) |
| permission | `permission/` | ReBAC engine (OpenFGA integration, permission check, authorization, migration) |
| linsight | `linsight/` | Linsight autonomous agent framework, independent Worker |
| llm | `llm/` | LLM provider management, model registration |
| chat_session | `chat_session/` | Chat session management, message persistence |
| tool | `tool/` | Tool / plugin management |
| channel | `channel/` | Multi-channel communication, intelligence center |
| message | `message/` | Message inbox |
| user | `user/` | User management, auth (JWT), RBAC menu permissions |
| finetune | `finetune/` | Model fine-tuning pipeline |
| share_link | `share_link/` | Public share links |
| telemetry_search | `telemetry_search/` | Telemetry data retrieval |
| workstation | `workstation/` | Workstation backend |
| open_endpoints | `open_endpoints/` | v2 RPC interfaces for external system integration |
| mcp_manage | `mcp_manage/` | MCP protocol integration (SSE / STDIO / Streamable) |

**Non-standalone modules** (routes under `api/v1/`, no own top-level dir):
assistant, evaluation, audit, group, tag, mark, flows, skillcenter, variable, report, invite_code

### Infrastructure Modules

| Directory | Responsibility |
|-----------|----------------|
| `core/context/` | App lifecycle context management (`ApplicationContextManager`) |
| `core/config/settings.py` | Pydantic Settings config model |
| `core/database/` | SQLAlchemy engine factory (sync pymysql + async aiomysql) |
| `core/cache/` | Redis cache (RedisManager) |
| `core/ai/` | AI model service wrappers (llm, embeddings, asr, tts, rerank) |
| `core/storage/minio/` | MinIO S3 object storage |
| `core/search/elasticsearch/` | Elasticsearch (business instance + stats instance) |
| `core/vectorstore/` | Milvus vector store |
| `core/openfga/` | OpenFGA SDK wrapper (FGAClient singleton) |
| `common/errcode/` | Error code definitions (5-digit MMMEE) |
| `common/schemas/api.py` | Unified response model `UnifiedResponseModel` |
| `common/dependencies/` | FastAPI dependency injection (`UserPayload`) |
| `database/models/` | SQLModel ORM models; each file contains Schema + DAO |
| `worker/` | Celery async tasks |

---

## API Routes

**v1** (`/api/v1`, 29 routes, frontend-facing):
chat, knowledge, knowledge_space, qa, workflow, assistant, llm, user, group, tool, evaluation, finetune, server, linsight, session, channel, message, share_link, telemetry_search, flows, workstation, skillcenter, endpoints, variable, report, audit, tag, mark, invite_code

**v2 RPC** (`/api/v2`, 6 routes, external integration):
knowledge_rpc, filelib_rpc, chat_rpc, assistant_rpc, workflow_rpc, llm_rpc
(implemented in `open_endpoints/api/`)

---

## Core Data Models (`database/models/`)

| Model | Notes |
|-------|-------|
| Flow | Unified app definition. FlowType: ASSISTANT=5, WORKFLOW=10, WORKSTATION=15, LINSIGHT=20, CHANNEL_ARTICLE=25, KNOWLEDGE_SPACE=30 |
| FlowVersion | Version control; `is_current` marks the active version |
| Assistant / AssistantLink | Assistant config + join table (tools / skills / knowledge bases) |
| ChatMessage | Chat messages; fields: liked, solved, sensitive_status |
| MessageSession | Session records linking app and user |
| Role / RoleAccess | Role definition + permission mapping (AdminRole=1, DefaultRole=2) |
| Tenant / UserTenant | Tenant master table + user-tenant many-to-many |
| Department / UserDepartment | Department tree (materialized path) + user-department join |

**6 storage engines**: MySQL (relational), Redis (cache/broker/state), Milvus (dense vectors), Elasticsearch (sparse index + telemetry stats, dual instances), MinIO (file objects), OpenFGA (relational permissions)

---

## App Entry Points

- **`main.py`** — FastAPI app creation, lifespan management
- **`api/router.py`** — Global route registration
- **`config.yaml`** — Main config file (local dev)

Infrastructure init order (`core/context/manager.py`):
```
DatabaseManager → RedisManager → MinioManager → EsConnManager(business)
→ EsConnManager(stats) → HttpClientManager → PromptManager → FGAClient(OpenFGA)
```

Middleware stack (inbound order): `CORSMiddleware` → `CustomMiddleware` (request log + X-Trace-ID) → `WebSocketLoggingMiddleware`

---

## Workflow Engine (`workflow/`)

LangGraph-based DAG execution engine.

| File | Role |
|------|------|
| `graph/graph_engine.py` | GraphEngine — compiles workflow JSON into LangGraph state machine |
| `graph/graph_state.py` | GraphState variable pool for inter-node data passing |
| `graph/workflow.py` | Workflow wrapper managing timeout and conversation history |
| `nodes/node_manage.py` | NodeFactory + NODE_CLASS_MAP registry |
| `callback/` | Callback system (on_node_start, on_stream_msg, on_output_msg, …) |

**14 node types** (each in its own `workflow/nodes/<type>/`):
START, END, INPUT, OUTPUT, FAKE_OUTPUT, LLM, CODE, CONDITION, KNOWLEDGE_RETRIEVER, QA_RETRIEVER, RAG, TOOL, AGENT, REPORT

**Add a new node type** (3 steps):
1. Add `NodeType` enum entry in `workflow/common/node.py`
2. Create node class under `workflow/nodes/<name>/`, inherit `BaseNode`, implement `_run()`
3. Register in `workflow/nodes/node_manage.py` → `NODE_CLASS_MAP`

**Interrupt / resume**: INPUT node and OUTPUT (via FakeNode) trigger LangGraph `interrupt_before`. State stored in Redis; Celery task resumes execution.

**Variable reference format**: `{node_id}.{variable_key}` or `{node_id}.{variable_key}#{index}`

**Config**: WorkflowConf (max_steps=50, timeout=720 min)

**Celery tasks**: `execute_workflow` / `continue_workflow` / `stop_workflow` in `worker/workflow/tasks.py`

---

## Knowledge / RAG Pipeline (`knowledge/`)

Three-phase pipeline: **Load → Transform → Ingest**

- **Load**: file-type-specific loaders (PDF / DOCX / TXT / HTML / Excel / images); PDF supports 4 engines (ETL4LM / MineRU / PaddleOCR / local)
- **Transform**: summary extraction → attachment/image handling → thumbnail generation → text chunking (ElemCharacterTextSplitter, default chunk_size=1000) → preview cache
- **Ingest**: simultaneous write to Milvus (dense vectors, semantic search) + Elasticsearch (sparse BM25 index)

**File processing states**: WAITING(5) → PROCESSING(1) → SUCCESS(2) / FAILED(3) / TIMEOUT(6)

**Async processing**: all file processing via Celery `knowledge_celery` queue

**Core classes**: `knowledge/rag/pipeline/base.py` (NormalPipeline), `knowledge/rag/knowledge_file_pipeline.py` (KnowledgeFilePipeline)

---

## Linsight Agent Framework (`linsight/`)

Independent Worker process, decoupled from API via Redis queue.

**Flow**: user submits → SOP generation → task decomposition → Agent executes step-by-step (tool calls, user interaction, sub-task generation)

**Events**: TaskStart, TaskEnd, ExecStep, NeedUserInput, GenerateSubTask

**State persistence**: Redis cache + MySQL dual-write; Redis key TTL 1 hour

**Worker model**: multiple `ScheduleCenterProcess` (multiprocessing), each with `asyncio.Semaphore` concurrency control

**Key files**:
- `linsight/worker.py` — Worker entry point
- `linsight/domain/task_exec.py` — `LinsightWorkflowTask` executor
- `src/backend/bisheng_langchain/linsight/` — LinsightAgent, TaskManage, Task/ReactTask runtime

---

## Celery Workers (`worker/`)

| Queue | Concurrency | Responsibility |
|-------|-------------|----------------|
| `knowledge_celery` | 20 threads | Document parsing, embedding, vector writes |
| `workflow_celery` | 100 threads | Workflow DAG execution |
| `celery` (default) | 100 threads | Telemetry stats |

Beat tasks: telemetry sync at 00:30, intelligence center articles at 05:30 daily.
Worker heartbeat: writes to Redis (`celery_worker_alive_queues`) every 5 seconds.
Multi-tenant: Beat iterates all active tenants per task — adding a task multiplies by N tenants.

---

## Configuration Reference (`config.yaml`)

Load priority: `YAML file → env vars (BS_*) → DB config (initdb_config) → Redis cache (100s TTL)`

Supports `!env ${VAR}` syntax for env var injection.

Key config groups:

| Group | Notes |
|-------|-------|
| `database_url` | MySQL connection. Password is Fernet-encrypted (key in `core/config/settings.py` `secret_key`) |
| `redis_url` / `celery_redis_url` | Redis connections |
| `vector_stores.milvus` | Milvus connection |
| `vector_stores.elasticsearch` | ES connection (business + stats instances) |
| `object_storage.minio` | MinIO. `sharepoint` must match Vite `fileServiceTarget` exactly |
| `openfga` | OpenFGA: api_url, store_id, model_id |
| `multi_tenant` | enabled (default false), default_tenant_code, storage_isolation |
| `workflow_conf` | max_steps=50, timeout=720 min |
| `linsight_conf` | max_steps=200, retry_num=3 |
| `cookie_conf` | JWT cookie expiry (default 86400s) |
