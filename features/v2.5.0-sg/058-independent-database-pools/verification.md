# 验证记录 Verification: SQLAlchemy 同步与异步连接池独立配置

## 阅读摘要

- 本文档记录 F058 的 Test-First 证据、自动化回归、静态检查、验收覆盖和未验证项。
- 配置解析、Engine 参数隔离、SQLite、MySQL/aiomysql、DM URL、事件循环隔离和 Docker 样例均有自动化证据。
- 当前 macOS 环境没有 DM8 驱动，真实 DM8 启动验证保持 `MANUAL_REQUIRED`；自动化测试不连接真实数据库。
- 三个既有基础设施文件的全文件 Ruff 历史债务可在 `HEAD` 基线复现；本次修改区间和关键错误规则检查通过，未扩大为无关格式化。

## 元信息 Metadata

- Feature ID: `058-independent-database-pools`
- Status: `implemented-manual-verification-required`
- Related requirements and design: [`spec.md`](./spec.md)
- Related tasks: [`tasks.md`](./tasks.md)
- Created: `2026-07-20`
- Updated: `2026-07-20`

## 验证摘要 Verification Summary

- Overall status: `MANUAL_VERIFY_REQUIRED`
- Completed tasks: `T001, T002, T003, T004, T005, T006, T007`
- Remaining tasks: `none`
- Blocked tasks: `none`
- Automated acceptance: `AC-01` 至 `AC-09`、`AC-11`、`AC-12` 为 `PASS`
- Manual acceptance: `AC-10` 的真实 DM8 启动验证为 `MANUAL_REQUIRED`

## 已执行命令 Commands Run

| Command | Purpose | Exit Code | Result | Evidence |
|---|---|---:|---|---|
| `.venv/bin/python -m pytest test/core/test_database_pool_config.py -q` | T001 配置解析 RED | 1 | PASS（预期 RED） | `7 failed, 3 passed`；旧模型缺少两套独立输出 |
| `.venv/bin/python -m pytest test/core/test_database_pool_config.py -q` | T002 配置解析 GREEN | 0 | PASS | `10 passed` |
| `.venv/bin/python -m pytest test/core/test_database_pool_config.py -q` | T003 参数路由 RED | 1 | PASS（预期 RED） | `4 failed, 7 passed`；共享参数仍存在于 Context/Manager/Connection |
| `.venv/bin/python -m pytest test/core/test_database_pool_config.py -q` | T004 参数路由 GREEN | 0 | PASS | `11 passed` |
| `.venv/bin/python -m pytest test/core/test_database_pool_config.py::test_docker_config_declares_independent_pool_defaults -q` | T005 Docker 样例 RED | 1 | PASS（预期 RED） | 旧样例解析为 `100+20`，不符合新默认值 |
| `.venv/bin/python -m pytest test/core/test_database_pool_config.py -q` | T006 最终连接池定向测试 | 0 | PASS | `12 passed in 1.82s` |
| `.venv/bin/python -m pytest test/core/test_database_pool_config.py test/celery/test_celery_async_runtime.py test/test_dm_dialect_helpers.py -q` | 连接池、事件循环和方言回归 | 0 | PASS | `66 passed in 6.46s`；另有 3 条既有 `__new__` 测试对象析构警告 |
| `.venv/bin/python -m pytest test/core -q` | 后端 core 回归 | 0 | PASS | `16 passed in 1.76s` |
| `.venv/bin/python -m ruff format --check bisheng/core/config/settings.py test/core/test_database_pool_config.py` | 完整检查新模型与测试格式 | 0 | PASS | `2 files already formatted` |
| `ruff format --check --range=...`（Context/Manager/Connection 三个改动区间） | 避免扩大既有文件格式差异 | 0 | PASS | 三个文件各输出 `1 file already formatted` |
| `.venv/bin/python -m ruff check bisheng/core/config/settings.py test/core/test_database_pool_config.py` | 完整 lint 新模型与测试 | 0 | PASS | `All checks passed!` |
| `.venv/bin/python -m ruff check --select E4,E7,E9,F <modified-python-files>` | 检查全部修改文件的语法、导入错误和未定义名称 | 0 | PASS | `All checks passed!` |
| `.venv/bin/python -m ruff check --output-format concise bisheng/core/context/manager.py bisheng/core/database/manager.py bisheng/core/database/connection.py` | 记录全文件既有 Ruff 债务 | 1 | FAIL（基线已存在） | 当前 32 项；`HEAD` 基线分别为 21/9/9，共 39 项，本次未新增 |
| `.venv/bin/python -m ruff format --check <three-legacy-infrastructure-files>` | 记录全文件既有格式债务 | 1 | FAIL（基线已存在） | 三个文件在 `HEAD` 基线同样返回 1；本次仅格式化修改区间 |
| `bash scripts/arch-guard.sh` | 架构边界检查 | 0 | PASS | 无违规输出 |
| `git diff --check -- <F058-tracked-files>` | 空白和补丁格式检查 | 0 | PASS | 无输出 |
| `rg -n "database_pool:" <declared-yaml-files>` | 配置样例范围检查 | 0 | PASS | 仅 `docker/bisheng/config/config.yaml` 显式声明并被修改 |
| `.venv/bin/python -c "import importlib.util; ..."` | 检查覆盖率工具可用性 | 0 | PASS | `pytest_cov=False`、`coverage=False`；未新增依赖 |

