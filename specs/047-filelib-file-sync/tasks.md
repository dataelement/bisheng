# 任务清单 Tasks: Filelib Fixed-Rule File Sync

- [x] T001 创建配置契约、同步规则和 params/响应 schema
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03_
  - _Verification: schema and rule unit tests_
  - _Boundary: portal schema and open_endpoints schemas only_

- [x] T002 创建同步查询 Repository
  - _Requirements: REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-REQ-002-03, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04_
  - _Verification: repository/service tests_
  - _Depends: T001_
  - _Boundary: filelib sync repository only_

- [x] T003 实现人员、部门、分类、业务域和目标空间解析服务
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05_
  - _Verification: service unit tests with repository/config/permission mocks_
  - _Depends: T001, T002_
  - _Boundary: filelib sync service only_

- [x] T004 增加固定同步编码和知识上传延迟入队能力
  - _Requirements: REQ-004, REQ-005_
  - _Acceptance: AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-005-03, AC-REQ-005-04_
  - _Verification: encoding unit test and upload regression test_
  - _Depends: T001_
  - _Boundary: file encoding transformer and KnowledgeSpaceService minimal changes_

- [x] T005 实现同步编排、11 个端点和实际 HTTP 错误响应
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_
  - _Acceptance: all acceptance criteria_
  - _Verification: FastAPI endpoint tests and route inspection_
  - _Depends: T002, T003, T004_
  - _Boundary: filelib sync endpoint/service/error code/router registration_

- [x] T006 更新接口文档并完成回归验证
  - _Requirements: REQ-001, REQ-005_
  - _Acceptance: AC-REQ-001-01, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04_
  - _Verification: pytest, ruff, arch-guard, git diff --check, verification.md_
  - _Depends: T005_
  - _Boundary: tests, docs and SDD verification only_

- [x] T007 移除 `external_file_id` 幂等记录和未发布迁移
  - _Requirements: REQ-004_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02_
  - _Verification: model/migration import absence, alembic heads, service unit tests_
  - _Depends: T005_
  - _Boundary: sync record model, migration, tenant model import and reservation logic only_

- [x] T008 验证重复 ID、来源元数据和既有上传行为
  - _Requirements: REQ-004, REQ-005_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02, AC-REQ-005-01, AC-REQ-005-03, AC-REQ-005-04_
  - _Verification: repeated-ID orchestration tests, pytest, ruff, arch-guard, git diff --check_
  - _Depends: T007_
  - _Boundary: sync tests, API docs and verification.md only_

## 实际偏差记录
- 仓库 `AGENTS.md` 仍描述 `features/v*/` 旧产物路径；当前同类功能已统一使用 `specs/NNN-*`，本功能沿用现行目录结构。
- 初版实现包含全局 `external_file_id` 幂等记录；用户在实现复核后明确取消去重和同步历史，本任务按 T007-T008 收缩设计。
