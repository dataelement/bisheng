# 《租户操作上下文统一方案》代码核对评审

日期：2026-11-13（台北时间）。评审对象：`tenant-context-unification-proposal-20261113.md`（已按上一轮评审修订的版本）。

本文与方案第 7 行引用的《方案评审》（`tenant-context-unification-review-20261113.md`）不是同一份文档。本文只做一件事：把方案里关于现状的断言逐条对照代码，并指出方案需要修订的地方。

## 1. 结论

**方案的方向成立，本文核对的现状断言都与代码一致。但这一版不能直接进入实施。** 原因有四个：

1. 三处现状描述偏轻或有遗漏（§3 的问题 1、2、3）。
2. 请求范围分类缺"个人业务数据"一类，需要产品决策（§3 的问题 4）。
3. 网关部分没有落点：网关对"当前操作租户"完全不知情，并且有五组自有接口没有租户维度（§4）。
4. 范围超出 3.1 beta1 单批能承受的大小，建议拆成三批（§5）。

## 2. 评审基线与限制

| 项目 | 说明 |
| --- | --- |
| 后端与前端代码 | 在本地 `feat/3.1.0-beta1` 的 `0b78bd7acc` 上阅读 |
| 方案基线 `3ce7e7ef3d` | 存在于 `origin/feat/3.1.0-beta1` 和 `origin/release`，比 `0b78bd7acc` 新 12 个提交 |
| 最新 origin `1d011b4efa` | 比方案基线再新 3 个提交 |
| 基线差异的影响 | 本文引用的文件在 `0b78bd7acc` 与 `1d011b4efa` 之间全部没有变化，结论对方案基线同样成立。唯一相关的新增见 §3 的问题 8 |
| 网关代码 | `dataelement/bisheng-gateway` 的 `main`（`62399806`，2026-11-06）。客户分支只搜索了请求头，没有逐个阅读 |
| 未评审的内容 | 方案引用的三份关联文档（方案评审、角色方案、接入抽查报告）不在手边，§2.5 与角色方案的衔接没有评审 |
| 证据等级 | 全部结论来自阅读源码。没有运行，没有现场复现，没有经网关实际发请求 |

## 3. 后端与前端

### 3.1 已核实成立的现状断言

| 方案断言 | 代码证据 |
| --- | --- |
| 业务 URL 靠手工清单接入，前后端各一份 | `common/middleware/admin_scope.py` 的 `MANAGEMENT_API_PREFIXES` 和 `_EXPECTED_SCOPE_WRITES`；`platform/src/controllers/managementScope.ts` 的 `requiresManagementScope` |
| 24006 拒绝路径 | `space_flow_retrieval.abuild_scoped_login_user` 把流程租户传给 `init_login_user`；后者把它作为 `expected_home_tenant_id`；`role/application/effective_roles.py` 的 `_resolve` 在两者不等时抛 `RolePolicyUnavailableError`（24006） |
| 切换时先写 Redis 再写 SQL 审计 | `TenantScopeService.set_scope` 先 `aset` 后 `AuditLogDao.ainsert_v2`，没有补偿 |
| 超管省略类型即创建共享角色 | `role/domain/services/role_service.py:65` 和 `:115`：`role_type = "global" if login_user.is_admin() else "tenant"` |
| 数据库钩子只处理 SELECT 和 `session.new`，租户不符只告警 | `core/database/tenant_filter.py` 的 `_on_orm_execute`、`_on_before_flush` |
| Celery 缺请求头时回退 Root，权限任务和复制任务严格 | `worker/tenant_context.py` 的 `restore_tenant_context` |
| `QuotaService.check_quota` 有超管绕过 | 第 265 行 `login_user.is_admin()` 短路 |
| Redis 值为十进制整数，清理任务按整数解析 | `admin/domain/services/tenant_scope.py` 的 `_selected_id`；`worker/admin_scope/tasks.py:70` |
| 准入中间件基于 `BaseHTTPMiddleware` | `AdminScopeMiddleware` 的类定义 |

### 3.2 需要修订的问题

