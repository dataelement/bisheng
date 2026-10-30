# AGENTS.md

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

Dev / test / build commands live in each sub-project's `AGENTS.md`: `src/backend/AGENTS.md` · `src/frontend/platform/AGENTS.md` · `src/frontend/client/AGENTS.md`.

Middleware (MySQL / Redis / Milvus / ES / MinIO / OpenFGA): integration tests run in **CI**; per-developer middleware machines are pending.

---

## 3. Backend Rules (P0)

- **Architectural laws** (DDD layering / dual-DB / multi-tenancy / permissions / error codes / security) → [`docs/constitution.md`](docs/constitution.md) (C1–C7); enforced by `scripts/arch-guard.sh` + Constitution Check in `/sdd-review design`.
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
8. /sdd-code-review --base <main>  (+ CI auto-review)
9. merge
```

Artifacts: `features/v{X.Y.Z}/{NNN}-{name}/{spec,design,tasks}.md`. Templates: `features/_templates/` (incl. `release-contract.md`).
**★ cannot be skipped.** Trivial/hotfix changes use a lighter track — see SDD-Guide §1.

Tests: new backend tests under `test/<module>/` (e.g., `test/approval/`), not `test/` root. `asyncio_mode=auto`.

- **Release line first**: changes not specific to a derived branch land on the release line, then merge down; across version lines, cherry-pick only from a commit already on a release line. Details (back-port duplicate checks, AC id format, renumbering sweep, verifying delivery) → `docs/SDD-Guide.md` §9.

---

## 7. Common Pitfalls

Subsystem pitfalls live in the nearest AGENTS.md (backend / client / platform §Known Pitfalls, linsight). Factual pitfalls table + method pitfalls in full → `docs/agent-pitfalls.md`. One-line index: liveness = trace callers + frontend entry · root cause = check magnitude, measure where it reproduces · scope follows root cause; dead code is deleted · surface model misbehaviour, don't fall back.

- **Shared working tree: no repo-wide git writes** — `git stash` (incl. pop/apply), `git checkout .`, `git reset --hard`, `git clean`, path-less `git restore`. Use `git show HEAD:<path>`, `git diff HEAD -- <path>`, `git worktree add`; a path-scoped `git checkout <ref> -- <path>` is safe. Put this in every concurrent sub-agent brief.
- **`git checkout --theirs <file>` takes the whole file**, silently dropping your side's unique entries (locale JSON, error-code copy). Use `git checkout --merge -- <file>`, resolve hunk by hunk, then parse the file to validate.

---

## 8. Reference

- **Docs index** → `docs/README.md` (navigation hub); onboarding & testing → `docs/architecture/09-development-guide.md`
- **Architecture docs** → `docs/architecture/` (overview, permission, gateway, multi-tenant, data-models, …)
- **Skills**: `/sdd-review`, `/task-review`, `/sdd-code-review`, `/e2e-test`, `/i18n-localizer`, `/react-component-refactor`. Single source in `.claude/skills/`; `.cursor/skills` and `.agents/skills` are symlinks to it — never add a copy there. `/sdd-code-review` is the project checklist review; Claude Code's built-in `/code-review` is a different tool.

**Instruction files (AGENTS.md map).** Root = this file, loaded every session. Auto-loaded on top when editing the matching directory: `src/backend/`, `src/frontend/` (rules shared by both apps), `src/frontend/platform/`, `src/frontend/client/`, `src/frontend/packages/ui/` (shared component library + design-token SSOT), plus deep-dir specials `src/backend/bisheng/core/database/alembic/` (migrations), `src/backend/scripts/` (one-off scripts), `src/backend/bisheng/linsight/` (agent-framework contracts) and `src/backend/bisheng/linsight/builtin_skills/` (skill-pack authoring). Every `CLAUDE.md` is a symlink to its sibling `AGENTS.md` — edit `AGENTS.md` only. Put a new rule in the deepest file covering its scope (cross-module → this file; cross-frontend-app → `src/frontend/AGENTS.md`; app- or dir-specific → the nearest file); never duplicate a rule across levels — it *will* drift.

**Only write verified behaviour into an AGENTS.md entry, and say how it was verified** (a measurement, a repro script, a test). If something is plausible but unproven, keep it in memory marked as a hypothesis (why → `docs/agent-pitfalls.md`).
