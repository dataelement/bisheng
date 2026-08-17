# Tasks: 发布管线、预置审批流、版本记录、资源档位与能力总线

**关联规格**: [spec.md](./spec.md)（65 条 AC，What 的唯一真相）· [design.md](./design.md)（How 的唯一真相，D1–D16 / 坑 1–30 / §4.2 契约 / §8 后续）
**版本**: v3.0.0
**纵切**: [mvp-114-path.md](../mvp-114-path.md) **§6 MVP-核心**（预算受限版，本轮裁剪基准）与 §2 F055 行——**Wave 1–3 全部标 `[MVP-核心]`**，Wave 4–7 为 release 必做但本轮顺延，只列标题 / 文件 / 测试载体 / 覆盖 AC，不展开逻辑。
**§6 字面读法的两处对齐**：① §6 F055 顺延栏写「`withdraw` 守卫**以外**的事件触达全表」→ 守卫（AC-22）留在 MVP 内 → **T051 归 Wave 3.9**（修点一行 + 一个测试文件，成本极低，无理由为省一行而偏离基准）；② 顺延栏其余项（审读视图 / 预览 / 能力总线 / 结构演进 / 版本差异 / 档位 tab）照 §6 顺延。
**代码事实口径**: 本文所有 `文件:行号` 沿用 design.md（`3.0-vibe`，2026-08-17 核实，路径以 `src/backend/bisheng/` 为根；前端另注 `platform/` = `src/frontend/platform/src/`、`client/` = `src/frontend/client/src/`）。**行号会漂移、符号名不会——落地前一律以符号名重定位。**

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-08-17 初稿 + 同日独立审查 33 条修订，65 AC 定稿（决议-1～9） |
| design.md | ✅ 已评审 | 2026-08-17 初版 + 同日评审 15 条修订（D1–D16 / 30 坑）；接手时的第一入口 |
| tasks.md | ✅ 已拆解（2026-08-17） | 本文；70 任务 / 7 Wave / 53 条 `[MVP-核心]`（2026-08-17 独立审查 14 条修订：Celery 登记 / 组合根接线 / 跨 Wave 执行序 / 档位依赖链 / 图标落地 / 16207 闸 / T044·T027 拆分 / 路径与 i18n 补齐 / 建桶接线 / 顺延任务测试载体 / 追溯表订正 / T051 上提） |
| 实现 | 🚧 进行中 | 7 / 70 完成（Wave 1 全部落地，2026-08-17）。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3-§4 |

---

## 开发模式

**按 Wave 组织任务**：
- **Wave 1**（T001–T007）= 基础设施，无测试配对，排最前，彼此可并行。
- **Wave 2**（T008–T023）= 管线服务（manifest / 包 / 扫描 / 档位 / 版本 / 预检 / 接收 / 阶段机），Test-First 成对。
- **Wave 3**（T024–T051）= 预置审批流与三项阻塞前置、审批终态与上线动作、`deploy`/`logs` 权限判定与状态接口、前端最小面、`withdraw` 终态守卫、114 手动验证与上游回写。
- **Wave 4–7** = release 必做但本轮顺延（design §8 的优先级顺序：审读视图 / 预览实例 → 能力总线 / 运行期凭据 → 结构演进 → 版本差异 → 档位 tab）。**只列标题 + 文件 + 测试载体 + 覆盖 AC**，展开在开工那一刻做。

**⚠️ 跨 Wave 执行序（Wave 编号 ≠ 拓扑序，照 Wave 顺跑会当场卡住）**：Wave 2 的 `accept()` / `run_pipeline()` 需要 Wave 3.2 的 `publish_approval_service`（在途闸 / 待上线闸 / Gate 提交），而 Wave 3.4 的 T038 又回头依赖 T021 / T023 —— **不拆任务、只按下面的真实拓扑序执行**：

```
T001–T007（Wave 1，可并行）
  → T014/T015 → T008/T009 → T010/T011 → T012/T013 → T016/T017 → T018/T019   ← Wave 2 前段（档位先行：T009 直接调 resolve_tier）
  → T024/T025 → T026/T027a/T027b → T028/T029 → T030/T031                    ← Wave 3.1–3.2 提前，产出 publish_approval_service
  → T020/T021 → T022/T023                                                    ← 回到 Wave 2 后段（accept / run_pipeline）
  → T032/T033 → T034/T035 → T036/T037 → T038/T039 → T040/T041 → T042/T043    ← Wave 3.3–3.5
  → T044a/T044b → T045 → T046 → T047 → T048 → T051 → T049 → T050             ← Wave 3.6–3.9
```

测试任务可先于其依赖的实现任务落盘（红测即预期），**实现任务一律按 `依赖:` 行排**。

**后端 Test-First**：测试任务先于其配对实现任务，`覆盖 AC` **逐条列举**（禁 `AC-01~AC-05` 范围写法）。基础设施任务（ORM / Alembic / 错误码 / Settings / 审计登记 / conftest）无测试配对、排最前。单测落 `src/backend/test/app_publish/`（**不放 `test/` 根**），`asyncio_mode=auto`。集成测试连 test 中间件（MySQL / Redis / MinIO / OpenFGA）在 CI 跑；DM8 在 105 回归。

**编排器一律 mock**：Wave 2–3 的后端测试全部 monkeypatch F054 `orchestrator_client`（build / build_status / probe / admission / deploy），**不连真 docker**；真拉起只在 T049 的 114 手动验证里出现。

**前端**：Platform / Client 分列，附「手动验证」步骤（Playwright 未落地）。platform `react-query` 已被 eslint 冻结（design K11 ①）→ 新面用 `platform/src/util/hook.ts:215 useTable` 或裸 `useState + useEffect`；新增 i18n key 三语同 PR；**触碰即还**：改到的存量文件里的冻结中文违规同 PR 抽键并 `pnpm lint:prune`（根 AGENTS.md）。

**自包含任务**：每个任务内联文件、逻辑、依赖、AC 覆盖；设计论证指向 design §X / D-x / 坑-x，**不复制**（避免第三处漂移）。

**⚠️ 一项待 ★ 确认、本轮按 spec 字面顺序实现**：密钥扫描的执行位置（design D5）。本文一律按 **spec AC-01 / F053 AC-31a 的字面顺序** 落地：`precheck_manifest → precheck_build → precheck_probe → secret_scan → 审批单`。「提前到构建之前」同时推翻两份已 ★ 确认的 spec，**不得在实现期自行调换**；确认通过后只需调换 `PIPELINE_STAGES` 元组里两个 step 的注册顺序，并同批改 F055 spec AC-01 / F053 spec AC-31a / design D4 与 §4.1。

**⚠️ 错误码一码一义（design §4.2 ⑧ 的两条红线，落码前对照）**：`16225` **只**归「审批场景未启用」；构建期 / 上线期容量不足是 `16226`。档位失败只有 `16223` 一个码（"不存在或已停用"），成因用 `details.reason: "not_found" | "disabled"` 表达，**不拆码**。

**⚠️ 错误码段 162 的分配已在上游完成**（design K9）：`release-contract.md` 的「已分配模块编码」表与 `docs/constitution.md` C5 均已写死 `162 = app_factory · F055 段`（F054 落码时一并写入）。**不要再去"修正"那两张表**——只需新建 `common/errcode/app_publish.py` + 三语 `api_errors`。

**跨 Feature 副作用登记**（release-contract 表 1 / 清单检查项 17）：
- **T025**（`approval/domain/services/approver_resolver.py` 的 `tenant_admin` 来源改真租户管理员 + Root 回退）—— **行为变更，对一切使用该来源的既有场景（频道订阅 / 知识空间加入）与人工配置立即生效**（AC-21），release note 必须显著声明；T024 的既有场景回归测试是它的护栏。
- **T027b**（`tenant/domain/services/tenant_service.py` `acreate_tenant` 与 `tenant_mount_service.py` `mount_child` 各挂一次 seed 钩子）—— 改的是 Tenant 领域的创建流程（归 F011/F012 域），只**追加** try/except 包住的一步，不改其它步骤；两条路径缺一即漏（坑 3）。**独立成任务、单独 review**（T027a 只做 seed 参数化与新场景条目，不碰 Tenant 领域）。
- **T029**（`approval/domain/services/approval_registry.py` 加 preset + `approval_runtime_handler_factory.py` 加分支）—— 审批模块注册表扩展，漏工厂分支 = 审批通过后应用永不上线（K1 ③）。
- **T035**（`approval/domain/services/approval_center_service.py` 新增 `cancel_instance_by_business`）—— 新增审批模块公共 API，**不改** `withdraw_instance` 既有行为（守卫是 T051，Wave 3.8）。
- **T035**（`main.py` lifespan `:82` 与 `worker/main.py` `on_worker_init`（`celeryd_after_setup`，`:80-87`）各调一次 `app_publish.composition.register()`）—— **组合根接线是两处、不是一处**：只挂 API lifespan 则 Celery worker 进程里删除钩子与场景 handler 从未注册，审批通过后工厂找不到 handler（K1 ③）、应用删除不取消在途单（AC-35 破），且形态是"API 里测都对、生产不生效"。
- **T023**（`worker/__init__.py` 顶部 `# register tasks` 显式 import 块追加一行）—— celery app 是 `Celery("bisheng", include=["bisheng.worker"])`（`worker/main.py:22`），**所有任务靠该 import 块注册**（审批 outbox 亦然）；漏登记 = `apply_async` 后 worker `NotRegistered`，表现为「deploy 返回成功、状态永远卡在 `received`」。
- **T006 / T045**（`database/models/audit_log.py` 两处白名单 + platform `controllers/API/log.ts` + `bs.json` 三语）—— 审计可见性四处 lockstep，**审计对象的查询面归 F056、写入归本 Feature**（坑 21）。
- **T015**（回写 F054 `app_runtime/domain/constants.py` 的 `DEFAULT_TIERS` 数值与第三档名称）—— F054 领域常量，档位实体归 F055（表 1），数值以本 spec AC-44 为准（坑 27）。
- **T044b**（platform `BuildPage/hostedApp/tabs/PublishTab.tsx` 填 slot）—— **F054 T067 已交付的应用态徽标 / 入口链接 / 停运 / 重新启用 / 手动上线三按钮一律不重做**，F055 只填 slot 内容并把 `can.manual_publish` 等条件经 props 下传（design D15）。
- **T002**（`database/models/resource_tier.py` 落共享层）—— 与 F054 只读契约相关：模型放共享层就是为了不让 `app_runtime` 反向 import `app_publish`（C1 / D16）；**arch-guard 不管 domain 层跨模块方向，靠 review 维持**。
- **T050**（回写 F053 spec AC-32 / F054 design + tasks；同 PR 更新 `.claude/skills/approval-module/SKILL.md`）。

**依赖 F054 的任务ID（跨 Feature，签名变更须回头改本文）**：F054 **T001**（`app` / `app_version` 模型与 DAO）· **T006**（`AppState` 枚举 + `DEFAULT_TIERS`）· **T047**（`orchestrator_client` 门面）· **T049**（`create_app` / `stage_version` / 取版规则）· **T051**（五个状态动作 + `lifecycle_hooks`）· **T053**（`AppMetaService.update_meta`）· **T057**（`/api/v1/apps/*` 端点）· **T064**（`useHostedAppActions`）· **T066/T067**（详情页壳与发布 tab slot）。依赖 F049 的：**T005**（`open_api_subject` `Depends` 工厂）· **T002/T003**（`api_credential.KEY_PREFIX` / `KEY_SECRET_LENGTH` 常量、`OpenApiPrincipal.resource_owner_user_id`）· **T005**（`app:manage` 位注册）。

---

## Tasks

### Wave 1 · `[MVP-核心]` 基础设施（无测试配对，排最前）

- [x] **T001**: `[MVP-核心]` ORM `app_deployment` 模型 + DAO + 租户感知登记
  **文件**: `src/backend/bisheng/app_publish/domain/models/app_deployment.py`（新）, `src/backend/bisheng/core/database/tenant_filter.py`（`_TENANT_AWARE_MODEL_MODULES:39` 登记 `bisheng.app_publish.domain.models`）
  **逻辑**: 按 design §4.2 ⑤ 建表（继承 `SQLModelSerializable`，含 `tenant_id` / `create_time` / `update_time`）：`id`(str PK) · `tenant_id` · `app_id`(str，首发时在 `create_app` 后回填) · `owner_user_id`(int，自然人) · `submitted_by_user_id`(int，服务账号) · `version_id`(str null) · `approval_instance_id`(int null) · **`stage` VARCHAR(32) 显式列** · **`status` VARCHAR(16) 显式列** · `code_object_key` · `manifest`(`JsonType`) · `tier_code` · `failure`(`JsonType`) · `scan_result`(`JsonType`)。**凡需 SQL 筛选的一律拆显式列**、JSON 列禁 `JSON_EXTRACT` / `JSON_CONTAINS`（C2 / K6）。DAO `AppDeploymentDao.{acreate, aget, aget_active_by_app, aadvance_stage, aset_failed}`——`aadvance_stage` 是**单行 UPDATE**；**禁批量 UPDATE / DELETE**（租户监听器只拦 SELECT，坑见 memory `reference_tenant_filter_in_list_trap`）。`stage` 取值集合 `{received, secret_scan, precheck_manifest, precheck_build, precheck_probe, version_recorded, approval_created, approved, publishing, online, pending_online}`、`status` 取值 `{running, waiting_approval, succeeded, failed}`（D1）。
  **回滚**: 建表 DDL 在 T003；本任务纯模型，回滚 = 删文件 + 撤销 tenant_filter 登记。
  **依赖**: 无

- [x] **T002**: `[MVP-核心]` ORM `resource_tier` 模型（**落共享层**）+ DAO
  **文件**: `src/backend/bisheng/database/models/resource_tier.py`（新）, `src/backend/bisheng/core/database/tenant_filter.py`（登记 `bisheng.database.models.resource_tier`，并在登记处写一行注释「无 `tenant_id` 列，登记只为 metadata import、不受自动过滤」）
  **逻辑**: 列：`id`(PK) · `code`(unique，`light` / `standard` / `performance`) · `name` · `cpu_millicores`(int) · `memory_mb`(int) · `description` · `enabled`(bool) · `sort_order` · `create_time` / `update_time`。**用整数毫核与 MB，不用浮点 vCPU**（DM8 与 JSON 往返会给出 `0.30000000000000004`，D11）。**平台级、无 `tenant_id` 列**（AC-44 跨租户共享，K6 ②）。DAO `ResourceTierDao.{alist, aget_by_code, acreate, aupdate_row}`——**不提供 delete**（AC-47 的前提：`app_version.tier_id` 是历史快照引用，删档会让老版本重新启用时解析不出规格，D11）。
  **⚠️ 为什么不落 `app_publish/domain/models/`**：`ResourceTier` 归 F055、**F054 只读**（release-contract 表 1 / F054 design D11），放进 `app_publish` 会逼 `app_runtime` 反向 import，双向依赖当场成立且**没有任何 arch-guard 规则会拦**（design C1 / D16 的订正）。业务逻辑仍全在 T015 的 `ResourceTierService`。
  **回滚**: 同 T001（DDL 在 T003）。
  **依赖**: 无

