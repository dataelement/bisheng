# BiSheng Architecture Constitution

> **The single source of truth for BiSheng's architectural laws — invariant across all features, never to be violated.**
>
> - `AGENTS.md` and every feature's `design.md` **reference this file; they never copy it.** Changing an implementation never requires editing this file (they point here).
> - `scripts/arch-guard.sh` is the **machine-enforcement arm** of this document: each RULE maps to a clause below (see the anchor table).
> - Violations are reported as **BLOCKER** during `/sdd-review design`.
> - **Change governance**: editing this file requires PR review (a law change affects every feature). If a RULE is involved, sync the "→ Cx" note in `arch-guard.sh`.
> - Last revised: 2026-06-05.

## Anchor Table (clause ↔ arch-guard RULE)

| Clause | Law | arch-guard RULE | Severity |
|---|---|---|---|
| **C1** | DDD layered call chain | RULE-1 / 2 / 3 / 4 / 5 | VIOLATION (RULE-3 is WARNING during migration) |
| **C2** | Dual-DB compatibility (MySQL + DM8) | — (review + CI) | — |
| **C3** | Multi-tenancy auto-injection | — (review) | — |
| **C4** | Permission unified entry point | RULE-8 | VIOLATION |
| **C5** | Error-code convention | — (review) | — |
| **C6** | No hardcoded secrets | RULE-7 | WARNING |
| **C7** | Frontend store must not call HTTP directly | RULE-6 | WARNING |

---

## C1. DDD Layered Call Chain

Call chain — **never skip layers**: `Router → Endpoint → Service → Repository → DB`

- **Never** `import bisheng.database.models.*` in endpoints — go through a Domain Service/DAO (RULE-3, WARNING during migration).
- **Never** write ORM queries in Service; **never** add new DAO entry points for new features.
- `common/`, `core/` must not import `domain/`, `api/` (RULE-1).
- `database/models/` must not import `domain/` (RULE-2).
- `domain/models/` must not import `domain/services/` (RULE-4).
- The API layer must not cross-import between modules (RULE-5).

## C2. Dual-DB Compatibility (MySQL + DM8) ⚠️

Every new feature must work on both dialects. **DM8 is not optional.**

| ✅ Use | ❌ Never use |
|--------|-------------|
| `dialect_helpers.JsonType` | `sqlalchemy.JSON`, `mysql.JSON` |
| `dialect_helpers.LargeText` | `LONGTEXT`, `MEDIUMTEXT` |
| `dialect_helpers.UPDATE_TIME_SERVER_DEFAULT` | `ON UPDATE CURRENT_TIMESTAMP` |
| `SQLAlchemy inspect()` | `information_schema`, `DATABASE()` |
| Explicit relational columns | `JSON_EXTRACT` / `JSON_CONTAINS` / `JSON_SEARCH` |

macOS: the DM8 driver (`dmPython`/`dmAsync`) is not installed (`sys_platform != 'darwin'`).
**DM8 is a development hard-requirement** — always use `dialect_helpers`, never MySQL-only syntax. But **DM8 compatibility is *verified* by a central regression run** (pre-release / periodic, on Linux), **not by per-feature CI gates** — day-to-day it's held by this law + review, not by a per-PR DM8 test.

## C3. Multi-Tenancy — Auto-Injected, Never Manual

**Never write `WHERE tenant_id = X` manually.** SQLAlchemy events handle it automatically for 23+ tables.
`multi_tenant.enabled=false` behaves identically to single-tenant (default `tenant_id=1`).

## C4. Permissions — Unified Entry Point

```python
from bisheng.permission.domain.services.permission_service import PermissionService
await PermissionService.check(...)      # check access
await PermissionService.authorize(...)  # write OpenFGA owner tuple on resource creation (required)
```

- **Never** query `role_access` directly for resource authorization (RULE-8 / historical invariant **INV-T19**, VIOLATION).
- Resource creation **must** call `PermissionService.authorize()`; failures go to the `failed_tuples` retry table.
- Five-level short-circuit: `super_admin` → tenant mismatch deny → tenant admin → ReBAC (OpenFGA) → RBAC menu.

## C5. Error-Code Convention

- 5-digit `MMMEE` (3-digit module + 2-digit error), defined in `common/errcode/`.
- Module numbers: 100=server, 104=assistant, 105=flow, 106=user, 108=llm, 109=knowledge, 110=linsight, 120=workstation, 130=chat, 140=message, 150=tool, 180=knowledge_space.

## C6. No Hardcoded Secrets (RULE-7)

No `password` / `secret_key` / `api_key` / `access_token` literals in code. Use config + Fernet encryption (passwords in `config.yaml` are Fernet-encrypted; never write plaintext).

## C7. Frontend Store Must Not Call HTTP Directly (RULE-6)

A frontend store must not call HTTP directly — go through `controllers/API/` (platform) or `api/` (client).
All other frontend conventions (state library, UI library, path aliases, i18n, Toast, etc.) live in `.claude/rules/platform-frontend.md` and `.claude/rules/client-frontend.md` (see also `AGENTS.md §4`).
