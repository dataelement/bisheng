# Feature: F051-部门子树与用户物理清理运维脚本

> **前置步骤**：已完成 Spec Discovery。执行人已确认目标范围、用户删除语义、资产接收人、历史数据边界和受保护部门规则。

**关联 PRD**: 运维数据清理需求（2026-07-10）
**优先级**: P0
**所属版本**: v2.6.0
**类型**: 后端运维脚本；不新增 HTTP API、数据库表或迁移。

---

## 1. 概述与用户故事

作为 **平台运维人员**，
我希望通过一个显式参数的脚本，预览并按业务 `dept_id` 清理整个部门子树及其用户，
以便在组织数据需要彻底下线时，安全地转移可转移资产、移除权限关系并删除无效账号。

### 范围边界

- **纳入**：目标部门与全部子孙部门；子树成员涉及的所有用户（包括同时属于树外部门、外部同步来源用户）；用户账号及账号/权限关联的物理删除；`linsight_session_version`、`linsight_sop`、`linsight_sop_record` 删除；现有资产转移注册表支持的资源；部门及部门权限关联的物理删除。
- **明确排除**：聊天、审计、渠道等历史记录删除；外部身份源或组织同步配置变更；数据库 Schema、Alembic migration、HTTP API 和前端改动。

---

## 2. 需求 Requirements

| ID | 需求 |
|----|------|
| REQ-001 | 脚本必须以业务 `dept_id` 为入口收集完整部门子树，并默认仅输出 dry-run 影响面。 |
| REQ-002 | 脚本必须在任何写入前预检受保护节点、接收人、成员用户、账号依赖和资产接收资格；已知阻塞项必须 fail-closed。 |
| REQ-003 | `--apply` 必须将可转移资产交给指定管理员，并物理清理已确认的用户账号/权限关联、Linsight 记录与部门树。 |
| REQ-004 | 脚本必须使用既有 OpenFGA 与失败元组补偿机制，准确报告外部权限清理状态。 |
| REQ-005 | 除明确纳入的 Linsight 记录外，脚本不得删除聊天、审计、渠道历史、外部身份源数据或组织同步配置，亦不得绕过租户与领域服务约束。 |

---

## 3. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 运维人员 | 执行 `purge_department_subtree.py --dept-id <dept_id> --transfer-to-user-id <id>`，不带 `--apply` | 仅输出完整部门子树、去重后的目标用户、资产转移计划、部门/账号/权限清理数量和阻塞原因；不写 MySQL、Redis 或 OpenFGA。 |
| AC-02 | 运维人员 | 传入不存在的 `dept_id`、不存在或已包含在删除用户集合中的接收人、受保护部门，或接收人不满足任一资产租户的可见范围 | 脚本以非零状态退出，并在开始删除前报告原因；不得删除任何目标部门或用户。 |
| AC-03 | 运维人员 | 对可通过预检的目标显式传入 `--apply` | 先将注册表支持的资产转移给 `--transfer-to-user-id`，再物理清理用户账号关联和部门树；部门按叶节点到根节点的顺序删除。 |
| AC-04 | 运维人员 | 目标子树中的用户同时属于树外部门，或其 `source` 为外部同步来源 | 仍将该用户纳入物理删除；其树外部门成员关系随账号关联一并清理。脚本明确提示外部同步可在后续同步时重新创建账号。 |
| AC-05 | 运维人员 | 删除执行成功 | `user_department`、部门管理员授权、部门角色、用户角色、用户组、用户租户关联、`linsight_session_version`、`linsight_sop`、`linsight_sop_record` 及对应 OpenFGA 元组不再保留；聊天、审计和渠道历史不主动删除。 |
| AC-06 | 运维人员 | OpenFGA 在清理阶段不可用或写入失败 | 数据库侧的清理意图通过现有 `FailedTuple` 补偿机制记录，脚本报告待补偿数量/状态，不将其伪报为 OpenFGA 已成功清理。 |

---

## 4. 边界情况

- `--dept-id` 是 `department.dept_id` 业务标识，不接受内部数字主键替代。
- 发现 `BS@guest` 或任一 `is_tenant_root=1` 节点时，整次操作中止；不支持危险绕过开关。
- `--transfer-to-user-id` 必须存在、未被纳入删除集合，并能作为每个资产所属租户的合法接收人。
- 子树成员通过 `UserDepartment` 汇总并按 `user_id` 去重；同一用户的多部门关系不会重复执行资产转移或删除。
- 可转移资源以 `ResourceOwnershipService` 的注册资源类型为准；发现无法由该服务安全处理的账号依赖时，应在预检阶段阻断，不允许静默跳过。
- 单次资产转移服务最多处理 500 项资源；超过上限时，脚本按用户、租户和资源类型分批转移，每批最多 500 项，任一批失败即停止后续删除。
- 预检通过后发生未预期异常时，脚本立即停止并返回非零状态；MySQL 与 OpenFGA 不支持分布式事务，OpenFGA 后续一致性依赖 `FailedTuple` 重试。

---

