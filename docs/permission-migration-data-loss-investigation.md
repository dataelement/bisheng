# 权限迁移与数据丢失排查结论

日期：2026-04-27

## 结论

当前“丢了不少书籍”的主要表现更像是权限迁移后资源不可见，而不是 F006 权限迁移脚本批量删除了 MySQL 中的知识库或知识文件。

109 服务器上，`knowledge` 表没有发现备份后被删除的记录；`knowledgefile` 表只确认有 1 条备份中存在、当前库缺失的历史记录：`id=176 / PDF_TestPage.pdf / knowledge_id=49`。该记录在 `2026-04-21 14:57:12` 被删除，早于 F006 权限迁移执行时间。

权限层面存在明确问题：OpenFGA failed_tuple 队列中有知识空间相关的失败写入，集中在把 `department:X#member` 写成 `knowledge_space#owner`，OpenFGA 模型拒绝该 tuple。这类问题会造成资源仍在数据库中，但用户或部门看不到。

## 已确认的迁移执行记录

### 109 服务器

F006 在后端启动过程中自动触发，不是从 shell 手动执行。

- 执行时间：`2026-04-25 15:27:05`
- checkpoint：`completed_step = 8`
- checkpoint 时间：`2026-04-25T15:27:11.106508`
- 统计：
  - Step 1 super_admin：3
  - Step 2 user_group：16
  - Step 3 role_access：0
  - Step 4 space_channel_member：115
  - Step 5 resource owners：126
  - Step 6 folder hierarchy：220
  - Step 7 user_department：22
  - Step 8 groupresource：137
- 当前 Alembic 版本：`f032_workbench_subscription_web_menu_backfill`

### 114 服务器

114 上存在分阶段执行记录。

- `2026-04-22 19:55:50`：旧版本 F006 跑到 Step 6，写入 124 tuples
- `2026-04-25 15:10:59`：checkpoint 显示 Step 8 完成
- 当前 Alembic 版本：`f030_tenant_root_dept_id_backfill`

## MySQL 数据对账结果

### 109：4/21 备份 vs 当前库

备份文件：`/data/bisheng-mysql-recovery-20260421-113612.sql.gz`

`knowledge`：

- 备份：29 条，ID 范围 `1..50`
- 当前：49 条，ID 范围 `1..70`
- 备份中存在但当前缺失：0 条

`knowledgefile`：

- 备份：201 条，ID 范围 `1..244`
- 当前：221 条，ID 范围 `1..270`
- 备份中存在但当前缺失：1 条

缺失记录：

```text
id=176
knowledge_id=49
file_name=PDF_TestPage.pdf
status=3
object_name=original/176.pdf
create_time=2026-04-20 19:27:14
```

### 109：binlog 删除记录

检查窗口：`2026-04-21 11:36:12` 到 `2026-04-27 23:59:59`

- `knowledge` DELETE：0
- `knowledgefile` DELETE：6

6 条 `knowledgefile` DELETE 中，只有 `id=176` 是备份已有且当前缺失的记录；其余为备份后新建又删除的文件。`id=176` 的删除时间是 `2026-04-21 14:57:12`，早于 F006 在 `2026-04-25` 的执行时间。

`2026-04-24` 之后没有发现 `knowledge` 或 `knowledgefile` 的 DELETE。

### 114：binlog 检查

检查窗口：`2026-04-22 00:00:00` 到 `2026-04-27 23:59:59`

- `knowledge` DELETE：0
- `knowledgefile` DELETE：0

114 未找到可用于做 ID 级对账的 SQL 备份文件。

## 权限层问题

### 109 failed_tuple

当前 `failed_tuple` 状态：

- `succeeded`：241
- `dead`：41

dead 记录集中在：

- `owner -> knowledge_space:53`
- `owner -> knowledge_space:55`
- `owner -> knowledge_space:59`

错误类型：

```text
department:X#member is not an allowed type restriction for knowledge_space#owner
```

