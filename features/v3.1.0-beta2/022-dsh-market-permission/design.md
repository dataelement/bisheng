# Design: 企业插件与企业工作台按用户 / 部门 / 用户组授权

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（目标、AC、边界）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动
>
> 调整原则（详见 `docs/SDD-Guide.md` §3-§4）：
> - 实现变化 → **覆盖更新本文档**，只留"今天的状态"、不留旧快照；但每个决策保留"为什么 + 被否方案"和坑（护栏，见 §3/§5）
> - **偏差分级**：推翻已 ★ 确认的决策 → 停下与用户重新确认；纯实现细节 → 直接改 design，不必停
> - `tasks.md`「实际偏差记录」只留一行指针，论证在本文档，不重复

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md) · [版本契约](../release-contract.md)
**版本**: v3.1.0-beta2
**最后更新**: 2026-11-16（设计评审修订，实现前）

---

## 1. 目标与非目标

- **目标**：把企业插件、企业工作台接入 F048 统一资源权限，成为两种新的可授权资源。管理员用现有权限弹窗按用户 / 部门 / 用户组授权；员工侧（Desktop 的目录、详情、截图、下载、同步）只放行有「可见」权限的项；桌面端对失去权限的已安装项自动停用。
- **非目标**：
  - 不改云端工作台（托管应用 `app`，已接入 F048）。
  - 不改公开市场与「允许安装第三方插件 / 工作台」开关（`dsh_market_install_policy`）。
  - 不新增权限动作或多级权限；不做按项委派管理（管理仍是租户管理员）。
  - 不新建业务表；不改企业插件、企业工作台对象本身的导入 / 更新 / 删除规则（归 F055 / F019）。
  - 不改删除对已安装客户端的现有行为（删除的插件、工作台在已安装的设备上继续可用，见决策 8 / 9）。

---

## 2. 关键约束

遵循 `docs/constitution.md` C1–C8（尤其 C4：业务适配器加载记录并构造 `VerifiedPermissionTarget`，判定只走 F048 runtime；资源创建 / Grant 变更先落持久投影再写 OpenFGA），以及 [版本契约](../release-contract.md)。本功能特有的约束：

- **改 F048 授权模型 = 已部署环境必须停服维护**。代码里的模型校验值与资源类型清单一变，未执行升级的环境所有进程都拒绝发 ready 心跳，**全部**权限判定 503（`docs/architecture/10-permission-rbac.md` §10.1）。发布脚本检测到运行中的进程心跳就拒绝执行，所以上线需要维护窗口：停服 → 一致备份 → 发布 → 补登记 → 校验 → 启动。Helm 初始化遇到已有环境模型不一致会直接报错，不会自动升级；Drone 自动部署（`release` → 192.168.106.116）也不跑这一步。
- **只保留「可见」一个动作**（F118：全平台移除 use）。可见即可安装、启用、使用。
- **默认全企业可见必须可撤销**：用租户成员的普通 Grant，不能用 `user:*` 公共标记（后者撤销普通 Grant 后仍对全员可见，是工具 / 技能接入时修掉的根因，见 `features/local/tools-skills-authorization/design.md`）。
- **标识**：企业插件、企业工作台主键是 32 位十六进制字符串（`dsh_market_plugin.id`、`dsh_market_workbench.id`）；F048 `resource_id` 是字符串，可直接使用。两张表**没有创建人字段**（只有导入记录 `actor_id`）。
- **规模**：单租户企业插件 / 工作台数量为几十到几百；员工侧列表与同步策略一次批量权限检查即可。
- **双库**：不新增业务表与 DDL；授权数据只写 F048 既有表；脚本中的 SQL 须对 MySQL 与 DM8 都成立（C2）。
- **市场仓储层是同步代码**（`dsh_market/domain/*` 的 `def`，经 `call(...)` 在线程中执行），F048 检查是异步接口，权限逻辑不能塞进同步仓储事务。

---

## 3. 方案对比与选定

### 决策 1：资源建模——新增两种 F048 资源类型

- **备选**：
  - A. 新增 `dsh_market_plugin`、`dsh_market_workbench` 两种类型（与表名一致）— 语义清晰、各自独立授权；需在多处「双胞胎清单」同步登记，并付出一次授权模型升级的运维成本。
  - B. 一种合并类型 `dsh_market_item` — 少登记一处，但两类 id 空间、管理页面、删除语义不同，适配器要再分支，权限弹窗的资源名也混在一起。
  - C. 复用 `tool` / `linsight_skill` 类型 — id 冲突、语义错误，否决。
- **选定**：A。
- **原因**：与现有「一个业务对象一种类型」一致（tool、linsight_skill、app 各自独立）。任何新类型都必须改 OpenFGA 模型（元组的 object 类型必须在模型中定义），B 也省不掉升级成本。
- **何时该重新考虑**：出现第三类市场对象且规则与前两者完全相同时，再评估合并。

### 决策 2：默认全企业可见——可撤销的租户成员 Grant

