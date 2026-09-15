# Design: PAT 数据范围收窄与「AI 助手接入」界面（F066）

> 本文档是现状快照（Why this How）。需求与 AC 见 [spec.md](./spec.md)（上游真相 = PRD v2.9 D21 / D22）；执行流水见 [tasks.md](./tasks.md)。
> 行号基线：`feat/3.0.0-beta1` @ `8db764f2b`（本分支分叉点），文中 `文件:行号` 均已在该基线上直接核实。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v3.0.0-beta1
**最后更新**: 2026-09-13（初版）

---

## 1. 目标与非目标

- **目标**：在 F053 已交付的 PAT 通道上加一层**租户可配的数据出口收窄**（仅本人创建的知识库），判定置于一切权限特权之前；同时把员工侧交付面从「个人 API 令牌」重构为「AI 助手接入」（入口前移、风险提示分层、四态范围文案），并同批修缮技能包 P0 三件。
- **非目标**：见 spec §1「明确排除」与 §4——特别是：不做部署级配置、不做动态清单、不下探文件创建者、不改技能包后端逻辑、不影响服务账号密钥。

---

## 2. 关键约束

全局铁律遵循 `docs/constitution.md` C1–C8，不重抄。本 feature 特有：

1. **判定必须先于管理员短路与 OpenFGA 查询**（INV-32 fail-closed + 修订后 INV-34）——beta1 的闸口已给 natural_person 注入真实管理员事实（`open_api/api/dependencies.py:98-107`，`f6bf9f51f`），任何借道既有 `ensure_*` 权限检查的收窄实现都会被短路放行，结构上不可行。
2. **热路径成本**：收窄判定落在每个 v2 knowledge 请求上，必须请求内 memo、文件粒度按批解析父资源，典型增量 ≤2 次 SQL/请求。
3. **滚动升级混版窗口**：租户策略缓存是跨进程共享的 Redis dict（`tenant_setting_service.py:19-20`，key `oapi:tenant:{id}:pat`、TTL 5s），旧版本进程会持续回填**不含新字段**的值——新版本读到缺键值时的解释规则是本设计唯一允许的宽松点（决策 4）。
4. **管理端 Update 契约**：`PersonalTokenSettingUpdate` 为 `extra="forbid"` + 全必填 + 服务层整体覆盖（`schemas/personal_token.py:13-16`、`tenant_setting_service.py:81-82`），新字段的可选性直接对应两类兼容故障（决策 4）。
5. 双端前端改造互不 import；三语 i18n 同 PR；`api_errors` 域产物文件禁手改；禁 `backdrop-filter`；client 单文件 ≤600 行。
6. 技能包分发是匿名端点、打包期不知租户且配置运行期可变——包内**不做**任何租户相关动态渲染。
7. **C4 触碰登记**：constitution C4 记载的短路顺序是「super_admin → 租户不匹配拒绝 → tenant_admin → 动作门 → OpenFGA」；本 feature 在该链**之前**插入 data_scope 拒绝（仅对开放面自然人主体生效）——deny 先于一切 ALLOW 短路是 D21 的语义要求。属对 C4 措辞的扩展，落码同批按宪法治理规则（PR review）在 `docs/constitution.md` C4 补一句。

---

## 3. 方案对比与选定

### 决策 1：收窄强制点放在哪一层

- **备选**：
  - A. service 层逐点过滤（retrieve 分发、get_knowledge、file/list、citation、QA 各加一段）——直观、省工；但每个过滤点是独立复制品，新端点默认 fail-open。
  - B. **PermissionActor 增 `data_scope` 字段 + 权限层内生强制**——闸口与异步快照装填；permission 层单一 helper 在四个判定点强制。
  - C. repo/SQL 层自动注入（tenant_filter 同款）——owned 语义按表各异（库看 `user_id`、空间看成员表 join、文件看父资源）无法统一注入；tenant_filter 只拦 SELECT 且 raw SQL 绕过；FGA 枚举不经 SQL。单独用必漏。
  - D. 签发期把收窄写进凭据行——配置变更无法作用于存量令牌，且违反「不做快照」「开关不写凭据行」两条既定规则。
