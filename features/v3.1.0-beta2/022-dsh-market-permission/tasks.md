# Tasks: 企业插件与企业工作台按用户 / 部门 / 用户组授权

**关联规格**: [spec.md](./spec.md)
**版本**: v3.1.0-beta2

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-11-16 `/sdd-review spec` 6 项意见已修订（含 F019 恢复语义选 A），需求方 Callum 确认 |
| design.md | ✅ 已评审 | 2026-11-16 `/sdd-review design` 修订（登记方式、7 个员工侧入口、升级脚本修正与备份回滚、工作台可见性查询接口），需求方 Callum 确认；接手时的第一入口 |
| tasks.md | ✅ 已拆解 | 2026-11-16 `/sdd-review tasks` 两轮：首轮 1 项 medium（桌面端任务文件未落定）已修；剩 1 项 low 记录不改（AC-16、AC-21 只由手动 / 同事环境任务覆盖，属「行为不变 / 达梦」类验收） |
| 实现 | 🚧 进行中 | 5 / 26 完成。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3-§4 |

---

## 开发模式

- **分支**：服务端与管理后台 `feat/3.1.0-beta2-022-dsh-market-permission`（基于 `feat/3.1.0-beta2` 4315308da，worktree `bisheng-market-permission/`）；桌面端在 bisheng-desktop 仓库另开分支（基于提 PR 时约定的版本线，先用 `V1.3.1`），独立 git worktree，不动现有工作区。
- **按 Wave 组织**：Wave 内无依赖的任务可并行；每个任务标 `依赖:`。
- **后端 Test-First**：测试任务先于配对实现任务；新测试放 `src/backend/test/dsh_market/`、`src/backend/test/permission/`。运行：`cd src/backend && .venv/bin/pytest <文件> -q`（`asyncio_mode=auto`）。
- **前端（platform）**：现有页面已有 vitest 用例，本特性在同一任务内补用例并附手动验证步骤。
- **桌面端**：vitest，运行需 `NODE_OPTIONS=--no-experimental-webstorage`。
- **设计论证**：每个任务只写「做什么」，「为什么」指向 design 决策 / 坑编号，不复制。
- **类型名常量**：`dsh_market_plugin`、`dsh_market_workbench`（下文简称「两种新类型」）。

---

## Tasks

### Wave 1 — 权限基础设施（资源类型登记）

- [x] **T001**: 新资源类型登记测试
  **文件**: `src/backend/test/permission/test_dsh_market_resource_types.py`（新建）
  **逻辑**: 断言两种新类型同时出现在 `core/openfga/authorization_model_f048.MIGRATED_RESOURCE_TYPES`、`permission/domain/services/catalog_policy.MIGRATED_RESOURCE_TYPES`、`resource_lifecycle_policy.FIXED_CUSTOM_TYPES`（`default_permission_mode` 返回 `CUSTOM`）、`permission/api/endpoints/grant_subjects.GRANT_SUBJECT_RESOURCE_TYPES`；`build_f048_authorization_model()` 生成的模型含两种类型定义、`MODEL_VERSION` 以 `-f022` 结尾；新共享常量（T004 产出，名为 `TENANT_SHARED_CAPABILITY_TYPES`）等于 `{"tool","linsight_skill","dsh_market_plugin","dsh_market_workbench"}`，`SYSTEM_OWNED_RESOURCE_ALLOWLIST` 包含两种新类型；`F048PermissionRuntime.tenant_use_grant` 对新类型的目标返回租户成员 Grant（仿 `test/permission/test_capability_authorization.py` 的 `capability_context`，参数化到新类型）；`migrate_capability_default` 对新类型仍拒绝。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-19
  **依赖**: 无

