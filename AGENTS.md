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

**Design specs & component library — mandatory entry for ANY UI work (new pages AND edits to existing ones):**
- **Read the design spec docs first.** They are the SSOT for "when to use what" (typography, color, radius/shadow, multi-device, per-component usage rules). They live at `src/frontend/packages/ui/docs/` (git-tracked; entry `index.md`, specs in `基础-*` / `组件-*` files; browsable as a site via `pnpm dev:ui` at `src/frontend/`). The specs are actively maintained and keep evolving — read the current version each time; never code from memory of an old read.
- **Component selection**: when a UI needs a component, use a **landed** one from the component overview (`src/frontend/packages/ui/docs/components/index.mdx` — i.e. pages marked `status: done`, shipped in `@bisheng/ui`). If the component you need is not finalized or not built yet, do NOT invent a new pattern — find the closest existing implementation in the current client code and follow it.
- **Ownership**: design spec content and component visual styles belong to the designer. Non-designers must not edit spec decisions, change component styles, or add new components on their own. Frontend engineers MAY improve existing component internals (refactor, perf, a11y), but any style/visual change requires designer sign-off.

**Hard rules (both apps — single source of truth here; per-app files add only app-specific detail):**
- TypeScript only (`.ts` / `.tsx`); functional components only; no class components.
- Single file ≤ 600 lines. Extract sub-components or hooks when exceeded.
- `interface` for Props; `type` for internal types. `handleXxx` internal handlers / `onXxx` props. PascalCase components, camelCase utilities/hooks.
- Named exports for components (`export function`); no default exports. Minimize `any` — if unavoidable, `// eslint-disable-next-line` + a one-line reason.
- **Never** `import axios` directly — use the wrapped request module. (store must not call HTTP = constitution **C7**)
- **Never** introduce new UI or state-management libraries.
- All code comments in English.
- 403 handled automatically by response interceptors — never add 403 branches in business code.
- **A Radix `<SelectItem>` must never receive an empty-string `value`** — it throws and takes the whole page down with it. Any selector rendering a backend list has to filter out rows whose id is `null` or `''` before mapping them to items. Do not rely on the backend to sanitize: older backend versions do send such rows, and the crash surfaces to the user as a blank page rather than an empty dropdown.
- **UI copy is written in plain language and does not borrow internal object names.** Where the spec says `PermissionModel`, the interface needs a separate business word: check what comparable products call it, then confirm the term isn't already taken by another concept on the platform. Don't coin abbreviations — read the sentence aloud, and if it sounds wrong it is wrong. Buttons take short verbs, fields take noun phrases, and explanatory sentences belong in a hint rather than crammed into a control's label. When copy refuses to come out clear, what's usually missing is a mechanism the page never explains — fix that first instead of renaming.
- **No frosted glass by default** — no `backdrop-filter` / `backdrop-blur-*`, including arbitrary values (`backdrop-blur-[4px]`), variant prefixes (`hover:backdrop-blur-sm`) and the arbitrary-property form `[backdrop-filter:blur(…)]`. Every such element gets its own compositing layer and re-snapshots + re-blurs its backdrop each frame; without GPU acceleration — the norm on 信创 machines — that runs on the CPU. A customer on 信保安全浏览器 (Chromium 108) had scrolling *and mouse movement* stall in daily chat; forcing `backdrop-filter: none` fixed it outright. Cost is **per element, not per radius**: a 4px blur on a 24px button costs the same order as a full-screen one, and the per-message action buttons multiplied it by conversation length. Use a translucent background instead (`bg-white/80`, `bg-black/40`) — past ~70% opacity the blur was invisible anyway. **Only exception**, and it must be justified: a full-screen overlay of which at most one exists at a time, verified on a 信创 browser. Never on anything that scales with content (list rows, message bubbles, cards, notification items). Rationale + alternatives: `packages/ui/docs/基础-阴影与圆角规范.mdx` §3.
- **i18n**: no hardcoded Chinese in source (lint-enforced; legacy frozen). New keys ship all three languages (zh-Hans/en/ja) in the same PR. Error-code copy lives ONLY in `src/frontend/packages/locales` (`api_errors` domain — platform addresses `api_errors:<code>`, client `api_errors.<code>`); its generated artifacts (`platform/public/locales/*/api_errors.json`, `client/src/locales/*/api_errors.gen.json`) are never edited by hand (CI-checked). CI also runs `pnpm check-i18n` — key parity across languages + backend error-code coverage; legacy drift is frozen in `scripts/i18n-baseline.json` (shrink-only, `--update-baseline` after healing). Legacy hardcoded Chinese is paid down by whoever touches the file: when editing a file with frozen violations, extract its Chinese strings to i18n (`/i18n-localizer`) in the same change. See `packages/locales/README.md`.
- **Quality gate (CI-enforced, `frontend-quality.yml`)**: `pnpm lint` + `pnpm typecheck` (run from `src/frontend/`) must pass. Legacy violations are frozen — ESLint in each app's `eslint-suppressions.json`, TS strict via `// @ts-strict-ignore` file headers — and may only shrink: never hand-edit the suppressions file, never add `@ts-strict-ignore` to a new file. After fixing violations in a file, run `pnpm lint:prune` (per app) and delete its `@ts-strict-ignore` header if it now passes strict.

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