- **选定**：B。四个判定点：`check_action`（`_identity_shortcut` **之前**）、`check_visible`（FGA 查询之前）、batch 版同前、`list_visible_objects`（结果与 owned id 集取交）。装填端：`verify_open_api_access`（dependencies.py，取 `get_policy` 的 data_scope 写入 actor）与 `OpenApiExecutionSnapshot` 重放（`execution_context.py` 处以 `get_policy_sync` **重新取值**，不信任快照旧值——满足「立即收窄」对异步任务同样成立）。
  **归属事实的取用遵守 C4 / INV-10：权限模块不 import 业务 ORM**——`permission.application` 定义归属解析协议（`DataScopeOwnershipResolver`：入参 resource_type + resource_id 集，出参 owned 与否 / owned id 集），由 knowledge 域实现并在装配期注册；权限层四判定点只调协议，**协议未注册时一律拒绝**（fail-closed，不得静默放行）。请求内 memo 与 file→parent 批量归父都在协议实现侧。
- **原因**：判定先于短路与 FGA ⇒ 管理员 PAT 被压、FGA 存量 tuple 未核实风险被结构性免疫；新端点只要走 F048（C4 本就强制）即自动被罩住；单一 helper 单一事实源。
- **何时重新考虑**：data_scope 需要扩展到非知识域资源、或需要按权限位分别配置时，字段语义要升级为映射而非单枚举。

### 决策 2：越界响应的产生机制

- **备选**：A. helper 返回 False，沿既有路径糊成 403 / 18040；B. **专用异常 `DataScopeDeniedError` 上抛**，由 open_api 异常链映射为 HTTP 403 + `26044`。
- **选定**：B；**列表路径例外**——`list_visible_objects` 交集是静默收窄，不产生 26044。
- **原因**：26044 存在的全部意义是行动分辨（26003=找管理员加权限位；26044=租户范围策略，加位与重试都无益）；A 会让它永远不出现。「检索面报错 / 清单面静默」的不对称已写入 PRD §4.10.7 与技能包 api.md。
- **何时重新考虑**：若将来产品要求清单端点也显式提示受限（如响应头），再加带外信号，不改静默语义。
- **落位注**（实现期确定）：异常类即 `common/errcode/open_api.PersonalTokenDataScopeError`（错误码类按域规约住 common/errcode，全层可 import），权限层直接抛它；`permission` 侧不再自定义中间异常。

### 决策 3：「本人创建」判定口径与查询

- **备选**：A. **SQL 主判**——文档/QA 库 `knowledge.user_id = 持有人 AND type IN (0,1)`；知识空间 `space_channel_member` CREATOR∧ACTIVE 行 ∧ 无 `department_knowledge_space` 绑定；B. FGA owner tuple 镜像判。
- **选定**：A。现成查询：`KnowledgeDao.aget_knowledge_ids_created_by`（`knowledge/domain/models/knowledge.py:309-328`，docstring 就是为此预置、当前零调用方）+ `get_my_created_spaces` 同款成员表口径（`knowledge_space_service.py:1852-1864` 含部门剪除）——两者都在 **knowledge 域的协议实现**里调用（决策 1），权限层不直接触碰。**文件粒度**：不逐文件判——一次批量取 file→parent 映射，归到父库/父空间后按父 memo 判定（每请求每父资源只判一次）。
- **原因**：SQL 是「我创建的」唯一在用事实源（列表全走 SQL，权限检查侧刻意 `del owner_user_id`）；与 UI 完全同源 ⇒ 「PAT 能搜到的 = 界面『我创建的』栏」可解释性最好；FGA owner 出过 26 条 `user:None` 僵尸、修复靠对账脚本，不配当安全白名单依据。
- **何时重新考虑**：F018 归属转移真正落地时（届时必须保证 SQL/FGA 双轴同步，本口径自动跟随 `user_id` 现值）。

### 决策 4：配置载体、枚举语义与兼容

