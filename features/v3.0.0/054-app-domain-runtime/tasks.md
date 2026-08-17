# Tasks: 托管应用领域模型与运行时（compose 形态 + 统一入口）

**关联规格**: [spec.md](./spec.md)（65 条 AC，What 的唯一真相）· [design.md](./design.md)（How 的唯一真相，D1–D15 / 坑 1–32 / §4.2 契约 / §7 测试策略）
**版本**: v3.0.0
**裁剪基准**: [mvp-114-path.md](../mvp-114-path.md) **§6 MVP-核心（预算受限版）** —— Wave 1–3 全部为 `[MVP-核心]`；Wave 4 = `[MVP-114]` 纵切紧随项（design §8 优先级 1–3）；Wave 5 = release 必做项。**后置 ≠ 裁掉**（spec 决议-3 对出站白名单已明确要求）
**代码事实口径**: 本文所有 `文件:行号` 沿用 design.md（`3.0-vibe` HEAD `b63a320f2`，2026-08-17 由四份探查笔记 E1–E4 核实；路径以 `src/backend/bisheng/` 为根，前端另注 `platform/` = `src/frontend/platform/src/`、`client/` = `src/frontend/client/src/`，仓根路径显式写出）。行号会漂移、符号名不会——落地前以符号名重定位。

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-08-17 定稿（65 AC，同日独立审查 28 条已修订；决议-1～8） |
| design.md | ✅ 已评审 | 2026-08-17 初版 + 同日独立审查 16 条修订；接手时的第一入口 |
| tasks.md | ✅ 已拆解（2026-08-17） | 本文；`/sdd-review tasks` 独立审查 16 条已修订（补 7 个测试任务 T082a/T084a/T086a/T087a/T089a/T090a/T094a + 可观测任务 T097） |
| 实现 | 🔲 未开始 | 0 / 104 完成。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3-§4 |

---

## 开发模式

**按 Wave 组织任务**：
- **Wave 1**（T001–T017）= 基础设施（三张表 / Alembic / 错误码 161 段 / `app_runtime` 开关 / 常量 / 审计登记 / arch-guard RULE-10 / conftest）+ **`app` 资源类型注册**（后端 8 处 + 前端 3 处 + 114 存量生效脚本）。这两组互不依赖，可并行。
- **Wave 2**（T018–T045）= 两个**独立包**（`src/runtime-manager/`、`src/app-proxy/`，均在 `src/backend/bisheng/` 之外）+ backend 内部授权端点。runtime-manager 与 app-proxy 各自有独立的测试基础设施任务，两条线可并行（app-proxy 只依赖 §4.2 的 RPC 契约，不依赖对方实现）。
- **Wave 3**（T046–T075）= backend 领域服务与 API（状态动作 / 元信息 / 读侧 / UNION 第三支与 6 组硬闸）+ platform 前端 + client 一处开关读取 + 114 部署增量与联调。
- **Wave 4**（T076–T081）= `[MVP-114]` 紧随项：出站白名单双层 + docker-socket-proxy + WS 反代与三不变量。
- **Wave 5**（T082–T097）= release 必做项：两个过渡态页 / 附件存储 / 数据面 WB-06 / 访问记录 / 预览入口 / 二维码 / `node20`·`static` 模板 / 备份手册 / AC-64 / 稳定性双形态验收 / E2E / 关键日志与指标。

每个任务标 `依赖:`，无依赖的可并行。

**编号后缀 `a` 的含义**：`T082a` / `T084a` / `T086a` / `T087a` / `T089a` / `T090a` / `T094a` 是 2026-08-17 tasks 审查补入的**测试任务**，为保持既有 T 编号稳定而用后缀区分。**后缀 a 的测试任务一律先于其配对实现任务执行**（写在文件里也物理排在前面）；`依赖:` 仍是唯一的顺序真相。

**后端 Test-First**：测试任务先于配对实现任务，`覆盖 AC` 逐条列举（禁 `AC-01~AC-05` 范围写法）。基础设施任务（ORM / Alembic / 错误码 / Settings / 常量 / 审计登记 / conftest / 包工程骨架）无测试配对、排最前。后端单测放 `src/backend/test/app_runtime/`（不放 `test/` 根），`asyncio_mode=auto`；两个独立包的测试放各自包内 `tests/`。集成测试连 test 中间件（MySQL / Redis / OpenFGA），在 CI 跑。

**容器相关测试一律标「测试降级：需 docker，CI 中间件阶段 + 114 手动验证」**——runtime-manager 的单测用 fake docker 客户端断言**下发参数**（`HostConfig` / `NanoCpus` / `Memory` / `ReadonlyRootfs` / `SecurityOpt` / 无 `PortBindings`），真容器行为（build → run → probe → kill 自愈 → 限额核验）在 CI 的 docker 阶段与 114 上跑。

**前端**：Platform 任务附「手动验证」步骤（Playwright 未落地），Client 任务同理。platform **react-query 已被 lint 冻结**（坑 25 前置）→ 新代码用 `useTable` / `useInfiniteCursorTable` / 裸 `useState + useEffect`；**详情页 / 日志接口对非 owner 不得返回 403/404**（坑 25：platform 拦截器对 GET 会整页跳 `/403`），一律用业务码 161xx 或 `silent: true`。client 新读取 hook **不得 import recoil**（lint 冻结），用 react-query v4。新增 i18n key 三语（zh-Hans / en / ja）同 PR。

**自包含任务**：每个任务内联文件、逻辑、AC 覆盖；设计论证指向 design §X / D-x / 坑 n，不复制。

**编号 ≠ 严格执行顺序**：Wave 2 的两条包线（T018–T031 runtime-manager、T036–T045 app-proxy）与 Wave 1 的两组（基础设施、权限注册）均可并行；`依赖:` 是唯一的顺序真相。

**跨 Feature 副作用登记**（release-contract 表 1 / 检查项 17）：
- **T002 / T089**（`core/database/tenant_filter.py:39` 的 `_TENANT_AWARE_MODEL_MODULES` 加项——design §4.3 要求 `{app, app_version, app_instance, app_access_log}` **四个**模块路径全部登记：前三个由 T002 落、`app_access_log` 由 T089 落，**两处任务缺一即漏登记**）· **T004**（`docs/constitution.md` C5 登记表 + **`features/v3.0.0/release-contract.md:98` 已分配模块编码表**，`app_factory` 由 `_待分配_` 落定为 161–164）· **T007**（`database/models/audit_log.py` 两处白名单 + platform `controllers/API/log.ts` 三处，审计对象归 F056 查询面、写入归本 Feature）· **T008**（`scripts/arch-guard.sh` 新增 RULE-10 + `docs/constitution.md` 锚点表——影响全仓后端写入）· **T089**（`release-contract.md` 表 1 新增领域对象 `AppAccessLog` 行）
- **T011 / T012 / T013**（改 F048 领域的 `MIGRATED_RESOURCE_TYPES` / `ACTION_RESOURCE_SCOPES` / `FIXED_CUSTOM_TYPES` / `GRANT_SUBJECT_RESOURCE_TYPES` / registry 组合根——**只增 `app` 一个值，不改既有类型行为**；模型 checksum 变化的存量影响由 T017 升级脚本承接，坑 3/4）
- **T059 / T060**（`database/models/flow.py` 的 `_build_apps_subquery` 加第三支 + `FlowType` 新枚举 35；`api/services/workflow.py` 的 `SUPPORTED_APP_TYPES` / `_FLOW_TYPE_TO_RESOURCE_TYPE` / 标签 4 处 + `group_resource.ResourceTypeEnum.HOSTED_APP=10`——**F056 广场的 `get_online_flows_page` 走同一道闸，直接受益，不要重复改**）。⚠️ **`_build_apps_subquery`（`flow.py:660`）共 4 个调用方**，加第三支会让托管应用同时流进另两条与构建页无关的路径：`get_all_app_by_time_range_sync:810`（→ `api/services/workflow.py:1039`，按时间范围取应用）与 `get_first_app:849`（→ `scripts/sync_increment_table.py:53`，**商业版增量同步**）——两者的产品口径须在 T059 显式确认（不是"顺带受益"），并跑既有回归 `src/backend/test/workflow/test_flow_dao_tenant_isolation.py`（覆盖这四个方法的租户隔离）
- **T063 / T065**（platform 共享组件两处：`components/bs-comp/cardComponent/avatar.tsx` 的 `AppAvator` 图标 map 按 `AppNumType` 分支，加第三类型即改**共享头像组件**；`components/bs-comp/cardComponent/index.tsx` 是 workflow / assistant 共用的**共享组件**，只加两个可选 prop、缺省行为不变。两者缺省行为均须逐像素不变；回归验证由 F056 承接 GOV-01 验收 6）
- **T072 / T073 / T074**（部署契约：systemd 单元 / nginx conf 两份同构 / compose service，运维仓 `bisheng-ops` 与产品仓 `docker/` 同批改，K10 / 坑 16）
- **F055 消费面**：T049（`stage_version`）· T051（五个状态动作 + `lifecycle_hooks`）· T053（`AppMetaService.update_meta`）· T006（`DEFAULT_TIERS` 供 F055 `ResourceTier` seed 读取）· T047（`orchestrator_client` 门面）——**F055 只调不直写**（决议-8），签名变更须同步 F055 tasks。

---

## Tasks

### Wave 1 · `[MVP-核心]` 基础设施（无测试配对，排最前）

- [ ] **T001**: `[MVP-核心]` ORM `app` / `app_version` 模型 + DAO
  **文件**: `src/backend/bisheng/database/models/app.py`（新）, `src/backend/bisheng/database/models/app_version.py`（新）
  **逻辑**: 按 design D8 建两表（继承 `SQLModelSerializable`）。`app`：`id`(str PK) / `slug`(str，**全局 `UniqueConstraint`**，跨租户唯一) / `name` / `description` / `logo` / `owner_user_id`(int) / `tenant_id`(int) / `state`(VARCHAR16 显式列) / `current_version_id`(str null) / `pending_version_id`(str null) / `create_time` / `update_time`；**主键必须是 str**（UNION 三支列类型要与 `Flow.id` / `Assistant.id` 一致）。`app_version`：`id` / `app_id` / `version_no`(int) / `kind` / `terminal_state`(null) / `code_object_key` / `manifest`·`capabilities`·`injections`(`JsonType`) / `tier_id`·`runtime`(显式列) / `image_ref` / `submitted_at`；**无 `tenant_id`**（K5 ②，隔离经 `app_id` 借道 `app` 行）。DAO：`AppDao.{aget, aget_by_slug, acreate, aupdate_state_cas, alist_by_owner}`、`AppVersionDao.{ainsert, aget, alist_by_app, amark_terminal}`——**`AppVersionDao` 不提供通用 UPDATE**（AC-02 只增不改，`terminal_state` 是唯一单列更新口）；**每个按 `version_id` 起手的 DAO 方法签名强制带 `app_id`**（坑 31）。禁 `JSON_EXTRACT` / `JSON_CONTAINS`（K4）、禁批量 UPDATE / DELETE（K5）。
  **回滚**: 模型文件删除即回滚（表 DDL 在 T003）。
  **跨 Feature**: 落点在 `database/models/` 而非 `app_runtime/domain/models/` 是 arch-guard RULE-2 逼出来的（坑 27 / D8「模型落点」），**不要"顺手搬回模块内"**。
  **依赖**: 无

- [ ] **T002**: `[MVP-核心]` ORM `app_instance` 模型 + DAO + 租户感知登记
  **文件**: `src/backend/bisheng/database/models/app_instance.py`（新）, `src/backend/bisheng/core/database/tenant_filter.py`（`_TENANT_AWARE_MODEL_MODULES:39` 登记 `bisheng.database.models.app` / `.app_version` / `.app_instance`）
  **逻辑**: `app_instance`：`id` / `app_id` / `tenant_id` / `version_id` / `phase` / `health` / `exec_ref`（执行体引用，compose 形态是容器名，**唯一允许出现形态特有值的字段、且只对内**）/ `started_at` / `restart_count` / `last_probe_at`；DAO `AppInstanceDao.{aget_by_app, aupsert, aset_phase}`。tenant_filter 登记只保证 metadata 被 import——**`app_version` 无 `tenant_id` 列，登记后仍不受自动过滤**（K5 ②、坑 31），在登记处写一行注释点明。⚠️ design §4.3 要求登记的是**四个**模块路径，第四个 `bisheng.database.models.app_access_log` 随该表一起由 **T089** 落（本任务只落前三个）；在登记处留一行 `# app_access_log 见 F054 T089` 提醒，避免建表任务漏登记。
  **回滚**: 同 T001；tenant_filter 登记回退 = 删元组项。
  **跨 Feature**: 改 F048/核心库共享文件 `tenant_filter.py`，只增元组项，不改过滤逻辑。
  **依赖**: T001

