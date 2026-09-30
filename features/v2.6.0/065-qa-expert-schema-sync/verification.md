# 验证 Verification：专家表岗位字段迁移补齐

## 元信息

- Feature ID: `065-qa-expert-schema-sync`
- Status: `passed`
- Verified: `2026-07-21`

## 结果摘要

- 新迁移以 `f063_knowledge_file_pdf_artifact` 为父节点，Alembic 保持唯一头。
- 迁移幂等增加 `position`、`job_family`、`job_category` 三个可空 `VARCHAR(255)` 字段。
- SQLite 内存数据库已验证 upgrade、重复 upgrade 和 downgrade 的真实 DDL 往返。
- 专家初始化脚本的 9 个回归测试继续通过。
- 未连接或修改目标 MySQL/DM8 数据库。

## 自动化验证证据

### 测试

命令：

```bash
.venv/bin/pytest -q test/qa_expert test/scripts/test_shougang_execute_qa_expert.py
```

结果：

```text
................                                                         [100%]
16 passed in 0.10s
```

覆盖：

- 迁移 revision/down revision。
- 三个字段的名称、类型、长度、可空性和注释。
- 表不存在时安全返回。
- 已存在字段跳过、缺失字段继续创建。
- downgrade 逆序删除。
- SQLite upgrade、重复 upgrade、downgrade 真实 DDL。
- 专家硬编码数据、名称解析、幂等和持久化脚本回归。

### 格式和静态检查

```bash
.venv/bin/ruff format --check \
  bisheng/core/database/alembic/versions/v2_6_0_f064_add_qa_expert_job_fields.py \
  test/qa_expert/test_qa_expert_job_fields_migration.py \
  scripts/shougang_execute_qa_expert.py \
  test/scripts/test_shougang_execute_qa_expert.py
.venv/bin/ruff check \
  bisheng/core/database/alembic/versions/v2_6_0_f064_add_qa_expert_job_fields.py \
  test/qa_expert/test_qa_expert_job_fields_migration.py \
  scripts/shougang_execute_qa_expert.py \
  test/scripts/test_shougang_execute_qa_expert.py
```

结果：`4 files already formatted`，`All checks passed!`。

### 语法检查

```bash
.venv/bin/python -m py_compile \
  bisheng/core/database/alembic/versions/v2_6_0_f064_add_qa_expert_job_fields.py \
  scripts/shougang_execute_qa_expert.py \
  test/qa_expert/test_qa_expert_job_fields_migration.py \
  test/scripts/test_shougang_execute_qa_expert.py
```

结果：通过，无输出。

### Alembic 拓扑

```bash
.venv/bin/python -m alembic heads
```

结果：

```text
f064_add_qa_expert_job_fields (head)
```

### Architecture Guard 与差异检查

- 对新增迁移、迁移测试、专家脚本及其测试执行 `scripts/arch-guard.sh`，无输出。
- `git diff --check` 通过，无空白错误。

## 未验证项

- macOS 不提供项目 DM8 驱动，未进行真实 DM8 数据库迁移；需要 Linux CI 或部署环境验证。
- 按任务边界未执行目标 MySQL 数据库的 `alembic upgrade head`，因此日志对应运行环境仍需部署并应用迁移后才能恢复。

## 部署后验证

在目标环境 `src/backend` 目录执行：

```bash
uv run alembic upgrade head
uv run python scripts/shougang_execute_qa_expert.py --dry-run
uv run python scripts/shougang_execute_qa_expert.py
```

执行迁移前应先确认当前 Alembic revision 和数据库备份策略。字段投入使用后不要通过 downgrade 回滚，优先采用前向修复。
