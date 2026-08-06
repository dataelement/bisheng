# auth-identity

## summary
平台登录是「PyJWT HS256 + HttpOnly cookie(access_token_cookie, path=/, host-only)」的无状态体系：账号密码走 /api/v1/user/login，SSO/扫码由商业网关经 HMAC login-sync 回调完成；v1 端点鉴权统一收口在 LoginUser.get_login_user（只认 cookie），token_version(F012) 是唯一的服务端失效机制。PRD 所需的个人 API key、MCP/双协议/CLI 三面、/apps/{id} 入口均无现成实现，但「构造 UserPayload + set_current_tenant_id」的并行鉴权收口模式（get_default_operator_async 已示范）、client 401→LOGIN_PATHNAME→platform 登录→回跳的免二次登录链路、client 头像下拉 AccountSettings.tsx 均可直接承接。账号禁用经 aincrement_token_version 即时废除 JWT，可作为 key 自动失效的挂接点。

## current_state
【登录流｜verified】账号密码：POST /api/v1/user/login（src/backend/bisheng/user/api/user.py:150）→ UserService.user_login（src/backend/bisheng/user/domain/services/user.py:420-660）：验证码(Redis)→RSA 解密密码→同名候选逐一校验→「无可用菜单拒登」守卫(_reject_login_if_user_has_no_usable_access)→多租户 leaf 解析(UserTenantSyncService.sync_user, F012)→读 fresh token_version→LoginUser.create_access_token→set_access_cookies（同时把 access_token 放响应体）→写 Redis USER_CURRENT_SESSION（只写不读，OSS 无单会话/异地登录强制；10604 异地登录码来自商业网关，platform request.ts:173 有处理分支）→审计(AuditLogService.user_login)+telemetry。SSO/扫码：OSS 侧 /api/v1/user/sso（user.py:59，已标 deprecated，需 bisheng_pro）自动建用户+发 token；新链路 = 商业 Java Gateway 完成 IdP/企微交互后回调 HMAC 认证的 /api/v1/internal/sso/login-sync（src/backend/bisheng/sso_sync/api/endpoints/login_sync.py + domain/services/hmac_auth.py）。前端侧：platform 登录页（src/frontend/platform/src/pages/LoginPage/login.tsx:43-84）启动时调 getSSOurlApi()（API/pro），若配置 redirect_login_url 则整页跳 IdP，并把 THIRD_PARTY_LOGIN_URL/THIRD_PARTY_LOGOUT_URL 存 localStorage 供 401/登出跳转；loginBridge.tsx 渲染 SSO/企微扫码按钮（oauthData.sso / oauthData.wx，点击 location.href 跳转）；/admin-login 为绕过 SSO 自动跳的后门（routes/index.tsx:161）。
【JWT 签发与校验｜verified】库 = PyJWT（`import jwt`），HS256，自研 AuthJwt 类（src/backend/bisheng/user/domain/services/auth.py:157-221）：payload sub=json{user_id,user_name,tenant_id,token_version}，exp=now+cookie_conf.jwt_token_expire_time（默认 86400s），iss=jwt_iss（默认 bisheng），secret=settings.jwt_secret。Cookie 配置 CookieConf（src/backend/bisheng/core/config/settings.py:482-493）：名 access_token_cookie，path="/"，domain=None（host-only），httponly=True，secure=False，samesite=None——path=/ 且 host-only 意味着同源下 /workspace、/admin（以及未来的 /apps/{id}）天然共享登录态，这是 RT-01「免二次登录」的现成物理基础。端点鉴权依赖 = LoginUser.get_login_user（auth.py:625，classmethod Depends）→ AuthJwt.get_subject() 默认 auth_from="request" **只读 cookie**；auth_from="headers"（读 Authorization Bearer）分支存在但全仓无调用方（死分支，verified by grep）；WebSocket 的 get_login_user_from_ws（auth.py:651）在 get_subject("websocket") 中 `if websocket: token = websocket.cookies.get(...)` 无条件覆盖传入的 t 参数（t 永不生效）。UserPayload = class UserPayload(LoginUser)（src/backend/bisheng/common/dependencies/user_deps.py:10），全仓 v1 端点統一 Depends 它或 LoginUser。HTTP 中间件（src/backend/bisheng/utils/http_middleware.py）：_extract_http_access_token 兼收 cookie 与 Bearer → 解 JWT → set_current_tenant_id（C3）+ _validate_token_version（F012：与 UserDao.aget_token_version 比对，Redis key user:{id}:token_version TTL=300s，fail-open，mismatch→401「token_version mismatch」）；TENANT_CHECK_EXEMPT_PATHS 豁免登录/验证码/login-sync 等。
【会话存储｜verified】无服务端 session，JWT 全无状态；Redis USER_CURRENT_SESSION（user_current_session:{uid}）仅在 login/sso/switch-tenant 写入，无任何读取方——不能当会话依据。
【前端携带】platform（verified）：axios.defaults.withCredentials=true + 请求拦截器把 localStorage ws_token 注入 Authorization: Bearer（src/frontend/platform/src/controllers/request.ts:13-21）；但 ws_token 仅在 iframe 内嵌时保存（login.tsx:161 `window.self===window.top ? remove : set`），顶层窗口纯 cookie；注意 Bearer 只被中间件消费，端点依赖仍只认 cookie。client /workspace（verified）：~/api/request.ts 纯同源 cookie，setTokenHeader 是 no-op（src/frontend/client/src/api/chat/headers-helpers.ts:7-9），用户态来自 /api/v1/user/info（api/chat/api-endpoints.ts:4）；client 自带的 /workspace/login 页（routes/index.tsx:128）POST /api/auth/login 是 LibreChat 遗留死路由（后端无 /api/auth），生产不生效——真登录永远在 platform SPA。
【登录回跳现状（RT-01 相关）｜verified】client 生产 401：request.ts:242-244 `localStorage.setItem('LOGIN_PATHNAME', location.pathname)` → 跳 getPlatformAdminPanelUrl()（src/frontend/client/src/utils/platformAdminUrl.ts，BISHENG_HOST 默认 /admin）；platform 登录成功后 login.tsx:163-176 读 LOGIN_PATHNAME 并 location.href 回跳，否则按 default_entry（LoginUser.default_web_entry，auth.py:759）落工作台/后台。已知局限：只存 pathname（丢 query/hash）；platform 自身 401 只回根不存回跳地址（request.ts:200-204）；SSO 自动跳 IdP 部署下回跳由网关 redirect 配置决定，LOGIN_PATHNAME 机制不参与（网关内部行为为 inferred，login-sync 端点为 verified）。
【账号禁用/删除传导｜verified】禁用 = /user/update 把 delete 置 1（user.py:697-731）→ UserService.ainvalidate_jwt_after_account_disabled（user/domain/services/user.py:70-90）→ UserDao.aincrement_token_version（原子 UPDATE + **主动 aset 刷新 Redis 缓存**，使失效即时而非等 300s TTL；user/domain/models/user.py:513-538）+ TenantScopeService.clear_on_token_version_bump → 中间件下一请求 401。登录侧候选查询排除 delete=1 并单独提示 UserForbiddenError。无用户硬删除端点（delete 字段即软删/禁用，org-sync 禁用带 disable_source 仅超管可恢复）。token_version 机制只覆盖 JWT——PAT 不是 JWT，key 自动失效需另行挂接。
【(a) PAT 并行鉴权集成点】v2 open_endpoints 现状（verified）：零鉴权 + get_default_operator_async / resolve_operator（src/backend/bisheng/open_endpoints/domain/utils.py）按配置 default_operator 构造 UserPayload 并 set_current_tenant_id——这就是「非 cookie 身份 → UserPayload 收口」的现成模式（伴生 PRD 已判此链路改 SAK）。MCP 面/OpenAI-Anthropic 双协议面/CLI 面在代码中不存在（mcp_manage 仅出站 client：clients/{sse,stdio,streamable}.py，无 FastMCP/inbound server，无 /v1/chat/completions 兼容端点，verified by grep）。PAT 鉴权应是与 LoginUser.get_login_user 平行的新 FastAPI dependency：解析 Authorization: Bearer bs-pat-* → hash 查表 → init_login_user(user_id, tenant) + set_current_tenant_id（init_login_user 已支持任意 user_id/tenant_id，auth.py:565）。
【(c) 账户菜单｜verified】src/frontend/client/src/components/Nav/AccountSettings.tsx —— 头像下拉 DropdownMenu（个人知识 MyKnowledgeView、管理后台入口 canShowPlatformAdminEntry、语言子菜单、退出登录）；「我的 API key」DropdownMenuItem 加在 DropdownMenuContent（第 100-140 行区间），弹窗形态可仿 MyKnowledgeView/Settings 的受控 open state。

