# 验证记录 Verification: F082 部门简称

## 元信息 Metadata

- Feature ID: `082-department-short-name`
- Overall Status: `MANUAL_VERIFY_REQUIRED`
- Code State: `2026-08-21 local worktree (uncommitted)`
- Verified At: `2026-08-10`（原范围）；`2026-08-21`（历史简称回填增量）
- Environment: macOS；本机无 DM8 驱动，`localhost:7860` 未启动后端

## 结论

部门简称的 migration、ORM、DTO、Service、两条同步保留路径、Platform 创建/设置表单、三语文案和 E2E 场景代码均已实现。迁移/后端定向测试共 14 个用例通过，Platform 定向测试共 8 个用例通过，Platform production build 通过。

最终状态保留为 `MANUAL_VERIFY_REQUIRED`，原因是当前环境不能提供真实 MySQL/DM8 升降级证据，也未运行所需的本地后端服务，因此 HTTP E2E 只能完成收集验证，实际执行在健康检查阶段连接失败。

2026-08-21 新增的 REQ-006 历史简称回填范围已实现：脚本默认 dry-run，跨所有租户和来源扫描，使用同租户直接父部门精确前缀派生简称，保护已有值并在 apply 写入前复核当前数据。新增聚焦测试 9 个通过，和既有同步简称保护合并回归共 11 个通过。

真实 MySQL/DM8 数据库仍未运行该脚本的 dry-run 或 `--apply`，也没有修改任何真实部门数据；发布期运行证据继续标记为 `MANUAL_REQUIRED`。

## Evidence

| Evidence | Result | Command / Step | Scope |
|----------|--------|----------------|-------|
| E-001 | PASS (expected red) | `uv run pytest test/core/database/test_department_short_name_migration.py -q`（实现前） | 2 个用例分别因 migration 模块和 ORM 字段缺失失败，确认红灯原因正确 |
| E-002 | PASS | `uv run pytest test/core/database/test_department_short_name_migration.py -q` | 2 passed；upgrade 幂等、历史 `NULL`、downgrade、MySQL/DM 兼容 DDL |
| E-003 | PASS | `uv run pytest test/core/database/test_department_short_name_migration.py test/department/test_department_short_name.py test/sso_sync/test_department_short_name_preservation.py -q` | 14 passed；创建/更新三态、64 字符边界、同步保留 |
| E-004 | PASS | `npm test -- src/test/departmentSettingsPayload.test.tsx src/test/createDepartmentShortName.test.tsx` | 8 passed；创建 payload、设置回显/修改/清空、同步可编辑、归档只读 |
| E-005 | PASS | `npm run build` | Platform production build 成功；仅有项目既有 chunk/eval/Browserslist warning |
| E-006 | PASS | 三语 JSON 解析及 F082 key 集合比对 | `zh-Hans`、`en-US`、`ja` 各 3 个 key 完整一致 |
| E-007 | PASS | `bash scripts/arch-guard.sh` 与 `git diff --check` | Architecture Guard 无违规；diff whitespace 检查通过 |
| E-008 | PASS | `uv run ruff check ...`、`python -m py_compile ...`、`uv run alembic heads` | F082 Python 文件通过定向 lint/语法检查；唯一 head 为 `f082_department_short_name` |
| E-009 | PASS (collection) | `uv run pytest test/e2e/test_e2e_department_tree.py -k short_name --collect-only -q` | 唯一 F082 E2E 场景成功收集 |
| E-010 | MANUAL_REQUIRED | `uv run pytest test/e2e/test_e2e_department_tree.py -k short_name -q` | `localhost:7860` 连接被拒绝，未进入业务断言 |
| E-011 | FAIL (pre-existing harness drift) | `uv run pytest test/test_department_api.py test/test_department_service.py -q` | 18 passed、36 failed；首个 ORM 错误是 fixture 缺少既有 `sync_parent_external_id`，并非 F082 `short_name` |
| E-012 | NOT_RUN | `npx prettier --write ...` | 项目 CommonJS Prettier 配置无法 `require()` ESM `prettier-plugin-tailwindcss`；未改配置，使用 build、Vitest 和 diff check 替代 |
| E-013 | PASS (expected red) | `uv run --python=.venv/bin/python pytest test/scripts/test_backfill_department_short_names.py -q`（实现前） | 测试收集因 `backfill_department_short_names` 模块不存在失败，红灯原因与 T014 一致 |
| E-014 | PASS (regression caught) | 新增同批第二条写入失败用例（修复前） | 8 passed、1 failed；证明逐行 savepoint 无法满足批次整体回滚，随后改为显式批次 rollback |
| E-015 | PASS | `uv run --python=.venv/bin/python pytest test/scripts/test_backfill_department_short_names.py test/sso_sync/test_department_short_name_preservation.py -q` | 11 passed；精确父前缀、跨租户/来源、dry-run、apply、保护/跳过、写前漂移、批次回滚、幂等及同步保留 |
| E-016 | PASS | 定向 `ruff format --check`、`ruff check`、`py_compile`、脚本 `--help`、`bash scripts/arch-guard.sh`、`git diff --check` | 新脚本与测试格式/静态/语法/CLI/架构门禁通过；未发现 MySQL 专属或 DM8 禁止 SQL |

