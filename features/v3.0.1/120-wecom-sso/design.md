# Design: 企业微信单点登录（WeCom SSO，无网关）

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**；本文回答 **为什么这么实现**：关键决策、运行时不直观的事实、对外契约。
> - 实现变化 → 覆盖更新本文档；每个决策保留「为什么 + 被否方案」和坑。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v3.0.1
**最后更新**: 2026-11-16

---

## 1. 目标与非目标

- **目标**：在**没有商业版 Java 网关**的部署里，由 BiSheng 后端自己完成企业微信 OAuth2 授权与回调，把企微身份交给既有 `LoginSyncService` 完成建号 / 部门绑定 / 租户派生 / JWT 签发，并把登录态以 cookie 交给两个 SPA。
- **非目标**：不实现自定义 OAuth2 / LDAP / 钉钉 / 飞书；不做单点退出；不新建企微凭据管理面（凭据唯一来源是组织同步配置）；不实现企微「服务商代开发」扫码。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C7（分层 / 双 DB / 多租户自动注入 / 权限统一入口 / 错误码 / 无硬编码密钥 / 前端 store 不直连 HTTP）与 C8（多进程无本地共享状态 → state 必须落 Redis）。
- **spec 级约束**：INV-44（首登超管只一次）、INV-45（凭据唯一来源）、INV-46（token 不进 URL）、INV-47（复用 LoginSync 语义，见 [release-contract](../release-contract.md)）。
- **登录发生在租户上下文之外**：请求到达时没有 tenant ContextVar（`/api/v1/user/wecom/*` 在中间件白名单里与 `/user/login` 同级），读 `org_sync_config` 必须 `bypass_tenant_filter()`，写入侧由 `LoginSyncService` 自己设置 ROOT 上下文。
- **多节点**：OAuth state 与"一次性消费"语义必须跨进程成立 → Redis，不用进程内字典。
- **企业微信接口形态**（来源：企业微信官方文档，**未在真实企微租户联调过**，首次部署需按 §7 手工验证）：
  - 企微内网页授权：`https://open.weixin.qq.com/connect/oauth2/authorize?appid=<corpid>&redirect_uri=<enc>&response_type=code&scope=snsapi_base&state=<state>&agentid=<agent_id>#wechat_redirect`
  - PC 扫码登录：`https://login.work.weixin.qq.com/wwlogin/sso/login?login_type=CorpApp&appid=<corpid>&agentid=<agent_id>&redirect_uri=<enc>&state=<state>`
  - code → 成员：`GET https://qyapi.weixin.qq.com/cgi-bin/auth/getuserinfo?access_token=<token>&code=<code>` → `{userid}`（不在应用可见范围时只返回 `openid`）
  - 成员详情：`GET https://qyapi.weixin.qq.com/cgi-bin/user/get?access_token=<token>&userid=<userid>` → `{department[], main_department, name, email, mobile, status}`
  - 应用 token：`GET https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=&corpsecret=`（仓库内 `org_sync/domain/providers/wecom.py` 已实现并带 Redis 缓存）

---

## 3. 方案对比与选定

### 决策 1：代码归属 —— 放进既有 `bisheng/sso_sync` 模块

- **备选**：
  - A. `bisheng/sso_sync/`（新增 `api/endpoints/wecom_login.py` + `domain/services/wecom_*`）— 与 LoginSyncService、193 错误码段、HMAC 同域；
  - B. 新建 `bisheng/wecom_sso/` — 职责名字更准，但要跨模块 import `sso_sync` 的 service 与错误码，且 193 段属 sso_sync。
- **选定**：A
- **原因**：本 feature 的实质是"另一个 SSO 入口"，用户/部门/租户/JWT 全部走 `sso_sync` 的既有 service；错误码 19330–19349 已登记在 193 段。新模块只会多一层跨模块引用（RULE-5 针对 api 层，但分层上也没有收益）。
- **何时该重新考虑**：若后续要接入钉钉/飞书/LDAP 等多个 IdP，抽象出 `identity_providers/` 统一层时再拆。

### 决策 2：登录态交付 —— 服务端 Set-Cookie + 302，token 不进 URL

- **备选**：
  - A. 回调直接 `Set-Cookie: access_token_cookie=<jwt>` 后 302 回前端首页 — 与网关现状一致，前端无感；
  - B. 回调 302 到前端 `?token=<jwt>` 由 JS 存 localStorage — 令牌会进浏览器历史/日志/Referer（INV-46 禁止）；
  - C. 回调 302 带一次性 code，前端再 POST 换 token — 多一跳，且一次性 code 又是一份需要防护的凭据。