- [x] **T003**: `[MVP-核心]` Alembic revision：`app_deployment` + `resource_tier` 两表
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v3_0_0_f055_app_publish_tables.py`（新）
  **逻辑**: **DDL-only**（`core/database/alembic/AGENTS.md`）；`down_revision` 取 `uv run alembic heads` 的**唯一头**（F054 的建表 revision 落地后头会变，落码时现取）；**不传 `mysql_charset` / `mysql_collate`**（DM8 双方言，C2）；JSON 列用 `JsonType` 对应方言类型（DM8 落 CLOB）；索引：`resource_tier.code` 唯一、`app_deployment(app_id, status)`、`app_deployment(tenant_id, create_time)`。**seed 不写在 revision 里**（档位 seed 归 T015 的 `init_default_data`，幂等按 `code`）。
  **回滚**: `downgrade()` 按 `app_deployment → resource_tier` 顺序 drop（无外键，仍按此序）；**回滚前提**：`app_version.tier_id` 会变成悬空引用 → downgrade 前须确认无托管应用在运行，说明写进 revision docstring。
  **依赖**: T001, T002

- [x] **T004**: `[MVP-核心]` 错误码 162 段 + 三语 `api_errors`
  **文件**: `src/backend/bisheng/common/errcode/app_publish.py`（新，**勿写进 F054 的 `app_factory.py`**）, `src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`（三语视为一组）
  **逻辑**: 按 design §4.2 ⑧ 定义 `AppPublishError(BaseErrorCode)` 家族：`16201` 包超上限 · `16202` 包解析失败 / 非法路径条目 · `16203` 缺 `bisheng-app.yaml` · `16205` 该应用归属他人 · `16207` 工场运行时层未启用 · `16221` manifest 校验失败 · `16222` `runtime` 不支持 · `16223` 档位不存在或已停用 · `16224` 能力声明引用不可解析 · **`16225` 审批场景未启用** · **`16226` 运行环境容量不足** · `16227` 依赖构建失败 · `16228` 启动探活失败 · `16229` 结构变更未确认 · `16230` 能力声明含密钥引用（本版不支持）· `16231` 本环境未启用能力总线 · `16241` 密钥扫描命中 · `16251` 已存在在途审批单 · `16252` 待上线态不接受新提交 · `16253` 版本记录不存在 · `16254` 仅 owner 可执行 · `16255` 当前应用态不允许该动作 · `16273` 该能力已被收回（Wave 5 才有写入方，一次登记到位）· `16274` 未在能力声明中的能力 · `16291` 运行期凭据主体不可用。三语文案落 `packages/locales`（生成物 `platform/public/locales/*/api_errors.json` / `client/src/locales/*/api_errors.gen.json` **由脚本生成、不手改**，CI `pnpm check-i18n`）。**不改 `release-contract.md` 与 `constitution.md` 的分配表**（K9：已是对的，改动只制造 diff 噪声）。
  **依赖**: 无

- [x] **T005**: `[MVP-核心]` `settings.app_runtime` 新增五个键
  **文件**: `src/backend/bisheng/core/config/app_runtime.py`（F054 已建的配置块，**增量加字段**）
  **逻辑**: 加 `max_package_mb: int = 50` · `max_unpacked_mb: int = 200` · `max_package_entries: int = 20000`（D2 三闸，**本期就做**——F053 AC-32 要求 CLI 按"部署配置的上限"自查，上限若只是后端常量 CLI 只能硬编码）· `default_tiers: dict | None = None`（档位出厂规格覆盖，AC-44「规格初始默认值为部署配置项」）· `preview_ttl_days: int = 7`（决议-5，Wave 4 才消费，一次加到位避免二次改同一文件）。**一律挂进 F054 已开的 `app_runtime` 块、不开顶层键**（K10）。
  **⚠️ 部署顺序**（`common/services/config_service.py:91-107` 对未知顶层键直接 `raise KeyError`）：**先发代码 → 再改 `config.yaml` → 再重启**，顺序反了直接拒启。写进 T049 的部署清单。
  **依赖**: 无

- [x] **T006**: `[MVP-核心]` 审计事件族 `app.release.*` 后端 lockstep 登记
  **文件**: `src/backend/bisheng/database/models/audit_log.py`（`_UI_VISIBLE_V2_ACTIONS`，元组 `:193`–`:259`）
  **逻辑**: 追加 design §4.2 ⑥ 的全部 action：`app.release.{submit, precheck_failed, scan_blocked, version_created, approval_created, approval_exception, self_approval, approved, rejected, withdrawn, cancelled, online, pending_online, manual_publish, capability_declared, rollback}`（后两者本轮写入方少但**一次登记到位**，避免二次改同一处）。**`_V2_NAMESPACE_TO_ACTION_PREFIX` 的 `"app": "app."` 已由 F054 落码建好（`:266`），不要重复建命名空间**。**不在 `app.publish.*` 前缀下追加**——F054 已把 `app.publish` 用作"上线动作"的 action 名，同前缀混用会让审计筛选与命名空间映射两头别扭（D12）。
  **⚠️ 四处 lockstep 缺一即"写库了但审计页看不到"**（坑 21）：本任务是第 1 处；第 2–4 处（platform `controllers/API/log.ts` 的 `actions` / `getModulesApi` + `bs.json` 三语的 `log.systemIdEnum` / `log.eventTypeEnum`）在 **T045**，**必须与本任务同 PR**。
  **依赖**: 无

- [x] **T007**: `[MVP-核心]` pytest 基础设施 `test/app_publish/conftest.py`
  **文件**: `src/backend/test/app_publish/conftest.py`（新）, `src/backend/test/app_publish/fixtures/minimal_app/`（新，最小可用应用包素材：`bisheng-app.yaml` + `main.py` + `requirements.txt`）
  **逻辑**: fixtures：`service_account_principal`（构造 `OpenApiPrincipal`，可参数化 `scopes` 与 `resource_owner_user_id`，F049 T005 的形状）· `owner_user` / `dept_admin_user` / `tenant_admin_user` / `super_admin_user`（**审批人解析矩阵四类身份；`tenant_admin_user` 必须是非超管的真租户管理员**，否则 AC-21 的护栏测不出来）· `app_factory`（复用 F054 conftest 的同名 fixture，直接经 DAO 落 `app` + `app_version`）· `deployment_factory` · **`tier_seed`**（跑一次 T015 的 `seed_resource_tiers()` 落三档；**T008/T009 的 `tier` 解析测试与 T014 共用同一份 seed**，避免两处各造一份档位数据）· `fake_orchestrator`（monkeypatch F054 `orchestrator_client` 的 `build` / `build_status` / `probe` / `admission` / `deploy`，返回 design §4.2 ① 的响应形状，可编程成功 / 容量不足 / 失败三态）· `fake_minio`（monkeypatch `MinioStorage.put_object` / `get_object` 到临时目录，避免单测连真 MinIO）· `tarball_factory`（按参数生成 tar.gz：正常包 / 缺 manifest / 含符号链接 / 含 `..` 穿越 / 含硬链接 / 含设备文件 / 含 FIFO / 超条目数 / 解包超大 / 含密钥样本）· `audit_sink`（捕获 `AuditLogDao.ainsert_v2` 调用）· `approval_env`（跑一次 T027a 的 seed，让 Gate 不抛 `ApprovalScenarioDisabledError`）。**autouse fixture 清 `HTTP(S)_PROXY` / `ALL_PROXY` env**（缺 `socksio` 会整批误报 ERROR，memory `reference_local_backend_pytest_socks_proxy`）。fixture 体内**惰性 import** 业务 Service，避免尚未落地的模块让整包收集失败。
  **依赖**: T001, T002

---

### Wave 2 · `[MVP-核心]` 管线服务（Test-First 成对）

- [ ] **T008**: `[MVP-核心]` AppManifest 校验矩阵测试
  **文件**: `src/backend/test/app_publish/test_app_manifest.py`（新）
  **逻辑**: 断言 `AppManifest` 的解析与拒绝矩阵，以及失败五元组 `{stage, code, message, details, hints}` 的结构（AC-11 的唯一形态）。
  **测试**: `test_missing_required_name_runtime_port_each_rejected`（三个必填项各缺一次 → `16221` 且 `details` 逐字指出缺哪个字段）→ AC-07, AC-11 / `test_unknown_field_rejected_with_suggestion`（`extra='forbid'`；`runtimee` → 提示"是不是想写 runtime"）→ AC-07 / `test_runtime_not_in_local_enum_rejected_16222` → AC-07 / `test_port_out_of_range_rejected` → AC-07 / `test_manifest_version_ahead_hints_upgrade_platform` → AC-07 / `test_yaml_uses_safe_load_rejects_python_object_tag`（`!!python/object` 不得被反序列化）→ AC-07 / `test_tier_absent_defaults_to_light` → AC-46 / `test_tier_unknown_or_disabled_rejected_16223_with_details_reason`（`details.reason ∈ {not_found, disabled}`，**不拆码**）→ AC-46 / `test_capabilities_non_empty_rejected_16231`（MVP 期声明非空即拒并提示「本环境未启用能力总线」，**不静默忽略**，D16）→ AC-07 / `test_secret_reference_rejected_16230` → AC-56 / `test_database_tables_declared_gives_hints_not_reject`（本期允许声明但不建表、只给 `hints`，D3）→ AC-07 / `test_failure_tuple_has_machine_and_human_forms`（`code` + `stage` + `details` 机读、`message` + `hints` 人读）→ AC-11
  **覆盖 AC**: AC-07, AC-11, AC-46, AC-56
  **依赖**: T007, T015（`tier_seed` fixture + `resolve_tier` 已存在）

- [ ] **T009**: `[MVP-核心]` AppManifest schema + 本地引用校验实现
  **文件**: `src/backend/bisheng/app_publish/domain/schemas/app_manifest.py`（新，**AppManifest 权威 schema，release-contract 表 1 归本 Feature**）, `src/backend/bisheng/app_publish/domain/services/manifest_validator.py`（新）
  **逻辑**: pydantic v2 模型 + `extra='forbid'`（D3，零新依赖；`ValidationError.errors()` 的 `{loc,msg,type}` 三元组直接映射 AC-11 双形态）。字段按 design §4.2 ③ 表：必填 `name`(1–64) / `runtime`(枚举) / `port`(1–65535)；可选 `description` / `icon` / `slug` / `tier`(默认 `light`) / `capabilities{models[],knowledge_bases[]}` / `database.tables[]` / `egress.domains[]` / `manifest_version`(默认 1)。`SUPPORTED_RUNTIMES` **本地枚举常量**（MVP 期仅 `python3.11`）——它是 F054 manager `supported_runtimes` 的**副本**，与 manager 的复核**下沉到 T019 的异步段**（同步段不发 RPC，D4）；在常量旁写一行注释「F054 加运行时模板时必须同批改这里」。`manifest_validator`：YAML `yaml.safe_load`（**禁 `full_load` / `unsafe_load`**）→ pydantic → 本地引用校验（`tier` **直接调 T015 的 `ResourceTierService.resolve_tier(code)`** · 能力声明格式 · 密钥引用出现即拒 16230 · `capabilities` 非空即拒 16231）→ 失败一律构造五元组。
  **⚠️ 档位解析只有一份实现**：`manifest_validator` **不得自己再写一遍**"查表 + 判 `enabled` + 拼 `details.reason`"——两份实现必然在 `details.reason ∈ {not_found, disabled}` 的口径上分叉（AC-46 / AC-47 的判据就落在这个字段上）。`resolve_tier` 抛出的 `16223` 原样上抛，`manifest_validator` 只负责包成五元组。
  **测试**: T008 全部通过。
  **覆盖 AC**: AC-07, AC-11, AC-46, AC-56
  **依赖**: T008, T002, T004, **T015**
  **⚠️ 编号 ≠ 执行顺序**：本任务依赖 T014/T015（`ResourceTierService.resolve_tier` + 三档 seed）的产出，实际排在它们之后；编号保留在此只为与 T008 相邻。

- [ ] **T010**: `[MVP-核心]` 包接收、解包安全闸与快照存储测试
  **文件**: `src/backend/test/app_publish/test_package_service.py`（新）
  **逻辑**: 用 `tarball_factory` 造六类恶意条目与三类超限包，断言全部被拒且错误码正确；断言快照键布局与"不整包进内存"。
  **测试**: `test_reject_absolute_path_entry` / `test_reject_dotdot_traversal` / `test_reject_symlink` / `test_reject_hardlink` / `test_reject_device_file` / `test_reject_fifo`（**tar 比 zip 多后四类**，仓内唯一先例 `skill_store.py:171-176 _safe_rel_path` 只防前两类，坑 15）→ 各自 `16202` / `test_reject_over_max_package_mb_16201` → AC-02 / `test_reject_over_max_unpacked_mb`（tar bomb）→ AC-02 / `test_reject_over_max_package_entries` → AC-02 / `test_snapshot_key_layout_matches_f054`（`apps/{app_id}/versions/{version_id}/code.tar.gz`，`version_id` 在**接收时**生成、预检通过后被 `app_version` 复用；**不先写 deployments 键再 server-side copy**——那是幻觉优化，memory `project_linsight_skill_object_storage`）→ AC-02, AC-43 / `test_upload_never_read_into_memory`（断言走 `put_object(file=Path(...))` 而非 `await file.read()`）→ AC-02 / `test_bucket_ensured_idempotently_on_first_use`（`minio_storage.py:291 _init_bucket_conf` **只建 public / tmp 两桶**，坑 14 → `bisheng-apps` 由 `package_service` 自己 ensure；断言首次 `store_package` 会建桶、第二次不重复建、且**不修改 `_init_bucket_conf`**）→ AC-02 / `test_snapshot_immutable_and_retrievable`（快照可完整取回、内容不可改）→ AC-43 / `test_orphan_cleanup_on_next_deploy_same_app`（超 7 天且无 deployment 引用的孤儿键被清；**不起 Beat**，D2）→ AC-02
  **覆盖 AC**: AC-02, AC-43
  **依赖**: T007, T005

- [ ] **T011**: `[MVP-核心]` `package_service` 实现
  **文件**: `src/backend/bisheng/app_publish/domain/services/package_service.py`（新）
  **逻辑**: `store_package(upload, app_id, version_id)`：`UploadFile` **落临时盘后** `put_object(file=Path(...))`（走 `fput_object` + `asyncio.to_thread`，`minio_storage.py:359-407`），键 `apps/{app_id}/versions/{version_id}/code.tar.gz`，桶 `bisheng-apps`（**独立桶，不挂 nginx location、不设匿名策略**——`src/frontend/nginx.conf:49` 的 `location ~ ^(/workspace/bisheng|bisheng|tmp-dir)/` 会把公共桶任意 key 匿名转发出去，K5 / 坑 13）；**桶由 `package_service` 内部 `_ensure_bucket()` 幂等保证**——首次 `store_package` 时 `create_bucket_sync(bucket_name='bisheng-apps')`（存在即 no-op），进程内加一个 `_bucket_ready` 标志避免每次调用都发 `bucket_exists`。**不改 `minio_storage.py:291 _init_bucket_conf`、不挂 lifespan**（坑 14：那里只建 public / tmp 两桶且给 public 桶设了匿名读策略；把 `bisheng-apps` 塞进去等于把独立桶的生命周期绑到共享初始化路径上，还会诱导后人顺手给它加匿名策略——K5 明令禁止）。`safe_extract(tar_path, dest)`：照抄 `skill_store.py:171-176 _safe_rel_path` 拒绝绝对路径与 `..`，**额外拒 `TarInfo.issym() / islnk() / isdev() / isfifo()`**；边解包边累计大小与条目数，越限即中止。`cleanup_orphans(app_id)`：同 `app_id` 前缀下无 `app_version` 行、无 deployment 引用且超 7 天的键删除，**挂在下一次同应用 deploy 的接收阶段顺手做**（不引 Beat，D2）。三闸阈值读 `settings.app_runtime.*`（T005）。
  **测试**: T010 全部通过。
  **覆盖 AC**: AC-02, AC-43
  **依赖**: T010, T005

- [ ] **T012**: `[MVP-核心]` 密钥扫描规则集遍历测试（AC-10 的直接承载）
  **文件**: `src/backend/test/app_publish/test_secret_rules.py`（新）
  **逻辑**: **遍历 `SECRET_SCAN_RULES` 元组**，每条规则一个正样本（必须命中）+ 一个反样本（必须不命中）——AC-10「规则集内样本 100% 被阻断」由这个遍历式单测直接承载，**新增规则时忘了加样本 = 测试红**。
  **测试**: `test_every_rule_has_positive_and_negative_sample`（元组驱动，规则数 == 样本对数）→ AC-10 / `test_every_positive_sample_blocks_publish` → AC-10 / `test_output_never_contains_secret_value`（把扫描结果 JSON 序列化后断言**不含样本密钥子串**，连脱敏值都不给）→ AC-10 / `test_bs_sak_rule_follows_key_prefix_constant`（规则由 F049 `api_credential.KEY_PREFIX` / `KEY_SECRET_LENGTH` **拼出**，改常量后规则自动跟随；C6 禁硬编码字面量）→ AC-10 / `test_db_conn_string_requires_user_and_password`（只有 host 的连接串是正常配置、不得命中）→ AC-10 / `test_generic_high_entropy_skips_placeholders`（`your_key` / `<...>` / `${…}` / `change_me` / `example` 白名单）→ AC-10 / `test_binary_file_skipped_by_null_byte_sniff` → AC-10 / `test_large_file_marked_skipped_not_silent`（单文件 > 1 MiB 跳过并在结果里标 `skipped`——**大文件被静默跳过等于假通过**）→ AC-10 / `test_hit_report_shape_is_file_and_line_only`（`{rule_id, name_i18n_key, file, line}`）→ AC-10, AC-11
  **覆盖 AC**: AC-10, AC-11
  **依赖**: T007

- [ ] **T013**: `[MVP-核心]` `secret_scanner` 实现
  **文件**: `src/backend/bisheng/app_publish/domain/services/secret_scanner.py`（新）
  **逻辑**: `SECRET_SCAN_RULES: tuple[SecretRule, ...]` 常量表（形态同 `open_api/domain/scopes.py:66-185 OPEN_API_SCOPES`），`SecretRule(rule_id, name_i18n_key, pattern: re.Pattern, description_i18n_key)`。首批规则见 design D5：`bs_sak`（**引 F049 常量拼**）· `aws_akid` · `openai_sk` · `private_key_pem` · `db_conn_string`（用户名密码都在串里才算命中）· `generic_high_entropy`（带占位符白名单）。`scan_package(root) -> ScanResult`：逐文件；跳过 `.git/` / `node_modules/` / `venv/` / `__pycache__/` / `dist/` / `build/`；二进制嗅探（前 8KB 含 `\x00` 即跳过）；单文件 > 1 MiB 标 `skipped`。命中 → `16241` 阻断，`hits: [{rule_id, name_i18n_key, file, line}]`——**永不含值**（AC-10 硬承诺）。**不引 `detect-secrets` / `gitleaks`**（全仓零先例 + 规则集不可控，D5）；**不做行级抑制机制**（一开就会被用来绕过，design §8）。**本常量是 AC-10「与平台内发布同一规则集」的落地手段**——PRD-2 平台内发布直接复用它，只有一份（§6.1 Outgoing）。
  **测试**: T012 全部通过。
  **覆盖 AC**: AC-10, AC-11
  **依赖**: T012, T004

- [ ] **T014**: `[MVP-核心]` `ResourceTierService` 测试（seed / 选档 / 停用 / 无删除）
  **文件**: `src/backend/test/app_publish/test_resource_tier_service.py`（新）
  **逻辑**: 断言三档 seed 的幂等与数值来源、选档解析、停用语义与"不可删"不变量。
  **测试**: `test_seed_creates_three_platform_level_tiers`（轻量 1C/2G · 标准 2C/4G · 性能 4C/8G；**无 `tenant_id` 列、跨租户共享**）→ AC-44 / `test_seed_values_come_from_f054_default_tiers_constant`（seed 从 F054 `DEFAULT_TIERS` 读取落库，保证"表未落"与"表刚 seed 完"两个时刻规格恒等）→ AC-44 / `test_settings_default_tiers_overrides_constant`（`settings.app_runtime.default_tiers` > 常量；**114 必须用它把 `light` 下调**，坑 27）→ AC-44 / `test_seed_idempotent_by_code_does_not_reset_admin_edits`（跑两次不重复；超管改过的规格不被升级重置，与 AC-19 同判据）→ AC-44 / `test_manifest_without_tier_resolves_light` → AC-46 / `test_unknown_tier_rejected_16223_reason_not_found` → AC-46 / `test_disabled_tier_rejected_16223_reason_disabled` → AC-46, AC-47 / `test_disabled_tier_existing_apps_keep_running_and_resolve_spec`（停用**只拦新选择**，存量版本仍可解析规格）→ AC-47 / `test_dao_has_no_delete_method`（**不可删是 F054 可依赖的不变量**：`tier_id` 永远可解析）→ AC-47 / `test_tier_code_written_into_version_snapshot_spec_read_at_runtime`（快照记**档位标识**、规格取运行时当前值 → 规格调整自下一次发布 / 重新启用生效）→ AC-48 / `test_tier_in_use_app_count_counts_online_versions_only`（**仅为 Wave 7 的 T065 预置计数口径，不计入本任务的 `覆盖 AC`**；AC-45 的承载任务是 T065 / T066，追溯表以那两条为准）
  **覆盖 AC**: AC-44, AC-46, AC-47, AC-48
  **依赖**: T007, T002

- [ ] **T015**: `[MVP-核心]` `ResourceTierService` + 三档 seed 实现（含回写 F054 常量）
  **文件**: `src/backend/bisheng/app_publish/domain/services/resource_tier_service.py`（新）, `src/backend/bisheng/common/init_data.py`（`init_default_data` 内加档位 seed 调用）, `src/backend/bisheng/app_runtime/domain/constants.py`（**回写 F054 `DEFAULT_TIERS`**）
  **逻辑**: `seed_resource_tiers()`：优先级 `settings.app_runtime.default_tiers`（T005）> F054 `DEFAULT_TIERS` 常量；**幂等按 `code` 存在即跳过**。`resolve_tier(code | None) -> ResourceTier`：`None` → `light`；不存在或 `enabled=False` → `16223`（`details.reason ∈ {not_found, disabled}`，**不拆码**）。`list_tiers()` / `update_tier(code, patch)`（Wave 7 的管理 tab 消费）/ `count_apps_using(tier_id)` = `SELECT COUNT(DISTINCT app_id) FROM app_version WHERE tier_id=? AND terminal_state='online'`。**无 delete**（D11）。
  **跨 Feature 回写**（design §8 回写项 1）：F054 `DEFAULT_TIERS` 现为 `0.5 vCPU/512 MiB · 1/1024 · 2/2048「增强」`，与本 spec **AC-44** 的 `1C/2G · 2C/4G · 4C/8G「性能」` 数值与命名皆冲突（坑 27）→ **以本 spec 的产品口径为准**，改数值 + 第三档名「增强」→「性能」，并把 F054 design D11「何时重新考虑」里的"支持删档"改为"档位只可停用不可删"。**改常量不影响存量表**（seed 幂等按 `code` 跳过）。
  **测试**: T014 全部通过。
  **覆盖 AC**: AC-44, AC-46, AC-47, AC-48
  **依赖**: T014, T005

- [ ] **T016**: `[MVP-核心]` `VersionService` 测试（写入时点 / 终态标注 / 派生显示 / 补偿）
  **文件**: `src/backend/test/app_publish/test_version_service.py`（新）
  **逻辑**: 断言"先 Gate 后 INSERT"的写入时点、`terminal_state` 四取值、"待上线"是派生显示不是列值、并发兜底与补偿路径。
  **测试**: `test_version_row_only_created_after_precheck_and_scan_pass`（预检 / 扫描失败的提交**不进版本列表**，只在 `app_deployment` 留记录，决议-9）→ AC-02 / `test_version_row_created_after_gate_not_before`（Gate 会抛「场景未启用」→ 先 INSERT 会留一条永远没有终态也没有审批单的僵尸版本，D6-B 的致命缺陷）→ AC-02 / `test_gate_exception_approver_empty_still_inserts_version`（`decision=EXCEPTION` 也算"已进入审批流"，否则管理员处理完异常后没有对象可上线）→ AC-18 / `test_gate_raises_scenario_disabled_marks_deployment_failed_16225_no_version` → AC-02 / `test_compensation_cancels_approval_when_insert_fails`（Gate 自带写库与 commit、**不能与 INSERT 同事务** → 显式两阶段补偿：`cancel_instance_by_business` + deployment failed + 审计 `app.release.rollback`）→ AC-02 / `test_version_no_is_max_plus_one_with_unique_constraint`（`UNIQUE(app_id, version_no)` 兜并发）→ AC-40 / `test_kind_initial_vs_iteration` → AC-39 / `test_terminal_state_only_four_values`（`online` / `rejected` / `withdrawn` / `NULL`；**F055 不给它加过程值**）→ AC-39 / `test_pending_online_is_derived_display_not_column`（`terminal_state IS NULL ∧ app.pending_version_id == version.id` → 显示「待上线」；存在在途审批单 → 显示「待审」）→ AC-39 / `test_manual_publish_flips_null_to_online_without_new_row`（决议-6）→ AC-39 / `test_app_deleted_cancel_keeps_terminal_state_null`（不引入第五个取值）→ AC-39 / `test_mark_terminal_state_is_the_only_update_writer`（`app_version` 唯一被 UPDATE 的列、唯一写入函数）→ AC-40 / `test_version_row_never_deleted` → AC-40 / `test_read_by_version_id_requires_app_scope`（**`app_version` 无 `tenant_id`**，登记进 `_TENANT_AWARE_MODEL_MODULES` 也不受自动过滤 → 按 `version_id` 起手必须先借道 `app` 行校验归属，坑 19）→ AC-40 / `test_snapshot_retrievable_and_immutable_for_any_version` → AC-43
  **覆盖 AC**: AC-02, AC-18, AC-39, AC-40, AC-43
  **依赖**: T007, T011

- [ ] **T017**: `[MVP-核心]` `VersionService` 实现
  **文件**: `src/backend/bisheng/app_publish/domain/services/version_service.py`（新）
  **逻辑**: `insert_version(deployment, approval_instance_id | None)`：`version_no = MAX(version_no)+1 WHERE app_id=?` 在同一事务内取；`kind` = `initial`（该 app 首条）/ `iteration`；写 `code_object_key` / `manifest` / `capabilities` / `injections` / `tier_id`（**四者同属一个快照**，F054 AC-02 已定"任何写入方不得只改其一"）。`mark_terminal_state(app_id, version_id, state)`：**唯一被授权 UPDATE `terminal_state` 的函数**（F054 D8 的只增不改例外），单行带前态断言。`derive_display_state(app, version)`：派生「待上线」/「待审」，**不落库**。`get_snapshot(app_id, version_id)`：经 `package_service` 取回 tar（供审读视图 / 预览拉起 / 将来回滚）。**每个按 `version_id` 起手的方法签名强制带 `app_id`**（坑 19）。
  **测试**: T016 全部通过。
  **覆盖 AC**: AC-02, AC-18, AC-39, AC-40, AC-43
  **依赖**: T016, T011

- [ ] **T018**: `[MVP-核心]` 托管预检编排测试（线性 fail-fast + 五元组）
  **文件**: `src/backend/test/app_publish/test_precheck_service.py`（新）
  **逻辑**: 用 `fake_orchestrator` 编程构建 / 探活的成功与三类失败，断言阶段序、fail-fast 与失败五元组。
  **测试**: `test_stage_order_manifest_build_probe_then_scan`（**spec AC-01 / F053 AC-31a 的字面顺序**；扫描提前是待 ★ 确认的偏离，**不得在此实现**）→ AC-07 / `test_fail_fast_stops_at_first_failing_stage`（manifest 层内部一次性报全，跨阶段 fail-fast）→ AC-07 / `test_manifest_stage_makes_no_rpc`（同步段不发任何 RPC——manager 不可达就会把 `deploy` 变成挂在超时上的请求，D4/D1-C 的兑现）→ AC-07 / `test_runtime_rechecked_against_manager_in_async_stage_16222`（本地枚举与 manager `supported_runtimes` 取交，复核在 `precheck_build` 起手）→ AC-07 / `test_build_capacity_shortage_is_16226_not_16225`（**一码一义红线**：16225 专归"审批场景未启用"）→ AC-07 / `test_build_failure_16227_carries_manager_stage_message_tail` → AC-07, AC-11 / `test_probe_failure_16228_with_hosting_contract_hints`（AC-08 的判据**下沉为探活失败**：本轮不做静态依赖分析，`hints` 给"平台不提供自带数据库 / 消息队列 / 缓存；数据请改接 `BISHENG_APP_DB_URL`"）→ AC-08 / `test_egress_domains_format_only_this_round` → AC-08 / `test_failure_shape_is_five_tuple_in_all_stages` → AC-11 / `test_precheck_failure_produces_no_approval_and_no_version`（AC-07 的硬承诺）→ AC-07
  **覆盖 AC**: AC-07, AC-08, AC-11
  **依赖**: T009, T013, T015
  **⚠️ 编号 ≠ 执行顺序**：本任务依赖 T009 / T013 / T015 三个实现任务的产出（`manifest_validator` / `secret_scanner` / `ResourceTierService` 接口），故实际排在它们之后；编号保留在此只为与 T019 相邻。

- [ ] **T019**: `[MVP-核心]` `precheck_service` 实现
  **文件**: `src/backend/bisheng/app_publish/domain/services/precheck_service.py`（新）
  **逻辑**: 线性 fail-fast 阶段机（design D4 阶段表）：① `precheck_manifest`（**同步段**：YAML + pydantic，16221/16203）② `precheck_manifest`（**同步段**：本地可判的引用校验——`runtime` ∈ 本地枚举常量 · `tier` 查本地表 · 能力声明格式 · 密钥引用，16222/16223/16224/16230/16231）③ `precheck_build`（**异步段**：起手 `GET /v1/runtime/status.supported_runtimes` 复核 `runtime` → `POST /v1/intents/build` → 轮询 `GET /v1/builds/{id}`；容量不足 **16226**、失败 16227）④ `precheck_probe`（异步段：`POST /v1/intents/probe` 临时形态，不占实例名额，16228）。失败原因恒为 `{stage, code, message, details, hints[]}` **五元组**，同一结构同时出现在 CLI 轮询返回、发布面审批状态区、`app_deployment.failure` 落库（AC-11）。**编排器一律经 F054 `orchestrator_client` 门面**，backend 零 docker 依赖。
  **测试**: T018 全部通过。
  **覆盖 AC**: AC-07, AC-08, AC-11
  **依赖**: T018

- [ ] **T020**: `[MVP-核心]` 管线同步前段 `accept()` 测试（归属 / 两道闸 / 首发建草稿）
  **文件**: `src/backend/test/app_publish/test_pipeline_accept.py`（新）
  **逻辑**: 断言同步前段的顺序与每个拒绝分支；断言首发建草稿应用走 F054 而非直写 `app` 表。
  **测试**: `test_first_deploy_creates_draft_app_via_f054_create_app`（**F055 不得直写 `app` 表**，决议-8；owner = 密钥所属服务账号的 `resource_owner_user_id`）→ AC-01, AC-04 / `test_iteration_deploy_requires_owner_match_else_16205`（迭代只对该归属人 owner 的应用放行，含租户管理员名下服务账号的密钥）→ AC-04 / `test_owner_read_from_resource_owner_user_id_not_subject_user_id`（坑 28）→ AC-04 / `test_active_approval_blocks_new_submit_16251`（**断言不是"静默返回既有实例"**——Gate 的重复提交拦截是静默返回，AC-03 必须在**调 Gate 之前**自查，K2 ① / 坑 8）→ AC-03 / `test_pending_online_state_blocks_new_submit_16252`（提示"须先手动上线或删除"）→ AC-03 / `test_deployment_row_created_with_stage_received` → AC-01 / `test_version_id_generated_at_accept_and_reused_by_version_row` → AC-02 / `test_meta_not_updated_at_accept`（元信息在**预检 + 扫描通过后**才更新，失败不更新，AC-05）→ AC-05 / `test_retry_deploy_reuses_same_app_id_not_new_draft`（CLI 把 app_id 随项目保存，重试复用，D2-B 的代价控制）→ AC-01 / `test_accept_returns_deployment_id_within_seconds_no_rpc` → AC-01
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05
  **依赖**: T011, T017
  **⚠️ 执行顺序（Wave 编号 ≠ 拓扑序）**：本任务与 T021 / T022 / T023 依赖 T031（在途闸 / 待上线闸 / Gate 提交都落在 `publish_approval_service`，Wave 3.2），而 T031 → T030 → T029 → T028 → T027a/T027b → T025 整条链都在 Wave 3 —— **实际执行序见「开发模式 · 跨 Wave 执行序」：Wave 3.1–3.2 先跑完再回来做 T020–T023**。测试可先落盘（红测即预期），实现一律按 `依赖:` 排。

- [ ] **T021**: `[MVP-核心]` `publish_pipeline_service.accept()` 实现（同步前段）
  **文件**: `src/backend/bisheng/app_publish/domain/services/publish_pipeline_service.py`（新，本任务只落 `accept()`）
  **逻辑**: 按 design §4.1-A ① 的顺序：归属判定（`principal.resource_owner_user_id == app.owner_user_id`，否 → 16205）→ 大小闸 → 落临时盘 → `put_object` 到 `bisheng-apps` → 解包安全闸 + 解包大小闸 + 条目数闸 → 读 `bisheng-app.yaml` → `manifest_validator`（T009）→ 本地引用校验 → **首发**：调 F054 `AppStateService.create_app(manifest, owner_user_id, tenant_id)` 建草稿应用（**不直写 `app` 表**）→ 在途审批单闸（16251）/ 待上线态闸（16252）→ INSERT `app_deployment(stage=received, status=running)` → `apply_async` 后段 → 返回 `{deployment_id, app_id, version_id}`。**本段绝不发任何编排器 RPC**（D1-C 的兑现：秒级错误秒级回）。审计 `app.release.submit`。
  **测试**: T020 全部通过。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05
  **依赖**: T020, T031

- [ ] **T022**: `[MVP-核心]` 管线异步后段阶段机测试（阶段推进 / 元信息 / 审计）
  **文件**: `src/backend/test/app_publish/test_pipeline_run.py`（新）
  **逻辑**: 断言 `run_pipeline` 的阶段推进、每阶段一条审计、元信息更新时点与失败终止。
  **测试**: `test_stage_advances_one_row_update_per_stage` → AC-01 / `test_each_stage_writes_one_app_release_audit_with_app_id_and_version_no`（metadata 恒带 `app_id` / `version_no` / `deployment_id`；`target_type='app_version'`——**审批族审计的 `target_type` 恒为 `approval_instance`，按"对象=应用"筛不到**，坑 20）→ AC-01 / `test_scan_hit_terminates_pipeline_16241_no_version_no_approval` → AC-02, AC-10 / `test_precheck_failure_terminates_and_persists_failure_tuple` → AC-02, AC-11 / `test_meta_updated_after_precheck_and_scan_pass_not_awaiting_approval`（调 F054 `AppMetaService.update_meta`，**F055 不另写一份更新逻辑**）→ AC-05 / `test_icon_extracted_from_package_and_stored_as_minio_object_name`（**断言 `app.logo` 落的是公共桶 object_name `icon/{uuid}.png`**，既不是包内相对路径〔写进去图标全站不显示〕，也不是 `/upload/icon` helper 返回的 `file_path`〔那是 **7 天过期的预签名 URL**，一周后全站图标 403，坑 16〕；同时断言 >1 MiB 或扩展名 ∉ {jpeg,jpg,png} 的图标被跳过并给 `hints`、**不阻断发布**）→ AC-05 / `test_tier_and_capabilities_enter_snapshot` → AC-05, AC-48 / `test_capability_declaration_change_audited_each_release`（`app.release.capability_declared`）→ AC-55 / `test_status_becomes_waiting_approval_after_approval_created` → AC-01 / `test_worker_tenant_context_restored_from_celery_header`（租户 ContextVar 经 header 自动透传，`worker/tenant_context.py:63-90`；断言子租户发布不串租户）→ AC-01
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-10, AC-11, AC-48, AC-55
  **依赖**: T019, T021

- [ ] **T023**: `[MVP-核心]` `run_pipeline()` 实现 + Celery 任务
  **文件**: `src/backend/bisheng/app_publish/domain/services/publish_pipeline_service.py`（**增量**加 `run_pipeline()`，不改 T021 已落的 `accept()`）, `src/backend/bisheng/worker/app_publish/tasks.py`（新）, `src/backend/bisheng/worker/app_publish/__init__.py`（新，空）, **`src/backend/bisheng/worker/__init__.py`（存量：顶部 `# register tasks` 块追加 `from bisheng.worker.app_publish.tasks import run_publish_pipeline`）**
  **逻辑**: `run_pipeline(deployment_id)`：`precheck_build → precheck_probe → secret_scan → update_meta（含图标）→ approval_created`（**spec 字面顺序**，扫描提前是待 ★ 确认的偏离，勿自行调换）。每次阶段推进 = 一次 `app_deployment` 单行 UPDATE + 一条 `app.release.*` 审计。
  **⚠️ Celery 任务必须显式登记**（否则整条异步后段永不执行）：celery app 是 `Celery("bisheng", include=["bisheng.worker"])`（`worker/main.py:22`），**只 import 包、不扫子模块** → 任务全靠 `worker/__init__.py` 顶部 `# register tasks` 的显式 import 块注册（`admin_scope` / `approval`（outbox）/ `knowledge` / `workflow` 全在那里）。漏这一行的现象是**最难定位的形态**：`apply_async` 正常返回、`deploy` 报成功、worker 侧 `NotRegistered`、114 上表现为「状态永远卡在 `received`」且后端日志无异常。落码后自检：`uv run celery -A bisheng.worker.main:bisheng_celery inspect registered | grep app_publish`。
  **元信息更新（含图标落地，AC-05）**：调 F054 `AppMetaService.update_meta(app_id, name/description/slug)`；**图标由本任务负责落地**（design D12）——从已解包目录按 `manifest.icon` 相对路径取字节 → 校验 ≤ 1 MiB 且扩展名 ∈ {jpeg, jpg, png} → `MinioStorage.put_object(bucket=public_bucket, object_name=f"icon/{uuid4()}.png", ...)` → 把 **object_name**（不是预签名 URL、不是包内相对路径）写进 `app.logo`。**校验不过只跳过图标 + 记 `hints`，不阻断发布**（图标是元信息、不是发布前提）。终止时写 `failure` 五元组 + `status=failed`。审计写法：`AuditLogDao.ainsert_v2(...)`——该方法**内部自带 `bypass_tenant_filter()` + 独立 session + commit**，调用方**不需要也不应该**再包事务；写失败会抛，用 `approval_outbox_service.py:105-121` 的"审计失败不影响主流程"包法。
  **Worker / tenant_id**: Celery 任务 `bisheng.worker.app_publish.tasks.run_publish_pipeline(deployment_id)`，**走默认 `celery` 队列**（与审批 outbox 同队列，114 已有 default worker；**不新建队列**，D1）。`tenant_id` 由 `accept()` 侧 `apply_async` 时经 **Celery header 自动透传**（`worker/tenant_context.py:63-90`），worker 内**不需要**手动 `set_current_tenant_id`；但任务体第一行须断言 `current_tenant_id` 非空并记日志（无 header 时框架兜底 `DEFAULT_TENANT_ID`，静默串租户是最坏形态）。
  **可观测**: 结构化日志 `app_publish.pipeline`（`deployment_id / app_id / stage / status / duration_ms / failure_code`，**每阶段一条**）与 `app_publish.scan`（`files_scanned / files_skipped / hits`，**不含命中值**）。
  **测试**: T022 全部通过。
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-10, AC-11, AC-48, AC-55
  **依赖**: T022, T031

