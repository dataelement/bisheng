# BiSheng Desktop 第一方会话与 Token Exchange

BiSheng Web、App、Desktop 分别使用 `bisheng-web`、`bisheng-mobile`、`bisheng-desktop`。三者复用统一平台会话有效期、刷新轮换、身份/租户绑定及在线撤销校验。Desktop 为原生客户端，凭据以 JSON 返回，后续使用 Bearer，不借用浏览器 Cookie。

## Desktop 客户端接入

1. 登录改用 `POST /api/v1/auth/login`，JSON 包含既有用户名、密码和必要验证码，并传 `client_id: "bisheng-desktop"`，可附 `device_label`、`client_version`。安全保存响应 `data` 内的 Access Token 和 Refresh Token。该入口是密码登录；现有浏览器 SSO/PKCE 登录不能只改 client_id 就自动切换。
2. 使用统一平台 Access Token 请求 `POST /api/v1/oauth2/token`，参数示例如下。可使用表单；不要发送浏览器 Cookie，也不要将目标应用 Token 当作平台登录 Token。

```text
grant_type=urn:ietf:params:oauth:grant-type:token-exchange
subject_token_type=urn:bisheng:params:oauth:token-type:platform-session
subject_token=<Desktop平台Access Token>
audience=xpie
scope=openid profile email
```

3. 读取 OAuth 原生响应中的 `access_token`、`expires_in`、`token_type`；用换得的 Token 调用目标应用。目标 Token 到期后重新换证；换证不会返回 Refresh Token。
4. 平台 Access Token 到期时调用 `POST /api/v1/auth/refresh`，JSON 为 `{"refresh_token":"..."}`。将返回的新凭据一起保存，避免并发刷新。
5. 退出登录调用 `POST /api/v1/auth/logout`，通过 Bearer 提交平台 Access Token，或单独用 JSON 提交 Refresh Token；不要混用。父会话撤销后，依赖它的换证 Token 在在线校验时失效。

## xpie 配置与用户授权

目标 `xpie` 必须启用，且 `grant_types` 包含 `urn:ietf:params:oauth:grant-type:token-exchange`。Scope 必须属于目标允许范围与 `openid/profile/email` 的交集。第一方来源不需要跨 OAuth 客户端的两两 exchange policy；`require_consent=true` 时仍须先通过正常授权页面取得该用户、租户及目标注册对应的同意，缺少同意会返回 `consent_required`，客户端应引导正常授权，不能自动批准。

## 兼容边界

旧 `/api/v1/dsh/*` 登录协议及既有内置 OAuth `dsh-desktop` 注册保留兼容，不改写数据库标识，不把旧 DSH Token 冒充统一平台 Token。`bisheng-desktop` 是新增的统一第一方会话标识；切换客户端后需要重新登录。只部署服务端不会自动升级既有 Desktop 客户端。这里的名称统一针对第一方认证标识和默认显示名称，既有 API 路径和软件包命名保持兼容。

本次代码修改不包含 Desktop 应用本身的发布，也不自动调整线上 xpie 注册。
