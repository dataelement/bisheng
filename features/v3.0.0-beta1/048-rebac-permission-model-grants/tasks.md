# Tasks: F048 ReBAC 权限模型与 Grant 升级

**关联规格**：[spec.md](./spec.md)
**设计入口**：[design.md](./design.md)
**版本**：v3.0.0-beta1
**功能分支**：`feat/v3.0.0-beta1/048-rebac-permission-model-grants`

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 本次迭代已进入 Design | 原 Spec 已确认；用户于 2026-08-13 指示按新增可见性需求更新 Design |
| design.md | 🔲 本次迭代待用户确认 | 单槽浅层 visible、停用保留已有授权、删除前清零绑定及旧系统单次迁移口径已完成 24 项复审，结果 LGTM；尚未取得本次 Design ★ |
| tasks.md | ⏸ 待 Design ★ 后更新 | 原 140 项已完成；本次可见性增量任务尚未拆解 |
| 实现 | ⏸ 本次迭代未开始 | 原 F048 功能与迁移脚本已完成；不得把 BENCH-01 原型当作本次生产实现 |

---

## 开发模式与硬边界

- 按 Wave 和依赖执行；同一 Wave 中无相互依赖的任务可以并行，但单个任务最多修改两个文件。
- 后端严格 Test-First：测试任务先产生失败断言，配对实现任务再使其通过。基础设施任务
  （ORM、错误码、配置、Alembic DDL）按模板例外置于最前。
- Alembic revision **只做 MySQL/DM8 DDL**；旧 Config、业务事实和 OpenFGA tuple 的数据迁移
  只从 `src/backend/scripts/migrate_f048_permission_data.py` 显式启动，禁止 lifespan/API/Celery 自动迁移。
- 升级沿用既有流程：更新镜像并启动；旧 model 下 API/Worker 进程只进入
  `MIGRATION_REQUIRED/NOT_READY`，应用自动拒绝非 health HTTP/WS，Celery/Linsight 暂停
  消费任务；运维从 backend 容器执行脚本，成功后重启服务并自动恢复访问/任务消费。
- 权限领域只消费业务 Service 生成的 `VerifiedPermissionTarget` 或迁移 DTO，不查询资源存在性、
  tenant、状态、父级或展示名称。
- Platform 与 Client 分开实现和测试；Platform 使用 Zustand/react-query v3/request wrapper，
  Client 使用 Recoil/react-query v4/request wrapper。
- Worker 权限调用沿用 Celery `before_task_publish` 注入 `tenant_id` header、
  `task_prerun` 恢复 `current_tenant_id` ContextVar 的链路；不得用默认 tenant 猜测调用范围。
- 本计划不使用“测试降级”；需要 OpenFGA、MySQL、DM8 的测试标为中央集成环境执行，但仍保留
  自动化断言，不把本 Feature 范围内验证延迟到未来。
- T001～T143 记录的是本次可见性增量前的已完成实现基线，其中关于 inactive fail closed、
  深层 visible 等描述不代表本次目标语义；待 Design ★ 确认后，必须新增任务成对修改测试与
  实现，不能把历史任务的完成标记当作单槽 visible/停用保留授权已经实现的证据。

### 跨 Feature 与共享文件影响

| 影响面 | 本计划约束 |
|---|---|
| F004/F006/F007/F008 | F048 直接替代旧资源四档、Config 模型与成员 UI；T126～T134 必须证明旧路径对已迁移资源不可达 |
| F017 shared resource | T063/T064 只保留精确 ID 跨 tenant 只读业务加载，不把 shared relation 改成普通 Grant |
| F018 owner transfer | 按 OQ-07 与 INV-25，T049/T050 删除交接 API；其他 owner 仍作为 ordinary source 并存 |
| F027/F036/F040 列表性能 | 原任务的“统一候选优先”结论已被本次 Design 取代；每个入口按代表性数据选择可见 ID 优先或业务候选优先，待 Design ★ 后新增任务 |
| `core/openfga/client.py` / `discovery.py` / `manager.py` | T017～T020 是共享运行时变更；llm_server/llm_model 只保留显式 legacy allowlist，其他资源禁止 dual；latest 只用于启动发现并必须匹配 SQL CURRENT Catalog |
| Constitution C4 | T027/T028 将 F048 原子路径切到 durable projection ledger；旧单 tuple 路径的 `failed_tuple` 不被误删 |

---

## Wave 1 — 基础设施（无测试配对）

### 基础设施

- [x] **T001：登记 F048 权限错误码**
  - **文件**：`src/backend/bisheng/common/errcode/permission.py`
  - **逻辑**：新增 25001～25013，分别表达非法动作、版本冲突、标准模型不可变、模型状态、
    越级授权、protected 变更、非法模式、发布未就绪、投影失败、迁移阻断、model 不匹配、
    impact 过期和 mutation 过大；保留 19000/19002 通用语义。
  - **依赖**：无

- [x] **T002：定义 F048 领域与 HTTP schema**
  - **文件**：`src/backend/bisheng/permission/domain/schemas/f048.py`,
    `src/backend/bisheng/permission/domain/schemas/__init__.py`
  - **逻辑**：定义 `VerifiedPermissionTarget`、Action/Model/Catalog DTO、Grant/assignee、
    mode draft、cursor、mutation 和 check response；客户端 payload 不接受 tenant、protected、
    source、等级或业务状态。
  - **依赖**：无

- [x] **T003：建立 Catalog/Action/Model ORM**
  - **文件**：`src/backend/bisheng/permission/domain/models/catalog.py`
  - **逻辑**：实现 `permission_catalog_release`、`permission_action`、
    `permission_action_resource_scope`、`permission_model`、`permission_model_action` 和
    `permission_catalog_projection_tuple`；动作和资源范围均规范化，不使用大 JSON。
  - **依赖**：无

- [x] **T004：建立 Grant/assignee/mode ORM**
  - **文件**：`src/backend/bisheng/permission/domain/models/grant.py`
  - **逻辑**：实现 `permission_grant`、`permission_grant_assignee`、
    `resource_permission_mode`；使用真实 `tenant_id`、稳定 `model_key`、source/protected/version
    字段及双库可移植唯一键。
  - **依赖**：无

- [x] **T005：建立 durable projection ORM**
  - **文件**：`src/backend/bisheng/permission/domain/models/projection.py`
  - **逻辑**：实现 `permission_projection_operation` 和 `permission_projection_tuple`，
    包含 PREPARED/STAGING/COMMIT_UNKNOWN/COMMITTED/FINALIZED/FAILED_CLOSED 状态、幂等 checksum
    与 inverse tuple，不保存超大 JSON。
  - **依赖**：无

- [x] **T006：建立 model release 与数据迁移审计 ORM**
  - **文件**：`src/backend/bisheng/permission/domain/models/migration.py`
  - **逻辑**：实现 `authorization_model_release`、`permission_migration_run`、
    `permission_migration_item`，记录同 Store source/target model、checkpoint、lease、
    source/target checksum、人工项与逐项状态；这些是 scripts 数据，不是 Alembic 状态。
  - **依赖**：无

- [x] **T007：注册 ORM 与 tenant 自动过滤**
  - **文件**：`src/backend/bisheng/permission/domain/models/__init__.py`,
    `src/backend/bisheng/core/database/tenant_filter.py`
  - **逻辑**：导出 T003～T006 模型，将 tenant 级 Grant/mode/operation/assignee 注册到
    `_TENANT_AWARE_MODEL_MODULES`；PLATFORM Catalog 和 migration run/item 只能由专用 Repository
    窄范围 bypass，不伪造 `tenant_id=0`。
  - **依赖**：T003, T004, T005, T006

- [x] **T008：创建 F048 DDL-only Alembic revision**
  - **文件**：`src/backend/bisheng/core/database/alembic/versions/f048_permission_model_grants.py`
  - **逻辑**：设置 `revision='f048_permission_grants'`、`down_revision='f044_llm_status_time'`，
    仅创建/删除 T003～T006 的表、索引、
    FK 和约束；`upgrade()/downgrade()` 不 SELECT、seed、backfill、dedup、cleanup，不 import
    Config、业务 Service、数据脚本或 OpenFGA。正式数据迁移后应用级 downgrade 不受支持。
  - **依赖**：T003, T004, T005, T006, T007

- [x] **T009：定义权限 Repository ports**
  - **文件**：`src/backend/bisheng/permission/domain/repositories/interfaces.py`,
    `src/backend/bisheng/permission/domain/repositories/__init__.py`
  - **逻辑**：声明 Catalog、Grant、mode、projection、migration run/item 的事务、cursor、
    version CAS 和 checksum 接口；不暴露业务资源 Repository。
  - **依赖**：T002, T003, T004, T005, T006

- [x] **T010：收敛 OpenFGA 连接配置与生产启动门禁**
  - **文件**：`src/backend/bisheng/core/config/openfga.py`
  - **逻辑**：配置只保留连接信息、稳定 Store name 和 recent-consistency window；
    Store/model/Catalog ID 与 checksum 不写配置；生产模式拒绝自动建 Store/写 model、
    legacy model 和 dual model。
  - **依赖**：无

---

## Wave 2 — 后端 Domain 与 OpenFGA 核心

### 后端 Domain（Test-First）

- [x] **T011：DDL/ORM 双库合同测试**
  - **文件**：`src/backend/test/permission/test_f048_schema_contract.py`
  - **测试**：断言表、FK、唯一键、tenant 注册、Alembic 单 head；静态拒绝 revision 中的
    SELECT/DML、业务 import、Config/OpenFGA/数据脚本调用，并在 CI 对 MySQL/DM8 upgrade 验证。
  - **覆盖 AC**：AC-137, AC-138, AC-139, AC-140, AC-146, AC-158
  - **依赖**：T003, T004, T005, T006, T007, T008