## key_files
- src/backend/bisheng/user/domain/services/auth.py — AuthJwt(PyJWT HS256, cookie 名 access_token_cookie)+LoginUser：create_access_token/get_subject(只认 cookie, headers 分支无调用方)/get_login_user 依赖(:625)/init_login_user(:565, PAT 依赖可复用)/default_web_entry(:759 登录落点)
- src/backend/bisheng/common/dependencies/user_deps.py — UserPayload(LoginUser) 全仓 v1 鉴权依赖入口(:10)+get_tenant_admin_user(:78)——PAT 平行依赖应落此层
- src/backend/bisheng/user/domain/services/user.py — user_login 全流程(:420-660)；ainvalidate_jwt_after_account_disabled(:70) 禁用即时废 JWT——key 自动失效的挂接点
- src/backend/bisheng/user/api/user.py — /user/login(:150) /user/sso(:59 deprecated) /user/logout(:261)；/user/update 禁用分支(:697-731) 调 ainvalidate
- src/backend/bisheng/user/domain/models/user.py — UserDao.aget_token_version/aincrement_token_version(:479-538)：Redis TTL300s+bump 时主动刷新缓存——PAT 吊销 5s 上界可照抄此模式
- src/backend/bisheng/utils/http_middleware.py — cookie/Bearer 双收→tenant ContextVar+token_version 校验(fail-open)；TENANT_CHECK_EXEMPT_PATHS 豁免清单——新 PAT 面路径需在此定位
- src/backend/bisheng/core/config/settings.py — CookieConf(:482-493)：path=/ host-only httponly——/apps/{id} 同源免二次登录的物理基础
- src/backend/bisheng/open_endpoints/domain/utils.py — get_default_operator_async/resolve_operator：非 cookie 身份→UserPayload+set_current_tenant_id 的现成收口模式(伴生 PRD 改 SAK 的对象)
- src/backend/bisheng/sso_sync/api/endpoints/login_sync.py — HMAC 认证的网关 SSO 回调(/api/v1/internal/sso/login-sync)，SSO 身份进入平台的唯一新链路
- src/frontend/platform/src/pages/LoginPage/login.tsx — 平台登录页：SSO 自动跳(:43-84)+登录成功读 LOGIN_PATHNAME 回跳(:163-176)+default_entry 分流
- src/frontend/platform/src/controllers/request.ts — platform axios：withCredentials+ws_token Bearer 注入(:13-21)；401→回根(:185-206)、403/404→Page403、10604 异地登录分支
- src/frontend/client/src/api/request.ts — client axios：纯 cookie；生产 401→存 LOGIN_PATHNAME(仅 pathname)→跳 platform 登录(:242-245)——回跳机制的写端
- src/frontend/client/src/components/Nav/AccountSettings.tsx — 工作台头像下拉菜单——「我的 API key」入口的落点(DropdownMenuContent :100-140)
- src/frontend/client/src/hooks/AuthContext.tsx — client 登录态容器：user 来自 /api/v1/user/info；logout 走 THIRD_PARTY_LOGOUT_URL 或回 platform
- src/frontend/client/src/utils/platformAdminUrl.ts — client→platform 跳转 URL 构造(BISHENG_HOST/PLATFORM_ORIGIN)，回跳链路的另一半
- src/frontend/client/src/routes/index.tsx — client 路由：/apps 广场已存在(:181)、/share/app 落地页、/workspace/login 为 LibreChat 死路由(:128)——/apps/{id} 新路由的挂载处