- [x] **T002**: 授权模型与目录策略登记新类型
  **文件**: `src/backend/bisheng/core/openfga/authorization_model_f048.py`、`src/backend/bisheng/permission/domain/services/catalog_policy.py`
  **逻辑**: 两处 `MIGRATED_RESOURCE_TYPES` 追加两种新类型（带注释说明 F022 与双胞胎关系）；`RESOURCE_ACTION_SCOPES` / `ACTION_RESOURCE_SCOPES` 中 `manage_permission`、`delete` 已按全部类型生成，不额外加 `edit` 等动作；`MODEL_VERSION` 改为 `"f048-v6-app-f118-f022"`，在其上方注释写明本次变化（design 决策 1、10，坑 1）。
  **测试**: T001 中对应断言通过
  **依赖**: T001

- [x] **T003**: 生命周期策略与授权主体接口登记新类型
  **文件**: `src/backend/bisheng/permission/domain/services/resource_lifecycle_policy.py`、`src/backend/bisheng/permission/api/endpoints/grant_subjects.py`
  **逻辑**: `FIXED_CUSTOM_TYPES`、`GRANT_SUBJECT_RESOURCE_TYPES` 追加两种新类型（缺后者时弹窗选不到人，坑 1）。
  **测试**: T001 中对应断言通过
  **依赖**: T001

- [x] **T004**: 共享常量 + 所有者 / Grant 服务接入
  **文件**: `src/backend/bisheng/permission/domain/services/owner_service.py`、`src/backend/bisheng/permission/domain/services/grant_service.py`
  **逻辑**: 在 `resource_lifecycle_policy.py`（owner_service、grant_service、runtime、resource_api 都已依赖的纯策略模块，避免循环导入）定义 `TENANT_SHARED_CAPABILITY_TYPES = frozenset({"tool","linsight_skill","dsh_market_plugin","dsh_market_workbench"})`；`SYSTEM_OWNED_RESOURCE_ALLOWLIST` 加两种新类型；`owner_service.py:138` 与 `grant_service.py:305` 的 `{"tool", "linsight_skill"}` 改用该常量（design 坑 2）。
  **测试**: T001 中对应断言通过；`test/permission/test_capability_authorization.py`、`test_f048_owner_projection.py` 不回归
  **依赖**: T001

- [x] **T005**: runtime 与资源授权接口接入共享常量
  **文件**: `src/backend/bisheng/permission/application/runtime.py`、`src/backend/bisheng/permission/application/resource_api.py`
  **逻辑**: `runtime.py:606`（`authorize_system_owned` 的租户成员 Grant）、`resource_api.py:409`（弹窗 `all_members_*`）、`resource_api.py:647`（允许租户主体授权）改用 `TENANT_SHARED_CAPABILITY_TYPES`；`runtime.py:1154`（`migrate_capability_default`，替换旧 `user:*` 标记）**保持**只允许 `tool`、`linsight_skill`。
  **测试**: T001 全部通过；`test/permission/` 中 capability、grant subjects、skill grant subjects 相关用例不回归
  **依赖**: T004

### Wave 2 — 企业市场后端（适配器、可见性服务、接口）

- [ ] **T006**: 适配器与可见性服务单元测试
  **文件**: `src/backend/test/dsh_market/test_market_permission.py`（新建）
  **逻辑**: 用 `test_market.py` 的 SQLite 内存库 fixture 造数据，F048 runtime 用假对象（记录调用、按预设集合返回可见）。用例：适配器对不存在 / 跨租户 id 拒绝，对已删除插件、无当前版本工作台仍构造目标；列表「先过滤后分页」（可见项分布在多页时页数、`total` 正确，无空页）；单项不可见与不存在抛同一异常；同步策略只保留可见插件且保留可见的已删除插件；`access` 查询对不存在 / 跨租户 / 不可见返回 false；确保登记调用 `reconcile_system_owned_resources`，参数为系统所有 + `("visible",)`，对同一 id 重复调用不改已有授权（假 runtime 记录 MISSING / CURRENT）；存量清单含已删除记录。
  **覆盖 AC**: AC-03, AC-07, AC-08, AC-14, AC-17, AC-18
  **依赖**: 无