- **备选**：
  - A. 登记时生成「所属租户成员」普通 Grant（`PermissionRuntime.tenant_use_grant`，与内置工具、企业技能相同）。
  - B. 写 `user:*` 公共可见标记 — 无法通过撤销普通 Grant 收回，否决。
- **选定**：A。
- **原因**：管理员「取消全企业可见」就是撤销这条 Grant；资源授权接口对这类资源返回 `all_members_model_key` / `all_members_sources`，权限弹窗用 `allowAllMembers` 现成支持（内置工具、技能管理已在用）。
- **何时该重新考虑**：F048 引入新的「全员」表达方式时跟随迁移。

### 决策 3：登记方式与时机——系统所有资源，导入成功后在异步层「确保登记」

- **备选**：
  - A. **系统所有**：`authorize_system_owned(action_codes=("visible",))`，无个人所有者，附带可撤销的租户成员 Grant（与内置工具相同）。在 4 个导入完成入口（插件导入、插件导入续传、工作台导入、工作台导入续传）成功后，于异步应用层「确保登记」：调用现有 `permission/application/system_resource_reconcile.py` 的 `reconcile_system_owned_resources(apply=True)`（内置技能 `ensure_builtin_skill_permission` 同样用法）——未登记（MISSING）才登记；已登记（CURRENT，包括删除后重新导入恢复）不做任何改动；中断留下的未完成登记按原幂等键续完。
  - B. `authorize_created`，以导入的管理员为所有者 — 两张表没有创建人字段，存量补登记无从得知所有者；所有者授权受保护、不可撤销，管理员身份被收回后仍能在员工侧看到；还会引入按项所有者，与「不做按项委派管理」矛盾。
  - C. 在同步仓储 `finish_import` 事务里登记 — 跨同步 / 异步边界，且违反 C4「业务行先落库，再走投影」的顺序。
  - D. 启动时扫描补登记 — 现有对账助手只补缺失、不会恢复撤销，但存量补登记属于升级数据迁移：要求模型已发布，C4 也要求一次性迁移不进入启动或正常请求路径；且全量扫描放在每次启动上没有必要。
- **选定**：A。存量数据由维护窗口内的补登记脚本处理（决策 7），不在启动流程里补。
- **原因**：市场对象由企业（租户管理员）统一管理，与内置工具「系统所有、租户管理员管理授权」的语义一致；新建与存量走同一个对账助手，结果一致。对账助手的幂等键按（租户、类型、id）固定（`f048:system-bootstrap:...`），并发重复调用不会重复登记。
- **登记失败**：导入记录已落库但未登记 → 对员工全不可见（失败即关闭），导入接口返回 F048 的错误；管理员重试导入（同一文件幂等，F019 AC-01）会再次触发确保登记。
- **何时该重新考虑**：市场对象引入个人所有者或「按项委派管理」时，改为 B；市场增加导入以外的创建入口时，同样接入确保登记。

### 决策 4：删除不清授权，恢复沿用原授权（spec AC-17 / AC-18，选项 A）

- **备选**：
  - A. 删除只改业务状态（插件 `deleted=True, current_version_id=NULL`；工作台 `current_version_id=NULL`，均保留记录），不删除 F048 资源与 Grant；员工侧继续由现有业务状态过滤。重新导入复用原记录与原 id，授权自然保留。
  - B. 删除时同时删除 F048 资源，恢复时重新登记 — 会丢掉删除前的授权，违背已确认的选项 A。
- **选定**：A。
- **原因**：现有导入按 `(tenant_id, name)`（插件，含已删除行）/ 按身份（工作台）复用记录，恢复时 id 不变；保留 F048 资源即可满足 AC-18。删除后列表、详情、下载已由现有业务条件拒绝（下载要求 `current_version_id` 等于请求版本），满足 AC-17，无需新逻辑。
- **何时该重新考虑**：若市场改为物理删除，需要同步删除 F048 资源（走资源删除投影）。

### 决策 5：员工侧过滤放在市场接口的异步应用层，先过滤后分页

- **备选**：
  - A. 新增 `dsh_market` 内的异步可见性服务：员工侧 7 个入口（插件目录、插件下载、同步策略、工作台列表、详情、截图、下载）在现有业务条件之后叠加「可见」过滤；列表先取符合业务条件的全部候选 id，经 `batch_check_business_actions(actions=("visible",))` 过滤后再分页组装；单项入口按单项检查；同步策略对整份列表过滤。管理端接口不经过它。
  - B. 沿用仓储的数据库分页，取回一页后再过滤 — 页面条数不足甚至空页，`total` 失真。
  - C. 把可见 id 集合作为参数传进仓储，在 SQL `IN (...)` 里分页 — 需先批量检查全部候选，成本与 A 相同；作为 A 的实现手段可选。
