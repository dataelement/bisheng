# BiSheng Architecture Constitution

> **The single source of truth for BiSheng's architectural laws — invariant across all features, never to be violated.**
>
> - `AGENTS.md` and every feature's `design.md` **reference this file; they never copy it.** Changing an implementation never requires editing this file (they point here).
> - `scripts/arch-guard.sh` is the **machine-enforcement arm** of this document: each RULE maps to a clause below (see the anchor table).
> - Violations are reported as **BLOCKER** during `/sdd-review design`.
> - **Change governance**: editing this file requires PR review (a law change affects every feature). If a RULE is involved, sync the "→ Cx" note in `arch-guard.sh`.
> - Last revised: 2026-08-14 (C8: no shared state on the local filesystem).

## Anchor Table (clause ↔ arch-guard RULE)

| Clause | Law | arch-guard RULE | Severity |
|---|---|---|---|
| **C1** | DDD layered call chain | RULE-1 / 2 / 3 / 4 / 5 | VIOLATION (RULE-3 is WARNING during migration) |
| **C1** | Backend holds no orchestration privilege (F054 K1): no docker / kubernetes SDK import, no `/var/run/docker.sock`, no `DOCKER_HOST` anywhere under `src/backend/bisheng/**`. Container lifecycle is driven by desired-state intents sent to the standalone `src/runtime-manager/` process, which is the sole holder of that access surface. | RULE-10 | VIOLATION |
| **C2** | Dual-DB compatibility (MySQL + DM8) | — (review + CI) | — |
| **C3** | Multi-tenancy auto-injection | — (review) | — |
| **C4** | Permission unified entry point | RULE-8 / 9 | VIOLATION |
| **C5** | Error-code convention | — (review) | — |
| **C6** | No hardcoded secrets | RULE-7 | WARNING |
| **C7** | Frontend store must not call HTTP directly | RULE-6 | WARNING |
| **C8** | No shared state on the local filesystem | — (review) | — |

---

## C1. DDD Layered Call Chain

Call chain — **never skip layers**: `Router → Endpoint → Service → Repository → DB`

- **Never** `import bisheng.database.models.*` in endpoints — go through a Domain Service/DAO (RULE-3, WARNING during migration).
- **Never** write ORM queries in Service; **never** add new DAO entry points for new features.
- `common/`, `core/` must not import `domain/`, `api/` (RULE-1).
- `database/models/` must not import `domain/` (RULE-2).
- `domain/models/` must not import `domain/services/` (RULE-4).
- The API layer must not cross-import between modules (RULE-5).
- `src/backend/bisheng/**` must not import a container/orchestration SDK (`docker`, `aiodocker`, `kubernetes`, `kubernetes_asyncio`), reference `/var/run/docker.sock`, or read `DOCKER_HOST` (RULE-10). The backend describes *desired state* over HTTP to the standalone `src/runtime-manager/` package; only that process holds the orchestration access surface. Rationale: a backend that can talk to dockerd is root-equivalent on the host, which defeats the isolation the whole hosted-app design rests on.

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

## C4. Permissions — Verified Business Target + Unified Action Runtime

```python
from bisheng.permission.application.business_authorization import (
    require_business_action,
)

await require_business_action(
    login_user,
    resource_type="workflow",
    resource_id=workflow_id,
    action="edit",
)
```

- The owning business Service/adapter first loads the resource, checks
  tenant/status/parent/version rules, then creates `VerifiedPermissionTarget`.
  The permission module only performs business-independent authorization; it
  **must not** import or query business ORM/DAO/Repository/Service objects.
- **Never** query `role_access`, OpenFGA, or legacy relation/`permission_id`
  templates directly for resource authorization (RULE-8 / historical invariant
  **INV-T19**, VIOLATION). Concrete actions go through the sole F048 runtime.
- Resource creation/move/copy/delete, Grant mutation, mode switch, and Catalog
  publish must pre-record a durable operation/tuple projection ledger before
  OpenFGA mutation. SQL finalize is allowed only after the atomic projection
  succeeds; retry/forward repair uses the same idempotency key and frozen plan.
- Concrete resource decisions short-circuit in this order:
  `super_admin` → tenant mismatch deny → tenant admin → Catalog/action gate →
  OpenFGA. RBAC menu access remains a separate navigation/API-capability
  concern and is never a fallback ALLOW for resource actions.
- Business modules depend only on application protocols exported by
  `permission.application`. They must never import an OpenFGA client/manager,
  construct transport tuples, or branch on OpenFGA-specific errors. Identity
  checks, relation queries, grants, revokes, and projection mutations all pass
  through the permission module; only permission infrastructure and explicit
  operational migration tools may access OpenFGA directly (RULE-9).
- Production resolves one unique OpenFGA Store by stable name and its latest
  model on first permission-runtime access, then requires that Store/model/checksum to match the one
  ACTIVE authorization release referenced by the SQL CURRENT Catalog. Every
  Check/List/Write still sends that resolved model ID explicitly. Legacy/
  dual-model clients, runtime model writes, and fail-open behavior are
  forbidden. During an explicit version upgrade, a predecessor model or an
  incomplete CURRENT Catalog must fail the lazy permission Context closed: it
  must not publish a ready heartbeat, serve production authorization, or start
  data migration. Migration traffic control belongs to deployment/ingress and
  queue operations; application health checks and global HTTP/WebSocket/Celery/
  Linsight gates must not encode the one-time migration procedure.

## C5. Error-Code Convention

- 5-digit `MMMEE` (3-digit module + 2-digit error), defined in `common/errcode/`.

