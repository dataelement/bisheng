# DSH Desktop 客户端：安装标识解绑兼容说明

日期：2026-09-11；公开协议版本：**0.5.0（保持不变）**；文档修订：安装标识解绑。
状态：已核对本地客户端实际代码；服务端改造与真实环境联调尚未执行。本文件可交付客户端开发和联调，不代表已向客户端团队发送。

## 结论

本次服务端删除 installation_id、取消 License 环境匹配，**不新增或删除桌面客户端所需的公开字段，不要求客户端改代码**。License 的 schema=2 是服务端发行格式，与 `/api/v1/dsh/config` 的 contract_version 无关；服务端不得因此返回 0.6.0 并导致现有客户端版本检查拦截。

客户端继续只配置毕昇 Nginx 地址，例如 `http://192.168.106.109:13001`；不配置安装标识、机器指纹、License、Gateway 地址或 HMAC 密钥。

代码核对依据（2026-09-11 本地工作区，不声称已验证所有历史客户端二进制）：

- `dsh-desktop/packages/dsh-desktop-enterprise/contract.js` 的 API_PATHS 列出以下 7 个公开接口；parseConfig 当前接受 0.4.0/0.5.0。
- 同文件 parseAuthorization 读取 auth_id、authorize_url、expires_in；parseToken 将 access_token 和 refresh_token 作为不透明字符串，只读取外层会话/用户/租户字段，不解析 JWT claims。
- `packages/dsh-desktop-enterprise/index.js` 的 exchangeTicket 发送 identity_ticket、auth_id、code_verifier；回调校验 auth_id、state 与 identity_ticket/error，均不依赖安装标识。
- 客户端包中未发现 installation_id/installationId 的引用。主契约对 Token 的不透明要求继续有效。

## 公开接口对照

完整字段、错误码与时序仍以 [client-api.md](./client-api.md) 的 0.5.0 契约为准。

| 接口 | 本次变化 | 客户端何时调用 |
|---|---|---|
| GET `/api/v1/dsh/config` | 无；enabled=true 时仍为 client_id=dsh-desktop、contract_version=0.5.0 | 配置地址后、开始登录前检查功能可用性 |
| POST `/api/dsh/authorizations` | 无 | 启动本地回调监听、生成 state 和 PKCE 后，创建登录事务并打开 authorize_url |
| POST `/api/dsh/token` | 无；两种 grant_type 与响应字段保持 | 收到或粘贴当前事务 ticket 后兑换；access 临近到期或明确失效时按原规则单次串行刷新 |
| POST `/api/dsh/logout` | 无；仍返回 204 | 主动登出，按原 access/refresh 规则撤销当前会话 |
| GET `/api/v1/dsh/models` | 无 | 登录成功、启动恢复或刷新账号模型时读取授权模型 |
| POST `/api/v1/dsh/chat/completions` | 无；JSON/SSE/工具调用/缓存 Token 明细保持 | 用户提交模型调用时；不因本次改造增加自动重放 |
| GET `/api/v1/dsh/usage` | 无；逐模型月额度及北京时间边界保持 | 账号页、模型调用结束后、手动刷新用量时 |

浏览器 `/desktop-login?auth_id=...`、网页授权/拒绝接口、loopback 回调与手动复制 ticket 流程不变。唤起地址及 server 参数也不因本次 License 修订变化。

Token 内部 issuer、claims 和派生密钥改变只由 Gateway 和毕昇处理；客户端仍使用 `Authorization: Bearer <access_token>`。不得解析或校验安装标识，也不得将 License 指纹作为登录参数。

## 切换期间的兼容行为

本次测试版服务端统一切换会清退旧凭证和未完成登录事务，**用户需要重新登录一次**，但不丢失已分配席位、模型授权、额度或历史用量。之后单纯更换 License、Pod 或节点不再触发这次凭证清退行为。

1. 服务端升级暂停期间返回现有不可用错误时，客户端按既有错误处理展示；不要循环刷新或重放模型调用。
2. 恢复后，旧 access token 按现有 `invalid_access_token` 返回；客户端按原逻辑尝试刷新。旧 refresh 缺失时仍返回现有 `invalid_refresh_token`；已撤销会话按现有撤销错误处理。客户端 refreshAccess 的失败分支会暂停模型并清理本地会话，用户重新发起登录，不为本次新增错误码。
3. 用户点击“在浏览器中登录”，重新创建 state、PKCE、auth_id，再获取新 ticket。旧浏览器页或复制的旧 ticket 不重用。
4. 新登录按原 token→models/usage→模型调用流程继续。客户端不需区分服务端安装标识版本，也不需修改已保存的毕昇地址。

## 联调检查清单（待执行）

- [ ] 当前客户端无需更新即可接受服务端 config=0.5.0。
- [ ] 新建授权、网页确认、自动回调与手动 ticket 兑换均成功。
- [ ] 升级前保存的旧会话能按既有错误流程回到重新登录，不无限刷新。
- [ ] 新会话刷新、模型列表展示、非流/流式调用、缓存 Token 明细和逐模型用量正常。
- [ ] 原已分配用户重新登录没有新增占席；多个 Gateway 副本共用同一席位池。
- [ ] 同一 License 在两个独立环境均可使用；客户端仍按各自毕昇地址建立会话。

服务端若在实施中发现必须改变上述公开路径、字段、状态码或时序，应先同步本文并取得用户确认，不能只修改代码或提升 contract_version。
