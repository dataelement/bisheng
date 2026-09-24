# 任务拆分 Tasks: SQLAlchemy 同步与异步连接池独立配置

## 阅读摘要

- 本文档只规划 F058 的配置模型、Engine 参数路由、Docker 样例迁移、测试和验证证据。
- `spec.md` 是已确认的需求与设计权威来源；本文档中的 REQ ID 仅为其内容建立稳定追踪标识，不增加新范围。
- 实现顺序采用后端 Test-First：先写预期失败测试，再做最小实现使其通过。
- `tasks.md` 确认前不创建功能分支，不修改生产代码、测试或 Docker 配置。

## 元信息 Metadata

- Feature ID: `058-independent-database-pools`
- Version: `v2.5.0-sg`
- Status: `implemented-manual-verification-required`
- Mode: `spec-then-implement`
- Related requirements and design: [`spec.md`](./spec.md)
- Related release contract: [`../release-contract.md`](../release-contract.md)
- Created: `2026-07-20`
- Updated: `2026-07-20`

## 状态

| 阶段 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已确认 | 用户于 2026-07-20 明确“确认 spec” |
| tasks.md | ✅ 已确认 | 用户于 2026-07-20 明确“确认 tasks，开始实现” |
| 功能分支 | ✅ 已创建 | `feat/2.5.0-sg-058-independent-database-pools` |
| 实现 | ✅ 已完成 | 7 / 7 完成 |
| verification.md | 🟨 自动化通过 | 真实 DM8 验证为 MANUAL_REQUIRED |

## 需求索引 Requirement Index

| Requirement | 已确认需求 | Spec 来源 |
|-------------|------------|-----------|
| REQ-001 | 同步与异步连接池分别具有五项参数和各自默认值：同步 `20+10`、异步 `40+20`，其余为 `30/3600/true` | §0、§2.1、AC-01、AC-03、AC-05 |
| REQ-002 | 兼容旧扁平配置，并按 Engine 默认值 → 扁平公共覆盖 → Engine 专属覆盖合并 | §2.2、§2.3、AC-02、AC-04、AC-11 |
| REQ-003 | 同步与异步 Engine 只接收各自最终参数；Alembic 继续使用同步 Engine 配置 | §0、§7、AC-06、AC-07 |
| REQ-004 | 保持 SQLite、MySQL、DM8 方言处理及 Engine 创建、事件循环隔离、关闭释放等生命周期行为 | §0、§4、§9、AC-09、AC-10、AC-12 |
| REQ-005 | 只将 `docker/bisheng/config/config.yaml` 的现有样例迁移为同步 `20+10`、异步 `40+20` 的嵌套配置 | §0、§8、AC-08 |

## 开发与验证约束

- 后端命令工作目录固定为 `src/backend/`，使用现有 `.venv/bin/python`。
- T001 开始前必须获得用户对本任务清单的确认和明确实施授权，并创建 F058 功能分支。
- 仅修改 `spec.md` §8 已列出的文件及本 Feature 的 SDD 文档；不得新增依赖、数据库迁移、API、业务模型或错误码。
- 配置兼容逻辑只在 `DatabasePoolConf` 收敛；Context、Manager 和 Connection 层保持同步、异步参数显式分离。
- 测试不得连接真实数据库；MySQL/DM8 行为使用现有 mock、URL 和方言专项测试验证。真实 DM8 验证在 Linux/CI 执行。
- 当前工作区已有的 `portal_config_service.py` 与 `celerybeat-schedule.db` 修改不属于本 Feature，任何任务不得修改、格式化、暂存或覆盖它们。

## 阶段 1：配置解析 Test-First

- [x] T001 编写同步/异步配置解析与旧配置兼容测试
  - Files: `src/backend/test/core/test_database_pool_config.py`
  - Done when: 测试覆盖无配置默认值、完整五字段嵌套配置、仅 `sync`、仅 `async`、部分专属配置、仅部分扁平配置、扁平与专属混用优先级，以及完整旧版 `100+20` 配置；测试在旧实现上以预期原因失败。
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-11_
  - _Verification: V-AC-01, V-AC-02, V-AC-03, V-AC-04, V-AC-05, V-AC-11_
  - _Depends: none_
  - _Boundary: tests only; no production or YAML changes_

- [x] T002 实现配置模型、默认值与三层合并规则
  - Files: `src/backend/bisheng/core/config/settings.py`
  - Done when: `DatabasePoolConf` 能解析 `sync`/`async`（含 Python 保留字 alias），分别输出两套完整 Engine kwargs；旧扁平字段保持可选公共覆盖语义，专属字段最后覆盖；T001 全部通过。
  - _Requirements: REQ-001, REQ-002_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-11_
  - _Verification: V-AC-01, V-AC-02, V-AC-03, V-AC-04, V-AC-05, V-AC-11_
  - _Depends: T001_
  - _Boundary: config model only; no Engine construction or sample YAML changes_