**Module registry** (35 in use as of 2026-08-17). The authoritative source is always the `Code: int = NNNNN` literals themselves; this table mirrors them and *will* drift. **Before claiming a new module number, re-derive the list:**

```bash
grep -rhoE "Code:\s*int\s*=\s*[0-9]{5}" src/backend/bisheng/common/errcode/*.py \
  | grep -oE "[0-9]{5}" | cut -c1-3 | sort -un
```

| Range | Assignments |
|---|---|
| 10x | 100 server · 101 finetune · 102 model_deploy · 103 component · 104 assistant · 105 flow · 106 user · 107 tag · 108 llm · 109 knowledge |
| 11x | 110 linsight · 111 linsight (second block) |
| 12x–18x | 120 workstation · 140 message · 150 tool · 160 dataset · **161 app_factory (F054)** · 170 telemetry · 180 knowledge_space · 181 approval |
| 19x (tenant / permission) | 190 channel **and** permission ⚠️ · 191 tenant_resolver · 192 tenant_fga · 193 sso_sync · 194 tenant_quota · 195 tenant_sharing · 196 resource_owner_transfer · 197 admin_scope · 198 llm_tenant |
| 20x–26x (org / open API) | 200 tenant · 210 department · 220 org_sync **and** tenant_tree ⚠️ · 230 user_group · 240 role · 250 permission · 260 open_api |

- ⚠️ **190 and 220 are each shared by two modules** — pre-existing collisions, not a precedent. Never reuse an occupied number.
- **130 was registered as `chat` but is not used by any error code.** Do not treat it as free without checking; do not cite it as an example.
- **260 = open_api** (F049, `common/errcode/open_api.py`): open face `/api/v2` uses 26001–26019 (26001 / 26002 / 26003 / 26004 / 26012 implemented; 26005–26007 / 26010 / 26016 reserved for F050 delegation; 26013 / 26014 retired, never reuse), management face `/api/v1/service-accounts/**` uses 26020+ (26020–26031 implemented). Every 260xx carries a real `http_status` for the `/api/v2` handler; copy for each code must land in `packages/locales/src/api_errors/*.json` (all three languages) in the same change.
- **181 = approval** (F025 审批中心, `common/errcode/approval.py`): 18100–18118 in use. Note that 181 is the band for the approval **engine**, which every scenario shares — `withdraw` / `decide` guards live here (e.g. **18118** `ApprovalInstanceNotPendingError`, F055 T051), *not* in a scenario owner's band such as 162. A code added here tightens behaviour for menu access, channel subscription, knowledge-space join and app publish at once, so it needs regression coverage in every live scenario, and its copy must land in `packages/locales/src/api_errors/*.json` (all three languages) in the same change.
- **161–164 = app_factory** (v3.0.0 应用工场). One band, four owners — split so each feature can claim codes without touching another's file: **161 = F054** (hosted-app domain + runtime, `common/errcode/app_factory.py`) · **162 = F055** (publish pipeline) · **163 = F056** (app square / governance) · **164 = F059** (k8s runtime backend). 161 sub-ranges: `16100-16119` domain/state machine · `16120-16139` runtime/orchestration · `16140-16159` entry & identity injection · `16160-16179` data plane/logs · `16180-16199` deployment switch/ops. The same assignment is mirrored in `features/v3.0.0/release-contract.md` ("已分配模块编码"), which is where F055 / F056 / F059 look it up — update both together.
- When you claim a number, add it here in the same change.

## C6. No Hardcoded Secrets (RULE-7)

No `password` / `secret_key` / `api_key` / `access_token` literals in code. Use config + Fernet encryption (passwords in `config.yaml` are Fernet-encrypted; never write plaintext).

## C7. Frontend Store Must Not Call HTTP Directly (RULE-6)

A frontend store must not call HTTP directly — go through `controllers/API/` (platform) or `api/` (client).
All other frontend conventions (state library, UI library, path aliases, i18n, Toast, etc.) live in `.claude/rules/platform-frontend.md` and `.claude/rules/client-frontend.md` (see also `AGENTS.md §4`).

## C8. No Shared State on the Local Filesystem ⚠️

**Multi-node is the default assumption, not an edge case.** The backend already runs as several
processes that need not share a machine: API replicas (`uvicorn --workers`), Celery workers, the
Linsight worker (`bisheng/linsight/worker.py`, hostname-derived `node_id` + heartbeats), and Beat.
Two processes agreeing today only because a single-host `docker compose` happens to bind-mount the
same `/app/data` is an accident, not a design.

The authoritative store for anything read by more than one process is **MySQL/DM8, Redis, or MinIO**.
The local filesystem is a cache: disposable, rebuildable, never the source of truth.

| ✅ Use | ❌ Never |
|--------|---------|
| Object storage for bytes + DB row for the pointer | A DB row whose payload only exists on the writer's disk |
| Content-addressed keys, local cache keyed by that hash | A mutable local path treated as the live copy |
| Startup work registered in **every** process role that needs it | Initialization only in `main.py`'s FastAPI lifespan |
| Fail loudly, or report the gap to the user | Log a warning and continue silently degraded |

Reference implementations: `WorkspaceBackend` (MinIO truth + write-through cache) and `SkillStore`
(content-addressed objects + local materialization) in `bisheng/linsight/domain/services/`.

Precedents that make this a law rather than advice: skill bundles shipped as node-local files and
were unreadable from any other host (fixed by moving them to object storage); the F048 resource
registry was installed only in the API process and had to be retrofitted into the background
workers (`02cbb921a`). Both failed **silently** — which is the real cost, and why the last row of
the table matters as much as the first.
