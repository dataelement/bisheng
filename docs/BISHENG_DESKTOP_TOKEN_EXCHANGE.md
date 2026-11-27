# BiSheng Desktop 第一方会话与 Token Exchange

BiSheng Web、App、Desktop 分别使用 `bisheng-web`、`bisheng-mobile`、`bisheng-desktop`。三者复用统一平台会话有效期、刷新轮换、身份/租户绑定及在线撤销校验。Desktop 为原生客户端，凭据以 JSON 返回，后续使用 Bearer，不借用浏览器 Cookie。

## Desktop 客户端接入

1. 保留现有浏览器登录：`POST /api/v1/dsh/authorizations`（兼容交接标识仍为 `dsh-desktop`）→浏览器登录/授权→回调 Desktop→`POST /api/v1/dsh/token`，提交 `identity_ticket`、`auth_id`、`code_verifier`。服务端在一次性票据与 PKCE 校验完成后签发 `client_id=bisheng-desktop` 的统一平台会话，以原 DSH JSON 顶层结构返回 Access/Refresh Token 和用户/租户显示字段。无需改成密码输入或第三方 OIDC 登录。统一 `/api/v1/auth/login` 接口也继续保留。
2. 使用统一平台 Access Token 请求 `POST /api/v1/oauth2/token`，参数示例如下。可使用表单；不要发送浏览器 Cookie，也不要将目标应用 Token 当作平台登录 Token。

```text
grant_type=urn:ietf:params:oauth:grant-type:token-exchange
subject_token_type=urn:bisheng:params:oauth:token-type:platform-session
subject_token=<Desktop平台Access Token>
audience=xpie
scope=openid profile email
```

3. 读取 OAuth 原生响应中的 `access_token`、`expires_in`、`token_type`；用换得的 Token 调用目标应用。目标 Token 到期后重新换证；换证不会返回 Refresh Token。
4. 原 `POST /api/v1/dsh/token` 的 `grant_type=refresh_token` 分支支持新平台 Refresh Token，并保留旧 DSH Refresh Token 的精确归属分派。也可调用统一 `POST /api/v1/auth/refresh`（JSON `{"refresh_token":"..."}`，响应包在 `data` 内）。将返回的新凭据一起保存，避免并发刷新。
5. 原 `POST /api/v1/dsh/logout` 支持新平台凭据，也可调用统一 `/api/v1/auth/logout`。通过 Bearer 提交平台 Access Token，或单独用 JSON 提交 Refresh Token；不要混用。父会话撤销后，依赖它的换证 Token 在在线校验时失效。

## xpie 配置与用户授权

目标 `xpie` 必须是已启用的非内置应用；第一方平台会话换证不要求目标额外开启 Token Exchange Grant Type。第三方 OAuth 来源的换证授权规则保持不变。Scope 必须属于目标允许范围与 `openid/profile/email` 的交集。第一方来源不需要跨 OAuth 客户端的两两 exchange policy；`require_consent=true` 时仍须先通过正常授权页面取得该用户、租户及目标注册对应的同意，缺少同意会返回 `consent_required`，客户端应引导正常授权，不能自动批准。

## 兼容边界

旧 `/api/v1/dsh/*` 登录协议及既有内置 OAuth `dsh-desktop` 注册保留兼容，不改写数据库标识，不把旧 DSH Token 冒充统一平台 Token。`bisheng-desktop` 是统一第一方会话标识；重新走一次原浏览器授权登录即可获取新会话。已存在的旧 DSH 会话不会被自动转换；客户端若严格校验旧 Token 的 typ/aud 或固定响应字段，需要适配统一平台 Token 结构，不能继续假设旧 DSH 专属 Token。这里的名称统一针对第一方认证标识和默认显示名称，既有 API 路径和软件包命名保持兼容。

本次代码修改不包含 Desktop 应用本身的发布，也不自动调整线上 xpie 注册。
