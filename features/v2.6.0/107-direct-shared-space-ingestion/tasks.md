# Tasks: F107 共享知识空间直接解析入库

**关联规格**: [requirements.md](./requirements.md)、[design.md](./design.md)  
**版本**: v2.6.0  
**状态**: 已完成

## Tasks

- [x] **T001**: 建立 metadata/filter 回归测试
  _Requirements: REQ-002_  
  _Acceptance: AC-002, AC-007_  
  _Verification: pytest shared storage adapter contract tests_  
  _Depends: none_  
  _Boundary: 不连接真实 Milvus/ES_

- [x] **T002**: 保留共享物理 schema 的 tenant 兼容字段并移除查询 tenant filter
  _Requirements: REQ-002_  
  _Acceptance: AC-002, AC-007_  
  _Verification: T001 tests + ruff_  
  _Depends: T001_  
  _Boundary: writer 固定补写 tenant_id=1，tenant routing/writer binding 保留_

- [x] **T003**: 建立 direct ingestion 与失败关闭回归测试
  _Requirements: REQ-001, REQ-003, REQ-005_  
  _Acceptance: AC-001, AC-003, AC-004, AC-006_  
  _Verification: pytest direct ingestion tests_  
  _Depends: T001_  
  _Boundary: fake writer/embedding，不访问外部存储_

- [x] **T004**: 实现 canonical prepare/finalize 与直接共享入库服务
  _Requirements: REQ-001, REQ-003_  
  _Acceptance: AC-001, AC-003, AC-004_  
  _Verification: T003 tests + document distribution regression_  
  _Depends: T003_  
  _Boundary: 不改变 SQL schema_

- [x] **T005**: 接入上传解析 shared/legacy 路由
  _Requirements: REQ-001, REQ-005_  
  _Acceptance: AC-001, AC-003, AC-006_  
  _Verification: addEmbedding route tests_  
  _Depends: T004_  
  _Boundary: routed failure 禁止 legacy fallback_

- [x] **T006**: 收口 post-parse projection 职责
  _Requirements: REQ-004_  
  _Acceptance: AC-005_  
  _Verification: projection worker/service tests_  
  _Depends: T004, T005_  
  _Boundary: legacy loader 保留给 migration 显式调用_

- [x] **T007**: 执行相关格式、静态和模块回归验证
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_  
  _Acceptance: AC-001, AC-002, AC-003, AC-004, AC-005, AC-006, AC-007_  
  _Verification: ruff + related pytest suites_  
  _Depends: T002, T004, T005, T006_  
  _Boundary: 真实 Milvus/ES 写入验证为 MANUAL_REQUIRED_

## 实际偏差记录

- 项目 `.gitignore` 当前忽略整个 `features/` 目录；本特性的规格文件已在本地生成并更新，但除已被
  Git 跟踪的 `release-contract.md` 外，不会自动出现在普通 `git status` 中。
- 未连接真实 Milvus/ES；部署后需重试故障文件验证既有 schema 可接受 `tenant_id=1`。
