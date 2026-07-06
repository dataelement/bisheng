# AGENTS.md

---

## 1. Project Identity

**BiSheng (毕昇)** — Enterprise LLM application DevOps platform. Monorepo, three sub-projects:

| Path | Project | Stack |
|------|---------|-------|
| `src/backend/` | FastAPI + Celery Workers + Linsight Worker | Python 3.11+, uv, SQLModel, LangGraph |
| `src/frontend/platform/` | Admin / builder UI | Vite 5 + **Zustand** + react-query v3 + bs-ui |
| `src/frontend/client/` | End-user chat UI (`/workspace` base path) | Vite 6 + **Recoil** + react-query v4 (@tanstack) + shadcn/ui |

**Runtime topology** (full picture → `docs/architecture/01-architecture-overview.md`):
- Two SPAs — platform (:3001) and client (:4001, base `/workspace`) — call FastAPI (:7860): `/api/v1` frontend-facing, `/api/v2` open RPC. Commercial edition inserts a Java gateway in front (→ `architecture/11-gateway.md`).
- Async work: Celery workers (knowledge / workflow / default queues) + Beat; the Linsight agent runs as an independent worker process fed by a Redis queue.
- Storage ×6: MySQL|DM8 (dual-DB law C2), Redis, Milvus + ES (RAG dual recall), MinIO, OpenFGA (ReBAC).
- Cross-cutting: tenant isolation auto-injected via ContextVar (C3); every permission check goes through PermissionService → OpenFGA (C4).

---

## 2. Commands

Dev / test / build commands live in each sub-project's `AGENTS.md`: `src/backend/AGENTS.md` · `src/frontend/platform/AGENTS.md` · `src/frontend/client/AGENTS.md`.

Middleware (MySQL / Redis / Milvus / ES / MinIO / OpenFGA): integration tests run in **CI**; per-developer middleware machines are pending.

---

## 3. Backend Rules (P0)

- **Architectural laws** (DDD layering / dual-DB / multi-tenancy / permissions / error codes / security) → [`docs/constitution.md`](docs/constitution.md) (C1–C7); enforced by `scripts/arch-guard.sh` + Constitution Check in `/sdd-review design`.
- **Backend coding conventions** (module layout, API/response helpers, pagination, error handling) + subsystem quick map → `src/backend/AGENTS.md` (auto-loads when editing backend files).

---

## 4. Frontend Rules (P0)

Two React apps that **must not be mixed**. Per-app rules auto-load from each sub-project's `AGENTS.md`:
- `src/frontend/platform/AGENTS.md` — Admin/builder UI (Zustand, react-query v3, bs-ui, `@/`)
- `src/frontend/client/AGENTS.md` — End-user chat UI (Recoil, react-query v4, shadcn, `~/`)

**Hard rules (both apps — single source of truth here; per-app files add only app-specific detail):**
- TypeScript only (`.ts` / `.tsx`); functional components only; no class components.
- Single file ≤ 600 lines. Extract sub-components or hooks when exceeded.
- `interface` for Props; `type` for internal types. `handleXxx` internal handlers / `onXxx` props. PascalCase components, camelCase utilities/hooks.
- Named exports for components (`export function`); no default exports. Minimize `any` — if unavoidable, `// eslint-disable-next-line` + a one-line reason.
- **Never** `import axios` directly — use the wrapped request module. (store must not call HTTP = constitution **C7**)
- **Never** introduce new UI or state-management libraries.
- All code comments in English.
- 403 handled automatically by response interceptors — never add 403 branches in business code.

---

## 5. Architecture Guard (Auto-enforced)

`scripts/arch-guard.sh` runs after every Write/Edit via a PostToolUse hook (through `.claude/hooks/arch-guard-hook.sh`, which feeds violations back to the agent as `additionalContext` for self-correction).
The 8 RULEs are the machine-enforcement arm of constitution **C1 / C4 / C6 / C7** — the clause↔RULE anchor table lives in [`docs/constitution.md`](docs/constitution.md). **VIOLATION must be fixed immediately.**

---

## 6. SDD Workflow (non-trivial features)

**Full guide — track selection, ★ pause points, deviation re-confirm rule, document roles, constitution gate, harness → [`docs/SDD-Guide.md`](docs/SDD-Guide.md).**

```
0. release-contract.md (features/v{X.Y.Z}/release-contract.md;
   version's first feature creates it) + read constitution.md
1. Spec Discovery                          → ★ user confirms
2. spec.md   → /sdd-review <dir> spec       → ★ user confirms
3. design.md → /sdd-review <dir> design     → ★ user confirms (Constitution Check)
4. tasks.md  → /sdd-review <dir> tasks
5. branch feat/<version>/{NNN}-{name}  (create early; docs + code on the branch)
6. implement wave-by-wave → /task-review <dir> <id> → check off
7. /e2e-test <dir>  (mandatory)
8. /code-review --base <main>  (+ CI auto-review)
9. merge
```

Artifacts: `features/v{X.Y.Z}/{NNN}-{name}/{spec,design,tasks}.md`. Templates: `features/_templates/` (incl. `release-contract.md`).
**★ cannot be skipped.** Trivial/hotfix changes use a lighter track — see SDD-Guide §1.

Tests: new backend tests under `test/<module>/` (e.g., `test/approval/`), not `test/` root. `asyncio_mode=auto`.

---

## 7. Common Pitfalls

Backend runtime pitfalls (tenant-filter SELECT-only gap, ruff hook import trap, Celery Beat × multi-tenant, DB config Redis TTL) → `src/backend/AGENTS.md` §Known Pitfalls. MinIO `sharepoint` image-proxy pitfall → `src/frontend/platform/AGENTS.md` §Known Pitfalls. Commercial edition (`BISHENG_PRO` env, gateway proxy, SSO) → `docs/architecture/11-gateway.md`.

| Pitfall | Reality |
|---------|---------|
| `/api/v1/env` version field | Hardcoded `2.4.0` in source — unreliable. Use route probing instead. |
| Passwords in config.yaml | Fernet-encrypted. Never write plaintext passwords into the YAML. |
| First registered user | Becomes `super_admin` automatically. In multi-tenant mode, create the tenant first. |

---

## 8. Reference

- **Docs index** → `docs/README.md` (navigation hub); onboarding & testing → `docs/architecture/09-development-guide.md`
- **Architecture docs** → `docs/architecture/` (overview, permission, gateway, multi-tenant, data-models, …)
- **Skills**: `/sdd-review`, `/task-review`, `/code-review`, `/e2e-test`, `/i18n-localizer`, `/react-component-refactor`

**Instruction files (AGENTS.md map).** Root = this file, loaded every session. Auto-loaded on top when editing the matching directory: `src/backend/`, `src/frontend/platform/`, `src/frontend/client/`, plus deep-dir specials `src/backend/bisheng/core/database/alembic/` (migrations) and `src/backend/scripts/` (one-off scripts). Every `CLAUDE.md` is a symlink to its sibling `AGENTS.md` — edit `AGENTS.md` only. Put a new rule in the deepest file covering its scope (cross-app / cross-module → this file; app- or dir-specific → the nearest file); never duplicate a rule across levels — it *will* drift.

