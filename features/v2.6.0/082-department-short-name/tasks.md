# 任务拆分 Tasks: F082 部门简称

## 元信息 Metadata

- Feature ID: `082-department-short-name`
- Status: `manual_verify_required`
- Related spec: `features/v2.6.0/082-department-short-name/spec.md`
- Created: `2026-08-10`
- Updated: `2026-08-21`

## 状态

| 阶段 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户于 2026-08-10 通过 SDD 暂停点 2 |
| tasks.md | ✅ 已增量拆解 | 原 13 个任务保留，新增历史简称回填 T014～T016 |
| 实现 | ⚠️ 主体及回填脚本完成，环境门禁待验收 | 12 / 16 完成；T003、T011～T013 未完成 |
| verification.md | ⚠️ 待人工门禁 | 已记录自动证据、环境限制和人工步骤 |

## 开发与验证模式

- **迁移 Test-First**：T001 先建立 upgrade/downgrade 回归，T002 再增加 migration 和 ORM 字段。
- **后端 Test-First**：T004/T005 分别锁定部门公开契约和两条同步路径，T006 再实现 DTO/Service。
- **前端 Test-Alongside**：创建表单和设置表单各自与对应 Vitest 放在同一原子任务中。
- **最小回归**：同类空值参数化；同步只覆盖 F009 对象更新和 F014/F015 DAO upsert 两条独立路径。
- **E2E 门禁**：只增加一条“创建 → 查询 → 更新 → 清空”场景，边界输入留在后端定向测试。
- **范围边界**：不新增依赖、端点、错误码、索引或唯一约束；不修改组织树、搜索、权限和 Client 前端。
- **回填 Test-First**：T014 先锁定精确父前缀、跨租户/来源、保护、dry-run/apply 和幂等行为，T015 再实现独立脚本与运行文档。
- **数据安全**：脚本默认 dry-run；测试和实现阶段不得对真实数据库运行 `--apply`，正式 apply 必须在 dry-run、备份和独立确认后由运维执行。

## 依赖图

```text
T001 migration regression
  └─→ T002 migration + ORM
        ├─→ T003 legacy fixture parity
        │     └─→ T004 department contract tests
        └─→ T005 sync preservation tests
                T004 + T005 ─→ T006 backend implementation
                                  └─→ T007 Platform types
                                        ├─→ T008 create form + test
                                        └─→ T009 settings form + test
                                              T008 + T009 ─→ T010 i18n
                                  T006 ─→ T011 E2E
                                              T010 + T011 ─→ T012 backend verification
                                                                   └─→ T013 Platform/final verification

T002 + T005 ─→ T014 backfill contract tests
                  └─→ T015 backfill script + docs
                        └─→ T016 script verification evidence
```

---

## 基础设施：数据库迁移与测试契约

- [x] T001 建立部门简称迁移回归
  - Files: `src/backend/test/core/database/test_department_short_name_migration.py`（新建）
  - Logic:
    - 加载目标 migration，断言 revision/down revision、字段名、`VARCHAR(64)`、nullable、无 server default、无索引和无数据回填。
    - 临时数据库先插入历史部门行；upgrade 后历史行简称为 `NULL`，重复 upgrade 不重复加列。
    - downgrade 只删除 `short_name`，其他字段和历史行保留。
    - migration 尚未实现时必须因模块/字段缺失产生正确红灯，不得跳过或放宽断言。
  - Test context: 复用 `test/core/database/` 现有 migration 测试模式，不连接真实生产数据库。
  - 覆盖 AC: AC-01, AC-02
  - Done when: 红灯原因与缺少 F082 migration 一致，且测试不复制 migration 内部实现。
  - _Requirements: REQ-001_
  - _Acceptance: AC-01, AC-02_
  - _Verification: V-DB-01_
  - _Depends: none_
  - _Boundary: tests only under `src/backend/test/core/database/`_