- [ ] **T007**: 仓储新增候选查询
  **文件**: `src/backend/bisheng/dsh_market/domain/repository.py`、`src/backend/bisheng/dsh_market/domain/workbench_repository.py`
  **逻辑**: 同步方法，不含权限：`MarketRepository.employee_candidate_ids(tenant, q)`（沿用 `list(employee=True)` 的业务条件，返回有序 id）、`list_by_ids(tenant, ids, page, size)`（按传入顺序分页组装，返回与现有 `list` 相同结构与 `total`）、`permission_record(tenant, plugin_id)`（含已删除）、`all_ids()`（全部租户、全部记录，供存量清单）；`WorkbenchRepository` 对应 `employee_candidate_ids`、`list_by_ids`、`permission_record`、`all_ids`。不改现有方法的行为（坑 13：管理端共用 `list`）。
  **测试**: T006 中仓储相关用例通过；`test/dsh_market/test_market.py`、`test_workbench.py` 不回归
  **依赖**: T006

- [ ] **T008**: 适配器 + 可见性服务
  **文件**: `src/backend/bisheng/dsh_market/domain/permission.py`（新建）
  **逻辑**: `MarketPluginPermissionAdapter` / `MarketWorkbenchPermissionAdapter`（仿 `linsight/domain/services/skill_permission.py`：经 `call` 在线程中读 `permission_record`，不存在或租户不符抛 `PermissionInvalidResourceError`，用 `runtime.get_permission_version` 构造 `VerifiedPermissionTarget`；不按业务状态拒绝，design 决策 5 适配器口径）。`MarketVisibility`：`visible_ids(actor, resource_type, ids)`（`batch_check_business_actions(actions=("visible",))`）、`require_visible(...)`（不可见抛与不存在相同的 `LookupError`，决策 6）、`filter_policies(...)`、`access(...)`、`ensure_registered(tenant_id, resource_type, resource_id, operator_id)`（`reconcile_system_owned_resources(apply=True)`，`action_codes=("visible",)`，决策 3）、`system_owned_inventory(resource_types)`（返回 `SystemOwnedResourceSpec` 元组，供 T015）。只依赖 `permission.application` 导出的接口（C4）。
  **测试**: T006 全部通过
  **依赖**: T005, T007

- [ ] **T009**: 适配器注册
  **文件**: `src/backend/bisheng/api/services/f048_permission_runtime.py`
  **逻辑**: 在 `build_f048_resource_composition` 中 `registry.register("dsh_market_plugin", ...)`、`registry.register("dsh_market_workbench", ...)`（API 与 worker 共用，坑 3）。
  **测试**: T010 中经真实注册表解析新类型的用例通过；`test/permission/test_resource_type_registry.py` 不回归
  **依赖**: T008

- [ ] **T010**: 市场接口测试
  **文件**: `src/backend/test/dsh_market/test_market_permission_api.py`（新建）
  **逻辑**: TestClient + 依赖覆盖（`market_actor` / `market_admin`、`get_market_service`、可见性服务假对象）。员工侧：`/catalog` 分页只含可见项；插件下载、工作台详情 / 截图 / 下载对不可见项返回与不存在相同；`/sync` 的 `policies` 只含可见项；`POST /workbenches/access` 返回布尔映射、超过 500 个 id 返回 422；新获得权限后再次请求即可见。管理端：`/admin/plugins`、`/admin/workbenches` 不过滤；插件导入、插件续传、工作台导入、工作台续传成功后各调用一次 `ensure_registered`，失败的导入不调用，`ensure_registered` 抛错时接口返回错误；删除后重新导入同一包时 `ensure_registered` 收到同一 id。不受影响：`/capabilities`、`/admin/install-policy` 响应不变。
  **覆盖 AC**: AC-03, AC-06, AC-07, AC-08, AC-09, AC-10, AC-15, AC-17, AC-18
  **依赖**: T008