## 阶段 2：Engine 参数路由 Test-First

- [x] T003 编写同步/异步 Engine 参数隔离与兼容回归测试
  - Files: `src/backend/test/core/test_database_pool_config.py`
  - Done when: 测试证明 Context/Manager/Connection 将两套 kwargs 分别送入 `create_engine()` 与 `create_async_engine()`；Alembic 获取的同步连接使用同步参数；同步和异步 SQLite 继续过滤不兼容容量参数；Engine 关闭路径和异步事件循环隔离不回归；旧实现上的新增隔离断言以预期原因失败。
  - _Requirements: REQ-003, REQ-004_
  - _Acceptance: AC-06, AC-07, AC-09, AC-10, AC-12_
  - _Verification: V-AC-06, V-AC-07, V-AC-09, V-AC-10, V-AC-12_
  - _Depends: T002_
  - _Boundary: tests only; all Engine/database interactions mocked or use in-memory SQLite_

- [x] T004 实现 Context、Manager 与 Connection 的双配置传递
  - Files: `src/backend/bisheng/core/context/manager.py`, `src/backend/bisheng/core/database/manager.py`, `src/backend/bisheng/core/database/connection.py`
  - Done when: 三层接口显式持有并转发同步、异步 Engine kwargs；同步 Engine 仅合并同步配置，异步 Engine 仅合并异步配置；fallback、懒创建、按事件循环缓存、关闭释放、MySQL/aiomysql/DM8/SQLite 专属逻辑保持原行为；T003 全部通过。
  - _Requirements: REQ-003, REQ-004_
  - _Acceptance: AC-06, AC-07, AC-09, AC-10, AC-12_
  - _Verification: V-AC-06, V-AC-07, V-AC-09, V-AC-10, V-AC-12_
  - _Depends: T003_
  - _Boundary: database infrastructure parameter routing only; no business-layer or database schema changes_

## 阶段 3：Docker 配置样例 Test-First

- [x] T005 编写 Docker 样例解析与范围保护测试
  - Files: `src/backend/test/core/test_database_pool_config.py`
  - Done when: 测试从 `docker/bisheng/config/config.yaml` 加载 `database_pool`，断言同步 `20/10/30/3600/true` 与异步 `40/20/30/3600/true`；测试在扁平旧样例上以预期原因失败，并明确不要求其他 YAML 出现该配置块。
  - _Requirements: REQ-005_
  - _Acceptance: AC-08_
  - _Verification: V-AC-08_
  - _Depends: T004_
  - _Boundary: tests only; no YAML changes_

- [x] T006 迁移 Docker 连接池配置样例
  - Files: `docker/bisheng/config/config.yaml`
  - Done when: 仅将现有 `database_pool` 扁平样例替换为 `sync` 与 `async` 嵌套块，分别使用已确认的两套五字段默认值；T005 通过，其他 YAML 保持未修改。
  - _Requirements: REQ-005_
  - _Acceptance: AC-08_
  - _Verification: V-AC-08_
  - _Depends: T005_
  - _Boundary: one declared Docker sample only; no credentials, URLs, or unrelated settings changes_

## 阶段 4：验证与交付

- [x] T007 执行自动化验证、SDD review 与生成 `verification.md`
  - Files: `features/v2.5.0-sg/058-independent-database-pools/verification.md`, `features/v2.5.0-sg/058-independent-database-pools/tasks.md`
  - Done when: 记录每条命令、退出码和输出摘要；全部 AC 标记 PASS/FAIL/MANUAL_REQUIRED；完成连接池定向测试、相关数据库运行时回归、Ruff format/check、架构守卫、`git diff --check` 和范围审查；真实 DM8 验证明确标记 MANUAL_REQUIRED；仅依据新鲜证据勾选任务并记录实际偏差。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12_
  - _Verification: V-AC-01, V-AC-02, V-AC-03, V-AC-04, V-AC-05, V-AC-06, V-AC-07, V-AC-08, V-AC-09, V-AC-10, V-AC-11, V-AC-12, V-STATIC-01, V-MANUAL-01_
  - _Depends: T006_
  - _Boundary: verification and SDD status updates only; no real database connections or unrelated fixes_

## 验证方法 Verification Methods

