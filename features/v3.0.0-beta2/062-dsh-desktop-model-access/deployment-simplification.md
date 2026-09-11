# DSH 部署配置简化（客户端契约 0.4.0）

2026-09-09，按用户确认实施。本修订替代旧文档中重复密钥、独立 Redis 和模型部署白名单的设计。

## 单一配置来源

| 内容 | 当前来源 | 取消的重复配置 |
|---|---|---|
| 毕昇与 Gateway 共享 Secret | 毕昇 sso_sync.gateway_hmac_secret；Gateway bisheng.gateway-hmac-secret | DSH 双向 key ID/secret、Token 签名私钥和验签公钥、issuer 配置 |
| 毕昇 Redis | 已解密的应用 settings.redis_url | dsh.quota_redis_url |
| 用户可用模型和逐模型月额度 | DSH 管理界面；候选模型复用原模型管理及租户共享规则 | dsh.verified_model_capabilities |
| 月度边界 | Asia/Shanghai，北京时间每月 1 日零点 | 默认 UTC |
| 对外地址 | dsh.platform_public_url 与 Gateway dsh.public-origin，等于客户端填写的 Nginx origin | 不与客户端 loopback 回调混淆 |

## 身份协议

> 2026-09-11 实现修订（未部署）：删除安装标识；以下派生方式由双方同步切换，详细要求见 [解绑修订](./installation-unbinding-revision.md)。公开客户端 contract_version 保持 0.5.0。

现有用户同步 HMAC 协议不变。DSH 由同一共享 Secret 通过 HKDF-SHA256 派生用途密钥，不增加运维配置：salt=UTF-8("bisheng-dsh-v1")，info=UTF-8(purpose)，输出 32 字节；purpose 分别为 bisheng-to-gateway-v1、gateway-to-bisheng-v1、dsh-access-v1。服务请求继续使用时间窗和共享 nonce 防重放，其 HMAC secret 为派生结果的小写 hex UTF-8；Token 直接使用 32 字节派生结果签名。

DSH access token 固定 HS256、typ=bisheng-dsh-access+jwt、kid=dsh-access-v1、iss=bisheng-dsh、aud=bisheng-dsh-model，最长 600 秒。验签之后仍在线检查真实用户、租户、席位和会话。普通 JWT/PAT/SAK 不成为 DSH 凭证。客户端不获得共享 Secret，也不本地验签；将 token 视为不透明凭证。

Ticket 保持随机、短期、Redis 原子一次性消费和 PKCE/授权事务绑定，Gateway 通过 HMAC 认证的内部接口兑换。无需为 ticket 新增签名格式。/api/dsh/jwks 为旧接线保留空 keys 响应，任何密钥都不通过该接口发布。License 发行和验证继续独立，不以共享 HMAC 生成 License。

## 模型与用量

候选模型来自原 LLMService 模型目录，每次校验合法租户、共享授权、模型启用和类型。用户每模型配置只在管理界面维护；部署文件不登记模型 ID。流、tools 和参数支持由现有供应商适配实现确定，不保证任意供应商支持所有参数；不支持时按协议返回错误。缺少 usage 正常保留响应和 USAGE_UNKNOWN 明细，不冻结用户。

## 共享 Redis 的运行边界

不改其他业务的连接池、全局淘汰策略或持久化配置。DSH 使用相同应用连接配置创建受控连接，当前覆盖单实例与 Sentinel，Cluster 未实现，不能宣称兼容。复用后不要求单独配置 AOF/noeviction；仍通过外部恢复审批绑定 Redis run_id/epoch 和已核对的 evicted_keys。连接/主身份改变或发生新的淘汰必须停止 DSH 新准入，不能把丢失账本当零用量。该保护不等于缺失 usage 的用户冻结。

共享模式按服务器已有 maxmemory 判断余量，不将其他业务占用算入原 DSH 512 MiB 上限；未设置全局上限时保留 DSH Stream 积压数量/时间保护和异步清理，不擅自设置全局上限。既有受控恢复审批对象仍需配置，此次取消的是重复 Redis 地址，不是丢账恢复校验。

## 2026-09-09 历史切换记录（非本次升版要求）

config.contract_version 升为 0.4.0；HTTP 路径、调用顺序、ticket 兑换和正常 JSON/SSE 形状不变。旧 RS256 access token 失效，应重新登录；已有席位和逐模型额度记录保留。共享 Secret 轮换同时影响用户同步与 DSH，应协调两端同步更新。客户端契约已更新在本地，未向客户端团队发送消息。

部署目标为 192.168.106.109。毕昇通过 feat/3.0.0-beta2-pre 推送构建；Gateway 通过带 -dsh- 的 v 前缀联调 tag 构建，跳过旧流水线对 115 的自动部署。最终构建 SHA、镜像 digest、运行版本和实测结果另行记录，不将本设计说明视为部署完成证明。

## 2026-09-10：HTTP 部署支持

按用户确认，平台公开地址、Gateway 内部地址及 Gateway 的 Python 地址允许 HTTP 或 HTTPS origin；不额外引入协议开关。109 独立联调入口统一为 `http://192.168.106.109:13001`，取消 3443、HTTPS 跳转及客户端 CA 要求。服务内部直接使用 Compose DNS `http://gateway:8080` / `http://backend:7860`。原 HMAC、防重放、PKCE、一次性票据和精确 Origin 校验保持不变；HTTP 登录 Cookie 沿用原 `secure=false` 配置。客户端同步放开 BASE / 唤起 server 参数的 HTTP 校验，接口形状及调用时序不变。
