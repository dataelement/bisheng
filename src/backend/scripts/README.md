# Script Directory

This directory contains manual maintenance and migration scripts for the backend.

## Export Scripts

### `export_daily_chat_messages.py`

Export 日常模式（`flow_type = 15`）对话内容，默认导出最近 30 天消息并按会话聚合为 JSON。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/export_daily_chat_messages.py
PYTHONPATH=./ .venv/bin/python scripts/export_daily_chat_messages.py --days 7
PYTHONPATH=./ .venv/bin/python scripts/export_daily_chat_messages.py --format csv
PYTHONPATH=./ .venv/bin/python scripts/export_daily_chat_messages.py --tenant-id 3
PYTHONPATH=./ .venv/bin/python scripts/export_daily_chat_messages.py --full-session
```

Options:

- `--config`: 指定配置文件，默认取环境变量 `config`，否则使用 `config.yaml`
- `--days`: 最近多少天，默认 `30`
- `--format`: `json` 或 `csv`
- `--tenant-id`: 仅导出指定租户
- `--user-id`: 仅导出指定用户
- `--chat-id`: 仅导出指定会话
- `--include-deleted`: 包含已删除会话
- `--full-session`: 只要会话在时间窗口内活跃，就导出该会话的全部消息

## Permission Scripts

### `migrate_workstation_models_to_workbench.py`

One-off migration for moving the legacy daily-workbench model list from the
global `config.key = "workstation"` row into the default tenant's
`tenant_system_model_config.key = "linsight_llm"` row.

Behavior:

- reads `workstation.models` from `config`
- writes only to default tenant `tenant_id = 1`
- if Root already has `linsight_llm`, merges by updating only `models`
- if Root does not have `linsight_llm`, creates a new row
- preserves legacy `workstation.models`; later UI save flows can handle cleanup/overwrite

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/migrate_workstation_models_to_workbench.py
PYTHONPATH=./ .venv/bin/python scripts/migrate_workstation_models_to_workbench.py --apply

bash scripts/migrate_workstation_models_to_workbench.sh
bash scripts/migrate_workstation_models_to_workbench.sh apply
```

Options:

- `--apply`: perform writes; default is dry-run

### `migrate_channel_permissions_for_relation_models.py`

Backfills channel-module default permissions into legacy **custom** relation
models (资源权限模板) that were created before the channel module existed.

Behavior:

- reads the global `config.key = "permission_relation_models_v1"` JSON list
- for each custom (`is_system = false`) model with **no** channel permission ids,
  appends the channel defaults for its inherited level
  (`owner` / `manager` / `editor` / `viewer`), sourced from
  `channel_permission_template.default_permission_ids_for_relation`
