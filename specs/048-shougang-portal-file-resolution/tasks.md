# 任务清单 Tasks: 首钢门户普通文件持久引用解析修复

- [x] T001 建立普通主版本失败回归
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02_
  - _Verification: 修复前执行新增测试并确认因“没有唯一有效入口”失败_
  - _Boundary: `test_knowledge_document_entry_resolver.py`_

- [x] T002 实现直接入口优先和历史入口安全回退
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-003-01, AC-REQ-003-03, AC-REQ-003-04_
  - _Verification: 持久引用解析器定向测试_
  - _Depends: T001_
  - _Boundary: `knowledge_document_entry_resolver.py` 最小修改_

- [x] T003 加固普通版本的逻辑文档完整性校验
  - _Requirements: REQ-003_
  - _Acceptance: AC-REQ-003-02, AC-REQ-003-03_
  - _Verification: 缺失逻辑文档失败测试及既有租户/历史版本测试_
  - _Depends: T001_
  - _Boundary: 普通入口解析分支和对应测试_

- [x] T004 审计并验证同类调用方
  - _Requirements: REQ-004_
  - _Acceptance: AC-REQ-001-03, AC-REQ-004-01, AC-REQ-004-02_
  - _Verification: 调用点搜索、知识模块定向测试、ruff、diff check_
  - _Depends: T002, T003_
  - _Boundary: 只读审计；不复制调用方修复逻辑_

- [x] T005 记录验证证据与剩余风险
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  - _Acceptance: all acceptance criteria_
  - _Verification: `verification.md`_
  - _Depends: T004_
  - _Boundary: SDD 状态和验证文档_