---

### Wave 3 · `[MVP-核心]` 预置审批流、三项阻塞前置、终态与上线、权限判定、前端最小面、`withdraw` 守卫

#### 3.1 三项阻塞前置（**存量代码行为变更**）

- [ ] **T024**: `[MVP-核心]` `tenant_admin` 来源修正 + Root 回退测试（含既有场景回归护栏）
  **文件**: `src/backend/test/app_publish/test_approver_source_fix.py`（新）
  **逻辑**: 断言 `tenant_admin` 来源从"全站系统超管"改为"当前租户的真实租户管理员"，Root 租户回退平台超管；**并回归既有两个场景**——这是行为变更的护栏。
  **测试**: `test_tenant_admin_source_resolves_real_tenant_admins_not_super_admin`（今天 `approver_resolver.py:63-74` 解析的是 `UserRoleDao.aget_roles_user([AdminRole])` 全站超管、与 `req.tenant_id` 完全无关，注释自认 "pragmatic approximation"，坑 1）→ AC-21 / `test_sub_tenant_admin_only_sees_own_tenant_approvals`（多租户下不再全压超管一人）→ AC-21 / `test_root_tenant_falls_back_to_super_admin`（`TenantAdminService.list_tenant_admins` 对 Root 租户**恒返回 `[]` 是显式设计不是 bug**，`tenant_admin_service.py:95-96`；114 单租户形态**必然**命中此分支）→ AC-15 / `test_non_root_tenant_with_no_admin_does_not_fallback`（非 Root 无租户管理员且来源①亦空 → 走异常态，不叠加任何额外兜底）→ AC-15 / `test_existing_channel_scenario_still_resolves_approvers`（**行为变更护栏**）→ AC-21 / `test_existing_knowledge_space_scenario_still_resolves_approvers` → AC-21 / `test_notification_recipient_function_unchanged`（**断言 `approval_notification_service.py:122-152 _get_admin_recipient_ids` 一行未改**——它是**无条件 union**、语义与条件回退不同，合并的两种错法各自致命，坑 2）→ AC-21
  **覆盖 AC**: AC-15, AC-21
  **依赖**: T007