- skips system models (they compute channel defaults from the template at runtime)
- skips custom models that already hold any channel permission id (never
  overwrites an admin's explicit channel customization)
- preserves all non-channel permissions

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/migrate_channel_permissions_for_relation_models.py
PYTHONPATH=./ .venv/bin/python scripts/migrate_channel_permissions_for_relation_models.py --apply

bash scripts/migrate_channel_permissions_for_relation_models.sh
bash scripts/migrate_channel_permissions_for_relation_models.sh apply
```

Options:

- `--apply`: perform writes; default is dry-run

### `backfill_relation_model_move_permissions.py`

Backfills the F034 permissions `move_file` / `move_folder` into **frozen system**
relation tiers (所有者 / 可管理 / 可编辑) whose checkbox snapshot was frozen
before those permissions existed.

> **Usually you don't need to run this.** The same idempotent backfill runs
> automatically on every backend startup (wired into `main.py` lifespan), so a
> normal upgrade + restart self-heals. This standalone script exists only for
> fixing an environment without a restart, or for inspecting the change first.

Behavior:

- reads the global `config.key = "permission_relation_models_v1"` JSON list
- for each **system** (`is_system = true`) model with `permissions_explicit = true`,
  unions in `{move_file, move_folder} ∩ default_permission_ids_for_relation(relation)`
  — owner/manager/editor get both, viewer gets none
- skips dynamic (`permissions_explicit = false`) models — they already compute
  the new permissions from the template at runtime
- skips custom (`is_system = false`) models; preserves all other permissions
- idempotent: once aligned, re-runs are no-ops

Usage (from `src/backend/`):

```bash
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_relation_model_move_permissions.py
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_relation_model_move_permissions.py --apply
```

Options:

- `--apply`: perform writes; default is dry-run

### `backfill_channel_member_rebac_grants.py`

Repairs **already-active** channel subscribers that were activated before commit
`c530bf375` and therefore never got a ReBAC grant written. The 成员管理 /
authorization list is rendered from OpenFGA tuples, so such members are active in
`space_channel_member` but invisible in the list.

Behavior:

- scans channels (all, or one via `--channel-id`) for `status = ACTIVE`,
  non-`CREATOR`, **direct** (`grant_subject_type` in `NULL` / `self`) members
- for each member with **no** existing FGA grant on the channel, writes the
  viewer/manager grant + relation-model binding via
  `ChannelService.sync_direct_channel_user_permissions` (idempotent)
- skips the creator (owner is managed by `OwnerService`), `PENDING` / `REJECTED`
  members, organisation-granted members, and members already present in FGA

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/backfill_channel_member_rebac_grants.py
PYTHONPATH=./ .venv/bin/python scripts/backfill_channel_member_rebac_grants.py --apply
PYTHONPATH=./ .venv/bin/python scripts/backfill_channel_member_rebac_grants.py --channel-id <id> --apply

bash scripts/backfill_channel_member_rebac_grants.sh
bash scripts/backfill_channel_member_rebac_grants.sh apply
bash scripts/backfill_channel_member_rebac_grants.sh --channel-id <id> apply
```

Options:

- `--channel-id <id>`: restrict to a single channel; default is all channels
- `--apply`: perform writes; default is dry-run

### `clean_department_space_user_group_grants.py`

One-off F033 cleanup. Department knowledge spaces no longer allow the **user-group**
authorization dimension (the API rejects new user_group grants; the client hides
the tab). This removes any historical user_group grant on a department space —
revokes the OpenFGA tuple and drops the relation-model binding. Runtime code keeps
no compatibility path for these grants.

Behavior:

- scans every department knowledge space (`DepartmentKnowledgeSpaceDao.aget_all`)
- reports each `user_group` grant as `(space_id, group_id, relation, affected_users)`
- with `--apply`, revokes the grant via `PermissionService.authorize` + removes the binding
- only touches department spaces' `user_group` grants — never normal spaces, never user/department grants

Usage:

```bash
export config=config.yaml
PYTHONPATH=./ .venv/bin/python scripts/clean_department_space_user_group_grants.py            # dry-run
PYTHONPATH=./ .venv/bin/python scripts/clean_department_space_user_group_grants.py --apply    # execute
```

Options:

- `--apply`: perform the revokes; default is dry-run. Irreversible (revokes group members' access) — review dry-run output first.

### `permission_migration.sh`

Manual runner for the F006 historical permission migration from RBAC to ReBAC.

Usage:

```bash
bash bisheng/script/permission_migration.sh
bash bisheng/script/permission_migration.sh dry_run
bash bisheng/script/permission_migration.sh verify
bash bisheng/script/permission_migration.sh replay
bash bisheng/script/permission_migration.sh replay 3
```

Modes:

- `execute`: run migration normally
- `dry_run`: preview migration statistics only
- `verify`: compare old RBAC and new ReBAC permission results
- `replay`: force replay from the specified step, ignoring previous completion state and clearing checkpoint
- `force`: same behavior as `replay`, kept for compatibility

Step map:

- `1`: Super Admin
- `2`: User Group Membership
- `3`: Role Access Expansion
- `4`: Space/Channel Members
- `5`: Resource Owners
- `6`: Folder Hierarchy
- `7`: Department Membership
- `8`: Group Resources

### `reconcile_permission_migration_db.py`

Business-level database reconciliation for the F006 RBAC -> ReBAC migration.

This script does not replay the migration implementation. Instead, it rebuilds
expected tuples directly from business tables such as `userrole`,
`roleaccess`, `space_channel_member`, `knowledgefile`, `user_department`, and
`groupresource`, then compares them with rows in the OpenFGA datastore's
`tuple` table.

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/reconcile_permission_migration_db.py \
  --tuple-db-url "mysql+pymysql://user:pass@host:3306/openfga" \
  --step 1

PYTHONPATH=./ .venv/bin/python scripts/reconcile_permission_migration_db.py \
  --tuple-db-url "mysql+pymysql://user:pass@host:3306/openfga" \
  --step 3 --apply
```

Options:

- `--tuple-db-url`: SQLAlchemy URL of the OpenFGA datastore
- `--store-id`: optional OpenFGA store id; auto-resolved when omitted
- `--step`: check exactly step `N` (`1` to `8`)
- `--apply`: apply writes/deletes through OpenFGA API after diffing
- `--sample-limit`: how many sample tuple diffs to print

### `reconcile_permission_migration_db.sh`

Shell wrapper for step-specific database-level reconciliation.

Usage:

```bash
bash scripts/reconcile_permission_migration_db.sh check 1 "mysql+pymysql://user:pass@host:3306/openfga"
bash scripts/reconcile_permission_migration_db.sh apply 3 "mysql+pymysql://user:pass@host:3306/openfga"
```

Arguments:

- arg1: `check` or `apply`
- arg2: step number (`1` to `8`)
- arg3: OpenFGA tuple DB URL

The 3rd argument can be omitted if one of these environment variables is set:

- `OPENFGA_TUPLE_DB_URL`
- `OPENFGA_DATASTORE_URL`
- `OPENFGA_DATASTORE_URI`

## Linsight Scripts (F035)

### `migrate_sop_to_skill.sh` / `migrate_sop_to_skill.py`

> **Upgrade-required (< v2.6 → v2.6, F035 step 4 of 4) — MANUAL.** Run after
> `alembic upgrade head`. Unlike the F035 menu/model backfills (steps 2/3, which
> auto-run at startup), this SOP→Skill data migration is **not** auto-run — it
> writes object storage and is heavier, so it stays a manual ops script. Part of
> the F035 upgrade checklist — see `docs/architecture/08-deployment.md` → 升级 checklist.

One-shot migration of legacy `linsight_sop` rows into tenant custom skills
(`linsight_skill` + `SKILLS_ROOT/data/skills/{tenant_id}/<name>/SKILL.md`).
`display_name` keeps the original (Chinese) SOP name; the skill ID is a
pypinyin slug; `metadata.sop-id` makes re-runs idempotent. The skill description
uses the SOP's own description, falling back to the SOP name when absent (no LLM
call — a skill description is mandatory and can never be blank). Prints and writes
a JSON migration summary (ops artifact — there is no in-product migration report).

Usage (from `src/backend/`, dry-run by default):

```bash
bash scripts/migrate_sop_to_skill.sh                       # dry-run, all tenants
bash scripts/migrate_sop_to_skill.sh apply                 # persist
bash scripts/migrate_sop_to_skill.sh --tenant-id 2 apply   # single tenant
```

Options: `--apply` (persist), `--tenant-id <id>`,
`--report-file <path>` (default `./migrate_sop_to_skill_report.json`).

### `backfill_linsight_task_mode_web_menu.py`

> **F035 step 3 of 4 — AUTO at startup.** Runs automatically on service startup
> (`main.lifespan`, idempotent, failure never blocks boot); shared logic in
> `bisheng/permission/domain/linsight_task_mode_menu_backfill.py`. This CLI is only
> for a manual re-run or dry-run preview. See `docs/architecture/08-deployment.md` → 升级 checklist.

Grants WEB_MENU `linsight_task_mode` to every role that already has `home`.
F035 split 任务模式 (`/linsight`) out of the shared `home` menu permission into
its own sub-toggle; without this backfill, upgraded deployments would lose
任务模式 access for existing roles (the route guard now checks
`linsight_task_mode`). Idempotent & re-runnable; dry-run by default.

Usage (from `src/backend/`):

```bash
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_linsight_task_mode_web_menu.py            # dry-run
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_linsight_task_mode_web_menu.py --apply    # write
```

### `migrate_linsight_task_model_to_default.py`

> **F035 step 2 of 4 — AUTO at startup.** Runs automatically on service startup
> (`main.lifespan`, idempotent, failure never blocks boot); shared logic in
> `bisheng/llm/domain/services/linsight_default_model_backfill.py`. This CLI is only
> for a manual re-run or dry-run preview. See `docs/architecture/08-deployment.md` → 升级 checklist.

F035 Track E (deepagents). Rewrites every tenant's `linsight_llm` config row in
`tenant_system_model_config`: drops the legacy `task_model` / `linsight_executor_mode`
keys and sets the new single `linsight_default_model_id` (keeps the old
`task_model.id` when it still exists in the row's `models` list, otherwise falls
back to the first model id, or empty when `models` is empty). JSON is parsed in
Python (no `JSON_EXTRACT`) for DM8/MySQL compatibility. Idempotent (rows without
`task_model` are skipped) & re-runnable; dry-run by default.

Usage (from `src/backend/`):

```bash
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/migrate_linsight_task_model_to_default.py            # dry-run
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/migrate_linsight_task_model_to_default.py --apply    # write
```

### `seed_overflow_skill.py`

> **Dev/QA fixture — NOT part of any upgrade checklist.** Seeds ONE throwaway
> "overflow QA" skill whose fields are pushed to their limits so the skill-detail
> drawer (`SkillDetailSheet.tsx`, 2026-06-16 overflow hardening, Track I) can be
> eyeballed. Idempotent (re-run replaces the same skill); `--remove` deletes it.

Inserts a skill into the target tenant (default 1) with `display_name`=255 chars,
`name`=64 chars, `description`=1024 chars (no spaces), a SKILL.md body carrying a
400-char unbroken token, and a long-named bundle asset — covering all four
overflow points (title / ID chip / description / preview) plus the file tree.
Manual-verification checklist: `features/v2.6.0/035-linsight-task-mode/tasks.md` → TI-1.

Usage (from `src/backend/`):

```bash
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/seed_overflow_skill.py            # dry-run
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/seed_overflow_skill.py --apply    # create
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/seed_overflow_skill.py --remove   # clean up
```

## Tenant / Data Fix Scripts

### `dedupe_gpts_tools.py`

清理同一租户下 `(tool_key, tenant_id)` 重复的**预置**工具 / 工具类型行。历史上"复制内置工具到子租户"未显式带 `tenant_id`，在 root 上下文下被 `server_default=1` 盖成 root，加上 `t_gpts_tools.tool_key` 当时没有唯一约束，导致 root 下同一 `tool_key` 堆了多份（如 `web_search` ×3）。这会让 `get_tool_by_tool_key().first()` 解析到非预期的那条（工作流读到旧配置），也会阻止后续添加 `UNIQUE(tool_key, tenant_id)` 约束。

行为：每组保留最小 id 为 canonical，重定向 `assistantlink.tool_id`、`t_gpts_tools.type` 到 canonical，硬删 stray 行。非预置（自定义 API/MCP）重复**只报告不删除**。工作台配置 JSON / OpenFGA 中对 stray id 的引用也只报告，需人工跟进。

Usage (from `src/backend/`，**apply 前先备份数据库**):

```bash
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/dedupe_gpts_tools.py           # dry-run（默认，不写库）
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/dedupe_gpts_tools.py --apply    # 执行清理（硬删 + 重定向引用）
```

apply 干净后再手动加约束：

```sql
ALTER TABLE t_gpts_tools ADD CONSTRAINT uk_gpts_tools_key_tenant UNIQUE (tool_key, tenant_id);
```

### `backfill_knowledge_space_user_pin.py`

F037：知识空间置顶从 `space_channel_member.is_pinned` 解耦到独立的 `knowledge_space_user_pin` 表（置顶是纯个人偏好，不再寄生在成员关系上）。本脚本把历史置顶迁移到新表，让升级后用户保留已置顶的空间。

来源行：`space_channel_member` 中 `business_type='space'` 且 `is_pinned` 为真且 `status='ACTIVE'`，每条转成 `knowledge_space_user_pin(user_id, space_id=business_id)`。幂等：已存在的 `(user_id, space_id)` 跳过，可重复运行。

> 前置：先 `alembic upgrade head`（建好 `knowledge_space_user_pin` 表，迁移 `f044_knowledge_space_user_pin`）。

Usage (from `src/backend/`):

```bash
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_space_user_pin.py            # dry-run（默认，不写库）
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_space_user_pin.py --apply    # 写入

# 或用 shell 包装（自动探测解释器 / PYTHONPATH / config）：
bash scripts/backfill_knowledge_space_user_pin.sh          # dry-run
bash scripts/backfill_knowledge_space_user_pin.sh apply    # 写入
```

### `backfill_user_tenant_associations.py`

把缺失/未激活的默认租户归属回填到 `user_tenant` 表。这段逻辑原先挂在服务启动流程 `init_default_data()` 的 `_init_default_tenant` 里，每次进程启动都会全表扫描 `users`/`user_tenant`（一次反连接 + 一次"把全部 `is_active=1` 行读进内存"），在大用户量部署下属于把数据维护塞进了热路径。已从启动流剥离——启动只保证默认租户(id=1)存在。

运行期不依赖这张回填表：`UserPayload` 租户解析在用户无 `user_tenant` 行时回退到 `DEFAULT_TENANT_ID`，多租户登录还会惰性补挂，故缺行不会阻塞登录/查询，本回填是纯数据一致性维护，按需运行一次即可。

做什么（两步，与原启动逻辑等价、幂等）：①对没有任何 `user_tenant` 行的用户插入默认租户行 `(tenant_id=1, is_default=1, is_active=1, status='active')`；②对 `tenant_id=1 / is_default=1 / status='active' / is_active IS NULL` 且该用户当前无任何 `is_active=1` 行的孤儿默认行，置 `is_active=1`（每用户只激活一条）。只新增/激活，不删除、不 demote。

Usage (from `src/backend/`):

```bash
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_user_tenant_associations.py            # dry-run（默认，不写库）
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_user_tenant_associations.py --apply    # 写入

# 或用 shell 包装（自动探测解释器 / PYTHONPATH / config）：
bash scripts/backfill_user_tenant_associations.sh          # dry-run
bash scripts/backfill_user_tenant_associations.sh apply    # 写入
```

### `backfill_departments_under_single_root.py`

把所有"误挂为根"的部门收编到默认组织根部门(`BS@root`)下，保证全平台只有一个根部门。

背景：历史上 SSO 网关同步的顶层部门(`parent_external_id` 为空)被挂为 `parent_id=None`，变成与"默认组织"平级的兄弟根，导致出现多个根、且其 `path` 不以默认组织根 path 为前缀(按 `path LIKE '{root_path}%'` 圈定租户成员时被漏算)。同步逻辑已修复(顶层部门改挂默认组织根下)，但增量推送未重推的存量部门需本脚本一次性收编。

做什么：默认租户下、除默认组织根外的所有 active 根部门(`parent_id IS NULL`)，设 `parent_id=默认组织根.id` 并级联重写整棵子树 `path`。不区分 source，不触碰挂载状态。幂等：收编后 `parent_id` 不再为空，重复运行被自然跳过。

Usage (from `src/backend/`):

```bash
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_departments_under_single_root.py            # dry-run（默认，不写库）
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_departments_under_single_root.py --apply    # 写入

# 或用 shell 包装（自动探测解释器 / PYTHONPATH / config）：
bash scripts/backfill_departments_under_single_root.sh          # dry-run
bash scripts/backfill_departments_under_single_root.sh apply    # 写入
```

### `backfill_user_tenant_associations.py`

把缺失/未激活的默认租户归属回填到 `user_tenant` 表。这段逻辑原先挂在服务启动流程 `init_default_data()` 的 `_init_default_tenant` 里，每次进程启动都会全表扫描 `users`/`user_tenant`（一次反连接 + 一次"把全部 `is_active=1` 行读进内存"），在大用户量部署下属于把数据维护塞进了热路径。已从启动流剥离——启动只保证默认租户(id=1)存在。

运行期不依赖这张回填表：`UserPayload` 租户解析在用户无 `user_tenant` 行时回退到 `DEFAULT_TENANT_ID`，多租户登录还会惰性补挂，故缺行不会阻塞登录/查询，本回填是纯数据一致性维护，按需运行一次即可。

做什么（两步，与原启动逻辑等价、幂等）：①对没有任何 `user_tenant` 行的用户插入默认租户行 `(tenant_id=1, is_default=1, is_active=1, status='active')`；②对 `tenant_id=1 / is_default=1 / status='active' / is_active IS NULL` 且该用户当前无任何 `is_active=1` 行的孤儿默认行，置 `is_active=1`（每用户只激活一条）。只新增/激活，不删除、不 demote。

Usage (from `src/backend/`):

```bash
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_user_tenant_associations.py            # dry-run（默认，不写库）
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_user_tenant_associations.py --apply    # 写入

# 或用 shell 包装（自动探测解释器 / PYTHONPATH / config）：
bash scripts/backfill_user_tenant_associations.sh          # dry-run
bash scripts/backfill_user_tenant_associations.sh apply    # 写入
```

### `backfill_department_parent_tuples.py`

把 DB 部门树的父子关系回填成 OpenFGA 的 `department#parent` 继承边（additive，只加不删，幂等）。

背景：写 `department:{parent}#parent@department:{child}` 边的只有 F002 手动建/移部门；SSO 同步及早期 f006 迁移进来的部门在 FGA 里没有这条边，导致部门 admin 的 FGA 继承对其失效。SSO 同步链路已修复为实时维护 parent 边，本脚本按 DB 当前树形一次性补齐**存量**部门的边。

遍历所有 `status='active'` 且 `parent_id` 非空的部门（全租户、全来源），每个发一条 `write department:{parent_id}#parent department:{id}`。`batch_write_tuples` 对重复写幂等，可反复跑。

> 运行顺序：在 `backfill_departments_under_single_root.py`（定型 parent_id）**之后**运行，会一并补上被收编部门的 root→顶层 边。

Usage (from `src/backend/`):

```bash
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_department_parent_tuples.py            # dry-run（默认）
config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_department_parent_tuples.py --apply     # 写入

# 或用 shell 包装（自动探测解释器 / PYTHONPATH / config）：
bash scripts/backfill_department_parent_tuples.sh          # dry-run
bash scripts/backfill_department_parent_tuples.sh apply    # 写入
```

### `seed_load_test_org.py`

压测数据脚本：批量生成**部门树 + 用户**灌入数据库，用于大用户量下的体验/性能测试（尤其 ReBAC 读路径）。

在平台默认根部门（`Tenant.root_dept_id`）下按 `--fanout` 广度优先生成 `--departments` 个部门（自动维护物化 `path` 与 `department#parent` FGA 边），再生成 `--users` 个本地用户轮询分配主部门（`is_primary=1`，可选 `--secondary-ratio` 挂附属部门），每人写 user + 默认角色 + user_department + user_tenant 及 `department#member` FGA 边。

所有数据打 `source=<--source>`（默认 `loadtest`）标签 + `external_id=loadtest_dept_*/loadtest_user_*`，因此**幂等**且可用 `--purge` 一键清理。统一密码 `Test@1234ab`。

> 干跑是默认行为，`--apply` 才写库/写 FGA/删数据。默认写 OpenFGA；`--no-fga` 只灌库。`--with-role-fga` 才逐用户同步默认角色到 FGA（慢）。

Usage (from `src/backend/`):

```bash
config=config.yaml PYTHONPATH=./ python scripts/seed_load_test_org.py --departments 200 --users 50000 --fanout 8             # dry-run（默认）
config=config.yaml PYTHONPATH=./ python scripts/seed_load_test_org.py --departments 200 --users 50000 --fanout 8 --apply      # 写入 DB + FGA
config=config.yaml PYTHONPATH=./ python scripts/seed_load_test_org.py --departments 200 --users 50000 --apply --no-fga        # 只灌库
config=config.yaml PYTHONPATH=./ python scripts/seed_load_test_org.py --purge --apply                                        # 清理压测数据

# 或用 shell 包装（自动探测解释器 / PYTHONPATH / config）：
bash scripts/seed_load_test_org.sh --departments 200 --users 50000 --apply
```