- **选定**：A（分页可用 C 的 `IN` 方式实现）。
- **原因**：保持仓储同步、无权限依赖（C1 分层）；分页正确；业务状态（删除、停用、无当前版本）仍由原代码负责，权限只做叠加。
- **适配器口径**：按 id + 租户加载记录，**包括已删除 / 已停用 / 无当前版本的记录**，只在记录不存在或租户不符时拒绝。否则同步策略里已删除插件会被权限过滤掉，改变「删除后已安装的继续可用」的现状（坑 10）。
- **何时该重新考虑**：单租户候选数达到数千、批量检查成为瓶颈时，改为 F048 的可见列表查询。

### 决策 6：员工无权限时的响应——与「不存在」相同

- **备选**：
  - A. 详情、截图、下载对无权限项返回与已删除 / 不存在相同的响应（现有 not found），不返回名称、描述、文件。
  - B. 返回明确的「无权限」 — 向从未获权的人暴露该项存在。
- **选定**：A。
- **原因**：满足 spec AC-07 / AC-08「不返回其文件、名称或描述」；桌面端已有「不可用」处理路径（F019 desktop-workbench-api 的错误处理表）；不新增错误码（C5）。
- **何时该重新考虑**：产品要求员工能「申请权限」时，需要区分并返回可申请的标识。

### 决策 7：上线方式——修正现有发布脚本与补登记脚本，回滚靠升级前一致备份

- **备选**：
  - A. 用 `scripts/publish_authorization_model_change.py`（v6 技能接入时使用）发布新模型，并经 `CatalogService` 草稿发布补动作作用域、**重新推导标准权限模型**；用 `scripts/reconcile_f048_system_owned_resources.py`（系统所有资源对账，现只处理内置工具）把存量企业插件、企业工作台登记为全企业可见。两个脚本都需要扩展（见下）。
  - B. 扩展 §10.1 的 `upgrade_f048_authorization_model.py`（F054 `app` 专用，自带 plan / apply / verify / rollback）— 它直接插入作用域行、不重新推导标准权限模型。F118 之后「查看者」标准模型的「仅可见资源类型」由代码中的资源类型清单推导，新增类型后已存储的模型行与推导结果不一致，启动校验报 Catalog 不一致，整站 503（坑 5）。否决。
  - C. 再写一个一次性脚本 — 第三份发布逻辑，否决。
  - 补登记的备选：`scripts/migrate_capability_authorization.py`（v6 把工具 / 技能的公共标记迁成普通 Grant）— 早于 F118：要求 id 为纯数字、系统所有登记带已退役的 `use`、按创建人登记，都不适用于本特性，否决（坑 8）。
- **选定**：A，并做以下修正：
  1. **发布脚本**：动作作用域改为按代码 `RESOURCE_ACTION_SCOPES` 为 Catalog 中尚未出现的资源类型补齐（只增不减，不改其他类型现有作用域），替换写死的 `"linsight_skill"`；重建自定义权限模型时带上 `visibility_only_resource_types`、`visibility_level`、`retired_use_level_floor`（与 `catalog_api.py` 一致；现脚本早于 F118，漏带会改坏 F118 生成的「仅可见」自定义模型，坑 6）；新增只读 `--verify`：按运行时同一套校验加载 CURRENT Catalog，确认新类型的作用域、模型校验值、标准模型推导一致。
  2. **补登记脚本**：`reconcile_f048_system_owned_resources.py` 新增 `--resource-type`（可选 `tool`、`dsh_market_plugin`、`dsh_market_workbench`，默认仍只有 `tool`，不改现有用法）；资源清单由 `api/services/f048_system_resource_bootstrap.py` 按类型组合，市场两类的清单由 `dsh_market` 提供（全部记录，包括已删除，使「每条市场记录都已登记」成立，恢复时沿用）。对账助手对已登记项不做改动（保留管理员撤销）。
  3. **回滚**：维护窗口开始时对业务库与 OpenFGA 存储库做一致备份；失败时恢复两库备份并回退到上一版镜像。
- **原因**：A 是唯一走 `CatalogService` 正规发布路径、会重新推导标准模型的现有工具；修正后下次新增类型只需改代码常量。回滚不做「反向发布」：反向发布要恢复旧模型、旧 Catalog，还要处理旧代码不认识的新类型 Grant 行，复杂且难验证；最近一次模型变更 F118 也采用停服 + 一致备份 + 恢复备份的回滚方式。
- **何时该重新考虑**：F048 提供运行期作用域变更（`CatalogChangeType` 支持 `resource_types`）或正式的 Catalog 回滚命令时，改用它们。

### 决策 8：桌面端插件——沿用同步策略停用，补「收回」原因

- **备选**：
  - A. 服务端同步策略只返回可见插件；桌面端 `market.js` 的 `enforce()` 对「在线且策略中找不到」的已安装插件停止运行并把 `enabled` 置为 false（现状）。新增：记录停用原因码，界面显示「管理员已收回使用权限」，与管理员停用、版本不匹配区分。
  - B. 新增独立的收回通知通道 — 重复造轮子。
