# 任务清单 Tasks: 门户智能问答与知识库工作台查看范围对齐

- [x] T001 建立门户 BFF 范围和懒加载回归测试
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-002-01, AC-REQ-002-03, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-004-01_
  - _Verification: 修复前新增测试因仍调用广域 QA 接口而失败_
  - _Boundary: `backend/tests/test_qa_knowledge_scope_api.py`_

- [x] T002 实现门户 BFF 工作台范围与通用树接口复用
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-*, AC-REQ-002-01..04, AC-REQ-003-*_
  - _Verification: 门户 BFF QA 定向测试_
  - _Depends: T001_
  - _Boundary: QA 路由与 `KnowledgeService`，不改通用门户发现范围_

- [x] T003 限定前端分类选择知识库范围
  - _Requirements: REQ-002, REQ-005_
  - _Acceptance: AC-REQ-002-05, AC-REQ-005-01, AC-REQ-005-02_
  - _Verification: 前端接线测试、TypeScript build_
  - _Boundary: 首页和智能应用页选择器回调；不改选择器懒加载实现_

- [x] T004 建立并实现 BiSheng 最终检索权限回归
  - _Requirements: REQ-004_
  - _Acceptance: AC-REQ-004-*_
  - _Verification: 不可读空间/目录/文件、非 SUCCESS、整库和 20 文件上限测试_
  - _Depends: T001_
  - _Boundary: 门户 QA 最终范围解析器和工作站调用契约_

- [x] T005 执行 V3 权限回归并记录证据
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_
  - _Acceptance: all acceptance criteria_
  - _Verification: 门户后端 pytest、BiSheng 知识/工作站 pytest、前端 tests/build、ruff、diff check_
  - _Depends: T002, T003, T004_
  - _Boundary: 相关模块回归，不运行无关全仓测试_

- [x] T006 建立同名个人知识库分组失败回归
  - Done when: 两个不同 ID、规范化名称相同的本人个人空间会使回归断言在修复前失败。
  - _Requirements: REQ-006_
  - _Acceptance: AC-REQ-006-01, AC-REQ-006-02_
  - _Verification: V-AC-REQ-006-01_
  - _Depends: none_
  - _Boundary: `src/backend/test/knowledge/test_knowledge_space_level_team_ks.py`_

- [x] T007 实现个人知识库分组名称防重
  - Done when: 分组接口只保留既有排序中的第一条同名本人个人空间，其他分组和不同名空间行为不变。
  - _Requirements: REQ-006_
  - _Acceptance: AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03_
  - _Verification: V-AC-REQ-006-01, V-AC-REQ-006-02_
  - _Depends: T006_
  - _Boundary: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`_

- [x] T008 更新重复个人知识库修复验证证据
  - Done when: 定向回归、相关分组模块测试和静态检查结果记录到 `verification.md`。
  - _Requirements: REQ-006_
  - _Acceptance: AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03_
  - _Verification: V-AC-REQ-006-01, V-AC-REQ-006-02_
  - _Depends: T007_
  - _Boundary: verification only_
