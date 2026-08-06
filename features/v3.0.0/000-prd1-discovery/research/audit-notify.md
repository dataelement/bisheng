# audit-notify

## summary
审计与站内消息两套子系统均已存在且机制完备，PRD GOV-04 与「事件触达」大部分可在既有骨架上扩展。审计侧：单表 auditlog 双轨写入（legacy EventType 枚举 + v2.5.1 结构化 ainsert_v2），后端已支持平台超管跨租户查询（tenant_scope=None）与 F019 admin-scope 切换，但审计页前端无租户筛选/租户列、操作日志无导出；「按 key 用量账单」是最大缺口——llm_token_log/llm_call_log 无 key 维度、无聚合 API/UI，且 API key 体系本身（开放 API PRD）尚未实现，构成硬前置依赖。站内消息侧：bisheng/message 模块提供 send_generic_notify/send_generic_approval 通用门面，任意后端模块可向任意 user_id 列表发消息，client 工作台铃铛+未读角标+消息弹窗全链路在用，管理后台无消息面（与 PRD 一致）；~8 条新事件通知 ≈ 每条一个后端调用点 + 新 action_code + client i18n/跳转映射，工作量小（约 3-5 人天），审计扩展中等（页面增量 2-4 人天 + 双归属 schema 1-2 人天），按 key 账单需新建（约 5-8 人天，另加 key 体系本身）。

## current_state
【审计/操作日志（全部 verified）】
■ 表：单表 `auditlog`，模型 `AuditLog`（src/backend/bisheng/database/models/audit_log.py:97-169），uuid 主键。双轨字段并存：legacy（operator_id/operator_name/group_ids(JSON)/system_id/event_type/object_type/object_id/object_name/note/ip_address）+ v2.5.1 F011 结构化字段（tenant_id=资源侧叶租户、operator_tenant_id=操作者侧租户、action(String64 索引)、target_type/target_id/reason/audit_metadata(SQL 列名 metadata, JSON)）。老调用方继续写 legacy 列（新列 NULL），新调用方写结构化列。
■ 写入 API 两条路：(1) legacy 门面 `AuditLogService`（src/backend/bisheng/api/services/audit_log.py，918 行）按模块提供语义化方法（create_chat_workflow/create_knowledge/update_user/user_login/create_channel/create_knowledge_space...），内部拼 AuditLog → `AuditLogDao.insert_audit_logs`；事件枚举 `EventType`（约 33 值）+ `SystemId`（7 模块）+ `ObjectType`（audit_log.py:24-94）。(2) v2 结构化 `AuditLogDao.ainsert_v2(tenant_id, operator_id, operator_tenant_id, action, target_type, target_id, reason, metadata, ...)`（audit_log.py:365-432），action 为点分字符串（tenant.mount / approval.task.approve 等），15+ 调用方分布在 tenant/llm/approval/sso_sync/org_sync/admin 各域服务；operator_name 缺省自动查 UserDao 回填，operator_id=0 记 'system'。
■ UI 可见性白名单：`_UI_VISIBLE_V2_ACTIONS` 元组（audit_log.py:178-202）——v2 action 不在此 tuple 内则只写库不进审计页；注释明确要求与前端 `getActionsApi`/`getActionsByModuleApi` 白名单 lockstep。合成模块映射 `_V2_NAMESPACE_TO_ACTION_PREFIX`（audit_log.py:207，tenant./llm.server./approval. 三个命名空间）。
■ 租户 scoping 与跨租户：`AuditLogDao.get_audit_logs(..., tenant_scope)`（audit_log.py:239-313）：tenant_scope=None → 平台超管全租户视图；=X → `_visible_for_tenant`（tenant_id==X OR operator_tenant_id==X）。DAO 全程 `bypass_tenant_filter()` 自管隔离。判定在 `AuditLogService._get_audit_tenant_scope`（api/services/audit_log.py:59-75）：is_global_super 且无 F019 admin-scope → None（跨租户），否则 get_current_tenant_id()。即「平台超管跨租户查询」后端已存在，还可经 F019 admin-scope 切到目标租户视角。
■ 查询接口：`/api/v1/audit`（GET，筛选 group_ids/operator_ids/start_time/end_time/system_id/event_type + 分页，api/v1/audit.py:13-27）、`/audit/operators`（操作人下拉）、`/audit/session` + `/audit/session/export/data`（会话审计及其导出）。操作日志本体无导出端点。权限：is_admin() 或角色 web_menu 含 'log' 或用户组管理员（组内交集）。
■ 平台审计页：platform/src/pages/LogPage/systemLog/index.tsx（264 行）。筛选器：操作用户(多选)/用户组/起止日期/系统模块/操作行为（模块与行为下拉硬编码在 platform/src/controllers/API/log.ts 的 getModulesApi/getActionsApi）；表列：审计ID/用户名/操作时间/系统模块/操作行为/对象类型/操作对象/IP/备注。无导出按钮、无租户筛选、无租户列。会话审计页 useAppLog/index.tsx 有 CSV 导出先例（exportCsvDataApi + exportCsv 前端拼 CSV）。
■ 用量数据：`llm_token_log`（bisheng/llm/domain/models/llm_token_log.py:31-82，tenant_id/user_id/model_id/server_id/session_id/prompt/completion/total_tokens/created_at），写入方 `LLMTokenTracker.record_usage`（llm/domain/services/token_tracker.py:38，依赖 tenant ContextVar，缺失即抛 TenantContextMissingError）与 workflow/callback/llm_usage_callback.py；`llm_call_log`（llm/domain/models/llm_call_log.py:24-73，含 endpoint/status/latency_ms/error_msg = 调用次数与成败）。读侧目前仅 QuotaService._count_tokens_monthly 用原生 SQL 求和做配额（role/domain/services/quota_service.py:654），没有任何「用量账单」查询 API 或 UI。两表均无 api key / 应用 token 维度；仓内不存在 ApiKey 模型（grep database/models 与 open_endpoints 无 api_key，与开放 API PRD「v2 现状零鉴权」一致）。
■ 双归属：audit_log 只有 operator_*（actor）侧，无 subject（被代表用户）列；audit_metadata JSON 可承载但不可索引筛选。