- [x] T002 实现 additive migration 与 Department ORM 字段
  - Files:
    - `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f082_department_short_name.py`（新建）
    - `src/backend/bisheng/database/models/department.py`（修改）
  - Logic:
    - 实现前运行 `uv run alembic heads`，`down_revision` 指向当时唯一 head；若不再是 `f081_knowledge_file_original_origin`，记录到“实际偏差记录”，不得产生第二个 head。
    - Upgrade 使用 SQLAlchemy `inspect()` 幂等增加 `short_name VARCHAR(64) NULL`；无 default、回填、索引或方言专属 SQL。
    - Downgrade 在字段存在时删除字段；注释明确删列会丢失简称数据。
    - ORM 增加 `short_name: str | None`，使用 `String(64)`、`nullable=True`，现有构造路径不传时自然为 `None`。
  - Done when: T001 通过，Alembic 保持单 head，ORM 与 migration 的字段类型/nullability 一致。
  - _Requirements: REQ-001, REQ-005_
  - _Acceptance: AC-01, AC-02, AC-05_
  - _Verification: V-DB-01, V-REG-01_
  - _Depends: T001_
  - _Boundary: one migration and Department ORM field only_

- [ ] T003 对齐 legacy 部门测试 fixture
  - Files:
    - `src/backend/test/test_department_api.py`（修改）
    - `src/backend/test/test_department_service.py`（修改）
  - Logic:
    - 仅在文件内手写的 `department` SQLite DDL 中增加 `short_name VARCHAR(64)`。
    - 同步和异步 API fixture 必须保持同构；不得顺手补齐其他历史字段或重构测试基础设施。
  - Test context: 这是 production ORM 与 sandbox/in-memory schema 的 parity 保护，避免测试因漏列产生假失败或假通过。
  - Done when: 两套相关 fixture 可加载新 ORM，现有部门 API/Service 用例仍能启动。
  - _Requirements: REQ-001, REQ-005_
  - _Acceptance: AC-05, AC-15_
  - _Verification: V-BE-01, V-REG-01_
  - _Depends: T002_
  - _Boundary: `department` DDL parity only in two legacy test files_

---

## 后端 Domain / API：Test-First

- [x] T004 建立部门简称公开契约回归
  - Files: `src/backend/test/department/test_department_short_name.py`（新建）
  - Logic:
    - 参数化创建的有效简称、字段缺失、`null`、空字符串和仅空白；断言响应和数据库的值/nullability。
    - 覆盖更新三态：缺失保持，非空去首尾空格，显式 `null`/空白清空。
    - 覆盖规范化后 64 字符接受、65 字符拒绝且旧值不变。
    - 覆盖两个部门同简称允许、同级完整名称重复仍拒绝、树节点仍以 `name` 为现有契约。
  - Test context: 从 FastAPI/Service 可观察边界断言最终状态，不复制 `model_fields_set` 或 Service 分支逻辑。
  - 覆盖 AC: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-15
  - Done when: T006 实现前测试按预期因 DTO/Service 尚未支持简称而失败。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-005_
  - _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-15_
  - _Verification: V-BE-01, V-REG-01_
  - _Depends: T003_
  - _Boundary: one backend department contract test file_

- [x] T005 建立两条组织同步简称保留回归
  - Files: `src/backend/test/sso_sync/test_department_short_name_preservation.py`（新建）
  - Logic:
    - F009 路径：已有简称的同步部门经 `OrgSyncService` 重命名对象更新后，`name` 更新、`short_name` 保留。
    - F014/F015 路径：已有简称的同步部门经 `DepartmentDao.aupsert_by_external_id` 更新/校对后，简称保留。
    - 两条路径共享最终状态断言；不为不同 provider 复制完整 suite，不扩展同步 DTO。
  - Test context: 测试字段级更新契约，避免 AI 把“同步部门名称只读”误推广为“简称由同步覆盖”。
  - 覆盖 AC: AC-13
  - Done when: 两条独立同步实现路径都有机械保护；若现有代码自然满足，可在 T006 不修改同步生产代码。
  - _Requirements: REQ-004_
  - _Acceptance: AC-13_
  - _Verification: V-SYNC-01_
  - _Depends: T002_
  - _Boundary: one sync regression test file; no production sync edits_

- [x] T006 实现后端创建、详情与更新简称契约
  - Files:
    - `src/backend/bisheng/department/domain/schemas/department_schema.py`（修改）
    - `src/backend/bisheng/department/domain/services/department_service.py`（修改）
  - Logic:
    - `DepartmentCreate` / `DepartmentUpdate` 接受可选 `short_name`，后端统一 trim、空值转 `None`、规范化后最大 64 字符。
    - 创建 Service 写入规范化值；创建、更新、详情沿用 ORM `model_dump()` 返回 `string | null`。
    - 更新通过 Pydantic 显式字段集合区分“未提交”和“显式清空”，不得用 `if data.short_name is not None`。
    - source-readonly 仍只限制 `name`；简称可按现有权限更新。归档只读检查仍先于所有写入。
    - 简称不得进入名称重复查询、树 schema、搜索、多租户条件或同步 DTO。
  - Done when: T004、T005 全部通过；若 T005 已通过，不修改同步生产代码。若失败，先更新 spec 的受影响文件再修复。
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-12, AC-13, AC-14, AC-15_
  - _Verification: V-BE-01, V-SYNC-01, V-REG-01_
  - _Depends: T004, T005_
  - _Boundary: Department DTO and Service only; no endpoint or sync DTO changes_