- **选定**：A
- **原因**：后端中间件（`utils/http_middleware.py:138`）与 WebSocket 鉴权（`user/domain/services/auth.py:180-182`）都优先读 `access_token_cookie`，设置即可全局生效；`AuthJwt.set_access_token()` 已封装 cookie 策略（`cookie_conf`：httponly/secure/samesite/path/domain），`/user/logout` 也已服务端 `delete_cookie`。
- **cookie 用非 HttpOnly**：平台现有会话是「登录响应返回 token → JS 写同名 cookie + `localStorage.ws_token`」，少数组件（`pages/BuildPage/.../TestChat.tsx`、`modals/formModal`）直接读 `ws_token`。SSO 若下发 HttpOnly cookie，JS 既写不了 `ws_token`，也无法在同名 cookie 上覆盖，会让这些功能静默失效。**安全性不因此下降**：密码登录路径本来就把同一枚 JWT 放进 JS 可读的 cookie 与 localStorage。实现时显式传 `httponly=False`，并在 design §5 记录该取舍。
- **何时该重新考虑**：若将来把 `ws_token` 从所有组件中移除、并把 cookie 全面改成 HttpOnly，则应同步改为 HttpOnly。

### 决策 3：OAuth state —— Redis 一次性键，GETDEL 消费

- **备选**：A. Redis `wecom_sso:state:{state}`，值 = `{mode, return_to}`，TTL 300s，回调时 `GETDEL`；B. 签名 state（无状态，但无法一次性消费）；C. 进程内字典（多节点失效，C8 禁止）。
- **选定**：A
- **原因**：既要防 CSRF（state 必须由本次发起方签发），又要防重放（一次性）。`GETDEL` 让"校验 + 消费"成为单条原子命令，并发双回调只有一个能成功。
- **何时该重新考虑**：Redis 不可用时不降级 —— 直接按 19332 拒绝（fail-closed）。

### 决策 4：凭据读取 —— 只读组织同步配置，要求唯一启用

- **备选**：A. 读 `org_sync_config`（provider=wecom，`status=active`），**恰好 1 条**才可用；B. 新增 `sso_sync.wecom.corp_id/...` 配置项；C. 新增登录专用设置页。
- **选定**：A
- **原因**：INV-45 / spec AC-01~AC-04。组织同步已经维护并加密存储（Fernet）这组凭据，且要求通讯录权限，语义天然一致。多条启用时无法判定该用哪套（AC-03）→ fail-closed 19331。
- **何时该重新考虑**：出现"同一平台连多个企微企业"的真实需求时，需要引入显式的默认配置指针。

### 决策 5：部门绑定 —— 先探测再降级，不吞业务异常

- **备选**：A. 登录前用 `DepartmentDao.aget_by_source_external_id(source='wecom', id)` 探测企微部门；缺失就不带部门字段（`LoginSyncService` 会落到 `BS@guest` 临时访客部门）+ WARNING 日志；B. 直接带部门让 `assert_parent_chain_exists` 抛 19312（拒绝登录）；C. 登录后补同步部门（超出本 feature 范围）。
- **选定**：A
- **原因**：spec AC-08 要求不阻断登录；但 19312 既是"未同步"也是"数据真的不一致"的信号，**不能**用 try/except 吞掉——吞掉会把其它部门的并发删除等真实故障也变成静默降级。探测是只读且精确的，只对"这个用户的部门不存在"这一事实降级。
- **何时该重新考虑**：若组织同步改为登录时实时拉取（on-demand sync），本决策作废。

### 决策 6：首登超管 —— 给 `LoginSyncService` 加显式开关，默认关闭

- **备选**：A. `LoginSyncService.execute(..., bootstrap_first_user_admin: bool = False)`，仅在新建用户分支且平台用户数为 0 时用 `add_user_and_admin_role` + AdminRole 同步（照搬旧 `/user/sso`）；B. 登录后由 WeCom 服务再提权（需要额外的角色写入 + 竞态 + 审计割裂）；C. 不改服务，要求客户先手工建超管（被 spec AC-11 否决）。
- **选定**：A
- **原因**：只有服务内部知道"这次是否新建了用户"，事后提权无法区分"新用户"与"老用户"；默认 `False` 保证网关/旧链路行为完全不变（AC-22/AC-24）。复制的只是 legacy `/user/sso` 已存在的引导语义（AC-25 明确 `admin_username` 不参与）。
- **何时该重新考虑**：若产品决定统一"首登引导"语义到所有登录方式，则把开关转正并写进契约。