## reuse
- 免二次登录基础：CookieConf path=/ + host-only（core/config/settings.py:482）使同源下任何新路径（含 /apps/{id}）自动带 access_token_cookie，后端 LoginUser.get_login_user 直接可用——RT-01「已登录点开即用」零后端改造
- 登录回跳骨架：client request.ts:242-244 LOGIN_PATHNAME 写入 + platform login.tsx:163-176 读取回跳，已覆盖「无登录态→登录页→回原地址」主链路，/apps/{id} 挂 client SPA 即可复用（需补 query/hash 保留）
- SSO 复用：登录页 SSO 自动跳/扫码按钮（login.tsx+loginBridge.tsx）与网关 login-sync 回调（sso_sync/）即 RT-01『含平台已配置的 SSO 方式』的现成实现，无需新做
- PAT 身份收口模式：open_endpoints/domain/utils.py get_default_operator_async 已示范『非 cookie 凭据→查 User→UserPayload.init_login_user+set_current_tenant_id』，bs-pat- 依赖照此结构写即可；init_login_user(auth.py:565) 支持任意 user_id/tenant_id
- 撤销即时生效模式：UserDao.aincrement_token_version（user/domain/models/user.py:513）的『原子 UPDATE+主动刷新 Redis 缓存(TTL300s)』正是 PRD『吊销生效上界 5 秒、主动清缓存』要的形状，PAT 校验缓存可照抄
- 账号禁用联动：UserService.ainvalidate_jwt_after_account_disabled（user.py:729 唯一调用点）是『禁用→名下 key 全部失效』的天然挂接点；登录候选查询已排除 delete=1 用户
- 身份/组织注入数据源：LoginUser.init_login_user + /api/v1/user/info（client 已消费）已含 user/role/dept 信息，RT-01『应用取得访问者身份与组织信息』可直接复用该 payload 结构
- 审计先例：AuditLogService.user_login + telemetry_service.log_event(USER_LOGIN) 给 key 签发/吊销/调用审计提供了现成写入模式
- 账户菜单落点：AccountSettings.tsx 的 DropdownMenu 结构与 MyKnowledgeView 弹窗形态即『我的 API key』入口+弹窗的模板；canShowPlatformAdminEntry 是入口条件渲染的先例（GOV-07 隐藏可仿）