【站内消息（全部 verified）】
■ 表：`inbox_message`（bisheng/message/domain/models/inbox_message.py:22-87）：content=JSON 数组（结构化 items：user/system_text/business_url/target/tooltip_text/agree_reject_button）、sender(int)、message_type(notify|approve)、receiver=JSON int 数组、status(wait_approve|approved|rejected)、action_code(varchar64，驱动前端文案与路由)、operator_user_id、tenant_id；配套 `inbox_message_read` 已读表。两表均注册在 `_TENANT_AWARE_MODEL_MODULES`（core/database/tenant_filter.py:79-80），读写受 F013 租户自动过滤/回填。
■ API：`/api/v1/message/*`（message/api/endpoints/message_endpoint.py）：list（tab=all|request）、unread_count、mark_read、mark_all_read、approve（同意/拒绝按钮回传）、delete。tab=request 用 `APPROVAL_CENTER_NOTIFY_ACTION_CODES`（message_service.py:32，10 个审批类 action code）过滤。
■ 发送门面：`MessageService.send_generic_notify(sender, receiver_user_ids, content_item_list, action_code)`（message_service.py:401）与 `send_generic_approval(...)`（:474，含 agree_reject_button + approval_id 回填）。任意模块可向任意 user_id 列表发消息——现有调用方：channel_service（4 处）、knowledge_space_service（3 处）、permission/resource_permission_notification_service（3 处）、approval_service/approval_center_service/approval_notification_service、tenant/domain/services/inbox_helper.py（无请求上下文的 Celery/SSO 场景 best-effort 发送，sender=0，并有 list_global_super_admin_ids 的 FGA 收件人解析先例）。内容统一由 `notification_content.build_notify_content` 构造。send_message 尾部挂 `maybe_forward_external`（notification/forwarder.py，中粮 E+ 定制外发钩子，按 action_code 路由）。
■ 审批中心触达：`approval/domain/services/approval_notification_service.py` 封装 notify_user/notify_users → send_generic_notify（action code 如 approval_task_pending/approval_instance_approved）；审批「待办」本体在 approval 模块自有表（ApprovalInstance/ApprovalTask，approval/domain/models/approval_instance.py），站内消息只是通知镜像，处理动作回审批中心界面完成——与 PRD「消息不承载操作」的约定天然一致。
■ Client 工作台入口：铃铛 + 未读角标在 client/src/layouts/UserPopMenu.tsx（Outlined.Bell，>99 显示 99+），计数 hook useNotificationCount.ts（150s 轮询 + focus/visibilitychange 即时刷新），消息中心弹窗 NotificationsDialog.tsx（1221 行，tab 全部/申请、action_code→i18n label 映射与跳转逻辑硬编码在组件内、agree/reject 按钮调 /message/approve）。API 封装 client/src/api/message.ts。
■ Platform 管理端无任何消息 UI（grep message/list、unread_count 无命中）——与 PRD「管理后台不设消息面」现状即吻合。