- [x] **T012：Repository 幂等、版本和租户合同测试**
  - **文件**：`src/backend/test/permission/test_f048_repositories.py`
  - **测试**：验证 Grant 唯一性、assignee source 去重、cursor/version CAS、projection idempotency、
    migration environment lease、item checkpoint 与窄 tenant bypass。
  - **覆盖 AC**：AC-19, AC-25, AC-27, AC-68, AC-93, AC-94, AC-143, AC-147
  - **依赖**：T004, T005, T006, T007, T009

- [x] **T013：实现 Catalog 与 Grant Repository**
  - **文件**：`src/backend/bisheng/permission/domain/repositories/catalog_repository.py`,
    `src/backend/bisheng/permission/domain/repositories/grant_repository.py`
  - **逻辑**：实现 current release `FOR UPDATE`、完整 draft、影响 cursor、Grant/assignee
    唯一来源、版本 CAS 和 cursor；只操作权限表。
  - **验收**：T012 对 Catalog/Grant 的断言通过
  - **依赖**：T012

- [x] **T014：实现 projection 与 migration Repository**
  - **文件**：`src/backend/bisheng/permission/domain/repositories/projection_repository.py`,
    `src/backend/bisheng/permission/domain/repositories/migration_repository.py`
  - **逻辑**：实现 operation/tuple ledger、commit 状态、environment lease、run/item checkpoint、
    checksum 和人工项；migration Repository 的 bypass 只包裹明确的跨 tenant cursor。
  - **验收**：T012 全部通过
  - **依赖**：T012

- [x] **T015：F048 Authorization Model 语义测试**
  - **文件**：`src/backend/test/permission/test_f048_authorization_model.py`
  - **测试**：对真实 model JSON 跑标准/自定义动作、Catalog/model active、Grant 多来源、
    grant-level、protected、CUSTOM/INHERIT、canonical parent、department userset、system/shared、
    dashboard 与 permission_enabled 语义。
  - **覆盖 AC**：AC-02, AC-04, AC-07, AC-08, AC-15, AC-19, AC-20, AC-21, AC-22, AC-26, AC-28, AC-29, AC-33, AC-36, AC-37, AC-38, AC-39, AC-40, AC-41, AC-45, AC-46, AC-47
  - **依赖**：T002

- [x] **T016：实现 F048 Authorization Model builder**
  - **文件**：`src/backend/bisheng/core/openfga/authorization_model_f048.py`
  - **逻辑**：构建 CatalogRelease→ModelRelease→Grant 三层交集、具体 `can_<action>`、
    visible、grant-level、mode gate、protected、department subtree、canonical parent、
    system/shared/dashboard 关系和稳定 checksum；不自动发布。
  - **验收**：T015 全部通过
  - **依赖**：T015

- [x] **T017：OpenFGA client model pin 与一致性测试**
  - **文件**：`src/backend/test/permission/test_f048_fga_client.py`
  - **测试**：验证 Check/BatchCheck/List/Write 显式 model ID、Store-scoped Read/Delete、
    higher consistency、100 服务上限与 90 业务上限；拒绝 shadow write 和 legacy client。
  - **覆盖 AC**：AC-30, AC-31, AC-32, AC-34, AC-69, AC-109, AC-111, AC-112
  - **依赖**：T010, T016

- [x] **T018：升级 OpenFGA client**
  - **文件**：`src/backend/bisheng/core/openfga/client.py`
  - **逻辑**：提供显式 model-scoped Check/BatchCheck/List/Write 与 consistency 参数；
    Read/Delete 仅按 Store tuple key；删除 dual/shadow write，编译 delta 超过 90 由上层拒绝。
  - **验收**：T017 全部通过
  - **依赖**：T017

- [x] **T019：FGAManager 自动发现/readiness 测试**
  - **文件**：`src/backend/test/permission/test_f048_openfga_manager.py`
  - **测试**：生产按 Store name 只接受唯一 Store并选最新 model；拒绝重名、缺失、
    checksum/CURRENT Catalog 不匹配、bootstrap、dual/legacy；readiness 暴露实际
    Store/new model/Catalog/cache window 和 instance heartbeat。
  - **覆盖 AC**：AC-16, AC-34, AC-99, AC-100, AC-102, AC-108, AC-110, AC-113, AC-115, AC-116
  - **依赖**：T010, T016, T018

- [x] **T020：实现 FGAManager 单 model runtime**
  - **文件**：`src/backend/bisheng/core/openfga/discovery.py`,
    `src/backend/bisheng/core/openfga/manager.py`
  - **逻辑**：生产按稳定 Store name 发现唯一 Store/latest model，禁止创建/写入，校验
    F048 checksum 和 SQL CURRENT Catalog 引用的 ACTIVE release，只构造一个显式 model
    client，并提供 API/Worker/Linsight 可复用 readiness/heartbeat。
  - **验收**：T019 全部通过
  - **依赖**：T019

- [x] **T021：动作 Catalog 纯规则测试**
  - **文件**：`src/backend/test/permission/test_f048_action_catalog_policy.py`
  - **测试**：验证唯一等级、未分配/停用、resource scope、旧 view 动作隐藏、动作变化影响、
    五区和全量 release 重算。
  - **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-148, AC-149, AC-156
  - **依赖**：T002, T003

- [x] **T022：实现动作 Catalog 纯规则**
  - **文件**：`src/backend/bisheng/permission/domain/services/catalog_policy.py`
  - **逻辑**：提供 action normalization、level/scope validation、完整 release 派生与 impact
    checksum 纯函数；不访问 ORM/FGA。
  - **验收**：T021 全部通过
  - **依赖**：T021

- [x] **T023：标准/自定义模型纯规则测试**
  - **文件**：`src/backend/test/permission/test_f048_model_policy.py`
  - **测试**：验证四个累计标准模型、不可编辑字段、同级策略、自定义最高动作等级、
    空/非法模型、共享模型影响、inactive、引用中删除和预设一次性初始化。
  - **覆盖 AC**：AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-39, AC-156
  - **依赖**：T002, T003, T022

- [x] **T024：实现标准/自定义模型纯规则**
  - **文件**：`src/backend/bisheng/permission/domain/services/model_policy.py`
  - **逻辑**：实现标准模型累计、custom 显式动作、派生 level、active、allow_same_level、
    deletion/reference 和 preset 校验；绝不按 custom level 自动补动作。
  - **验收**：T023 全部通过
  - **依赖**：T023

- [x] **T025：Catalog publish Service 崩溃矩阵测试**
  - **文件**：`src/backend/test/permission/test_f048_catalog_service.py`
  - **测试**：覆盖 draft/impact/fence、model stage、2-tuple active commit、SQL finalize、
    checksum 过期、并发管理员、recent marker 预置和 commit unknown 恢复。
  - **覆盖 AC**：AC-03, AC-06, AC-13, AC-14, AC-16, AC-17, AC-18, AC-66, AC-67, AC-68, AC-69, AC-143, AC-156
  - **依赖**：T013, T016, T018, T022, T024

- [x] **T026：实现 CatalogService**
  - **文件**：`src/backend/bisheng/permission/domain/services/catalog_service.py`
  - **逻辑**：编排完整 draft、跨 tenant 影响聚合、publish fence、model release staging、
    OpenFGA tests、active commit、finalize、审计、`permission_catalog_publish` metric-log 和
    crash reconcile；不直接 ORM 或 HTTP。
  - **验收**：T025 全部通过
  - **依赖**：T025

- [x] **T027：projection ledger 原子性测试**
  - **文件**：`src/backend/test/permission/test_f048_projection_service.py`
  - **测试**：覆盖 idempotency checksum、prepare/stage/commit/finalize、commit timeout 判定、
    recent marker、inverse compensation、FAILED_CLOSED、50/51 change 与 90/91 tuple 边界。
  - **覆盖 AC**：AC-16, AC-54, AC-66, AC-67, AC-68, AC-69, AC-70, AC-143
  - **依赖**：T014, T018

- [x] **T028：实现 ProjectionService**
  - **文件**：`src/backend/bisheng/permission/domain/services/projection_service.py`
  - **逻辑**：实现 durable operation/tuple 协议、原子 commit、higher-consistency 验证、
    recent marker、reconcile、审计和 `permission_projection` metric-log；任何不确定状态
    fail closed。
  - **验收**：T027 全部通过
  - **依赖**：T027

- [x] **T029：Grant 多来源与引用计数测试**
  - **文件**：`src/backend/test/permission/test_f048_grant_sources.py`
  - **测试**：验证资源+模型唯一 Grant、direct/department/group/other source 独立、
    userset 不展开、动作并集、精确撤销、重复幂等、不同模型并存、inactive fail closed。
  - **覆盖 AC**：AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27
  - **依赖**：T013, T024, T028

- [x] **T030：实现 Grant source service**
  - **文件**：`src/backend/bisheng/permission/domain/services/grant_source_service.py`
  - **逻辑**：维护 Grant/assignee 稳定来源、projected subject 引用计数、精确 ADD/MOVE/REMOVE、
    include_children 与 protected collision；不按用户有效结果压平来源。
  - **验收**：T029 全部通过
  - **依赖**：T029

- [x] **T031：可授模型与 protected 规则测试**
  - **文件**：`src/backend/test/permission/test_f048_grant_policy.py`
  - **测试**：对每个来源模型独立计算 manage_permission、level、same-level，拒绝跨模型拼接、
    stale version、无管理权限 roster/mutation、protected 删除/降级；允许多个 owner。
  - **覆盖 AC**：AC-36, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-157
  - **依赖**：T024, T030

- [x] **T032：实现 GrantService**
  - **文件**：`src/backend/bisheng/permission/domain/services/grant_service.py`
  - **逻辑**：编排可授模型、版本校验、protected/ordinary、mutation delta、projection 和审计；
    不读取 Config、业务资源或展示名称。
  - **验收**：T031 全部通过
  - **依赖**：T031