## gaps
- 个人 API key 全套后端：新表（key hash、bs-pat- 前缀、scope JSON、过期、吊销态、持有人、最近调用）+ DAO + 签发/吊销/scope 调整服务——注意新表须注册 tenant-aware（_TENANT_AWARE_MODEL_MODULES）
- PAT 鉴权 FastAPI dependency：解析 Authorization: Bearer bs-pat-* → hash 查表 → 校验状态/过期/scope → 查 user.delete(fail-closed) → UserPayload+set_current_tenant_id；含吊销缓存（主动失效，5s 上界）
- 三个消费面全部新建：MCP Server 面（仓内只有出站 MCP client，无 inbound server）、OpenAI/Anthropic 双协议兼容端点（无 /v1/chat/completions 类路由）、CLI（bisheng login/dev/deploy/logs，凭据存本地用户目录）
- /apps/{id} 统一入口路由 + 四类兜底页（无权限/未部署引导/已停用/不存在）——client routes 只有 /apps 广场与 /share/app 跳转，无按应用标识的入口页
- 回跳机制补强：LOGIN_PATHNAME 只存 pathname 丢 query/hash；platform 自身 401 不记回跳地址；SSO 自动跳 IdP 部署下的回原应用链路需打通（网关 redirect 配置）
- 管理后台 API key 管理页（platform 三类 key 同页 GOV-08）+ 工作台『我的 API key』弹窗（AccountSettings 新 DropdownMenuItem）+ 一次性展示/掩码组件
- 账号禁用→名下 key 自动失效联动 + 事件审计（现有 ainvalidate 只 bump token_version，不涉及任何 key 概念）
- GOV-07『未部署开放能力层则入口不展示』的配置开关与前端判定链（现无对应 bsConfig/env 字段）
- key 前缀模式进发布前密钥扫描规则集（RT-03/DEV-04 侧，本仓无扫描器）