## key_files
- src/backend/bisheng/database/models/audit_log.py — AuditLog 模型（legacy+v2 双轨字段）、EventType/SystemId/ObjectType 枚举、_UI_VISIBLE_V2_ACTIONS 白名单、AuditLogDao.get_audit_logs(tenant_scope)/ainsert_v2 —— 审计扩展的核心锚点
- src/backend/bisheng/api/services/audit_log.py — AuditLogService：legacy 语义化写入门面 + _get_audit_tenant_scope（超管跨租户/F019 admin-scope 判定）+ 查询权限（is_admin/web_menu 'log'/组管理员）
- src/backend/bisheng/api/v1/audit.py — /api/v1/audit 查询路由（无操作日志导出端点；/session/export/data 是会话导出）
- src/frontend/platform/src/pages/LogPage/systemLog/index.tsx — 管理后台审计页（PRD 说的「既有审计页」）：5 筛选器 + 9 列；无导出、无租户筛选/列
- src/frontend/platform/src/controllers/API/log.ts — 前端模块/行为枚举白名单硬编码处（getModulesApi/getActionsApi/actionToI18nKey），需与后端 _UI_VISIBLE_V2_ACTIONS lockstep；useAppLog 页有 exportCsv 先例
- src/backend/bisheng/llm/domain/models/llm_token_log.py — token 用量表（tenant/user/model/server/session 维度，无 key 维度）——按 key 账单的改造对象
- src/backend/bisheng/llm/domain/services/token_tracker.py — LLMTokenTracker.record_usage 写入口（依赖 tenant ContextVar，缺失抛 TenantContextMissingError）
- src/backend/bisheng/llm/domain/models/llm_call_log.py — 调用次数/成败/耗时表（endpoint/status/latency_ms），账单的『调用次数』数据源
- src/backend/bisheng/message/domain/models/inbox_message.py — 站内消息表 InboxMessage（content JSON items/receiver JSON 数组/action_code/tenant_id）
- src/backend/bisheng/message/domain/services/message_service.py — MessageService：send_generic_notify/send_generic_approval 通用发送门面 + APPROVAL_CENTER_NOTIFY_ACTION_CODES（tab=request 过滤）
- src/backend/bisheng/message/api/endpoints/message_endpoint.py — /api/v1/message/* 路由：list/unread_count/mark_read/mark_all_read/approve/delete
- src/backend/bisheng/message/domain/services/notification_content.py — build_notify_content：通知内容协议统一构造器（新事件按此拼 content items）
- src/backend/bisheng/approval/domain/services/approval_notification_service.py — 审批中心站内信触达封装（notify_users → send_generic_notify），发布审批类事件的复用入口
- src/backend/bisheng/tenant/domain/services/inbox_helper.py — 无请求上下文（Celery/SSO）发站内信的先例 + list_global_super_admin_ids（FGA 解析管理员收件人）
- src/frontend/client/src/layouts/UserPopMenu.tsx — 工作台铃铛图标 + 未读角标（PRD『消息提醒』入口，已存在）
- src/frontend/client/src/components/NotificationsDialog.tsx — 消息中心弹窗（1221 行）：action_code→i18n 文案与跳转映射硬编码于此，新事件需扩展
- src/frontend/client/src/hooks/useNotificationCount.ts — 未读数轮询（150s + focus 刷新）
- src/backend/bisheng/core/database/tenant_filter.py — inbox_message/inbox_message_read 注册于 _TENANT_AWARE_MODEL_MODULES（:79-80）——消息读写受租户自动过滤，跨租户投递需留意
- src/backend/bisheng/notification/forwarder.py — send_message 尾部的外部转发钩子（中粮 E+ 定制），新增 action_code 不影响但会经过其路由判断

## reuse
- 审计写入机制：12 类新事件全部可走既有 v2 结构化写入 AuditLogDao.ainsert_v2（database/models/audit_log.py:365），按点分命名空间新增 action（如 app.create/app.publish/apikey.issue），与 15+ 既有调用方同一模式；不需要新表（audit_metadata JSON 可放能力声明 diff、版本号等特有要素）
- 平台超管跨租户审计查询：后端已完整支持——AuditLogDao.get_audit_logs 的 tenant_scope=None 全租户视图 + _visible_for_tenant OR 谓词 + F019 admin-scope 切租户视角（api/services/audit_log.py:59-75）；只差前端租户筛选器/租户列与接口透传参数
- 审计查询面：直接扩展 platform LogPage/systemLog 页 + /api/v1/audit 接口；模块/行为下拉的扩展点即 log.ts getModulesApi/getActionsApi + 后端 _V2_NAMESPACE_TO_ACTION_PREFIX/_UI_VISIBLE_V2_ACTIONS；导出可照抄 useAppLog 页的 exportCsvDataApi+exportCsv 前端 CSV 先例
- 用量原始数据：token 计量复用 llm_token_log + LLMTokenTracker.record_usage（llm/domain/services/token_tracker.py:38），调用次数/耗时/成败复用 llm_call_log——账单只需加 key 归属维度和聚合读路径，不必新造计量链路
- 站内消息发送：MessageService.send_generic_notify（message/domain/services/message_service.py:401）已是『任意模块→任意 user_id 列表』的通用门面，PRD ~8 条事件通知全部可用它实现；内容协议走 notification_content.build_notify_content；无请求上下文场景（Celery/发布流水线）照抄 tenant/domain/services/inbox_helper.py 先例
- 审批类事件触达：PRD 明确『复用审批中心既有触达』——approval_notification_service.notify_users + send_generic_approval + 审批中心待办（ApprovalInstance/ApprovalTask）整链已在生产使用；应用发布审批接入审批中心场景（scenario_code）后触达自动获得
- 工作台『消息提醒』入口：铃铛+未读角标+消息弹窗+已读标记+150s 轮询全部现成（UserPopMenu.tsx / NotificationsDialog.tsx / useNotificationCount.ts），新事件仅需 action_code→i18n label 与跳转落点映射
- 『管理后台不设消息面』：platform 现状本来就没有消息 UI（已 grep 验证零调用），该 PRD 约定零工作量
- 收件人为『租户管理员』的解析：inbox_helper.list_global_super_admin_ids 提供了经 OpenFGA list_users 解析管理员收件人的现成写法

## gaps
- 审计双归属（actor=应用 token / subject=当前访问用户）：audit_log 无 subject 列——需新增列（alembic，兼顾 DM8）或约定 audit_metadata JSON 字段；若要按 subject 筛选/追责必须加索引列。companion PRD §4.4.5/§4.8.1 同样要求，两册需统一字段定义
- ~12 类新审计事件的写入点：分散在应用工场各新功能（造应用/能力声明/发布回滚/密钥事件/改码权交接/可见范围变更/生产数据行编辑/访问记录），每个功能落地时埋点 ainsert_v2 + 三处白名单同步（后端 _UI_VISIBLE_V2_ACTIONS、前端 getModulesApi/getActionsApi、i18n + logActions.test.ts）
- 审计页前端增量：租户筛选器 + 租户列（仅平台超管视角）+ /api/v1/audit 接口透传 tenant 参数；操作日志导出（后端无导出端点，前端无按钮——会话导出不覆盖操作日志）
- 按 key 用量账单（最大块新建）：① API key/应用 token 体系本身未实现（无 ApiKey 表，v2 零鉴权——硬前置依赖 companion 开放 API PRD 落地）；② llm_token_log/llm_call_log 加 key_id（credential 归属）与 actor/subject 维度列；③ 聚合查询 API（按 key/时间段/模型拆分的 token 用量+调用次数）；④ platform『API key 管理页』行内用量入口 UI（该管理页本身也属新建）；⑤ client 工作台『我的 API key』本人用量自查 UI
- 访问记录（RT-01 谁在用）与运行期能力调用审计：高频写入场景，audit_log 现无异步/批量写入与归档能力——需要决定是否进 audit_log 或单独访问日志表
- ~8 条事件通知的新 action_code 全链路：后端常量 + 各业务调用点（配额不足通知 owner+租户管理员、停运/重新启用/代调可见范围、应用 token 强制吊销等）+ client NotificationsDialog 的 label/跳转映射 + 三语 i18n；跳转落点（发布面/应用管理列表）本身是 PRD-2/RT 的新页面
- 『租户管理员』收件人解析服务：现有先例只解析 global super_admin，需按租户解析 tenant_admin 用户列表的通用 helper

## risks
- audit_log 单表容量/性能：uuid 主键 + 8 个索引，现有事件全部低频管理动作；PRD 把『访问记录』『运行期能力调用』这类高频事件也归入审计——直接写 audit_log 会造成写放大与查询变慢，且平台无归档/TTL 机制（DM8 环境已有大表写放大事故先例）。建议高频类走独立表或复用 llm_call_log 扩展（C2 双库都要过）
- 三处白名单 lockstep 漂移：后端 _UI_VISIBLE_V2_ACTIONS ↔ 前端 getModulesApi/getActionsApi ↔ i18n，源码注释已明示必须同步；一次新增 12 类事件极易漏一处导致『写了查不到』（写库成功但 UI 白名单过滤掉）
- 计量写入依赖 tenant ContextVar：LLMTokenTracker.record_usage 缺租户上下文直接抛 TenantContextMissingError——开放 API/应用 runtime 的调用链（应用 token 鉴权后）必须正确 set_current_tenant_id，否则整条计费链路崩；v2 现状零鉴权无此保障，账单功能强依赖 companion PRD 的密钥→租户解析落地（C3）
- inbox_message 受 F013 租户自动过滤（tenant_filter.py:79 注册，verified）：消息 tenant_id 由写入时上下文自动回填，读取按读者租户上下文过滤——跨租户投递（如平台超管收子租户事件通知）会被隐藏（inferred，需实测）；PRD 事件接收方含租户管理员，多租户部署下要核实写入上下文与接收方租户一致
- 双归属的『操作人』筛选语义未定：审计页现有『操作人』下拉按 operator_id；应用 token 调用时 operator 是应用还是访问用户需拍板，否则筛选器与 get_all_operators 下拉的行为会混乱
- DM8 兼容（C2）：inbox repo 与 audit DAO 均已为 JSON 查询做 MySQL/DM8 方言分叉（json_contains vs text LIKE）；新账单聚合与新审计筛选若用 JSON 函数必须同样分叉，估算时不可按纯 MySQL 计
- 错误码与模块号（C5/C6）：新账单/导出 API 需按 MMMEE 规范注册错误码；新表（如 api key、账单聚合物化表）须注册 _TENANT_AWARE_MODEL_MODULES 否则漏租户过滤（C3）
- NotificationsDialog 已 1221 行，超过前端单文件 600 行硬规——再往里加 ~8 个 action_code 映射前应先按 react-component-refactor 拆分，否则违反前端 P0 规则

## open_questions
- 高频事件分层：『访问记录（谁在用）』『运行期能力调用』是否与管理动作同进 audit_log 单表？还是访问记录独立表 + 能力调用挂 llm_call_log/llm_token_log 扩展？（影响审计页『事件类型』枚举呈现与容量方案）
- 双归属字段形态：subject（被代表用户）做可索引新列还是 audit_metadata JSON 约定？审计页『操作人』筛选对双归属事件按 actor 还是 subject 匹配？需与 companion 开放 API PRD §4.8.1 的字段清单一次对齐
- 按 key 账单的数据通道：实时聚合查询 llm_token_log（量大时慢）还是引入按日聚合表/物化任务？是否随 Beat 定时跑（多租户迭代坑）
- 审计导出的范围与格式：照抄会话导出的前端拼 CSV（当前上限逻辑在前端），还是后端流式导出？超管跨租户导出是否含租户列？
- 操作日志本身要不要出现在应用工场事件里做保留期/合规要求（PRD 未提留存时长，现无 TTL/归档）
- 消息接收方为『租户管理员』时的精确定义：tenant_admin 角色全体？含部门管理员？平台超管是否兜底接收（涉及上文跨租户过滤问题）
- 个人 key 用量自查入口（工作台账户菜单『我的 API key』）与冻结的 knowledge-space-quota-display 账户菜单改造是否共用布局（该分支已冻结，是否复活其账户菜单骨架）
- ~12 类审计事件是否全部要进『审计页 UI 白名单』：现有产品决策（2026-05-06）是 v2 action 只精选子集曝光——应用工场事件是全量曝光还是同样分『合规留痕』与『UI 可见』两档