- [x] **T033：权限模式与生命周期测试**
  - **文件**：`src/backend/test/permission/test_f048_mode_service.py`
  - **测试**：覆盖 canonical parent、INHERIT/CUSTOM、无父级拒绝、move/copy/delete、
    snapshot/dedup/protected、故障原子性、新 space/file 默认和确认取消。
  - **覆盖 AC**：AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-55, AC-56, AC-57, AC-150, AC-151, AC-152
  - **依赖**：T028, T030, T032

- [x] **T034：实现 ModeService**
  - **文件**：`src/backend/bisheng/permission/domain/services/mode_service.py`
  - **逻辑**：只消费 verified parent/mode/snapshot，创建影响 draft，原子切换 mode gate，
    投影 move/copy/delete；始终保留 canonical parent，不查询或移动业务资源。
  - **验收**：T033 全部通过
  - **依赖**：T033

- [x] **T035：PermissionService 具体动作与列表测试**
  - **文件**：`src/backend/test/permission/test_f048_permission_service.py`
  - **测试**：验证 C4 短路顺序、tenant fence、具体 action Check、visible 与其他动作分离、
    bounded BatchCheck、受限 ListObjects、FGA 故障 fail closed 和无业务查询。
  - **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-63, AC-65, AC-69, AC-155
  - **依赖**：T018, T020, T026, T028, T032, T034

- [x] **T036：实现 PermissionService F048 facade**
  - **文件**：`src/backend/bisheng/permission/domain/services/permission_service.py`
  - **逻辑**：增加 check_action/batch_check_actions/受限 list、authorize、lifecycle projection
    和 `permission_decision` metric-log；只接收 verified target，具体 action 的 OpenFGA 结果
    为最终结论，无 creator/Config/SQL fallback。
  - **验收**：T035 全部通过
  - **依赖**：T035

- [x] **T037：权限解释最小化测试**
  - **文件**：`src/backend/test/permission/test_f048_permission_explain_service.py`
  - **测试**：验证 mode/source/model/protected/继承明细、direct+department 分行、无 roster 权限时
    仅返回本人摘要，display port 失败不改变授权结论。
  - **覆盖 AC**：AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65
  - **依赖**：T030, T032, T034, T036

- [x] **T038：实现 PermissionExplainService**
  - **文件**：`src/backend/bisheng/permission/domain/services/permission_explain_service.py`
  - **逻辑**：输出 opaque subject/source/model ID、scope、protected、editable 和
    `permission_roster_explain` metric-log；不产生 ALLOW，不查询用户、部门、用户组或资源名称。
  - **验收**：T037 全部通过
  - **依赖**：T037

- [x] **T039：权限领域边界架构测试**
  - **文件**：`src/backend/test/permission/test_f048_domain_boundaries.py`
  - **测试**：静态禁止 permission domain import Knowledge/Dashboard/Flow/Tool/Channel ORM、
    Repository/Service；伪造 HTTP tenant/status/parent/version 不能生成 verified target。
  - **覆盖 AC**：AC-30, AC-34, AC-35, AC-70, AC-155
  - **依赖**：T002, T036, T038

- [x] **T040：实现 verified target application coordinator**
  - **文件**：`src/backend/bisheng/permission/application/resource_permission_coordinator.py`,
    `src/backend/bisheng/permission/application/__init__.py`
  - **逻辑**：只接受各业务 Service 生成的 `VerifiedPermissionTarget`，编排 facade 与批量 display
    ports；HTTP payload 不可直接构造 target，名称补充失败不改变权限字段。
  - **验收**：T039 全部通过
  - **依赖**：T039

---

## Wave 3 — 后端 API 与业务资源适配

### 后端 API（Test-First）

- [x] **T041：Catalog HTTP API 测试**
  - **文件**：`src/backend/test/permission/test_f048_catalog_api.py`
  - **测试**：覆盖 catalog GET、draft create/get/publish，平台超管 gate、非法 action/标准模型字段、
    impact confirmation/version conflict 和 UnifiedResponseModel。
  - **覆盖 AC**：AC-03, AC-09, AC-10, AC-14, AC-17, AC-18, AC-64, AC-68, AC-148, AC-149, AC-156
  - **依赖**：T001, T002, T026

- [x] **T042：实现 Catalog endpoints**
  - **文件**：`src/backend/bisheng/permission/api/endpoints/catalog.py`
  - **逻辑**：实现 Design §6.1 的四个 Catalog endpoint；只做认证、schema、Service 委托和响应翻译，
    不直接 ORM/FGA。
  - **验收**：T041 全部通过
  - **依赖**：T041

- [x] **T043：Grant/context/mode HTTP API 测试**
  - **文件**：`src/backend/test/permission/test_f048_grant_api.py`
  - **测试**：覆盖 grantable-models、context、cursor grants、my-permissions、grants:mutate、
    mode draft/apply；验证 payload 禁止 source/protected/level、INHERIT 行只读和 protected 拒绝。
  - **覆盖 AC**：AC-19, AC-25, AC-36, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65, AC-68, AC-152, AC-157
  - **依赖**：T001, T002, T032, T034, T038, T040

- [x] **T044：实现 Grant/context/mode endpoints**
  - **文件**：`src/backend/bisheng/permission/api/endpoints/grant.py`
  - **逻辑**：实现 Design §6.1 的资源上下文、roster、my-permissions、mutation 和 mode endpoints；
    资源加载委托 application coordinator/业务 port，cursor 绑定 tenant/resource/release/version。
  - **验收**：T043 全部通过
  - **依赖**：T043

- [x] **T045：具体动作 Check HTTP API 测试**
  - **文件**：`src/backend/test/permission/test_f048_decision_api.py`
  - **测试**：`POST /api/v1/permissions/check` 验证 allowed true/false、未知 action、tenant 隐匿、
    FGA unavailable 19002、业务 target 不能由客户端伪造。
  - **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-65, AC-69, AC-155
  - **依赖**：T001, T002, T036, T040

- [x] **T046：实现 decision endpoint**
  - **文件**：`src/backend/bisheng/permission/api/endpoints/decision.py`
  - **逻辑**：实现具体 action check，委托业务 ResourceAuthorizationPort 生成 verified target；
    正常 DENY 返回 `allowed=false`，不可用返回明确错误。
  - **验收**：T045 全部通过
  - **依赖**：T045

- [x] **T047：F048 Router 集成测试**
  - **文件**：`src/backend/test/permission/test_f048_router.py`
  - **测试**：验证 Catalog/Grant/decision 路由注册、认证依赖、统一响应和无旧 alias；
    旧 relation/permission_id payload 返回 25001。
  - **覆盖 AC**：AC-05, AC-09, AC-34, AC-43, AC-65, AC-144
  - **依赖**：T042, T044, T046

- [x] **T048：注册 F048 Router**
  - **文件**：`src/backend/bisheng/permission/api/router.py`,
    `src/backend/bisheng/permission/api/endpoints/__init__.py`
  - **逻辑**：注册 catalog/grant/decision endpoints；不新增兼容 alias，不把旧 endpoint 留在新模式。
  - **验收**：T047 全部通过
  - **依赖**：T047

- [x] **T049：F018 退役与旧 API 不可达测试**
  - **文件**：`src/backend/test/permission/test_f048_legacy_api_retirement.py`
  - **测试**：验证 transfer-owner 和旧 relation/model/binding mutation 不可达；ordinary owner 走
    grants:mutate，protected creator 不可删，多个 owner 合法。
  - **覆盖 AC**：AC-05, AC-09, AC-34, AC-44, AC-103, AC-116, AC-144, AC-145, AC-157
  - **依赖**：T044, T048

- [x] **T050：退役 F018 owner transfer API**
  - **文件**：`src/backend/bisheng/tenant/api/endpoints/resource_owner_transfer.py`,
    `src/backend/bisheng/tenant/domain/services/resource_ownership_service.py`
  - **逻辑**：从 F048 启服构建删除 transfer/list-pending 路由与 Service；不提供 protected owner
    transfer 替代，ordinary owner 由 Grant API 管理。
  - **验收**：T049 全部通过
  - **依赖**：T049

### 后端 Domain — 业务资源适配（Test-First）

- [x] **T051：knowledge_space/library 权限适配测试**
  - **文件**：`src/backend/test/permission/test_f048_knowledge_space_adapter.py`
  - **测试**：业务 Service 先验证 tenant/status/type，space/library 固定 CUSTOM、protected owner、
    list/action、copy/delete/mode；权限模块不回查业务行。
  - **覆盖 AC**：AC-28, AC-30, AC-35, AC-45, AC-47, AC-48, AC-50, AC-55, AC-56, AC-57, AC-86, AC-87, AC-91, AC-150, AC-152, AC-155, AC-157
  - **依赖**：T036, T040