### 决策 7：前端入口 —— platform 登录页承载，client 走既有回跳

- **备选**：A. platform 登录页新增「企业微信登录」按钮（放在现有 `LoginBridge` 同一区域），client 继续把未登录用户引导到 platform 登录页（既有跨应用契约），登录后由 `consumeLoginReturnTo()` 回到 client 原页面；B. client 自建登录页 + 按钮（client 目前没有线上登录页，等于新建一屏 UI）。
- **选定**：A
- **原因**：spec AC-19 已明确 client 不自建独立登录页；跨应用回跳契约（`LOGIN_PATHNAME` + `LOGIN_PATHNAME_AT`）已经在两端实现并有测试。
- **何时该重新考虑**：client 将来若拥有独立登录页，则在其上复用同一个 availability 接口。

### 决策 8：网关并存判定 —— 用 `bisheng_pro` 作为"网关已接管"的标记

- **备选**：
  - A. 后端 `availability` 在 `settings.get_system_login_method().bisheng_pro == true` 时直接返回 `enabled=false`，前端只在拿到 `enabled=true` 时才渲染自建入口；
  - B. 运行期探测 `/api/oauth2/list` 是否有网关响应（前端判断两套入口的优先级）— 探测结果受网络/缓存影响，且网关故障时会错误地启用自建链路；
  - C. 新增一个显式的部署开关配置项 — 引入第二处开关，与 `bisheng_pro` 语义重复。
- **选定**：A
- **原因**：商业版网关部署要求后端 `export BISHENG_PRO=true`（`docs/architecture/11-gateway.md` §11.1，「否则商业版接口不会注册」），因此它是现成的、运维已经必须设置的事实来源；前端拿到 `enabled=false` 即不渲染入口，网关自己的 `/api/oauth2/list` 继续决定它那套按钮（AC-24）。不引入新开关，避免两处配置漂移。
- **何时该重新考虑**：若出现"网关部署但想用后端自建企微登录"的真实客户，则改为显式配置开关。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

```text
[platform 登录页]
  GET /api/v1/user/wecom/availability
     → WeComLoginService.availability(): bisheng_pro=false（决策 8）且存在唯一启用的 wecom 组织同步配置
     → { enabled, mode, authorize_url }        # mode 由 UA 决定：wxwork → silent，否则 qr
  location.href = authorize_url
        ↓
GET /api/v1/user/wecom/authorize?return_to=<abs>
     → 校验 return_to（白名单/同源）→ 生成 state 写 Redis（TTL 300s）
     → 302 企微授权页（silent: open.weixin.qq.com/connect/oauth2/authorize；qr: login.work.weixin.qq.com/wwlogin/sso/login）
        ↓
企微授权 → 302 /api/v1/user/wecom/callback?code=&state=
     → GETDEL state（缺失/过期 → 19332）
     → WeComOAuthClient: gettoken(缓存) → auth/getuserinfo(code) → userid
     → user/get(userid) → 部门/姓名/邮箱/手机（失败 → 降级 + WARNING）
     → 探测部门是否已同步 → 组装 LoginSyncRequest(source=wecom)
     → LoginSyncService.execute(..., bootstrap_first_user_admin=True)
     → AuthJwt.set_access_token(token, httponly=False)  # Set-Cookie
     → 302 return_to
        ↓
[platform / client] 携带 cookie 调 /api/v1/user/info → 已登录
```