- [ ] **T025**: `[MVP-核心]` `approver_resolver` 修正实现（**跨 Feature 行为变更**）
  **文件**: `src/backend/bisheng/approval/domain/services/approver_resolver.py`（存量改动）
  **逻辑**: 顶部**新增函数** `resolve_tenant_admin_user_ids(tenant_id) -> list[int]`：`ids = await TenantAdminService.list_tenant_admins(tenant_id)`；`if not ids and tenant_id == ROOT_TENANT_ID: ids = AdminRole 用户`。把 `tenant_admin` 分支的 `UserRoleDao.aget_roles_user([AdminRole])` 换成它。
  **⚠️ 三条不得违反的边界**：① **绝不与 `_get_admin_recipient_ids` 合并**——那个是通知侧的**无条件 union**（任何租户都并入全站超管），拿它做审批人解析等于把 AC-21 要修的缺陷原样搬过来；反过来改它则悄悄改掉审批异常态的管理员通知收件人（坑 2）。② **不用 `TenantService._get_tenant_admin_users`**——private、分页上限 100、返回 dict 且**含 super_admin**（`tenant_service.py:771/780-790`）；`list_tenant_admins`（`tenant_admin_service.py:90-106`）是干净公共 API、返回 `list[int]`、权限后端异常 `return []`（fail-closed 成空 → 走 approver_empty 异常态，正合 AC-18）。③ **不在这里做申请人过滤**（那是场景 handler 的出口过滤，塞进公共解析器会污染频道 / 知识空间两个既有场景）。
  **跨 Feature 副作用**: **对一切使用 `tenant_admin` 来源的既有场景与人工配置立即生效**（AC-21）→ **release note 必须显著声明**；T024 的两条回归测试是护栏。同 PR 更新 `.claude/skills/approval-module/SKILL.md`（T050）。
  **测试**: T024 全部通过。
  **覆盖 AC**: AC-15, AC-21
  **依赖**: T024

- [ ] **T026**: `[MVP-核心]` 审批场景 seed 参数化与新建租户钩子测试
  **文件**: `src/backend/test/app_publish/test_approval_seed.py`（新）
  **逻辑**: 断言「应用发布」场景随部署即存在、可被人工改配后不被升级重置、且**两条**新建租户路径都会落库。
  **测试**: `test_fresh_deploy_has_app_publish_scenario_enabled`（全新部署未做任何配置直接发布即可生成审批单）→ AC-12 / `test_seed_shape_single_catchall_route_single_or_node`（`ApprovalScenario(enabled=True)` → `ApprovalFlowDefinition(is_active=True)` → `ApprovalFlowVersion(version_no=1,is_active=True)` → `ApprovalNodeDefinition(node_order=1,node_mode='or')` → `ApprovalRouteRule(route_type='flow', match_config={})`；**`match_config={}` 就是 catch-all**，`approval_gate.py:443-445` 无 field 直接返回该 route）→ AC-12 / `test_sources_are_department_admin_and_tenant_admin` → AC-12 / `test_seed_idempotent_by_tenant_and_scenario_code`（**按 `tenant_id + scenario_code` 存在即 `continue`** = AC-19「平台升级不重置人工改动」的落地）→ AC-19 / `test_manual_reconfig_survives_reseed` → AC-19 / `test_create_tenant_path_seeds_scenario`（`TenantService.acreate_tenant`，**管理后台主路径**）→ AC-20 / `test_mount_child_path_seeds_scenario`（`TenantMountService.mount_child`）→ AC-20 / `test_seed_failure_does_not_break_tenant_creation`（照 `tenant_service.py:140-149` 的 `seed_builtin_skills` 形状：`try/except` + `logger.warning`）→ AC-20 / `test_menu_access_scenario_not_touched`（**不顺手扩到 menu_access**，那是另一条产品决策）→ AC-19
  **覆盖 AC**: AC-12, AC-19, AC-20
  **依赖**: T007

- [ ] **T027a**: `[MVP-核心]` seed 参数化 + 「应用发布」场景条目（**不碰 Tenant 领域**）
  **文件**: `src/backend/bisheng/approval/domain/services/approval_seed_service.py`（新，对外暴露 `seed_approval_scenarios_for_tenant(tenant_id)`）, `src/backend/bisheng/common/init_data.py`（`_init_default_approval_scenarios(session)` → `(session, tenant_id)`，**六处硬编码 `DEFAULT_TENANT_ID`**（`:365/374/384/402/414/425`）改参数）
  **逻辑**: 新增 seed 条目 `{scenario_code:'app_publish_request', scenario_name:'应用发布', sources:[{"type":"department_admin"},{"type":"tenant_admin"}]}`，落 5 行（形态见 T026）。幂等判据**不动**（按 `tenant_id + scenario_code`）。`init_data.py` 的 `init_default_data()` 仍按 `DEFAULT_TENANT_ID` 调一次（行为不变）。
  **⚠️ 签名变更需全量 grep 调用方**：`_init_default_approval_scenarios` 加参数后，**先 `grep -rn "_init_default_approval_scenarios\|seed_approval_scenarios" src/backend/`** 确认全部调用点都传了 `tenant_id`；六处 `DEFAULT_TENANT_ID` 改参数时逐处核对——漏改一处的现象是"某类 seed 行永远落在默认租户"，不报错。
  **测试**: T026 中除两条路径钩子外的全部用例通过（`test_fresh_deploy_has_app_publish_scenario_enabled` / `test_seed_shape_*` / `test_sources_are_*` / `test_seed_idempotent_*` / `test_manual_reconfig_survives_reseed` / `test_menu_access_scenario_not_touched`）。
  **覆盖 AC**: AC-12, AC-19
  **依赖**: T026

- [ ] **T027b**: `[MVP-核心]` **两条**租户创建路径挂 seed 钩子（**跨 Feature：改 Tenant 领域，单独 review**）
  **文件**: `src/backend/bisheng/tenant/domain/services/tenant_service.py`（`acreate_tenant` 挂一次）, `src/backend/bisheng/tenant/domain/services/tenant_mount_service.py`（`mount_child` 挂一次）
  **逻辑**: 各**追加**一次 `seed_approval_scenarios_for_tenant(tenant.id)`，形状照抄 `tenant_service.py:140-149` 的 `seed_builtin_skills([tenant.id])`（`try/except` 包住 + `logger.warning`，其注释已明说"startup seeding 只覆盖当时存在的租户"）。**只加这一步、不动创建流程里的任何既有步骤**。
  **⚠️ 两条路径缺一必漏**（坑 3）：`mvp-114-path.md:50` 与 PRD-1 §3.3 锚点表**都只写了 `tenant_mount_service`，口径不全**——`TenantService.acreate_tenant` 才是管理后台主路径，漏它则从管理后台建的租户永远没有发布审批场景，第一次 deploy 就 `ApprovalScenarioDisabledError`，且这类 bug 要等客户建第二个租户才暴露。**本任务之所以从 T027a 拆出来单独提交，就是为了让这两行改动被单独 review 一次。**
  **跨 Feature 副作用**: 改 Tenant 领域（F011 / F012）的创建流程；`seed_builtin_skills` 是同位置的现成先例，review 时逐字比对两者形状是否一致。
  **测试**: T026 的 `test_create_tenant_path_seeds_scenario` / `test_mount_child_path_seeds_scenario` / `test_seed_failure_does_not_break_tenant_creation` 通过。
  **覆盖 AC**: AC-20
  **依赖**: T027a

#### 3.2 审批场景接入（四件套）