- **选定**：A。
- **原因**：现有机制已满足 AC-11 的停用与保留安装；`enabled=false` 持久化，恢复授权后需员工手动启用，满足 AC-13；离线时只停运行实例、保留 `enabled`，恢复在线后继续，即 AC-14「插件保持现有离线行为」。今天同步策略包含租户全部插件（含已删除），因此「在线且策略中找不到」在本特性之后**只**意味着不可见，提示语准确。
- **何时该重新考虑**：服务端物理删除插件或策略改为排除已删除插件时，需要服务端给出原因码以区分「删除」与「收回」。

### 决策 9：桌面端企业工作台——新增「已安装项可见性」查询接口，在线时核对

- **备选**：
  - A. 新增员工侧接口 `POST /api/v1/dsh/market/workbenches/access`：请求体为本机已安装的企业工作台 id 列表（上限 500），只返回每个 id 是否可见（`true` / `false`；不存在、跨租户、不可见均为 `false`）。桌面端在线并完成企业账号同步时调用；`false` → 经 Plugin Manager 停用并记录「已收回」；请求失败（网络、身份、服务错误、旧服务端 404）→ 保持现状（AC-14）；恢复授权后由员工手动启用（AC-13），启用前再查一次。
  - B. 逐个请求工作台详情 — 删除后的工作台详情也返回不存在，与「不可见」无法区分，会把已删除的工作台也停用，改变 F019「删除不卸载客户端内容」下的现有行为，提示语也不准确。
  - C. 拉取完整工作台列表做差集 — 列表分页且排除已删除，同样无法区分删除与收回，也无法区分「这一页没有」与「拉取失败」。
  - D. 不处理 — 不满足 AC-12。
- **选定**：A。
- **原因**：可见性与插件同步策略同口径（按 F048 可见判定，删除不影响），删除的工作台继续可用、被收回的停用，两者与插件一致；只返回布尔值，对从未获权或不存在的 id 一律 `false`，不泄露存在性（决策 6）。
- **何时该重新考虑**：服务端为工作台提供与插件一致的周期同步策略时，合并到同步机制。

### 决策 10：授权模型版本名——按命名规则追加后缀

- **备选**：
  - A. 在现有 `f048-v6-app-f118` 后追加本特性后缀 `-f022`。
  - B. 升为 `f048-v7` — 编号由发版线统一分配，分支不能占用。
- **选定**：A。
- **原因**：`authorization_model_f048.py` 注释规定编号由发版线管理、分支只追加后缀；运行时只认校验值，名称仅作标签。
- **何时该重新考虑**：发版线合并时统一改名的，以发版线为准（不影响校验值）。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

**员工侧（今天，全部只校验租户与业务状态，不做个人权限检查）**
- 插件目录：`GET /api/v1/dsh/market/catalog` → `MarketService.list_plugins(employee=True)` → `MarketRepository.list`（未删除、未停用、有当前版本，**数据库分页**）。
- 插件下载：`GET /dsh/market/plugins/{plugin_id}/versions/{version_id}/artifact` → `MarketService.download`（要求未停用且 `current_version_id` 等于请求版本）。
- 设备同步：`POST /dsh/market/sync` → `MarketService.synchronize` → `MarketRepository.policies`（**租户全部插件，含已删除**，每项带 `disabled`、`revision`、`current_version_id`、发布过的版本）；桌面端每 60 秒同步一次。
- 工作台：`GET /dsh/market/workbenches`、`/workbenches/{id}`、`/workbenches/{id}/versions/{vid}/screenshots/{image_id}`、`/workbenches/{id}/versions/{vid}/artifact` → `WorkbenchService`（`current_version_id` 非空即可见；**管理端与员工端共用 `list`**）。

**管理侧（今天）**
- 导入：插件 `POST /dsh/market/admin/imports`、续传 `/admin/imports/{task_id}/resume` → `validate_import` → `MarketRepository.finish_import`（按 `(tenant_id, name)` 查找，含已删除行）；工作台 `POST /dsh/market/admin/workbenches/imports`、续传 `/admin/workbenches/imports/{task_id}/resume`，按身份复用记录。导入在请求内同步完成。
- 删除：插件 `DELETE /admin/plugins/{id}` → `deleted=True, current_version_id=NULL`；工作台 `DELETE /admin/workbenches/{id}` → `current_version_id=NULL`。均保留记录。
- 管理页入口：管理后台 `/dsh`（`DshPage`，菜单权限 `sys`）中的企业插件、企业工作台。

**F048 授权（参照内置工具，今天）**
- 适配器注册：`api/services/f048_permission_runtime.py` 的 `build_f048_resource_composition`（API 与 worker 共用）。
- 登记：`authorize_system_owned(...)` → `OwnerService.project_created`（系统所有 + 租户成员 Grant）。
- 判定：`batch_check_business_actions(user, resource_type, resource_ids, actions=("visible",))`（如 `linsight/domain/services/user_skills.py`）。
- 弹窗：`resource_api` 对可撤销全员类型返回 `all_members_*`，前端 `PermissionDialog allowAllMembers`（如 `pages/BuildPage/tools/index.tsx`）。

