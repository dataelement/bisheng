# Architecture (agent-facing)

Keep this short. Paths over essays. Rule text for each boundary lives in root `AGENTS.md`; this file only maps it to code.

## What this repo is

BiSheng (毕昇): enterprise LLM application DevOps platform. FastAPI backend + Celery workers, Platform admin UI, Client chat UI.

## Boundaries

| Boundary | Where enforced |
|----------|----------------|
| Platform vs Client frontends never import each other | `scripts/arch-guard.sh` RULE-11 |
| `Router → Endpoint → Service → Repository → DB` | `AGENTS.md` §3.1; arch-guard RULE-3/5 |
| `common/`, `core/` do not import `domain/`, `api/` | arch-guard RULE-1 |
| Permission checks only via `PermissionService` | `src/backend/bisheng/permission/domain/services/permission_service.py`; arch-guard RULE-8 |
| Tenant filter is auto-injected | `src/backend/bisheng/core/database/tenant_filter.py` |
| MySQL + DM8 column types | `src/backend/bisheng/core/database/dialect_helpers.py`; arch-guard RULE-9 |
| New routers registered centrally | `src/backend/bisheng/api/router.py` |

Long-form docs: `docs/architecture/` (`10-permission-rbac.md`, `11-gateway.md`).

## Exemplars (copy these patterns)

| Pattern | Path |
|---------|------|
| New backend module (`api/` + `domain/`) | `src/backend/bisheng/approval/`, `src/backend/bisheng/points/` |
| Login user dependency | `src/backend/bisheng/common/dependencies/user_deps.py` |
| Business error codes | `src/backend/bisheng/common/errcode/` |
| Platform HTTP | `src/frontend/platform/src/controllers/request.ts` |
| Client HTTP | `src/frontend/client/src/api/request.ts` |

Do not copy from `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`; it is an oversized legacy service.

## Narrow boundary upgrade

Default: `改 → 验 → 报`.

**Upgrade** (≤5-line blast radius, pause if high risk) only when changing:

1. Shared semantics — dedup, quota, visibility, cache-key meaning, event/outbox contract, points award rules
2. External contracts — public API, `/api/v2`, schema, DB field meaning, response shape consumed by the portal BFF
3. Irreversible / authz — migrations, bulk delete/update, permission tightening, OpenFGA tuples, tenant isolation

**Do not upgrade** for private one-module work, UI copy, tests-only, or multi-file edits that do not change the above.

When unsure and not (1)–(3) → proceed; note residual risk in the report.

See also: `sensitive-areas.md` for verified hot paths.