- [ ] **T028**: `[MVP-核心]` 场景 handler 测试（审批人解析矩阵 / 申请人 / 自审 / 异常态 / detail 结构）
  **文件**: `src/backend/test/app_publish/test_publish_scenario_handler.py`（新）
  **逻辑**: 覆盖 GOV-02 的全部解析分支与 `detail_snapshot` 结构契约。
  **测试**: `test_gate_returns_pending_with_non_empty_approvers_after_seed`（**`resolve_approvers` 由 handler 自己实现**、通用来源要**显式转调** `resolve_approvers_from_sources`；忘了转调的现象与"没配审批人"完全一样、极难定位，坑 9）→ AC-12 / `test_approvers_union_dept_admin_and_tenant_admin_single_or_node` → AC-12 / `test_or_node_first_decision_closes_other_tasks`（任一人处理立即出终态并同步关闭另一方待办）→ AC-13 / `test_owner_without_primary_department_falls_to_tenant_admin`（`UserDepartmentDao.aget_user_primary_department`，**只取主部门、不向上回溯**）→ AC-14 / `test_department_without_admin_falls_to_tenant_admin` → AC-14 / `test_applicant_is_owner_natural_person_not_service_account`（`applicant_user_id = app.owner_user_id`，**不是** `principal.subject_user_id`；服务账号会被自动兜底进 guest 部门，按它解析部门会解析到完全无关的人，坑 28 / INV-29）→ AC-16 / `test_approver_note_marks_no_department_admin_source` → AC-16 / `test_applicant_filtered_out_of_approvers` → AC-17 / `test_self_approval_kept_when_applicant_is_only_candidate_and_audited`（唯一允许"自己批自己"的情形，审计必须标注）→ AC-17 / `test_self_approval_flag_carried_via_handler_instance_attr`（引擎侧**没有通道**——Gate 只取 `list[int]`，`ApprovalGateResult` 只有四字段 → 走 `self.last_self_approval` 实例属性，D7）→ AC-17 / `test_concurrent_two_releases_one_self_one_not_audit_exactly_one_self_approval`（**验证 handler 未被复用**：每次发布请求必须新建 handler 实例，绝不可提成模块级单例，D7）→ AC-17 / `test_both_sources_empty_returns_exception_not_raise`（`decision=EXCEPTION` + 通知管理员，**断言不抛异常**、不放行也不静默卡死，K2 ②）→ AC-18 / `test_detail_snapshot_structured_plus_three_flat_fallback_keys`（`app_name` / `release_kind_text` / `tier_name` 供未识别该场景的旧渲染路径；嵌套子树键须加进前端 `DETAIL_INTERNAL_KEYS`，坑 7）→ AC-24 / `test_detail_snapshot_fields_match_contract`（design §4.2 ④ 字段表逐字段）→ AC-24 / `test_gate_request_has_business_resource_type_and_id`（`ApprovalGateRequest` 的 `business_resource_type='app'` / `business_resource_id=str(app_id)` **是无默认值的必填字段**，漏填 = 构造即 `ValidationError`）→ AC-24 / `test_every_release_generates_approval_no_exemption`（首发与迭代均生成；能力声明与可见范围未变的迭代同样必审；**不存在任何免审配置项**，INV-34）→ AC-23 / `test_approver_resolver_not_modified_by_this_scenario`（申请人过滤只在本场景出口做）→ AC-17
  **覆盖 AC**: AC-12, AC-13, AC-14, AC-16, AC-17, AC-18, AC-23, AC-24
  **依赖**: T025, T027a, T027b

- [ ] **T029**: `[MVP-核心]` 场景 handler 实现 + preset + runtime handler 工厂分支（**四件套之①②③**）
  **文件**: `src/backend/bisheng/app_publish/domain/services/app_publish_scenario_handler.py`（新）, `src/backend/bisheng/approval/domain/services/approval_registry.py`（存量：`with_default_presets()` 加一条 preset）, `src/backend/bisheng/approval/domain/services/approval_runtime_handler_factory.py`（存量：`build_runtime_handler` 加 `app_publish_request` 分支）
  **逻辑**: handler 为**鸭子类型、无 ABC**，完整协议照 `knowledge_space_subscribe_scenario_handler.py:55-157`：`resolve_approvers`（显式转调 `resolve_approvers_from_sources` + AC-17 出口过滤 + `self.last_self_approval` 标志）· `build_title` → 「{应用名} · {首发|迭代} 发布审批」· `build_business_link` → platform 应用详情页发布 tab · `build_detail` → design §4.2 ④ 的**结构化** payload · `on_approved`（T033）/ `on_rejected` / `on_withdrawn` / `on_cancelled`（T035）。
  **preset**: `ApprovalScenarioPreset(scenario_code='app_publish_request', scenario_name='应用发布', handler_key='app_publish_request', approver_source_types=['department_admin','tenant_admin','direct_user'])`。⚠️ **`handler_key` 是无默认值的必填字段**（`approval_center_schema.py:38-43`），漏传会在 `with_default_presets()` 求值时 `ValidationError`、**import 期就崩**。`direct_user` 是为 AC-19「租户管理员可改配审批人」留的。场景名接受**中文单语**（与既有三场景一致，坑 24）。
  **工厂分支**: `approval_runtime_handler_factory.py:17-35` 加分支——**漏加 = 审批通过后应用永远不上线**（`build_runtime_handler` 抛 KeyError → `_record_outbox_task_failure`，K1 ③）。
  **测试**: T028 全部通过。
  **覆盖 AC**: AC-12, AC-13, AC-14, AC-16, AC-17, AC-18, AC-23, AC-24
  **依赖**: T028

- [ ] **T030**: `[MVP-核心]` `publish_approval_service` 测试（Gate 组装 / 前置闸 / 首节点通知 / 草稿不可访问）
  **文件**: `src/backend/test/app_publish/test_publish_approval_service.py`（新）
  **逻辑**: 断言 Gate 的组装范式、两个"静默"语义的调用方兜底、首节点通知自发。
  **测试**: `test_gate_assembled_per_request_with_fresh_registry_and_handler`（范式逐字照 `channel_service.py:1523-1530`：`ApprovalRegistry.with_default_presets()` → `register_handler(...)` → `ApprovalGate(registry=...)`；**引擎本就没有全局单例注册表**，K1 ②）→ AC-23 / `test_active_instance_checked_before_gate_raises_16251`（Gate 命中 `find_duplicate_active_instance` 会**静默返回既有实例**，靠它兜 = CLI 显示"提交成功"但什么都没提交，坑 8）→ AC-03 / `test_pending_online_checked_before_gate_raises_16252` → AC-03 / `test_scenario_disabled_raises_maps_to_16225_not_16226`（一码一义红线）→ AC-23 / `test_first_node_notification_sent_by_us_not_gate`（`approval_gate.py:232-248` 只建 task + 写审计、**不发站内信**，三个既有场景都在自己那侧补发，坑 5）→ AC-64 / `test_business_key_is_deployment_id`（一次发布尝试 = 一个审批单）→ AC-23 / `test_draft_app_not_accessible_before_approval`（首发在审批通过前，除审批人外任何其他用户不可访问——**MVP 期的落点是 F054 `create_app` 的 `authorize_created(protected=True)` 默认仅 owner 可见**；审读视图 / 预览试用两条审批人通道随 Wave 4）→ AC-30
  **覆盖 AC**: AC-03, AC-23, AC-30, AC-64
  **依赖**: T029

- [ ] **T031**: `[MVP-核心]` `publish_approval_service` 实现
  **文件**: `src/backend/bisheng/app_publish/domain/services/publish_approval_service.py`（新）
  **逻辑**: `_build_publish_approval_gate()`（**每次调用新建 registry + handler + Gate**，绝不缓存复用，D7 自审标志的成立前提）· `assert_no_active_release(app_id)`（16251）· `assert_not_pending_online(app_id)`（16252）· `submit(deployment)`：**先 Gate 后 INSERT**（D6-C）——`request_or_pass(business_key=str(deployment_id), applicant_user_id=app.owner_user_id, applicant_department_id=owner 主部门, business_resource_type='app', business_resource_id=str(app_id))` → `PENDING` 或 `EXCEPTION` 都照落版本记录（调 T017）→ Gate **抛异常** → deployment `failed(stage='approval_created', code=16225)` 且不落版本 → 返回 PENDING 后调 `ApprovalNotificationService.notify_users(..., action_code='approval_task_pending', scenario_code='app_publish_request')`（坑 5）→ 读 `handler.last_self_approval` 写审计 `app.release.self_approval`。**补偿**：Gate 成功而 INSERT 失败 → 立即 `cancel_instance_by_business(...)`（T035）+ deployment failed + 审计 `app.release.rollback`（**显式两阶段补偿，不假装原子**）。
  **测试**: T030 全部通过。
  **覆盖 AC**: AC-03, AC-23, AC-30, AC-64
  **依赖**: T030, T017

#### 3.3 审批终态处理与上线终检

- [ ] **T032**: `[MVP-核心]` `on_approved` 三分支测试（待上线不是失败）
  **文件**: `src/backend/test/app_publish/test_on_approved.py`（新）
  **逻辑**: 断言 outbox 语义边界——**产品定义的终态必须正常返回、系统性失败必须抛**。
  **测试**: `test_online_marks_terminal_online_and_notifies_owner` → AC-31 / `test_capacity_shortage_returns_normally_and_sets_pending_capacity`（**必须"正常返回"而不是 raise**——raise 会让 instance 变 `execute_failed` + 建异常 + 通知管理员，产品上是"审批失败了"，与 AC-31 直接矛盾，K3 / 坑 10）→ AC-31 / `test_deploy_failure_returns_normally_and_sets_pending_deploy_failed`（决议-8 的第二种成因）→ AC-31 / `test_approval_instance_stays_approved_in_both_pending_cases` → AC-31 / `test_orchestrator_unreachable_raises`（判据写死为一句：**"应用最终会不会自己好起来"——会就返回，不会就抛**）→ AC-31 / `test_version_not_found_raises_16253` → AC-31 / `test_stopped_app_only_stages_not_publishes`（审批通过仅落为待运行版本、不自动重新启用；重新启用后新版本生效）→ AC-36 / `test_deleted_app_returns_normally_as_race_defense`（删除时已取消审批单，这是竞态兜底）→ AC-35 / `test_stage_version_called_before_publish`（写 `pending_version_id`、不改应用态）→ AC-31 / `test_pending_online_notifies_owner_and_tenant_admin_root_falls_to_super_admin`（**此处是通知不是审批人解析** → 可直接复用 `_get_admin_recipient_ids` 的无条件 union，与 T025 的条件回退是两码事、别混用）→ AC-31, AC-64
  **覆盖 AC**: AC-31, AC-35, AC-36, AC-64
  **依赖**: T029, T017

- [ ] **T033**: `[MVP-核心]` `on_approved` 实现（调 F054 状态动作）
  **文件**: `src/backend/bisheng/app_publish/domain/services/app_publish_scenario_handler.py`（**增量**加 `on_approved`，不改 T029 已落方法）
  **逻辑**: 编排见 design D9：① 取 `app` 与 `app_version`（**按 `version_id` 起手必须先借道 `app` 行校验归属**，坑 19）；应用已删 → 正常返回。② F054 `AppStateService.stage_version(app_id, version_id)`。③ 分派：应用态 ∈ {草稿, 已上线, 待上线} → `publish(app_id, version_id)`；**已停运 → 只 stage 不 publish**（AC-36）；已删除 → 同①。④ `publish` 三结果：`online` → `mark_terminal_state('online')` + 审计 `app.release.online` + 通知 owner；容量不足 → 应用态「待上线（资源不足）」+ 审批单保持通过 + `terminal_state` 保持 `NULL`（派生显示「待上线」）+ 通知 owner + 租户管理员（Root → 平台超管）；拉起 / 探活非容量失败 → 「待上线（上线失败）」+ 同上、成因文案区分。**后两者正常返回**（K3 / 坑 10）。**应用态一律经 F054，F055 不直写**（决议-8）。
  **测试**: T032 全部通过。
  **覆盖 AC**: AC-31, AC-35, AC-36, AC-64
  **依赖**: T032

- [ ] **T034**: `[MVP-核心]` 驳回 / 撤回 / 删除致取消测试
  **文件**: `src/backend/test/app_publish/test_release_terminal_states.py`（新）
  **逻辑**: 三条终态分支各自的版本标注、应用态影响、通知接收方与审计。
  **测试**: `test_reject_marks_version_rejected_and_keeps_app_state`（首发保持草稿态；迭代保持已上线、当前版本继续运行——被驳回**不写** `pending_version_id`，F054 AC-05 天然成立）→ AC-33 / `test_reject_reason_full_text_available_to_owner`（来源 = `approval_task.comment`，经状态只读接口回传）→ AC-33 / `test_resubmit_after_reject_creates_new_approval` → AC-33 / `test_withdraw_marks_version_withdrawn_and_notifies_approvers`（owner-only 由既有 `withdraw_instance` 的 `applicant_user_id` 校验天然成立，`:430`；通知由既有 `withdraw_instance` 负责）→ AC-34 / `test_withdraw_then_resubmit_creates_new_approval` → AC-34 / `test_app_deleted_cancels_active_instance_and_notifies_approvers`（**不能复用 `cancel_exception_api`**——它从 exception 记录起手且通知的是**申请人**，与 AC-35 要求的"通知审批人"相反，坑 6）→ AC-35 / `test_cancel_audit_carries_app_id_and_version_no` → AC-35 / `test_hook_failure_does_not_rollback_delete_and_read_side_still_shows_cancelled`（**F054 已明示钩子失败不回滚删除** → 读侧对"应用已删除"独立判定并按已取消呈现，不把正确性全押在钩子送达上，D10 防御）→ AC-35 / `test_composition_root_registered_in_both_api_and_worker`（组合根注册必须在 API 与 Celery worker **两类进程**都执行；只挂 API lifespan 会在多进程下静默半失效，memory `feedback_multinode_default_assumption`）→ AC-35
  **覆盖 AC**: AC-33, AC-34, AC-35
  **依赖**: T029

- [ ] **T035**: `[MVP-核心]` 终态回调 + `cancel_instance_by_business` + 组合根（**跨 Feature**）
  **文件**: `src/backend/bisheng/app_publish/domain/services/app_publish_scenario_handler.py`（**增量**加 `on_rejected` / `on_withdrawn` / `on_cancelled`）, `src/backend/bisheng/approval/domain/services/approval_center_service.py`（**新增** `cancel_instance_by_business`）, `src/backend/bisheng/app_publish/composition.py`（新，组合根）, **`src/backend/bisheng/main.py`（存量：`lifespan`（`:82`）内调一次 `register()`）**, **`src/backend/bisheng/worker/main.py`（存量：`on_worker_init`（`@celeryd_after_setup`，`:80-87`）内调一次 `register()`）**
  **逻辑**: `on_rejected` → `mark_terminal_state('rejected')` + deployment `failed(stage='approved', code=None)`（区分于预检失败）+ 审计 `app.release.rejected`（`reason` = 驳回理由全文），**应用态不动**。`on_withdrawn` → `mark_terminal_state('withdrawn')` + deployment failed + 审计。`on_cancelled` → 保持 `terminal_state=NULL`（应用整体已删，不需要第五个取值）+ 审计 `app.release.cancelled`。
  **新增审批模块 API** `cancel_instance_by_business(*, instance_id | (scenario_code, business_key), reason, operator_user_id)`：置 instance=CANCELLED + 全部 PENDING task → CANCELLED + 写 `approval_action_log` + 审计 + **通知审批人**（新 action_code `approval_instance_cancelled`）+ 调 handler `on_cancelled`。**放审批模块**（它操作的是审批实体，放 F055 里就是跨模块直写别人的表）；形状通用，将来任何"业务对象消失需取消在途单"的场景直接复用（§6.1）。
  **组合根** `composition.py`：暴露 `register()` —— 注册 F054 `lifecycle_hooks.register_app_deleted_hook(fn)` + 场景 handler；**函数体自身幂等**（重复调用不重复注册），因为它要在两处被调（D16 ⚠️）。
  **⚠️ 两个接线点缺一即静默半失效**（memory `feedback_multinode_default_assumption`）：① `main.py` 的 `lifespan`（`:82`，与 `_register_permission_runtime_contexts()` 同一段，照它的位置放）；② `worker/main.py` 的 `on_worker_init`（`@celeryd_after_setup.connect`，`:80-87`，紧随 `initialize_app_context(..., instance_role="celery")` 之后）。**只挂 API 的形态最坑**：API 进程里手测全对，而审批 outbox 执行、删除钩子这些真正跑在 worker 进程里的路径全都找不到 handler（K1 ③ 原样复现），日志只留一条 `_record_outbox_task_failure`。T034 的 `test_composition_root_registered_in_both_api_and_worker` 是它的护栏。
  **跨 Feature 副作用**: 新增审批模块公共 API（**不改** `withdraw_instance` 既有行为，守卫是 T051，Wave 3.8）；同 PR 更新 approval-module skill（T050）。
  **测试**: T034 全部通过。
  **覆盖 AC**: AC-33, AC-34, AC-35
  **依赖**: T034, T033

#### 3.4 服务端权限判定、状态只读接口与端点