**本特性之后**
- 员工侧 7 个入口叠加可见过滤（决策 5）；新增工作台可见性查询接口（决策 9）；4 个导入完成入口成功后确保登记（决策 3）；管理页加权限按钮；桌面端插件补收回原因、工作台新增在线核对（决策 8 / 9）。

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| F048 `resource_type` | `dsh_market_plugin` / `dsh_market_workbench` | 本特性新增的资源类型 | 权限弹窗、授权 API、OpenFGA 模型 |
| F048 `resource_id` | 32 位十六进制字符串 | 即 `dsh_market_plugin.id` / `dsh_market_workbench.id` | 同上 |
| 同步回执 `policies[]` | 现有结构不变 | 只包含该员工可见的插件（含可见但已删除的）；不可见插件**不出现** | 桌面端 `market.js` `authorized()` / `enforce()` |
| `POST /dsh/market/workbenches/access` 请求 | `{"workbench_ids": ["<32 hex>", ...]}`，≤ 500 | 本机已安装的企业工作台 | 服务端 |
| 同上 响应 `data` | `{"<id>": true \| false}` | 不存在 / 跨租户 / 不可见均为 `false` | 桌面端 `dsh-desktop-workbenches` |
| 员工侧详情 / 截图 / 下载对不可见项的响应 | 与不存在相同 | 不返回名称、描述、文件 | 桌面端市场与工作台客户端 |
| 桌面端插件安装记录 `reason` | `revoked` / `disabled` / `version` | 在线同步确认后写入；授权恢复后清除（插件保持停用，由员工手动启用） | 「设置 → 插件 → 来自企业」页签显示「管理员已收回使用权限」 |
| 桌面端企业工作台安装记录（`<工作台数据目录>/enterprise-installs.json`，新增） | `{ <企业工作台 id>: { id, pluginName, version, installedAt, revoked? } }` | 安装成功时写入；核对确认不可见时 `revoked: true` 并经 Plugin Manager `setBundleEnabled(name, false)` 停用 | `dsh-desktop-workbenches`（核对路由、卡片提示、启用前复核） |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `core/openfga/authorization_model_f048.py`（`MIGRATED_RESOURCE_TYPES`、`RESOURCE_ACTION_SCOPES`、`MODEL_VERSION`）与 `permission/domain/services/catalog_policy.py`、`resource_lifecycle_policy.py`、`permission/api/endpoints/grant_subjects.py` | 登记新类型（双胞胎清单须同时改） | 不含业务规则 |
| 「可撤销全员 / 系统所有」类型集合：`permission/application/runtime.py`（`authorize_system_owned`、`migrate_capability_default`）、`resource_api.py`（弹窗 `all_members_*`、租户主体授权校验）、`domain/services/grant_service.py`、`domain/services/owner_service.py`（`SYSTEM_OWNED_RESOURCE_ALLOWLIST` 及系统所有分支） | 加入两种新类型，并集中为一个共享常量 | `migrate_capability_default`（替换旧 `user:*` 标记）不对新类型开放 |
| `dsh_market` 新增权限适配器 | 按 id + 租户加载记录（含已删除），构造 `VerifiedPermissionTarget` | 不查 OpenFGA、不判定、不按业务状态拒绝（C4，决策 5） |
| `dsh_market` 新增异步可见性服务 | 员工侧过滤、先过滤后分页、单项检查、可见性查询、导入后确保登记 | 不改仓储的同步事务 |
| `dsh_market/api/endpoints.py`、`utils/http_middleware.py`（桌面令牌路由白名单） | 员工侧 7 个入口改走可见性服务；新增 `workbenches/access` 并登记到桌面令牌白名单；4 个导入完成入口成功后确保登记 | 管理端列表不过滤 |
| `scripts/publish_authorization_model_change.py`、`scripts/reconcile_f048_system_owned_resources.py`（清单组合在 `api/services/f048_system_resource_bootstrap.py`） | 维护窗口内发布模型、补作用域、重推导标准模型、校验；存量补登记 | 不在启动流程中执行；不负责停服与备份；不碰 `migrate_capability_authorization.py` |
| 前端 `pages/BuildPage/dsh/PluginMarketPage.tsx`、`WorkbenchMarketSection.tsx`、`components/bs-comp/permission/types.ts` | 权限按钮 + `PermissionDialog`（`allowAllMembers`） | 不直接调 HTTP（C7，经 controllers API） |
| 桌面 `packages/dsh-desktop-enterprise/market.js`、`client.js` | 插件停用原因码；「来自企业」页签显示收回提示 | 不改离线行为；不在服务端拼接展示文案 |
| 桌面 `packages/dsh-desktop-enterprise/workbench-market.js`、`index.js` | `checkAccess(ids)`；经 `enterpriseWorkbenchPackages.access` 提供给工作台插件 | — |
| 桌面 `src/main/enterprise/enterprise-market.ts` | 主进程只转发白名单内的企业市场请求；放行 `workbenches/access` 并校验请求体只含 ≤ 500 个工作台 id | — |
| 桌面 `packages/dsh-desktop-workbenches/enterprise-access.mjs`、`index.js`、`client.js` | 记录「企业 id ↔ 插件包名」；`/api/desktop-workbenches/enterprise-access-check` 核对并停用；账号同步时触发；卡片提示；启用前复核 | 离线或请求失败时不停用；不卸载、不删数据 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 资源类型清单有多份「双胞胎」（授权模型、目录策略、生命周期策略、授权主体接口），注释要求同时改 | 漏一处：写元组 400，或读目录直接抛错 | 决策 1；§4.3 第一行 |
| 2 | 「可撤销全员 / 系统所有」类型集合 `{"tool", "linsight_skill"}` 写死在 runtime、resource_api、grant_service、owner_service 共 7 处 | 漏一处：登记时报 `PermissionInvalidResourceError`、弹窗没有「全企业可见」、或撤销全员授权被拒 | §4.3 第二行，集中为共享常量 |
| 3 | 适配器注册表 API 与 Celery / Linsight worker 共用 | 只在 API 注册时，worker 首次检查报 `F048 resource registry is not configured` | `build_f048_resource_composition` |
| 4 | 已部署环境只发代码、不执行升级 → **全部**权限判定 503，不只是新类型 | 109 / .116 / 客户环境整站权限失效 | 版本契约「部署注意」、PR 说明、维护窗口步骤 |
| 5 | 标准权限模型（如「查看者」）的「仅可见资源类型」由代码中的资源类型清单推导并存储；新增类型后已存储行与推导不一致，启动校验报 `CURRENT stored model differs from the canonical derivation` | 只补作用域（§10.1 脚本做法）仍整站 503 | 决策 7：经 `CatalogService` 草稿发布重新推导 |
| 6 | `publish_authorization_model_change.py` 早于 F118，重建自定义权限模型时不带 `visibility_only_resource_types` / `visibility_level` / `retired_use_level_floor` | 在已做过 F118 迁移的环境上运行，改坏「仅可见」自定义模型及引用它们的授权 | 决策 7 修正 1 |
| 7 | `permission_action_resource_scope` 运行期没有代码写；不补作用域则新类型上所有检查抛 `InvalidCatalogActionError` | 模型发布成功了，功能仍全部报错，且日志看起来像升级成功 | 决策 7 修正 1，`--verify` 检查 |
| 8 | 有两个看起来都能「补登记」的脚本：`migrate_capability_authorization.py` 早于 F118（要求 id 为纯数字、系统所有登记带已退役的 `use`，而 `_validate_system_owned` 只允许 `visible` / `download`） | 用错脚本会在新类型上直接报错；处理到未登记的内置工具也会报错中断 | 决策 7：只用 `reconcile_f048_system_owned_resources.py --resource-type` |
| 9 | 发布脚本与补登记脚本检测到运行中的进程心跳就拒绝执行 | 不停服直接跑会失败 | 维护窗口：停服 → 备份 → 发布 → 补登记 → 校验 → 启动 |
| 10 | 同步策略包含**已删除**插件，已安装的设备上删除的插件继续可用；工作台删除后详情返回不存在 | 适配器拒绝已删除记录 → 删除的插件被停用；用详情核对工作台 → 删除的工作台被停用。两者都改变现状 | 决策 5 适配器口径、决策 9 |
| 11 | 员工插件目录在数据库分页 | 先分页后过滤会出现空页、`total` 错误 | 决策 5 |
| 12 | 市场仓储是同步代码，权限检查是异步 | 把检查塞进仓储会阻塞或无法调用 | 决策 5 异步可见性服务 |
| 13 | 工作台没有 `deleted` 字段；管理端与员工端共用 `WorkbenchService.list` | 在共用函数里过滤会让管理员也看不到（违反 AC-06） | 只在员工侧入口过滤 |
| 14 | 工作台截图是独立的员工侧入口 | 漏掉它，无权限者仍能按 id 取到截图 | 决策 5（7 个入口） |
| 15 | 导入按名称 / 身份复用记录，含已删除 | 若删除时清掉 F048 资源，恢复会丢授权 | 决策 4 |
| 16 | 存量补登记不放在启动流程；也不能用「重新登记」的方式补全员授权 | 放启动：违反 C4 的一次性迁移边界；绕过对账助手直接重新登记：把管理员撤销后的空授权补回 | 只用显式脚本 + 对账助手（决策 3 / 7） |
| 17 | C4 判定顺序中租户管理员直接放行，管理员在员工侧（桌面端）也看得到全部 | 用管理员账号测员工侧过滤，结果永远「全可见」 | §7 用普通员工账号验证 |
| 18 | 桌面插件离线时停止运行实例、保留 `enabled`（恢复在线后继续）；工作台装好后今天没有任何核对 | 误以为两者一致 | 决策 8 / 9；spec AC-14 |
| 19 | 不要用 `force_write_model` | 只写 OpenFGA 不写 SQL、生产禁用 | `docs/architecture/10-permission-rbac.md` §10.1 |
| 20 | 桌面端的专用令牌只在 `utils/http_middleware.py` 的 `DSH_CREDENTIAL_ROUTES`（及其正则）登记过的路由上被接受 | 新增员工侧接口不登记，桌面端调用会被当作浏览器请求拒绝，而网页端测试照样通过 | `POST /dsh/market/workbenches/access` 已登记；`test/dsh_market/test_desktop_auth.py` 守护 |
| 22 | 企业工作台装好后桌面端原本不记录「企业 id ↔ 插件包名」，客户端靠企业目录按包名对应；收回后目录不再列出该项 | 无从得知要问哪个 id，收回永远不生效 | `enterprise-installs.json`（安装时写入）；升级前已安装的，在客户端读到企业目录（仍可见）时按包名补记（`/api/desktop-workbenches/enterprise-installs/adopt`，排除工作台市场与本地目录安装的同名包）。**剩余限制**：升级后首次同步前就已被收回的旧安装无法补记，需重新安装后才受约束 |
| 23 | 桌面主进程按白名单转发企业市场请求（`parseMarketRequest`），只有 `sync` 允许请求体 | 新接口在桌面端本地就被拒绝，服务端测试照样通过 | `src/main/enterprise/enterprise-market.ts`，`test/enterprise-workbench-market.test.ts` 守护 |
| 21 | 列表与同步的可见判定走「批量读取权限快照 + `batch_check_verified_business_visible`」，不走逐个解析的 `batch_check_business_actions` | 逐个解析时每项一次数据库读取；同步每台设备每 60 秒一次，插件多、设备多时压力大 | `dsh_market/domain/permission.py` 的 `_visible_ids` |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| 员工侧 `catalog`、插件下载、`sync` 的 `policies`、工作台列表 / 详情 / 截图 / 下载 **只含或只放行可见项** | HTTP 语义收窄（结构不变） | BISHENG 桌面客户端 |
| `POST /api/v1/dsh/market/workbenches/access` | 新增 HTTP 接口（§4.2） | BISHENG 桌面客户端 |
| 资源类型 `dsh_market_plugin`、`dsh_market_workbench` | F048 资源（资源授权 API、权限弹窗） | 管理后台 |
| 可见性服务（列表过滤、单项检查、确保登记） | `dsh_market` 内部 Python 异步接口 | 仅 `dsh_market` 接口层 |
| 「可撤销全员 / 系统所有」类型共享常量 | `permission` 内部常量 | F048 runtime、后续新增同类资源的特性 |
| `publish_authorization_model_change.py --verify`；`reconcile_f048_system_owned_resources.py --resource-type` | 运维脚本参数 | 部署人员；后续新增类型的特性 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F048 `reconcile_system_owned_resources`（→ `authorize_system_owned`）/ `batch_check_business_actions` / `tenant_use_grant`、资源授权 API 与权限弹窗 | 内部 Python API + HTTP | 接口或「系统所有只允许 visible / download」规则变化 |
| F048 `CatalogService.build_draft / publish` 与标准模型推导 | 内部 Python API | 推导规则变化时发布脚本需同步 |
| OpenFGA（模型不可变、按校验值查重） | 第三方服务 | 模型发布失败 → 维护窗口内恢复备份 |
| F055 / F019 仓储的记录复用、删除语义 | 隐式数据契约 | 改为物理删除或换 id → 决策 4 失效；策略排除已删除插件 → 决策 8 提示语需原因码 |
| 桌面端 `enforce()` 对「在线且策略中不存在」即停用并置 `enabled=false` | 隐式客户端行为 | 客户端改动该逻辑会让收回失效 |
| 桌面 Plugin Manager 的停用 / 启用接口 | 客户端内部 API | 接口变化影响工作台停用与恢复 |
| 部署方执行维护窗口步骤（含一致备份） | 部署流程 | 未执行 → 坑 4；未备份 → 无法回滚 |

