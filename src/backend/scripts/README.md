# Script Directory

This directory contains manual maintenance and migration scripts for the backend.

## Knowledge Space Scripts

### `backfill_file_similarity_candidates.py`

回填历史知识空间文件的相似候选缓存表 `knowledge_file_similarity_candidate`。默认 dry-run，只统计将刷新的文件；传入 `--apply` 后会逐个调用相似候选刷新逻辑，写入候选明细并同步更新 `knowledgefile.similar_status`。可通过 `--sleep-ms` 降低回填期间 CPU 压力。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py --apply
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py --apply --knowledge-id 3516
PYTHONPATH=./ .venv/bin/python scripts/backfill_file_similarity_candidates.py --apply --limit 200 --batch-size 20 --sleep-ms 100
```

Scope:

- 仅处理知识空间 `Knowledge.type = SPACE`
- 仅处理真实文件、解析成功、未处理完成的文件：`file_type = FILE`、`status = SUCCESS`、`similar_status != 2`
- 跳过没有有效 `simhash` 或没有有效前三段 `file_encoding` 的文件

### `reparse_knowledge_space_files.py`

重新解析知识空间文件。默认 dry-run，只统计将处理的文件；传入 `--apply` 后会直接在脚本进程内执行解析，默认单并发，可通过 `--concurrency` 调整。每个文件重解析前只清理该文件在 Milvus 和 Elasticsearch 中的旧索引，不删除 MinIO 原文件或预览产物。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --concurrency 4
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --space-id 10 --folder-id 20
PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --file-id 101 --file-id 102

bash scripts/reparse_knowledge_space_files.sh
bash scripts/reparse_knowledge_space_files.sh --apply --concurrency 4
```

Scope:

- 不传范围参数：处理所有知识空间中的真实文件
- `--space-id`：包含指定知识空间下的所有真实文件，可重复传入
- `--folder-id`：递归包含指定文件夹下所有层级的真实文件，可重复传入
- `--file-id`：包含指定真实文件，可重复传入
- 仅处理 `SUCCESS` / `FAILED` / `TIMEOUT` / `VIOLATION` 状态，跳过 `WAITING` / `PROCESSING` / `REBUILDING`

## Export Scripts

### `get_knowledge_file_chunks.py`

按 `knowledge_file_id` 查询一个知识文件在 Elasticsearch 中的全部 chunk，并将文本和元数据以 JSON 输出到标准输出。脚本只读，不会修改数据库或索引。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/get_knowledge_file_chunks.py --knowledge-file-id 123
```

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

## Expert QA Scripts

### `delete_qa_expert_question.py`

按专家问答问题 ID 删除 `qa_question` 及关联的回答、评论 / 追问、问题投票、回答投票、评论投票和通知。

默认 dry-run，只输出影响范围；执行写入必须显式传入 `--apply`。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/delete_qa_expert_question.py 123
PYTHONPATH=./ .venv/bin/python scripts/delete_qa_expert_question.py 123 --apply

bash scripts/delete_qa_expert_question.sh 123
bash scripts/delete_qa_expert_question.sh 123 --apply
```

Scope:

- `qa_question`
- `qa_answer`
- `qa_comment`
- `qa_question_vote`
- `qa_answer_vote`
- `qa_comment_vote`
- `qa_notification`

## Permission Scripts

### `reconcile_department_member_tuples.py`

根据业务库 `user_department` 全量核对 OpenFGA 的
`user:<id> member department:<id>` 关系，并补齐缺失 tuple。默认 dry-run，
不会写入数据库、Redis 或 OpenFGA；仅传入 `--apply` 时才向 OpenFGA 新增缺失
tuple。脚本不会删除已有业务关系或 OpenFGA tuple。

Usage:

```bash
# 全量预检，只输出缺失统计和样例
bash scripts/reconcile_department_member_tuples.sh

# 先在指定部门验证
bash scripts/reconcile_department_member_tuples.sh --department-id 190

# 确认预检结果后，全量补齐缺失关系
bash scripts/reconcile_department_member_tuples.sh --apply
```

Options:

- `--apply`：执行写入；不传时为只读预检。
- `--department-id <ID>`：可重复传入，仅处理指定部门。
- `--batch-size <N>`：每页读取的 `user_department` 记录数，默认 `500`。
- `--sample-limit <N>`：JSON 中保留的缺失样例数，默认 `20`。

### `diagnose_department_space_access.py`

只读诊断“用户通过部门授权后无法在门户首页看到知识空间”的权限链路。输出 JSON，包含业务数据库中的用户部门归属、目标空间绑定/成员信息、OpenFGA 资源授权 tuple、用户部门 `member` tuple、`check` 与 `list_objects` 结果，以及自动判定的断点。不会写入数据库、Redis 或 OpenFGA。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/diagnose_department_space_access.py \
  --user-id 123 --space-id 3569

bash scripts/diagnose_department_space_access.sh \
  --user-id 123 --space-id 3569
```

Exit codes:

- `0`：诊断完成；输出中的 `findings` 可能仍包含权限缺失结论。
- `2`：用户或知识空间不存在，或参数无效。
- `3`：OpenFGA 未启用、缺少只读连接所需的 store/model 配置，或查询失败。

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

### `reset_admin_only_knowledge_permissions.py`

高风险权限重置脚本：校验唯一可用 `admin` 用户后，将非 admin 用户收敛为普通用户，撤销非 admin 的租户/部门/用户组/个人菜单管理授权；删除知识空间、文件夹、文件的非 admin 资源授权，并把创建者和 owner 权限重置到 admin。

默认 dry-run，只输出影响范围；执行写入必须显式传入 `--apply`。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/reset_admin_only_knowledge_permissions.py
PYTHONPATH=./ .venv/bin/python scripts/reset_admin_only_knowledge_permissions.py --json
PYTHONPATH=./ .venv/bin/python scripts/reset_admin_only_knowledge_permissions.py --apply

bash scripts/reset_admin_only_knowledge_permissions.sh
bash scripts/reset_admin_only_knowledge_permissions.sh --apply
```