- [ ] **T036**: `[MVP-核心]` 手动上线 + 发布状态只读服务测试
  **文件**: `src/backend/test/app_publish/test_publish_status_service.py`（新）
  **逻辑**: 断言状态接口的字段完整性、**唯一实现**、owner-only 的业务规则前置拦截与"不回 403/404"红线。
  **测试**: `test_manual_publish_does_not_re_approve_and_marks_online`（成功 → `mark_terminal_state('online')` + 审计 `app.release.manual_publish`，**不产生新版本记录**，决议-6）→ AC-32 / `test_manual_publish_failure_keeps_pending_and_does_not_change_approval` → AC-32 / `test_manual_publish_owner_only_prefilter_not_permission_runtime`（**管理员在权限运行时被身份短路放行**，`permission_action_service.py:372-385` → owner-only 必须是业务规则前置拦截，C4）→ AC-32, AC-62 / `test_status_service_is_single_implementation_for_ui_and_mcp`（AC-38「两处返回一致」由"只有一处实现"**结构性保证**，不靠约定）→ AC-38 / `test_status_returns_reject_reason_full_text_and_pending_reason` → AC-38 / `test_status_shape_matches_contract`（design §4.2 ② 字段表）→ AC-38 / `test_status_no_permission_returns_business_code_not_403`（platform 拦截器对 `403/404` **整页跳转 `/403`**，`request.ts:160-166` → 无权者返回 200 + `16254` 或 `silent: true`，K11 ② / 坑 22）→ AC-38, AC-62 / `test_tenant_admin_can_view_but_cannot_withdraw_delete_manual_publish`（角色矩阵）→ AC-62 / `test_can_flags_reflect_role_and_state` → AC-62 / `test_deleted_app_status_reports_cancelled_independently`（D10 读侧防御）→ AC-38
  **覆盖 AC**: AC-32, AC-38, AC-62
  **依赖**: T033, T035

- [ ] **T037**: `[MVP-核心]` `publish_status_service` + 手动上线实现
  **文件**: `src/backend/bisheng/app_publish/domain/services/publish_status_service.py`（新）
  **逻辑**: `get_publish_status(app_id, actor)` —— **AC-38 的唯一实现**（发布面 + F052 MCP 应用状态工具共用）。返回 design §4.2 ② 的结构：`app_state` / `pending_reason` / `current_version` / `pending_version` / `deployment{stage,status,failure}` / `approval{instance_id,status,reject_reason,...}` / `tier` / `capabilities`（本轮恒空数组）/ `schema_change`（本轮恒 `null`）/ `can{withdraw,manual_publish,submit}`。**不写库**。`request_manual_publish(app_id, actor)`：owner-only 前置拦截（16254）→ 调 F054 `POST /api/v1/apps/{app_id}/actions/manual-publish` 对应的 `AppStateService.manual_publish` → 成功 `mark_terminal_state('online')` + 审计；仍失败保持待上线并回成因。能力「已失效」标记**按需计算**（`declared ∖ 当前可解析`），**不落库、不起定时任务**（本轮 `capabilities` 恒空，接口形状先定死，D13）。
  **测试**: T036 全部通过。
  **覆盖 AC**: AC-32, AC-38, AC-62
  **依赖**: T036

- [ ] **T038**: `[MVP-核心]` `/api/v2/apps` 管线端点集成测试（权限矩阵 + 全链）
  **文件**: `src/backend/test/app_publish/test_deploy_api.py`（新）
  **逻辑**: TestClient + 真实包素材（`fake_orchestrator` / `fake_minio`），覆盖四个 v2 端点与 AC-04 权限矩阵。
  **测试**: `test_deploy_requires_app_manage_scope_else_rejected`（缺位 → 明确提示缺哪位）→ AC-04 / `test_logs_requires_app_manage_scope` → AC-04 / `test_delegate_scope_rejected_with_local_dev_hint`（错误指向「委托专用、本地开发另发一把」；F049 期 `delegate` 位**根本发不出来**，本期天然成立、只需对齐文案，INV-31）→ AC-04 / `test_first_deploy_sets_owner_from_resource_owner_user_id` → AC-04 / `test_iteration_deploy_other_owner_rejected_16205_with_ownership_hint`（含租户管理员名下服务账号的密钥）→ AC-04 / `test_logs_only_for_owner_app` → AC-04 / `test_session_cookie_cannot_call_v2_endpoints`（v2 只认 `Bearer bs-sak-…`）→ AC-04 / `test_full_pipeline_happy_path_creates_version_and_approval`（断言 `app_deployment` 阶段推进、`app_version` 落行、审批单生成、`app.release.*` 审计落行且在 UI 白名单内）→ AC-01 / `test_active_release_blocks_second_deploy_16251` → AC-03 / `test_pending_online_blocks_deploy_16252` → AC-03 / `test_deployment_polling_returns_failure_tuple` → AC-11 / `test_deploy_limits_returns_settings_values` → AC-01 / `test_cross_tenant_deployment_id_not_visible` → AC-01 / `test_app_runtime_disabled_returns_16207` → AC-01
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-11
  **依赖**: T021, T023, T031

- [ ] **T039**: `[MVP-核心]` `/api/v2/apps` router + 四端点实现
  **文件**: `src/backend/bisheng/app_publish/api/router.py`（新）, `src/backend/bisheng/app_publish/api/endpoints/deploy.py`（新）, `src/backend/bisheng/api/router.py`（挂接新 router）
  **逻辑**: **F055 自建 router `/api/v2/apps`，每个端点挂 `Depends(open_api_subject("app:manage"))`**（F049 `open_api/api/dependencies.py:103-115` 的 docstring 逐字预留了这个用法：*"For routers that F053 / F055 add outside the shared /api/v2 router"*；**不自建鉴权**，K8）。
  **⚠️ 工场运行时层未启用闸（`16207`）**：四个端点共用一个前置依赖 `require_app_runtime_enabled()` —— 读 F054 的 `settings.app_runtime.enabled`（未部署工场运行时层的存量环境该值为假）→ 假则直接 `16207`。**位置写死为「`Depends(open_api_subject("app:manage"))` 之后、归属判定之前」**：先鉴权再报"功能未启用"，避免未认证方探测部署形态；早于归属判定则是因为环境没启用时根本没有 `app` 表数据可判。漏这一闸 = T038 的 `test_app_runtime_disabled_returns_16207` 红测，且存量环境调 `deploy` 会一路走到编排器 RPC 超时。
  四端点（design §4.2 ①）：`GET /deploy-limits` → `{max_package_mb, max_unpacked_mb, max_package_entries}`（F053 打包后上传前自查，取不到时退化为直接上传由 16201 兜底）· `POST /deploy`（multipart：`package` + `app_id?` + `confirm_schema_change`〔**本期只接受不消费**，避免 CLI 侧改两次〕）→ `{deployment_id, app_id, version_id, entry_url?}` · `GET /deployments/{deployment_id}` → 轮询载荷 · `GET /{app_id}/logs` → **转发 F054 `GET /api/v1/apps/{id}/logs` 的同一服务方法**，只加 `app:manage` + 归属人判定。owner 判定读 `OpenApiPrincipal.resource_owner_user_id`（**不是** `subject_user_id`）。端点一律经 domain service、不直接 import `database/models`（RULE-3）。
  **测试**: T038 全部通过。
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-11
  **依赖**: T038

- [ ] **T040**: `[MVP-核心]` `/api/v1` 发布状态端点集成测试
  **文件**: `src/backend/test/app_publish/test_publish_status_api.py`（新）
  **逻辑**: TestClient 覆盖登录态下的状态只读与手动上线端点。
  **测试**: `test_publish_status_endpoint_path_and_shape`（`GET /api/v1/apps/{app_id}/publish-status`，形状在此定死，供发布面与 F052 消费）→ AC-38 / `test_publish_status_non_owner_gets_business_code_not_403_404`（坑 22）→ AC-38, AC-62 / `test_manual_publish_endpoint_owner_only_16254` → AC-32, AC-62 / `test_withdraw_goes_through_existing_approval_endpoint`（直接调既有 `POST /api/v1/approval/instances/{instance_id}/withdraw`，**不新建撤回端点**——owner-only 由它已有的 `applicant_user_id` 校验天然成立，`:430`）→ AC-34 / `test_all_endpoints_return_unified_response_model` → AC-38 / `test_cross_tenant_app_id_rejected` → AC-38
  **覆盖 AC**: AC-32, AC-34, AC-38, AC-62
  **依赖**: T037

- [ ] **T041**: `[MVP-核心]` `/api/v1` 发布状态端点实现
  **文件**: `src/backend/bisheng/app_publish/api/endpoints/publish_status.py`（新）, `src/backend/bisheng/app_publish/api/router.py`（**增量**注册 v1 子路由，不改 T039 已落的 v2 部分）
  **逻辑**: `GET /api/v1/apps/{app_id}/publish-status`（登录态，`UserPayload` 注入）委托 `PublishStatusService.get_publish_status`；`POST /api/v1/apps/{app_id}/publish/manual-publish` 委托 `request_manual_publish`（**F054 已有 `actions/manual-publish` 端点做状态动作，本端点只做 owner-only 前置 + 版本终态标注的编排**，避免两处都能改应用态）。**无权者返回 200 + 业务码**（K11 ②）。`UnifiedResponseModel` 包装。
  **测试**: T040 全部通过。
  **覆盖 AC**: AC-32, AC-34, AC-38, AC-62
  **依赖**: T040, T039

#### 3.5 事件触达

- [ ] **T042**: `[MVP-核心]` 六类触达测试（收件人解析 + 消息不承载操作）
  **文件**: `src/backend/test/app_publish/test_publish_notification.py`（新）
  **逻辑**: 断言 AC-64 六类事件的接收方与 AC-65 的"只通知不承载操作"发送契约。
  **测试**: `test_approval_created_notifies_approvers`（Gate 不发、由我们自发，坑 5）→ AC-64 / `test_approved_and_rejected_notify_owner` → AC-64 / `test_withdrawn_notifies_approvers_who_received_task` → AC-64 / `test_cancelled_by_delete_notifies_approvers_new_action_code`（`approval_instance_cancelled`）→ AC-64 / `test_pending_online_notifies_owner_and_tenant_admin_root_super_admin` → AC-64 / `test_resource_released_and_capability_revoked_send_nothing`（两类**不主动提示**，仅发布面自查）→ AC-64 / `test_non_approval_notifications_use_neutral_message_type`（**发送契约写死**：`message_type` **不得为 `request` / `approve`**——`isApprovalMessageType`（`NotificationsDialog.tsx:152-156`）在这两个类型下**也为真**，并不只看 action_code 白名单，用错类型会长出一个点了会报错的跳转按钮，AC-65 当场破）→ AC-65 / `test_notifications_carry_no_action_payload` → AC-65
  **覆盖 AC**: AC-64, AC-65
  **依赖**: T033, T035

- [ ] **T043**: `[MVP-核心]` `publish_notification_service` 实现
  **文件**: `src/backend/bisheng/app_publish/domain/services/publish_notification_service.py`（新）
  **逻辑**: 六类触达的收件人解析与发送，**复用** `ApprovalNotificationService` / 既有站内消息服务（不新建通道）。新 action_code（design §4.2 ⑦）：`approval_instance_cancelled`（审批人）· `app_publish_pending_capacity`（owner + 租户管理员，Root → 超管）· `app_publish_deploy_failed`（同上）。后两者是**非审批类**，`message_type` 用中性类型（见 T042 的发送契约）。待上线两类的管理员收件人**直接复用** `_get_admin_recipient_ids` 的无条件 union（多通知一个超管无害；与 T025 的条件回退是两码事，**别混用**）。**消息只通知不承载操作**（AC-65），处理动作一律回发布面或审批中心。
  **测试**: T042 全部通过。
  **覆盖 AC**: AC-64, AC-65
  **依赖**: T042

#### 3.6 前端 Platform（手动验证）

- [ ] **T044a**: `[MVP-核心]` Platform：发布面 API 层 + 审批状态卡
  **文件**: `src/frontend/platform/src/controllers/API/hostedApp.ts`（F054 已建，**增量**加 `getPublishStatus` / `manualPublish` / `getVersions` / `withdrawApproval` 四个方法）, `src/frontend/platform/src/pages/BuildPage/hostedApp/publish/ApprovalStatusCard.tsx`（新）, `src/frontend/platform/public/locales/{zh-Hans,en,ja}/bs.json`（三语一组：本卡新增 key；**与 T045 是同一组文件、必须同 PR**）
  **逻辑**:
  - 四个 API 方法：`getPublishStatus(appId)` → `GET /api/v1/apps/{appId}/publish-status`（T041）· `manualPublish(appId)` → `POST /api/v1/apps/{appId}/publish/manual-publish` · `getVersions(appId, params)` → 版本列表（**返回体须是 `{data,total}`**，供 T044b 的 `useTable` 消费）· `withdrawApproval(instanceId)` → 直接调既有 `POST /api/v1/approval/instances/{id}/withdraw`（**不新建撤回端点**）。**一律经 `controllers/request` 封装，禁 `import axios`**（C7）。
  - `ApprovalStatusCard`：待审 / 通过 / 驳回 / 已撤回 / 待上线成因（资源不足 · 上线失败文案区分）+ **驳回理由全文**（不截断）+ 结构变更提示位（本轮恒空）+ 在途时「撤回」按钮 + 「手动上线」按钮（按 `can.manual_publish` 显示，动作本体由 F054 T067 已交付、本卡只按状态放行）。
  - 数据拉取用裸 `useState + useEffect`（K11 ①：platform `react-query` 已被 eslint 冻结）；无权时接口回业务码（**不能触发整页跳 `/403`**，坑 22）。
  **手动验证**: 打开 `http://192.168.106.114:3001/build/apps/{appId}` 的「发布」tab —— ① 在途时状态卡显示「待审」且「撤回」可点，点后变「已撤回」；② 驳回后能看到**理由全文**（不截断）；③ 待上线（资源不足）时出现「手动上线」，点击成功后状态变「已上线」；④ 非 owner 打开**不整页跳 `/403`**，而是看到只读或提示区块；⑤ 切 en / ja 无裸键名。
  **覆盖 AC**: AC-32, AC-33, AC-34, AC-62
  **依赖**: T041

- [ ] **T044b**: `[MVP-核心]` Platform：版本列表卡 + 危险操作卡 + 填 F054 slot
  **文件**: `src/frontend/platform/src/pages/BuildPage/hostedApp/publish/{VersionListCard,DangerZoneCard}.tsx`（新，**每块一个文件**，避开 F054 `PublishTab.tsx` 与 600 行硬规）, `src/frontend/platform/src/pages/BuildPage/hostedApp/tabs/PublishTab.tsx`（**只填 slot**，不重写壳）, `src/frontend/platform/public/locales/{zh-Hans,en,ja}/bs.json`（三语一组：本批新增 key；同 T044a / T045 一组）
  **逻辑**:
  - `VersionListCard`：只读列表（版本号 / 类型 / 提交时间 / 终态标注；待上线版本显示「待上线」），**不提供回滚入口**。⚠️ **绝不复用 `CardSelectVersion`**（`BuildPage/CardSelectVersion.tsx`）——它**切换即写库**（`handleChange :25-31` 调 `changeCurrentVersion`），且 `version_list` 对托管应用**恒空**（坑 29）。数据拉取用 `util/hook.ts:215 useTable`（**要求接口返回 `{data,total}`**，否则 `:238` 直接 console.error）。
  - `DangerZoneCard`：显式删除调 F054 动作，仅 owner；已上线态置灰并提示「请先停运」。
  - **AC-06**：CLI 导入应用的「提交发布」按钮**不可用并提示以 `bisheng deploy` 提交**（本册 CLI 应用无草稿工作区，决议-2）。
  - **填 slot**：把 T044a 的 `ApprovalStatusCard` 与本任务两卡装进 `PublishTab.tsx` 的 slot。**不重做 F054 T067 已交付的**应用态徽标 / 入口链接 / 停运 / 重新启用 / 手动上线三按钮；F055 只把 `can.manual_publish` / `pending_reason` 经 props 下传，让「手动上线」按待上线态出现。**可见范围区是 F056 的槽位**，只留位不写内容。
  **手动验证**: 同一「发布」tab —— ① 版本列表只读、无任何切换 / 回滚控件；② 手动上线成功后版本列表该行终态由「待上线」变「已上线」且**不多出一行**；③ 「提交发布」置灰并提示走 `bisheng deploy`；④ 已上线态下删除按钮置灰并提示「请先停运」；⑤ F056 的可见范围槽位为空时布局不塌；⑥ 三卡同屏布局正常、无横向滚动。
  **覆盖 AC**: AC-06, AC-39, AC-61
  **依赖**: T044a

