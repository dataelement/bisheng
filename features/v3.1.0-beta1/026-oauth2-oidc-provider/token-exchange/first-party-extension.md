# 第一方会话换证：已确认增量规格与设计

用户在2026-11-27明确接受：第一方可信会话＋B启用换证→静默签发；不增加第一方→B配对授权/审批；尊重B.require_consent。之后明确要求开发完成后部署115，代替此前“不部署”约束；不自动合并PR。

## 增量验收

- **AC-18**：WHEN 持有有效BiSheng正式web/mobile会话、目标B存在/启用且grant_types包含标准token-exchange，THE SYSTEM SHALL 静默签发B身份Token，无需登记第一方OAuth客户端或维护第一方→B策略。未启用/内置DSH目标拒绝。
- **AC-19**：WHEN B.require_consent=false，THE SYSTEM SHALL 不增加交互同意；WHEN 为true且缺少本人、本租户、该登记实例、全部请求scope的显式同意，THE SYSTEM SHALL 返回consent_required。正常consent页批准后可再静默换证；拒绝、自动批准、旧会话不推导用户同意。
- **AC-20**：WHEN 原第一方会话撤销/版本变化/到期、用户或成员资格失效，THE SYSTEM SHALL 拒绝新换证及派生Token在线查询；撤销B不影响原会话。B本地验签仍最多300秒残余，B自己的登录会话自行管理。
- **AC-21**：WHEN 交换或查询，THE SYSTEM SHALL 固定本人和原租户，仅openid/profile/email，输出ES256、aud=B，截止不超过原Access、原Session、请求开始+B TTL、请求开始+300秒，处理耗时计入，无refresh/id_token。
- **AC-22**：WHEN 来源伪造/类型不匹配、bootstrap未绑定、旧网页/DSH/refresh、Cookie/Bearer/body矛盾、Cookie缺Origin/CSRF，THE SYSTEM SHALL 拒绝。不得把第一方Token交给第三方或写入JWT/存储/日志；B只收到自己的Token。
- **AC-23**：WHEN 应用删除重建、撤销用户同意或收窄配置，THE SYSTEM SHALL 不继承旧应用登记的待授权请求/授权码/同意/派生Token。用户可撤销自己的同意，租户隔离；旧OAuth A→B路径继续适用AC01–17和配对策略。

## 接口和数据流

复用POST /api/v1/oauth2/token；grant_type保持RFC8693 URN；subject_token_type显式为urn:bisheng:params:oauth:token-type:platform-session，audience=B、scope显式身份scope，可选requested_token_type只能access_token URN。

原生第一方以body subject_token或Bearer提供正式Access Token，重合凭据须相同；网页省略subject_token，使用选定HttpOnly平台Cookie及Origin/X-CSRF-Token。该分支拒绝client_id/client_secret/Basic，来源由签名会话确定。此扩展Token Type的Cookie选择语义是BiSheng约定，不宣称Cookie形式可供任意标准RFC8693客户端直接使用。

用户域application/oauth_exchange接缝调用正式get_platform_auth/inspect/decode；不自行按OAuth ES256解码平台HS256。F026只接收闭合的已验证subject及无密credential_reference，通过注入用户域validate_reference做在线复核。旧fixed access_token_cookie残留不作为主体，也不遮蔽有效的新会话。用户/租户仍由权威身份lookup复核。

B opt-in复用既有grant_types，不增加新开关、配对表或seed。B.require_consent缺授权时返回HTTP400 consent_required（28119），由调用方进入既有OAuth authorize+PKCE/consent流程；确认后可再次调用换证，不凭空跳过consent。DELETE /api/v1/oauth2/consent/grants/{client_id}撤销当前第一方用户/租户的同意，Cookie同样校验CSRF；使用平台业务信封。

## 存储与生命周期

新增独立oauth2_platform_exchange_session保存B session_id、source_client_id、无密父引用、target_client_id/registration_id、user/tenant、issuer及expires；新增oauth2_user_consent按client_registration_id+user_id+tenant_id记录已批准scope。不存Token、密钥、CSRF。现有5张OAuth表不改；标准alembic upgrade head自动发现整表创建，无数据回填。

AuthService在明确consent approve且require_consent=true时调用recorder；自动批准不写同意。待授权request与授权码都包含client_registration_id，展示/批准/兑换检查当前登记；部署前尚未完成、缺该字段的短期请求/授权码失效，需要重新发起，不是既有登录或refresh失效。新B不继承同client_id旧登记的用户同意。

B session与父link同一事务，失败回滚；发出前重查父引用与期限。在线UserInfo按签名exchange_source=platform_session分派，验证child/link/issuer/aud/user/tenant/目标登记及当前scope/consent，再由用户域检查父引用。缺link或未知source fail closed。旧OAuth父链不改成平台父链。

## 审查与验证状态

Constitution：领域无FastAPI/跨域SQL；用户域application seam隔离所有平台会话校验；新表用共享JsonType/时间类型支持双库；身份引用按user/tenant约束，raw凭据不持久化。独立安全审查发现旧待批页跨登记consent问题，已用registration绑定修复并加pending/code/existing consent回归。实际测试、审查及115部署结果见verification.md/code-review.md，未执行项不得据此声明通过。
