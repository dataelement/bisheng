# 任务拆分 Tasks: 业务域候选空间专用查询优化

## 元信息 Metadata

- Feature ID: `057-domain-bindable-spaces-perf`
- Status: completed
- Related requirements: `features/v2.6.0/057-domain-bindable-spaces-perf/requirements.md`
- Related design: `features/v2.6.0/057-domain-bindable-spaces-perf/design.md`
- Created: 2026-07-16

## Tasks

- [x] T001 编写 BiSheng 专用候选空间查询回归测试（先红）
  - Done when: 覆盖管理员、非管理员、公共/部门过滤、未发布过滤、业务域编码透传及不走通用可见空间路径。
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04_
  - _Verification: `uv run pytest test/knowledge/test_shougang_portal_business_domain_codes.py -q`_
  - _Depends: none_
  - _Boundary: 测试仅限业务域候选空间专用接口；不改通用 grouped 测试。_

- [x] T002 实现 BiSheng 管理员专用候选空间接口
  - Done when: 新接口按确认规则返回轻量候选项，且 T001 通过。
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04_
  - _Verification: `uv run pytest test/knowledge/test_shougang_portal_business_domain_codes.py -q`；`uv run ruff check ...`_
  - _Depends: T001_
  - _Boundary: schema、service、`shougang_portal.py`；不修改数据库表和通用 grouped 接口。_

- [x] T003 编写并实现门户 BFF 上游切换
  - Done when: `space-options` 调用新路径、保留门户管理员校验及空列表降级，且不回退通用空间接口。
  - _Requirements: REQ-003_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02_
  - _Verification: `./.venv/bin/python -m pytest tests/test_admin_config_api.py -q -k 'space_options'`_
  - _Depends: T002_
  - _Boundary: 只改门户 BFF 与既有 API 测试；不改前端缓存或 UI。_

- [x] T004 运行验证并记录结果
  - Done when: 定向测试、格式检查和 diff 检查有新鲜证据，更新 `verification.md` 与任务状态。
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-003-02_
  - _Verification: verification.md_
  - _Depends: T001, T002, T003_
  - _Boundary: 验证与文档，不做范围外修复。_

## 实现记录

- T001：先运行测试确认接口尚不存在，收集期因缺少 endpoint 失败；补齐测试后覆盖管理员、空间等级、发布状态、业务域编码和通用可见范围路径隔离。
- T002：新增 BiSheng `GET /api/v1/knowledge/shougang-portal/spaces/domain-bindable`，服务层以 `is_admin()` 拒绝非管理员，并只读取 public/department scope 与已发布空间。
- T003：门户 `/api/v1/admin/config/space-options` 已切换到专用接口；上游异常仍返回空候选列表，且没有通用 grouped 回退。
- T004：定向测试、编译和 `git diff --check` 通过，详见 [verification.md](./verification.md)。