---

## 前端 Platform：Test-Alongside

- [x] T007 扩展 Platform 部门 API 类型
  - Files: `src/frontend/platform/src/types/api/department.ts`（修改）
  - Logic:
    - `DepartmentDetail.short_name: string | null`。
    - `DepartmentCreateForm` / `DepartmentUpdateForm` 支持可选 `short_name?: string | null`。
    - 不把简称加入 `DepartmentTreeNode` 的展示依赖。
  - Done when: 类型准确表达详情 nullability 和更新清空语义，不改变树契约。
  - _Requirements: REQ-002, REQ-003, REQ-005_
  - _Acceptance: AC-05, AC-07, AC-08, AC-15_
  - _Verification: V-FE-01, V-REG-01_
  - _Depends: T006_
  - _Boundary: one Platform API type file_

- [x] T008 实现创建部门简称输入与 payload 测试
  - Files:
    - `src/frontend/platform/src/pages/DepartmentPage/components/CreateDepartmentDialog.tsx`（修改）
    - `src/frontend/platform/src/test/createDepartmentShortName.test.tsx`（新建）
  - Logic:
    - 在部门名称下方增加可选简称输入，`maxLength={64}`。
    - 提交前 trim；有效值随创建请求提交，空值不得提交为非空字符串。
    - Vitest 断言控件顺序、有效 payload、空值行为和 64 字符 UI 边界。
  - Test context: 前端 Test-Alongside；mock 现有 API wrapper，不测试后端 validator 实现。
  - 覆盖 AC: AC-10
  - Done when: 目标 Vitest 通过，创建部门其他字段和管理员选择行为不变。
  - _Requirements: REQ-002, REQ-003_
  - _Acceptance: AC-10_
  - _Verification: V-FE-01_
  - _Depends: T007_
  - _Boundary: CreateDepartmentDialog and its focused Vitest only_

- [x] T009 实现部门设置简称状态与 payload 测试
  - Files:
    - `src/frontend/platform/src/pages/DepartmentPage/components/DepartmentSettings.tsx`（修改）
    - `src/frontend/platform/src/pages/DepartmentPage/components/DepartmentBasicInfoSection.tsx`（新建）
    - `src/frontend/platform/src/test/departmentSettingsPayload.test.tsx`（修改）
  - Logic:
    - 详情 `null` 回显为空输入；简称进入 baseline、变更检测、取消恢复、最小 payload 和保存后 baseline。
    - 未修改不提交；清空显式提交 `short_name: null`；保存有效值前 trim。
    - 同步部门名称 disabled、简称 enabled；归档部门简称 disabled。
    - Vitest 覆盖加载、修改、清空、未变化、同步可编辑和归档只读的可观察状态/payload。
  - Test context: 复用文件现有 API/UI mock；不引入新的测试 harness。
  - 覆盖 AC: AC-11, AC-12, AC-14
  - Done when: 目标 Vitest 通过，既有“只改名称不提交管理员”回归仍通过。
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-11, AC-12, AC-14_
  - _Verification: V-FE-01_
  - _Depends: T007_
  - _Boundary: DepartmentSettings, its basic-info subcomponent and existing focused Vitest only_

- [x] T010 补齐 Platform 三语简称文案
  - Files:
    - `src/frontend/platform/public/locales/zh-Hans/bs.json`（修改）
    - `src/frontend/platform/public/locales/en-US/bs.json`（修改）
    - `src/frontend/platform/public/locales/ja/bs.json`（修改）
  - Logic:
    - 三个文件增加同一组键：简称标签、可选占位符和 1～64 字符提示。
    - Create/Settings 只引用这些 i18n key，不硬编码用户文案。
    - 三个 locale 文件是同一原子翻译契约，集中修改可避免 key 集合漂移；不改 `dev` fallback 文件。
  - 覆盖 AC: AC-16
  - Done when: 三个 JSON 可解析、键集合一致，语言切换无 raw key。
  - _Requirements: REQ-002, REQ-005_
  - _Acceptance: AC-16_
  - _Verification: V-I18N-01_
  - _Depends: T008, T009_
  - _Boundary: exactly three Platform production locale files_