---

## 7. 测试与可观测

**分层策略**
- **单元（后端，`test/dsh/`、`test/permission/`）**：适配器（不存在、跨租户拒绝；已删除照常构造目标）；可见性服务（先过滤后分页、单项拒绝与不存在一致、同步策略只含可见且保留已删除、access 接口对不存在 / 跨租户返回 false）；确保登记（新建登记、已登记不改授权、恢复不改授权）；类型集合与双胞胎清单一致；发布脚本（只为新类型补作用域、自定义模型的三个可见字段原样保留、`--verify` 能发现缺作用域与模型推导不一致）；补登记脚本（十六进制 id、`--resource-type` 过滤、重复执行保留撤销、含已删除记录）。
- **前端（platform vitest）**：权限按钮显示条件与 `PermissionDialog` 参数（`resourceType`、`allowAllMembers`）。
- **桌面端（vitest）**：插件收回原因码与文案；工作台核对（false → 停用并标记、请求失败 / 404 → 保持、恢复后手动启用前再核对）。
- **本机集成**：本机独立中间件与后端跑真实链路，包括一次完整的升级演练（见下）。单元测试的 mock 不能代替升级演练。
- **达梦**：本机无驱动，请同事在 Linux 环境跑补登记脚本与相关回归。
- **真实环境**：beta2 部署到 109 / .116 并执行维护窗口步骤后验收；无服务器权限，依赖部署方。