- **Renumbering a section means running a cross-reference sweep** — collect every `§X.Y` reference and every heading, and diff both ways. Prose problems are caught by reading the document once; broken references are not.
- **Write AC ids out in full** (`AC-P4、AC-P5`, never `AC-P4 / P5`): a contracted form is not greppable and breaks the traceability chain. Anything meant to change later belongs in an AC, not a comment — comments get lost, ACs get checked at delivery.
- **Whether a feature actually shipped cannot be read off the `features/` directory**, nor off its entry in the release contract: complete spec and design documents with zero lines of implementation have happened. Grep the implementation side for real wiring (registration, call sites, i18n keys) before claiming delivery.
- **The release-line branch is the single source of truth.** Anything not specific to a derived branch lands on the current release line first, and derived branches merge down from it. Doing it the other way round — first on the derived branch, then cherry-picked back — leaves the same change on two lines under different hashes, so history carries it twice and "did this reach the release line?" can only be answered by comparing content. Across version lines, cherry-pick only, and only from a commit that is already on a release line. When back-porting, `git cherry` is not a reliable duplicate check: a fix that was picked into a hotfix branch and then merged forward is an *ancestor* of the merge base, so the comparison range is empty and it looks absent. Check per file with `git diff <base> <head> -- <file>` plus `git log <base> -- <file>`, and record any deliberate divergence from the source branch — otherwise the next person "corrects" it back.

---

## 7. Common Pitfalls

Backend runtime pitfalls (tenant-filter SELECT-only gap, ruff hook import trap, Celery Beat × multi-tenant, DB config Redis TTL and db index, single-host compose hiding multi-node bugs, `create_time` tie-breaking, duplicate table definitions, non-admin permission verification, baseline-diff regression judgement) → `src/backend/AGENTS.md` §Known Pitfalls; config/packaging contracts (new YAML top-level keys, `uv export`, committed CLI wheel, dependency licensing) → the same file's §Config & Packaging Contracts. Linsight agent-framework contracts → `src/backend/bisheng/linsight/AGENTS.md`; skill-pack authoring → `.../linsight/builtin_skills/AGENTS.md`. Client pitfalls (MinIO presigned-URL host, sandboxed `srcDoc` storage, markdown pipeline, local dev login, `pnpm install` breaking jest) → `src/frontend/client/AGENTS.md` §Known Pitfalls. MinIO `sharepoint` image-proxy pitfall → `src/frontend/platform/AGENTS.md` §Known Pitfalls. Commercial edition (`BISHENG_PRO` env, gateway proxy, SSO) → `docs/architecture/11-gateway.md`.