- [ ] **T045**: `[MVP-核心]` Platform：审计前端 lockstep + 三语 i18n
  **文件**: `src/frontend/platform/src/controllers/API/log.ts`（`actions` / `getModulesApi` 加 `app.release.*`）, `src/frontend/platform/public/locales/{zh-Hans,en,ja}/bs.json`（三语一组：`log.systemIdEnum` / `log.eventTypeEnum` + 发布面新增 key）
  **逻辑**: 完成 design 坑 21 的**四处 lockstep 的第 2–4 处**（第 1 处是 T006）——**必须与 T006 同 PR**，漏任一处 = 事件写库了但审计页与筛选下拉一条看不到，排查半天以为审计没写。同批补 T044a / T044b 发布面的三语 key（**`bs.json` 三语是本任务与 T044a/T044b 共用的同一组文件，三者必须同 PR**；新 key 三语齐全，CI `pnpm check-i18n` 校验 key parity）。**不加铃铛**（PRD §3.0.3：管理后台不设消息面）。
  **手动验证**: 审计页「系统操作」筛选出现「应用」命名空间，筛选后能看到 `app.release.submit` / `approval_created` / `approved` / `online` 四条且带应用名；切换 en / ja 无裸键名。
  **覆盖 AC**: AC-01
  **依赖**: T006, T044a, T044b

- [ ] **T046**: `[MVP-核心]` Platform：审批场景配置补 `tenant_admin` 来源选项
  **文件**: `src/frontend/platform/src/pages/ApprovalPage/index.tsx`（`APPROVER_SOURCE_OPTIONS`，约 `:590-597`）
  **逻辑**: 该下拉今天**只有 6 项、没有 `tenant_admin`**，而 `APPROVER_SOURCE_LABEL_KEYS`（`:180-188`）与三语（`bs.json` 的 `approverSource.tenant_admin`，**两处** `:1832` / `:1842`）**早就有**（坑 23）→ 只需补选项一行。不补 = 租户管理员一旦改配审批人，就**再也没法把「租户管理员」这个来源加回来**，AC-19 半残。「应用发布」场景**自动出现在左栏列表**（seed 落库即有，`:1632-1700`）且因已存在而不出现在「新增」下拉（`:232`）→ AC-19 的"展示"部分**零前端改动**。场景名 `应用发布` 是**后端硬编码中文**、前端直接渲染 `s.scenario_name`（`:1660`）——**接受中文单语**（与既有三场景一致，坑 24），不另开映射表。
  **手动验证**: 管理后台 → 审批中心 → 场景配置 → 左栏出现「应用发布」并展示预置配置（单条无条件分支 / 单节点或签 / 两个来源）；改配审批人时下拉里能选到「租户管理员」；改完后新发布按新配置生成审批单，重启后端不被重置。
  **覆盖 AC**: AC-19
  **依赖**: T027a

#### 3.7 前端 Client（手动验证）

- [ ] **T047**: `[MVP-核心]` Client：审批单四分区面板 + 驳回理由必填 + i18n 债
  **文件**: `src/frontend/client/src/components/approval/AppPublishDetailPanel.tsx`（新）, **`src/frontend/client/src/components/approval/ApprovalCenterDialog.tsx`**（存量：早分派 + `DETAIL_INTERNAL_KEYS` + 驳回必填 + 抽 4 条硬编码中文；**路径是 `components/approval/`，不是 `components/` 根**）, `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`（三语一组：四分区面板文案 + 抽出的 4 条中文；**与 T048 是同一组文件、必须同 PR**——新 key 三语同 PR 是根 AGENTS.md 硬规、CI `pnpm check-i18n` 拦）
  **逻辑**:
  - 在 `TaskDetailPanel`（`:682`）内按 `detail.scenario_code === 'app_publish_request'` **早分派**到新组件（**不建通用注册表**——一个场景不值得，既有先例 `canRevoke :378-382` 就是"顶层算个布尔 + 条件渲染"；出现第二个场景时再抽，D14）。新文件避开 `ApprovalCenterDialog.tsx` 已 1037 行 + 600 行硬规。
  - **四分区**（AC-24）：① 头部基本信息（应用名 / owner / 来源：平台内造或 CLI 导入 / 首发或迭代 / 提交时间）→ 复用 `DetailHeader`（`:650-680`）+ `InfoGrid`（`:152-166`）；② 能力声明白话摘要 → **新分区**（`InfoGrid` 签名是 `[string,string][]`，装不下"图标 + 名称 + 说明 + 失效标记"三段行；本轮声明恒空 → 显示「本次发布未声明平台能力」）；③ 可见范围快照 + **「仅供参考，可见范围变更即时生效、不经审批」黄注** → 新分区（参考「申请理由」灰底块 `:726-731`）；④ 资源档位（含结构变更时的「结构变更」行，本轮恒空）。
  - **必须把结构化子树的键加进 `DETAIL_INTERNAL_KEYS`**（`:136`：`capabilities` / `visibility_snapshot` / `tier` / `schema_change` / `approver_note` …），否则未分派到的通用两列网格会把它们渲染成 `[object Object]` 一坨（坑 7）。
  - **驳回理由必填**（AC-24）：`runTaskDecision`（`:328-334`）的 `:331` 今天在评论为空时兜底成**硬编码中文** `"同意"/"驳回"` → ① 驳回按钮 `disabled={actionLoading || !decisionComment.trim()}`（现成范式：`:613` 的 `disabled={!revokeReason.trim()}`）② 去掉中文兜底。**通过仍可空**——AC-24 只要求驳回必填，别一刀切。
  - **MVP 期不渲染审读视图整块**（连「查看待上线版本」按钮也不出，避免死链，D14）。
  - **i18n / lint 债（触碰即还）**：`ApprovalCenterDialog.tsx` 在 `client/eslint-suppressions.json:1714-1723` 有冻结违规（`no-explicit-any ×16` / **`no-restricted-syntax ×4` 硬编码中文** / `exhaustive-deps ×3`），其中 `:331` 正是本任务要改的那行 → 同 PR 把 4 条中文抽成 i18n 并 `pnpm lint:prune`（根 AGENTS.md「谁触碰谁还债」）。
  **手动验证**: 用审批人账号登录 `http://192.168.106.114:4001/workspace` → 审批中心 → 打开应用发布单：① 详情是**四分区**而不是两列网格，无 `[object Object]`、无裸英文键名；② 不填理由点「驳回」按钮**置灰点不动**，填了才可点；③ 点「通过」不填评论可提交；④ 无「查看待上线版本」按钮（不出死链）；⑤ `pnpm lint` 通过且该文件的中文违规条目已从 suppressions 减少。
  **覆盖 AC**: AC-24
  **依赖**: T029

- [ ] **T048**: `[MVP-核心]` Client：站内信场景文案 + 三语 key
  **文件**: `src/frontend/client/src/components/NotificationsDialog.tsx`（`APPROVAL_TASK_SCENARIO_TEXT_KEYS`，约 `:96-100`）, `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`（三语一组）
  **逻辑**: **一处代码**：`APPROVAL_TASK_SCENARIO_TEXT_KEYS` 加 `app_publish_request: 'com_notifications_action_request_app_publish'`（同族键 `com_notifications_action_request_channel` 在 `zh-Hans:489` / `en:501` / `ja:486`）。**三语 key**：该键 + `approval_instance_cancelled` + **两条非审批类** `com_notifications_action_app_publish_pending_capacity` / `com_notifications_action_app_publish_deploy_failed`——后两者走 `getNotificationText` 的兜底 key `com_notifications_action_{action_code}`（`:470`）**零前端代码**，前提是发送侧用中性 `message_type`（T042 的发送契约）。
  **手动验证**: 审批人铃铛出现「提交了应用发布申请」（**不是裸 action_code**）；owner 在待上线时收到「资源不足」通知且**没有跳转按钮**（AC-65）；切 en / ja 无裸键。
  **覆盖 AC**: AC-64, AC-65
  **依赖**: T043, T047

#### 3.8 `withdraw` 终态守卫（§6 字面读法留在 MVP 内）

- [ ] **T051**: `[MVP-核心]` `withdraw` 终态守卫（非 PENDING 一律拒；错误码走 **approval 段 181xx**、不占 162）
  **文件**: `src/backend/bisheng/approval/domain/services/approval_center_service.py`（`withdraw_instance` 约 `:432` 之前加守卫）, `src/backend/bisheng/common/errcode/approval.py`, `src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`（新错误码三语一组）, `src/backend/test/app_publish/test_withdraw_guard.py`（新）
  **逻辑**: `withdraw_instance` 今天只校验 `applicant_user_id`、**不校验 instance 状态**（坑 4）→ 已 APPROVED / REJECTED / CANCELLED 的单子被直接打 API 也能"撤回"，落到 F055 就是**已上线版本的 `terminal_state` 被反复改写成 `withdrawn`**（`on_withdrawn` 照样触发）。守卫加在 `applicant_user_id` 校验之后、状态变更之前：`if instance.status != PENDING: raise ApprovalInstanceNotPendingError`（**新码归 approval 段 181xx**，不占 F055 的 162 段——它修的是审批模块的既有缺陷，不是应用发布的业务错误）。
  **⚠️ 跨 Feature**: 改的是审批模块公共 API 的行为（收紧），对频道订阅 / 知识空间加入两个既有场景同样生效 → 测试须含这两个场景的回归；同 PR 更新 approval-module skill（T050 一并做）。
  **测试**: `test_withdraw_pending_still_succeeds` / `test_withdraw_approved_rejected_181xx`（三个终态各一次）/ `test_withdraw_cancelled_rejected` / `test_online_version_terminal_state_not_overwritten_by_late_withdraw`（AC-22 的真实后果）/ `test_existing_channel_and_knowledge_scenarios_withdraw_unaffected_when_pending`（行为收紧的护栏）
  **覆盖 AC**: AC-22
  **依赖**: T035

#### 3.9 114 部署验证与上游回写

- [ ] **T049**: `[MVP-核心]` 114 部署与手动验证清单（演示剧本步 3–4）
  **文件**: `features/v3.0.0/055-app-publish-pipeline/tasks.md`（本文「实际偏差记录」回填）
  **前置**: F049 / F054 首波已部署 → `bash /opt/bisheng-ops/deploy.sh` → **先发代码、再往 `config.yaml` 加 `app_runtime` 新键、再全量重启**（K10，顺序反了直接拒启）→ 确认**消费默认队列的 celery worker 在跑**（K12：缺它则管线后段与审批 outbox 双双不执行）。
  **验证清单**（逐条勾）:
  0. **前置自检**：`curl -s http://127.0.0.1:7860/api/v1/env | jq '.app_runtime_enabled, .open_platform_enabled'` → 均 `true`；`SELECT code,cpu_millicores,memory_mb,enabled FROM resource_tier;` → 三行且 **`light` 已按 `settings.app_runtime.default_tiers` 下调**（114 available ≈12G 但曾长期 ~0.9G，1C/2G 会在容量闸直接被拒，坑 27）；`SELECT tenant_id,scenario_code,enabled FROM approval_scenario WHERE scenario_code='app_publish_request';` → 有行；`ps -ef | grep 'celery.*worker'` → 有默认队列消费者。
  1. **步 3**：`bisheng deploy` → CLI 分阶段输出 `manifest → 构建 → 探活 → 扫描 → 审批单已生成`（**spec 字面顺序**）→ AC-01。
  2. **故意验证扫描**：包里塞一行 `token = "bs-sak-<43位>"` 再 deploy → 被阻断、输出含 `文件:行号`、**输出里 grep 不到那 43 位串** → AC-10。
  3. **故意验证 manifest**：删掉 `runtime` 再 deploy → `16221` 且 `details` 指出缺哪个字段 → AC-11。
  4. **在途闸**：不撤回直接再 deploy → `16251` → AC-03。
  5. **审批人解析**（114 单租户 → **必然走 Root 回退**）：`SELECT approver_user_id FROM approval_task WHERE instance_id=<N>;` → 平台超管（AC-15）；owner 有主部门且该部门设了部门管理员则应同时出现（AC-12）；`SELECT applicant_user_id FROM approval_instance WHERE id=<N>;` → **是 owner 自然人不是服务账号**（AC-16 / 坑 28）。
  6. **步 4**：用**审批人账号**（非发起人）登录 client → 铃铛有「提交了应用发布申请」（AC-64）→ 审批中心详情是**四分区**（AC-24）→ 不填理由点「驳回」置灰 → 填理由点「通过」→ `docker ps` 出现 `bisheng-app-*`、应用态「已上线」、`app_version.terminal_state='online'`（AC-31）。
  7. **审计**：审计页筛「应用」命名空间能看到 `app.release.submit` / `approval_created` / `approved` / `online` 四条且带应用名（AC-01；看不到 = 四处 lockstep 漏了一处，坑 21）。
  8. **待上线分支**：把 `settings.app_runtime.reserve_mb` 临时调到极大使容量闸必拒 → 再走一遍审批通过 → **审批单仍是"通过"**、应用态「待上线（资源不足）」、owner 与超管各收到一条**无跳转按钮**的站内信（AC-31 / AC-65）；恢复配置后发布面点「手动上线」→ 成功且**不产生新版本记录**（AC-32 / 决议-6）。
  9. **驳回 / 撤回**：驳回一次 → owner 在发布面看到**理由全文**（AC-33）；再提交后 owner 点「撤回」→ 审批人待办消失（AC-34）；**再对同一个已终态的 instance 直接打 `POST /api/v1/approval/instances/{id}/withdraw`** → 被 181xx 拒、`app_version.terminal_state` 不被改写（AC-22 / T051）。
  10. **删除致取消**：新建应用提交到待审 → 删除该应用 → 审批单 CANCELLED 且审批人收到通知（AC-35）。
  11. **既有场景回归**（行为变更护栏）：频道订阅 / 知识空间加入各走一次审批，审批人解析正常（AC-21）。
  **⚠️ health 200 会骗人**（admin 短路 ReBAC）——涉及权限的判定用非管理员账号复核。
  **覆盖 AC**: AC-01, AC-03, AC-10, AC-11, AC-12, AC-15, AC-16, AC-21, AC-22, AC-24, AC-31, AC-32, AC-33, AC-34, AC-35, AC-64, AC-65
  **依赖**: T039, T041, T044a, T044b, T045, T046, T047, T048, T051

- [ ] **T050**: `[MVP-核心]` 上游回写三项 + approval-module skill 同步
  **文件**: `features/v3.0.0/054-app-domain-runtime/{design.md,tasks.md}`（回写 1、2）, `features/v3.0.0/053-dev-cli-skills/spec.md`（回写 3）, `.claude/skills/approval-module/SKILL.md`（§3 / §4 / §5 / §7 / §8）
  **逻辑**（design §8「必须回写上游的三项」）:
  1. **F054 `DEFAULT_TIERS`**：数值与第三档名称按 D11 裁定回写（1C/2G · 2C/4G · 4C/8G，「增强」→「性能」），并把 F054 design D11「何时重新考虑」里的"支持删档"改为"档位只可停用不可删"——**代码侧改动在 T015，本任务只改文档**。
  2. **F054 `create_app` 契约行**：F054 tasks T049 已提供 `create_app(manifest, owner_user_id, tenant_id)`（坑 26 的"尚不存在"已被 F054 tasks 覆盖）→ 在 F054 design §4.2 ② 与 §6.1 各补一行把它登记为 Outgoing 契约（今天只列了五个状态动作 + `stage_version` + `update_meta`），并注明 **F055 调它、不直写 `app` 表**。
  3. **F053 spec AC-32**：补一句「上限经 `GET /api/v2/apps/deploy-limits` 取，取不到则直接上传由服务端 16201 兜底」——否则 CLI 只能硬编码 50 MiB，正是 K7「同一契约分两处必漂移」自己反对的形态。
  4. **approval-module skill**：本 Feature 改了 `approver_resolver`（T025）、新增 `cancel_instance_by_business`（T035）、新增预置场景与四件套（T027a / T027b / T029）、新增站内信触发时机（T043）、收紧 `withdraw_instance`（T051）→ **同一 PR 必须更新 SKILL.md**（该 skill 的维护契约明写"改完代码后问自己：本 skill 里有没有哪句话现在变成假的了"）。
  **⚠️ 不做的一项**：**不要**去改 `release-contract.md:98` 的错误码分配表与 `constitution.md` C5——161–164 早已落定（F054 落码时写入），照旧文回写会产生空转任务，还可能让实现者去"修正"本已正确的表（K9）。
  **依赖**: T015, T025, T027a, T027b, T029, T035, T043, T051

---

---

### Wave 4 · 紧随首波（release 必做，本轮顺延——只列标题 / 文件 / 测试载体 / 覆盖 AC）

> 优先级顺序取 design §8（`withdraw` 守卫已上提至 Wave 3.8，见文首「§6 字面读法的两处对齐」）。