错误路径统一 302 到 `{return_to_origin}{basepath}/?wecom_error=<code>`，前端读 `wecom_error` 用 `api_errors:<code>` 文案展示（AC-18）。

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| `GET /api/v1/user/wecom/availability` | `{enabled: bool, mode: "qr"\|"silent"\|null, login_path: str\|null}` | 前端判断是否渲染入口；`login_path` 由前端拼 `return_to`（浏览器侧才知道当前地址） | platform 登录页 |
| `GET /api/v1/user/wecom/authorize` | query: `return_to`（绝对 URL，同源或白名单）、可选 `mode`（qr/silent 覆盖 UA 判定） | 302 到企微 | platform 登录页 |
| `GET /api/v1/user/wecom/callback` | query: `code`、`state` | 302 回 `return_to`，`Set-Cookie: access_token_cookie` | 浏览器 |
| Redis `wecom_sso:state:{state}` | JSON `{"mode","return_to"}`，TTL 300s | 一次性，GETDEL | callback |
| `access_token_cookie` | JWT（`LoginUser.create_access_token`） | 与密码登录同一枚 cookie 名 | 后端中间件 / WS / 两个 SPA |
| `?wecom_error=` | 5 位错误码 | 登录页展示失败原因 | platform 登录页 |
| `source` | 固定 `"wecom"` | 用户/部门归属来源 | LoginSyncService、权限投影 |
| `external_user_id` | 企微 userid（原样，只做 trim） | 与组织同步写入的 external_id 一致 | Department/User 绑定 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `sso_sync/api/endpoints/wecom_login.py` | 三个 GET 入口；302、cookie 写入、错误码→跳转 | 不写业务规则、不碰 ORM |
| `sso_sync/domain/services/wecom_login_service.py` | availability / authorize / callback 编排；state、return_to 校验、降级判定 | 不直接调企微 HTTP、不写 ORM |
| `sso_sync/domain/services/wecom_oauth_client.py` | 企微 OAuth 与成员接口；token 缓存（复用 `org_sync:wecom:token:{config_id}`）；errcode → 19334 | 不读数据库、不建用户 |
| `sso_sync/domain/services/wecom_login_state.py` | state 存取（原子 GETDEL / Lua 后退方案） | 不持有业务数据 |
| `sso_sync/domain/services/login_sync_service.py` | 复用；新增 `bootstrap_first_user_admin` 开关 | 不感知 OAuth |
| `org_sync/domain/models/org_sync.py` | 只读企微配置（DAO 已有列表/详情方法，按需补一个"唯一启用配置"查询） | 不新增字段 |
| `frontend/platform/src/pages/LoginPage/` | 入口按钮 + 错误提示 + `ws_token` 镜像 | 不直连 HTTP（走 `controllers/API`） |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | **登录 payload 绝不能带 `account_disabled=False`**：`LoginSyncService` 见到该字段会把 `delete=1` 的用户重新启用（`login_sync_service.py:355-371`）。 | 管理员在平台停用的账号，只要本人再从企微登录一次就被复活，等于绕过封禁（违反 AC-12）。 | `wecom_login_service` 组装 payload 时不设置该字段 |
| 2 | **`assert_parent_chain_exists` 抛 19312 不能当"部门没同步"用 try/except 吞掉。** 它同时覆盖并发删除、数据不一致等真实故障。 | 真正的数据损坏会被静默降级为"访客部门"，且日志里看不出区别。 | 先只读探测部门，再决定是否带上部门字段（决策 5） |
| 3 | **`sso_sync.initial_password` 会给首登用户一个共享初始密码**，登录时该密码若未改会被 10601 拒绝并要求改密。 | 企微用户首登后被莫名要求改一个自己不知道的密码。 | design 记录：企微登录后该用户已有会话，**不应**再触发改密拦截；实现时确认首次登录路径不受 `_ensure_initial_password` 的 10601 分支影响（10601 在密码登录路径触发，不在 login-sync 路径）。 |
| 4 | **平台 JS 也会写同名 cookie**：密码登录成功后 `userContext.tsx:104` 用 `document.cookie` 写 `access_token_cookie`。 | 若 SSO 下发的 cookie 是 HttpOnly，JS 无法用同名覆盖，切换账号后可能带着上一个账号的令牌。 | 决策 2 显式 `httponly=False`，并保证 `/user/logout` 服务端清除 |
| 5 | **`/api/v1/user/wecom/*` 必须加入免登录白名单**（`utils/http_middleware.py` 的公开路径集合，参考 `/api/v1/user/login`）。 | 未登录请求会被中间件 401，根本进不了 callback。 | 同一处登记三个路径 |
| 6 | **企微内 UA 判定**：企微内置浏览器 UA 含 `wxwork`（大小写不敏感）。 | 在企微里给用户弹扫码页，体验割裂。 | availability/authorize 的 mode 判定 |
| 7 | **GETDEL 需 Redis ≥ 6.2**；本项目 Redis 版本需确认，若低于 6.2 退化为 `GET`+`DEL` 两步（用 Lua 保证原子）。 | 低版本上 GETDEL 报未知命令，登录全挂。 | `wecom_login_state` 实现处 |
| 8 | **`LoginSyncRequest.ts` 是必填字段**（源系统时间戳，LOGIN-T12 用）。登录本身没有上游版本号。 | 漏传直接 Pydantic ValidationError → 500，且报错只说 `ts Field required`，看不出是登录链路。 | `wecom_login_service._build_payload` 统一填 `int(time.time())` |
| 9 | **LoginSyncService 的拒绝是 `HTTPException`，不是 `BaseErrorCode`**（`UserForbiddenError.http_exception()`、`SsoUserLockBusyError.http_exception()`）。 | 只 catch `BaseErrorCode` 时，停用账号/并发登录会以 JSON 500 返回，浏览器停在回调地址（违反 AC-18）。 | `wecom_login` 端点同时 catch `HTTPException`，把 `status_code` 转成 `?wecom_error=` |