---

## 历史简称回填：Test-First

- [x] T014 建立历史部门简称回填契约回归
  - Files: `src/backend/test/scripts/test_backfill_department_short_names.py`（新建）
  - Logic:
    - 参数化纯解析规则：只接受直接父部门名称的区分大小写完整前缀，截取后 `strip()`，结果限定 1～64 字符；不做中间位置删除或祖先链推断。
    - 构造多个租户、`sg`/`local` 等不同来源的活动部门，证明候选扫描不受租户和来源限制。
    - 覆盖根部门、归档部门、父记录缺失/跨租户、父名称非前缀、父子同名、超长结果、已有非空白简称保护，以及空字符串/纯空白简称可回填。
    - dry-run 断言 `would_update` 与原因统计准确且数据库零写入；apply 断言只更新合法候选，再次运行时不产生额外更新。
    - 覆盖扫描后名称、父级、状态或简称发生变化时写前保护生效，不用旧快照覆盖新值。
  - Test context: 使用临时数据库或可注入 session 的最小集成边界，不连接真实环境；等价异常通过参数化表达，不复制脚本实现。
  - 覆盖 AC: AC-17, AC-18, AC-19, AC-20
  - Done when: T015 实现前测试因脚本模块缺失产生正确红灯；用例不依赖 MySQL/DM8 私有 SQL。
  - _Requirements: REQ-004, REQ-006_
  - _Acceptance: AC-17, AC-18, AC-19, AC-20_
  - _Verification: V-SCRIPT-01_
  - _Depends: T002, T005_
  - _Boundary: one focused test file under `src/backend/test/scripts/`; no production DB writes_

- [x] T015 实现全租户历史部门简称回填脚本与运行文档
  - Files:
    - `src/backend/scripts/backfill_department_short_names.py`（新建）
    - `src/backend/scripts/README.md`（修改）
  - Logic:
    - 提供可直接运行的 `argparse` 入口和模块说明；默认 dry-run，只有 `--apply` 才提交更新。
    - 在 `bypass_tenant_filter()` 下按 `Department.id` keyset 批次扫描所有租户、所有来源的活动部门；不引入 provider、租户或同步载荷特例。
    - 仅处理当前简称为 `NULL`、空字符串或纯空白的行；用直接父部门名称执行精确前缀解析，结果 `strip()` 后必须为 1～64 字符。
    - apply 在写入前复核当前名称、父级、状态和简称；已变化行按 `changed_before_update` 跳过，不覆盖人工值。
    - 输出 JSON：`mode`、`scanned`、`eligible`、`would_update`、`updated`、`skipped`、`reason_counts`、有界样例和最后扫描游标。
    - 数据异常按行跳过；数据库/事务失败回滚当前批次并返回非零退出码。脚本不自动运行、不提供反向批量清空。
    - README 记录从 `src/backend/` 执行的 dry-run/apply 示例、备份与独立确认要求、执行后再次 dry-run 的复核方式及无自动回滚风险。
  - Done when: T014 全部通过；`--help` 可用；脚本和 README 足以让运维先审计再执行，且没有真实数据库被修改。
  - _Requirements: REQ-004, REQ-006_
  - _Acceptance: AC-17, AC-18, AC-19, AC-20_
  - _Verification: V-SCRIPT-01_
  - _Depends: T014_
  - _Boundary: one backend operational script plus its README entry; no API, sync, migration, model, frontend or dependency changes_

- [x] T016 验证回填脚本并补充证据
  - Files:
    - `features/v2.6.0/082-department-short-name/verification.md`（增量补充）
    - `features/v2.6.0/082-department-short-name/tasks.md`（更新状态与实际偏差）
  - Logic:
    - 在同一代码状态下执行一次脚本聚焦测试、Ruff、语法检查、`--help` 和 Architecture Guard，并记录命令、结果及代码状态。
    - 复用现有同步简称保留证据；相关同步代码未变化时不重复运行整套组织同步测试。
    - 不在开发环境对真实数据库执行 `--apply`。真实 MySQL/DM8 dry-run、备份、apply 和执行后复核均记录为发布期 `MANUAL_REQUIRED`，直到运维提供证据。
    - 在 verification matrix 中补齐 AC-17～AC-20 与 V-SCRIPT-01；未运行项不得写成通过。
  - Commands:
    - `cd src/backend && uv run pytest test/scripts/test_backfill_department_short_names.py -q`
    - 对脚本与测试执行 `uv run ruff format --check`、`uv run ruff check` 和 `python -m py_compile`
    - `cd src/backend && PYTHONPATH=./ uv run python scripts/backfill_department_short_names.py --help`
    - `bash scripts/arch-guard.sh`
  - Done when: 自动化证据通过并写入 verification；真实数据库门禁有可执行步骤、风险和明确状态。
  - _Requirements: REQ-004, REQ-006_
  - _Acceptance: AC-17, AC-18, AC-19, AC-20_
  - _Verification: V-SCRIPT-01_
  - _Depends: T015_
  - _Boundary: focused script verification and evidence only; no real database apply_