## risks
- 端点鉴权只认 cookie（AuthJwt.get_subject 默认分支；headers 分支零调用方）：任何『用 PAT 调既有 v1 端点』的想法都会静默失败——PAT 必须走独立 router+独立依赖，不能幻想复用 v1 面（C1/C4：新面权限仍须经 PermissionService）
- 多租户 ContextVar（C3）：http_middleware 只从 JWT 设 tenant context，PAT 请求无 JWT——依赖内必须 set_current_tenant_id（get_default_operator 的 NoTenantContextError 教训已写在其 docstring），且持有人 active tenant 需在校验时实时解析
- token_version 的 300s Redis TTL + fail-open 只因『bump 时主动刷缓存』才达到即时失效——PAT 吊销若只做 TTL 缓存会违背 PRD 5 秒上界承诺，必须复刻主动清缓存；且 fail-open 语义（Redis 挂了放行）对凭据类校验是否可接受需明确改判 fail-closed
- SSO 自动跳 IdP 部署（THIRD_PARTY_LOGIN_URL 配置时登录页整页跳走）下，未登录访问 /apps/{id} 的回跳目标由商业网关 redirect 配置控制，OSS 侧 LOGIN_PATHNAME 机制完全不参与——免二次登录验收项 3 在该形态需网关配合（网关行为 inferred，需与商业侧确认）
- client /workspace/login 是 LibreChat 死代码（POST 不存在的 /api/auth/login）——评审/设计时勿把它当活的登录面（判断在用要追前端的教训）
- 无用户硬删除端点：PRD 写『账号被禁用/删除』，代码只有 delete 软删/禁用一种——『删除』语义需在 spec 里对齐为禁用，或 key 校验对 user 不存在也 fail-closed
- USER_CURRENT_SESSION 只写不读、10604 异地登录来自网关：不要把它当可复用的会话吊销机制
- cookie secure=False/samesite=None 默认值：手机扫码经外部浏览器进入 /apps/{id} 的场景若将来要求跨站嵌入或 https 严格模式，现配置是隐患（现状 verified，影响 inferred）
- PRD 要求每次调用审计到人+按 key 计量：现有 AuditLogService 是低频操作审计，per-call 写放大需要新的计量通道设计（勿直接往 audit 表灌）

## open_questions
- /apps/{id} 由哪个 SPA 承载：client(/workspace) 下新路由（天然复用 cookie+回跳+AccountSettings）还是独立轻量 shell？决定回跳改造与四类兜底页的落点
- SSO 自动跳 IdP 的部署形态下，登录成功回跳原 /apps/{id} 是否需要商业网关改造（把原始 URL 透传进 redirect 链）？OSS 侧无法单方面闭环
- PAT 三面（MCP/双协议/CLI 网关路径）挂 /api/v2 之下还是新顶级前缀？影响 http_middleware 豁免清单、商业网关转发规则与 GOV-07 开关粒度
- GOV-07『未部署开放能力层』的判定来源：环境级配置(BS_ env)、DB config、还是 license？前端两个入口（管理页/账户菜单）需要统一的探测接口
- key 校验对账号状态的策略拍板：每次调用实时查 user.delete（fail-closed，天然满足验收 7）vs 禁用事件批量吊销 key（PRD 两种表述都有，语义需统一）
- PAT 与伴生 PRD 的 SAK（bs-sak-）是否共用同一张凭据表+同一校验底座（GOV-08 说同源）——影响表设计一步到位还是两步走
- 回跳保真度要求：/apps/{id} 是否会带 query（如渠道参数）？若是，LOGIN_PATHNAME 需改存 pathname+search+hash 并评估开放跳转风险