**问题 1：未接入入口的现状比方案写的严重。** 方案 §3.1 写"忘记接入就默认为 Home"。实际情况是：超管在非清单路径上 `visible_tenant_ids` 为 `None`（`utils/http_middleware.py` 的 `_compute_visible_tenant_ids`）。SELECT 的实际范围取决于 `_resolve_tenant_id` 的回退，新增行写入 Home。建议在 §7.1 先核实这条读路径，再单列一项影响："超管在未接入路径上的列表结果会变化"。否则上线后会被当成数据丢失。

**问题 2：前后端两份清单已经不一致，并且存在第三处校验点。** 前端清单多出 `references`、`deletion`、`files/batch`、`files/move` 等规则，后端 `_EXPECTED_SCOPE_WRITES` 没有。另有端点级的范围校验分布在以下五处：

- `knowledge/api/endpoints/knowledge_space.py`
- `knowledge/api/endpoints/processing.py`
- `app_governance/domain/services/runtime_audit_scope.py`
- `approval/domain/services/approval_center_service.py`
- `open_api/domain/services/service_account_scope_service.py`

方案 §5 的落点表只列了中间件和 `api/router.py`。照此迁移会出现方案自己在 §3.1 禁止的"两个机制重复覆盖"。请把这五处补进落点表。

**问题 3：24006 的触发面比"Root 创建者 + A 流程"宽。** `workflow/common/knowledge.py:389` 和 `tool/domain/langchain/work_knowledge.py:33` 传入的是运行人加流程租户。因此子租户用户运行 Root 流程，在知识权限开关开启时也走同一条不等判断。Root 流程是否能被子租户用户运行，本文没有核实。请在方案 §2.3 和 §6.2 补上这一组合并确认。

**问题 4：请求范围分类缺"个人业务数据"一类。** 方案 §2.2 有租户业务、租户配置、身份、平台全局、独立凭据五类。超管本人的对话、会话历史、个人令牌、"我的申请"没有归类。现状已经不一致：`/api/v1/workstation`、`/api/v1/linsight`、`/api/v1/chat/online`、`/api/v1/personal-tokens` 在管理前缀内并随选择变化，其余会话路径不在。这是产品决策，需要确认：超管切到 A 之后，本人的历史对话留在 Home，还是随视图切换。

**问题 5：§3.3 第 4 条的前端设计超过现状需要。** 现有前端在范围变化时整页刷新（`platform/src/controllers/request.ts` 监听 `bisheng:management-scope-changed` 和 `storage` 事件）。整页刷新已经满足"旧表单失效、旧响应不覆盖、多标签同步"。方案要求的取消请求、加载序号、缓存键改造是新增工作量。建议本批保留整页刷新，并从 §6.2 验收表删去对应要求。

**问题 6：入口策略登记有现成先例，方案没有引用。** `api/router.py` 的 v2 路由已经使用 `@open_api_scope` 标记，缺少标记时抛 `OpenApiEndpointUnregisteredError` 并拒绝请求。方案 §3.1 和 §6.1 应写明复用这套做法，避免再造一套元数据机制。

**问题 7：超管资格撤销的表述需要对齐现状。** `_check_is_global_super` 有 300 秒 Redis 缓存。`TenantScopeService.clear_on_role_revoke` 在代码注释里写明没有接线。方案 §3.2 要求"撤销失效机制"，应写清本批是接线这个钩子，还是接受最长 300 秒的窗口。

**问题 8：基线之后新增的接口需要进入口清单。** `knowledge/api/endpoints/upload_preview.py` 新增 6 个知识空间上传预览接口（`/api/v1/knowledge/space/{space_id}/uploads/...`，含 POST、PUT、DELETE）。这些路径在 `/api/v1/knowledge` 管理前缀之下，读写跟随当前操作租户。前后端两份写清单都没有改动，所以这些写接口不要求目标请求头。它们有没有走端点级范围校验，本文没有逐个阅读，不能判定是否漏接。

## 4. 网关

### 4.1 核对到的事实

1. **网关没有任何 `X-Management-Tenant` 处理。** 在全部 20 个远端分支上搜索这个请求头，命中数都是 0。`/api/v1/**`、`/api/v2/**`、`/api/v3/**` 只做反向代理，没有找到增删这个请求头的代码。它目前靠代理的默认行为透传，范围校验全部在 Python 后端。

