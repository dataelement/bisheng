# 任务 Tasks：专家表岗位字段迁移补齐

## 元信息

- Feature ID: `065-qa-expert-schema-sync`
- Status: `completed`
- Updated: `2026-07-21`

## 任务清单

### T001：新增岗位字段迁移

- Status: `completed`
- Requirements: `REQ-001`, `REQ-002`
- Acceptance: `AC-REQ-001-01`～`AC-REQ-001-03`, `AC-REQ-002-01`～`AC-REQ-002-04`
- Files:
  - `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f064_add_qa_expert_job_fields.py`
- Implementation:
  - 以 `f063_knowledge_file_pdf_artifact` 为 `down_revision`。
  - 幂等增加三个 `VARCHAR(255) NULL` 字段。
  - 提供存在性检查和逆序 downgrade。
- Verification:
  - `alembic heads` 只有一个迁移头。

### T002：增加迁移回归测试

- Status: `completed`
- Requirements: `REQ-002`, `REQ-003`
- Acceptance: `AC-REQ-002-01`～`AC-REQ-002-04`, `AC-REQ-003-01`～`AC-REQ-003-04`
- Files:
  - `src/backend/test/qa_expert/test_qa_expert_job_fields_migration.py`
- Implementation:
  - 验证迁移元数据、字段定义、upgrade 幂等性和 downgrade。
- Verification:
  - 目标迁移测试通过。
  - 现有专家初始化脚本测试通过。

### T003：质量验证与交付记录

- Status: `completed`
- Requirements: `REQ-003`
- Acceptance: `AC-REQ-003-03`, `AC-REQ-003-04`
- Files:
  - `features/v2.6.0/065-qa-expert-schema-sync/verification.md`
- Verification:
  - Ruff 格式和检查通过。
  - Python 语法检查通过。
  - Architecture Guard 通过。
  - 记录 MySQL/DM8 验证边界及目标环境迁移命令。

## 实际偏差记录

- 暂无。
