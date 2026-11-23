# DSH 设备闲置会话 — 实施设计

关联：[spec.md](./spec.md) · [最终方案](../refresh-reliability-plan.md)。用户已确认需求与设计方向，授权服务端实施。遵循 constitution C1–C8，沿用现有认证与业务权限检查。

## 决策

1. 复用 SQL 设备会话，新增 expiry_policy、last_activity_at、idle_ttl_seconds，expires_at 是唯一有效截止时间。历史默认 ABSOLUTE_V1，新登录 SLIDING_IDLE_V1。每次活动使用行中固化期限，默认 14 天。
2. Session Service 在租户上下文中复查身份；Repository 锁定同一会话，复查归属、版本、状态和截止时间后更新会话与 ACTIVE refresh。后台认证和换证不调用活动记录。活动组件保存失败沿用会话服务错误，不进入业务执行，也不把暂时存储故障当作会话撤销。
3. 保留确定性 refresh，不扩大为任意祖先恢复。滑动模式不再把历史 token.expires_at 当作会话绝对上限；USED 恢复仍检查首次 used_at、窗口和直接后继。
4. 撤销只写 session.state，所有 access/refresh 先检查会话，避免长期会话逐行重写历史。ACTIVE 查询增加 tenant/session/state 索引；不提前删除有效会话的 USED 摘要。
5. core/session_activity.py 提供纯基础设施协议 AuthenticatedActivity 与业务入口装饰器 business_activity。装饰器只写服务端函数元数据，不包装签名，不读取业务响应。只有身份认证边界能在 HTTP/WS state 绑定 DshSessionActivity；普通 Web 无设备能力，不更新其他设备。
6. 原生 desktop_principal 校验凭据后绑定并调用通用入口；内嵌 Cookie 的 validate_web_session 只校验并绑定，LoginUser.get_login_user 完成认证后统一调用入口。LoginUser 不携带续期回调。模型、工具、计费和后台任务不读取设备 sessions 来续期。
7. HTTP 标记工作台聊天、Linsight 提交/启动/继续/人工输入、原生模型和工具调用；权限/配额拒绝及上游失败仍算活动。请求级标记防止同请求多次认证依赖重复写入，不按流分片写库。
8. WS 连接认证只绑定能力，ChatManager 在分发 input/init_data 前触发，并在业务权限检查前记录；check_status、stop、连接和心跳不记录。业务消息仍由原业务逻辑校验和执行。
9. Work MCP 包装 SDK 的 CallToolRequest 分发处理器，在完成 Host/Origin 和 RPC 解析后、SDK 工具 schema 校验及业务权限检查前统一触发 tools/call 活动；initialize、list、ping、GET SSE 均不触发。传输上下文通过有 finally reset 的 ContextVar 传递，不放入共享模型缓存或任务消息。

## 决策与模块边界

采用认证后统一入口，而不是对所有鉴权请求保活或依赖业务成功：前者会把轮询计为使用，后者把登录生命周期耦合到权限/配额，且曾使普通 Chat 的 settings-only 运行时因没有 sessions 而在真实调用前失败。core 不导入任何领域模块；dsh/application/session_activity.py 作为设备会话适配器复用原 Session Service/Repository。只有入口声明决定是否记录，模型工厂只组装模型、积分和审计。若以后要区分前台真人与自主客户端调用，必须重新评审客户端协议，不能从现有请求头推断。

| 模块 | 职责 |
| --- | --- |
| core/session_activity.py | 入口元数据、认证能力接口、统一触发、HTTP 请求内去重 |
| dsh/application/session_activity.py | 精确设备 principal 到现有 Session Service 的适配 |
| dsh/api/dependencies.py、user/domain/services/auth.py | 原生和内嵌 HTTP 认证后统一入口 |
| common/chat/manager.py | WS 消息入口，排除维护性 action |
| dsh/work_mcp.py | 已认证 MCP tools/call 分发入口和作用域清理 |
| 各 API endpoint 的 business_activity 标记 | 声明业务入口，不决定权限或配额 |

## 已知坑

- 仅 mock get_model_runtime 的用例无法发现组装依赖遗漏；普通 Chat 与原生 HTTP 回归必须保留真实工厂，模拟数据库、Redis 和供应商边界。
- 共享运行时不能持有某请求的设备或续期回调，否则会串用用户/设备。设备能力只放在认证后的连接 state，后台执行不继承该能力。
- MCP POST 同时承载维护和业务 RPC，不能按所有 POST 续期，也不能提前消费 ASGI 请求体；在 SDK CallToolRequest 分发入口触发；保留原 schema 校验和错误结果，不关闭校验。
- 无效/过期/撤销会话不能续期。已认证的业务拒绝可以续期；二者不可按 HTTP 是否成功混为一类。

## 配置与发布

session_idle_ttl_seconds 默认 1209600，允许 600–2592000 秒；session_ttl_seconds 维持旧绝对模式语义。session_idle_migrate_existing 默认 false；打开后仅对仍有效历史会话的业务活动转换。已过期不复活，部署时间不回填 last_activity_at。

迁移 dsh_idle_sessions 接在真实单 head merge_f114_dsh_refresh 后；仅 DDL，保留降级字段。跨副本必须一致切换。旧配置文件不新增默认启用的新键，防止不支持的旧镜像拒绝启动。

## 旧客户端

保持所有已有请求响应字段和别名。1.2.0 已解析每次 token 响应的动态到期字段；启动 restore 会尝试同步/刷新。部分入口缓存到期拦截是待实际安装包验证的边界，不修改桌面代码，也不以后台刷新保活绕开兼容问题。

## 已知边界

SQLite 不验证数据库行锁；MySQL/DM8 与实际 Electron 需要单独验收。长期活跃可积累历史 token 行，应监控规模。跨代迟到祖先仍可能触发撤销；账号/租户停用、凭据泄漏不受闲置期限保证。旧服务端回退需预演，不能通过删除证据或更换主密钥回退。

## 修订历史

- 2026-11-11：按用户确认将业务准入后回调改为认证后的统一入口；修复普通 Chat 共享工厂的 sessions 强依赖。
