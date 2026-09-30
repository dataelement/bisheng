# 设计 Design：专家表岗位字段迁移补齐

## 元信息

- Feature ID: `065-qa-expert-schema-sync`
- Status: `approved`
- Updated: `2026-07-21`

## 根因链路

```text
shougang_execute_qa_expert._run
  -> _prepare_experts
  -> ExpertRepository.get_by_user_id
  -> select(Expert)
  -> SELECT qa_expert.position, qa_expert.job_family, qa_expert.job_category
  -> MySQL 1054: qa_expert.position 不存在
```

三个字段在同一次模型变更中加入，但没有对应迁移。读取完整实体和后续插入都会依赖这些字段，因此修改脚本查询列或跳过幂等检查不能从根本上解决问题。

## 方案

新增线性 Alembic 迁移：

```text
f063_knowledge_file_pdf_artifact
  -> f064_add_qa_expert_job_fields
```

迁移使用以下定义：

| 字段 | 类型 | 可空 | 默认值 | 注释 |
|---|---|---:|---|---|
| `position` | `sa.String(255)` | 是 | 无 | Expert position |
| `job_family` | `sa.String(255)` | 是 | 无 | Expert job family |
| `job_category` | `sa.String(255)` | 是 | 无 | Expert job category |

### Upgrade

1. 通过 `op.get_bind()` 获取连接。
2. 使用 `table_exists()` 检查 `qa_expert`；表不存在时直接返回。
3. 逐字段调用 `column_exists()`；仅为缺失字段执行 `op.add_column()`。

### Downgrade

1. 表不存在时直接返回。
2. 按创建顺序的逆序检查并删除存在的目标字段。
3. 不尝试备份字段数据；生产环境字段投入使用后采用前向修复。

## 方案取舍

### 采用：新增迁移补齐结构

- ORM 是现行业务事实，脚本和 QA 接口都会使用这些字段。
- 修复覆盖查询和写入链路，不产生特殊兼容分支。
- 迁移可跟随标准部署流程审计和回滚。

### 不采用：脚本只查询旧字段

- 只能绕过当前 SELECT，INSERT 仍会引用缺失字段。
- 其他 `select(Expert)` 调用仍然失败。
- 会长期掩盖数据库与模型不一致。

### 不采用：启动脚本自行执行 DDL

- 绕过 Alembic 版本管理。
- 脚本权限和执行时机不可控。
- 不符合 MySQL/DM8 双数据库迁移规范。

## 测试设计

- 导入迁移模块并检查 revision 链。
- Mock `op` 和方言检查函数，验证三列的名称、类型、长度、可空性与注释。
- 覆盖表不存在、部分字段存在、全部字段降级。
- 运行现有 `test/scripts/test_shougang_execute_qa_expert.py`，确认脚本行为未回归。
- 执行 `alembic heads`，确认只有 `f064_add_qa_expert_job_fields` 一个头。

## 部署与验证

代码部署后，由目标环境在 `src/backend` 工作目录执行：

```bash
uv run alembic upgrade head
uv run python scripts/shougang_execute_qa_expert.py --dry-run
uv run python scripts/shougang_execute_qa_expert.py
```

本任务不直接执行上述目标环境数据库变更。
