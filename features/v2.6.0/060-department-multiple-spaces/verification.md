# 验证报告 Verification: 一个部门绑定多个知识空间

## 元信息
- Feature ID: `060-department-multiple-spaces`
- Status: `verified-with-deployment-gates`
- Verified: `2026-07-16`
- Branch: `feat/2.5.0-sg`

## 结论
- 后端一部门多空间、管理员全量同步、共享目标解析与迁移脚本的定向回归通过。
- Client 本次直接相关的保存成功与错误保留抽屉两条契约通过。
- 未执行真实数据库 upgrade；DM8 真实 DDL 兼容性仍需 Linux/DM8 CI 验证。
- 用户已有 `src/backend/celerybeat-schedule.db` 修改保持为工作区既有变更，本次未编辑、重置或覆盖该文件。

## Test-First 证据
| 阶段 | 命令 / 结果 | 状态 |
|---|---|---|
| RED | `uv run --frozen pytest test/knowledge/test_department_multiple_spaces.py -q`；实现前因缺少 `DepartmentKnowledgeSpaceAmbiguousError` 在 collection 阶段失败 | expected failure |
| GREEN | 新增错误、resolver、迁移和一对多实现后，新测试首次 `6 passed` | pass |
| Final backend | 下方 7 个定向文件合并运行：`85 passed, 8 warnings` | pass |

## 实际执行记录

### 后端定向回归
```text
uv run --frozen pytest \
  test/knowledge/test_department_multiple_spaces.py \
  test/knowledge/test_department_space_rebind.py \
  test/test_department_knowledge_space_service.py \
  test/test_department_binding_admin.py \
  test/test_free_space_migration_target.py \
  test/test_free_space_migration_guard.py \
  test/open_endpoints/test_filelib_sync.py -q
```
- Exit code: `0`
- Result: `85 passed, 8 warnings in 4.60s`
- Warnings: 既有依赖的 deprecation/user warnings，无本次断言失败。

### 部门空间 Service 独立运行
```text
uv run --frozen pytest test/test_department_knowledge_space_service.py -q
```
- Exit code: `0`
- Result: `8 passed in 1.06s`
- 说明: 补齐该历史测试文件的 `WorkStationService` 隔离桩，消除对其他测试导入顺序的依赖。

### Client 本次契约定向运行
```text
npx jest src/pages/knowledge/portal/PortalKnowledgeWorkbench.test.tsx \
  --runInBand --runTestsByPath \
  -t '系统管理员保存部门知识库设置时使用权威更新响应回显新部门|部门重绑遇到其他后端错误时保留设置抽屉并展示错误'
```
- Exit code: `0`
- Result: `2 passed, 98 skipped`

### Client 整文件现状
```text
npm run test:ci -- src/pages/knowledge/portal/PortalKnowledgeWorkbench.test.tsx --runInBand
```
- Exit code: `1`
- Result: `60 passed, 40 failed`
- 判断: 本次修改的两条用例均通过；其余失败集中于既有 API 参数、页面结构和维护阈值断言，与 F060 变更无调用链关系，因此未扩大范围修复。

### 静态质量与编译
| 检查 | 结果 |
|---|---|
| `uv run ruff check` 新增 migration、resolver、F060 测试 | `All checks passed` |
| `uv run ruff format --check` 上述新增文件 | `3 files already formatted` |
| 修改文件 `ruff --select E,F,I --ignore E501` | `All checks passed`；忽略项仅为既有测试长行 |
| `python -m compileall -q` 本次生产 Python 文件 | Exit `0` |
| `scripts/arch-guard.sh` 逐个扫描本次生产文件 | Exit `0`，无输出 |
| `git diff --check` | Exit `0` |

### 迁移与静态调用检查
| 检查 | 结果 |
|---|---|
| `uv run alembic -c alembic.ini heads` | `f060_department_multiple_spaces (head)` |
| 搜索 `aget_by_department_id` / `aget_space_id_by_department_id` / `find_department_space` | 无命中 |
| 迁移 upgrade 单测 | 删除部门唯一约束、已有普通索引时不重复创建 |
| 迁移 downgrade 单测 | 无重复时恢复唯一约束；有重复时明确失败且不删除数据 |
| Live migration | 未执行 |

## Acceptance 覆盖
| Acceptance | 状态 | 证据 |
|---|---|---|
| AC-REQ-001-01..03 | PASS | rebind、批量同部门双空间、旧团队绑定、模型/迁移测试 |
| AC-REQ-002-01..03 | PASS | 集合查询、列表去重测试、单值方法静态搜索无命中 |
| AC-REQ-003-01..03 | PASS | 多空间新增/移除同步及中途失败传播测试 |
| AC-REQ-004-01..05 | PASS | resolver 优先级、父级回退、两类歧义、free migration/filelib 测试 |
| AC-REQ-005-01..03 | PASS (targeted) | Client 两条定向契约、后端权限回归；整文件既有失败另行记录 |
| AC-REQ-006-01..03 | PASS | migration upgrade/downgrade 单测 |
| AC-REQ-006-04 | PARTIAL | 使用 dialect helpers/SQLAlchemy，MySQL/DM8 专有 SQL 静态检查通过；DM8 真实 CI 未运行 |
| AC-REQ-006-05 | PASS | 未执行 live upgrade，用户既有数据库文件修改未触碰 |

## 部署前门禁
- 在 MySQL 预发布环境审查 DDL 锁表窗口并执行 migration dry run。
- 在 Linux/DM8 CI 验证 constraint/index introspection 与 DDL。
- 若需要 downgrade，先检查是否已出现重复 `department_id`；迁移会拒绝自动删除合法多绑定数据。