2. **网关自己的租户功能使用另一套目标表达方式。** `DshSensitivePolicyController` 用查询参数 `tenant_id` 指定目标。`DshSafetyAdminClient.authorizeIdentity` 带浏览器请求头回调后端三个接口做校验：
   - `/api/v1/user/info`：非超管时要求 `leaf_tenant_id` 等于目标。
   - `/api/v1/dsh/admin/model-audit/settings?tenant_id=`：确认目标的审计设置可读。
   - `/api/v1/tenants/{id}`：超管时确认目标存在且状态为 `active`。

   这条路径不读取 Redis 里的管理选择。超管在界面上选 A，仍然可以对网关提交 `tenant_id=B`，网关会放行。

3. **网关的旧功能没有租户维度。** `main` 的主代码里，`tenant` 一词只出现在 DSH 相关文件和 `LoginSyncRequest`。以下五组接口的控制器里没有租户字段：敏感词（`/api/sensitive`）、用户组（`/api/group`）、组资源（`/api/resource`）、部门限流（`/api/department-limit`）、拦截记录（`/api/block`）。它们的服务层和表结构本文没有逐个阅读，"数据是否跨租户共用"还需要确认。

4. **网关的后端回调会转发浏览器的全部请求头。** `safeHeaders` 只去掉逐跳头和 `X-Forwarded-*`。浏览器带了 `X-Management-Tenant` 时，这个请求头会随回调到达后端。

### 4.2 对方案的影响

方案 §3.4 第一条"Java 网关和 Python 后端必须执行同一语义"目前没有落点，§5 的落点表只写了"网关"两个字。建议改成三项明确的范围决定：

| 网关部分 | 现状 | 方案需要写明 |
| --- | --- | --- |
| 代理到后端的请求 | 透传，由后端校验 | 保持透传。补一条验收：经网关后，请求头和响应头 `X-Management-Tenant` 都没有丢失。前端依靠响应头得知当前范围 |
| DSH 敏感策略接口 | 查询参数指定目标，不核对管理选择 | 二选一：归为"显式目标入口"并保留现状；或者增加"目标须与当前选择一致"的校验 |
| 敏感词、用户组、组资源、部门限流、拦截记录 | 控制器没有租户字段 | 本批是否纳入。如果不纳入，在功能清单里写明这五组接口不随当前操作租户变化 |

第三行是新发现的范围问题。方案 §2.2 列出了租户业务的范围，但没有提到网关自有的这五组接口。超管切到 A 之后，这些页面显示哪个租户的数据，方案没有回答。

## 5. 范围与流程建议

方案 §7 第 3 步覆盖十余个模块，加上网关、Worker、WebSocket，体量超过一个 feature。建议拆成三批，各自走 SDD 流程：

1. **缺陷闭环。** 包含 24006 执行身份、角色创建显式类型、访客链接、前后端清单合成单一来源。每一项可以独立验收。
2. **入口策略登记。** 全部路由声明范围，持续集成检查声明齐全，运行时只记录不拒绝。同一批产出方案 §7.1 的历史预检数据。
3. **强制拒绝。** 登记齐全并且预检结果得到确认之后再启用。

第 1 批里的角色创建缺省值变化会改动 F009 已确认的验收标准。这一项需要单独确认，并登记到 `features/v3.1.0-beta1/release-contract.md`。

## 6. 待确认事项

| 编号 | 事项 | 由谁确认 |
| --- | --- | --- |
| 1 | 超管切换后，本人的对话、会话历史、个人令牌是否随视图切换（问题 4） | 产品 |
| 2 | Root 流程是否允许子租户用户运行；如果允许，24006 修正需要覆盖这一组合（问题 3） | 方案作者 |
| 3 | 超管资格撤销：接线 `clear_on_role_revoke`，还是接受最长 300 秒窗口（问题 7） | 方案作者 |
| 4 | 新增的 6 个上传预览接口是否已有端点级范围校验（问题 8） | 方案作者 |
| 5 | 网关 DSH 敏感策略接口是否要求目标与当前选择一致（§4.2 第二行） | 产品与方案作者 |
| 6 | 网关五组旧接口本批是否纳入；它们的数据是否跨租户共用（§4.2 第三行） | 产品与网关负责人 |
| 7 | 是否接受三批拆分；角色创建缺省值变化是否确认（§5） | 产品 |
