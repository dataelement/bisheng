# Tasks: F052-admin 账号组织迁移运维脚本

**关联规格**: [spec.md](./spec.md)  
**版本**: v2.6.0

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已确认 | 用户已确认资源保留语义。 |
| tasks.md | ✅ 已评审 | 任务边界已确认。 |
| 实现 | ✅ 已完成 | 5 / 5 完成；真实 `--apply` 留给维护窗口。 |

## Tasks

- [x] **T001**: 更新 F052 测试为资源保留语义  
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-005_  
  _Acceptance: AC-01, AC-02, AC-04_  
  _Verification: V-001_  
  _Boundary: 只修改 `test/department/test_migrate_admin_to_department_script.py`；mock 所有数据库、OpenFGA 和缓存。_  
  **逻辑**：删除接收人/转移测试，增加废弃参数拒绝、dry-run 无写入、保留资源摘要、同租户不写资源 owner 的测试。

- [x] **T002**: 新增受限资源保留强制同步入口  
  _Requirements: REQ-004, REQ-005_  
  _Acceptance: AC-03, AC-05_  
  _Verification: V-001, V-002_  
  _Boundary: 只修改 `tenant/domain/services/user_tenant_sync_service.py` 与配套测试；不得改变 `sync_user()` 默认行为或全局配置。_  
  **逻辑**：复用租户激活、令牌、OpenFGA、缓存与审计，跳过资源阻断；入口名称和文档必须标明 maintenance-only。

- [x] **T003**: 新增维护专用主部门迁移入口  
  _Requirements: REQ-004, REQ-005_  
  _Acceptance: AC-03, AC-04, AC-05_  
  _Verification: V-001, V-003_  
  _Boundary: 只修改 `user/domain/services/user_department_service.py` 与测试；保留现有 `change_primary_department()` 行为。_  
  **逻辑**：以既有主部门切换逻辑为基础，调用 T002 的受限同步入口，保留次级部门关系与部门成员 OpenFGA 关系。

- [x] **T004**: 改造 CLI 与 README 取消资源接收人  
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-005_  
  _Acceptance: AC-01, AC-02, AC-03, AC-04_  
  _Verification: V-001, V-004_  
  _Boundary: 只修改 F052 脚本、包装器和 `scripts/README.md`；不得调用 `ResourceOwnershipService.transfer_owner`。_  
  **逻辑**：移除参数、资源转移批次和接收人预检；输出保留资源数量，调用 T003 维护迁移入口。

- [x] **T005**: 运行回归验证并更新验证记录  
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_  
  _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05_  
  _Verification: V-001, V-002, V-003, V-004_  
  _Boundary: 只运行定向测试、Ruff、`--help` 和 dry-run mock；不得真实执行 `--apply`。_  
  **逻辑**：记录实际输出、OpenFGA 及真实维护环境验证缺口。

## Verification Map

| ID | 方法 | 覆盖 |
|----|------|------|
| V-001 | `uv run pytest test/department/test_migrate_admin_to_department_script.py` | 参数、dry-run、资源保留、强制迁移调用与失败。 |
| V-002 | 强制同步单元测试 | 全局保护配置开启时仍可迁移，且普通同步不变。 |
| V-003 | 主部门迁移单元测试 | 次级部门关系保留，强制同步调用顺序正确。 |
| V-004 | Ruff、`--help`、mock dry-run | 静态质量与 CLI 契约。 |

## 实际偏差记录

- 用户确认将原先的资源交接需求替换为“资源继续归 admin”，此前完成的资源转移实现和验证结果不再适用。
