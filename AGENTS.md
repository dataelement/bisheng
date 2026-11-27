# AGENTS.md

**Before editing code:** Read and apply the [core Ponytail skill](.claude/skills/ponytail/SKILL.md) for every code change, including small fixes and hotfixes outside SDD. Follow the project's constitution and the selected track's required checks. Use the other [Ponytail skills](docs/SDD-Guide.md#11-ponytail-in-the-development-workflow) as needed.

---

## 1. Project Identity

**BiSheng (毕昇)** — Enterprise LLM application DevOps platform. Monorepo, three sub-projects:

| Path | Project | Stack |
|------|---------|-------|
| `src/backend/` | FastAPI + Celery Workers + Linsight Worker | Python 3.11+, uv, SQLModel, LangGraph |
| `src/frontend/platform/` | Admin / builder UI | Vite 6 + **Zustand** + @tanstack/react-query v4 + bs-ui |
| `src/frontend/client/` | End-user chat UI (`/workspace` base path) | Vite 6 + **Recoil** + react-query v4 (@tanstack) + shadcn/ui |

**Runtime topology** (full picture → `docs/architecture/01-architecture-overview.md`):
- Two SPAs — platform (:3001) and client (:4001, base `/workspace`) — call FastAPI (:7860): `/api/v1` frontend-facing, `/api/v2` open RPC. Commercial edition inserts a Java gateway in front (→ `architecture/11-gateway.md`).
- Async work: Celery workers (knowledge / workflow / default queues) + Beat; the Linsight agent runs as an independent worker process fed by a Redis queue.
- Storage ×6: MySQL|DM8 (dual-DB law C2), Redis, Milvus + ES (RAG dual recall), MinIO, OpenFGA (ReBAC).
- Cross-cutting: tenant isolation auto-injected via ContextVar (C3); every permission check goes through PermissionService → OpenFGA (C4).

---

## 2. Commands

Development commands and test conventions live in the sub-project guides: [backend](src/backend/AGENTS.md) · [platform](src/frontend/platform/AGENTS.md) · [client](src/frontend/client/AGENTS.md). For verification scope and environment, see the [SDD guide](docs/SDD-Guide.md).

---

## 3. Backend Rules (P0)

- **Architectural laws** → [`docs/constitution.md`](docs/constitution.md). The constitution maps each law to its review or automated check.
- **Backend coding conventions** (module layout, API/response helpers, pagination, error handling) + subsystem quick map → `src/backend/AGENTS.md` (auto-loads when editing backend files).

---

## 4. Frontend Rules (P0)

Two React apps that **must not be mixed**. Rules shared by both apps (design-spec entry, component selection, hard rules, i18n, quality gate) → `src/frontend/AGENTS.md`; per-app detail → `src/frontend/platform/AGENTS.md` · `src/frontend/client/AGENTS.md`. All of them auto-load when you edit files under `src/frontend/`.

---

## 5. Architecture Guard (Auto-enforced)

`scripts/arch-guard.sh` runs after every Write/Edit via a PostToolUse hook (through `.claude/hooks/arch-guard-hook.sh`, which feeds violations back to the agent as `additionalContext` for self-correction).
The 10 RULEs (RULE-1 … RULE-10) are the machine-enforcement arm of constitution **C1 / C4 / C6 / C7** — the clause↔RULE anchor table lives in [`docs/constitution.md`](docs/constitution.md). **VIOLATION must be fixed immediately.**

---

## 6. SDD Workflow (non-trivial features)

Before starting, pick the track in the [SDD guide](docs/SDD-Guide.md) and follow its steps, mandatory ★ confirmations, and release-line rules. The guide owns the process and artifact requirements.

---

## 7. Common Pitfalls

Read [BiSheng's known pitfalls](docs/agent-pitfalls.md) for verified lessons and links to the relevant subsystem rules.

- **Shared working tree: no repo-wide git writes** — `git stash` (incl. pop/apply), `git checkout .`, `git reset --hard`, `git clean`, path-less `git restore`. Use `git show HEAD:<path>`, `git diff HEAD -- <path>`, `git worktree add`; a path-scoped `git checkout <ref> -- <path>` is safe. Put this in every concurrent sub-agent brief.
- **`git checkout --theirs <file>` takes the whole file**, silently dropping your side's unique entries (locale JSON, error-code copy). Use `git checkout --merge -- <file>`, resolve hunk by hunk, then parse the file to validate.

---

## 8. Reference

- **Docs index** → `docs/README.md` (navigation hub); onboarding & testing → `docs/architecture/09-development-guide.md`
- **Architecture docs** → `docs/architecture/` (overview, permission, gateway, multi-tenant, data-models, …)
- **Skills**: `/sdd-review`, `/task-review`, `/sdd-code-review`, `/e2e-test`, `/i18n-localizer`, `/react-component-refactor`. Single source in `.claude/skills/`; `.cursor/skills` and `.agents/skills` are symlinks to it — never add a copy there. `/sdd-code-review` is the project checklist review; Claude Code's built-in `/code-review` is a different tool.

**Instruction files (AGENTS.md map).** Root = this file, loaded every session. Auto-loaded on top when editing the matching directory: `src/backend/`, `src/frontend/` (rules shared by both apps), `src/frontend/platform/`, `src/frontend/client/`, `src/frontend/packages/ui/` (shared component library + design-token SSOT), plus deep-dir specials `src/backend/bisheng/core/database/alembic/` (migrations), `src/backend/scripts/` (one-off scripts), `src/backend/bisheng/linsight/` (agent-framework contracts) and `src/backend/bisheng/linsight/builtin_skills/` (skill-pack authoring). Every `CLAUDE.md` is a symlink to its sibling `AGENTS.md` — edit `AGENTS.md` only. Put a new rule in the deepest file covering its scope (cross-module → this file; cross-frontend-app → `src/frontend/AGENTS.md`; app- or dir-specific → the nearest file); never duplicate a rule across levels — it *will* drift.

**Only write verified behaviour into an AGENTS.md entry, and say how it was verified** (a measurement, a repro script, a test). If something is plausible but unproven, keep it in memory marked as a hypothesis (why → `docs/agent-pitfalls.md`).