- [ ] **T003**: `[MVP-核心]` Alembic revision：三张表 DDL
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v3_0_0_f054_app_runtime_tables.py`（新）
  **逻辑**: DDL-only（`core/database/alembic/AGENTS.md`）：建 `app` / `app_version` / `app_instance` 三表；`down_revision` 取 `uv run alembic heads` 的唯一头；**不传 `mysql_charset` / `mysql_collate`**（DM8 双方言，C2 / K4）；JSON 列用 `JsonType` 对应的方言类型（DM8 落 CLOB）；索引：`app.slug` 唯一、`app(tenant_id, state)`、`app_version(app_id, version_no)`、`app_instance(app_id)`。
  **回滚**: `downgrade()` 按 `app_instance → app_version → app` 顺序 drop（无外键约束，仍按此序避免残留）；**回滚前须先停运并删除全部托管应用**（否则容器与本机卷 `{data_root}/apps/*` 变成无主孤儿，只能靠 T029 的孤儿回收清理）——说明写进 revision docstring。
  **依赖**: T001, T002

- [ ] **T004**: `[MVP-核心]` 错误码 161 段 + C5 登记 + 三语
  **文件**: `src/backend/bisheng/common/errcode/app_factory.py`（新）, `docs/constitution.md`（C5 登记表：`app_factory` 由 `_待分配_` 落定为 161=F054 / 162=F055 / 163=F056 / 164=F059）, `features/v3.0.0/release-contract.md`（**「已分配模块编码」表 `:98` 的 `app_factory` 行同批把 `_待分配_` 改成 161–164 并按 F054/F055/F056/F059 逐段注明**）, `src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`（三语视为一组）
  **逻辑**: 按 design §4.2 ⑥ 定义 `AppFactoryError(BaseErrorCode)` 与本期启用码：`16101`（应用不存在）/ `16102`（状态冲突，前态不符）/ `16103`（slug 冲突）/ `16104`（已上线不可删除，请先停运）/ `16105`（仅 owner 可执行）/ `16121`（编排器不可用）/ `16122`（构建失败）/ `16123`（`runtime` 取值不支持）/ `16124`（启动探活失败）/ `16125`（运行环境容量不足）/ `16141`–`16146`（入口六态）/ `16161`（无权查看日志）/ `16181`（工场运行时层未部署）；`16162`（无权访问应用数据）留 Wave 5。三语文案落 `packages/locales`（生成物 `platform/public/locales/*/api_errors.json`、`client/src/locales/*/api_errors.gen.json` **由脚本生成、不手改**，CI `pnpm check-i18n` 校验）。**161 段确认空闲**（16x 只有 160=dataset；260 已被 F049 占用，K11）。**回写 release-contract 是硬要求**：F055 / F056 / F059 拆自己的段位时以该表为唯一权威来源，只改 constitution 不改 contract → 下游三个 Feature 无处可查（design 修订历史「需回写上游的两项」之①）。
  **跨 Feature**: `docs/constitution.md` C5 表与 `features/v3.0.0/release-contract.md:98` 编码表都是全版本共享清单，**同一次改动同批落**，只增本 Feature 段位、不动 260 行。
  **依赖**: 无

- [ ] **T005**: `[MVP-核心]` 工场运行时层开关三段式（后端两段）+ `app_runtime` Settings
  **文件**: `src/backend/bisheng/core/config/app_runtime.py`（新：`AppRuntimeConf`）, `src/backend/bisheng/core/config/settings.py`（`multi_tenant` / `open_platform` 旁加 `app_runtime: AppRuntimeConf`）, `src/backend/bisheng/api/v1/endpoints.py`（`get_env` 增 `app_runtime_enabled`）
  **逻辑**: `AppRuntimeConf(enabled=False, manager_base_url='http://127.0.0.1:8091', manager_hmac_secret='', proxy_hmac_secret='', obo_secret='', obo_ttl_seconds=900, entry_base_url='', data_root='/opt/bisheng/app-data', reserve_mb=2048, overcommit_ratio=0.8, build_reserve_mb=2048, build_index_url='', ws_max_lifetime_seconds=28800)`；进程级 config.yaml、**不进 DB 热配置**（K12，`initdb_config` 有 100s Redis 缓存、语义是租户偏好）。与 F049 的 `open_platform.enabled` 是**同形态兄弟键、不合并**（AC-61 两开关任意组合可启动）。三个 secret 走 `!env` 或 Fernet（C6），不落代码。⚠️ **部署顺序**（坑 23）：`load_settings_from_yaml` 对未知顶层键直接 `KeyError` 拒启 → **必须先发代码、后往 `config.yaml` 加 `app_runtime:` 键**，这条写进 T075 的 114 步骤。
  **粒度说明**（一任务 3 文件的理由）：`AppRuntimeConf` 定义、`Settings` 挂载、`/api/v1/env` 暴露 `app_runtime_enabled` 是**同一个配置项的三段接线**，任一段单独落地都得不到可运行的开关（缺挂载 → 配置读不到；缺 env 暴露 → 两个 SPA 判不了「整层未装」，AC-62 不成立），且三段共用同一个键名，拆开只会制造键名漂移窗口。
  **依赖**: 无

- [ ] **T006**: `[MVP-核心]` 常量与枚举：应用态 / 审计动作 / 出厂档位
  **文件**: `src/backend/bisheng/app_runtime/domain/constants.py`（新）, `src/backend/bisheng/app_runtime/__init__.py`（新，空）
  **逻辑**: `AppState` 枚举（`draft` / `online` / `pending_capacity`（待上线·资源不足）/ `stopped` / `deleted`）+ **合法跃迁表 `ALLOWED_TRANSITIONS`**（AC-03：草稿→已上线；已上线↔已停运；上线遇容量不足→待上线；待上线→已上线；草稿/待上线/已停运→已删除；**已上线→已删除禁止**）；`AppAuditAction` Enum（`app.publish` / `app.publish_pending` / `app.manual_publish` / `app.stop` / `app.resume` / `app.delete` / `app.delete_hook_failed` / `app.meta_update` / `app.data_row_edit`，先例 `tenant/domain/constants.py:14-46`）；`DEFAULT_TIERS`（轻量 0.5 vCPU / 512 MiB · 标准 1 / 1024 · 增强 2 / 2048）——**这是三档出厂规格的唯一代码来源，F055 的 `ResourceTier` seed 从本表读取落库**（design D11 对账口径，§6.1 Outgoing 契约）。
  **依赖**: 无

- [ ] **T007**: `[MVP-核心]` 审计动作 lockstep 登记（后端 2 处 + 前端 3 处 + 三语）
  **文件**: `src/backend/bisheng/database/models/audit_log.py`（`_UI_VISIBLE_V2_ACTIONS:178-203` + `_V2_NAMESPACE_TO_ACTION_PREFIX:209-213` 加 `app.` 族）, `src/frontend/platform/src/controllers/API/log.ts`（模块下拉 / actions 数组 / `getActionsByModuleApi` switch 三处）
  **逻辑**: 登记 T006 的全部 `app.*` action（含 Wave 5 才产生事件的 `app.data_row_edit`，**一次登记到位避免二次改同一处**）。坑 24：不进 `_UI_VISIBLE_V2_ACTIONS` 白名单 → **写库但「系统操作」页看不到**，AC-65 验收判不通过。三语 i18n key 同 PR。
  **跨 Feature**: `audit_log.py` 白名单是全平台共享清单，只增不改；查询面归 F056。
  **跨栈说明**（清单 7/18 禁「跨前后端任务」的**刻意例外**）：后端 `_UI_VISIBLE_V2_ACTIONS` 白名单与 platform `log.ts` 的模块下拉 / actions 数组 / `getActionsByModuleApi` switch 是**同一份清单的两个副本**，是仓内既成的 lockstep 结构（坑 24）；拆成两条任务只会制造"后端已写库、前端下拉里没这一项 → 审计页筛不出来"的中间态，且两条任务必须互为依赖、同 PR 合入，实质仍是一个原子改动。故本任务刻意跨栈；**新增行为一律只加 `app.` 族，不动既有任何一族**。
  **依赖**: T006

- [ ] **T008**: `[MVP-核心]` arch-guard RULE-10：backend 禁编排依赖
  **文件**: `bisheng/../scripts/arch-guard.sh`（仓根 `scripts/arch-guard.sh`，现有 RULE-1~9 之后新增 RULE-10）, `docs/constitution.md`（arch-guard 锚点表新增一行，并订正"8 条 RULE"的过时表述）
  **逻辑**: RULE-10 = **只扫 `src/backend/bisheng/**` 的 `.py`**（坑 18：`.drone.yml:57,89,173,224,259,316` 是 CI 用法，扫进去会假阳性并被人顺手关掉），命中即 VIOLATION：`^(from|import)\s+(docker|kubernetes|aiodocker|kubernetes_asyncio)\b`、字面量 `/var/run/docker.sock`、`DOCKER_HOST`。这是 AC-14「部署检查可核验」的强制力来源（K1：今天只是纸面承诺，全仓 `import docker` = 0）。同批把 `src/backend/pyproject.toml` 的依赖检查写进 T046 的自动化断言。
  **回滚**: 删除 RULE-10 段落 + 回退 constitution 表行。
  **跨 Feature**: 影响全仓后端写入的 PostToolUse 守卫——落地前先在本地跑 `bash scripts/arch-guard.sh` 全量确认零存量违规（design K1 已核实为 0）。
  **依赖**: 无

- [ ] **T009**: `[MVP-核心]` 后端测试基础设施 `test/app_runtime/conftest.py`
  **文件**: `src/backend/test/app_runtime/conftest.py`（新）, `src/backend/test/app_runtime/__init__.py`（新）
  **逻辑**: fixtures：`tenant_admin_payload`（**非超管**的租户管理员，避开 admin 短路 ReBAC，坑 26）/ `normal_user`（本租户普通自然人，作被授权方）/ `chinese_name_user`（**姓名含中文**，专供注入头 percent-encoding 用例，坑 9）/ `app_factory`（直接经 DAO 落一行 `app` + 一行 `app_version`，参数化 state / owner / tenant）/ `fake_orchestrator`（monkeypatch `orchestrator_client` 的 **10 个方法**为可编程 stub——与 T047 门面逐一对齐：`build` / `build_status` / `deploy` / `stop` / `destroy` / `probe` / `admission` / `status` / `logs` / `runtime_status`，返回 §4.2 ① 的响应形状；**stub 数必须等于门面方法数**，漏一个的现象是该方法静默走真实 HTTP、测试在 CI 里连不上 8091 才暴露）/ `sub_tenant`（子租户 + 其管理员，跨租户断言用）/ `fga_down`（monkeypatch F048 判定抛 `PermissionServiceUnavailableError`，AC-12 fail-closed 用）/ `audit_sink`（捕获 `AuditLogDao.ainsert_v2` 调用）。**autouse fixture 清 `HTTP(S)_PROXY` / `ALL_PROXY` env**（缺 `socksio` 会整批误报 ERROR，memory `reference_local_backend_pytest_socks_proxy`）。fixture 体内**惰性 import** 业务 Service，避免尚未落地的模块让整包收集失败。
  **依赖**: T001, T002

### Wave 1 · `[MVP-核心]` `app` 资源类型注册（Test-First）

- [ ] **T010**: `[MVP-核心]` `app` 资源类型注册测试（单元 + 集成）
  **文件**: `src/backend/test/app_runtime/test_app_permission_registration.py`（新）
  **逻辑**: `test_catalog_action_effective_for_app`（`is_action_effective("app", a)` 对 `use` / `edit` / `manage_permission` / `delete` / `publish` / `unpublish` 六动作为真——**不新增 action code**，D9）；`test_owner_gets_all_actions_on_create`（`authorize_created` 后 owner 的 `my-permissions` 含全动作）→ AC-09；`test_default_visible_only_to_owner`（首发落库后未授权的普通用户 `check_business_action("app", id, other, "use")` = deny）→ AC-11；`test_grant_use_to_user_department_group_then_allow`（分别授用户 / 部门 / 用户组后 allow）→ AC-09；`test_visibility_change_effective_next_request_and_audited`（撤销后下一次判定即 deny；PermissionGrant 写入记录变更人）→ AC-10；`test_tenant_admin_short_circuit_visible`（本租户管理员天然 allow，非本 Feature 新增）→ AC-09；`test_fga_unavailable_denies_not_allows`（`fga_down` fixture → 抛 `PermissionServiceUnavailableError` 被翻成 deny + `16146`，**绝不放行**）→ AC-12；`test_grant_subjects_five_endpoints_accept_app`（users / user-groups / departments-children / departments-search / **departments/{id}/path-tree** 五处对 `resource_type=app` 均不 403——坑 2，第 5 处最易漏）→ AC-09；`test_linsight_skill_style_half_registration_would_fail`（回归断言：若 registry 未注册则 `check_business_action` 抛 `InvalidCatalogActionError`，坑 32 的反面样板）→ AC-12。
  **测试降级**: 无（连 test 中间件 OpenFGA，在 CI 跑）。
  **覆盖 AC**: AC-09, AC-10, AC-11, AC-12
  **依赖**: T001, T009

- [ ] **T011**: `[MVP-核心]` FGA 模型常量 + Catalog 策略两处
  **文件**: `src/backend/bisheng/core/openfga/authorization_model_f048.py`（`MIGRATED_RESOURCE_TYPES:32-42` 加 `"app"`；`RESOURCE_ACTION_SCOPES:55-78` 的 `use`/`edit`/`publish`/`unpublish` 加 `"app"`；`MODEL_VERSION` 升 `f048-v2`）, `src/backend/bisheng/permission/domain/services/catalog_policy.py`（`MIGRATED_RESOURCE_TYPES:31-43` 加 `"app"`；`ACTION_RESOURCE_SCOPES:45-68` 逐 action 加 `"app"`）
  **逻辑**: D9 的 8 处清单第 1–4 项。**两份 `MIGRATED_RESOURCE_TYPES` 必须同批改**（坑 1：漏前者 → 模型里没有 `app` type、写 tuple 400；漏后者 → `derive_action_release` 在每次 `_load_snapshot` 都跑，**Catalog 读取直接崩**）。`RESOURCE_ACTION_SCOPES` 是**死常量**（全仓无消费者），同步只为可读性，别在评审里当锚点（坑 5）。**明确不改**：`PARENT_TYPES` / `SYSTEM_SHARED_ACTION_TYPES` / `SYSTEM_OWNED_RESOURCE_ALLOWLIST` / `REGISTERED_ACTION_CODES` / `f048_source_inventory.py` / `permission_schema.VALID_RESOURCE_TYPES` / `core/openfga/authorization_model.py`（后两者是死代码）。
  **测试**: T010 相关用例通过（`is_action_effective` 一组需 T017 脚本或测试库新建 store 后才全绿，见 T016）。
  **覆盖 AC**: AC-09
  **跨 Feature**: 改 F048 领域常量，**checksum 变化 → 存量环境启动即 `migration_required=True`、全站权限 503**（K9）；这条由 T017 的升级脚本承接，**不得单独部署本任务到存量环境**。
  **依赖**: T010

- [ ] **T012**: `[MVP-核心]` 资源生命周期策略 + 授权主体端点放行
  **文件**: `src/backend/bisheng/permission/domain/services/resource_lifecycle_policy.py`（`FIXED_CUSTOM_TYPES:14-26` 加 `"app"`）, `src/backend/bisheng/permission/api/endpoints/grant_subjects.py`（`GRANT_SUBJECT_RESOURCE_TYPES:28-40` 加 `"app"`）
  **逻辑**: D9 第 5、8 项。`FIXED_CUSTOM_TYPES` 让 `app` 起始即 CUSTOM 模式（`linsight_skill` 就在 :24）。`GRANT_SUBJECT_RESOURCE_TYPES` 是 baseline「12 处」之外的**活闸门**（坑 2）：5 个端点 5 处硬闸（`:89` users · `:113` user-groups · `:135` departments/children · `:152` departments/search · **`:168` departments/{dept_id}/path-tree**），漏改的现象是"授权弹窗能打开但一个主体都搜不到"、或"能搜到部门但点开树是空的"。
  **测试**: T010 的 `test_grant_subjects_five_endpoints_accept_app` 通过。
  **覆盖 AC**: AC-09
  **依赖**: T010

- [ ] **T013**: `[MVP-核心]` F048 adapter + registry 注册
  **文件**: `src/backend/bisheng/app_runtime/domain/services/f048_app_permission.py`（新，模板 = `tool/domain/services/f048_tool_permission.py:1-80+`）, `src/backend/bisheng/api/services/f048_permission_runtime.py`（`build_f048_resource_composition:128-196` 加 `adapters["app"]` + `registry.register("app", ...)`）
  **逻辑**: D9 第 6–7 项。Loader：`load_permission_record` 读 tenant / owner / state / update_time + `runtime.get_permission_version`；Adapter：`resolve_permission_target` → `VerifiedPermissionTarget.from_business_service`（状态白名单 / 租户匹配 / `owner_user_id > 0` 三判）、`authorize_created(mode="CUSTOM", protected=True)`、`project_delete`。**只依赖 `permission.domain.schemas` 与 `permission_action_service.PermissionActor`，不 import OpenFGA 基础设施**（RULE-9）。`build_f048_resource_composition` 是 **API 与 worker 两个组合根共用的注册点**——漏了则 celery / linsight 进程判权直接 `RuntimeError("F048 resource registry is not configured")`（memory 已踩过）。
  **测试**: T010 全部通过。
  **覆盖 AC**: AC-09, AC-11, AC-12
  **依赖**: T011, T012

- [ ] **T014**: `[MVP-核心]` 前端 Platform：`ResourceType` union 两处
  **文件**: `src/frontend/platform/src/controllers/API/permission.ts:6-16`, `src/frontend/platform/src/components/bs-comp/permission/types.ts:3-13`
  **逻辑**: 两处 union **重复定义**（D9），必须同时加 `'app'`。`PermissionDialog` 组件本身无 per-type 分支，union 加完即可用。
  **手动验证**: 构建 → 应用（Wave 3 落地后）卡片 ⚙️「管理权限」能打开弹窗并搜到用户 / 部门 / 用户组。
  **覆盖 AC**: AC-09
  **依赖**: T013

- [ ] **T015**: `[MVP-核心]` 前端 Client：`ResourceType` union 一处
  **文件**: `src/frontend/client/src/api/permission.ts:3-13`
  **逻辑**: 加 `'app'`。F056 的广场与授权弹窗消费它，本 Feature 一并加避免 F056 再改同一行。
  **手动验证**: `pnpm typecheck`（从 `src/frontend/`）通过；client 无运行时行为变化。
  **覆盖 AC**: AC-09
  **依赖**: T013

- [ ] **T016**: `[MVP-核心]` 存量环境生效脚本测试（dry-run / apply / verify 三态）
  **文件**: `src/backend/test/app_runtime/test_upgrade_authorization_model.py`（新）
  **逻辑**: 在一个干净 store 上模拟 M1 → M2：`test_dry_run_reports_plan_and_writes_nothing`（默认 dry-run，DB 与 store 零变化）；`test_apply_publishes_model_idempotently`（重跑不再多写一个 M2——**按 checksum 查重**，照 `_find_remote_model`（`permission/migration/f048_runtime_storage.py:463-479`）；⚠️ 该符号**不在** `core/openfga/discovery.py`）；`test_apply_writes_release_rows_in_one_sql_txn`（`authorization_model_release` 新 ACTIVE 行 + M1 置 RETIRED + CURRENT catalog release 指针 + `permission_action_resource_scope` 补 `app` 行，**四步在同一 SQL 事务**，中途异常整体回滚）；`test_step1_not_rollbackable_documented`（步骤 1 的 store 写入回滚不掉 → 回滚手段 = 指针指回 M1 + 撤 scope 行，断言脚本 `rollback` 子命令按此语义执行）；`test_preflight_blocks_on_live_heartbeats`（`list_runtime_heartbeats()` 非空且无 `--allow-live` → 拒绝）；`test_verify_asserts_read_side`（`current_catalog()` 通过 + `is_action_effective("app", 每个动作)` 为真）；`test_noop_when_checksum_matches`。
  **测试降级**: 无（连 test 中间件 OpenFGA + MySQL，CI 跑）。
  **覆盖 AC**: AC-13
  **依赖**: T011, T012, T013, T009

- [ ] **T017**: `[MVP-核心]` 存量生效脚本实现 + 升级说明
  **文件**: `src/backend/scripts/upgrade_f048_authorization_model.py`（新，惯例仿 `reconcile_f048_projection_operations.py` 的 `--apply` 默认 dry-run）, `docs/architecture/12-multi-tenant.md`（或新建 `docs/api/` 升级说明章节：`app` 资源类型生效步骤）
  **逻辑**: D9「114 存量生效脚本」四步：①（控制面 HTTP，**事务外**）按 canonical checksum 查重后发布含 `app` 的模型 M2；② `authorization_model_release` 新 ACTIVE 行（`model_version=f048-v2` / `predecessor_model_id=M1` / 重算 `required_relations_checksum`），M1 置 RETIRED；③ CURRENT `permission_catalog_release.required_authorization_model_release_id` 指向新行；④ 对 CURRENT release 的目标 action `INSERT permission_action_resource_scope(action_id, 'app')` 并重算 release checksum。子命令 `plan|apply|verify|rollback`。**不用 `force_write_model`**（坑 3：只写 OpenFGA 不写 SQL、不查重、生产禁用）。
  **回滚**: `rollback` 子命令 = ACTIVE 指针指回 M1 行 + 撤 scope 行 + 全进程重启；**M2 会永久留在 store**（无害孤儿：运行时只认 SQL pin 的那个）。
  **文档**: 升级说明必须写死三件事——**跑完必须全进程重启**（API / celery×3 / beat / linsight worker；心跳 15s 复核、TTL 45s，不重启的旧进程自行 fail-closed，坑 4）· **先发代码后加 `config.yaml` 键**（坑 23）· 存量环境**先 dry-run 再 apply**。
  **测试**: T016 全部通过。
  **覆盖 AC**: AC-13
  **依赖**: T016

### Wave 2 · `[MVP-核心]` runtime-manager 独立包（`src/runtime-manager/`）

- [ ] **T018**: `[MVP-核心]` runtime-manager 包工程骨架 + HMAC 服务端鉴权
  **文件**: `src/runtime-manager/pyproject.toml`（新）, `src/runtime-manager/runtime_manager/{__init__,main,config,auth}.py`（新，主入口 FastAPI 监听 `127.0.0.1:8091`）
  **逻辑**: D1：仓根独立包、**不在 `src/backend/bisheng/` 内**、不 import `bisheng`。`config.py` 读环境变量（`RTM_HMAC_SECRET` / `RTM_DATA_ROOT` / `RTM_NETWORK=bisheng-apps` / `RTM_RESERVE_MB` / `RTM_OVERCOMMIT_RATIO` / `RTM_BUILD_INDEX_URL`）；`auth.py` 照抄 `sso_sync/domain/services/hmac_auth.py:58-110` 的签名串（`METHOD\nPATH\nraw_body`、`X-Signature` 头、`hmac.compare_digest`、**空 secret fail-closed**）为 FastAPI 依赖。docker 客户端在 `runtime_manager/docker_backend.py` 单点封装（MVP 直连 `/var/run/docker.sock`，D2-A；换 socket-proxy 只改 base URL）。
  **依赖**: 无

- [ ] **T019**: `[MVP-核心]` runtime-manager 测试基础设施
  **文件**: `src/runtime-manager/tests/conftest.py`（新）, `src/runtime-manager/tests/fakes.py`（新）
  **逻辑**: `fake_docker`（可编程假客户端：记录 `create_container` 的完整 `HostConfig` / `Config`、模拟 `inspect` 返回 `State.Health` / `NetworkSettings.Networks[bisheng-apps].IPAddress`、模拟 `build` 的分阶段输出与失败）/ `rtm_client`（`TestClient` + 预置正确 HMAC 签名的请求辅助）/ `fake_meminfo`（可注入 `MemAvailable` / `MemTotal` / `nproc`）/ `tmp_data_root`。**所有需要真 docker 的用例统一打 `@pytest.mark.docker`**，默认跳过。
  **依赖**: T018

- [ ] **T020**: `[MVP-核心]` 容量准入测试
  **文件**: `src/runtime-manager/tests/test_admission.py`（新）
  **逻辑**: D11 双闸取与：`test_gate1_pass_gate2_fail_rejects`（可用内存充足但已承诺额度之和超 `total × 0.8` → 拒）/ `test_gate2_pass_gate1_fail_rejects`（额度够但 `MemAvailable - reserve_mb` 不足 → 拒；对应 114 上 available 曾 0.9G 的真实场景，K2）/ `test_both_pass_admits` / `test_purpose_build_uses_build_reserve_mb`（`purpose=build` 用 `build_reserve_mb`，失败阶段标 `build_admission`）→ AC-15 的失败阶段与 AC-19 同源 / `test_snapshot_fields_present`（返回 `mem_available_mb` / `committed_mb` / `total_mb` / `cpu`，供 AC-65 如实展示成因与 AC-23 运行环境状态复用）/ `test_cpu_gate_by_nproc_ratio` / `test_single_instance_admission_counts_running_only`。
  **覆盖 AC**: AC-19, AC-65
  **依赖**: T019

- [ ] **T021**: `[MVP-核心]` 容量准入实现
  **文件**: `src/runtime-manager/runtime_manager/admission.py`（新）, `src/runtime-manager/runtime_manager/api/intents.py`（新，`POST /v1/admission` 路由）
  **逻辑**: 闸① `MemAvailable - reserve_mb ≥ 本次所需`；闸② `已运行实例 mem limit 之和 + 本次 ≤ total × overcommit_ratio`，CPU 按 `nproc × ratio`；两闸取与；返回 `{admitted, reason, snapshot{...}}`。读 `/proc/meminfo` 与 `os.cpu_count()`，已承诺额度从 T029 的期望态存储取。
  **测试**: T020 全部通过。
  **覆盖 AC**: AC-19, AC-65
  **依赖**: T020

- [ ] **T022**: `[MVP-核心]` 构建（Dockerfile 模板渲染 + build 意图）测试
  **文件**: `src/runtime-manager/tests/test_build.py`（新）
  **逻辑**: `test_supported_runtimes_dynamic_from_templates`（`SUPPORTED_RUNTIMES` 由本部署实际存在的模板目录给出，MVP 期恰为 `["python3.11"]`）/ `test_unsupported_runtime_rejected_lists_supported`（`runtime="go1.22"` → 拒绝且错误体列出支持取值）→ AC-15 / `test_template_render_deterministic`（同输入渲染字节一致；模板含 **非 root 用户 + read-only 友好布局 + `BISHENG_APP_BASE_PATH` wrapper**，D5.2）/ `test_build_args_inject_index_url`（`PIP_INDEX_URL` / `PIP_TRUSTED_HOST` 来自配置）/ `test_build_memory_limited_and_admission_checked`（build 前过 `purpose=build` 闸，`--memory` 生效，K2）/ `test_build_failure_returns_stage_and_tail`（四阶段 `fetch_source` / `render_dockerfile` / `docker_build` / `probe`，失败返回 `{stage, message, tail}`）→ AC-15 / `test_image_tag_never_reused`（`bisheng-app/{slug}:{version_no}-{version_id[:8]}`）/ `test_image_retention_keeps_current_and_previous`（保留当前 + 上一个版本镜像，AC-21 旧实例宽限退休要用）。
  **测试降级**: 需 docker，CI 中间件阶段 + 114 手动验证——本任务的单测用 `fake_docker` 断言 build 参数与阶段映射，真镜像构建在 CI docker 阶段与 T075 上验证。
  **覆盖 AC**: AC-15
  **依赖**: T019, T021

- [ ] **T023**: `[MVP-核心]` 构建实现（模板矩阵 + builder）
  **文件**: `src/runtime-manager/runtime_manager/builder.py`（新）, `src/runtime-manager/runtime_manager/templates/python3.11/Dockerfile.j2`（新，含入口 wrapper）
  **逻辑**: D3：平台持有 Dockerfile 模板，开发者与 AI 不写 Dockerfile（PRD-1 DEV-04 明禁）。`POST /v1/intents/build` → 从 MinIO 拉 `code_object_key`（由 backend 传预签 URL，manager 不认平台凭据）→ 渲染模板 → `docker build`（限 `--memory`）→ 分阶段收集日志 → `GET /v1/builds/{build_id}` 查状态。安全基线（非 root、`no-new-privileges` 友好、无 shell 入口）**由模板统一落，开发者改不了**。`node20` / `static` 模板见 T092。
  **测试**: T022 全部通过。
  **覆盖 AC**: AC-15
  **依赖**: T022

- [ ] **T024**: `[MVP-核心]` 实例生命周期与容器规格测试
  **文件**: `src/runtime-manager/tests/test_lifecycle.py`（新）
  **逻辑**: 断言 `create_container` 下发参数：`test_tier_limits_applied`（`NanoCpus` / `Memory` 与档位一致，**限额在创建时固化、不做在线 update**，AC-64 的前提）→ AC-63 / `test_readonly_rootfs_and_tmpfs`（`ReadonlyRootfs=true`、`/tmp` tmpfs、`/data` 是唯一可写持久路径）→ AC-17 / `test_no_new_privileges`（`SecurityOpt` 含 `no-new-privileges`）→ AC-17 / `test_no_published_ports`（`PortBindings` 为空——绕过入口直连不可行）→ AC-33 / `test_env_injection_names`（`BISHENG_APP_DB_URL=sqlite:////data/app.db` / `BISHENG_APP_DB_PATH` / `BISHENG_APP_ID` / `BISHENG_APP_SLUG` / `BISHENG_APP_VERSION` / `BISHENG_PLATFORM_API_BASE` / **`PORT` 与 `BISHENG_APP_PORT`（design §4.2 ⑤ 两者并列，值均须等于 manifest `port`——断言两个名字都在、且取值一致；只断言 `PORT` 会让缺失的别名拖到 F053 `bisheng dev` 本地开发侧才暴露）** / `BISHENG_APP_BASE_PATH=/apps/{slug}`——**F053 `dev` 同名注入**，§4.2 ⑤）→ AC-17, AC-45 / `test_restart_policy_unless_stopped`（**不用 `always`**：停运是显式 `docker stop`，`unless-stopped` 语义正好是"显式停了就别自愈"）→ AC-20 / `test_healthcheck_params`（`interval=10s` / `timeout=3s` / `retries=3` / `start_period` 按档位 20–60s）/ `test_single_instance_per_app`（同一 app 重复 deploy 不产生第二个长驻实例；无实例数 / 并发入参）→ AC-24 / `test_volume_survives_stop_and_recreate`（stop / rm / run 后 `/data` 卷不动，数据完整）→ AC-39, AC-45 / `test_destroy_purge_volume_flag`（`purge_volume=false` 保卷、`true` 才删）→ AC-40。
  **测试降级**: 需 docker，CI 中间件阶段 + 114 手动验证——单测用 `fake_docker` 断言下发参数，`docker inspect` 的真实核验在 CI docker 阶段与 T075 步 1 上做。
  **覆盖 AC**: AC-17, AC-20, AC-24, AC-33, AC-39, AC-40, AC-45, AC-63
  **依赖**: T019, T021

- [ ] **T025**: `[MVP-核心]` 实例生命周期实现（deploy / stop / destroy）
  **文件**: `src/runtime-manager/runtime_manager/lifecycle.py`（新）
  **逻辑**: `POST /v1/intents/{deploy,stop,destroy}`。deploy = 过容量准入 → 以新版本镜像起**新容器**（容器名带 version 后缀，与旧容器并存）→ 交 T027 探活 → 更新路由条目 → 旧容器**宽限 30 秒**后 stop + rm（D4；30s ≫ app-proxy 的 3s 路由缓存，是 AC-21 不落 502 的真正理由，D5.1）。卷 = 宿主 `{data_root}/apps/{app_id}/db/` 挂容器 `/data`（K6：SQLite WAL 绑定单实例 + 本机卷，**绝不上网络存储**）。网络 = `bisheng-apps` bridge、**不 publish 端口**。
  **测试**: T024 全部通过。
  **覆盖 AC**: AC-17, AC-20, AC-24, AC-33, AC-39, AC-40, AC-45, AC-63
  **依赖**: T024, T023

- [ ] **T026**: `[MVP-核心]` 启动探活 + 路由表测试
  **文件**: `src/runtime-manager/tests/test_probe_and_route.py`（新）
  **逻辑**: `test_probe_ready_within_timeout` / `test_probe_timeout_returns_readable_reason`（未就绪 → `{ready:false, reason}`，供 F055 预检输出）→ AC-18 / `test_probe_standalone_image`（临时形态入参 `{image_ref, env, port, health}`，供 F055 预检与预览实例复用）→ AC-18 / `test_route_returns_bridge_ip_port`（`GET /v1/apps/{id}/route` → `{upstream: "http://<bridge IP>:<port>", version_id, generation}`——**宿主可达、外部不可达**，两形态同一机制；坑 30：114 上 app-proxy 是宿主 systemd 单元、解析不了容器名）→ AC-25, AC-33 / `test_route_generation_bumps_only_after_probe_pass`（新容器**探活通过后**才原子换路由并 `generation+1`）→ AC-21 / `test_route_404_when_no_instance`。
  **测试降级**: 需 docker，CI 中间件阶段 + 114 手动验证。
  **覆盖 AC**: AC-18, AC-21, AC-25, AC-33
  **依赖**: T019, T024

- [ ] **T027**: `[MVP-核心]` 探活与路由表实现
  **文件**: `src/runtime-manager/runtime_manager/probe.py`（新）, `src/runtime-manager/runtime_manager/routing.py`（新）
  **逻辑**: `POST /v1/intents/probe`（按 manifest `port` + `health.path` 轮询至就绪或超时）；`GET /v1/apps/{app_id}/route`（从 `docker inspect` 取 `NetworkSettings.Networks[bisheng-apps].IPAddress` + 端口，配合期望态存储的 `generation`）。**`app_instance.exec_ref` 是平台侧审计 / 排障引用、不是路由依据**——路由的唯一真相在 manager 的期望态存储（D5.1）。
  **测试**: T026 全部通过。
  **覆盖 AC**: AC-18, AC-21, AC-25, AC-33
  **依赖**: T026

- [ ] **T028**: `[MVP-核心]` reconcile 循环与期望态存储测试
  **文件**: `src/runtime-manager/tests/test_reconciler.py`（新）
  **逻辑**: `test_missing_container_recreated`（期望态有、实际无 → 拉起）/ `test_unhealthy_two_rounds_rebuilds`（`unhealthy` 连续 2 轮 → stop → rm → run，**卷不动**；坑 17：docker 单机 healthcheck 与 restart policy **无联动**，不补这一段第二类故障永不恢复）→ AC-20 / `test_orphan_container_reclaimed`（无期望态的 `bisheng-app-*` 容器被回收）/ `test_recovery_budget_within_5min`（用注入时钟断言分解预算：healthcheck 判 unhealthy ≤30s + reconcile 感知 ≤30s〔2×15s〕+ 重建拉起并探活 ≤90s = ≤2.5 分钟 < 5 分钟）→ AC-20 / `test_manager_restart_does_not_touch_running_containers`（重启期间不 stop 任何容器，容器存活依赖 dockerd 而非 manager）→ AC-22 / `test_startup_full_reconcile_from_labels`（期望态存储 = 本机状态文件 + 容器 label **双写**，状态文件丢失时从 label 恢复）→ AC-50 / `test_one_app_oom_does_not_affect_others`（模拟一个实例被 OOM kill，其它实例期望态不受影响、不被连带重建）→ AC-47。
  **测试降级**: 需 docker，CI 中间件阶段 + 114 手动验证——真 `docker kill` / 健康端点改 500 的自愈计时在 T075 步 6 与 T095 上做。
  **覆盖 AC**: AC-20, AC-22, AC-47, AC-50
  **依赖**: T019, T025

- [ ] **T029**: `[MVP-核心]` reconciler 与期望态存储实现
  **文件**: `src/runtime-manager/runtime_manager/reconciler.py`（新）, `src/runtime-manager/runtime_manager/desired_state.py`（新）
  **逻辑**: D4：**15 秒**一轮，比对期望态 vs `docker ps`，三类动作（缺失即拉起 / `unhealthy` 连续 2 轮即重建 / 孤儿即回收）；进程退出由 docker `restart unless-stopped` 内置退避兜住，manager 不参与。期望态存储 = 本机 JSON 状态文件 + 容器 label 双写（**label 是灾备真相**），进程启动时先做一次全量对齐（AC-50）。
  **测试**: T028 全部通过。
  **覆盖 AC**: AC-20, AC-22, AC-47, AC-50
  **依赖**: T028

- [ ] **T030**: `[MVP-核心]` 只读接口（status / logs / runtime-status）测试
  **文件**: `src/runtime-manager/tests/test_readonly_api.py`（新）
  **逻辑**: `test_status_shape`（`{instance_id, phase, health, current_version_id, started_at, restart_count, last_probe_at}`，`phase ∈ {pending, building, starting, running, unhealthy, stopped, failed}`——**形态无关，无 container / compose 字样**，INV-33）→ AC-23 / `test_logs_tail_since_keyword`（`GET /v1/apps/{id}/logs?tail=&since=&keyword=` 三参生效，来源 = docker json-file driver + `max-size=10m max-file=3` 轮转）→ AC-23, AC-55 / `test_logs_redact_known_injected_secrets`（对**平台注入的已知敏感值**做字面量替换为 `***`；**不做通用脱敏**——日志是应用自己打印的，通用脱敏是幻觉级承诺，密钥靠 F055 发布期扫描兜，D14）→ AC-55 / `test_runtime_status_shape`（`{backend_available, supported_runtimes[], capacity{...}, preflight[]}`）→ AC-23 / `test_backend_unavailable_reports_not_500`（dockerd 不可用 → `backend_available=false`，其余接口返 16121 语义）。
  **测试降级**: 需 docker，CI 中间件阶段 + 114 手动验证。
  **覆盖 AC**: AC-23, AC-55
  **依赖**: T019, T025

- [ ] **T031**: `[MVP-核心]` 只读接口实现
  **文件**: `src/runtime-manager/runtime_manager/api/readonly.py`（新）
  **逻辑**: `GET /v1/apps/{id}/status`、`GET /v1/apps/{id}/logs`、`GET /v1/runtime/status`。日志走 `docker logs`（D14-B：平台侧零采集器、零存储成本、形态无关）；保留期 = docker 轮转窗口（30MB / 应用），产品口径是"最近的运行日志"、不承诺永久留存。
  **测试**: T030 全部通过。
  **覆盖 AC**: AC-23, AC-55
  **依赖**: T030

### Wave 2 · `[MVP-核心]` backend 入口判定与内部授权端点（Test-First）

- [ ] **T032**: `[MVP-核心]` `entry_authz_service` 五步判定测试
  **文件**: `src/backend/test/app_runtime/test_entry_authz_service.py`（新）
  **逻辑**: 严格按 spec §3「入口判定顺序与信息泄漏口径」（D6）：`test_layer_not_deployed_short_circuits`（开关关 → 「未启用」，先于登录态判）→ AC-30 / `test_no_token_returns_login_handoff`（无 cookie → `decision=login`）→ AC-27 / `test_token_version_mismatch_denied` / `test_disabled_account_denied` / `test_disabled_tenant_denied`（三项复用 backend 中间件同一函数集 `http_middleware.py:60-73 / :124-142 / :263-279 / :325-349`——**本地解 JWT 会绕过它们**，K7）→ AC-26 / `test_draft_pending_deleted_and_nonexistent_return_same_page`（草稿 / 待上线 / 已删除 / 不存在**一视同仁**返回「不存在或未上线」，防信息泄漏）→ AC-29 / `test_not_visible_returns_forbidden_with_app_name_and_owner`（无权限页可带应用名与 owner——PRD 明示的引导信息）→ AC-28 / `test_stopped_returns_stopped_page_only_for_visible_users`（已停用页只对可见范围内用户呈现）→ AC-29 / `test_fga_unavailable_fail_closed_16146`（`PermissionServiceUnavailableError` / `PermissionBackendUnavailableError` → deny，**绝不放行**）→ AC-12 / `test_headers_material_complete`（十个头材料齐全，含 `X-BiSheng-Subject-Kind`；`Dept-Id` 取 `Department.dept_id` 业务键 `BS@xxx` **不是自增 id**）→ AC-31 / `test_chinese_name_percent_encoded_roundtrip`（用 `chinese_name_user` fixture：`User-Name` / `Dept-Name` / `Dept-Path` 三头 UTF-8 percent-encoding 往返——坑 9：HTTP 头是 latin-1，测试账号常是英文名故**极易漏测**）→ AC-31 / `test_obo_token_signed_with_dedicated_secret`（HS256、`aud="bisheng-app-obo"`、TTL 900s、**签名密钥独立于 `settings.jwt_secret`**——否则一个 OBO 令牌能被当平台会话 cookie 用；不持久化、不入库、不上界面）→ AC-34。
  **覆盖 AC**: AC-12, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-34
  **依赖**: T009, T013, T005

- [ ] **T033**: `[MVP-核心]` `entry_authz_service` 实现
  **文件**: `src/backend/bisheng/app_runtime/domain/services/entry_authz_service.py`（新）
  **逻辑**: 五步判定（D6）→ 返回 `{decision, headers{...}, obo_token, app_state, app_name, owner_name}`。可见范围判定用 **`check_business_action("app", app_id, actor, "use")`**（不用 `runtime.check_visible`——后者对"授了 editor 但没 use"的自定义模型更宽，会让口径与 PermissionDialog 显示不一致，D9）。部门信息经 `UserDepartmentDao.aget_user_primary_department`（`user_department` 表**无 tenant_id**、`department` 表有 → 需 `bypass_tenant_filter` 或显式上下文）。**不反代、不渲染页面**（那是 app-proxy 的活）。
  **测试**: T032 全部通过。
  **覆盖 AC**: AC-12, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-34
  **依赖**: T032

- [ ] **T034**: `[MVP-核心]` 内部授权端点 + 未部署引导页端点测试
  **文件**: `src/backend/test/app_runtime/test_internal_app_proxy_api.py`（新）
  **逻辑**: `test_hmac_required_and_constant_time`（无签名 / 错签名 → 401；`hmac.compare_digest`）/ `test_path_in_tenant_check_exempt`（端点在 `TENANT_CHECK_EXEMPT_PATHS`，handler 内 `bypass_tenant_filter`，否则跨租户访问自己被过滤掉）→ AC-26 / `test_response_contains_no_upstream_address`（**刻意不含目标实例地址**——上游解析是 app-proxy ↔ manager 的独立通道，两者缓存节奏不同，D5.1）/ `test_decision_matrix_end_to_end`（allow / login / forbidden / stopped / not_found / not_enabled 六态）→ AC-28, AC-29, AC-30 / `test_obo_returned_on_allow_only` → AC-34 / `test_unavailable_page_endpoint_returns_html_200`（`GET /api/v1/apps/_unavailable` 返回引导页 HTML，nginx `error_page` 回落用；**backend 提供一张静态 HTML 不违反 K1**）→ AC-30。
  **覆盖 AC**: AC-26, AC-28, AC-29, AC-30, AC-34
  **依赖**: T033

- [ ] **T035**: `[MVP-核心]` 内部授权端点实现
  **文件**: `src/backend/bisheng/app_runtime/api/endpoints/internal_app_proxy.py`（新）, `src/backend/bisheng/app_runtime/api/router.py`（新，并在 `bisheng/api/router.py` 挂载）
  **逻辑**: `POST /api/v1/internal/app-proxy/authorize`（HMAC 保护、加入 `TENANT_CHECK_EXEMPT_PATHS`、handler 内 `bypass_tenant_filter`）+ `GET /api/v1/apps/_unavailable`（引导页 HTML）。端点**不直接 import `database/models`**（RULE-3），一律经 domain service。
  **测试**: T034 全部通过。
  **覆盖 AC**: AC-26, AC-28, AC-29, AC-30, AC-34
  **依赖**: T034

### Wave 2 · `[MVP-核心]` app-proxy 独立包（`src/app-proxy/`）

- [ ] **T036**: `[MVP-核心]` app-proxy 包工程骨架
  **文件**: `src/app-proxy/pyproject.toml`（新）, `src/app-proxy/app_proxy/{__init__,main,config,clients}.py`（新，FastAPI 监听 `127.0.0.1:8090`）
  **逻辑**: D5-C：自研 Python 反代（**不套 oauth2-proxy**——CVE-2025-64484 正是头剥离不彻底，我们托管的是不可控的 Python 应用框架，这是设计前提级红线）。**不 import `bisheng` 包**（D6-B 的双份真相被否）。`clients.py` = 两个 HMAC 客户端（backend 授权端点 / manager 路由端点）+ 两把**独立**的 3 秒缓存。配置读环境变量（`APP_PROXY_BACKEND_BASE` / `APP_PROXY_MANAGER_BASE` / 两个 HMAC secret）。
  **依赖**: 无

- [ ] **T037**: `[MVP-核心]` app-proxy 测试基础设施
  **文件**: `src/app-proxy/tests/conftest.py`（新）, `src/app-proxy/tests/fakes.py`（新）
  **逻辑**: `fake_backend`（可编程 authorize 响应：六种 decision + 头材料 + OBO）/ `fake_manager`（可编程 route 响应，支持"先失败后成功"以测缓存作废重取）/ `echo_upstream`（一个把收到的 **全部请求头 + 路径 + query** 原样回显的 ASGI 应用，用于断言剥离 / 注入 / 前缀）/ `proxy_client`（`TestClient`，可设 `Sec-Fetch-Mode` / `Accept` / cookie）/ `frozen_clock`（缓存 TTL 用例）。
  **依赖**: T036

- [ ] **T038**: `[MVP-核心]` 头归一化剥离与注入测试
  **文件**: `src/app-proxy/tests/test_headers.py`（新）
  **逻辑**: `test_strip_all_x_bisheng_equivalence_class`（`X_BiSheng_User_Id` / `x-bisheng-user-id` / `X-BISHENG-USER-ID` / `x_bisheng_USER_name` 混合下划线连字符大小写**全部被丢弃**——按 `lower()` + `_`→`-` 归一后凡以 `x-bisheng-` 开头一律丢，**不是只丢精确的十个名字**；WSGI/ASGI 框架把 `X_BiSheng_User_Id` 与 `X-BiSheng-User-Id` 归一到同一个 `HTTP_X_BISHENG_USER_ID` 是常态，只按精确名剥离等于没剥离）→ AC-32 / `test_forged_header_has_no_effect_on_upstream`（客户端伪造 → 上游读到的仍是真实访问者）→ AC-32 / `test_inject_ten_headers`（十个 `X-BiSheng-*` 齐全）→ AC-31 / `test_forwarded_headers_rewritten_not_passthrough`（`X-Forwarded-Prefix` / `Proto` / `Host` **先丢客户端值再由 app-proxy 写入**——否则应用会用伪造 Host 生成外链，D5.2）→ AC-32 / `test_percent_encoded_chinese_values_pass_latin1`（三个含中文的头编码后可被 uvicorn/h11 正常发出，坑 9）→ AC-31。
  **覆盖 AC**: AC-31, AC-32
  **依赖**: T037

- [ ] **T039**: `[MVP-核心]` 头处理实现
  **文件**: `src/app-proxy/app_proxy/headers.py`（新）
  **逻辑**: `strip_platform_headers(headers)` + `build_injected_headers(material, slug, request_id)`（§4.2 ③ 十头 + 三个 `X-Forwarded-*`）。WS 升级请求走同一段代码（Wave 4 接线时复用，不另写一份）。
  **测试**: T038 全部通过。
  **覆盖 AC**: AC-31, AC-32
  **依赖**: T038

- [ ] **T040**: `[MVP-核心]` 判定接入 + 3s 缓存 + 四类兜底页测试
  **文件**: `src/app-proxy/tests/test_authz_and_fallback.py`（新）
  **逻辑**: `test_authorize_cached_3s_by_cookie_hash_and_slug`（同一 `(cookie 哈希, slug)` 3 秒内只问一次 backend；**与路由缓存互不干扰**）/ `test_visibility_revoke_effective_after_cache_expiry`（撤销后 ≤3s 生效，与 AC-10「自下一次请求起生效」口径相容）→ AC-10, AC-26 / `test_allow_forwards`（allow → 进入反代路径）→ AC-26 / `test_forbidden_page_content`（应用名 + owner + 无访问权限文案 + 引导联系 owner 或租户管理员 + 「返回广场」按钮；**本版无在线申请入口**）→ AC-28 / `test_stopped_page_content`（应用名 + 已停用提示 + 引导 + 返回广场）→ AC-29 / `test_not_found_page_for_draft_pending_deleted_and_unknown`（四种情形同一页，不落报错页）→ AC-29 / `test_not_enabled_guide_page_not_404_or_5xx`→ AC-30 / `test_backend_timeout_or_5xx_fail_closed`（内部端点超时 / 5xx → 拒绝而非放行）→ AC-12 / `test_recovering_static_page_on_upstream_unreachable`（MVP 期切换窗口 / 崩溃窗口表现为「应用恢复中」**静态版**，不落报错页；自动重试版见 T082）→ AC-36。
  **覆盖 AC**: AC-10, AC-12, AC-26, AC-28, AC-29, AC-30, AC-36
  **依赖**: T037, T039

- [ ] **T041**: `[MVP-核心]` 判定接入与兜底页实现
  **文件**: `src/app-proxy/app_proxy/authz.py`（新）, `src/app-proxy/app_proxy/pages.py`（新，四类兜底页 + 「应用恢复中」静态版 HTML 模板）
  **逻辑**: D7-A′：**app-proxy 自渲染**（URL 不变，扫码 / 收藏 / 刷新重试语义最稳；hash 零丢失；client 零改动）。被否的 B（302 → client gate 路由）有竞态型缺陷：`AuthContextProvider` 一挂载就拉 `/user/info`、401 拦截器的 `redirectToLogin()` 是**首次调用胜出的一次性守卫**，会把 gate 页 URL 写进 `LOGIN_PATHNAME`。页面用极简内联样式，不引外部资源。
  **测试**: T040 全部通过。
  **覆盖 AC**: AC-10, AC-12, AC-26, AC-28, AC-29, AC-30, AC-36
  **依赖**: T040

- [ ] **T042**: `[MVP-核心]` 登录交接页与非导航请求分流测试
  **文件**: `src/app-proxy/tests/test_login_handoff.py`（新）
  **逻辑**: `test_navigation_gets_inline_js_handoff`（`Sec-Fetch-Mode: navigate` → 返回内联 JS 页：写 `localStorage.LOGIN_PATHNAME = location.href`（**天然含 query + hash**）+ `LOGIN_PATHNAME_AT` 后 `location.replace('/admin')`）→ AC-27 / `test_query_and_hash_preserved`（`/apps/foo?a=1#b` 登录后回到含 `?a=1#b` 的原地址——**服务端 302 做不到**：hash 永不上送服务器，且 platform 登录页**只认这两个 localStorage key、不认任何 `?redirect=` query`**，坑 11）→ AC-27 / `test_key_names_and_ttl_match_platform_contract`（键名 / 10 分钟时效 / 同源校验必须与 `platform/utils/loginReturnTo.ts:35-70` 原样一致——这是跨 SPA 契约）→ AC-27 / `test_xhr_gets_json_and_real_status`（非导航请求返回 JSON + 真实 401/403/404/503，**不返回 HTML**，否则应用内 XHR 拿到一坨 HTML 会解析崩）/ `test_ws_upgrade_rejected_with_close_code`。
  **覆盖 AC**: AC-27
  **依赖**: T037, T041

- [ ] **T043**: `[MVP-核心]` 登录交接页与分流实现
  **文件**: `src/app-proxy/app_proxy/login_handoff.py`（新）
  **逻辑**: D7：分流判据 = `Sec-Fetch-Mode: navigate`（或 `Sec-Fetch-Dest: document`，回落 `Accept: text/html`）。交接页跳 `/admin`——未登录即 platform `LoginPage`；配了 SSO 时它自己跳 IdP，回来后 `App.tsx:154-160` 或 `login.tsx:168-172` 消费同一 key 回跳。
  **测试**: T042 全部通过。
  **覆盖 AC**: AC-27
  **依赖**: T042

- [ ] **T044**: `[MVP-核心]` 上游解析 + 前缀剥离 + HTTP 反代测试
  **文件**: `src/app-proxy/tests/test_proxy.py`（新）
  **逻辑**: `test_route_cached_3s_and_invalidated_on_conn_error`（连接失败〔`ECONNREFUSED` / 连接超时〕→ **立刻作废该条并重取一次**，再失败才渲染「应用恢复中」）→ AC-25, AC-36 / `test_prefix_stripped_three_forms`（`/apps/foo` → `/`、`/apps/foo/` → `/`、`/apps/foo/x?y=1` → `/x?y=1`；`X-Forwarded-Prefix` 恒为 `/apps/foo`）→ AC-25 / `test_relative_paths_work_through_entry`（上游生成的相对路径经入口可达）→ AC-25 / `test_entry_stable_across_version_switch`（`generation` 变化后同一 `/apps/{slug}` 仍可达，路由缓存过期后指向新实例；宽限 30s ≫ 3s 缓存 → 切换窗口内命中旧地址仍被旧容器正常服务、**不产生 502**）→ AC-21, AC-25 / `test_upstream_is_bridge_ip_not_published_port`（断言反代目标是 bridge IP，**不经任何宿主 published 端口**——绕过入口直连不可行）→ AC-33 / `test_streaming_and_large_body_passthrough`。
  **覆盖 AC**: AC-21, AC-25, AC-33, AC-36
  **依赖**: T037, T039, T041

- [ ] **T045**: `[MVP-核心]` 反代实现（路由解析 + 前缀剥离 + HTTP 转发）
  **文件**: `src/app-proxy/app_proxy/proxy.py`（新）, `src/app-proxy/app_proxy/routing.py`（新）
  **逻辑**: D5.1 + D5.2：问 manager `GET /v1/apps/{app_id}/route` 取 `upstream`（3s 缓存，与鉴权缓存**两把独立**）→ 剥 `/apps/{slug}` 前缀 → 重写 `X-Forwarded-Prefix/Proto/Host` → 注入十头 → httpx 流式转发。**WS 反代属 Wave 4**（T079/T080），MVP 期只反代 HTTP。
  **测试**: T044 全部通过。
  **覆盖 AC**: AC-21, AC-25, AC-33, AC-36
  **依赖**: T044

### Wave 3 · `[MVP-核心]` backend 领域服务与 API（Test-First）

- [ ] **T046**: `[MVP-核心]` `orchestrator_client` 测试 + backend 零编排依赖断言
  **文件**: `src/backend/test/app_runtime/test_orchestrator_client.py`（新）
  **逻辑**: `test_hmac_signature_matches_manager_contract`（签名串 `METHOD\nPATH\nraw_body`、`X-Signature` 头、空 secret fail-closed）/ `test_timeout_and_retry_then_16121`（manager 不可达 → `16121` 编排器不可用，不是 500）/ `test_admission_passthrough_snapshot`（容量快照原样透出供 AC-65 展示成因）→ AC-19 / `test_interface_semantics_are_form_agnostic`（门面方法名与入参**无 container / compose 字样**，`phase` 取值取自形态无关集合——INV-33，F059 只换 manager 内部后端）→ AC-14 / **`test_backend_has_zero_orchestration_dependency`**（扫描 `src/backend/bisheng/**/*.py` 无 `import docker|kubernetes|aiodocker`、无 `/var/run/docker.sock` 字面量；`src/backend/pyproject.toml` 依赖树不含 docker SDK——这是 AC-14「部署检查可核验」的自动化断言，与 T008 的 arch-guard RULE-10 双保险）→ AC-14。
  **覆盖 AC**: AC-14, AC-19
  **依赖**: T009, T005, T008

- [ ] **T047**: `[MVP-核心]` `orchestrator_client` 实现
  **文件**: `src/backend/bisheng/app_runtime/domain/services/orchestrator_client.py`（新）
  **逻辑**: httpx 薄客户端 + HMAC + 超时 + 重试，暴露 **10 个方法** `build / build_status / deploy / stop / destroy / probe / admission / status / logs / runtime_status`（§4.2 ①；**方法数与 T009 `fake_orchestrator` 的 stub 数必须一致**）。**绝不 import docker**；不含编排语义判断（意图式：backend 只下发期望态，manager 自 reconcile）。
  **测试**: T046 全部通过。
  **覆盖 AC**: AC-14, AC-19
  **依赖**: T046

- [ ] **T048**: `[MVP-核心]` 应用与版本落库测试（建应用 / slug / 只增不改 / 待运行版本）
  **文件**: `src/backend/test/app_runtime/test_app_state_service_registry.py`（新）
  **逻辑**: `test_create_app_persists_as_third_type_with_owner_and_state_draft`（应用标识 / 名称 / 描述 / 图标 / owner / 租户 / 应用态齐全；创建即调 `runtime.authorize_created`）→ AC-01, AC-11 / `test_slug_from_manifest_or_generated_from_name` → AC-08 / `test_slug_global_unique_across_tenants_rejects_16103`（与**任一租户**内既有标识冲突 → 拒绝首发并提示更换）→ AC-08 / `test_slug_immutable_name_mutable_and_duplicable`（名称可重可改、改名不影响标识与入口地址）→ AC-01, AC-08 / `test_owner_single_and_not_retroactive`（每应用有且只有一个 owner；归属人后续变更**不追溯改变**已建应用的 owner）→ AC-07 / `test_version_insert_only_no_update_method`（`AppVersionDao` 无通用 UPDATE；一条版本记录含版本号 / 类型 / 提交时间 / 终态标注 / 代码快照引用 / 能力声明 / 注入配置 / 资源档位——**四者同属一个快照**，任何写入方不得只改其一）→ AC-02 / `test_stage_version_writes_pending_without_state_change`（`stage_version` 写 `pending_version_id`、**不改应用态**——AC-04「已停运态可落新版本但不自动重新启用」的唯一落点）→ AC-04 / `test_resume_publish_pick_pending_then_current`（取版规则 `pending_version_id ?? current_version_id`；生效后 `pending` 置空、`current` 更新、该版本 `terminal_state='online'`）→ AC-04 / `test_rejected_or_withdrawn_never_writes_pending`（被驳回 / 撤回只标 `terminal_state`，故「迭代被驳回不改变已上线态」天然成立）→ AC-05 / `test_version_read_by_version_id_requires_app_scope`（按 `version_id` 起手的读写先取 `app` 行校验归属；跨租户直接读 → 拒——坑 31：`app_version` 无 `tenant_id`，登记进 `_TENANT_AWARE_MODEL_MODULES` 也**不会**被自动过滤，泄漏面是 `code_object_key` 即源码对象键）。
  **覆盖 AC**: AC-01, AC-02, AC-04, AC-05, AC-07, AC-08, AC-11
  **依赖**: T009, T013, T006

- [ ] **T049**: `[MVP-核心]` 应用与版本落库实现（`create_app` / `stage_version` / 取版规则）
  **文件**: `src/backend/bisheng/app_runtime/domain/services/app_state_service.py`（新，本任务只落建应用 / 待运行版本 / 取版三段）
  **逻辑**: `create_app(manifest, owner_user_id, tenant_id)`（slug 校验与生成 → 落 `app`（`state=draft`）→ `runtime.authorize_created(mode="CUSTOM", protected=True)`，AC-11「默认仅 owner 可见」由此成立）；`stage_version(app_id, version_id)`（写 `pending_version_id`、不改态；**F055 只调不直写**，决议-8）；`_pick_version(app)` = `pending_version_id ?? current_version_id`。版本记录的**写入时机**归 F055，本 Feature 只提供 DAO 与取版语义。
  **测试**: T048 全部通过。
  **覆盖 AC**: AC-01, AC-02, AC-04, AC-05, AC-07, AC-08, AC-11
  **依赖**: T048, T047

- [ ] **T050**: `[MVP-核心]` 五个状态动作测试（含前态矩阵 / 并发 / 审计 / 钩子）
  **文件**: `src/backend/test/app_runtime/test_app_state_actions.py`（新）
  **逻辑**: `test_transition_matrix_full`（五动作 × 五前态全矩阵；**已上线 → 已删除必须被拒**）→ AC-03 / `test_concurrent_actions_second_gets_16102`（带前态断言的单行 `UPDATE ... WHERE id=:id AND state IN (...)`，受影响行数 0 → `AppStateConflictError`(16102)，并发的「停运」与「上线终检」不互相覆盖、无需行锁）→ AC-03 / `test_publish_admission_fail_sets_pending_capacity_with_reason`（容量不足 → **不拉起半可用实例**、应用态置待上线并返回成因）→ AC-19, AC-65 / `test_publish_probe_fail_sets_pending_with_reason`（拉起 / 探活失败 → 待上线 + 成因「上线失败」）→ AC-65 / `test_manual_publish_from_pending_capacity`→ AC-65 / `test_stop_recycles_exec_body_only_assets_intact`（停运只回收执行体，代码快照 / 每应用数据库 / 附件真身恒在平台存储）→ AC-39, AC-40 / `test_resume_runs_admission_first_and_keeps_stopped_on_shortage`（重新启用叠加容量准入；不足则保持已停运并返回成因）→ AC-19, AC-41 / `test_resume_uses_pending_version`→ AC-04 / `test_stop_resume_allowed_for_owner_tenant_admin_and_superadmin_proxy`（超管经租户管理视图代行，**审计记超管本人**）→ AC-41 / `test_delete_blocked_when_online_16104`（前置状态闸「请先停运」）→ AC-42 / `test_delete_allowed_from_draft_pending_stopped`→ AC-42 / `test_delete_rejected_for_non_owner_16105`（含租户管理员与平台超管；**业务规则前置拦截**，不受权限运行时管理员短路影响）→ AC-44 / `test_delete_purges_assets_and_marks_deleted`→ AC-43 / `test_delete_triggers_on_app_deleted_hook`（注册假 hook，`DELETE` 后断言被同步调用）→ AC-43 / `test_hook_failure_does_not_rollback_delete`（hook 抛异常 → 删除仍成功且落审计 `app.delete_hook_failed`——删除是终态、资产已回收，回滚只会造出"态还在但资产没了"的僵尸）→ AC-43 / `test_no_path_deletes_assets_except_explicit_delete`（停运 / 实例崩溃 / 整层不部署三条路径均只回收执行体）→ AC-40 / `test_every_action_audited_with_version_and_reason`（五动作每次执行与结果均计审计，含版本号与成因）→ AC-65。
  **覆盖 AC**: AC-03, AC-04, AC-19, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-65
  **依赖**: T049, T047

- [ ] **T051**: `[MVP-核心]` 五个状态动作实现 + 删除事件钩子
  **文件**: `src/backend/bisheng/app_runtime/domain/services/app_state_service.py`（**增量新增**五动作方法，不改 T049 已落方法）, `src/backend/bisheng/app_runtime/domain/services/lifecycle_hooks.py`（新）
  **逻辑**: `publish / manual_publish / stop / resume / delete` —— **应用态的唯一写入方**（决议-8，F055 只调不直写）。每个动作：业务规则前置拦截（删除仅 owner；停运 / 重新启用 owner ∪ 租户管理员 ∪ 超管代行）→ 带前态断言的单行 UPDATE → 调 `orchestrator_client`（admission → deploy / stop / destroy）→ 审计（`AuditLogDao.ainsert_v2`，`app.*` 命名空间）。`lifecycle_hooks.py` = `register_app_deleted_hook(fn)` / `on_app_deleted(app_id, actor, tenant_id)`，**F055 在自己的组合根注册**（F054 **不 import F055**——依赖方向是 F055 → F054，反向 import 是依赖倒挂且撞 RULE-5）。
  **测试**: T050 全部通过。
  **覆盖 AC**: AC-03, AC-04, AC-19, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-65
  **依赖**: T050

- [ ] **T052**: `[MVP-核心]` `AppMetaService` 测试
  **文件**: `src/backend/test/app_runtime/test_app_meta_service.py`（新）
  **逻辑**: `test_update_meta_does_not_change_state`（改名称 / 描述 / 图标后应用态不变）→ AC-06 / `test_update_meta_creates_no_version_record`（`app_version` 行数不变——元信息不属能力声明）→ AC-06 / `test_update_meta_audited`（`app.meta_update`）→ AC-06 / `test_slug_not_updatable`（标识不在可改字段白名单）→ AC-08 / `test_same_implementation_used_by_pipeline`（F055「元信息随 deploy 更新」调同一方法，断言 Service 是唯一实现、不另写一份）→ AC-06。
  **覆盖 AC**: AC-06, AC-08
  **依赖**: T049

- [ ] **T053**: `[MVP-核心]` `AppMetaService` 实现
  **文件**: `src/backend/bisheng/app_runtime/domain/services/app_meta_service.py`（新）
  **逻辑**: `update_meta(app_id, patch, actor)` —— AC-06 的**唯一实现**（HTTP `PATCH /api/v1/apps/{app_id}` 与 F055 管线共用，§6.1 Outgoing 契约）。不碰应用态、不产生 `app_version` 行。
  **测试**: T052 全部通过。
  **覆盖 AC**: AC-06, AC-08
  **依赖**: T052

- [ ] **T054**: `[MVP-核心]` `AppQueryService` 读侧测试（详情 / 实例 / 日志 / 运行环境状态 / 版本列表）
  **文件**: `src/backend/test/app_runtime/test_app_query_service.py`（新）
  **逻辑**: `test_detail_returns_entry_url_from_backend_config`（入口 URL **由后端返回完整地址**，取部署配置的公网基址——前端**别用 `location.origin` 拼**，dev 下 origin 是 :3001 且 `/apps` 不在 vite 代理内）→ AC-25 / `test_instance_status_shape`→ AC-23 / `test_logs_scope_identical_across_three_entries`（详情页 tab / CLI `logs`〔F053〕/ MCP 日志工具〔F052〕**内容范围一致**，权限各按入口口径）→ AC-23, AC-55 / `test_logs_visible_to_owner_and_tenant_admin_only`（其他用户不可访问该 tab 与其接口；**业务规则前置拦截**，不能依赖权限运行时——管理员在那里会被短路放行）→ AC-55 / `test_logs_denied_returns_business_code_not_403`（返回 `16161` 业务码，**不返回 HTTP 403/404**——坑 25：platform 拦截器对 GET 会整页跳 `/403`）→ AC-55 / `test_logs_no_platform_side_logs_and_has_empty_state`→ AC-55 / `test_runtime_status_superadmin_only`（两形态同一接口）→ AC-23 / `test_version_list_readonly_source_not_flow_version`（托管应用版本下拉的数据源是 `app_version` 而非 `FlowVersionDao`；只读、不提供切换与回滚——坑 13：`add_extra_field` 的 `version_list` 对 app 恒空，直接复用 `CardSelectVersion` 会去改**工作流**的当前版本）→ AC-52 / `test_owner_list_filter_and_tenant_admin_scope`（owner 看自己 owner 的、租户管理员看本租户全部）→ AC-57。
  **覆盖 AC**: AC-23, AC-25, AC-52, AC-55, AC-57
  **依赖**: T047, T049

- [ ] **T055**: `[MVP-核心]` `AppQueryService` 实现
  **文件**: `src/backend/bisheng/app_runtime/domain/services/app_query_service.py`（新）
  **逻辑**: 详情（含 `entry_url`）/ 实例状态 / 日志 / 运行环境状态 / 版本列表的读侧，三入口权限口径分派（详情页：owner ∪ 本租户租户管理员；MCP / CLI：仅密钥归属人 owner 的应用）。**不写库**。
  **测试**: T054 全部通过。
  **覆盖 AC**: AC-23, AC-25, AC-52, AC-55, AC-57
  **依赖**: T054

- [ ] **T056**: `[MVP-核心]` 状态动作 API + 读 API 端点集成测试
  **文件**: `src/backend/test/app_runtime/test_apps_api.py`（新）
  **逻辑**: TestClient 覆盖 `POST /api/v1/apps/{id}/actions/{publish,manual-publish,stop,resume}` · `DELETE /api/v1/apps/{id}` · `PATCH /api/v1/apps/{id}` · `GET /api/v1/apps/{id}` · `GET /api/v1/apps/{id}/instance` · `GET /api/v1/apps/{id}/logs` · **`GET /api/v1/apps/{app_id}/versions`（版本列表，只读）** · `GET /api/v1/apps/runtime-status`：`test_versions_endpoint_path_and_shape`（**路径与响应形状在此定死**：返回 `[{version_id, version_no, kind, terminal_state, submitted_at, is_current, is_pending}]`，按 `version_no` 倒序；数据源是 `app_version` 而非 `FlowVersionDao`，**不提供任何切换 / 回滚写口**，坑 13）→ AC-52 / `test_versions_endpoint_non_owner_gets_business_code_not_403`（坑 25）→ AC-52 / `test_stop_resume_happy_path_and_audit`→ AC-41 / `test_delete_online_returns_16104`→ AC-42 / `test_delete_non_owner_returns_16105`→ AC-44 / `test_delete_owner_success_and_hook_called`→ AC-43 / `test_publish_capacity_shortage_returns_pending_with_reason`→ AC-65 / `test_meta_patch_no_version_no_state_change`→ AC-06 / `test_logs_non_owner_gets_16161_not_403`→ AC-55 / `test_cross_tenant_app_id_returns_16101`（租户自动过滤 + 显式校验双保险）/ `test_all_endpoints_return_unified_response_model`。
  **覆盖 AC**: AC-06, AC-41, AC-42, AC-43, AC-44, AC-52, AC-55, AC-65
  **依赖**: T051, T053, T055

- [ ] **T057**: `[MVP-核心]` 状态动作 API + 读 API 端点实现
  **文件**: `src/backend/bisheng/app_runtime/api/endpoints/apps.py`（新）, `src/backend/bisheng/app_runtime/api/router.py`（挂载，已在 T035 建）
  **逻辑**: FastAPI 端点，`UserPayload` 认证注入，委托 Service，`UnifiedResponseModel` 包装（§4.2 ②）。端点层**不直接 import `database/models`**（RULE-3）。**端点清单含 `GET /api/v1/apps/{app_id}/versions`**（只读版本列表，委托 T055 的 `AppQueryService`）——**design §4.2 ② 的读接口清单遗漏了这一条，落地时同批回写 design**；T062 的「版本列表」HTTP 封装、T064 的卡片只读版本下拉、T066 的版本 tab **三处共用这一个路径与形状**，不得各自发明。
  **测试**: T056 全部通过。
  **覆盖 AC**: AC-06, AC-41, AC-42, AC-43, AC-44, AC-52, AC-55, AC-65
  **依赖**: T056

- [ ] **T058**: `[MVP-核心]` 构建页列表第三类型端到端测试（UNION + 6 组硬闸 + 租户隔离）
  **文件**: `src/backend/test/app_runtime/test_build_list_third_type.py`（新）
  **逻辑**: `test_third_type_end_to_end_non_empty`（`flow_type=35` 走完 `SUPPORTED_APP_TYPES` → UNION → `_application_action_map` 分桶 → `add_extra_field`，断言"列表非空**且带 `write` / `tags`**"——坑 28：只加 UNION 会在这里挂，且失败现象是**空列表不报错**，极易被当成"权限没配好"排查半天）→ AC-51 / `test_type_filter_returns_only_hosted_apps`→ AC-51 / `test_app_state_filter_covers_five_values`（应用态五值走**新参数 `app_state`**；`status` 列只投影 2/1 供既有开关复用——坑 8：`getAppsApi` 只放行 `status ∈ {1,2}`）→ AC-51 / `test_tenant_isolation_in_union_third_branch`（子租户账号列不出别租户应用——**UNION 子查询的自动过滤失效**，第三支必须手工 `build_tenant_filter_clause(App.tenant_id)`，今天**没有第三支范例可抄**，坑 21 / K5 ③）→ AC-51 / `test_owner_scope_and_tenant_admin_scope`→ AC-57 / `test_cursor_pagination_stable_across_three_branches`（keyset `(update_time, id)` 三支归并稳定）→ AC-51 / `test_tag_filter_and_tag_link_for_app`（标签预过滤 3 处 + `check_tag_link_permission` 认 `HOSTED_APP`；不改这组 = "筛选框在、结果恒空"，打标还会直接 404）→ AC-51 / `test_permission_bucket_populated`（`_application_action_map` 的 `grouped` 有 `"app"` 桶；不加则"有卡片但什么都点不了"）→ AC-51。
  **覆盖 AC**: AC-51, AC-57
  **依赖**: T009, T013, T049

- [ ] **T059**: `[MVP-核心]` UNION 第三支 + `FlowType` / `ResourceTypeEnum` 枚举
  **文件**: `src/backend/bisheng/database/models/flow.py`（`FlowType:33-39` 加 `HOSTED_APP = 35`；`_build_apps_subquery:660-702` 加第三支 SELECT）, `src/backend/bisheng/database/models/group_resource.py`（`ResourceTypeEnum:14-22` 加 `HOSTED_APP = 10`）
  **逻辑**: D8：第三支把 `app` 表投影成同一列集 `(id, name, description, flow_type, logo, user_id, status, create_time, update_time)`——`flow_type` 投常量 35（避开已占 5/10/15/20/25/30）、`user_id` 投 `owner_user_id`、`status` 投 **2（已上线）/ 1（其余四态）**；租户条款**手工** `build_tenant_filter_clause(App.tenant_id)`，照 `flow_clause:695` / `assistant_clause:698` 两支自己加。`flow.py` import `database/models/app`（**同目录，不触 RULE-2**；这正是三张表落 `database/models/` 的原因，坑 27）。
  **跨 Feature（副作用登记，必读）**: `_build_apps_subquery:660` 有 **4 个调用方**，第三支会同时改变另两条与构建页无关的路径——`get_all_app_by_time_range_sync:810`（→ `api/services/workflow.py:1039` 的 `get_all_app_by_time_range`，按时间范围取应用）与 `get_first_app:849`（→ `src/backend/scripts/sync_increment_table.py:53`，**商业版增量同步**）。本任务须**显式确认**这两条路径接纳托管应用是期望行为（而非"顺带流进去"）：增量同步侧确认托管应用行（`flow_type=35`、`status` 投 2/1）不会让同步脚本按 `Flow` 语义去取不存在的字段；时间范围侧确认返回结构一致。
  **测试**: T058 相关用例通过；**并跑既有回归 `src/backend/test/workflow/test_flow_dao_tenant_isolation.py`**（覆盖 `get_all_apps` / `aget_all_apps` / `get_all_app_by_time_range_sync` / `get_first_app` 四个方法的租户隔离）——**必须扩一个第三支用例**：托管应用行经这四个方法均不跨租户泄漏（坑 21 / K5 ③：UNION 子查询自动过滤失效，第三支的手工 `build_tenant_filter_clause` 一处写漏，四个方法一起漏）。
  **覆盖 AC**: AC-51, AC-57
  **依赖**: T058

- [ ] **T060**: `[MVP-核心]` 后端 6 组硬闸（`workflow.py` + 标签体系）
  **文件**: `src/backend/bisheng/api/services/workflow.py`（`SUPPORTED_APP_TYPES:76` 加 35；`_FLOW_TYPE_TO_RESOURCE_TYPE:77-80` 加 `35 → "app"`；`_application_action_map:146-179` 的 `grouped:151-154` 加 `"app": []` 桶；tag 预过滤 `:203` / `:598` / `:998-999` 加 `HOSTED_APP`；新增 `app_state` 查询参数）, `src/backend/bisheng/api/services/tag.py`（`check_tag_link_permission:75-103` 认 `HOSTED_APP`）
  **逻辑**: D8「后端 6 组硬闸」。`filter_supported_apps:83-84` 是公共闸、被 6 处调用，**加 1 即全放行、无需逐处改**（这组里唯一的好消息）。`add_extra_field:87-127` 的 `user_name` / `tags` / `logo` / `write` 四项对 app 直接复用，**`version_list` 不复用**（改由 T055 的只读版本源提供，坑 13）。
  **跨 Feature**: `get_online_flows_page:514` 走同一道 `SUPPORTED_APP_TYPES` 闸 → **F056 广场直接受益，不要重复改**。
  **测试**: T058 全部通过。
  **覆盖 AC**: AC-51, AC-57
  **依赖**: T058, T059

- [ ] **T061**: `[MVP-核心]` 工场运行时层开关组合测试（未部署回归 + 两开关正交）
  **文件**: `src/backend/test/app_runtime/test_runtime_layer_switch.py`（新）
  **逻辑**: `test_env_exposes_app_runtime_enabled_anonymously`（`GET /api/v1/env` 匿名可读该字段，两个 SPA 据此渲染）→ AC-62 / `test_switch_off_hides_hosted_apps_from_list`（构建页列表不出现托管应用类型与卡片）→ AC-58 / `test_switch_off_no_new_menu_or_permission_point`（升级前后角色配置面的菜单项与权限点数量不变——**零新增菜单 / 权限点**；详情页走 `build/apps/:appId` 子路由 + `permission: 'build'`）→ AC-58 / `test_no_ui_create_entry_in_any_state`（本册任何形态下均不提供托管应用的界面新建入口，唯一创建路径 = CLI 首发）→ AC-58 / `test_switch_off_no_resident_process_or_beat_task`（无新增常驻进程与定时任务）→ AC-59 / `test_platform_regression_unchanged_when_off`（既有列表 / 权限 / 审计接口行为零变化）→ AC-59 / `test_two_switches_orthogonal_four_combinations_boot`（`app_runtime.enabled` × `open_platform.enabled` 四种组合下平台均可正常启动）→ AC-61 / `test_unknown_yaml_key_rejects_boot`（回归坑 23：先加 `config.yaml` 键后发代码 → `KeyError` 拒启，故升级顺序必须是先代码后键）→ AC-60。
  **覆盖 AC**: AC-58, AC-59, AC-60, AC-61, AC-62
  **依赖**: T005, T057, T060

### Wave 3 · `[MVP-核心]` 前端 Platform（手动验证）

- [ ] **T062**: `[MVP-核心]` Platform：API 封装 + `appRuntimeEnabled` 读取
  **文件**: `src/frontend/platform/src/controllers/API/hostedApp.ts`（新）, `src/frontend/platform/src/contexts/locationContext.tsx:75-92` + `src/frontend/platform/src/types/api/app.ts`（`appConfig.appRuntimeEnabled`）
  **逻辑**: 全部 HTTP 封装（详情 / 实例 / 日志 / 运行环境状态 / 五个状态动作 / 元信息 PATCH / **版本列表 `GET /api/v1/apps/{app_id}/versions`**——路径与响应形状由 T056 定死、T057 实现，T064 的卡片只读版本下拉与 T066 的版本 tab 共用本封装，**三处不得各自发明**）；**不 import axios**（C7），用仓内既有 request 模块；日志等只读 GET 传 `silent: true` 或依赖业务码，**不得触发 403/404 整页跳转**（坑 25）。`appRuntimeEnabled` 从 `/api/v1/env` 读，供构建页 / 详情页 / 引导页渲染。
  **手动验证**: 关闭开关时 `appConfig.appRuntimeEnabled === false`；`pnpm typecheck` 通过。
  **覆盖 AC**: AC-62
  **依赖**: T057, T061

- [ ] **T063**: `[MVP-核心]` Platform：构建页第三类型（筛选 / 分派 / 扩展点）
  **文件**（**已按代码事实订正——`pages/BuildPage/components/` 目录不存在，不得新建同名组件文件，否则会造出与真身并存的死组件**）: `src/frontend/platform/src/pages/BuildPage/apps.tsx`（`SelectAppStatus` 就地定义在 **`:37`**、`SelectType` 在 **`:57`**，二者均为本文件内的 `export const`，"就地扩展" = 改这两个函数本身）, `src/frontend/platform/src/controllers/API/flow.ts`（**`getAppsApi` 在 `:177`，不在 `apps.tsx`**：`type` 联合类型、类型→数值 map、新增 `app_state` 查询参数都改在这里）, `src/frontend/platform/src/types/app.ts`（**`AppNumType` 在 `:9-12` 只有 `FLOW=10` / `ASSISTANT=5`**，必须新增 `HOSTED_APP = 35`，并同步 `AppType` 枚举与 `AppTypeToNum` / `AppNumToType` 两张 map；不加则角标 / 头像 / 类型 map **全部落默认分支**，现象是"卡片出来了但类型显示成工作流"）, `src/frontend/platform/src/components/bs-comp/cardComponent/avatar.tsx`（**共享组件** `AppAvator:15`，图标 map 按 `AppNumType` 分支，需加第三类型图标）
  **逻辑**: D13 的 14 处扩展点中属列表骨架的部分：`SelectType`（`apps.tsx:57`）加「托管应用」并加**条件 prop**（坑 12：该组件被模板页 `appTemps.tsx:82` 复用，直接加会让模板页出现一个点了 404 的类型；且只在 `appRuntimeEnabled` 时给）· `SelectAppStatus`（`apps.tsx:37`）覆盖应用态五值（含「待上线（资源不足）」）→ 走新参数 `app_state` · **`types/app.ts` 的 `AppNumType` 加 `HOSTED_APP=35` 并同步 `AppTypeToNum` / `AppNumToType`** · `TypeNames` / `typeCnNames`（角标）· `APP_ACTIONS` 第三桶 `useResourceActions('app', …)` · `handleOpenPermission` 的 `typeMap` 补 `35 → 'app'`（坑 7：默认回落 `'workflow'` → 弹窗对着 workflow 类型开、registry 校验 record 类型不符报 19003，现象是"弹窗打开但一片红"）· `handleSetting` → 详情页 · **`controllers/API/flow.ts:177` 的 `getAppsApi`** 的 `type` 联合类型与 map · `LabelSelect` 的 `ResourceTypeEnum` 映射 · **`cardComponent/avatar.tsx` 的 `AppAvator`** 图标。**复用既有搜索与标签筛选**。
  **跨 Feature**: `components/bs-comp/cardComponent/avatar.tsx` 是 workflow / 助手 / 模板页共用的**共享头像组件**（与 T065 的 `cardComponent/index.tsx` 同族）——**只加第三个分支，既有两类型的图标与尺寸逐像素不变**；回归验证随 T065 一并由 F056 承接 GOV-01 验收 6。`types/app.ts` 的 `AppNumType` 同为全平台共享枚举，**只增值、不改既有值**（`FLOW=10` / `ASSISTANT=5` 与 `FlowType` 数值口径一一对应，改动会连带后端 UNION 分支错位）。
  **手动验证**: 构建 → 应用：类型筛选出现「托管应用」（关开关后消失）；选中后只列托管应用；状态筛选五值可选并生效；搜索 / 标签筛选正常；模板管理页的类型下拉**不含**托管应用；**托管应用卡片头像显示第三类型图标而非默认回落图标**；工作流 / 助手卡片的头像、角标、类型文案零变化。
  **覆盖 AC**: AC-51, AC-57, AC-58
  **依赖**: T062, T060

- [ ] **T064**: `[MVP-核心]` Platform：`HostedAppCard` + `useHostedAppActions`
  **文件**: `src/frontend/platform/src/pages/BuildPage/HostedAppCard.tsx`（新）, `src/frontend/platform/src/pages/BuildPage/useHostedAppActions.ts`（新）
  **逻辑**: 卡片装配（图标 / 名称 / 描述 / 创建用户 / 类型角标 / 应用态徽标 / **只读**版本下拉〔不复用会去改工作流当前版本的 `CardSelectVersion`，坑 13〕/ 上下线开关）+ 三动作 hook（停运 / 重新启用 / 删除 + 二次确认文案：停运明示"入口与广场将呈已停用"；删除**不要求输入应用名**、文案明示将一并删除**代码、对话历史与应用生产数据**）。⚙️ 菜单**只出现「管理权限」与「删除」**（`onAddTemp=undefined` / `showCopy=false` 即隐藏"创建模板 / 复制"，**零改共享组件**）；删除项仅 owner 可见、已上线时置灰提示「请先停运」。**卡片与详情页共用同一 hook**，避免两份文案漂移。`apps.tsx` 已 426 行 → 抽出本文件是 ≤600 行硬规逼出来的。
  **手动验证**: 卡片字段齐全；⚙️ 只有两项；已上线时删除置灰并有 Tooltip；停运 → 二次确认 → 徽标变已停运、开关翻转；重新启用恢复；版本下拉只读（点击不触发任何写请求，Network 面板确认）。
  **覆盖 AC**: AC-42, AC-52, AC-53
  **依赖**: T063, T065

- [ ] **T065**: `[MVP-核心]` Platform：`CardComponent` 两个可选 prop（共享组件）
  **文件**: `src/frontend/platform/src/components/bs-comp/cardComponent/index.tsx`
  **逻辑**: 新增 `deleteDisabledHint?: string`（`DropdownMenuItem disabled` + Tooltip）与 `switchTexts?: {on: string; off: string}`（上下线 Switch 文案由 `t('skills.online/offline')` 改为可覆盖，表达"停运 / 重新启用"）。坑 6：现状是 `!checked && onDelete` **整项不渲染**（`:239-244`），照现状实现 AC-42 会变成"看不见"而非"置灰"。**两个 prop 均可选、缺省行为与今天逐像素一致**。
  **跨 Feature**: workflow / assistant 共用该组件，回归验证由 F056 承接 GOV-01 验收 6。
  **手动验证**: 工作流 / 助手卡片行为无任何变化（⚙️ 菜单、上下线文案、删除项显隐）；托管应用卡片已上线时删除项置灰 + Tooltip。
  **覆盖 AC**: AC-42, AC-53
  **依赖**: T062

- [ ] **T066**: `[MVP-核心]` Platform：应用详情页壳 + 路由
  **文件**: `src/frontend/platform/src/pages/BuildPage/hostedApp/{index.tsx,Header.tsx,types.ts,hooks/useHostedApp.ts}`（新）, `src/frontend/platform/src/routes/index.tsx`（`MainLayout` 子路由 `build/apps/:appId`，`permission: 'build'`）
  **逻辑**: D13-B：**零新增菜单 / 权限点**（AC-58）。四 tab（发布 · 数据 · 运行日志 · 版本）用 `bs-ui/tabs`（范式 `pages/SystemPage/index.tsx:54-118`）；**无左侧对话区、无管家**；数据 tab 与版本 tab 本期只出壳与空态（数据 tab 内容 → T088；版本 tab 列表 → F055）。副作用：顶部「应用 / 工具 / 工作台配置」子 tab 在详情页消失（`layout/HeaderMenu.tsx:24` 只在精确等于三个路径时渲染），与知识库详情页同行为、可接受。react-query **禁用**（lint 冻结），用 `useState + useEffect`。
  **手动验证**: 点卡片进入 `/build/apps/{id}`；四 tab 可切换；刷新页面不丢 tab；非 owner 且非租户管理员访问 → 看到无权限提示**而不是被甩到 `/403` 页**。
  **覆盖 AC**: AC-54, AC-58
  **依赖**: T062

- [ ] **T067**: `[MVP-核心]` Platform：发布 tab 最小形态
  **文件**: `src/frontend/platform/src/pages/BuildPage/hostedApp/tabs/PublishTab.tsx`（新）
  **逻辑**: 决议-6：本 Feature 只交付**应用态徽标 + 入口链接（可复制）+ 运营动作（停运 / 重新启用 / 手动上线）**；入口 URL **用后端返回的完整地址**，不用 `location.origin` 拼（dev 下 origin 是 :3001 且 `/apps` 不在 vite 代理内）。**用 slot / children 给 F055（管线 / 能力 / 档位 / 危险操作区）与 F056（可见范围区）留位**，避免三个 Feature 改同一文件冲突。二维码属 Wave 5（T091）。运营动作复用 T064 的 `useHostedAppActions`（同一份确认文案）。
  **手动验证**: 徽标与应用态一致；复制入口链接后粘贴可直达 `/apps/{slug}`；停运 / 重新启用 / 手动上线三按钮按应用态正确启用禁用；F055 / F056 的 slot 位为空时布局不塌。
  **覆盖 AC**: AC-41, AC-54, AC-65
  **依赖**: T066, T064

- [ ] **T068**: `[MVP-核心]` Platform：运行日志 tab
  **文件**: `src/frontend/platform/src/pages/BuildPage/hostedApp/tabs/LogsTab.tsx`（新）
  **逻辑**: platform 无先例的自建件（E3 §1.8）：筛选栏（`DatePicker`×2 时间范围 + 关键字 + 刷新按钮）+ `<pre>` 等宽块 + 空态说明 + `setInterval` 轮询（无 `usePolling` hook）。只读；只呈现应用运行输出与错误信息（含错误栈），**不含平台侧日志**；权限失败时显示"无权查看"提示而非跳 403（业务码 `16161`，坑 25）。
  **手动验证**: `curl` 触发应用打印几条 → tab 内可见；关键字筛选生效；时间范围生效；空应用显示空态；非 owner 账号看到提示而非被甩出页面。
  **覆盖 AC**: AC-55
  **依赖**: T066

- [ ] **T069**: `[MVP-核心]` Platform：`apps/*` 未部署引导页路由
  **文件**: `src/frontend/platform/src/routes/index.tsx`（public + private **两张路由表都加** `apps/*`）, `src/frontend/platform/src/pages/AppRuntimeGuide/index.tsx`（新）
  **逻辑**: D5「未部署引导页两层」之第一层：整层没装时 nginx 里根本没有 `location /apps/`，`/apps/x` 落 `location /` → platform SPA（坑 15：现状已登录 `* → /404`、未登录 → `LoginPage`，AC-30 在默认路径上不成立）。本路由渲染「本环境未启用应用工场」引导页（引导联系平台超管），读匿名 `/api/v1/env.app_runtime_enabled` 判定。**零 nginx 变更**；已部署环境该路由永远命中不到（被更长前缀截走）。
  **手动验证**: 关开关 + 移除 nginx location 后访问 `/apps/foo` → 引导页（**不是 404 / 5xx**，登录与未登录两种状态都试）。
  **覆盖 AC**: AC-30
  **依赖**: T062

- [ ] **T070**: `[MVP-核心]` Platform：三语 i18n + `apps.tsx` 存量中文抽键
  **文件**: `src/frontend/platform/public/locales/{zh-Hans,en,ja}/*.json`（本 Feature 新增 key）, `src/frontend/platform/src/pages/BuildPage/apps.tsx`（存量硬编码中文抽键，如 `:269 '无编辑权限'`）
  **逻辑**: 新增 key 三语同 PR（CI `pnpm check-i18n` 校验 key 平价）；按"谁触碰谁还债"把 `apps.tsx` 的 frozen 中文抽到 i18n，随后跑 `pnpm lint:prune`、若该文件已过 strict 则删其 `// @ts-strict-ignore` 头。错误码文案**只在** `packages/locales` 的 `api_errors` 域（T004 已落），此处不重复。
  **手动验证**: 三语切换下构建页与详情页无中文残留；`pnpm lint` + `pnpm typecheck`（从 `src/frontend/`）通过。
  **覆盖 AC**: AC-51
  **依赖**: T063, T064, T066, T067, T068

### Wave 3 · `[MVP-核心]` 前端 Client（手动验证）

- [ ] **T071**: `[MVP-核心]` Client：读取工场运行时层开关
  **文件**: `src/frontend/client/src/@types/chat.ts:102`（`BishengConfig.app_runtime_enabled`）, `src/frontend/client/src/hooks/useAppRuntimeEnabled.ts`（新）
  **逻辑**: 用 **react-query v4** 拉 `/api/v1/env`（**不得 import recoil**——lint 冻结）。F056 的广场据此决定是否渲染托管应用；本 Feature 只交付读取能力与类型，不改广场。
  **手动验证**: 开关关 → hook 返回 false；`pnpm typecheck` 通过；client 现有页面行为零变化。
  **覆盖 AC**: AC-62
  **依赖**: T005

### Wave 3 · `[MVP-核心]` 114 部署增量与联调

- [ ] **T072**: `[MVP-核心]` systemd 两单元 + `deploy.sh` / `smoke.sh` 增量
  **文件**: `features/v3.0.0/054-app-domain-runtime/deploy/bisheng-runtime-manager.service`（新，模板）, `features/v3.0.0/054-app-domain-runtime/deploy/bisheng-app-proxy.service`（新，模板）
  **逻辑**: §4.2 ⑧：`bisheng-runtime-manager.service`（`127.0.0.1:8091`、`After=docker.service`、以 root 或 docker 组运行）· `bisheng-app-proxy.service`（`127.0.0.1:8090`、`After=bisheng-api.service`、**不需要 docker 权限**）；两者追加进 `bisheng.target` 的 `Wants=` 与 `deploy.sh` 的 `SERVICES=`、`smoke.sh` 增两条探针。⚠️ **这些文件不在产品仓**——真身在独立仓 `~/Projects/bisheng-ops/`（K10），本任务在 feature 目录交付模板 + 落库说明，实际写入由 T075 在 114 上执行。⚠️ 产品仓根 `./deploy.sh`（钉 `feat/2.5.0` 的 nohup 老脚本）与 `docker/deploy.sh`（compose 运维壳）**都不是 114 在用的**，不要引用。
  **回滚**: `systemctl disable --now` 两单元 + 从 `bisheng.target` 与 `SERVICES=` 移除；平台其余服务不受影响。
  **依赖**: T018, T036

- [ ] **T073**: `[MVP-核心]` nginx `location /apps/`（仓内两份同构）
  **文件**: `docker/nginx/conf.d/default.conf`（compose 挂载，权威）, `src/frontend/nginx.conf`（镜像内置同构副本）
  **逻辑**: D5：新增 `location /apps/`（前缀匹配，长于 `/` 故优先于 platform SPA fallback；不与正则 `~ ^(/workspace)?/api(/|$)` 冲突）。关键指令 = **变量式 upstream + `resolver`（compose 用 127.0.0.11）延迟解析**（坑 14：nginx 在 config load 时解析静态 `proxy_pass` 主机名，profile 未启动 → 容器名不可解析 → **nginx 整个起不来**，客户升级后前端白屏）+ `proxy_http_version 1.1` + `Upgrade/Connection` 头（复用文件顶部既有 `map`，`default.conf:3-6`）+ 长 `proxy_read_timeout` + `proxy_buffering off` + `error_page 502 503 504 = @apps_unavailable` → 反代 backend 的 `GET /api/v1/apps/_unavailable`。**两份必须同时改**（坑 16：`platform/nginx.conf` / `client/nginx.conf` 是历史残留、不用改）；114 的两份在仓外（`/etc/nginx/conf.d/bisheng-lilu.conf` 4101 与 `bisheng-external-13000.conf`），由 T075 同批改。
  **回滚**: 删除该 location 段；`/apps/*` 回落 platform SPA 引导页（T069），不产生 404 / 5xx。
  **依赖**: T045, T035, T069

- [ ] **T074**: `[MVP-核心]` compose 两个 service + profile 表达「整层不装」
  **文件**: `docker/docker-compose.yaml`（新增 `runtime-manager` / `app-proxy` 两个 service，**不 publish 端口**，加 `profiles: [app-runtime]`）, `docker/deploy.sh`（`ALL_SERVICES` 增两项 + `--profile` 支持）
  **逻辑**: GOV-10「整层可不装」的 compose 形态表达；仓内无 profiles 先例，需在 `deploy.sh` 加 `--profile` 传递。两 service 与 backend 同网络，`bisheng-apps` bridge 网络由 runtime-manager 首次启动时创建。
  **回滚**: 不带 `--profile app-runtime` 启动即整层缺席，平台其余服务零变化（AC-59）。
  **依赖**: T072, T073

- [ ] **T075**: `[MVP-核心]` 114 部署与手动验证（剧本步 4–8）
  **文件**: `features/v3.0.0/054-app-domain-runtime/tasks.md`（本文「114 部署记录」节追加结果）
  **逻辑**: 按 design §7「114 手动验证」执行。**顺序不可换**：`bash /opt/bisheng-ops/deploy.sh` 发代码 → **再**往 `config.yaml` 加 `app_runtime: enabled: true`（坑 23）→ 跑 T017 升级脚本 `plan` 再 `--apply` → **全进程重启**（API / celery×3 / beat / linsight worker，坑 4）→ 装两个 systemd 单元（T072）与 nginx location（T073，114 的两份在仓外）。验证 0–6 步：前置自检（`/api/v1/env.app_runtime_enabled=true`、两单元 active、`runtime-status` 的 `supported_runtimes=["python3.11"]` 与容量快照）· 上线后 `docker inspect` 核对 CPU / 内存 / `ReadonlyRootfs=true` / **无 `Ports`** · ⚙️「管理权限」能搜到主体（验坑 2）· **用非管理员 + 中文姓名账号**访问 `/apps/{slug}`（admin 短路 ReBAC，坑 26；中文姓名验坑 9）· 无痕访问 `?a=1#b` 登录后回到原地址（验坑 11）· 伪造头 `curl -H "X_BiSheng_User_Id: 1"` 应用仍读到真实访问者 · `docker kill` ≤5 分钟自愈 · `systemctl restart bisheng-runtime-manager` 期间应用**零中断**。
  **测试降级**: 需 docker + 真实环境，无法自动化——114 手动验证，结果逐条记入本文「114 部署记录」。
  **覆盖 AC**: AC-13, AC-20, AC-22, AC-25, AC-26, AC-27, AC-31, AC-32, AC-33, AC-46, AC-47, AC-51, AC-55, AC-60, AC-63
  **依赖**: T017, T057, T061, T070, T071, T074

### Wave 4 · `[MVP-114]` 纵切紧随项（design §8 优先级 1–3；**不得裁掉**）

- [ ] **T076**: `[MVP-114]` 出站白名单双层测试
  **文件**: `src/runtime-manager/tests/test_egress.py`（新）
  **逻辑**: 构建期只放行配置的包源与平台分发端点；运行期默认封禁一切出站、只放行平台 API 与 manifest 声明域名；直连 IP / UDP 一律阻断（D12；A DNS-only 与 B 换 runtime 均已被否）。
  **测试降级**: 需 docker，CI 中间件阶段 + 114 手动验证。
  **覆盖 AC**: AC-16
  **依赖**: T029

- [ ] **T077**: `[MVP-114]` 出站白名单双层实现（`--internal` 网络 + egress-proxy + `DOCKER-USER` 兜底 + UDP 封禁）
  **文件**: `src/runtime-manager/runtime_manager/egress.py`（新）, `src/runtime-manager/runtime_manager/lifecycle.py`（接入）
  **逻辑**: D12-C；⚠️ Docker 29 起 nftables 后端**无 `DOCKER-USER` 链**（坑 22），需探测后端分别下发或在部署基线锁定 iptables。**任何非 114 环境部署前是硬前置**。
  **测试**: T076 全部通过。
  **覆盖 AC**: AC-16
  **依赖**: T076

- [ ] **T078**: `[MVP-114]` docker-socket-proxy 端点白名单（D2-B）
  **文件**: `src/runtime-manager/runtime_manager/docker_backend.py`, `docker/docker-compose.yaml`
  **逻辑**: 把 root 等价权限收成端点级（`/build`、`/containers/create|start|stop|remove`、`/images`、`/networks`）；对 manager 代码只是**换一个 base URL**、不构成返工；代理端口绝不对外暴露。
  **覆盖 AC**: AC-14
  **依赖**: T077

- [ ] **T079**: `[MVP-114]` WS 反代 + 不变量① 测试
  **文件**: `src/app-proxy/tests/test_websocket.py`（新）
  **逻辑**: 握手时定死连接授权有效期 = `min(OBO 剩余寿命, ws_max_lifetime_seconds)` + 随机抖动，到期主动 `close(4001)`；WS 升级请求走同一段头剥离代码。
  **覆盖 AC**: AC-25, AC-35
  **依赖**: T045

- [ ] **T080**: `[MVP-114]` WS 反代与不变量① 实现
  **文件**: `src/app-proxy/app_proxy/websocket.py`（新）
  **逻辑**: D6「WS 三不变量落地程度」。
  **测试**: T079 全部通过。
  **覆盖 AC**: AC-25, AC-35
  **依赖**: T079

- [ ] **T081**: `[MVP-114]` WS 不变量②③（吊销 / 停运主动断连 + 前端重握手常态）
  **文件**: `src/app-proxy/app_proxy/connections.py`（新）, `src/backend/bisheng/app_runtime/domain/services/app_state_service.py`（停运 / 撤权时通知）
  **逻辑**: app-proxy 维护 connection → (user, app) 索引，应用停运、可见范围撤销时主动断开该用户连接——**②正是自研 app-proxy 的核心理由**（反代生态无先例），别因为"先只做①"就忘了。
  **覆盖 AC**: AC-35
  **依赖**: T080, **T051**（本任务要改 `app_state_service.py` 的停运 / 撤权路径——该文件由 T049 建、T051 补齐五动作；只写 `依赖: T080` 时链路 T080→T079→T045 完全不经过 T049/T051，并行执行会撞上一个尚不存在的文件）

### Wave 5 · release 必做（MVP-核心之外，按 design §8 优先级）

- [ ] **T082a**: 两个过渡态页测试（Test-First，先于 T082）
  **文件**: `src/app-proxy/tests/test_transition_pages.py`（新）
  **逻辑**: `test_deploying_page_on_generation_switch`（切换窗口 → 「发布中」页而非报错页）→ AC-48 / `test_recovering_page_on_upstream_unreachable`（上游不可达 → 「应用恢复中」页）→ AC-36 / `test_auto_retry_markup_present`（页面含 `meta http-equiv=refresh` 或内联定时 reload，间隔可断言）→ AC-36, AC-48 / `test_ready_after_retry_enters_app`（fake 上游从不可达转就绪 → 下一次请求进入应用，用户无需手动刷新）→ AC-48 / `test_mutually_exclusive_with_four_fallback_pages`（过渡态与 forbidden / stopped / not_found / not_enabled 四类兜底页**互斥**，同一请求只可能命中一类）→ AC-36 / `test_xhr_gets_json_not_transition_html`（非导航请求仍走 T042 的分流口径，返 JSON + 真实状态码）。
  **覆盖 AC**: AC-36, AC-48
  **依赖**: T045, T041

- [ ] **T082**: 两个过渡态页实现（「发布中」/「应用恢复中」+ 自动重试）
  **文件**: `src/app-proxy/app_proxy/pages.py`
  **逻辑**: 自渲染 + `meta http-equiv=refresh` / 内联 JS 定时 reload，就绪后自动进入应用、用户无需手动刷新；与四类兜底页**互斥**。
  **测试**: T082a 全部通过。
  **覆盖 AC**: AC-36, AC-48
  **依赖**: T082a

- [ ] **T083**: 切流量 health gate 与「发布中」联调
  **文件**: `src/runtime-manager/runtime_manager/lifecycle.py`, `src/app-proxy/app_proxy/routing.py`
  **逻辑**: 新实例探活通过才切上游、旧实例宽限退休；切换窗口内入口呈「发布中」而非报错页。
  **覆盖 AC**: AC-21, AC-48
  **依赖**: T082

- [ ] **T084a**: 附件存储句柄测试（Test-First，先于 T084）
  **文件**: `src/runtime-manager/tests/test_storage.py`（新）
  **逻辑**: `test_four_operations_scoped_to_app_prefix`（put / get / delete / list 四操作的对象键恒被强制加 `apps/{app_id}/attachments/` 前缀）→ AC-45 / `test_cross_app_key_rejected`（传入他应用前缀或 `../` 越界键 → 拒绝，不是静默改写）→ AC-45 / `test_single_file_size_limit_enforced` → AC-45 / `test_bucket_is_bisheng_apps_not_public_bucket`（坑 20：`bisheng` 桶挂着 nginx `/bisheng/` location，附件必须落独立 bucket `bisheng-apps`、且该桶无匿名策略、不挂 nginx location）→ AC-45 / `test_not_counted_into_tenant_storage_quota`（不计租户存储配额）→ AC-45。
  **覆盖 AC**: AC-45
  **依赖**: T031, T019

- [ ] **T084**: 附件存储句柄实现（manager 侧四操作 + 越界拒绝 + 单文件上限）
  **文件**: `src/runtime-manager/runtime_manager/storage.py`（新）
  **逻辑**: 按应用收窄、不进公共可读存储、不计租户存储配额（坑 20：`bisheng` 桶挂着 nginx `/bisheng/` location → 用独立 bucket `bisheng-apps`）。
  **测试**: T084a 全部通过。
  **覆盖 AC**: AC-45
  **依赖**: T084a

- [ ] **T085**: 附件句柄环境变量注入（`BISHENG_APP_STORAGE_*`）
  **文件**: `src/runtime-manager/runtime_manager/lifecycle.py`, `src/backend/bisheng/app_runtime/domain/constants.py`
  **逻辑**: 与 F057 SDK storage 同名同 API、与 F053 `dev` 同名注入。
  **覆盖 AC**: AC-45
  **依赖**: T084, **T006**（本任务要改 `app_runtime/domain/constants.py`，该文件由 T006 产出）

- [ ] **T086a**: 数据面 manager RPC 测试（Test-First，先于 T086）
  **文件**: `src/runtime-manager/tests/test_appdb.py`（新）
  **逻辑**: `test_list_tables_and_schema`（表清单 + 列结构）→ AC-56 / `test_row_read_paginated_with_stable_order` → AC-56 / `test_row_update_single_row_only`（一次只改一行，带主键断言；受影响行数 ≠ 1 → 拒绝）→ AC-56 / `test_ddl_statements_rejected`（`CREATE` / `ALTER` / `DROP` / `PRAGMA` 一律拒——**数据面无 DDL**，结构演进归 F055）→ AC-56 / `test_export_produces_file_handle` → AC-56 / `test_short_transaction_and_busy_timeout`（短事务 + `busy_timeout`；断言不开长事务扫全表——WAL 单写者下长事务会把应用自己的写阻塞住）→ AC-56 / `test_backend_never_opens_host_db_file`（RPC 是唯一通路，K1 / 多节点，D10-C）→ AC-56。
  **覆盖 AC**: AC-56
  **依赖**: T031, T019

- [ ] **T086**: 数据面 manager RPC 实现（表清单 / 结构 / 行读写 / 导出，**无 DDL**）
  **文件**: `src/runtime-manager/runtime_manager/appdb.py`（新）
  **逻辑**: D10-C（backend 直读宿主库文件违反 K1 且多节点必错）；短事务 + `busy_timeout`，别开长事务扫全表。
  **测试**: T086a 全部通过。
  **覆盖 AC**: AC-56
  **依赖**: T086a

- [ ] **T087a**: backend `AppDataService` 测试（Test-First，先于 T087）
  **文件**: `src/backend/test/app_runtime/test_app_data_service.py`（新）
  **逻辑**: `test_owner_only_business_rule_precheck`（仅 owner；租户管理员与平台超管同样被拒——**业务规则前置拦截**，不能依赖权限运行时，管理员在那里会被短路放行）→ AC-56 / `test_non_owner_gets_16162_not_403`（业务码 `16162`「无权访问应用数据」，坑 25）→ AC-56 / `test_row_edit_audited_with_before_after`（审计 `app.data_row_edit`，记表名 / 主键 / 变更前后）→ AC-56, AC-65 / `test_ddl_rejected_at_backend_layer_too`（backend 侧同样拒 DDL，不把判断全交给 manager）→ AC-56 / `test_forwards_to_manager_only_never_opens_db_file`（用 `fake_orchestrator` 断言只走 RPC）→ AC-56 / `test_mcp_face_reuses_same_service_method`（F052 MCP 数据工具复用同一方法、**不得直连 manager**——断言 Service 是唯一实现）→ AC-56。
  **覆盖 AC**: AC-56
  **依赖**: T086, T009

- [ ] **T087**: backend `AppDataService` 实现（owner 收窄 + 审计 + 转发）
  **文件**: `src/backend/bisheng/app_runtime/domain/services/app_data_service.py`（新）
  **逻辑**: 仅 owner（业务规则前置拦截）；单行编辑二次确认 + 审计 `app.data_row_edit`；**F052 MCP 数据工具复用同一方法、不得直连 manager**。启用 T004 预留的 `16162`。
  **测试**: T087a 全部通过。
  **覆盖 AC**: AC-56
  **依赖**: T087a

- [ ] **T088**: Platform 数据 tab（表清单 → 分页查看 → 单行编辑 → 导出）
  **文件**: `src/frontend/platform/src/pages/BuildPage/hostedApp/tabs/DataTab.tsx`（新）
  **逻辑**: `bs-ui/table` + `useResizableColumns` + `AutoPagination` + `Dialog` 行编辑（保存前 `bsConfirm`）；导出**走后端产文件 + `downloadFile`**（别新用已被 lint 冻结的 `xlsx`）。react-query **禁用**（lint 冻结），用 `useTable` 或 `useState + useEffect`；权限失败按业务码 `16162` 渲染提示，**不得触发 403 整页跳转**（坑 25）。
  **手动验证**（Playwright 未落地）: 详情页数据 tab → 表清单列出应用建的表；点表 → 分页翻页正常、列宽可拖；单行编辑弹窗保存前有二次确认、保存后表格即时刷新且「系统操作」页能查到 `app.data_row_edit`；导出下载得到文件且内容与表格一致；**非 owner 账号（含租户管理员）看到"无权访问应用数据"提示而不是被甩到 `/403` 页**；应用无表时显示空态。
  **覆盖 AC**: AC-56
  **依赖**: T087, T066

- [ ] **T089a**: 访问记录留痕测试（Test-First，先于 T089）
  **文件**: `src/backend/test/app_runtime/test_app_access_log.py`（新）
  **逻辑**: `test_one_row_per_entry_not_per_request`（一次进入一条，同一会话的后续静态资源 / XHR 请求不再产生行——**不记请求级明细**）→ AC-38 / `test_dedup_window_setnx_merges_repeat_entries`（`SETNX app_access:{app_id}:{user_id}` 窗口内重复进入只留一条；窗口过期后再进入产生新行；默认 300s）→ AC-38 / `test_row_fields_complete`（应用 / 访问用户 / 时间 / 租户齐全）→ AC-38 / `test_written_only_on_allow_decision`（判定为 login / forbidden / stopped / not_found 时**不写行**）→ AC-38 / `test_write_failure_does_not_block_entry`（fire-and-forget：Redis 或 DB 异常时入口判定仍返回 allow，异常被吞并记日志）→ AC-38 / `test_tenant_isolation_of_access_log`（跨租户查不到别租户的访问记录——依赖 `_TENANT_AWARE_MODEL_MODULES` 已登记 `app_access_log`；**故意先断言登记生效**，漏登记时这条会红）→ AC-38 / `test_app_proxy_does_not_write_directly`（写入方恒是 backend 内部授权端点，app-proxy 不连库）→ AC-38。
  **测试降级**: 无（连 test 中间件 MySQL + Redis，CI 跑）。
  **覆盖 AC**: AC-38
  **依赖**: T035, T009

- [ ] **T089**: 访问记录留痕实现（`app_access_log` + Redis 去重窗口）
  **文件**: `src/backend/bisheng/database/models/app_access_log.py`（新）, `src/backend/bisheng/core/database/alembic/versions/v3_0_0_f054_app_access_log.py`（**新 Alembic revision，`down_revision` 必须挂在 T003 的 `v3_0_0_f054_app_runtime_tables` 之后**；DDL-only、不传 `mysql_charset` / `mysql_collate`，C2 / K4）, `src/backend/bisheng/core/database/tenant_filter.py`（`_TENANT_AWARE_MODEL_MODULES:39` 追加 **`bisheng.database.models.app_access_log`**——design §4.3 要求登记的四个模块路径的**第四个**，T002 只落了前三个）, `src/backend/bisheng/app_runtime/domain/services/entry_authz_service.py`, `features/v3.0.0/release-contract.md`（**表 1「领域对象归属」新增 `AppAccessLog` 行**，Owner = F054、查询面 F056；表 1 现只有 App / AppVersion / AppInstance）
  **逻辑**: D14-B：独立业务日志表 + `asyncio.create_task` fire-and-forget + `SETNX app_access:{app_id}:{user_id}` 合并窗口（默认 300s，**窗口值由 F056 定**）；写入方是 **backend 内部授权端点**（判定通过时顺带），不是 app-proxy 直连库；一次进入一条、不记请求级明细。
  **回滚**: revision `downgrade()` drop 表；**访问记录是审计资产，drop 前先 dump**；tenant_filter 登记回退 = 删元组项。
  **跨 Feature**: 改核心库共享文件 `tenant_filter.py`（只增元组项）+ 回写 `release-contract.md` 表 1（新增领域对象必须登记，检查项 17）。
  **测试**: T089a 全部通过。
  **覆盖 AC**: AC-38
  **依赖**: T089a, T003

- [ ] **T090a**: 审批期临时预览入口测试（Test-First，先于 T090）
  **文件**: `src/backend/test/app_runtime/test_preview_entry.py`（新，backend 判定侧）, `src/app-proxy/tests/test_preview.py`（新，反代侧）
  **逻辑**: backend 侧：`test_only_approver_of_that_ticket_allowed`（该审批单的审批人 allow；同租户其他用户 / owner 本人 / 别单审批人一律 forbidden 页）→ AC-37 / `test_preview_session_expired_or_unknown_returns_not_found_page`（过期 / 未知 session 与"不存在"同页，防信息泄漏）→ AC-37 / `test_injected_identity_is_approver_himself`（注入的是审批人本人身份，不是 owner、不是模拟身份——INV-32）→ AC-37, AC-31 / `test_fga_unavailable_fail_closed` → AC-12。app-proxy 侧：`test_preview_path_uses_same_strip_and_inject_code`（`/apps/preview/{session}` 走 T039 同一段头剥离 / 注入代码，不另写一份）→ AC-32 / `test_preview_prefix_stripped_and_forwarded_prefix_set` → AC-25 / `test_preview_instance_lifecycle_not_controlled_here`（app-proxy / F054 不拉起也不回收预览实例，**归 F055**；上游不存在时呈过渡态页）→ AC-37。
  **覆盖 AC**: AC-12, AC-25, AC-31, AC-32, AC-37
  **依赖**: T045, T033, T009

- [ ] **T090**: 审批期临时预览入口实现（`/apps/preview/{session}`）
  **文件**: `src/app-proxy/app_proxy/preview.py`（新）, `src/backend/bisheng/app_runtime/domain/services/entry_authz_service.py`
  **逻辑**: 仅该审批单的审批人可达（其他人得无权限页），注入审批人本人身份，其余注入与转发规则同正式入口；**实例的拉起 / 回收由 F055 控制**。
  **测试**: T090a 全部通过。
  **覆盖 AC**: AC-37
  **依赖**: T090a

- [ ] **T091**: 入口二维码
  **文件**: `src/frontend/platform/src/pages/BuildPage/hostedApp/tabs/PublishTab.tsx`, `src/frontend/platform/package.json`
  **逻辑**: `qrcode.react` 走 pnpm catalog 加进 platform（`pnpm-workspace.yaml:22` 已登记 `^4.2.0`，**monorepo 不引入新库**）；二维码内容 = **后端返回的完整入口地址**（不用 `location.origin` 拼——dev 下 origin 是 :3001 且 `/apps` 不在 vite 代理内，拼出来的码扫了打不开）。
  **手动验证**（Playwright 未落地）: 发布 tab 出现二维码；**用手机扫码**（或用二维码识别工具解出文本）得到的地址与「复制入口链接」按钮复制到的地址**逐字符一致**、且能直达 `/apps/{slug}`；应用未上线 / 已停运时二维码与入口链接的显隐口径一致；`pnpm lint` + `pnpm typecheck`（从 `src/frontend/`）通过。
  **覆盖 AC**: AC-54
  **依赖**: T067

- [ ] **T092**: `node20` / `static` Dockerfile 模板
  **文件**: `src/runtime-manager/runtime_manager/templates/node20/Dockerfile.j2`（新）, `src/runtime-manager/runtime_manager/templates/static/Dockerfile.j2`（新）
  **逻辑**: 同一份模板矩阵扩两档，`SUPPORTED_RUNTIMES` 自动含三值；安全基线（非 root / read-only 友好 / base path wrapper）与 `python3.11` 一致。
  **覆盖 AC**: AC-15
  **依赖**: T023

- [ ] **T093**: 备份手册：应用存档位置随平台备份
  **文件**: `docs/architecture/09-development-guide.md`（或运维备份章节）
  **逻辑**: 列出代码快照（`bisheng-apps/apps/{app_id}/versions/*`）、SQLite 快照（`.backup` 后 tar，坑 19：**裸 tar WAL 库会得到不一致副本**）、附件前缀三处位置与恢复步骤。
  **覆盖 AC**: AC-45
  **依赖**: T085

- [ ] **T094a**: 档位解析测试（Test-First，先于 T094）
  **文件**: `src/backend/test/app_runtime/test_tier_resolution.py`（新）
  **逻辑**: `test_tier_resolved_from_table_when_present_else_default_tiers`（`ResourceTier` 表有行以表为准，否则回落 T006 的 `DEFAULT_TIERS`）→ AC-64 / `test_tier_change_does_not_touch_running_instance`（改档位后运行中实例的限额不变、不触发在线 update、不重建）→ AC-64 / `test_tier_change_takes_effect_on_next_publish`→ AC-64 / `test_tier_change_takes_effect_on_resume`→ AC-64 / `test_ac63_baseline_is_snapshot_tier_not_current_table`（**AC-63 的核验基准恒是"该实例所属版本快照里 `tier_id` 当时解析出的规格"**，不是当下的表；构造"发布后改表"场景断言核验仍用快照值，D11）→ AC-63。
  **覆盖 AC**: AC-63, AC-64
  **依赖**: T051, T009, T006

- [ ] **T094**: 档位规格调整自下次发布 / 重新启用生效（实现）
  **文件**: `src/backend/bisheng/app_runtime/domain/services/app_state_service.py`
  **逻辑**: 限额在**创建容器时**固化、不做在线 update；运行中实例不受影响；`ResourceTier` 表存在时以表为准、否则用 `DEFAULT_TIERS`；**AC-63 的核验基准恒是"该实例所属版本快照里 `tier_id` 当时解析出的规格"**，不是当下的表（D11）。依赖 F055 的档位管理 tab。
  **测试**: T094a 全部通过。
  **覆盖 AC**: AC-63, AC-64
  **依赖**: T094a

- [ ] **T095**: 稳定性双形态验收自动化（AC-49 用例可移植性）
  **文件**: `src/backend/test/app_runtime/test_stability_portable.py`（新）
  **逻辑**: 把 AC-20 / AC-22 / AC-46 / AC-47 / AC-48 / AC-50 写成**不含任何 compose 专有步骤**的用例（只用形态无关的意图 RPC 与 `phase` 取值），F059 可原样在 k8s 形态执行（**INV-33，已于 2026-08-17 随 F054 spec 定稿在 `release-contract.md:54` 转正，不再是候选**；T030 的写法即为正式口径，两处口径统一）。
  **测试降级**: 需 docker，CI 中间件阶段 + 114 手动验证。
  **覆盖 AC**: AC-20, AC-22, AC-46, AC-47, AC-48, AC-49, AC-50
  **依赖**: T029, T083

- [ ] **T096**: E2E（`/e2e-test`）+ 页面手动验证清单
  **文件**: `src/backend/test/e2e/test_e2e_app_domain_runtime.py`（新，由 `/e2e-test features/v3.0.0/054-app-domain-runtime` 生成）, `features/v3.0.0/054-app-domain-runtime/tasks.md`（追加清单结果）
  **逻辑**: API 层 E2E 走 design §7 与 `mvp-114-path.md` §1 步 4–8 剧本（**非管理员账号**）；页面手动清单覆盖构建页三类型筛选 / 状态筛选五值 / ⚙️ 菜单只两项 / 已上线删除置灰 / 详情页四 tab / 停运 → 入口呈已停用 → 重新启用恢复。
  **测试降级**: 前端交互 = 手动验证——理由：Playwright 未落地。
  **覆盖 AC**: AC-42, AC-51, AC-52, AC-53, AC-54, AC-55, AC-56, AC-57, AC-58
  **依赖**: T088, T091, T095

- [ ] **T097**: 关键日志 / 指标落地（design §7 整节的承接任务）
  **文件**: `src/app-proxy/app_proxy/observability.py`（新）, `src/app-proxy/tests/test_observability.py`（新）, `src/runtime-manager/runtime_manager/observability.py`（新）, `src/runtime-manager/tests/test_observability.py`（新）, `src/backend/bisheng/app_runtime/domain/services/app_state_service.py`（`app.state_transition` 结构化日志）
  **逻辑**: design §7「关键日志 / 指标」此前**无任务承接**——这些是上线后排障与 AC-32 伪造头监控的唯一手段，落不了地只能事后补。三处逐条落：
  - app-proxy：`app_proxy.request`（结构化字段 `request_id / slug / user_id / decision / reason / cache_hit / upstream_status / latency_ms`）· **`app_proxy.header_strip`（记录被剥离的伪造头名；`WARNING` 级并可告警——AC-32「伪造无效」只有这一条能在生产上被观测到）** · `app_proxy.fallback`（兜底页类型分布）。
  - runtime-manager：`rtm.intent`（`kind / app_id / result / latency_ms`）· `rtm.reconcile`（每轮 `desired / actual / actions`）· `rtm.rebuild`（unhealthy 重建，**频次异常 = 应用本身有问题**）· `rtm.admission_reject`（**含容量快照**，与 T021 返回的 snapshot 同字段，供 AC-65 成因与运维对账用同一份数据）。
  - backend：`app.state_transition`（`from → to / reason / actor`）。
  测试断言"**事件名 + 必填字段齐全**"（而非日志文本）：`test_request_log_fields_complete` / `test_header_strip_logged_at_warning_with_forged_names` / `test_fallback_type_recorded` / `test_intent_and_reconcile_fields` / `test_admission_reject_carries_snapshot` / `test_state_transition_logged_for_all_five_actions`。⚠️ backend 侧用 `loguru` 时**不得传 `exc_info` 等 stdlib kwarg**（会炸 KeyError，memory `project_loguru_exc_info_strands_sessions`）；两个独立包用各自的 stdlib logging。
  **覆盖 AC**: AC-32, AC-65
  **依赖**: T045, T029, T051

---

## AC → 任务追溯表（核对用）

> 每条 AC 至少出现在一个**测试任务**（或标注了手动验证步骤的前端 / 部署任务）的「覆盖 AC」里；标 † 的仅由手动验证 / E2E 覆盖，理由见该任务。

| AC | 测试任务 | AC | 测试任务 | AC | 测试任务 |
|---|---|---|---|---|---|
| AC-01 | T048 | AC-23 | T030, T054 | AC-45 | T024, T084a, T084, T085, T093 |
| AC-02 | T048 | AC-24 | T024 | AC-46 † | T075, T095 |
| AC-03 | T050 | AC-25 | T026, T044, T054, T075, T079, T090a | AC-47 | T028, T075, T095 |
| AC-04 | T048, T050 | AC-26 | T032, T034, T040, T075 | AC-48 | T082a, T083, T095 |
| AC-05 | T048 | AC-27 | T042, T075 | AC-49 | T095 |
| AC-06 | T052, T056 | AC-28 | T032, T034, T040 | AC-50 | T028, T095 |
| AC-07 | T048 | AC-29 | T032, T034, T040 | AC-51 | T058, T063 †, T070 †, T075, T096 |
| AC-08 | T048, T052 | AC-30 | T032, T034, T040, T069 † | AC-52 | T054, T056, T064 †, T096 |
| AC-09 | T010, T011, T012, T013, T014 †, T015 † | AC-31 | T032, T038, T075, T090a | AC-53 | T064 †, T065 †, T096 |
| AC-10 | T010, T040 | AC-32 | T038, T075, T090a, T097 | AC-54 | T066 †, T067 †, T091 †, T096 |
| AC-11 | T010, T048 | AC-33 | T024, T026, T044, T075 | AC-55 | T030, T054, T056, T068 †, T075, T096 |
| AC-12 | T010, T032, T040, T090a | AC-34 | T032, T034 | AC-56 | T086a, T087a, T088 †, T096 |
| AC-13 | T016, T017, T075 | AC-35 | T079, T081 | AC-57 | T054, T058, T063 †, T096 |
| AC-14 | T046, T078 | AC-36 | T040, T044, T082a | AC-58 | T061, T063 †, T066 †, T096 |
| AC-15 | T022, T092 | AC-37 | T090a | AC-59 | T061 |
| AC-16 | T076 | AC-38 | T089a | AC-60 | T061, T075 |
| AC-17 | T024 | AC-39 | T024, T050 | AC-61 | T061 |
| AC-18 | T026 | AC-40 | T024, T050 | AC-62 | T061, T062 †, T071 † |
| AC-19 | T020, T046, T050 | AC-41 | T050, T056, T067 † | AC-63 | T024, T075, T094a |
| AC-20 | T024, T028, T075, T095 | AC-42 | T050, T056, T064 †, T065 †, T096 | AC-64 | T094a |
| AC-21 | T026, T044, T083 | AC-43 | T050, T056 | AC-65 | T020, T050, T056, T067 †, T097 |
| AC-22 | T028, T075, T095 | AC-44 | T050, T056 | | |

**未被任何测试任务覆盖的 AC：无。**（2026-08-17 修订：AC-37 / AC-38 原先只挂在纯实现任务 T090 / T089 上，现分别由新增测试任务 **T090a** / **T089a** 覆盖，该断言方才成立。）

**汇总**（2026-08-17 审查后重算，逐条与正文实列核对过）：
- **任务 104 个**：T001–T097（97 条）+ 7 条后缀 a 的补充测试任务（T082a / T084a / T086a / T087a / T089a / T090a / T094a）。
- **Wave 5 个**。
- `[MVP-核心]` **75 个**（T001–T075，Wave 1–3 全部，逐条标记）。
- `[MVP-114]` 紧随项 **6 个**（T076–T081，Wave 4，逐条标记）。
- **测试任务 34 个**：T010 / T016 / T020 / T022 / T024 / T026 / T028 / T030 / T032 / T034 / T038 / T040 / T042 / T044 / T046 / T048 / T050 / T052 / T054 / T056 / T058 / T061 / T075 / T076 / T079 / T082a / T084a / T086a / T087a / T089a / T090a / T094a / T095 / T096（**数一遍：25 条无后缀 + 7 条后缀 a + T095 + T096 = 34**）。
- **数据库变更 3 组**（T001 / T002+T003 / T089，均含回滚方案；T089 的 revision `down_revision` 挂在 T003 之后）。
- Client 任务 **2 个**（T015 / T071）。
- 标「测试降级：需 docker」的任务 **8 个**：T022 / T024 / T026 / T028 / T030 / T075 / T076 / T095。**另**：T096 的前端交互、T088 / T091 的 platform 页面行为降级为手动验证（Playwright 未落地），不计入这 8 个。
- **跨栈（前后端同任务）任务 1 个**：T007（理由写在该任务的「跨栈说明」里，是仓内既成的 lockstep 结构）。

---

## 114 部署记录

> T075 执行时填写：部署时间 / commit / `app_runtime` 键写入时间 / 升级脚本 `apply` 与 `verify` 输出 / 全进程重启时间 / 手动验证 0–6 步逐条结果（含 `docker inspect` 关键字段、非管理员 + 中文姓名账号的截图或日志）。

（未开始）

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认（§3 第四个 ★），再记录。

| 任务 | 偏差 | 回写到 design | 原因（一句话） |
|---|---|---|---|
| — | — | — | — |

（尚无偏差；实现期每条偏差一行，design 同步覆盖为「今天的状态」。）