> ⚠️ 坑 3 需在实现后按 §7 手工验证一次：新建的企微用户从企微登录 → 进入平台后不被要求改密；用「初始密码」从密码登录 → 被 10601 要求改密。

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /api/v1/user/wecom/availability` | HTTP API（免登录） | platform 登录页 |
| `GET /api/v1/user/wecom/authorize` | HTTP 302（免登录） | platform 登录页 |
| `GET /api/v1/user/wecom/callback` | HTTP 302 + Set-Cookie（免登录） | 浏览器 |
| 错误码 19330–19334 | `common/errcode/sso_sync.py` + 三语 copy | 前端 `api_errors` |
| `LoginSyncService.execute(bootstrap_first_user_admin=...)` | 内部 Python API（默认 False） | 本 feature；网关链路不受影响 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `LoginSyncService.execute` | 内部 Python API | 它改了用户 upsert / 部门 / 租户语义，本 feature 跟着变（INV-47 要求一致，这是期望行为） |
| `org_sync_config`（provider=wecom） | 数据库只读 | 组织同步改加密格式/字段名 → 登录读不出凭据 |
| 企微 `auth/getuserinfo` + `user/get` | 外部 HTTP | 应用可见范围不足 → 只返回 openid；通讯录权限不足 → user/get 失败（降级） |
| `access_token_cookie` 及 `cookie_conf` | 共享鉴权契约 | 改名会影响密码登录/WS/网关 |
| 平台 `LOGIN_PATHNAME` 跨应用回跳 | localStorage 契约 | 两端必须同时改（client `loginRedirect.ts` 注释已声明） |

---

## 7. 测试与可观测

- **单元测试**（`src/backend/test/sso/`，均已实现并通过）：
  - `test_wecom_login_state.py`：state 写入/一次性消费/过期；Redis 不可用时 fail-closed。
  - `test_wecom_oauth_client.py`：gettoken 缓存命中、errcode 40029 → 19333、`openid`-only → 19334、通讯录错误降级 / 凭据错误上抛。
  - `test_wecom_login_service.py`：唯一配置判定、`bisheng_pro` 关闭入口、UA→mode、return_to 白名单、部门探测降级、payload 不含 `account_disabled`、callback 透传 `bootstrap_first_user_admin`。
  - `test_wecom_login_api.py`：三个端点；callback 的 `Set-Cookie`（含非 HttpOnly）与 302 目标；`BaseErrorCode` 与 `HTTPException` 两条失败路径都回到 `?wecom_error=`。
  - `test_wecom_first_user_bootstrap.py`：首登超管的 Redis 一次性守卫（空库/已有用户/并发/Redis 故障）。
- **回归**：`test/sso/` 既有用例（LoginSyncService 加默认参数不得改变行为）、`test/api/test_route_path_naming.py`（新路径不含 `config`）。
- **手工验证（真实企微租户）**：
  1. 在企微管理后台把自建应用可见范围覆盖测试成员，配置组织同步并执行一次同步；
  2. PC 浏览器打开 platform → 点「企业微信登录」→ 扫码 → 回到首页且 `/api/v1/user/info` 返回本人；
  3. 企微内置浏览器打开同一地址 → 不弹扫码，直接进入；
  4. 停用组织同步配置 → 入口消失，直接访问 authorize 返回 19330；
  5. 检查 `audit_log`（登录动作）与 `org_sync_log`（`sso_realtime`）各一条。
- **可观测**：WARNING 日志 `wecom sso dept fallback`（含 userid、缺失部门 id）；登录审计走既有 `AuditLogService.user_login`。

---

## 8. 后续改进 / 不打算做的事

- 多企微企业并存（需要"默认配置"指针）——本期 fail-closed。
- 单点退出（企微侧或 IdP 全局登出）——本期不做。
- 将 `ws_token` 从组件中移除并全面 HttpOnly —— 属于会话模型重构，另起 feature。
- 登录限流（同一 IP 短时间大量 authorize）——本期依赖 state TTL 与企微侧风控。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-16 | 初版（含 spec 评审 8 条发现的处理） | feature 启动 |
| 2026-11-16 | §4.2 availability 契约改为 `login_path`；§5 增坑 8（`ts` 必填）、坑 9（HTTPException vs BaseErrorCode）；§7 记录已实现测试 | 实现期发现（偏差记录见 tasks.md） |