## 验收覆盖 Acceptance Coverage

| Acceptance ID | Requirement | Verification Method | Evidence | Status |
|---|---|---|---|---|
| AC-01 | REQ-001 | V-AC-01 | 默认值与空对象测试，最终定向测试 `12 passed` | PASS |
| AC-02 | REQ-002 | V-AC-02 | 部分旧扁平字段同时覆盖两套配置 | PASS |
| AC-03 | REQ-001 | V-AC-03 | 仅同步/仅异步及部分专属配置测试 | PASS |
| AC-04 | REQ-002 | V-AC-04 | 混合配置逐字段优先级测试 | PASS |
| AC-05 | REQ-001 | V-AC-05 | 两套完整五字段配置测试 | PASS |
| AC-06 | REQ-003 | V-AC-06 | Context 捕获测试及实际 sync/async pool 属性断言 | PASS |
| AC-07 | REQ-003 | V-AC-07 | `sync_get_database_connection()` fallback 参数路由与 Alembic `engine` 路径检查 | PASS |
| AC-08 | REQ-005 | V-AC-08 | 完整 Docker YAML 解析后通过 `Settings` 基类验证两套值；`ConfigService` 继承该模型且不覆盖初始化 | PASS |
| AC-09 | REQ-004 | V-AC-09 | 同步/异步 SQLite Engine 创建与释放测试 | PASS |
| AC-10 | REQ-004 | V-AC-10、V-MANUAL-01 | MySQL charset、aiomysql pre-ping、DM URL 自动化通过；真实 DM8 未在 macOS 执行 | MANUAL_REQUIRED |
| AC-11 | REQ-002 | V-AC-11 | 完整旧扁平 `100+20` 同时作用两套配置 | PASS |
| AC-12 | REQ-004 | V-AC-12 | 事件循环隔离回归、同步/异步关闭调用及清理代码路径检查 | PASS |

## 人工验证 Manual Verification

| Acceptance ID | Manual Steps | Expected Result | Actual Result | Status |
|---|---|---|---|---|
| AC-10 | 在 Linux/CI 安装项目锁定的 `dmPython` / `dmAsync` 驱动，分别使用差异化 sync/async pool 参数启动数据库上下文；检查两套 Engine pool 属性，执行一次同步与异步 `SELECT 1`，最后关闭上下文 | 两套 Engine 使用各自参数；DM sync URL 去除 schema、async URL 保留现有转换；查询与释放成功 | 当前 macOS 无 DM8 驱动，未执行 | NOT_RUN |

## 失败与缺口 Failures and Gaps

- 真实 DM8 集成未执行，原因是项目明确不在 macOS 安装 DM8 驱动；需要 Linux/CI 环境完成 V-MANUAL-01。
- `.venv` 未安装 `pytest-cov` 或 `coverage`，未生成覆盖率百分比；本次未为测试临时新增项目依赖。
- 全文件 Ruff 检查在三个历史基础设施文件上仍为非零；基线原有 39 项，当前为 32 项。所有本次修改区间已格式化，完整的新模型/测试 lint 以及全部修改文件的 E4/E7/E9/F 检查通过。
- `test_dm_dialect_helpers.py` 有 3 条既有 `PytestUnraisableExceptionWarning`：测试通过 `__new__` 构造未初始化对象，析构时缺少 `_engine`；该问题与连接池独立配置无关，未扩大范围修复。
- 直接导入 `ConfigService` 会触发模块级完整应用配置初始化，首次 T005 测试因此被终止；最终测试改为解析完整 Docker YAML 并交给 `ConfigService` 的 `Settings` 基类验证，同时静态确认 `ConfigService.load_settings_from_yaml()` 最终调用 `ConfigService(**settings_dict)`。

## SDD 合规复核

- 代码与配置改动仅覆盖 `spec.md` §8 声明的 6 个文件。
- 未新增依赖、数据库迁移、HTTP API、业务模型、错误码或其他 YAML 修改。
- 合并顺序与 AD-03 一致：Engine 默认值 → 旧扁平覆盖 → Engine 专属覆盖。
- Context、DatabaseManager 和 DatabaseConnectionManager 全链路保持两套配置显式分离。
- SQLite、MySQL/aiomysql、DM URL、事件循环隔离和关闭释放逻辑未被重构。
- 工作区中已有的门户、Celery schedule 和前端修改未被修改、格式化或暂存。

## 验证质量门 Verification Quality Gate

- [x] Every acceptance criterion has a status.
- [x] Every completion claim is backed by fresh evidence.
- [x] Test/build/lint/smoke commands include actual result summaries.
- [x] Manual-required checks include clear steps.
- [x] Failures are reported without claiming success.