- [x] **T052：适配 knowledge_space/library Service**
  - **文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`,
    `src/backend/bisheng/knowledge/domain/services/knowledge_service.py`
  - **逻辑**：加载并验证资源后生成 verified target，使用具体 action 和 lifecycle projection；
    space/library 固定 CUSTOM，移除旧 relation/creator fallback。
  - **验收**：T051 全部通过
  - **依赖**：T051

- [x] **T053：folder/file 权限生命周期测试**
  - **文件**：`src/backend/test/permission/test_f048_knowledge_file_adapter.py`
  - **测试**：合法 parent 下默认 INHERIT，CUSTOM/INHERIT move/copy/delete 原子，protected owner
    不破坏普通继承，缺失/跨租户/循环 parent 拒绝。
  - **覆盖 AC**：AC-45, AC-46, AC-47, AC-48, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-55, AC-56, AC-57, AC-86, AC-88, AC-89, AC-90, AC-92, AC-151, AC-152, AC-155, AC-157
  - **依赖**：T034, T036, T040

- [x] **T054：适配 folder/file Service**
  - **文件**：`src/backend/bisheng/knowledge/domain/services/knowledge_file_service.py`,
    `src/backend/bisheng/knowledge/domain/services/knowledge_permission_service.py`
  - **逻辑**：业务侧验证存在性/tenant/status/parent/path 后调用具体 action、mode 和 lifecycle
    projection；删除 SQL/creator/旧 relation ALLOW。
  - **验收**：T053 全部通过
  - **依赖**：T053

- [x] **T055：workflow/assistant 权限适配测试**
  - **文件**：`src/backend/test/permission/test_f048_application_adapters.py`
  - **测试**：workflow/assistant 的列表、详情、编辑、删除、分享、发布和创建 owner 使用 verified
    target+具体 action；builtin system-owned 只命中 allowlist+业务 predicate。
  - **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-45, AC-47, AC-57, AC-155, AC-157
  - **依赖**：T036, T040

- [x] **T056：适配 workflow/assistant Service**
  - **文件**：`src/backend/bisheng/api/services/workflow.py`,
    `src/backend/bisheng/api/services/assistant.py`
  - **逻辑**：业务 Service 加载资源并生成 verified target，替换 ApplicationPermissionService/
    permission template 调用；创建走 protected owner projection，builtin 使用显式 system predicate。
  - **验收**：T055 全部通过
  - **依赖**：T055

- [x] **T057：tool 权限适配测试**
  - **文件**：`src/backend/test/tool/test_f048_tool_permissions.py`
  - **测试**：普通 tool 的 visible/use/edit/delete/manage 与创建 protected owner；preset tool 仅按
    system allowlist，FGA 失败不回退旧 ToolPermissionService。
  - **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-44, AC-155, AC-157
  - **依赖**：T036, T040

- [x] **T058：适配 tool Service**
  - **文件**：`src/backend/bisheng/tool/domain/services/tool.py`,
    `src/backend/bisheng/permission/domain/services/tool_permission_service.py`
  - **逻辑**：tool 业务加载后直接调用 F048 facade，并删除旧 ToolPermissionService 运行实现；
    preset predicate 由业务侧验证，不保留 fallback adapter。
  - **验收**：T057 全部通过
  - **依赖**：T057

- [x] **T059：channel 权限与成员来源测试**
  - **文件**：`src/backend/test/channel/test_f048_channel_permissions.py`
  - **测试**：channel visible/edit/delete/manage、direct/department/group、CREATOR protected、
    shared/system relation、业务 tenant/status 与具体动作 fail closed。
  - **覆盖 AC**：AC-20, AC-21, AC-22, AC-23, AC-24, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-45, AC-47, AC-57, AC-120, AC-126, AC-155, AC-157
  - **依赖**：T032, T036, T040

- [x] **T060：适配 channel Service**
  - **文件**：`src/backend/bisheng/channel/domain/services/channel_authorization_service.py`,
    `src/backend/bisheng/channel/domain/services/channel_service.py`
  - **逻辑**：channel 业务侧验证资源/tenant/status/CREATOR 后生成 target，使用具体 action 与
    Grant source；删除旧 template/binding fallback。
  - **验收**：T059 全部通过
  - **依赖**：T059

- [x] **T061：dashboard 全动作合同测试**
  - **文件**：`src/backend/test/permission/test_f048_dashboard_permissions.py`
  - **测试**：列表/详情/组件数据/复制源/默认/分享链接检查 visible，标题/状态/布局/组件检查 edit，
    删除检查 delete，成员检查 manage_permission，创建仍由菜单 gate 并投影 protected owner。
  - **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-44, AC-153, AC-155, AC-157
  - **依赖**：T036, T040

- [x] **T062：适配 DashboardService 与 endpoint**
  - **文件**：`src/backend/bisheng/telemetry_search/domain/services/dashboard.py`,
    `src/backend/bisheng/telemetry_search/api/endpoints/dashboard.py`
  - **逻辑**：业务层验证 dashboard tenant/type/status，按 T061 映射具体 action，创建投影 owner；
    删除不再复用 can_edit，分享链接不能绕过 visible。
  - **验收**：T061 全部通过
  - **依赖**：T061

- [x] **T063：F017 精确共享边界测试**
  - **文件**：`src/backend/test/permission/test_f048_resource_share_boundary.py`
  - **测试**：普通 Grant 不跨 tenant；shared_with 只允许精确已共享 ID 的只读/使用语义，
    未共享、inactive、错误 owner tenant 和写动作拒绝；permission domain 不做跨 tenant 查询。
  - **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-126, AC-155
  - **依赖**：T036, T040

- [x] **T064：适配 ResourceShareService 与 Repository**
  - **文件**：`src/backend/bisheng/tenant/domain/services/resource_share_service.py`,
    `src/backend/bisheng/tenant/domain/repositories/resource_share_repository.py`
  - **逻辑**：保留 F017 精确 ID 跨 tenant 业务加载和状态校验；只把 verified shared target 交给
    PermissionService，不创建跨 tenant 普通 Grant。
  - **验收**：T063 全部通过
  - **依赖**：T063

- [x] **T065：部门 userset 与 parent mirror 测试**
  - **文件**：`src/backend/test/permission/test_f048_department_projection.py`
  - **测试**：部门授权不展开用户，include_children 使用根部门 subtree userset，成员退出仅移除
    部门来源，部门 move 的 parent+child 同一 Write，非法 parent/cycle fail closed。
  - **覆盖 AC**：AC-21, AC-24, AC-45, AC-49, AC-57, AC-82, AC-92, AC-121, AC-122, AC-125
  - **依赖**：T016, T028, T030

- [x] **T066：实现部门 projection handler**
  - **文件**：`src/backend/bisheng/department/domain/services/department_service.py`,
    `src/backend/bisheng/permission/domain/services/department_change_handler.py`
  - **逻辑**：DepartmentService 先验证业务树和 tenant，再传 verified old/new parent/member delta；
    handler 通过 ledger 原子投影 parent+child，不展开资源 Grant。
  - **验收**：T065 全部通过
  - **依赖**：T065

- [x] **T067：创建者与多 owner 投影测试**
  - **文件**：`src/backend/test/permission/test_f048_owner_projection.py`
  - **测试**：user-owned 创建产生一个 protected owner，允许 0..N ordinary owner；protected
    不可普通删除，copy 重新生成，失败走 durable compensation；system-owned 双重 predicate。
  - **覆盖 AC**：AC-44, AC-52, AC-53, AC-56, AC-57, AC-70, AC-77, AC-120, AC-150, AC-151, AC-157
  - **依赖**：T028, T032, T034, T036

- [x] **T068：实现 owner projection 与通知适配**
  - **文件**：`src/backend/bisheng/permission/domain/services/owner_service.py`,
    `src/backend/bisheng/permission/domain/services/resource_permission_notification_service.py`
  - **逻辑**：创建/复制只通过 PermissionService+ledger 建 protected owner，ordinary owner 独立；
    通知从 assignee/source/model 生成，不解析旧 relation/binding。
  - **验收**：T067 全部通过
  - **依赖**：T067

- [x] **T069：文件预览与下载边界测试**
  - **文件**：`src/backend/test/knowledge/test_f048_preview_download_permissions.py`
  - **测试**：preview endpoint 不调用 PermissionAction；原件/打包下载必须检查 download，
    visible 或已预览不能代替 download，RAG 继续检查 library use。
  - **覆盖 AC**：AC-32, AC-154
  - **依赖**：T036, T052, T054

- [x] **T070：适配知识文件预览/下载 endpoints**
  - **文件**：`src/backend/bisheng/knowledge/api/endpoints/knowledge.py`,
    `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`
  - **逻辑**：保持 preview 无 action；原件/打包下载在业务 Service 验证资源后调用 download，
    RAG/use 与原始文件 URL 分离。
  - **验收**：T069 全部通过
  - **依赖**：T069

---

## Wave 4 — Worker、Celery 与 Linsight

### Worker（Test-First）

- [x] **T071：Celery 单 model pin 与 tenant header 测试**
  - **文件**：`src/backend/test/permission/test_f048_worker_runtime.py`
  - **测试**：Worker 启动只接受同一 Store/new model/Catalog；发布任务把 current tenant 写入
    Celery header，`task_prerun` 恢复 ContextVar，缺失/非法 tenant 的权限任务 fail closed；
    不注册数据迁移任务。
  - **覆盖 AC**：AC-34, AC-35, AC-69, AC-99, AC-100, AC-102, AC-110, AC-113, AC-115, AC-155
  - **依赖**：T020, T036

- [x] **T072：升级 Celery 权限 runtime**
  - **文件**：`src/backend/bisheng/worker/main.py`,
    `src/backend/bisheng/worker/tenant_context.py`
  - **逻辑**：Worker 使用 FGAManager 同一 readiness/heartbeat；权限任务严格依赖
    `before_task_publish tenant_id header → task_prerun current_tenant_id ContextVar`，不默认猜 tenant；
    不 import/触发 F048 数据迁移脚本。
  - **验收**：T071 全部通过
  - **依赖**：T071

- [x] **T073：Linsight 权限 runtime 测试**
  - **文件**：`src/backend/test/permission/test_f048_linsight_runtime.py`
  - **测试**：Linsight task 从任务载荷恢复 tenant ContextVar，使用同一 Store/new model/Catalog
    和 durable owner projection；旧 model/Config/FGA 故障不产生 ALLOW。
  - **覆盖 AC**：AC-34, AC-35, AC-70, AC-99, AC-100, AC-102, AC-110, AC-113, AC-115, AC-155
  - **依赖**：T020, T036, T068

- [x] **T074：适配 Linsight runtime**
  - **文件**：`src/backend/bisheng/linsight/domain/task_exec.py`,
    `src/backend/bisheng/linsight/domain/services/skill_service.py`
  - **逻辑**：task_exec 明确设置/重置 tenant ContextVar；skill 创建授权使用 F048 durable
    authorize，不保留 best-effort legacy tuple 语义，并报告统一 runtime heartbeat。
  - **验收**：T073 全部通过
  - **依赖**：T073

---

## Wave 5 — 前端 Platform

### 前端 Platform（Vitest Test-First）

- [x] **T075：Platform permission API 合同测试**
  - **文件**：`src/frontend/platform/src/test/f048PermissionApi.test.ts`
  - **测试**：mock wrapped request，验证 Catalog/draft/publish、context/roster/my-permissions、
    mutate/mode/check 的 path、payload 和 response type；不发送 protected/source/level。
  - **覆盖 AC**：AC-42, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65, AC-68, AC-148, AC-149, AC-152, AC-156
  - **依赖**：T048

- [x] **T076：升级 Platform permission API 模块**
  - **文件**：`src/frontend/platform/src/controllers/API/permission.ts`
  - **逻辑**：使用 `@/controllers/request.ts` 暴露 T075 的类型化 API；API 模块不写 Zustand，
    store/component 不直接 HTTP。
  - **验收**：T075 全部通过
  - **依赖**：T075

- [x] **T077：ActionLevelBoard 交互测试**
  - **文件**：`src/frontend/platform/src/test/f048ActionLevelBoard.test.tsx`
  - **测试**：未分配+1～4 五区、动作唯一、未分配不可进入模型、拖动只更新 draft、
    scope/active 影响与确认发布。
  - **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-148, AC-149, AC-156
  - **依赖**：T076

- [x] **T078：实现 ActionLevelBoard**
  - **文件**：`src/frontend/platform/src/pages/SystemPage/components/permission/ActionLevelBoard.tsx`
  - **逻辑**：命名导出、局部 state/draft、五区拖动和 impact 入口；不直接请求 HTTP，
    通过 props/callback 使用 API 层。
  - **验收**：T077 全部通过
  - **依赖**：T077

- [x] **T079：ModelEditor 与 ImpactDialog 测试**
  - **文件**：`src/frontend/platform/src/test/f048ModelEditor.test.tsx`
  - **测试**：标准模型字段只读、custom 显式动作/派生等级、inactive、同级开关条件、
    preset 初始化、资源/Grant/source 影响与版本过期。
  - **覆盖 AC**：AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-17, AC-18, AC-39, AC-64, AC-156
  - **依赖**：T076

- [x] **T080：实现 ModelEditor 与 ImpactDialog**
  - **文件**：`src/frontend/platform/src/pages/SystemPage/components/permission/ModelEditor.tsx`,
    `src/frontend/platform/src/pages/SystemPage/components/permission/ImpactDialog.tsx`
  - **逻辑**：按服务端 preview 展示派生等级和影响；publish 只提交 draft/checksum/confirmed，
    不在前端自行重算最终授权。
  - **验收**：T079 全部通过
  - **依赖**：T079

- [x] **T081：Platform 权限配置页回归测试**
  - **文件**：`src/frontend/platform/src/test/f048RolesAndPermissions.test.tsx`
  - **测试**：平台超管进入动作/模型配置，普通管理员不可见；旧 relation/permission_id UI
    不再出现，ActionLevelBoard/ModelEditor/ImpactDialog 正确编排。
  - **覆盖 AC**：AC-05, AC-09, AC-14, AC-64, AC-148, AC-149
  - **依赖**：T078, T080

- [x] **T082：重构 RolesAndPermissions**
  - **文件**：`src/frontend/platform/src/pages/SystemPage/components/RolesAndPermissions.tsx`
  - **逻辑**：将 F048 动作/模型配置编排接入现有页面，控制文件小于 600 行；角色菜单 RBAC
    与资源 action 分离，不保留旧 Config model 编辑。
  - **验收**：T081 全部通过
  - **依赖**：T081

- [x] **T083：Platform roster 来源展示测试**
  - **文件**：`src/frontend/platform/src/test/f048PermissionRoster.test.tsx`
  - **测试**：mode、继承资源、subject/model/level/source/protected，direct+department 分行，
    INHERIT 只读、无 roster 权限只请求本人摘要、cursor 分页。
  - **覆盖 AC**：AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65
  - **依赖**：T076

- [x] **T084：实现 Platform PermissionListTab**
  - **文件**：`src/frontend/platform/src/components/bs-comp/permission/PermissionListTab.tsx`,
    `src/frontend/platform/src/components/bs-comp/permission/SourceBadge.tsx`
  - **逻辑**：按 response schema 渲染 cursor roster、来源和 protected；不按最高 relation 压平，
    不查询全量 total。
  - **验收**：T083 全部通过
  - **依赖**：T083

- [x] **T085：Platform Grant 编辑测试**
  - **文件**：`src/frontend/platform/src/test/f048PermissionGrantTab.test.tsx`
  - **测试**：只展示 grantable models，ADD/MOVE/REMOVE 精确 assignee/version，protected 锁定，
    stale version/impact 反馈；不提交 source/protected/level。
  - **覆盖 AC**：AC-36, AC-37, AC-38, AC-40, AC-41, AC-42, AC-43, AC-44, AC-60, AC-61, AC-63
  - **依赖**：T076, T084

- [x] **T086：实现 Platform PermissionGrantTab**
  - **文件**：`src/frontend/platform/src/components/bs-comp/permission/PermissionGrantTab.tsx`,
    `src/frontend/platform/src/components/bs-comp/permission/RelationSelect.tsx`
  - **逻辑**：使用稳定 model_key、assignee_id/version 和 change list，保持 Zustand/API 边界；
    类型复用 T076 API 契约并删除旧 RelationSelect 组件。
  - **验收**：T085 全部通过
  - **依赖**：T085

- [x] **T087：Platform 模式切换对话框测试**
  - **文件**：`src/frontend/platform/src/test/f048PermissionDialog.test.tsx`
  - **测试**：展示当前 mode/parent、影响预览、INHERIT 成员只读、CUSTOM 可编辑、
    confirm/cancel/version expired 和 protected 行。
  - **覆盖 AC**：AC-45, AC-46, AC-47, AC-48, AC-51, AC-52, AC-53, AC-54, AC-58, AC-59, AC-60, AC-61, AC-152
  - **依赖**：T084, T086

- [x] **T088：实现 Platform PermissionDialog/ModeHeader**
  - **文件**：`src/frontend/platform/src/components/bs-comp/permission/PermissionDialog.tsx`,
    `src/frontend/platform/src/components/bs-comp/permission/ModeHeader.tsx`
  - **逻辑**：先请求 context，再按权限选择 roster 或 my-permissions；mode apply 只提交服务端
    draft+确认，不重传成员清单。
  - **验收**：T087 全部通过
  - **依赖**：T087

- [x] **T089：Platform dashboard 权限 UI 测试**
  - **文件**：`src/frontend/platform/src/test/f048DashboardPermissions.test.tsx`
  - **测试**：dashboard 列表/详情/编辑/删除/成员入口按 visible/edit/delete/manage_permission
    响应渲染；分享链接和默认设置不能绕过 visible。
  - **覆盖 AC**：AC-32, AC-58, AC-60, AC-63, AC-65, AC-153
  - **依赖**：T076, T088

- [x] **T090：适配 Platform dashboard UI**
  - **文件**：`src/frontend/platform/src/pages/Dashboard/hook.ts`,
    `src/frontend/platform/src/pages/Dashboard/components/dashboard/DashboardListItem.tsx`
  - **逻辑**：消费 F048 my-permissions/action response 显示按钮和调用业务 API；前端隐藏不替代
    服务端鉴权，不自行把 edit 当 delete。
  - **验收**：T089 全部通过
  - **依赖**：T089

- [x] **T091：Platform F048 i18n key 测试**
  - **文件**：`src/frontend/platform/src/test/f048PermissionI18n.test.ts`
  - **测试**：验证 zh-Hans/en-US/ja 都含未分配、动作等级、标准/自定义、继承、本级、受保护、
    来源、影响、模式确认及迁移/投影错误 key，三语言 key 集一致且组件无硬编码中文。
  - **覆盖 AC**：AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-148, AC-149, AC-152
  - **依赖**：T078, T080, T084, T086, T088

- [x] **T092：补 Platform 中英文 F048 词条**
  - **文件**：`src/frontend/platform/public/locales/zh-Hans/permission.json`,
    `src/frontend/platform/public/locales/en-US/permission.json`
  - **逻辑**：补齐 T091 断言的 permission namespace key，不在 TSX 中硬编码文案。
  - **验收**：T091 的 zh-Hans/en-US 断言通过
  - **依赖**：T091

- [x] **T093：补 Platform 日文 F048 词条**
  - **文件**：`src/frontend/platform/public/locales/ja/permission.json`
  - **逻辑**：补齐与 zh-Hans/en-US 相同 key 集。
  - **验收**：T091 全部通过
  - **依赖**：T091, T092

---

## Wave 6 — 前端 Client

### 前端 Client（Jest Test-First）

- [x] **T094：Client permission API 合同测试**
  - **文件**：`src/frontend/client/src/api/permission.test.ts`
  - **测试**：mock `~/api/request.ts`，验证 context/roster/my-permissions/grantable/mutate/mode/check
    path、payload 和 response；不混用 Platform API/state。
  - **覆盖 AC**：AC-42, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65, AC-68, AC-152
  - **依赖**：T048

- [x] **T095：升级 Client permission API**
  - **文件**：`src/frontend/client/src/api/permission.ts`
  - **逻辑**：使用 Client request wrapper 和类型化契约；不写 Recoil、不导入 Platform 文件。
  - **验收**：T094 全部通过
  - **依赖**：T094

- [x] **T096：Client roster 来源展示测试**
  - **文件**：`src/frontend/client/src/components/permission/PermissionListTab.test.tsx`
  - **测试**：验证 mode/parent、direct+department、多 model、protected/source、INHERIT 只读、
    无管理权限最小摘要和 cursor。
  - **覆盖 AC**：AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65
  - **依赖**：T095

- [x] **T097：实现 Client PermissionListTab**
  - **文件**：`src/frontend/client/src/components/permission/PermissionListTab.tsx`,
    `src/frontend/client/src/components/permission/SourceBadge.tsx`
  - **逻辑**：使用 Client shadcn/Recoil 约束渲染来源与 protected；不压平最高模型，不 fetch-all。
  - **验收**：T096 全部通过
  - **依赖**：T096

- [x] **T098：Client Grant 编辑测试**
  - **文件**：`src/frontend/client/src/components/permission/PermissionGrantTab.test.tsx`
  - **测试**：只展示可授模型，精确 assignee/version mutation，protected/INHERIT 锁定，
    version conflict；payload 不含服务端字段。
  - **覆盖 AC**：AC-36, AC-37, AC-38, AC-40, AC-41, AC-42, AC-43, AC-44, AC-60, AC-61, AC-63
  - **依赖**：T095, T097

- [x] **T099：实现 Client PermissionGrantTab**
  - **文件**：`src/frontend/client/src/components/permission/PermissionGrantTab.tsx`,
    `src/frontend/client/src/components/permission/RelationSelect.tsx`
  - **逻辑**：接入稳定 model_key、assignee/version changes；使用 Client request/API 与 Recoil，
    类型复用 T095 API 契约，删除旧 RelationSelect，不复制 Platform store。
  - **验收**：T098 全部通过
  - **依赖**：T098

- [x] **T100：Client 模式切换对话框测试**
  - **文件**：`src/frontend/client/src/components/permission/PermissionDialog.test.tsx`
  - **测试**：context→roster/my-permissions 分流、mode impact/confirm/cancel、继承只读、
    protected 和 expired draft。
  - **覆盖 AC**：AC-45, AC-46, AC-47, AC-48, AC-51, AC-52, AC-53, AC-54, AC-58, AC-59, AC-60, AC-61, AC-152
  - **依赖**：T097, T099

- [x] **T101：实现 Client PermissionDialog/ModeHeader**
  - **文件**：`src/frontend/client/src/components/permission/PermissionDialog.tsx`,
    `src/frontend/client/src/components/permission/ModeHeader.tsx`
  - **逻辑**：按 Client 组件库实现 context、mode draft/apply 和成员 tabs；不增加状态/UI 库。
  - **验收**：T100 全部通过
  - **依赖**：T100

- [x] **T102：Client channel 权限 UI 测试**
  - **文件**：`src/frontend/client/src/components/ChannelMemberDialog.test.tsx`
  - **测试**：channel roster/source/protected、grantable models、无 manage 时本人摘要，
    旧 relation selector 不再出现。
  - **覆盖 AC**：AC-20, AC-23, AC-43, AC-58, AC-60, AC-61, AC-62, AC-63, AC-65
  - **依赖**：T095, T101

- [x] **T103：适配 Client channel 权限组件**
  - **文件**：`src/frontend/client/src/components/ChannelMemberDialog.tsx`,
    `src/frontend/client/src/pages/Subscription/ChannelPermissionDialog.tsx`
  - **逻辑**：复用 Client F048 permission components，移除旧 relation payload；频道业务数据仍由
    channel API 管理。
  - **验收**：T102 全部通过
  - **依赖**：T102

- [x] **T104：Client 文件预览/下载 UI 测试**
  - **文件**：`src/frontend/client/src/pages/knowledge/FilePreview/TopBar.test.tsx`
  - **测试**：打开 preview 不触发 PermissionAction check；点击原件下载调用 download 授权路径，
    visible/preview 状态不直接解锁下载。
  - **覆盖 AC**：AC-32, AC-154
  - **依赖**：T095

- [x] **T105：适配 Client preview/download**
  - **文件**：`src/frontend/client/src/pages/knowledge/FilePreview/TopBar.tsx`,
    `src/frontend/client/src/api/knowledge.ts`
  - **逻辑**：preview 渲染保持无 action；下载使用后端受保护下载 endpoint，不在前端缓存 ALLOW。
  - **验收**：T104 全部通过
  - **依赖**：T104

- [x] **T106：Client F048 i18n key 测试**
  - **文件**：`src/frontend/client/src/components/permission/permissionI18n.test.ts`
  - **测试**：验证 zh-Hans/en/ja 都含 mode/source/protected/model/impact/错误 key，组件无硬编码
    中文且三语言 key 集一致。
  - **覆盖 AC**：AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65, AC-152
  - **依赖**：T097, T099, T101, T103

- [x] **T107：补 Client 中英文 F048 词条**
  - **文件**：`src/frontend/client/src/locales/zh-Hans/translation.json`,
    `src/frontend/client/src/locales/en/translation.json`
  - **逻辑**：新增与 T091 同语义的 Client 嵌套 namespace key，不复制 Platform 文件格式。
  - **验收**：T106 的 zh-Hans/en 断言通过
  - **依赖**：T106

- [x] **T108：补 Client 日文 F048 词条**
  - **文件**：`src/frontend/client/src/locales/ja/translation.json`
  - **逻辑**：补齐与 zh-Hans/en 相同 key 集。
  - **验收**：T106 全部通过
  - **依赖**：T106, T107

---

## Wave 7 — scripts 数据迁移、验证与旧路径退役

### 后端 Domain / scripts（Test-First）

- [x] **T109：F048 迁移 source inventory 测试**
  - **文件**：`src/backend/test/permission/test_f048_migration_inventory.py`
  - **测试**：D1 schema/ready heartbeat=0/Store/watermark 前置，旧动作/模型/binding/tuple/
    parent/mode/owner/failed_tuple 盘点，损坏 JSON、跨租户、stale-resource tuple、确定性
    failed_tuple 对账和 blocker 分类；不形成 dry-run。
  - **覆盖 AC**：AC-71, AC-72, AC-73, AC-74, AC-75, AC-76, AC-99, AC-108, AC-113, AC-141, AC-142
  - **依赖**：T011, T014, T020, T052, T054, T056, T058, T060, T062, T064, T066, T068

- [x] **T110：实现迁移 source inventory**
  - **文件**：`src/backend/bisheng/permission/migration/f048_source_inventory.py`
  - **逻辑**：消费各业务 `PermissionMigrationSourcePort` DTO 和旧 Config/Store facts，生成规范化
    source item/checksum/blocker；已删除资源的遗留 tuple 审计后进入删除计划；failed_tuple
    通过 Store/模型/资源证据以及业务域提供的 tenant/department canonical member state 对账，
    permission domain 不直接查询业务表；被阻断且尚未发布目标模型的 run 可重新冻结 source；
    source item 按 500 条批量写入，避免大数据量盘点产生逐行 INSERT。
  - **验收**：T109 全部通过
  - **依赖**：T109

- [x] **T111：旧模型与动作 mapper 测试**
  - **文件**：`src/backend/test/permission/test_f048_model_mapper.py`
  - **测试**：view_* 移除、标准/edited system/custom、active 缺省、稳定 ID、最高等级、
    空/未知动作、manage_* 连续边界、单模型多引用和完整 action scope 规范化。
  - **覆盖 AC**：AC-05, AC-73, AC-78, AC-79, AC-80, AC-127, AC-128, AC-129, AC-130, AC-131, AC-132, AC-133, AC-134, AC-135, AC-136, AC-137, AC-139
  - **依赖**：T022, T024, T110

- [x] **T112：实现旧模型与动作 mapper**
  - **文件**：`src/backend/bisheng/permission/migration/f048_model_mapper.py`
  - **逻辑**：按 T111 输出 Catalog/Action/Model/ModelAction 目标 DTO 与 difference item；
    不使用等级给 custom 补动作，不猜测不连续 manage 范围。
  - **验收**：T111 全部通过
  - **依赖**：T111

- [x] **T113：旧 tuple/binding mapper 测试**
  - **文件**：`src/backend/test/permission/test_f048_tuple_mapper.py`
  - **测试**：direct tuple、唯一 binding 优先、标准 fallback、userset/include_children、
    多来源/不同模型、幂等去重、孤儿/冲突、shared/system 保留和 Config→Grant/assignee。
  - **覆盖 AC**：AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-73, AC-77, AC-81, AC-82, AC-83, AC-84, AC-85, AC-118, AC-119, AC-121, AC-122, AC-123, AC-124, AC-126, AC-138, AC-140, AC-141
  - **依赖**：T030, T110, T112

- [x] **T114：实现旧 tuple/binding mapper**
  - **文件**：`src/backend/bisheng/permission/migration/f048_tuple_mapper.py`
  - **逻辑**：只转换持久化 direct facts，保留 userset/source/protected；生成 Grant/assignee/
    tuple key 与 source checksum，不展开 computed/parent 用户集。
  - **验收**：T113 全部通过
  - **依赖**：T113

- [x] **T115：旧 mode/parent mapper 测试**
  - **文件**：`src/backend/test/permission/test_f048_mode_mapper.py`
  - **测试**：复用 canonical parent；space/library CUSTOM；无普通本级 file/folder INHERIT，
    有本级则 CUSTOM+快照；多来源保留，缺失/跨租户/cycle blocker。
  - **覆盖 AC**：AC-45, AC-47, AC-73, AC-86, AC-87, AC-88, AC-89, AC-90, AC-91, AC-92, AC-125
  - **依赖**：T110, T114

- [x] **T116：实现旧 mode/parent mapper**
  - **文件**：`src/backend/bisheng/permission/migration/f048_mode_mapper.py`
  - **逻辑**：输出 ResourcePermissionMode 和 ordinary snapshot DTO；canonical parent 始终保留，
    不创建 `permission_parent`。
  - **验收**：T115 全部通过
  - **依赖**：T115

- [x] **T117：业务迁移 source adapters 合同测试**
  - **文件**：`src/backend/test/permission/test_f048_migration_source_ports.py`
  - **测试**：每个 adapter 通过所属 Repository 验证 tenant/current owner/parent/type/status，
    输出 canonical DTO；knowledge/channel CREATOR 差异保留，system-owned 双重 predicate。
  - **覆盖 AC**：AC-35, AC-73, AC-74, AC-75, AC-77, AC-82, AC-86, AC-87, AC-88, AC-89, AC-90, AC-91, AC-92, AC-120, AC-123, AC-126, AC-141, AC-155, AC-157
  - **依赖**：T039, T052, T054, T056, T058, T060, T062

- [x] **T118：实现 Knowledge/Channel migration source ports**
  - **文件**：`src/backend/bisheng/knowledge/domain/services/permission_migration_source.py`,
    `src/backend/bisheng/channel/domain/services/permission_migration_source.py`
  - **逻辑**：用各自 Repository cursor 输出 space/library/file/folder/channel verified DTO，
    包含 CREATOR/user_id 差异和 canonical parent；不写权限目标表。
  - **验收**：T117 对 Knowledge/Channel 的断言通过
  - **依赖**：T117

- [x] **T119：实现 Application/Tool migration source ports**
  - **文件**：`src/backend/bisheng/api/services/permission_migration_source.py`,
    `src/backend/bisheng/tool/domain/services/permission_migration_source.py`
  - **逻辑**：输出 workflow/assistant/tool verified DTO，验证 preset/system predicate 与 current owner；
    不调用旧权限 Service。
  - **验收**：T117 对 Application/Tool 的断言通过
  - **依赖**：T117

- [x] **T120：实现 Dashboard migration source port**
  - **文件**：`src/backend/bisheng/telemetry_search/domain/services/permission_migration_source.py`
  - **逻辑**：输出 dashboard tenant/type/current owner/status DTO；CUSTOM dashboard 建 protected
    owner，preset 只标 system-owned。
  - **验收**：T117 全部通过
  - **依赖**：T117

- [x] **T121：正式数据迁移 coordinator 测试**
  - **文件**：`src/backend/test/permission/test_f048_migration_coordinator.py`
  - **测试**：唯一 environment run/lease、同 Store 新 model、batch checkpoint、崩溃 resume、
    target write→legacy tuple delete、Config 原始行只读保留且运行路径退役、forward-only、
    无并发/双 model/自动启动。
  - **覆盖 AC**：AC-71, AC-72, AC-73, AC-74, AC-75, AC-76, AC-93, AC-94, AC-95, AC-96, AC-97, AC-98, AC-99, AC-100, AC-101, AC-102, AC-103, AC-104, AC-105, AC-106, AC-107, AC-108, AC-109, AC-110, AC-111, AC-112, AC-113, AC-115, AC-116, AC-117, AC-143, AC-144, AC-145, AC-146, AC-147, AC-158
  - **依赖**：T014, T016, T018, T020, T110, T112, T114, T116, T118, T119, T120

- [x] **T122：实现正式数据迁移 coordinator**
  - **文件**：`src/backend/bisheng/permission/migration/f048_coordinator.py`
  - **逻辑**：从 D2 创建/续跑真实 run，在现有 Store 发布新 model，按 500 DB/90 FGA batch
    写控制面和 tuple、持久化 source/target checksum、发出 `permission_migration` metric-log，
    核对后退役 legacy tuple，保留 Config 原始行供排障但禁止运行时引用；失败时保持应用
    访问门禁并前向续跑。
  - **验收**：T121 全部通过
  - **依赖**：T121

- [x] **T123：D4 verifier 测试**
  - **文件**：`src/backend/test/permission/test_f048_migration_verifier.py`
  - **测试**：source/target count+checksum、blocker/manual item、跨租户/orphan/parent/owner、
    high-risk Check/List、多来源/dashboard/download、legacy tuple=0、Config 保留数仅审计、
    全实例 pin。
  - **覆盖 AC**：AC-74, AC-75, AC-76, AC-93, AC-95, AC-96, AC-97, AC-98, AC-100, AC-101, AC-102, AC-104, AC-105, AC-106, AC-107, AC-114, AC-115, AC-116, AC-117, AC-147
  - **依赖**：T122

- [x] **T124：实现 D4 verifier**
  - **文件**：`src/backend/bisheng/permission/migration/f048_verifier.py`
  - **逻辑**：只验证已存在正式 run，使用 higher consistency 和 approved difference list，
    通过后置 `READY_TO_START`；不运行旧/新 shadow，不提供 rollback。
  - **验收**：T123 全部通过
  - **依赖**：T123

- [x] **T125：数据迁移 CLI 合同测试**
  - **文件**：`src/backend/test/permission/test_f048_migration_cli.py`
  - **测试**：`migrate` 缺 `--apply` 直接参数错误且不扫描；`migrate --apply` 初始化/关闭完整
    app context、验证 schema/store/ready heartbeat=0 并 resume；`verify` 只读既有 run；
    无 dry-run/rollback 子命令。
  - **覆盖 AC**：AC-71, AC-93, AC-94, AC-95, AC-99, AC-100, AC-103, AC-108, AC-110, AC-113, AC-116, AC-158
  - **依赖**：T122, T124

- [x] **T126：实现 scripts 唯一数据迁移入口**
  - **文件**：`src/backend/scripts/migrate_f048_permission_data.py`
  - **逻辑**：argparse 提供 `migrate --apply` 与 `verify`；从 `src/backend/` 加载 live config，
    `initialize_app_context`/`close_app_context` 包裹 coordinator/verifier，窄 tenant bypass；
    不建 schema、不注册 API/Celery/startup。
  - **验收**：T125 全部通过
  - **依赖**：T125

- [x] **T127：登记 F048 数据迁移脚本 runbook**
  - **文件**：`src/backend/scripts/README.md`
  - **逻辑**：记录更新镜像并启动、自动访问门禁、D0/D1 前置、现有 Store/new model、
    容器内 migrate/verify 命令、迁移后重启、`--apply` 含义、exit code、checkpoint 续跑和
    前向修复；不保存生产凭据或数据。
  - **依赖**：T126

- [x] **T128：旧权限运行时静态退役测试**
  - **文件**：`src/backend/test/permission/test_f048_legacy_runtime_retirement.py`
  - **测试**：已迁移资源无 FineGrainedPermissionService、Config model/binding parser、
    permission template、creator fallback、shadow write、legacy/dual client、F018 route；
    llm_server/llm_model 仅显式 allowlist。
  - **覆盖 AC**：AC-05, AC-34, AC-103, AC-104, AC-105, AC-112, AC-115, AC-116, AC-117, AC-144, AC-145
  - **依赖**：T050, T052, T054, T056, T058, T060, T062, T070, T074, T126

- [x] **T129：退役细粒度第二 PDP 与 roster cache**
  - **文件**：`src/backend/bisheng/permission/domain/services/fine_grained_permission_service.py`,
    `src/backend/bisheng/permission/domain/services/application_permission_service.py`
  - **逻辑**：删除已迁移资源的第二 PDP、Config fallback 与旧 application facade；llm allowlist
    隔离在明确 legacy internal adapter，不暴露给 F048。
  - **验收**：T128 对第二 PDP/application service 的断言通过
  - **依赖**：T128

- [x] **T130：退役 knowledge 权限 templates**
  - **文件**：`src/backend/bisheng/permission/domain/knowledge_space_permission_template.py`,
    `src/backend/bisheng/permission/domain/knowledge_library_permission_template.py`
  - **逻辑**：删除运行时模板和 Config permission ID 解释，调用方已由 T052/T054 接管。
  - **验收**：T128 对 knowledge templates 的断言通过
  - **依赖**：T128

- [x] **T131：退役旧 roster cache 与 check endpoint**
  - **文件**：`src/backend/bisheng/permission/domain/services/relation_roster_cache.py`,
    `src/backend/bisheng/permission/api/endpoints/permission_check.py`
  - **逻辑**：删除 relation roster 缓存和旧 relation check HTTP 入口；新 roster/check 只由
    F048 explain/decision endpoints 提供。
  - **验收**：T128 对 cache/check endpoint 的断言通过
  - **依赖**：T128

- [x] **T132：退役旧 resource_permission 与 backfill runtime**
  - **文件**：`src/backend/bisheng/permission/api/endpoints/resource_permission.py`,
    `src/backend/bisheng/permission/domain/relation_model_backfill.py`
  - **逻辑**：删除旧 Config model/binding CRUD、relation/permission_id 成员入口和运行期 backfill；
    历史数据只由 T126 scripts CLI 迁移。
  - **验收**：T128 全部通过
  - **依赖**：T128, T129, T130, T131

- [x] **T133：退役 application/tool 权限 templates**
  - **文件**：`src/backend/bisheng/permission/domain/application_permission_template.py`,
    `src/backend/bisheng/permission/domain/tool_permission_template.py`
  - **逻辑**：删除旧动作数组/relation 模板；workflow/assistant/tool 只走具体 action。
  - **验收**：T128 对 application/tool templates 的断言通过
  - **依赖**：T128

- [x] **T134：退役 channel/workflow 旧权限模板**
  - **文件**：`src/backend/bisheng/permission/domain/channel_permission_template.py`,
    `src/backend/bisheng/permission/domain/workflow_app_permission.py`
  - **逻辑**：删除旧四档/permission_id 映射，保留业务 Service 的 F048 action adapter。
  - **验收**：T128 全部通过
  - **依赖**：T128, T129, T130, T131, T132, T133

---

## Wave 8 — 性能、集成、E2E 与文档收口

### 后端 Domain / 集成验证

- [x] **T135：BENCH-01 性能合同测试**
  - **文件**：`src/backend/test/permission/test_f048_performance_contract.py`
  - **测试**：固定脱敏 fixture 和 checksum，分别测 Check、20/50/100 BatchCheck、ListObjects
    direct/department/group/inherit、10/100/1000 结果与业务 cursor；断言设计阈值和不静默截断。
  - **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-69
  - **依赖**：T016, T018, T036, T134

- [x] **T136：实现 BENCH-01 可复现实验脚本**
  - **文件**：`src/backend/scripts/benchmark_f048_permission_paths.py`
  - **逻辑**：从脱敏 fixture 运行基线/新路径，输出 P50/P95/P99、dispatch/datastore reads、
    dataset/model checksum；不连接生产，不作为迁移预演。
  - **验收**：T135 全部通过
  - **依赖**：T135

- [x] **T137：真实 OpenFGA v1.15.1 集成测试 harness**
  - **文件**：`src/backend/test/permission/test_f048_openfga_integration.py`
  - **测试**：在 pinned image/digest 验证 model tests、同 Store新 model、Store-scoped legacy delete、
    higher consistency、atomic Write、Check/List 语义和 max resolve depth。
  - **覆盖 AC**：AC-22, AC-23, AC-28, AC-30, AC-33, AC-34, AC-37, AC-38, AC-46, AC-47, AC-54, AC-69, AC-109, AC-111, AC-112, AC-114
  - **依赖**：T016, T018, T020, T028, T032, T034, T124

- [x] **T138：MySQL/DM8 schema+checkpoint 集成测试 harness**
  - **文件**：`src/backend/test/permission/test_f048_database_integration.py`
  - **测试**：默认静态断言 Alembic 只做 DDL；环境门控的 disposable MySQL/DM8 用例验证
    schema、唯一键、cursor、CAS 与 checkpoint 约束。正式 `migrate/verify` 逻辑由
    T121～T127 的 coordinator/runtime/verifier/CLI 测试覆盖；本任务不伪称已经运行目标数据库。
  - **覆盖 AC**：AC-93, AC-94, AC-95, AC-137, AC-138, AC-139, AC-140, AC-146, AC-147, AC-158
  - **依赖**：T011, T126, T127, T134

- [x] **T139：更新权限架构现状文档**
  - **文件**：`docs/architecture/10-permission-rbac.md`, `docs/constitution.md`
  - **逻辑**：在实现完成后回写单 OpenFGA PDP、Catalog/Model/Grant、业务 verified target、
    projection ledger、同 Store 单 model pin、DDL-only Alembic 与 scripts 数据迁移现状；
    不保留未来式或旧双模型说明；复核 C4 durable compensation wording 已经 PR 审查且与
    RULE-8 anchor 一致。
  - **依赖**：T134, T137, T138

- [x] **T140：记录 F048 E2E 范围决策并形成报告**
  - **文件**：`features/v3.0.0-beta1/048-rebac-permission-model-grants/e2e-test-report.md`
  - **测试**：功能、迁移脚本、专项回归、两端构建和静态门禁已完成；用户于 2026-07-30
    明确确认本地不执行真实环境 E2E。报告保留未执行项，不能被解释为生产发布验证证据。
  - **覆盖 AC**：AC-06, AC-13, AC-14, AC-16, AC-22, AC-23, AC-24, AC-28, AC-30, AC-34, AC-40, AC-44, AC-49, AC-50, AC-51, AC-53, AC-54, AC-55, AC-56, AC-57, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65, AC-66, AC-67, AC-68, AC-69, AC-70, AC-96, AC-98, AC-100, AC-101, AC-102, AC-104, AC-105, AC-107, AC-114, AC-115, AC-117, AC-150, AC-151, AC-152, AC-153, AC-154, AC-155, AC-156, AC-157, AC-158
  - **依赖**：T093, T108, T127, T134, T136, T137, T138, T139

- [x] **T141：修复大 Config 冻结载荷并保留排障原始行**
  - **文件**：`src/backend/bisheng/permission/domain/models/migration.py`,
    `src/backend/bisheng/core/database/alembic/versions/v3_0_0_f048_migration_item_message_longtext.py`,
    `src/backend/bisheng/permission/migration/f048_coordinator.py`,
    `src/backend/bisheng/permission/migration/f048_runtime_storage.py`,
    `src/backend/bisheng/permission/migration/f048_verifier.py`
  - **逻辑**：将 migration item 冻结载荷改为 MySQL LONGTEXT/DM8 CLOB；只删除已验证的
    legacy tuple，不删除两份 Config 原始行；Config 保留数量只进 verify 审计证据，不作为
    开放门禁。
  - **测试**：单 head/DDL-only、大文本 ORM 类型、迁移不调用 Config delete、Config 保留时
    verify 可完成。
  - **覆盖 AC**：AC-93, AC-94, AC-95, AC-145, AC-146, AC-147
  - **依赖**：T006, T008, T011, T123, T124

- [x] **T142：修复真实历史数据的 mapping-blocked 兼容与明细账本**
  - **文件**：`f048_model_mapper.py`, `f048_tuple_mapper.py`, `f048_coordinator.py`,
    `f048_runtime_storage.py`, `permission_migration_source.py`（knowledge domain）及对应测试
  - **逻辑**：保留 visibility-only 自定义模型；按旧 usage/manager/owner/relation tier 推导并在
    新模型等级处安全收窄 manage boundary；孤儿 binding 只审计不恢复授权；知识子资源 tenant
    以根 Knowledge 为 canonical，父目录已删除的 FAILED 文件由业务 adapter 标为 stale；
    model/tuple/mode mapping 差异批量写入 migration item 并同步 blocker_count。
  - **测试**：覆盖仅可见模型不附加动作、旧 tier 蕴含与收窄、孤儿 binding no-op、跨租户
    child 修正、stale failed resource 退休、mapping blocker 明细持久化与 resume 忽略审计项。
  - **依赖**：T112～T127, T141

- [x] **T143：修复 D4 checksum 与 preserved tuple 误报**
  - **文件**：`migration_repository.py`, `f048_runtime_verification.py` 及对应测试
  - **逻辑**：source checksum 在应用层按 source kind/locator 做确定性排序，消除数据库
    collation 差异；preserved tuple 核对排除迁移计划已退休的 `STALE_RESOURCE_TUPLE` 和
    `CANONICAL_IDENTITY_STATE=false` tuple，不恢复已经 canonical 事实确认失效的授权。
  - **测试**：覆盖数据库返回顺序不同时 checksum 稳定，以及 stale parent/canonical-false
    member 不进入 preserved expected 集合。
  - **依赖**：T123, T124, T142

---

## 实际偏差记录

> 只记录一句话指针；设计原因和反直觉事实回写 [design.md](./design.md)。
> 若偏差推翻已确认 AC 或 Design 决策，立即停止并重新取得用户确认。

- T066 的生产接入范围扩展到 F014/F015 的 SSO 全量同步与组织 reconcile 调用链，用同一
  `DepartmentTopologyProjectionService` 关闭“业务行已提交、ledger 尚未创建”的崩溃窗口；
  不改变已确认 AC 或 Design 决策。
- T140 按用户 2026-07-30 明确指示，不在本地执行真实环境 E2E；本次完成口径收敛为功能代码、
  DDL 与正式数据迁移/校验脚本开发完成。报告继续明确 E2E 未执行，不能作为生产发布证明。
- T138 评审后收紧为数据库 schema/checkpoint integration harness；完整数据迁移命令逻辑由
  T121～T127 的单元/契约测试验证，未把未执行的 MySQL/DM8 目标环境测试写成已完成事实。
- 用户于 2026-07-30 重新确认不配置随迭代变化的 Store/model/Catalog ID；T010/T019/T020、
  T125～T127 改为按稳定 Store name 自动发现唯一 Store/latest model，运行时再与 F048
  checksum 和 SQL CURRENT Catalog 严格匹配；迁移 CLI 移除 `--expected-store-id`，
  resume/verify 只接受 durable run 已记录的 Store/source model。
- 用户于 2026-07-31 将升级运维收敛为既有简单流程：更新镜像并启动后，旧 model 使
  API/Worker 仅进入 `MIGRATION_REQUIRED/NOT_READY`，不初始化 F048 runtime、不发布 ready
  heartbeat，应用自动拒绝非 health HTTP/WS；运维直接进入 backend 容器执行 migrate/verify，
  成功后重启服务并自动恢复访问。因此移除 `F048_SERVICES_STOPPED` 人工标记，不引入自动
  迁移、双 model、入口人工切换或额外运维容器。
- 真实迁移发现 `permission_migration_item.message` 的 MySQL TEXT 无法容纳约 120 KiB 的
  binding Config 冻结载荷；按用户 2026-07-31 指示改为 MySQL LONGTEXT/DM8 CLOB，并保留两份
  Config 原始行供排障。verify 仍记录其数量但不阻断，旧 Config 运行时路径继续退役。
- 116 真实迁移在 source reconciliation 后继续暴露 model/binding/parent mapping blocker；按用户
  2026-07-31“修复”确认，T142 将可由当前 Store 与业务 canonical 事实确定的数据改为无扩权的
  自动兼容：仅可见模型不补动作、超出新等级的 manage scope 只收窄、无 tuple 的 binding 不复活、
  child tenant 取根 Knowledge、父目录已删除的 FAILED 文件不进入权限图。仍无法形成连续低级边界、
  未知动作、真实跨租户主体或冲突 tuple 继续 fail closed。
- 116 的 D4 verify 进一步发现 MySQL collation 顺序与 Python 冻结顺序不同，以及 preserved
  核对仍包含计划删除的 stale/canonical-false tuple；T143 只修正取证算法，不修改已经完成的
  target tuple 写入和 legacy tuple 退休结果。