## 5. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 部门子树解析 | A: 递归 CTE / B: 按 `parent_id` 在应用层遍历 / C: 仅按 `path` 前缀 | 选 B | 现有模型以 `parent_id` 表达树关系；应用层遍历避免递归 SQL 的 MySQL/DM8 方言差异，也不依赖历史 `path` 一致性。 |
| AD-02 | 删除安全开关 | A: 直接执行 / B: dry-run 默认、`--apply` 写入 | 选 B | 符合运维脚本规范，先给出完整影响面，再允许不可逆操作。 |
| AD-03 | 资产归属变更 | A: 直接更新资源表 / B: `ResourceOwnershipService` | 选 B | 复用现有租户可见范围校验、OpenFGA owner 元组更新、审计和失败处理，避免脚本绕开领域规则。 |
| AD-04 | 删除顺序 | A: 根到叶 / B: 叶到根 | 选 B | 父节点在子节点或成员仍存在时不可删除；叶到根符合现有部门删除约束。 |
| AD-05 | 历史数据 | A: 全部保留 / B: Linsight 与用户一并删除 / C: 全部删除 | 选 B | Linsight 三张表对用户有非空外键，无法在保留原记录的前提下物理删除用户；已确认删除这些记录，同时保留聊天、审计与渠道历史。 |
| AD-06 | 受保护节点 | A: 允许删除 / B: 全局中止 / C: 跳过继续 | 选 B | 删除访客部门或租户挂载根会破坏平台租户结构，必须 fail-closed。 |
| AD-07 | 大批量资产转移 | A: 拒绝超过 500 项 / B: 以 500 项分批调用现有服务 | 选 B | `ResourceOwnershipService` 有单批上限；分批复用其校验与补偿能力，同时避免把可处理的大部门无谓拒绝。 |

---

## 6. 数据库 & Domain 模型

- 不新增或修改数据库表、字段、索引、迁移或配置。
- 脚本使用现有 `Department`、`UserDepartment`、`User`、`UserRole`、`UserGroup`、`UserTenant`、`DepartmentAdminGrant`、`Role` 及 `FailedTuple` 模型。
- 多租户表操作必须在脚本中显式使用 `bypass_tenant_filter()`，并对每项读取/写入记录所属租户，不能手写业务层 `tenant_id` 权限过滤替代既有机制。

---

## 7. CLI 契约

```bash
cd src/backend

# 默认预览，不写入
PYTHONPATH=./ .venv/bin/python scripts/purge_department_subtree.py \
  --dept-id BS@example \
  --transfer-to-user-id 1

# 显式执行（不可逆）
PYTHONPATH=./ .venv/bin/python scripts/purge_department_subtree.py \
  --dept-id BS@example \
  --transfer-to-user-id 1 \
  --apply
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--dept-id` | 是 | 目标部门的业务 `dept_id`。 |
| `--transfer-to-user-id` | 是 | 接收被删除用户可转移资产的内部 `user_id`。 |
| `--apply` | 否 | 显式允许数据库与 OpenFGA 写入；缺失时为 dry-run。 |

退出码：`0` 表示成功（包括无写入的有效 dry-run）；参数/预检/受保护节点错误、执行错误必须使用非零退出码并输出可读原因。

---

## 8. 服务与执行逻辑

1. 读取目标 `Department.dept_id`，使用 `parent_id` 广度优先收集完整子树，并保留叶到根删除顺序。
2. 在任何写入前完成保护节点、接收用户、成员用户、用户直接账号关联、资产接收资格与可转移资源的全量预检，生成稳定的执行计划。
3. dry-run 仅输出执行计划、数量与阻塞项后退出。
4. `--apply` 先调用 `ResourceOwnershipService` 转移每个目标用户在每个租户中的支持资源；任一转移失败立即停止，后续不得删除用户或部门。
5. 资产转移完成后，先删除 `linsight_session_version`、`linsight_sop` 与 `linsight_sop_record`，再删除用户及已确认的账号/权限关联；收集对应 OpenFGA 删除操作并使用 `PermissionService.batch_write_tuples(..., crash_safe=True)`。
6. 清理部门成员、管理员授权和部门作用域角色后，按叶到根删除部门；复用 `DepartmentChangeHandler` 生成部门 OpenFGA 删除操作。
7. 输出可机读/人工可读的完成摘要：已转移资源数、已删除用户数、已删除部门数、OpenFGA 操作数及待补偿状态。

---

## 9. 测试策略

- 单元测试：参数验证、子树遍历、成员去重、受保护节点、接收人冲突、跨租户接收人拒绝、dry-run 无副作用、Linsight 依赖删除、成功删除顺序、资源转移失败阻断、OpenFGA 失败补偿报告。
- 静态检查：`uv run ruff format --check` 与 `uv run ruff check`。
- CLI 冒烟：`--help` 与无 `--apply` 的 mocked dry-run。
- 不在开发/测试环境执行真实 `--apply`，不连接生产 MySQL、OpenFGA 或外部组织同步源。

---

## 10. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `features/v2.6.0/051-purge-department-subtree/spec.md` | 已确认需求、架构决策、CLI 契约与验收标准。 |
| `features/v2.6.0/051-purge-department-subtree/tasks.md` | 经规格确认后的可追踪实施任务。 |
| `src/backend/scripts/purge_department_subtree.py` | 运维脚本实现。 |
| `src/backend/scripts/purge_department_subtree.sh` | 可选解释器探测与参数转发包装器。 |
| `src/backend/test/department/test_purge_department_subtree_script.py` | 脚本核心逻辑单元测试。 |

### 修改

| 文件 | 说明 |
|------|------|
| `src/backend/scripts/README.md` | 新脚本用途、预览与显式执行示例、风险提示。 |

---

## 11. 风险与回滚

- `--apply` 后用户、部门及其账号/权限关联不可恢复；执行前必须保存 dry-run 输出并在维护窗口运行。
- 资产转移已成功但后续数据库删除失败时，资产可能已归属接收人；脚本必须准确报告中断状态，不得尝试猜测性回滚。
- OpenFGA 失败由 `FailedTuple` 机制重试；运维人员应在完成摘要中确认没有未解决的补偿记录。
- 本特性仅新增脚本、测试、文档，开发阶段可通过删除新增文件回滚；不修改数据结构。
