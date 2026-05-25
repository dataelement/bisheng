# AGENTS.md

Guidance for AI agents and Claude Code. Loaded every session — only P0 rules live here.
Deeper backend reference (module map, subsystems): `src/backend/AGENTS.md` (auto-loaded when editing backend files).

---

## 1. Project Identity

**BiSheng (毕昇)** — Enterprise LLM application DevOps platform. Monorepo, three sub-projects:

| Path | Project | Stack |
|------|---------|-------|
| `src/backend/` | FastAPI + Celery Workers + Linsight Worker | Python 3.10+, uv, SQLModel, LangGraph |
| `src/frontend/platform/` | Admin / builder UI | Vite 5 + **Zustand** + react-query v3 + bs-ui |
| `src/frontend/client/` | End-user chat UI (`/workspace` base path) | Vite 6 + **Recoil** + react-query v5 + shadcn/ui |

---

## 2. Commands

Backend commands (test, lint, start, Celery, Alembic) → `src/backend/CLAUDE.md`.

```bash
# Frontend
cd src/frontend/platform && npm install && npm start -- --host 0.0.0.0   # :3001
cd src/frontend/client  && npm install && npm run dev                     # :4001
# Commercial Gateway proxy mode:
VITE_PROXY_TARGET=http://localhost:8180 npm start -- --host 0.0.0.0

# Middleware (Docker only)
bash docker/local-dev/start-middleware.sh   # MySQL / Redis / Milvus / ES / MinIO / OpenFGA
```

---

## 3. Backend Rules (P0)

### 3.1 Layered Architecture (DDD)

Call chain — never skip layers:
```
Router → Endpoint → Service → Repository → DB
```

- **Never** `import bisheng.database.models.*` in endpoints (arch-guard RULE-3 WARNING).
- **Never** write ORM queries in Service; **never** add new DAO entry points for new features.
- New module layout: `<module>/{api/router.py, api/endpoints/, domain/services/, domain/models/, domain/schemas/, domain/repositories/}`
- Register the router in `bisheng/api/router.py`.

### 3.2 Dual-DB Compatibility (MySQL + DM8) ⚠️

Every new feature must work on both dialects. DM8 is not optional.

| ✅ Use | ❌ Never use |
|--------|-------------|
| `dialect_helpers.JsonType` | `sqlalchemy.JSON`, `mysql.JSON` |
| `dialect_helpers.LargeText` | `LONGTEXT`, `MEDIUMTEXT` |
| `dialect_helpers.UPDATE_TIME_SERVER_DEFAULT` | `ON UPDATE CURRENT_TIMESTAMP` |
| `SQLAlchemy inspect()` | `information_schema`, `DATABASE()` |
| Explicit relational columns | `JSON_EXTRACT` / `JSON_CONTAINS` / `JSON_SEARCH` |

macOS: DM8 driver (`dmPython`/`dmAsync`) is not installed (`sys_platform != 'darwin'`). Real DM8 validation runs on CI/Linux only.

### 3.3 Multi-Tenancy — Auto-Injected, Never Manual

**Never write `WHERE tenant_id = X` manually.** SQLAlchemy events handle it automatically for 23+ tables.
`multi_tenant.enabled=false` behaves identically to single-tenant (default `tenant_id=1`).

### 3.4 Permissions — Unified Entry Point

```python
from bisheng.permission.domain.services.permission_service import PermissionService
await PermissionService.check(...)      # check access
await PermissionService.authorize(...)  # write OpenFGA owner tuple on resource creation (required)
```

**Never** query `role_access` directly for resource authorization (arch-guard RULE-8 VIOLATION).
Resource creation **must** call `PermissionService.authorize()`; failures go to the `failed_tuples` retry table.

Five-level short-circuit: `super_admin` → tenant mismatch deny → tenant admin → ReBAC (OpenFGA) → RBAC menu.

### 3.5 API Conventions

```python
from bisheng.common.dependencies.user_deps import UserPayload
user: UserPayload = Depends(UserPayload.get_login_user)   # WebSocket: get_login_user_from_ws

from bisheng.common.schemas.api import resp_200, resp_500
return resp_200(data)        # success
return resp_500(code, msg)   # business error
```

Error codes: 5-digit `MMMEE` (3-digit module + 2-digit error), defined in `common/errcode/`.
Module numbers: 100=server, 104=assistant, 105=flow, 106=user, 108=llm, 109=knowledge, 110=linsight, 120=workstation, 130=chat, 140=message, 150=tool, 180=knowledge_space.

Pagination: `PageData[T]` (new code) with fields `data` + `total`; `PageList[T]` is legacy-compat only.

---

## 4. Frontend Rules (P0)

The two React apps **must not be mixed**. Apply rules by directory:

| Dimension | Platform (`src/frontend/platform/`) | Client (`src/frontend/client/`) |
|-----------|-------------------------------------|--------------------------------|
| State | **Zustand** (`@/store/`) + Context for local UI | **Recoil** (`~/store/`) |
| Server state | react-query **v3** (`useQuery({ queryFn })`) | react-query **v5** |
| Path alias | `@/` → `src/` | `~/` (or `@/`) → `src/` |
| HTTP layer | `@/controllers/request.ts` | `~/api/request.ts` |
| UI library | `@/components/bs-ui/` (Radix-based) | `~/components/ui/` (shadcn) |
| Icons | `@/components/bs-icons/` | `lucide-react` |
| i18n hook | `useTranslation()` → `t()` | `useLocalize()` → `localize()` |
| i18n files | `public/locales/{lang}/{ns}.json` (multi-namespace) | `src/locales/{lang}/translation.json` (single file) |
| Toast | `toast({ title, variant: 'error'\|'success', description })` | `showToast({ message, severity: 'error'\|'success' })` |
| Confirm dialog | `bsConfirm(...)` (bs-ui) | — |
| Workflow editor | `@xyflow/react` (**not** `react-flow-renderer`), nodes in `src/CustomNodes/` | — |

**Hard rules (both apps):**
- TypeScript only (`.ts` / `.tsx`); functional components only; no class components.
- Single file ≤ 600 lines. Extract sub-components or hooks when exceeded.
- `interface` for Props; `type` for internal types.
- `handleXxx` for internal handlers; `onXxx` for props.
- **Never** `import axios` directly — always use the wrapped request module above.
- **Never** introduce new UI libraries or state management libraries.
- All code comments in English.
- 403: handled automatically by response interceptors. Never add 403 branches in business code.

---

## 5. Architecture Guard (Auto-enforced)

`scripts/arch-guard.sh` runs after every Write/Edit via PostToolUse hook:

| # | Rule | Severity |
|---|------|----------|
| 1 | `common/`, `core/` must not import `domain/`, `api/` | VIOLATION |
| 2 | `database/models/` must not import `domain/` | VIOLATION |
| 3 | Endpoints must not directly import `database/models/` | WARNING (migration period) |
| 4 | `domain/models/` must not import `domain/services/` | VIOLATION |
| 5 | API layer must not cross-import between modules | VIOLATION |
| 6 | Frontend store must not call HTTP directly (use `controllers/API/` or `api/`) | WARNING |
| 7 | No hardcoded secrets (password/secret/token literals) | WARNING |
| 8 | DAO/Model must not read `RoleAccessDao` for permission filtering | VIOLATION |

**VIOLATION rules must be fixed immediately** — these are v2.5 refactor boundaries.

---

## 6. SDD Workflow (Required for non-trivial features)

```
0. release-contract.md (once per version)
1. Spec Discovery  →  ★ user confirms
2. spec.md  →  /sdd-review <dir> spec  →  ★ user confirms
3. tasks.md  →  /sdd-review <dir> tasks
4. branch: feat/<version>/{NNN}-{name}
5. implement task-by-task  →  /task-review <dir> <id>  →  check off
6. /e2e-test <dir>  (mandatory)
7. /code-review --base <main branch>
8. merge
```

Artifacts: `features/v{X.Y.Z}/{NNN}-{name}/spec.md` and `tasks.md`. Templates: `features/_templates/`.
**★ pause points cannot be skipped.** Deviations must be recorded in `tasks.md §实际偏差记录`.

Tests: file new backend tests under `test/<module>/` (e.g., `test/approval/`), not in `test/` root. `asyncio_mode=auto`.

---

## 7. Common Pitfalls

| Pitfall | Reality |
|---------|---------|
| `/api/v1/env` version field | Hardcoded `2.4.0` in source — unreliable. Use route probing instead. |
| MinIO image 403 | Vite `fileServiceTarget` must exactly match `config.yaml` `object_storage.minio.sharepoint`. |
| Passwords in config.yaml | Fernet-encrypted. Never write plaintext passwords into the YAML. |
| First registered user | Becomes `super_admin` automatically. In multi-tenant mode, create the tenant first. |
| `BISHENG_PRO=true` | Must be set **before** starting the backend, or `/api/v1/user/sso` endpoint won't exist. |
| DB config changes | 100s Redis TTL — wait or flush Redis after changing DB-stored config. |
| Celery Beat + multi-tenant | Beat iterates all active tenants; adding a task multiplies load by N tenants. |
| API proxy modes | Default: Vite → `:7860`. Commercial: set `VITE_PROXY_TARGET=http://localhost:8180`. |

---

## 8. Reference

- **Backend module map, subsystem internals** → `src/backend/CLAUDE.md`
- **Architecture docs** → `docs/architecture/` (`10-permission-rbac.md`, `11-gateway.md`)
- **SDD guide** → `docs/SDD-Guide.md`
- **v2.5 permission/multi-tenant PRD** → `docs/PRD/`
- **Skills**: `/sdd-review`, `/task-review`, `/code-review`, `/e2e-test`, `/i18n-localizer`, `/react-component-refactor`
