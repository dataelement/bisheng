# F108 Tasks

- [x] T001 建立无开关路由与缺初始化拒绝回归，实现共享核心契约。
  _Requirements: REQ-001, REQ-002_  
  _Acceptance: AC-001, AC-002, AC-005_  
  _Verification: adapter 与 shared-only 契约测试_  
  _Depends: none_
- [x] T002 收口创建、解析、投影、版本与全文同步，保留离线迁移。
  _Requirements: REQ-001, REQ-002, REQ-004_  
  _Acceptance: AC-002, AC-003, AC-005_  
  _Verification: ingestion、projection、fulltext、migration 回归_  
  _Depends: T001_
- [x] T003 收口问答、检索、工作流入口，验证非 SPACE 边界。
  _Requirements: REQ-001, REQ-003_  
  _Acceptance: AC-003, AC-004_  
  _Verification: retrieval、portal、workflow/workstation 相关测试_  
  _Depends: T001_
- [x] T004 完成相关回归、静态检查与验证记录。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_  
  _Acceptance: AC-001, AC-002, AC-003, AC-004, AC-005_  
  _Verification: 合并相关 pytest 范围、ruff、diff 与原有改动保留检查_  
  _Depends: T002, T003_

本地实现与验证已完成；真实 ES/Milvus、DM8 和部署后验证属于独立的 MANUAL_REQUIRED 项，见 verification.md。