Scope:

- 用户角色：非 admin 删除非普通角色，缺少普通角色时补 `DefaultRole`
- 管理授权：非 admin 的租户管理员、部门管理员、用户组管理员、个人菜单授权
- 知识空间资源：`knowledge_space`、`folder`、`knowledge_file` 的 OpenFGA 资源授权
- 知识空间数据：`knowledge.user_id`、`knowledgefile.user_id/updater_id`、空间成员
- 知识空间类型：保留 `knowledge_space_scope.level/owner_type/owner_id` 和 `department_knowledge_space` 绑定，不把团队、部门、公共知识库改成个人知识库
- 分享链接：失效所有 `knowledge_space_file` active 链接
- 重试队列：失效受影响资源和非 admin 管理授权相关的 pending `failed_tuple`

Failure handling:

- `--apply` 会先提交数据库收敛结果，并在同一事务中为本次 OpenFGA 操作预写 pending `failed_tuple`。
- 如果 OpenFGA 写入失败，脚本会以非 0 退出；此时数据库变更已经提交，预写的 `failed_tuple` 会保持 pending。运维必须先处理 retry 队列或重新执行 `--apply`，确认 OpenFGA 旧权限已清除后，才能认为重置完成。
- 如果脚本输出 OpenFGA 不可用，`--apply` 会在写数据库前中止。
- 如果 `permission_relation_model_bindings_v1` 配置不是合法 JSON list，脚本会中止，避免把损坏配置覆盖为空。

## Destructive Department Scripts

### `purge_department_subtree.py`

按业务 `dept_id` 物理删除指定部门及其全部子孙部门，并物理删除子树成员用户。脚本会将受支持的资源转移给指定管理员，清理 Linsight 用户记录和账号/部门权限关联；聊天、审计与渠道历史不主动删除。

默认是 dry-run，只输出部门、用户、资产和权限影响面。必须显式传入 `--apply` 才会执行不可逆写入。

Usage:

```bash
PYTHONPATH=./ .venv/bin/python scripts/purge_department_subtree.py \
  --dept-id BS@example \
  --transfer-to-user-id 1

PYTHONPATH=./ .venv/bin/python scripts/purge_department_subtree.py \
  --dept-id BS@example \
  --transfer-to-user-id 1 \
  --apply

bash scripts/purge_department_subtree.sh \
  --dept-id BS@example \
  --transfer-to-user-id 1
```

Safety:

- `BS@guest`、租户挂载根节点和不合法的资产接收人会使整次操作在写入前中止。
- 外部同步账号可能在下一轮组织同步时被重新创建；脚本不会修改外部身份源或同步配置。
- OpenFGA 失败会由 `failed_tuple` 补偿机制重试；执行摘要只报告已提交的权限清理操作。
- `--apply` 不可恢复，务必先保存 dry-run 输出并在维护窗口执行。

## Organization Migration Scripts

### `migrate_root_departments_under_default_org.py`

把默认租户中除 `tenant.root_dept_id` 指向节点以外的其他数据库根部门，整体迁移到默认组织下。迁移会级联更新整个部门子树的 `path`，并为 active 根部门补充 OpenFGA `parent` 关系；部门 ID、成员、管理员和知识空间绑定均保持不变。

默认只输出 JSON 迁移计划，不写数据库或 OpenFGA。确认后必须显式传入 `--apply`：

```bash
PYTHONPATH=./ .venv/bin/python scripts/migrate_root_departments_under_default_org.py
PYTHONPATH=./ .venv/bin/python scripts/migrate_root_departments_under_default_org.py --apply
```

Safety:

- 默认组织通过 `tenant.root_dept_id` 识别，不依赖名称或查询顺序。
- 执行前会校验默认组织和所有待迁移根部门的物化路径；检测到异常即停止。
- `--apply` 会再次校验待迁移部门仍是根节点且路径未变化，避免使用过期 dry-run 计划。
- 数据库提交后通过 `DepartmentChangeHandler` 写入 OpenFGA，失败操作进入现有 `failed_tuple` 补偿机制。

### `migrate_admin_to_department.py`

将一个明确指定的 admin 账号迁移到指定部门。默认 dry-run；`--apply` 会修改主部门和叶子租户，但保留 admin 在原叶子租户中拥有的资源。

每次必须且只能提供一种账号定位方式，以及一种目标部门定位方式。

Usage:

```bash
# 默认预览，不写入
PYTHONPATH=./ .venv/bin/python scripts/migrate_admin_to_department.py \
  --username admin \
  --dept-id BS@example

# 显式执行
PYTHONPATH=./ .venv/bin/python scripts/migrate_admin_to_department.py \
  --user-id 10 \
  --department-id 42 \
  --apply

bash scripts/migrate_admin_to_department.sh \
  --username admin \
  --dept-id BS@example
```

Safety:

- `--user-id` / `--username` 与 `--department-id` / `--dept-id` 均为必须二选一的参数组；用户名采用精确匹配。
- 不接受 `--transfer-to-user-id`，也不会修改任何资源 owner 或资源内容。
- 跨租户迁移仅由该脚本绕过资源阻断；不会修改全局 `enforce_transfer_before_relocate` 配置。
- `--apply` 会改变主部门与叶子租户。脚本不会修改管理员角色、账号状态、密码或其他次级部门关系；OpenFGA 同步遵循现有 `FailedTuple` 补偿机制。
