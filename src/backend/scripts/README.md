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