| ID | 方法 | 自动化状态 |
|----|------|------------|
| V-AC-01 | Pydantic 配置测试断言两套默认五字段值 | 自动化 |
| V-AC-02 | 参数化测试断言部分旧扁平字段同时覆盖两套配置 | 自动化 |
| V-AC-03 | 参数化测试断言单侧/部分专属配置不影响另一侧 | 自动化 |
| V-AC-04 | 混合配置测试断言默认值 → 扁平 → 专属的逐字段优先级 | 自动化 |
| V-AC-05 | 完整嵌套配置测试断言十个独立字段均被保留 | 自动化 |
| V-AC-06 | mock Engine 工厂与实际 pool 属性断言同步/异步 kwargs 隔离 | 自动化 |
| V-AC-07 | `sync_get_database_connection()` / Alembic 路径检查断言只取同步 Engine | 自动化 + 代码路径检查 |
| V-AC-08 | 加载 Docker YAML 并通过配置模型断言两套样例值 | 自动化 |
| V-AC-09 | 同步/异步 SQLite Engine 创建和释放回归测试 | 自动化 |
| V-AC-10 | 现有 MySQL charset、aiomysql pre-ping、DM8 URL 专项测试与定向回归 | 自动化；真实 DM8 为 V-MANUAL-01 |
| V-AC-11 | 完整旧扁平 `100+20` 回归测试断言两套 Engine 均保持旧值 | 自动化 |
| V-AC-12 | Engine 懒创建、事件循环缓存与关闭释放测试/代码路径检查 | 自动化 + 代码路径检查 |
| V-STATIC-01 | Ruff format/check、`scripts/arch-guard.sh`、`git diff --check` 和允许文件范围审查 | 自动化 |
| V-MANUAL-01 | Linux/CI 使用真实 DM8 驱动启动并检查同步/异步 Engine；macOS 环境不执行 | MANUAL_REQUIRED |

### 计划验证命令

在 `src/backend/` 执行：

```bash
.venv/bin/python -m pytest test/core/test_database_pool_config.py -q
.venv/bin/python -m pytest test/core/test_database_pool_config.py test/celery/test_celery_async_runtime.py test/test_dm_dialect_helpers.py -q
.venv/bin/python -m ruff format --check bisheng/core/config/settings.py bisheng/core/context/manager.py bisheng/core/database/manager.py bisheng/core/database/connection.py test/core/test_database_pool_config.py
.venv/bin/python -m ruff check bisheng/core/config/settings.py bisheng/core/context/manager.py bisheng/core/database/manager.py bisheng/core/database/connection.py test/core/test_database_pool_config.py
```

在仓库根目录执行：

```bash
bash scripts/arch-guard.sh
git diff --check -- features/v2.5.0-sg/058-independent-database-pools src/backend/bisheng/core/config/settings.py src/backend/bisheng/core/context/manager.py src/backend/bisheng/core/database/manager.py src/backend/bisheng/core/database/connection.py src/backend/test/core/test_database_pool_config.py docker/bisheng/config/config.yaml
```

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|-------------|---------------------|-------|--------------|
| REQ-001 | AC-01, AC-03, AC-05 | T001, T002, T007 | V-AC-01, V-AC-03, V-AC-05 |
| REQ-002 | AC-02, AC-04, AC-11 | T001, T002, T007 | V-AC-02, V-AC-04, V-AC-11 |
| REQ-003 | AC-06, AC-07 | T003, T004, T007 | V-AC-06, V-AC-07 |
| REQ-004 | AC-09, AC-10, AC-12 | T003, T004, T007 | V-AC-09, V-AC-10, V-AC-12, V-MANUAL-01 |
| REQ-005 | AC-08 | T005, T006, T007 | V-AC-08 |

## 任务质量门 Task Quality Gate

- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task and verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit and preserve Test-First order.
- [x] Boundary annotations prevent unrelated code and configuration edits.
- [x] No task implements work outside the confirmed spec.
- [x] Real DM8 integration is explicitly MANUAL_REQUIRED for the current macOS environment.

## 实际偏差记录 Implementation Notes

> 实现期间仅记录已经发生的偏差。若偏差改变范围、行为、兼容性或验收标准，必须先更新规格并重新确认。

- Git 已存在 `feat/2.5.0-sg` 分支，无法创建 `feat/2.5.0-sg/058-independent-database-pools` 子引用；功能分支改为等价的 `feat/2.5.0-sg-058-independent-database-pools`。该偏差只影响分支名，不改变需求、设计、代码范围或验收标准。
- 本仓库采用组合式 `spec.md` 承载 requirements 与 design，未额外拆分通用 SDD Skill 默认的 `requirements.md` / `design.md`；该项目级适配不改变已确认内容和追踪关系。
- T005 首次直接导入 `ConfigService` 时触发模块级完整应用配置初始化并长期运行；最终自动化改为解析完整 Docker YAML 后交给同一 `Settings` 基类验证，并静态确认 `ConfigService.load_settings_from_yaml()` 的构造链路。验证目标与 AC-08 不变。
- 当前 `.venv` 未安装覆盖率插件；未新增依赖，验证以定向测试、core 回归、方言回归、Ruff、架构守卫和范围检查完成。真实 DM8 验证保持 `MANUAL_REQUIRED`。