---

## 回归与验收

- [ ] T011 增加单条部门简称 E2E 契约场景
  - Files: `src/backend/test/e2e/test_e2e_department_tree.py`（修改）
  - Logic:
    - 创建含简称部门 → GET 回显 → PUT 更新并回显 → PUT `null` 清空并回显。
    - 使用既有认证、根部门和清理机制；不在 E2E 重复空白、超长、同步或 i18n 边界。
  - Test context: 项目强制 E2E 门禁，用一条主路径证明真实 endpoint/serialization/database wiring。
  - 覆盖 AC: AC-03, AC-05, AC-06, AC-08
  - Done when: `uv run pytest test/e2e/test_e2e_department_tree.py -k short_name` 通过。
  - _Requirements: REQ-001, REQ-002, REQ-003_
  - _Acceptance: AC-03, AC-05, AC-06, AC-08_
  - _Verification: V-E2E-01_
  - _Depends: T006_
  - _Boundary: one existing backend E2E file_

- [ ] T012 执行后端相关回归并建立 verification evidence
  - Files: `features/v2.6.0/082-department-short-name/verification.md`（新建）
  - Logic:
    - 同一代码状态下各执行一次 migration、部门契约、同步保护、legacy 部门回归、E2E 和 Ruff。
    - `verification.md` 先记录 V-DB-01、V-BE-01、V-SYNC-01、V-REG-01、V-E2E-01 的命令、结果、跳过项和代码状态。
    - 记录 MySQL 实测；macOS 无 DM8 驱动时把真实 DM8 证据标为 `MANUAL_REQUIRED`，不得写成通过。
    - 记录发布顺序“先 migration 后应用”和回滚顺序“先应用后删列”，明确 downgrade 会丢失简称数据。
  - Commands:
    - `cd src/backend && uv run pytest test/core/database/test_department_short_name_migration.py test/department/test_department_short_name.py test/sso_sync/test_department_short_name_preservation.py`
    - `cd src/backend && uv run pytest test/test_department_api.py test/test_department_service.py -k department`
    - `cd src/backend && uv run pytest test/e2e/test_e2e_department_tree.py -k short_name`
    - 对 T001～T011 涉及的 Python 文件执行 `uv run ruff format --check` 与 `uv run ruff check`
  - Done when: 所有可运行后端证据已记录，MySQL/DM8 未运行项有明确状态和原因。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-13, AC-15_
  - _Verification: V-DB-01, V-BE-01, V-SYNC-01, V-REG-01, V-E2E-01_
  - _Depends: T010, T011_
  - _Boundary: backend and E2E verification evidence only_

- [ ] T013 执行 Platform 回归并完成最终验证收口
  - Files:
    - `features/v2.6.0/082-department-short-name/verification.md`（增量补充）
    - `features/v2.6.0/082-department-short-name/tasks.md`（更新状态与实际偏差）
  - Logic:
    - 在 T012 相同代码状态上执行目标 Vitest、相关部门页面回归、Platform build、三语 JSON/key 检查和 Architecture Guard，不重复运行 T012 后端命令。
    - 补齐 V-FE-01、V-I18N-01，并在 `verification.md` 形成全部 AC / Verification ID 的最终矩阵。
    - 未运行项必须标明原因；实现偏差回写本文件，范围变化则先更新 spec。
  - Commands:
    - `cd src/frontend/platform && npm test -- src/test/departmentSettingsPayload.test.tsx src/test/createDepartmentShortName.test.tsx`
    - `cd src/frontend/platform && npm run build`
    - 解析 `zh-Hans`、`en-US`、`ja` 的 `bs.json` 并比较本特性 key 集合
    - `bash scripts/arch-guard.sh`
  - Done when: 前后端证据矩阵完整，tasks 状态与实际结果一致，剩余风险和 `MANUAL_REQUIRED` 项可见。
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-10, AC-11, AC-12, AC-14, AC-16_
  - _Verification: V-FE-01, V-I18N-01_
  - _Depends: T012_
  - _Boundary: Platform/global verification evidence and task status only_

