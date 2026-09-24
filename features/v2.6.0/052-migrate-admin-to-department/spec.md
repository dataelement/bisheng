# Feature: F052-admin 账号组织迁移运维脚本

> **变更记录（2026-07-10）**：用户确认取消资源交接；跨租户迁移后资源继续归 admin。该例外仅限本脚本，不修改全局保护配置。

**关联 PRD**: 运维账号组织迁移需求（2026-07-10）  
**优先级**: P1  
**所属版本**: v2.6.0  
**类型**: 后端运维脚本与受限领域迁移入口；不新增 HTTP API、数据库表或迁移。

---

## 1. 概述与用户故事

作为 **平台运维人员**，我希望将一个明确指定的 admin 账号迁移到目标组织，并在跨租户时仍保留其原租户资源，以便在组织调整中保持 admin 对既有资源的所有权。

### 范围边界

- **纳入**：账号和部门的显式定位、资源保留摘要、主部门/叶子租户/OpenFGA 同步、默认 dry-run、受限强制迁移入口。
- **明确排除**：资源 owner 修改、资源删除、`--transfer-to-user-id`、全局 `enforce_transfer_before_relocate` 配置变更、管理员角色/密码/账号状态/次级部门关系、HTTP API 和 Schema 变更。

---

## 2. 需求 Requirements

| ID | 需求 |
|----|------|
| REQ-001 | 脚本必须要求 `--user-id`、`--username` 恰好提供一个，`--dept-id`、`--department-id` 恰好提供一个；不得存在或接受 `--transfer-to-user-id`。 |
| REQ-002 | 脚本必须在写入前解析账号、当前/目标主部门、当前/目标叶子租户，并统计 admin 在原叶子租户保留的资源数量。 |
| REQ-003 | 默认执行必须为 dry-run，仅输出稳定、机读的迁移与资源保留摘要；只有 `--apply` 才能写入。 |
| REQ-004 | 跨租户 `--apply` 必须保留资源 owner 为 admin，且仅本脚本强制跳过 `enforce_transfer_before_relocate` 的资源阻断，完成主部门、叶子租户、令牌、OpenFGA、缓存和审计同步。 |
| REQ-005 | 脚本不得持久化修改全局保护配置，也不得改变资源表、管理员角色、账号状态、密码或其他次级部门关系。 |

---

## 3. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 运维人员 | 不带 `--apply` 执行合法参数命令 | 输出账号、原/新主部门、原/新叶子租户、保留资源数量；不写 MySQL、Redis 或 OpenFGA。 |
| AC-02 | 运维人员 | 缺少、重复或混用任一互斥定位参数；或传入已废弃的资源接收人参数 | 参数错误退出，且不发生写入。 |
| AC-03 | 运维人员 | admin 跨叶子租户且原租户拥有资源，系统全局保护开启 | `--apply` 仍完成迁移；资源 owner 继续为 admin，全局配置值保持不变。 |
| AC-04 | 运维人员 | 同一叶子租户迁移或目标已是主部门 | 不改变任何资源 owner；目标已是主部门时幂等成功。 |
| AC-05 | 运维人员 | 强制迁移后 OpenFGA 写入失败 | 数据库侧迁移状态与失败补偿状态如实记录，不伪报 OpenFGA 成功。 |

---

## 4. 架构决策

| ID | 决策 | 结论 | 理由 |
|----|------|------|------|
| AD-01 | 资源处置 | 保留 owner 为 admin，不转移。 | 用户已明确确认资源必须继续归 admin。 |
| AD-02 | 跨租户保护 | 新增仅供运维脚本调用的强制同步入口；普通 `sync_user()` 保持不变。 | 只对显式维护操作生效，避免弱化所有正常调岗的保护。 |
| AD-03 | CLI | 删除资源接收人参数。 | 没有资源转移时接收人无业务含义。 |
| AD-04 | 同步职责 | 复用既有租户激活、令牌、OpenFGA、缓存和审计逻辑，仅跳过资源阻断判断。 | 最小化行为漂移，保留既有补偿机制。 |

---

## 5. CLI 契约

```bash
cd src/backend

# 默认预览，不写入
PYTHONPATH=./ .venv/bin/python scripts/migrate_admin_to_department.py \
  --username admin \
  --dept-id BS@example

# 显式执行
PYTHONPATH=./ .venv/bin/python scripts/migrate_admin_to_department.py \
  --user-id 1 \
  --department-id 42 \
  --apply
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--user-id` | 二选一 | 迁移账号的内部 `user_id`。 |
| `--username` | 二选一 | 迁移账号的精确 `user_name`。 |
| `--dept-id` | 二选一 | 目标部门的业务 `dept_id`。 |
| `--department-id` | 二选一 | 目标部门的内部主键。 |
| `--apply` | 否 | 显式允许主部门、租户和 OpenFGA 写入；缺失时为 dry-run。 |

退出码：`0` 成功，`2` 参数或预检失败，`3` 预检后的执行异常。

---

## 6. 服务与执行逻辑

1. 解析账号和目标部门，推导当前/目标叶子租户，并统计当前叶子租户中仍归 admin 的资源数量。
2. dry-run 输出资源将被保留、不会转移的摘要后退出。
3. `--apply` 时调用受限强制迁移入口；它更新主部门并执行租户激活、令牌版本、OpenFGA 元组、缓存失效与审计。
4. 强制入口跳过资源拥有量导致的阻断，但不修改全局配置；资源表不参与写入。
5. OpenFGA 写入继续使用 crash-safe 补偿路径，并在摘要中准确反映其状态。

---

## 7. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/scripts/migrate_admin_to_department.py` | 取消资源转移后的运维脚本。 |
| `src/backend/scripts/migrate_admin_to_department.sh` | 参数转发包装器。 |
| `src/backend/test/department/test_migrate_admin_to_department_script.py` | 脚本与强制迁移调用测试。 |

### 修改

| 文件 | 变更内容 |
|------|----------|
| `src/backend/bisheng/tenant/domain/services/user_tenant_sync_service.py` | 新增仅供维护脚本调用的资源保留强制同步入口。 |
| `src/backend/bisheng/user/domain/services/user_department_service.py` | 新增调用该受限同步入口的维护迁移方法。 |
| `src/backend/scripts/README.md` | 更新 CLI、资源保留语义和跨租户风险。 |

---

## 8. 风险与回滚

- admin 迁移后可在新叶子租户下拥有原租户资源；资源访问仍受既有租户可见性与权限规则限制。
- 主部门、租户与 OpenFGA 不是分布式事务；OpenFGA 故障依赖 `FailedTuple` 补偿。
- 不修改全局配置；若需回滚，可将 admin 主部门迁回原部门，但资源 owner 不需要恢复。
