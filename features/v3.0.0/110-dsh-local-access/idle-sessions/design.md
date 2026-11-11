# DSH 设备闲置会话 — 实施设计

关联：[spec.md](./spec.md) · [最终方案](../refresh-reliability-plan.md)。用户已确认需求与设计方向，授权服务端实施。遵循 constitution C1–C8，沿用现有认证与业务权限检查。

## 决策

1. 复用 SQL 设备会话，新增 expiry_policy、last_activity_at、idle_ttl_seconds，expires_at 是唯一有效截止时间。历史默认 ABSOLUTE_V1，新登录 SLIDING_IDLE_V1。每次活动使用行中固化期限，默认 14 天。
2. Session Service 在租户上下文中复查身份；Repository 锁定同一会话，复查归属、版本、状态和截止时间后更新会话与 ACTIVE refresh。后台认证和换证不调用活动记录。若记录失败，不进入模型或工具外部执行。
3. 保留确定性 refresh，不扩大为任意祖先恢复。滑动模式不再把历史 token.expires_at 当作会话绝对上限；USED 恢复仍检查首次 used_at、窗口和直接后继。
4. 撤销只写 session.state，所有 access/refresh 先检查会话，避免长期会话逐行重写历史。ACTIVE 查询增加 tenant/session/state 索引；不提前删除有效会话的 USED 摘要。
5. DSH model 在额度准入后记录活动，失败时以已知零用量释放准入。工具在参数/权限和 lease 准入后记录，失败释放 lease。目录/发现均不记录。
6. 验证 DSH Web cookie 时在 HTTP/WebSocket state 中附加绑定精确 principal 的私有回调；LoginUser 私有属性传递回调，业务明确调用。普通浏览器无回调；模型输入、请求头和客户端版本不能指定会话。
7. 内嵌工作区覆盖工作台聊天、任务提交/继续/人工输入、Work MCP 工具执行、应用聊天和实际工作流执行/输入；工作流 check_status 等轮询不计。只在业务准入后调用，不按任意 WebSocket 消息保活。

## 配置与发布

session_idle_ttl_seconds 默认 1209600，允许 600–2592000 秒；session_ttl_seconds 维持旧绝对模式语义。session_idle_migrate_existing 默认 false；打开后仅对仍有效历史会话的业务活动转换。已过期不复活，部署时间不回填 last_activity_at。

迁移 dsh_idle_sessions 接在真实单 head merge_f114_dsh_refresh 后；仅 DDL，保留降级字段。跨副本必须一致切换。旧配置文件不新增默认启用的新键，防止不支持的旧镜像拒绝启动。

## 旧客户端

保持所有已有请求响应字段和别名。1.2.0 已解析每次 token 响应的动态到期字段；启动 restore 会尝试同步/刷新。部分入口缓存到期拦截是待实际安装包验证的边界，不修改桌面代码，也不以后台刷新保活绕开兼容问题。

## 已知边界

SQLite 不验证数据库行锁；MySQL/DM8 与实际 Electron 需要单独验收。长期活跃可积累历史 token 行，应监控规模。跨代迟到祖先仍可能触发撤销；账号/租户停用、凭据泄漏不受闲置期限保证。旧服务端回退需预演，不能通过删除证据或更换主密钥回退。