**手动验证（本机）**
1. 中间件：单独起一套容器（名称前缀 `f022-`，端口避开其他会话已有的容器）：MySQL、Redis、OpenFGA（MySQL 存储，先 `migrate` 再 `run`）、MinIO；后端用 `config=<本机配置绝对路径>` 指向它们，新库先 `.venv/bin/alembic upgrade head`。
2. 用**升级前代码**（`feat/3.1.0-beta2` 合并前的提交，独立 git worktree）启动后端与管理后台，注册超级管理员，建员工 A（普通用户，部门 D1）、员工 B（普通用户，部门 D2，用户组 G1）；在管理后台 `/dsh` 导入 2 个企业插件、1 个企业工作台，再删除其中 1 个插件。
3. 停掉全部后端进程，备份业务库与 OpenFGA 库，切到本分支代码，在 `src/backend` 下依次执行：
   ```bash
   PYTHONPATH=./ .venv/bin/python scripts/publish_authorization_model_change.py            # 预览，不写
   PYTHONPATH=./ .venv/bin/python scripts/publish_authorization_model_change.py --apply \
     --confirm-store-id <预览输出> --confirm-target-model-checksum <预览输出> --operator-id 1
   PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_system_owned_resources.py \
     --resource-type dsh_market_plugin --resource-type dsh_market_workbench                # 预览
   PYTHONPATH=./ .venv/bin/python scripts/reconcile_f048_system_owned_resources.py --apply --confirm-store-id <同上> \
     --resource-type dsh_market_plugin --resource-type dsh_market_workbench
   PYTHONPATH=./ .venv/bin/python scripts/publish_authorization_model_change.py --verify
   ```
   再执行一次补登记预览，确认 `missing_count` 为 0；启动后端。
