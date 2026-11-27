# Token Exchange 接入

适用：A/B均已注册毕昇OAuth客户端，B信任毕昇签名；同一自然人、同一租户。A必须为confidential服务端，浏览器/插件不能保存client_secret。新增接口不使用户自动获得B业务角色。

## 配置一次

1. 管理员通过既有 /api/v1/oauth2/clients 注册A/B；A的grant_types显式包含 authorization_code、refresh_token、urn:ietf:params:oauth:grant-type:token-exchange，默认不会开启第三项。客户端密钥仍只签发时展示。
2. 平台全局管理员PUT /api/v1/oauth2/exchange-policies/{A_CLIENT_ID}/{B_CLIENT_ID}，使用毕昇浏览器身份认证，JSON：

```json
{"enabled": true, "allowed_scopes": ["openid", "profile"]}
```

可通过GET同一集合路径分页查看（page/page_size/source_client_id）。停用用PUT enabled=false，不删除策略。租户管理员和普通用户没有该管理权。

## 每次登录

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

新增oauth2_exchange_policy、oauth2_exchange_session整表，标准API启动或Helm初始化的alembic upgrade head自动创建；已有三张OAuth表不改，无默认策略/数据回填。直接uvicorn部署需先跑同一正式升级。回滚代码时保留两新表即可，不需恢复数据库或删除用户数据。

错误：invalid_client(401)、unauthorized_client/invalid_target/invalid_scope/invalid_grant/invalid_request(400)、temporarily_unavailable(503)。public响应no-store；管理接口沿用平台HTTP200+status_code业务信封，不能只看HTTP成功判断管理操作成功。