- **选定**（租户级单层为用户拍板，两层方案已否决、勿再提回）：
  - `open_api_tenant_setting` 加列 `pat_data_scope VARCHAR(32) NOT NULL server_default 'all_visible'`（alembic 新迁移，不改 `f053_pat_tenant_setting`——它已有后继）。
  - 取值 `all_visible | personal_only`。**未知取值按 personal_only**（fail-closed，覆盖「新镜像写入未来扩展值后回滚」）。
  - **缓存 dict 缺 `data_scope` 键 = all_visible**——混版窗口唯一例外。论证：缺键只可能来自旧版本进程回填，旧版本语义本就是 all_visible；这不是评估失败，是历史语义，不违反 INV-32。
  - `PersonalTokenSettingUpdate.data_scope` **可选、缺省 = 保持现值**（服务层对 None 显式 preserve）：必填 → 老前端 422 强迫锁步；可选 + 兜底默认 → 「旧前端残缺 PUT 静默覆盖」坑复活。两坑全避；新前端先上老后端仍 422（extra=forbid），按同版交付纪律处理。
  - 生效：写库后 `invalidate`（`tenant_setting_service.py:87-90`），最坏 5 秒；`get_policy_sync`（:53-59）零缓存。
- **何时重新考虑**：出现「新装部署默认收紧」的安全侧要求，或需要扩展档位（如 spaces_only / 指定清单）时——enum 值域、管理端控件与「未知值按 personal_only」的兜底一起扩。

### 决策 5：旁路收口（三处，缺一则收窄档失守）

1. **`get_knowledge` 管理员分支**（`knowledge_service.py:502` 注释自认 "Admin bypass: no F048 enumeration, DB filter left unbounded"，:547 连逐页 BatchCheck 也跳）：actor.data_scope 受限时强制走 visible-first 路径并与 owned 集取交（或直接以 owned 集为候选），恢复动作批检。
2. **知识空间 `system_scope = login_user.is_global_super` 直读**（`knowledge_space_service.py:2841`、`:2990`）：v2 面上该判定改为咨询 ContextVar actor——data_scope 受限时不得进入 system_scope 分支。
3. **立规 + 断言**：v2 请求路径上任何 `login_user.is_admin()/is_global_super` 消费点均为审计对象；新增测试断言 v2 链路 grep 不出新增消费（AC-R3 矩阵之外的静态防线）。
4. **应用层 `actor.super_admin` ALLOW 短路**（105 e2e 实测抓获）：`business_authorization.py` 的 `check_business_action` 与 `batch_check_business_actions` 在进入 runtime **之前** `if actor.super_admin: return True/全通 map`——runtime 内的五个强制点全部够不着。修法：短路条件收紧为 `actor.super_admin and actor.data_scope == DATA_SCOPE_ALL`，收窄档超管落回 registry+runtime 正常路径吃 26044/False。静态守卫同步加第三道断言（短路数 == 带 DATA_SCOPE_ALL 守卫数）。

QA 双端点不在清单内：beta1 已有 `_qa_with_knowledge_access` 闸（`open_endpoints/api/endpoints/filelib.py:62`，读走 visible）→ 判定点在 check_visible，data_scope 自动叠加。

- **何时重新考虑**：F048/F049 列表策略重构若移除 `get_knowledge` 的 admin bypass 分支或统一 system_scope 判定，收口 ①② 随之简化乃至消失——届时只留 ③ 的静态断言。

### 决策 6：员工侧 UI 落位

- **备选**：整组件重写——被否：beta1 弹窗的关闭保护 / confirm / 深链逻辑已被验证，重写徒增回归面。**选定**：基于 beta1 现有 `PersonalTokenDialog`（`b19453d01` 已是两步弹窗 + confirm + 深链）**改造**；组件更名 + 状态机扩展（管理员签发前确认、范围卡四态、风险红条）。**何时重新考虑**：状态机膨胀触 600 行红线时按子组件拆分（一次性展示区 / 范围卡 / 管理员确认可各自独立）。
- 入口两处开同一弹窗：知识库页 sidebar 底部常驻入口（`KnowledgeSpaceSidebar.tsx`）+ 设置页新一级分区 `ai-access`（`settingsSections.ts`；「账号信息」页原行移除）。
- 深链：新参数落 `/settings/ai-access?connect=1`；**旧 `?api-token=1` 保留兼容映射**（AC-R7——已分发的安装提示词里带着旧链）。
- 文案全部走新键族 `com_ai_access_*`；范围四态与管理员警示文案以 PRD §4.10.6 与交互稿为准；`{{days}}` 用签发响应实际值（管理员 = `min(租户TTL, pat_admin_ttl_days)`，`personal_token_service.py:52-53`），前端不读配置拼。
- platform：SystemPage Tab 改名「AI 助手接入」，策略卡片改「使用策略」+ RadioGroup + 收紧确认弹窗;台账「管理员风险」徽标改「管理员持有」、吊销加确认、「按持有人吊销」合并、补分页。

