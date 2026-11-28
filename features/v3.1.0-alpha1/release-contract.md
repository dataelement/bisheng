# Release Contract — v3.1.0-alpha1

归档基线为 `alpha1-ui` 的 `ed1687aee8`，与本地 `origin/feat/3.1.0-alpha1` 引用一致。本文件登记已确认启动的特性。领域归属与业务约束沿用 [v3.1.0-beta2](../v3.1.0-beta2/release-contract.md) 和 [v3.1.0-beta1](../v3.1.0-beta1/release-contract.md) 契约。架构约束见 [constitution.md](../../docs/constitution.md)。

## 领域归属与依赖

| 领域 | 归属 | F001 使用范围 |
| --- | --- | --- |
| 用户身份与个人资料 | 用户域 | 使用本人现有头像更新入口，按用户身份展示头像。 |
| 站内通知 | 消息域 | 在 Client 已授权的通知列表展示发件人头像。 |
| 资源授权与授权主体 | F048 及各资源领域 | 在两端通用资源授权名单和选人时展示已有可见范围内的用户头像。 |
| 网页用户头像展示 | F001 网页用户头像统一 | 统一 Client、Platform、通知与资源权限管理中的默认样式和回退行为。 |

## 跨特性约束

- 同一 BiSheng 用户的网页头像来自该用户的个人资料。历史通知和权限记录继续关联原有主体，读取时展示该主体可见的当前头像。
- 头像展示遵循现有消息接收人、资源授权和主体可见范围。资源授权的判断、变更与权限归属继续由现有权限体系负责。
- 对象访问路径兼容性沿用 v3.1.0-beta1 的 F009 契约。错误码沿用既有领域分配。

## F026：第一方会话向第三方静默换证（用户已确认）

- 第一方正式 Web/App/Desktop 会话（bisheng-web、bisheng-mobile、bisheng-desktop）经用户域权威接缝校验后，可向已启用的非内置 B 静默换证；不要求 B 开启 token-exchange grant，不需要第一方→B配对白名单、人工审批或 OAuth 用户同意。B.require_consent 仅继续作用于原 OAuth 授权流程；旧第三方 OAuth A→B 保留原配对授权。
- 平台会话及其校验/撤销归F003用户域；输出B身份断言、child会话、同意与父引用关联归F026。只通过用户域application seam取得已验证值与无密引用，不跨域读写源Session。
- 输出同用户/租户、仅openid/profile/email、最长300秒并受原Access/Session及B TTL约束，不发refresh/id_token；不授予ApiCredential/API Key/PAT/DSH模型能力，不复制业务角色。B本地验签接受至多300秒撤销残余，B本地会话自行管理。
- 新平台父引用/同意两独立表由模型发现创建，原三张OAuth表不改；request/code绑定registration，旧未完成申请/code须重新发起，同ID新登记不继承旧用户同意。
- 增量规格/设计与证据：[F026第一方扩展](../v3.1.0-beta1/026-oauth2-oidc-provider/token-exchange/first-party-extension.md)。115部署需完整F003与两SPA协同，不能把旧SSO镜像作已签发平台凭证后的回滚地板。

## F003：平台统一认证与会话（开发及单元验证完成，真实集成待执行）

本增量对应 [spec](./003-platform-auth-session/spec.md) 与 [design](./003-platform-auth-session/design.md)。需求基线为 2026-11-27 用户确认的“将 DSH 会话机制平台化”；代码证据基线为 `572d5ecf77`。用户已确认spec S1、design D1以及Session／Refresh默认90天，随后已授权按tasks实施与测试；仅修改bisheng及bisheng-mobile，不改网关和桌面源码，未部署。

| 领域对象 | Owner | 依赖及边界 |
| --- | --- | --- |
| 平台登录 Session、平台 Refresh Token、平台凭证格式与签发 | 用户域／F003（本版本） | 提炼 DSH 轮换机制；不接管账号、部门、租户、角色的业务写入权 |
| Desktop 浏览器授权、旧 DSH Session 与平台会话交接 | DSH 负责票据/PKCE，用户域负责平台会话 | 保留浏览器回调体验；新票据兑换签发 bisheng-desktop 平台会话，旧 DSH 凭据仍走原校验，不自动转换 |
| 第三方 OAuth2 Client、OAuth2 Session 与 OIDC 凭证 | F026 OAuth2／OIDC Provider | 保留其签发、刷新和撤销语义；只适配读取当前网页登录身份的接缝 |
| 网关 HMAC 登录同步与组织同步 | 既有 SSO Sync 领域 | 入参、响应和网关程序不改；身份同步完成后调用 F003 的平台签发应用接口 |

| ID | 跨特性不变量 |
| --- | --- |
| AUTH-INV-01 | 新网页、App、BiSheng Desktop 使用同一种平台 Token 与同一会话核心；客户端标识不授予额外业务权限。 |
| AUTH-INV-02 | 新平台 Access Token 默认 30 天；不得因复用 DSH 而套用其 5 分钟期限或模型专用凭证用途。 |
| AUTH-INV-03 | 普通旧网页 JWT 允许在切换时失效；不得通过轮换全局主密钥破坏旧 DSH 或第三方 OAuth2／OIDC 凭证。 |
| AUTH-INV-04 | 旧 DSH 专用凭证及其短期浏览器桥接按原协议校验；普通旧网页 JWT 的拒绝规则不得覆盖该定向兼容入口。 |
| AUTH-INV-05 | 网关仍由后端签发平台 Token；不得要求网关生成、轮换、持久化新增 Refresh Token。 |
| AUTH-INV-06 | 平台登录与 `/api/v2` PAT／服务账号、公开匿名入口保持边界，不能以平台 Token 替代它们的专属契约。 |

106 用户错误码段继续由用户域拥有；设计暂预留 `10650–10664`（在上述代码基线中检索未占用），实施前必须重新检查代码占用，不新增模块编码。

## 2026-11-28 Desktop 与静默换证增量

用户已确认保留 Desktop 浏览器登录/PKCE/一次性票据交接，新票据兑换改由统一平台会话服务签发；统一密码登录继续保留。第一方换证无需 OAuth 同意，保留身份/租户、目标启用、Scope、TTL 及父会话撤销检查。原 F003/F026 文档中的“Desktop 后续迁移”“目标 grant opt-in”“第一方需既有同意”描述由本增量覆盖，第三方 OAuth 规则不变。接入及兼容边界见 [Desktop 接入说明](../../docs/BISHENG_DESKTOP_TOKEN_EXCHANGE.md)。

115 的 beta2 适配部署已记录实际 `platform_success source=bisheng-desktop target=xpie`；这不是 alpha1 实机验收。本次按用户要求不运行功能测试，移植仅执行静态检查。

## 变更历史

| 日期 | 内容 |
| --- | --- |
| 2026-11-19 | 用户确认网页内部头像统一范围与默认样式，登记 [F001 网页用户头像统一](./001-user-avatar-unification/spec.md)。 |
| 2026-11-19 | 用户确认 12 条正式规格，授权完成设计、开发及验证。 |
| 2026-11-19 | 用户要求将统一头像覆盖到 Client、Platform 其余现有自然人头像位置，补充 AC-13、AC-14。 |
| 2026-11-27 | 登记 F003 文档草案的领域归属与认证边界；仅编写 spec/design，未实现、未部署。 |
| 2026-11-27 | 用户确认规格与设计及90天期限，继续用例与任务文档阶段；实现仍未开始。 |
| 2026-11-27 | F003仅bisheng/mobile开发与单元验证完成；真实集成按用户指示移交，网关及桌面源码不改，未部署。 |