| Pitfall | Reality |
|---------|---------|
| `/api/v1/env` version field | Hardcoded `2.4.0` in source — unreliable. Use route probing instead. |
| Passwords in config.yaml | Fernet-encrypted. Never write plaintext passwords into the YAML. |
| First registered user | Becomes `super_admin` automatically. In multi-tenant mode, create the tenant first. |
| `docker compose restart bisheng-backend` | `bisheng-backend` is a `container_name`; the compose *service* names are `backend` / `backend_worker`. The wrong one fails with `no such service` and restarts nothing — and if the container happened to restart on its own, `Up N seconds` makes it look like the command worked. |
| "I clicked it and nothing happened" | Read `process_time` for that request in the backend access log first. "Slow" (a synchronous blocking action) and "broken" (a callback that never refreshed) have completely different fixes, and a second click usually returns a state-conflict error — if the frontend only toasts it without rolling back or re-syncing, the UI stays stuck on the old state forever. |

**Method pitfalls** (they cost more than the factual ones above):

- **To decide whether code is still live, trace its callers and its frontend entry point** — its presence in the tree proves nothing. This repo carries a lot of paths whose UI was removed while the backend implementation stayed. Grep the backend, then the frontend API layer and component usages, and then check whether guard conditions and field defaults leave the branch permanently untaken. Reading statically and treating leftovers as current produces badly wrong conclusions.
- **Let the root cause determine the scope; don't fold every gap you pass into one change.** For each candidate ask "once the root cause is fixed, does this still hold?" — the ones that don't go on an explicit "not doing" list with the reason. Before editing a prompt or adding a fallback, read what the existing template / DB config / YAML **actually contains**; absence from the code is not absence from the system. And the right treatment for dead code is deletion, not reconnection.
- **Surface model misbehaviour; do not paper over it with a fallback.** A model that claims a deliverable it never produced is a diagnosable defect — manufacturing the file on its behalf destroys the evidence and makes the defect unmeasurable. Preference order: fix the prompt, then detect and log or flag, then let the UI show the anomaly honestly (greyed out and marked "not generated", not a normal-looking link that does nothing). Keep a fallback only where it is already an established product contract.
- **When several agents share one working tree, repository-wide git writes are forbidden**: `git stash` (including pop/apply), `git checkout .`, `git reset --hard`, `git clean`, and `git restore` without a path. They act on the whole tree rather than "your" files and silently swallow another session's in-progress work. Read committed content with `git show HEAD:<path>`, inspect your own edits with `git diff HEAD -- <path>`, and use `git worktree add` when you need a clean checkout; a path-scoped `git checkout <ref> -- <path>` is safe. Put this in the task brief when dispatching concurrent sub-agents.
- **`git checkout --theirs <file>` takes the other side's *whole file*, not just the conflicted hunks.** On files where both sides added entries independently (locale JSON, error-code copy) it silently drops everything unique to your side, and the result still parses and still looks like a one-line diff. Use `git checkout --merge -- <file>` to restore the conflict markers and resolve hunk by hunk, then validate by parsing the file.

---

## 8. Reference

- **Docs index** → `docs/README.md` (navigation hub); onboarding & testing → `docs/architecture/09-development-guide.md`
- **Architecture docs** → `docs/architecture/` (overview, permission, gateway, multi-tenant, data-models, …)
- **Skills**: `/sdd-review`, `/task-review`, `/code-review`, `/e2e-test`, `/i18n-localizer`, `/react-component-refactor`

**Instruction files (AGENTS.md map).** Root = this file, loaded every session. Auto-loaded on top when editing the matching directory: `src/backend/`, `src/frontend/platform/`, `src/frontend/client/`, `src/frontend/packages/ui/` (shared component library + design-token SSOT), plus deep-dir specials `src/backend/bisheng/core/database/alembic/` (migrations), `src/backend/scripts/` (one-off scripts), `src/backend/bisheng/linsight/` (agent-framework contracts) and `src/backend/bisheng/linsight/builtin_skills/` (skill-pack authoring). Every `CLAUDE.md` is a symlink to its sibling `AGENTS.md` — edit `AGENTS.md` only. Put a new rule in the deepest file covering its scope (cross-app / cross-module → this file; app- or dir-specific → the nearest file); never duplicate a rule across levels — it *will* drift.