这说明迁移或后续权限写入曾尝试把部门成员关系写成知识空间 owner。该 tuple 不符合 OpenFGA authorization model，因此无法写入。结果是相关知识空间可能在 MySQL 中存在，但部门/用户侧不可见或权限不完整。

涉及的知识空间包括：

- `knowledge_space:53`：`yifeitest2`
- `knowledge_space:55`：`yifeitest3`
- `knowledge_space:59`：`毕昇测试环境SSO的知识空间`

### 114 failed_tuple

当前 `failed_tuple` 状态：

- `pending`：83
- `succeeded`：70

pending 中有较多旧的 `FGAClient not available` 失败记录，也包含指向历史测试资源或已不存在资源的 tuple。114 需要先做有效性清理，再重放仍然有效的权限。

## 脚本风险点

### 1. checkpoint 与 Redis completed marker 状态不一致

F006 runner 使用两个完成信号：

- 文件 checkpoint：`/tmp/bisheng-permission-migration/migration_f006_checkpoint.json`
- Redis marker：`migration:f006:completed`

现场看到 checkpoint 已经完成到 Step 8，但 Redis completed marker 之前检查为空。这样会导致“脚本看起来跑过”和“runner 判断是否完成”的状态来源不一致。

### 2. checkpoint 跳过粒度太粗

F006 每个 Step 成功后保存 checkpoint。后续如果发现某个 Step 的语义映射有问题，重启会直接跳过已完成 Step，不会自动补写或纠错。

### 3. FGAWriteError 中 `cannot write` 被当成成功

代码位置：

`src/backend/bisheng/permission/migration/migrate_rbac_to_rebac.py`

`_write_singles()` 中把包含 `already exists` 或 `cannot write` 的错误都算作成功：

```python
if 'already exists' in err_lower or 'cannot write' in err_lower:
    written += 1
```

`already exists` 可以视为幂等成功，但 `cannot write` 可能是真实模型不允许写入，不应该算作成功。线上 failed_tuple 中的知识空间 owner 错误就属于这类语义错误风险。

### 4. verify 覆盖不足

F006 的 verify 是抽样验证，并且主要比较 `can_read`。它无法证明所有知识库、知识空间、文件夹、知识文件的 owner/manager/editor/viewer/parent 关系都完整迁移。

## 本地测试结果

已运行：

```bash
src/backend/.venv/bin/python -m pytest \
  src/backend/test/test_f006_permission_migration.py \
  src/backend/test/test_reconcile_role_access_fga_entrypoint.py
```

结果：

```text
61 passed
```

现有测试能覆盖 F006 映射、流程、checkpoint、基础幂等场景，但没有覆盖线上发现的这些关键风险：

- `cannot write` 不应被视为成功
- failed_tuple 中无效 owner tuple 的修复策略
- checkpoint 完成但 Redis marker 缺失
- 全量资源可见性对账
- 知识空间、文件夹、知识文件 parent 链路的端到端可见性

## 下一步修复建议

1. 增加只读对账脚本，从 MySQL 旧权限表和当前资源表生成“应有 OpenFGA tuple”，与当前 OpenFGA tuple 做 diff。
2. 对 109 先处理 `knowledge_space:53/55/59` 的无效 owner failed_tuple，按正确 relation 重建权限，不要直接 retry 原 tuple。
3. 对 114 先清理 pending failed_tuple：区分仍有效资源、已删除资源、历史测试资源，再重放有效 tuple。
4. 修改 F006 `_write_singles()`，只把 `already exists` 视为幂等成功；`cannot write` 必须进入 failed_tuple 并让迁移失败或至少显式报警。
5. 给 F006 增加全量 verify 模式，至少输出：
   - MySQL 资源总数
   - 应有 tuple 数
   - OpenFGA 实际 tuple 数
   - 缺失 tuple 明细
   - 无效/stale tuple 明细
6. 明确 checkpoint 与 Redis completed marker 的权威来源，避免只完成 checkpoint 但没有 completed marker 的半完成状态。

