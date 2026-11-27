# Token Exchange 接入

两条路径均保持同一自然人、同一租户，由B信任毕昇签名：第一方正式会话可直接换B；第三方OAuth A→B则继续要求confidential A及配对策略。浏览器/插件不能保存client_secret，交换不自动赋予B业务角色。

## 第一方会话直接换证（新增）

已登录BiSheng网页或手机时，不需要先取得A的OAuth Token，也不需要配对策略。管理员登记B后，仅需让B的grant_types包含 urn:ietf:params:oauth:grant-type:token-exchange；受信任应用设置require_consent=false即可静默换证。B为public或confidential均可，第一方调用者不携带B的client_secret。

POST /api/v1/oauth2/token，表单字段：

- grant_type=urn:ietf:params:oauth:grant-type:token-exchange
- subject_token_type=urn:bisheng:params:oauth:token-type:platform-session
- audience=B_CLIENT_ID
- scope=openid profile

原生第一方SDK以Bearer或body subject_token携带自己正式平台Access Token；网页由第一方同源请求携带选定HttpOnly平台Cookie、Origin与X-CSRF-Token，省略body subject_token。第一方会话Token不能交给第三方B；B只收到新B Token。本分支拒绝Basic、client_id/client_secret及用户/租户覆盖字段，不允许拿旧网页/DSH/Refresh或bootstrap票据替代平台会话。

B.require_consent=true时，须已有本人、本租户、该B登记实例和全部scope的显式同意；否则HTTP400 consent_required。调用方先走现有authorize+PKCE/consent页面，批准后再次换证即可；不会自动弹新审批流程，也不会凭已登录就静默增加同意。用户可用同一第一方身份DELETE /api/v1/oauth2/consent/grants/{B_CLIENT_ID}撤销自己的同意，Cookie须Origin/CSRF，响应为平台业务信封。

输出及B的验签方式同下文。额外签名标记exchange_source=platform_session用于在线父链分派。B撤销不影响平台登录，平台退出后B在线UserInfo拒绝，B自建会话仍由B管理。

## OAuth A→B：配置一次

1. 管理员通过既有 /api/v1/oauth2/clients 注册A/B；A的grant_types显式包含 authorization_code、refresh_token、urn:ietf:params:oauth:grant-type:token-exchange，默认不会开启第三项。客户端密钥仍只签发时展示。
2. 平台全局管理员PUT /api/v1/oauth2/exchange-policies/{A_CLIENT_ID}/{B_CLIENT_ID}，使用毕昇浏览器身份认证，JSON：

```json
{"enabled": true, "allowed_scopes": ["openid", "profile"]}
```

可通过GET同一集合路径分页查看（page/page_size/source_client_id）。停用用PUT enabled=false，不删除策略。租户管理员和普通用户没有该管理权。

## OAuth A→B：每次登录

A先按正常授权码+PKCE流程取得该用户的毕昇Access Token。A后端POST /api/v1/oauth2/token，Content-Type为application/x-www-form-urlencoded，使用HTTP Basic认证(A_CLIENT_ID,A_CLIENT_SECRET)。请求字段：

- grant_type=urn:ietf:params:oauth:grant-type:token-exchange
- subject_token=A用户Access Token
- subject_token_type=urn:ietf:params:oauth:token-type:access_token
- audience=B_CLIENT_ID
- scope=openid profile（显式指定）

可选requested_token_type只支持access_token URN。Basic方式不要再在body重复放client_id/client_secret。拒绝actor_token、resource、多个audience、重复字段及用户/租户覆盖字段。不要在URL、日志或共享终端中输出密钥/Token。

成功返回access_token、issued_token_type、token_type=Bearer、expires_in、scope、session_id。不包含id_token或refresh_token。最长300秒且不超过原Token/会话寿命，处理耗时也计入期限。

## B如何接收

B后端配置固定issuer和自身B_CLIENT_ID，通过issuer的OIDC Discovery获取JWKS（不要信任Token提供的jku或任意公钥）。检查：ES256签名、iss、严格aud=B、exp/iat、token_use=access、token_exchange=true、sub/tenant_id。稳定身份键使用(iss,sub,tenant_id)，需要姓名/邮箱时用Bearer调用/userinfo（受profile/email scope约束）。B建立自己的登录会话，业务角色由B判定，不复制A的管理员权限。

参考接收端验签及拒绝错误aud的可执行例子在 src/backend/test/e2e/test_e2e_token_exchange_local.py 的真实HTTP测试中；该测试完整执行A登录→换B→JWKS验证→UserInfo→撤销父A后B在线拒绝。运行方式见 [验证报告](./verification.md)。

## 撤销与升级

B撤销其Token使用 /api/v1/oauth2/revoke；B为confidential时按B客户端认证。撤销B只影响B会话；撤销A使B的在线UserInfo失败。B仅本地验签时最多接受300秒残余有效期；B已经建立的本地登录会话不因此自动注销，B自行设计其寿命/登出。

四张新独立表为oauth2_exchange_policy、oauth2_exchange_session、oauth2_platform_exchange_session、oauth2_user_consent；标准alembic upgrade head自动发现创建，原三张OAuth表不改、无默认策略/数据回填。第一方路径另依赖alpha1完整F003平台会话能力，不能只给旧SSO镜像增加几份exchange文件。新待授权请求/code绑定登记实例，升级时旧的未完成申请/code须重发，已登录会话/refresh不因此失效。已签发平台会话后，回滚地板应保留F003验证/刷新/撤销能力，不能直接回到不认识平台凭证的旧SSO镜像。

错误：invalid_client(401)、unauthorized_client/invalid_target/invalid_scope/invalid_grant/invalid_request(400)、consent_required(400)、temporarily_unavailable(503)。public响应no-store；管理接口沿用平台HTTP200+status_code业务信封，不能只看HTTP成功判断管理操作成功。