## Acceptance Coverage

| Acceptance | Status | Evidence | 说明 |
|------------|--------|----------|------|
| AC-01 | MANUAL_REQUIRED | E-002, E-008 | SQLite upgrade 与 DDL 编译通过；真实 MySQL/DM8 尚待执行 |
| AC-02 | MANUAL_REQUIRED | E-002 | SQLite downgrade 通过；真实数据库降级尚待执行 |
| AC-03 | PASS | E-003 | 创建时 trim 并持久化 |
| AC-04 | PASS | E-003 | 省略、`null`、空串、空白统一为 `null` |
| AC-05 | PASS | E-002, E-003 | ORM/序列化公开 `string | null` |
| AC-06 | PASS | E-003 | 更新有效简称并返回规范化值 |
| AC-07 | PASS | E-003 | 更新省略字段时保持原值 |
| AC-08 | PASS | E-003 | `null`、空串、空白清空为 `NULL` |
| AC-09 | PASS | E-003 | 64 字符接受、65 字符被 Pydantic 拒绝 |
| AC-10 | PASS | E-004, E-005 | 创建表单字段顺序、边界与 payload 通过 |
| AC-11 | PASS | E-004, E-005 | 设置回显、修改、清空和最小 payload 通过 |
| AC-12 | PASS | E-003, E-004 | 同步部门名称禁用，简称允许更新 |
| AC-13 | PASS | E-003 | F009 对象更新与 F014/F015 DAO upsert 均保留简称 |
| AC-14 | PASS | E-004 | 归档部门名称和简称均禁用 |
| AC-15 | PASS | E-002, E-003, E-007 | 无简称索引/唯一约束，树 schema 和名称重复逻辑未改变 |
| AC-16 | MANUAL_REQUIRED | E-006, E-005 | 三语 key/构建通过；浏览器实际切换尚待人工 smoke |
| AC-17 | PASS | E-015 | 临时数据库证明默认 dry-run 跨租户/来源扫描且零写入 |
| AC-18 | PASS | E-015 | 精确父前缀 apply 得到预期简称，再次 dry-run 为零候选 |
| AC-19 | PASS | E-015 | 归档、根、已有值、缺父/跨租户、非前缀、空/超长结果均分类跳过；合法行继续处理 |
| AC-20 | PASS | E-003, E-015 | 脚本重复执行不覆盖，既有同步重命名/upsert 继续保留简称 |

## 新增回填范围验证计划

| Verification | Status | Planned Evidence | Scope |
|--------------|--------|------------------|-------|
| V-SCRIPT-01 | PASS | E-013～E-016 | AC-17～AC-20 的自动化契约，不连接真实数据库 |
| V-SCRIPT-MANUAL | MANUAL_REQUIRED | 真实环境 dry-run 报告审核、数据库备份、独立 apply 确认、apply 后再次 dry-run 与抽样核对 | MySQL/DM8 实际数据与运维门禁 |

## 未完成门禁与人工步骤

1. 在测试 MySQL 数据库执行 `uv run alembic upgrade f082_department_short_name`，检查历史部门 `short_name IS NULL`，再执行一次 upgrade 验证幂等；验证后按环境策略恢复。
2. 在 Linux/CI 的 DM8 环境执行相同升级检查。macOS 不安装 `dmPython`/`dmAsync`，本机仅提供兼容 DDL 编译证据。
3. 启动已应用 F082 migration 的后端后执行：`uv run pytest test/e2e/test_e2e_department_tree.py -k short_name -q`。
4. 在 Platform 切换 `zh-Hans`、`en-US`、`ja`，确认简称标签、占位符和提示无 raw key。
5. legacy 部门测试 fixture 缺少 `sync_parent_external_id`、`concurrent_session_limit` 等既有字段，应由独立维护任务修复；F082 仅按确认范围补充 `short_name`。
6. 回填脚本正式执行前必须先保存全量 dry-run JSON，再经数据库备份和独立确认执行 `--apply`；当前实现/验证阶段没有连接真实数据库。
7. apply 后再次运行 dry-run，目标为 `would_update=0` 或仅剩审核确认的跳过项；分别抽样不同租户和不同 `source`，核对简称只来自直接父名称前缀。

## 发布与回滚

- 发布顺序：先执行 additive migration，再部署读取/写入 `short_name` 的应用版本。
- 回滚顺序：先回滚应用到不访问 `short_name` 的版本，再执行 downgrade。
- downgrade 会删除所有已保存的部门简称，属于数据丢失操作；生产环境优先通过新的 forward migration 回退，不建议直接降级。