- [ ] **T011**: 市场接口接入可见性服务
  **文件**: `src/backend/bisheng/dsh_market/api/endpoints.py`
  **逻辑**: 员工侧 7 个入口（`catalog`、插件 `artifact`、`sync`、`workbenches`、`workbench_detail`、`workbench_screenshot`、`workbench_artifact`）按 design 决策 5 叠加可见过滤（列表：候选 id → `visible_ids` → `list_by_ids` 分页）；新增 `POST /workbenches/access`（请求 `{"workbench_ids": [...]}`，≤ 500，响应 `{id: bool}`，§4.2）；4 个导入完成入口在结果状态为成功时调用 `ensure_registered`（插件取结果中的插件 id，工作台取工作台 id）。管理端接口不变。
  **测试**: T010 全部通过
  **依赖**: T009, T010

### Wave 3 — 升级脚本

- [ ] **T012**: 发布脚本测试
  **文件**: `src/backend/test/permission/test_publish_authorization_model_change_f022.py`（新建）
  **逻辑**: 对 `scripts/publish_authorization_model_change.py` 的纯函数部分：动作作用域补齐只为 Catalog 中缺失的类型按代码 `RESOURCE_ACTION_SCOPES` 追加、不删除也不改其他类型现有作用域；重建自定义模型时 `visibility_only_resource_types`、`visibility_level`、`retired_use_level_floor` 原样带上；`--verify` 在缺新类型作用域、或已存模型与推导不一致时失败并给出原因，一致时通过；`--verify` 与默认预览均不写入（假 state 记录写调用）。参考 `test_authorization_model_publish_markers.py` 的构造方式。
  **覆盖 AC**: AC-04, AC-19, AC-20
  **依赖**: T002

- [ ] **T013**: 发布脚本修正
  **文件**: `src/backend/scripts/publish_authorization_model_change.py`
  **逻辑**: 抽出纯函数 `_target_actions(before_actions)`（替换写死 `"linsight_skill"`）与 `_custom_selections(before_models)`（带三项可见字段，同 `catalog_api.py`）；新增 `--verify`（只读：加载 CURRENT Catalog 走与运行时相同的一致性校验 `control_state`，检查两种新类型的作用域与模型校验值，输出 JSON）；更新文件头用法说明（design 决策 7 修正 1，坑 5、6、7）。
  **测试**: T012 全部通过；`test_authorization_model_publish_markers.py`、`test_contextual_model_publication.py` 不回归
  **依赖**: T012

- [ ] **T014**: 补登记脚本测试
  **文件**: `src/backend/test/permission/test_reconcile_system_owned_resource_types.py`（新建）
  **逻辑**: `scripts/reconcile_f048_system_owned_resources.py` 的 `parse_args`：默认 `--resource-type` 为 `["tool"]`，可多选两种新类型，非法值报错；清单组合：选两种新类型时只调用市场清单、不调用工具清单，输出 `selected_resource_types` 与所选一致；对账结果中已登记项（CURRENT）不被改动、缺失项（MISSING）被登记（用假 runtime）。
  **覆盖 AC**: AC-04, AC-20
  **依赖**: T008

- [ ] **T015**: 补登记脚本支持新类型
  **文件**: `src/backend/scripts/reconcile_f048_system_owned_resources.py`、`src/backend/bisheng/api/services/f048_system_resource_bootstrap.py`
  **逻辑**: 脚本加 `--resource-type`（choices: `tool`、`dsh_market_plugin`、`dsh_market_workbench`，可重复，默认 `tool`）；`f048_system_resource_bootstrap.py` 新增按类型组合清单的函数，市场两类调用 T008 的 `system_owned_inventory`；现有 `load_system_owned_resource_inventory()`（全新安装启动与 web fetch 工具补投影在用）行为不变（design 决策 7 修正 2，坑 8、16）。
  **测试**: T014 全部通过；现有 system-owned 相关测试不回归
  **依赖**: T014

