# Sensitive areas

**Verified** paths and topics that should trigger Ask First or a narrow boundary upgrade.

## Paths / modules

- `src/backend/bisheng/permission/domain/services/permission_service.py` — single ReBAC/RBAC entry
- `src/backend/bisheng/core/openfga/` — OpenFGA client; wrong tuples over- or under-grant
- `src/backend/bisheng/core/database/tenant_filter.py` — automatic tenant WHERE injection
- `src/backend/bisheng/tenant/domain/services/tenant_resolver.py` — tenant resolution after login
- `src/backend/bisheng/common/dependencies/user_deps.py` — JWT / `UserPayload`
- `src/backend/bisheng/sso_sync/api/endpoints/login_sync.py` — SSO login sync
- `src/backend/bisheng/user/api/user.py` — legacy `/user/sso` (mounted only with `BISHENG_PRO=true`)
- `src/backend/bisheng/core/database/alembic/versions/` — migrations; must run on MySQL and DM8
- `src/backend/bisheng/core/database/dialect_helpers.py` — dual-DB type contract
- `src/backend/bisheng/api/router.py` — global router registration
- `src/backend/bisheng/open_endpoints/` — `/api/v2` external RPC
- `src/backend/bisheng/approval/` — approval gateway and outbox
- `src/backend/bisheng/points/domain/services/points_award_facade.py` — points award facade
- `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` — visibility, subscription, quota
- `src/backend/bisheng/knowledge/rag/` — ingestion; Milvus + ES dual write
- `src/backend/bisheng/worker/` — Celery; Beat fans out per tenant
- `src/backend/bisheng/core/storage/tenant_storage.py` — per-tenant prefixes for MinIO / Milvus / ES / Redis
- `src/backend/bisheng/config.yaml` — gitignored; Fernet-encrypted passwords; DB-stored config has a 100 s Redis TTL

## Topics

| Topic | Where in this repo | Why sensitive |
|-------|--------------------|---------------|
| Auth / sessions / SSO | `common/dependencies/user_deps.py`; `sso_sync/api/endpoints/login_sync.py`; `user/api/user.py` | Identity, session, and user/department ownership |
| Permissions / visibility | `permission/domain/services/permission_service.py`; `core/openfga/`; `core/database/tenant_filter.py` | Cross-tenant leaks or privilege escalation |
| Public API / schema / contracts | `api/router.py`; `open_endpoints/`; `common/schemas/api.py`; `common/errcode/` | Frontends and portal BFF depend on response shape and 5-digit codes |
| Migrations / bulk data | `core/database/alembic/versions/`; approval outbox; points award | Irreversible or wide blast |
| Secrets / prod config / CI/CD | `bisheng/config.yaml`; `core/config/settings.py`; `docker/`; `.github/workflows/` | Leak and outage risk |

Paths in the table are relative to `src/backend/bisheng/` except `docker/` and `.github/`.

## Narrow upgrade reminder

Pause / Ask First only for **shared semantics**, **external contracts**, or **irreversible data/authz**.
Multi-file edits alone are not enough. For modules not listed, rely on the type triggers in `.cursor/rules/agents.mdc`.