- [ ] **T052**: 审读视图（左文件树 + 右只读代码 + 4 tab）+ 「查看待上线版本」入口；弹窗 `viewMode:'review'` 放宽至 1200px（K11 ③ / D14 案 A）
  **文件**: `client/src/components/approval/AppReviewView.tsx`, **`client/src/components/approval/ApprovalCenterDialog.tsx`**（路径含 `approval/` 子目录）, `client/src/locales/{zh-Hans,en,ja}/translation.json`, `src/backend/bisheng/app_publish/api/endpoints/snapshot.py`
  **测试载体**: `src/backend/test/app_publish/test_snapshot_api.py`（快照只读端点：归属 / 审批人放行 / 二进制与超大文件降级）+ 前端手动验证清单（文件树可展开、代码只读不可编辑、4 tab 切换、1200px 下不横向滚动、无「查看待上线版本」死链）
  **覆盖 AC**: AC-24, AC-25

- [ ] **T053**: 审批期临时预览实例后端（快照拉起 / 临时空库 / 审批人身份注入 + owner 权限放行〔NFR-1.2 审批例外，INV-36〕/ 终态与超时回收 / 不占实例名额）
  **文件**: `src/backend/bisheng/app_publish/domain/services/preview_instance_service.py`, `src/backend/bisheng/app_publish/api/endpoints/preview.py`, `src/backend/test/app_publish/test_preview_instance.py`
  **覆盖 AC**: AC-26, AC-27, AC-28, AC-29, AC-30

- [ ] **T054**: 审批期预览前端（「预览试用」置顶 / 四个界面状态 / 打开预览 / 手动回收）
  **文件**: `client/src/components/approval/AppPreviewPanel.tsx`, `client/src/locales/{zh-Hans,en,ja}/translation.json`
  **测试载体**: 前端手动验证清单（四个界面状态各截一次：未拉起 / 拉起中 / 可用 / 已回收；「预览试用」在详情面板置顶；手动回收后实例消失且不占名额；切 en / ja 无裸键）
  **覆盖 AC**: AC-26, AC-28

---

### Wave 5 · 能力总线与应用运行期凭据（release 必做，本轮顺延）

- [ ] **T055**: `hosted_app` 主体解析器注册与凭据生命周期（签发 / 重签 / 5 秒失效 / 停运拒绝 / 删除撤销 / 无任何管理入口 / 不进服务账号列表）
  **文件**: `src/backend/bisheng/app_publish/domain/services/app_credential_service.py`, `src/backend/bisheng/open_api/domain/subject_resolvers.py`（注册 `SUBJECT_RESOLVERS['hosted_app']`）, `src/backend/test/app_publish/test_app_credential.py`
  **覆盖 AC**: AC-57, AC-58, AC-59, AC-60

- [ ] **T056**: 模型能力注入（经 F051 OpenAI 兼容面 + `BISHENG_PLATFORM_API_BASE` / `BISHENG_APP_TOKEN` 注入；未声明不可调用；工作台无任何底层账号 / 端点配置入口）
  **文件**: `src/backend/bisheng/app_publish/domain/services/capability_bus_service.py`, `src/backend/test/app_publish/test_capability_model.py`
  **覆盖 AC**: AC-49, AC-51, AC-54

- [ ] **T057**: 知识库能力注入与 fail-closed（白名单由平台按当前生效声明确定、应用不可自报；运行期可及 = 白名单 ∩ 访问用户可见范围，文件级经 F052 门面；无访问用户身份一律拒绝、绝不回退全量；集合相等断言）
  **文件**: `src/backend/bisheng/app_publish/domain/services/capability_bus_service.py`（增量）, `src/backend/test/app_publish/test_capability_knowledge.py`
  **覆盖 AC**: AC-50, AC-52

- [ ] **T058**: 能力收回错误态（`16273` 带能力名与「已收回」原因、不回退旧值、应用整体可用）+ 迭代上线后旧能力 5 秒内失效 + 发布面「已失效 + 原因」标记（按需计算、不落库、不起定时任务）
  **文件**: `src/backend/bisheng/app_publish/domain/services/capability_bus_service.py`（增量）, `platform/src/pages/BuildPage/hostedApp/publish/CapabilityListCard.tsx`（**新建方**——T067 只在其上增量补全，两处都标「新」会互相覆盖）, `src/backend/test/app_publish/test_capability_revoked.py`
  **覆盖 AC**: AC-37, AC-53, AC-63

- [ ] **T059**: 能力调用审计双归属（actor = 应用 / subject = 当前访问用户；**仅模型调用**允许 subject = 「应用自身」并显式标注，检索无访问用户一律拒；含模型名与 token 数 / 检索目标；subject 列随 F050，落地前以附加字段承载）
  **文件**: `src/backend/bisheng/app_publish/domain/services/capability_audit.py`, `src/backend/test/app_publish/test_capability_audit.py`
  **覆盖 AC**: AC-55

- [ ] **T060**: 预检的能力声明引用校验（所引模型在本租户已启用且按 F051 名称解析规则可唯一解析〔裸名歧义 → 拒绝并提示限定名〕；所引知识库存在且为 F052 门面支持的类型）+ 审批单能力白话摘要接真数据
  **文件**: `src/backend/bisheng/app_publish/domain/services/precheck_service.py`（增量）, `src/backend/test/app_publish/test_precheck_capability_refs.py`
  **覆盖 AC**: AC-07, AC-24

---

### Wave 6 · 结构演进与版本差异（release 必做，本轮顺延）

- [ ] **T061**: `precheck_schema` 阶段 + 改 / 删列显式确认（CLI 交互或 `--confirm-schema-change`；未确认拒 `16229`；已确认进入管线、发布时不再二次确认；审批单与发布面展示结构变更）
  **文件**: `src/backend/bisheng/app_publish/domain/services/schema_evolution_service.py`, `src/backend/bisheng/app_publish/domain/services/precheck_service.py`（增量）, `src/backend/test/app_publish/test_schema_evolution.py`
  **覆盖 AC**: AC-09

- [ ] **T062**: 应用数据表由 manifest 声明、平台建表（DEV-07 ②）：加列自动迁移无需确认；改 / 删列**迁移前自动留生产数据快照**（键 `apps/{app_id}/db-snapshots/{ts}.tar`）
  **文件**: `src/backend/bisheng/app_publish/domain/services/schema_evolution_service.py`（增量）, `src/backend/test/app_publish/test_schema_migration_snapshot.py`
  **覆盖 AC**: AC-42

- [ ] **T063**: 版本差异服务端 diff（`GET /api/v1/apps/{app_id}/versions/{a}/diff/{b}` → `{files:[{path,change,additions,deletions}], patches:[…]}`；**服务端算 diff、不下发两份 tar**）
  **文件**: `src/backend/bisheng/app_publish/domain/services/version_diff_service.py`, `src/backend/bisheng/app_publish/api/endpoints/version_diff.py`, `src/backend/test/app_publish/test_version_diff.py`
  **覆盖 AC**: AC-41

- [ ] **T064**: 版本差异前端（版本 tab 与审读视图**同一呈现组件**）
  **文件**: `platform/src/pages/BuildPage/hostedApp/publish/VersionDiff.tsx`, `client/src/components/approval/AppReviewView.tsx`（增量接入）, `platform/public/locales/{zh-Hans,en,ja}/bs.json`
  **测试载体**: 前端手动验证清单（platform 版本 tab 与 client 审读视图**同一组件同一呈现**、二进制文件降级为「不可比较」、大 diff 分块不卡）
  **覆盖 AC**: AC-41

---

### Wave 7 · 档位管理 tab 与发布面补全（release 必做，本轮顺延）

- [ ] **T065**: 档位管理 API（列表 / 行内改规格与说明 / 停用；**无删除**；「使用中应用数」= `COUNT(DISTINCT app_id) WHERE tier_id=? AND terminal_state='online'`；仅平台超管）
  **文件**: `src/backend/bisheng/app_publish/api/endpoints/resource_tier.py`, `src/backend/bisheng/app_publish/domain/services/resource_tier_service.py`（增量）, `src/backend/test/app_publish/test_resource_tier_api.py`
  **覆盖 AC**: AC-45

- [ ] **T066**: Platform：系统管理页「资源档位」tab（仅平台超管；与工场运行时层开关联动、未部署不出现；`bs-ui/table` + 手写 `useState` 行内编辑〔平台无表单库〕；保存前 `bsConfirm`；停用提示"存量应用不动、发布面不再可选"）
  **文件**: `platform/src/pages/SystemPage/ResourceTierTab.tsx`, `platform/src/controllers/API/hostedApp.ts`（增量）, `platform/public/locales/{zh-Hans,en,ja}/bs.json`
  **测试载体**: 前端手动验证清单（非超管看不到 tab；工场运行时层未部署时 tab 不出现；行内改规格 → `bsConfirm` → 保存生效；停用后发布面档位不可选而存量应用不受影响；**列表无删除按钮**；切 en / ja 无裸键）
  **覆盖 AC**: AC-45

- [ ] **T067**: 发布面补全：能力声明完整白话清单（含失效标记）+ 档位选择卡（随 PRD-2 平台内造应用的提交入口启用；本册对 CLI 应用不可用）
  **文件**: `platform/src/pages/BuildPage/hostedApp/publish/{TierSelectCard,SchemaChangeNotice}.tsx`（新）, `platform/src/pages/BuildPage/hostedApp/publish/CapabilityListCard.tsx`（**增量**——该文件由 **T058 创建**，本任务只补「完整白话清单 + 档位联动」，**不得重建**）, `platform/public/locales/{zh-Hans,en,ja}/bs.json`
  **测试载体**: 前端手动验证清单（能力清单逐条白话 + 失效标记与原因；档位卡对 CLI 导入应用置灰并提示走 `bisheng deploy`；结构变更提示位有内容时不塌）
  **覆盖 AC**: AC-61, AC-63

- [ ] **T068**: AC-64 触达全表复核（含催办 / 超时提醒 / 升级机制**不做**的显式确认）+ AC-08 静态依赖判据复议（本轮由探活兜底）
  **文件**: `src/backend/test/app_publish/test_notification_matrix.py`, `features/v3.0.0/055-app-publish-pipeline/design.md`（§8 结论回填）
  **覆盖 AC**: AC-08, AC-64

---

## AC 追溯表（65 / 65 全覆盖）

> 每条 AC 至少一个**测试任务**覆盖；实现任务与其配对测试任务共享同一组 AC 标注，此表只列首要承载任务。`[核]` = 该 AC 在本轮 `[MVP-核心]` 内闭环；`[后]` = 本轮顺延（Wave 4–7）。

| AC | 承载任务 | 轮次 |
|---|---|---|
| AC-01 | T020/T021, T022/T023, T038/T039, T045, T049 | [核] |
| AC-02 | T010/T011, T016/T017, T020, T022 | [核] |
| AC-03 | T020/T021, T030/T031, T038 | [核] |
| AC-04 | T020/T021, T038/T039 | [核] |
| AC-05 | T020/T021, T022/T023 | [核] |
| AC-06 | T044b | [核] |
| AC-07 | T008/T009, T018/T019 · 能力引用部分 T060 | [核] + [后] |
| AC-08 | T018/T019 · 静态判据复议 T068 | [核] + [后] |
| AC-09 | T061 | [后] |
| AC-10 | T012/T013, T022, T049 | [核] |
| AC-11 | T008, T012, T018/T019, T022, T038, T049 | [核] |
| AC-12 | T026/T027a, T028/T029, T049 | [核] |
| AC-13 | T028/T029 | [核] |
| AC-14 | T028/T029 | [核] |
| AC-15 | T024/T025, T049 | [核] |
| AC-16 | T028/T029, T049 | [核] |
| AC-17 | T028/T029 | [核] |
| AC-18 | T016, T028/T029 | [核] |
| AC-19 | T026/T027a, T046 | [核] |
| AC-20 | T026/T027b | [核] |
| AC-21 | T024/T025, T049 | [核] |
| AC-22 | T051, T049 | [核] |
| AC-23 | T028/T029, T030/T031 | [核] |
| AC-24 | T028/T029, T047, T049 · 「查看待上线版本」入口 T052 · 能力摘要真数据 T060 | [核] + [后] |
| AC-25 | T052 | [后] |
| AC-26 | T053, T054 | [后] |
| AC-27 | T053 | [后] |
| AC-28 | T053, T054 | [后] |
| AC-29 | T053 | [后] |
| AC-30 | T030（草稿态默认仅 owner 可见）· 审批人两条通道 T053 | [核] + [后] |
| AC-31 | T032/T033, T049 | [核] |
| AC-32 | T036/T037, T040/T041, T044a, T049 | [核] |
| AC-33 | T034/T035, T044a, T049 | [核] |
| AC-34 | T034/T035, T040, T044a, T049 | [核] |
| AC-35 | T032, T034/T035, T049 | [核] |
| AC-36 | T032/T033 | [核] |
| AC-37 | T058 | [后] |
| AC-38 | T036/T037, T040/T041 | [核] |
| AC-39 | T016/T017, T044b | [核] |
| AC-40 | T016/T017 | [核] |
| AC-41 | T063, T064 | [后] |
| AC-42 | T062 | [后] |
| AC-43 | T010/T011, T016/T017 | [核] |
| AC-44 | T014/T015 | [核] |
| AC-45 | T065, T066 | [后] |
| AC-46 | T008/T009, T014/T015 | [核] |
| AC-47 | T014/T015 | [核] |
| AC-48 | T014/T015, T022/T023 | [核] |
| AC-49 | T056 | [后] |
| AC-50 | T057 | [后] |
| AC-51 | T056 | [后] |
| AC-52 | T057 | [后] |
| AC-53 | T058 | [后] |
| AC-54 | T056 | [后] |
| AC-55 | T022/T023（能力声明变更审计）, T059 | [核] + [后] |
| AC-56 | T008/T009 | [核] |
| AC-57 | T055 | [后] |
| AC-58 | T055 | [后] |
| AC-59 | T055 | [后] |
| AC-60 | T055 | [后] |
| AC-61 | T044b · 能力清单与档位卡 T067 | [核] + [后] |
| AC-62 | T036/T037, T040/T041, T044a | [核] |
| AC-63 | T058, T067 | [后] |
| AC-64 | T032, T042/T043, T048, T049 · 全表复核 T068 | [核] + [后] |
| AC-65 | T042/T043, T048, T049 | [核] |

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已 ★ 确认的决策时，**先停下与用户重新确认**（§3 第四个 ★），再记录。
> **本轮已知的一项待确认偏离不在此表**：密钥扫描提前到构建之前（design D5 / §8），确认前一律按 spec 字面顺序实现。

1. **T006 增建 `src/backend/bisheng/app_publish/domain/constants.py`**（`AppReleaseAuditAction` StrEnum + `RELEASE_AUDIT_TARGET_TYPE`）—— 任务只点名 `audit_log.py`，但那样 16 个 action 字面量会散落进 Wave 2–3 的十来个 service。照 F054 `app_runtime/domain/constants.py AppAuditAction` 的同形先例补上，lockstep 由 `test_wave1_infra.py::test_release_actions_are_registered_in_the_ui_whitelist` 守住。
2. **T004 顺带补 `16100` / `16200` 两个家族基类码的三语文案** —— `pnpm check-i18n` 把「后端声明了码、前端无文案」判红，而 F054 落码时漏了 `16100`；不补则本批的 i18n 门禁必红（判据不是"顺手清债"，是"本批的验证项过不了"）。
3. **`ResourceTierDao.aupdate_row` 的行键参数名取 `tier_code` 而非 `code`** —— 叫 `code` 时 `aupdate_row(session, "light", code="tiny")` 是 `TypeError`，"禁止改 code"这条守卫永远走不到；改名后 `code=` 落进 `**values` 被显式拒绝。
4. **`test/app_publish/conftest.py` 加 `_sqlite_ddl_quirks`** —— `userrole` 是复合主键 + 代理键 autoincrement，SQLite 直接拒绝建表（"does not support autoincrement for composite primary keys"）。只在 `create_all` 期间清 `autoincrement` 再还原，生产 DDL 归 Alembic、不受影响；代价是 fixture 写 `userrole` / `department_admin_grant` / `user_department` 需显式 `id`。
5. **Wave 1 增加一个 `test/app_publish/test_wave1_infra.py`** —— 本节标注「无测试配对」，但 F049 Wave 1 有同名先例（`test/open_api/test_wave1_infra.py`）。只断言基础设施（错误码唯一性与一码一义、审计 lockstep、settings 五键、两个 DAO、conftest fixture 自身），**不认领任何 AC**；AC 覆盖仍归 T008–T017。