- [ ] **T016**: 升级说明
  **文件**: `features/v3.1.0-beta2/022-dsh-market-permission/upgrade-guide.md`（新建）、`docs/architecture/10-permission-rbac.md`
  **逻辑**: 升级说明写维护窗口完整步骤（停全部进程：API / Celery×3 / Beat / Linsight worker → 一致备份业务库与 OpenFGA 存储库 → 发布预览 → 发布执行 → 补登记预览 → 补登记执行 → `--verify` → 启动全部进程 → 验收），每步的命令、预期输出、失败处理，回滚步骤（恢复两库 + 回退镜像），以及「只发程序不升级」的后果；`10-permission-rbac.md` §10.1 开头加一段：F118 之后新增资源类型使用 `publish_authorization_model_change.py` + `reconcile_f048_system_owned_resources.py`，不要用本节脚本（原因见 F022 design 坑 5）。
  **覆盖 AC**: AC-20
  **依赖**: T013, T015

### Wave 4 — 管理后台（platform）

- [ ] **T017**: 前端资源类型登记
  **文件**: `src/frontend/platform/src/components/bs-comp/permission/types.ts`、`src/frontend/platform/src/controllers/API/permission.ts`
  **逻辑**: 两处 `ResourceType` 联合类型追加两种新类型（两处为双胞胎，注释已要求同步）。
  **手动验证**: `npm run type-check`（或项目约定的 tsc 命令）通过
  **依赖**: T003

- [ ] **T018**: 企业插件列表权限按钮
  **文件**: `src/frontend/platform/src/pages/BuildPage/dsh/PluginMarketPage.tsx`、`src/frontend/platform/src/pages/BuildPage/dsh/PluginMarketPage.test.tsx`
  **逻辑**: 每行操作区加「权限」按钮，打开 `PermissionDialog`（`resourceType="dsh_market_plugin"`、`resourceId`、`resourceName=display_name`、`allowAllMembers`）；已删除的行不显示按钮；文案走 i18n（复用 permission 命名空间已有「权限」类键，无则在 zh-Hans / en-US / ja 补齐）；不直接调 HTTP（C7）。测试断言按钮显示条件与弹窗参数。
  **覆盖 AC**: AC-01, AC-06
  **手动验证**: 本机管理后台 `/dsh` → 企业插件 → 点「权限」→ 取消全企业可见、授权部门 D1 → 重开弹窗显示 D1
  **依赖**: T011, T017

- [ ] **T019**: 企业工作台列表权限按钮
  **文件**: `src/frontend/platform/src/pages/BuildPage/dsh/WorkbenchMarketSection.tsx`、对应测试文件（`WorkbenchMarketSection.preview.test.tsx` 同目录新增或扩展）
  **逻辑**: 同 T018，`resourceType="dsh_market_workbench"`。
  **覆盖 AC**: AC-02, AC-06
  **手动验证**: `/dsh` → 企业工作台 → 「权限」→ 只授权用户 EC → 重开弹窗显示 EC
  **依赖**: T011, T017

### Wave 5 — 桌面端（bisheng-desktop 仓库）

- [ ] **T020**: 插件收回原因测试
  **文件**: `test/enterprise-market.test.ts`（现有，`createMarketController` / `createManagedMarketSource` 的测试）
  **逻辑**: 同步回执中不含已安装插件 → 停止运行、`enabled=false`、原因码为 `revoked`；插件 `disabled` → 原因码为管理员停用；版本不匹配 → 原有原因；离线 → 停止运行、保留 `enabled`、无 `revoked`；恢复授权后手动启用成功并清除原因码；未恢复时启用失败。
  **覆盖 AC**: AC-11, AC-13, AC-14
  **依赖**: 无

- [ ] **T021**: 插件收回原因实现
  **文件**: `packages/dsh-desktop-enterprise/market.js`、`packages/dsh-desktop-enterprise/managed-market.js`
  **逻辑**: `market.js` 的 `enforce()` 在线时按「策略中无此插件 / disabled / 版本不匹配」写入记录字段 `reason`（`revoked` / `disabled` / `version`）；`startRecord` 成功时清除。`managed-market.js` 的 `listBundles()` 现把 `record.error` 映射为插件页卡片的 `error`，新增：`reason === 'revoked'` 时映射为 `{ code: 'authorization-revoked', diagnostic: <按界面语言的「管理员已收回使用权限」/「Your administrator revoked access」> }`（design 决策 8）。
  **测试**: T020 全部通过；企业插件相关现有测试不回归
  **依赖**: T020