---

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Test Tasks | Implementation Tasks | Verification |
|-------------|---------------------|------------|----------------------|--------------|
| REQ-001 | AC-01, AC-02, AC-05 | T001, T004, T011 | T002, T003 | V-DB-01, V-BE-01, V-E2E-01 |
| REQ-002 | AC-03, AC-04, AC-05, AC-06, AC-10, AC-11 | T004, T008, T009, T011 | T006, T007 | V-BE-01, V-FE-01, V-E2E-01 |
| REQ-003 | AC-03, AC-04, AC-06, AC-07, AC-08, AC-09, AC-11 | T004, T009, T011 | T006, T007 | V-BE-01, V-FE-01, V-E2E-01 |
| REQ-004 | AC-12, AC-13, AC-20 | T005, T009, T014 | T006, T015 | V-SYNC-01, V-FE-01, V-SCRIPT-01 |
| REQ-005 | AC-12, AC-14, AC-15, AC-16 | T004, T009, T010 | T002, T003, T006, T007 | V-REG-01, V-FE-01, V-I18N-01 |
| REQ-006 | AC-17, AC-18, AC-19, AC-20 | T014 | T015 | V-SCRIPT-01 |

## 任务质量门 Task Quality Gate

- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one test task with explicit `覆盖 AC` and one verification entry.
- [x] Backend test tasks precede their paired implementation tasks.
- [x] Dependencies exist, are ordered and form an acyclic graph.
- [x] Each task is self-contained and normally touches one or two files; the three-locale task is one indivisible key-parity contract.
- [x] No task crosses backend and frontend boundaries.
- [x] Migration rollback and destructive downgrade impact are explicit.
- [x] Shared fixture changes are limited to schema parity and do not refactor legacy harnesses.
- [x] No task changes organization tree, search, permission, Client frontend, Worker or dependency scope.
- [x] Backfill test task precedes implementation and covers cross-tenant scope, exact parsing, dry-run, apply protection and idempotency.
- [x] Real database `--apply` is excluded from implementation/automated verification and remains an independently confirmed operational gate.

## 实际偏差记录

- 当前 Alembic head 与规划一致，F082 成为唯一新 head；未发生 migration 链偏差。
- T003 已在两套手写 DDL 中补充 `short_name`，但 legacy 套件仍因 fixture 缺少既有 `sync_parent_external_id` 等字段失败。遵守已确认边界，未顺手修复其他 Feature 的测试债，因此 T003 暂不勾选。
- 两条同步保留测试自然通过，未修改 F009/F014/F015 同步生产代码。
- T011 E2E 场景已实现并可收集，但本机 `localhost:7860` 未启动，实际执行连接失败；T011～T013 保持未完成，人工步骤见 `verification.md`。
- 项目 Prettier 配置存在 CommonJS/ESM 插件加载冲突；未修改工具链，Platform Vitest、build、JSON 解析与 `git diff --check` 均通过。
- T009 为满足 Platform 单文件不超过 600 行的硬规则，将原基础信息 JSX 提取为同目录 `DepartmentBasicInfoSection.tsx`；仅做行为保持拆分，未增加新的业务范围。
- 2026-08-21 用户新增历史部门简称回填需求。规格从“migration 无数据回填”扩展为“migration 仍不回填，另提供默认 dry-run 的独立人工脚本”；新增 REQ-006、AC-17～AC-20 和 T014～T016，未改变组织同步不得覆盖简称的既有契约。
- T014 首轮红灯因目标脚本模块不存在，原因与测试先行预期一致。补充事务失败用例后发现 SQLite 下逐行 savepoint 可能使同批已释放写入无法整体回滚；T015 改为显式批次事务，任何候选写入或 commit 异常均 rollback 当前批次后重新抛出。
- T014～T016 自动化已完成：脚本聚焦测试 9 passed；脚本与既有同步简称保护合并回归 11 passed；Ruff format/check、`py_compile`、`--help`、Architecture Guard 和 `git diff --check` 均通过。未连接真实数据库，未执行 dry-run 或 `--apply`。