### 决策 7：审计

- **备选**：复用 v2 调用面的 ASGI 审计中间件——被否：它只罩已认证的 `/api/v2` 面（`open_api/api/middleware.py` 头注自认），管理端 PUT 在 `/api/v1`。**选定**：action 定名 `open_api.pat.settings.update`，范本抄 `personal_token_service.py:73-79`（`open_api.pat.create`）；记录 before/after 三字段（pat_enabled / pat_ttl_days / pat_data_scope）与操作人，写 `audit_log.audit_metadata`；仅值变化时记。顺带把整个 settings 更新纳入（现状零审计），不新增逐调用表。**何时重新考虑**：平台引入统一配置审计框架时并入。

### 决策 8：技能包修缮边界

- 只改 `open_api/skill_packs/bisheng-knowledge-search/` 下静态文件 + 新增 `references/api.md`（`.md` 后缀自动吃 `{{BASE_URL}}`/`{{OUTBOUND_ORIGIN}}` 渲染，`skill_pack_service.py` 零改动）。
- api.md 必写：端点表（retrieve / 列表 / file list）、响应 wrapper 与 chunk 字段、`extra=forbid`（多传字段即 422）、top_k ≤200、QA/个人库不可检索、**「先调 `GET /api/v2/filelib/`（type=3 与 type=0）拿知识库标识再检索」**、cursor 分页、引用回链格式（document_name + knowledge_id/document_id/chunk_index）、错误码表（26001/26002/26003/26030/26040/26043/**26044** 各自的行动指引）、**v2 type=3 清单不含部门空间**（可检索但需用户提供标识）。
- `search.py`：非 2xx 读取 `exc.read()` 透出 `status_code`/`status_message`；SKILL.md frontmatter description 补中文触发词。
- **何时重新考虑**：需要在包内携带实例相关 JSON（如 meta.json 带版本与地址）时，须把 `.json` 加进 skill_pack_service 的渲染后缀名单——那是唯一允许动打包服务的场景，本期不做。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（收窄判定，目标态）

```
v2 请求 → verify_open_api_access (open_api/api/dependencies.py)
   ├─ PAT 双开关（:69-73，get_policy 顺带取 data_scope）
   ├─ PermissionActor(..., data_scope=<effective>) 装入 ContextVar（:113-118 处扩展）
   ↓
端点 → F048 判定点（check_action / check_visible / batch / list_visible_objects）
   ├─ 先问 _data_scope_permits(actor, resource_type, resource_id)   ← 短路与 FGA 之前（经注册的归属解析协议取业务事实）
   │     └─ SQL owned 判定（决策 3；请求内 memo；file 批量归父）
   ├─ 受限且越界 → raise DataScopeDeniedError → exception_handlers → HTTP 403 + 26044
   └─ list_visible_objects → 结果 ∩ owned 集（静默收窄）
异步任务 → OpenApiExecutionSnapshot 重放（execution_context.py）→ get_policy_sync 重取 data_scope
```

### 4.2 关键契约字段

| 字段 / 结构 | 取值 / 格式 | 说明 | 谁消费 |
|---|---|---|---|
| `open_api_tenant_setting.pat_data_scope` | `all_visible`（默认）/ `personal_only` | 租户级数据范围；未知值按 personal_only | 闸口装填、管理端 |
| `GET/PUT /api/v1/personal-tokens/settings` | 增 `data_scope`（PUT 可选、缺省保持现值） | 管理端策略卡 | platform |
| `GET /api/v1/me/api-token` | 增 `data_scope`（effective）与生效 TTL 天数 | 驱动 client 四态文案与 `{{days}}` | client |
| `26044` | HTTP 403，`data` 只含 `{"scope": "personal_only"}`，不列资源 id | 范围受限（防枚举） | Agent / 技能包 api.md |
| 审计 action | `open_api.pat.settings.update`，metadata 含 before/after 三字段 | 策略变更留痕 | 审计查询 |
| 深链 | `/settings/ai-access?connect=1`；旧 `?api-token=1` 兼容映射 | 安装提示词密钥获取地址 | client 路由 |

### 4.3 关键模块职责

| 模块 / 文件（beta1 基线） | 职责 | 不做什么 |
|---|---|---|
| `open_api/api/dependencies.py` | 装填 data_scope 进 actor（:98-118 一带扩展） | 不做收窄判定本身 |
| `open_api/domain/services/tenant_setting_service.py` | 策略 + 缓存（**七处引用**：cache 读 :35-39 / DB 回退 :41-45 / cache 写 :46-50 / sync :53-59 / 响应组装 :61-70 / 覆盖写 :81-82 / `TenantPatPolicy` :23-26）| 不被业务层直调判定 |
| permission 层新 helper `_data_scope_permits` | 唯一判定入口（四个消费点），经注册协议取归属事实 | **不 import / 查询业务 ORM**（C4 / INV-10）；协议未注册即拒绝；不放行任何异常 |
| knowledge 域 `DataScopeOwnershipResolver` 实现 | 归属事实解析（口径 A + memo + file 批量归父），装配期注册 | 不做权限判定本身；不感知 scope 位与端点 |
| `knowledge/domain/services/knowledge_service.py` | 旁路收口 ①（:502 admin bypass、:547 needs_action_check） | — |
| `knowledge/domain/services/knowledge_space_service.py` | 旁路收口 ②（:2841 / :2990 system_scope） | — |
| `client .../PersonalTokenDialog.tsx` → AI 助手接入弹窗 | 状态机：两步 / 管理员确认 / 展示（红条+范围卡）/ 已连接 / 关停 | 不直调 axios；不超 600 行 |
| `platform .../SystemPage/components/PersonalToken/` | 使用策略卡（含 RadioGroup + 收紧确认）+ 台账 | 不新建页面级组件 |
| `open_api/skill_packs/bisheng-knowledge-search/` | 三个静态文件 + 新增 references/api.md | 打包服务零逻辑改动 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | **beta1 现在的红字是假话**：后端已注入管理员事实（f6bf9f51f），前端 `com_personal_token_admin_warning` 仍写「不会继承管理员特权」 | 沿用旧文案 = 对管理员说反话 | 新键族替换（AC-P29） |
| 2 | 策略缓存 dict **七处引用**（§4.3 行号），加字段漏一处即缓存/DB 分叉 | 收窄配置在部分路径不生效 | tenant_setting_service 一次性全改 + 单测 |
| 3 | Update schema `extra=forbid` + 全必填 + 整体覆盖 | 新字段设必填 → 老前端 422；可选 + 兜底默认 → 残缺 PUT 静默把范围写回默认 | 决策 4：可选 + preserve |
| 4 | **管理员 PAT 过得了 `use`/`edit` 检查**（D17 已合入 beta1） | 借道 `ensure_*` 实现收窄 = 管理员密钥全程放行 | 决策 1：判定先于短路 |
| 5 | `get_knowledge` 管理员分支连逐页 BatchCheck 都跳（:502/:547） | 收窄档下管理员令牌清单全租户裸奔 | 决策 5 ① |
| 6 | v2 `type=3` 清单只回「我创建的+加入的」，**部门空间可检索但不可列**（F030 AD-08 刻意裁定） | Agent「先列清单再检索」流程发现不了部门空间；误判为 bug 去改列表口径 | api.md 明写；不改列表行为 |
| 7 | QA 库（type=1）平台可见、清单可列，但 **retrieve 拒收**；读 QA 走 detail/query 端点（beta1 有库级闸 filelib.py:62） | 范围文案过度承诺；测试矩阵漏 QA 端点 | 四态文案不承诺 QA；矩阵含 QA 端点 |
| 8 | `DEFAULT_PAT_TTL_DAYS` **beta1=365**；beta2 上是 30（旧值） | 从 beta2 抄代码会把默认 TTL 改坏 | 本 feature 基线是 beta1，勿参照 beta2 |
| 9 | 管理员 TTL = `min(租户值, pat_admin_ttl_days=7)`（personal_token_service.py:52-53） | 前端硬写「7 天」在租户 TTL<7 时说大 | `{{days}}` 用签发响应实际值 |
| 10 | `f053_pat_tenant_setting` 迁移已有后继，**加列必须新开迁移**；单头纪律以 `alembic heads` 实跑为准 | 双头 → entrypoint fail-fast 全站起不来 | alembic/AGENTS.md §0-§3 |
| 11 | worktree 跑前端要镜像 node_modules + 重定向 @bisheng + 补链隐藏项；`pnpm install` 会搞坏 canvas | worktree 里 lint/test 全挂或 client jest 全挂 | 参照 bisheng-prd1 先例；能不 install 就不 install |
| 12 | `api_errors` 产物 json（client `api_errors.gen.json` / platform `public/locales/*/api_errors.json`）禁手改 | CI 挂 | 改 packages/locales 源 + 重跑 build |
| 13 | `tenant_filter` 只拦 SELECT、粒度只有租户、raw SQL 绕过 | 有人想借它做收窄（决策 1-C 的诱惑） | 已否决，见决策 1 |
| 14 | `26044` 不并入 `26003`：行动指引不同（加位 vs 范围策略） | Agent/用户拿到笼统 403 无从自救 | 决策 2 + api.md 错误码表 |
| 15 | 闸口取 `get_policy` 现在只在 natural_person 分支调用（dependencies.py:69-73）——data_scope 装填要复用这一次调用，别再加第二次策略读取 | 每请求多一次 Redis/DB 读 | 决策 1 装填端实现注意 |
| 16 | **beta1 在 runtime 之外还有应用层超管 ALLOW 短路**（`business_authorization.py` 单+批两处，beta2 基线审计时不存在、静态守卫只盯 `is_global_super` 字符串故双重漏网）——「判定先于短路」只对 runtime 内的短路天然成立 | 收窄档超管密钥单资源检索全放行（105 e2e N6 实测 200+内容） | 短路条件加 `data_scope == DATA_SCOPE_ALL`；守卫断言钉死 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `pat_data_scope` 配置语义（含缺键=all_visible、未知=personal_only） | DB 列 + 策略缓存 dict | 闸口、执行快照、将来任何策略消费方 |
| settings GET/PUT 增字段（PUT 可选 preserve） | HTTP API | platform 管理端 |
| `me/api-token` 增 `data_scope` + 生效 TTL | HTTP API | client 弹窗四态 |
| `26044` 错误码（403，防枚举） | 对外可观测行为 | 第三方 Agent、技能包 |
| 技能包 zip 新内容（SKILL.md 触发词 / api.md / search.py 错误透出） | 匿名下载物 | 员工的 Agent |
| `open_api.pat.settings.update` 审计事件 | audit_log | 审计/合规查询 |
| INV-34 修订版语义 | release-contract | 后续所有 PAT 相关 feature |
| constitution C4 短路顺序措辞增补（data_scope deny 先于身份短路） | `docs/constitution.md`（同批 PR，按宪法治理规则评审） | 全部走 F048 判定的 feature |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F048 四个判定点（check_action/check_visible/batch/list_visible_objects） | 内部 API（permission 层） | 判定点改名/改签名会静默漏收窄——覆盖矩阵测试兜底 |
| `KnowledgeDao.aget_knowledge_ids_created_by` + 空间 CREATOR 口径 | SQL 查询 | `knowledge.user_id` 存量 NULL 行在收窄档对所有人不可见（fail-closed 正确表现）；上线前建议跑一次归属完整性巡检 |
| beta1 `PersonalTokenDialog` 两步弹窗 + `?api-token=1` 深链 | client 组件 | 改造基线；beta2 前端旧一截，勿以 beta2 为准 |
| 凭据校验 → principal（actor_kind/actor_id） | F053 链路 | 无变更，只读 |
| skills 占位符渲染（`.md`/`.py` 后缀） | 打包服务既有机制 | api.md 必须用 `.md` 后缀才吃渲染 |
| 归属解析协议的装配期注册（knowledge 域 → permission.application） | 启动装配 | 漏注册必须表现为拒绝而非放行（fail-closed）；单测断言未注册路径 |

---

## 7. 测试与可观测

- **覆盖矩阵**（AC-R3，实现形态）：本地无中间件，矩阵拆两层——`test_data_scope_matrix.py` 的**注册表分类断言**（knowledge:read 每个端点必须有 raise/narrow/per-item/sa-only 分类，新增端点即 fail）+ **闸口→权限层→传输接线 e2e**（真策略/真闸口/桩 FGA：默认档不变、收窄次请求生效且可逆、管理员同收窄、403+26044 防枚举载荷）；真实端点全行为矩阵在 `/e2e-test`（e2e-checklist.md）对真实环境执行。
- 单测：策略缓存七处一致性（含缺键/未知值/混版回填模拟）、schema preserve 语义、helper 判定口径（含部门空间剪除、file 归父）、审计写入条件。
- 前端：client 弹窗状态机与四态文案组件测试；platform 策略卡交互测试（沿 `personalTokenSettingsInteraction.test.tsx` 范式）；`pnpm lint` / `typecheck` / `check-i18n`。
- 手动验证：本地起前后端连 test 环境中间件（既定偏好，不改 test 部署；启动命令见 `src/backend/AGENTS.md` 与两前端 `AGENTS.md`——platform :3001、client :4001 基路径 `/workspace`、API :7860）。浏览器链路：client 知识库页入口 → 两步弹窗 → （切管理员账号）签发前确认 → 密钥展示（红条 + 四态范围卡）→ platform :3001 系统管理「AI 助手接入」收紧 → 复制的密钥调 `POST /api/v2/filelib/retrieve` 验 26044 → 改回验恢复。
- 可观测：26044 计数可经既有 v2 审计中间件统计；策略变更看 audit_log。

---

## 8. 后续改进 / 不打算做的事

- `personal_strict` 档（文件创建者下探）：残余风险已接受、界面不提示；出现真实客户诉求再立项。
- 动态范围清单、`meta.json` + 版本自检、凭据配置文件回落、`--tag`/`--max-content`：另批。
- 旧深链 `?api-token=1` 的移除时机：至少保留一个大版本（安装提示词已散出去）。
- 归属完整性巡检脚本化（复用 F048 对账脚本家族模式）：上线前一次性跑即可，暂不做常驻。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-13 | 初版（8 项决策 + 15 条坑） | F066 设计定稿 |
| 2026-09-13 | 决策 2 补异常落位注；§7 矩阵改两层实现形态（T010 测试降级） | 实现期回写 |
| 2026-09-13 | 决策 5 收口清单 3→4 处；§5 增坑 16（应用层超管短路） | 105 e2e N6 抓获真旁路 |
| 2026-09-13 | 迭代二·去品牌化（采访定稿 5 条）：环境变量 `BISHENG_API_KEY`→`KNOWLEDGE_API_KEY`、技能包 slug/name `bisheng-knowledge-search`→`knowledge-search`（不留旧别名）、界面文案接 `$t(bisheng)` 白标插值、技能包内英文文档一律中性、`bs-pat-` 前缀不改；顺带修打包器 `__pycache__` 泄入 zip | 贴牌客户不能透出品牌（用户采访确认） |
| 2026-09-13 | 迭代二·交互修订（AC-P31 口径变更）：勾选门控取消，明文改在主弹窗之上的二次小弹窗（TokenRevealDialog，z-110 照 ConfirmContext 叠加先例）展示，×/Esc/遮罩直接关、关后主栏即掩码态；主栏永不渲染明文与红条；删「开发者文档说明」折叠区；驻地页副标题 Claude Code→WorkBuddy；入口副文案改「让第三方 AI 助手检索知识空间」 | 勾选才能关弹窗反直觉（对标 ima 二次弹窗）+ 第二步过长 |