- [ ] **T022**: 企业工作台核对测试
  **文件**: `test/` 下新建 `enterprise-workbench-access.test.mjs`
  **逻辑**: 在线同步完成后对本机 `source: 'enterprise'` 的已安装工作台调用 `POST /api/v1/dsh/market/workbenches/access`；返回 false → 经 Plugin Manager 停用并标记 `revoked`；返回 true → 不变；请求失败 / 404 / 离线 → 不变；标记 `revoked` 的工作台手动启用前再查，true 才启用并清除标记、false 拒绝并提示。
  **覆盖 AC**: AC-12, AC-13, AC-14
  **依赖**: 无

- [ ] **T023**: 企业工作台可见性查询客户端
  **文件**: `packages/dsh-desktop-enterprise/workbench-market.js`、`packages/dsh-desktop-enterprise/workbench-market.d.ts`
  **逻辑**: `createWorkbenchMarketController` 新增 `checkAccess(ids)`：校验 id 为 32 位十六进制、≤ 500，经 `accountController.marketRequest` 请求 `POST /workbenches/access`，解析为 `{ [id]: boolean }`；非 200 / 结构不符抛错（由调用方当作「保持现状」）；`applyEnterpriseWorkbenchMarket` 暴露给工作台模块使用（与现有详情、下载同一账号校验）。
  **测试**: T022 中客户端部分通过
  **依赖**: T022

- [ ] **T024**: 企业工作台核对、停用与恢复
  **文件**: `packages/dsh-desktop-workbenches/index.js`（宿主侧）、`packages/dsh-desktop-workbenches/client.js`（界面侧）
  **逻辑**: `index.js` 新增路由 `/api/desktop-workbenches/enterprise-access-check`：读取 `local-installs.json` 中 `source: 'enterprise'` 的记录，调用 T023 的 `checkAccess`，false → 经 Plugin Manager 停用并在记录上写 `revoked: true`，true → 清除标记；请求失败直接返回「保持现状」；企业工作台启用前同样核对。`client.js` 在现有企业账号同步时机（`dsh-desktop:enterprise-account-changed`、窗口 `focus` 触发的 `sync`）调用该路由，并对 `revoked` 的工作台显示「管理员已收回使用权限」、入口不可打开（design 决策 9）。
  **测试**: T022 全部通过；`test/enterprise-workbench-market.test.ts` 等现有测试不回归
  **依赖**: T023

### Wave 6 — 联调、升级演练与收尾

- [ ] **T025**: 本机联调与升级演练
  **文件**: 无代码改动；结果记入本文件「验证记录」
  **逻辑**: 按 design §7 手动验证 8 步执行（独立 `f022-` 中间件、升级前代码造数据、维护窗口升级、桌面开发版两个员工账号、收回 / 恢复 / 删除重导入、回滚演练），对照 test-cases.md 中 TC-MKP-001 ~ 033 记录结果。
  **覆盖 AC**: AC-04, AC-05, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-16, AC-19, AC-20
  **依赖**: T011, T016, T018, T019, T021, T024

- [ ] **T026**: 回归与达梦
  **文件**: 无代码改动
  **逻辑**: `scripts/arch-guard.sh`；`test/permission/`、`test/dsh_market/` 全量与 `feat/3.1.0-beta2` 干净基线对比新增失败为 0；platform vitest 相关目录；桌面全量 `npm test`；确认无新增 DDL、新 SQL 只用 SQLModel 表达式（C2 静态）；请同事在达梦环境执行补登记预览 / 执行与 TC-MKP-034。
  **覆盖 AC**: AC-21
  **依赖**: T025

---

## 验证记录

（实现后填写：每项检查的命令、结果、对比基线；未执行的写明原因）

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认（§3 第四个 ★），再记录。

- 拆解时：确保登记与存量补登记改用现有对账助手 / 脚本 → design 决策 3、7（修订历史 2026-11-16 实现细节条）