4. 桌面开发版（独立数据目录 `BISHENG_DEV_USER_DATA`）以员工 A 登录：企业市场与升级前一致（AC-04）；安装插件 P1 与工作台 W1。
5. 管理员把 P1、W1 改为只授权 D2：员工 A 下一次同步后 P1 显示「管理员已收回使用权限」、W1 停用（AC-11 / AC-12）；员工 B 刷新后可见（AC-09）；员工 A 按 id 请求详情 / 截图 / 下载返回不存在（AC-07 / AC-08）。
6. 把 P1 授权回 D1：员工 A 手动启用 P1 / W1，原配置与工作台数据仍在（AC-13）。
7. 删除 W1 后重新导入同一包：授权仍为 D1 + D2（AC-18）。
8. 回滚演练：恢复第 3 步的备份并启动升级前代码，确认可正常登录与使用。

**可观测**：沿用 F048 的授权审计与投影操作记录；补登记脚本输出每条资源的处理结果（create / preserved）；桌面端停用记录原因码。

---

## 8. 后续改进 / 不打算做的事

- 企业工作台离线强制收回（需要可信时间与离线凭证）：本期不做。
- 按项委派管理权（非租户管理员管理某个插件的授权）：本期不做，需要时按决策 3 的重新考虑条件切换登记方式。
- 工作台的服务端周期同步策略（与插件一致）：若后续需要更快生效再做（决策 9）。
- `migrate_capability_authorization.py` 对内置工具的系统所有登记仍带已退役的 `use`（坑 8）；`scripts/reconcile_f048_visible_projection.py` 重建自定义模型时同样漏带 F118 的三个可见字段。两者不属于本特性范围，本期不改，已在 PR 说明中提示。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-16 | 初版 | spec 确认后进入设计 |
| 2026-11-16 | 实现细节：确保登记与存量补登记改用现有系统所有资源对账助手 / 脚本（`reconcile_system_owned_resources`、`reconcile_f048_system_owned_resources.py`），不再修改 `migrate_capability_authorization.py` | 拆解任务时核对代码发现现成能力 |
| 2026-11-16 | 设计评审修订：登记方式改为系统所有（决策 3）；员工侧入口补工作台截图、适配器包含已删除记录（决策 5）；上线方式补发布脚本 F118 字段修正、`--verify`、补登记按类型过滤，回滚改为一致备份（决策 7）；决策 8 原因更正；工作台核对改为新增可见性查询接口（决策 9）；补决策 10 备选；§5 坑表、§6 接口、§7 手动验证步骤 | `/sdd-review design` |
