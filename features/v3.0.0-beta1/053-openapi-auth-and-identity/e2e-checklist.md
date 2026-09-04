# E2E 验证清单：F053 开放 API 鉴权与身份传递

**自动化入口**：`F053_E2E=1 ... pytest test/e2e/test_e2e_f053_openapi_auth_identity.py -v`

**专用环境前置条件**：完成三条 F053 迁移；OpenFGA 已发布包含 `service_account` 的兼容模型；部署级 PAT 和 guest access 已开启；准备同租户普通用户、已发布工作流、已发布知识助手及至少一个可用模型。

## Platform：服务账号与 API 密钥

- [ ] 以全局超管或当前租户管理员登录 Platform，进入“系统管理 → 服务账号”。
- [ ] 创建名称以 `e2e-f053-openapi-` 开头的服务账号并选择同租户自然人作为资源归属人；刷新后名称、归属人和状态保持一致。
- [ ] 确认数据库未为该服务账号新增 `user` 或 `user_tenant` 行。
- [ ] 签发 API 密钥，仅出现“基本信息、权限位、委托配置”三组；无网络、IP、配额、限流或分享配置。
- [ ] 勾选 `delegate` 但不填 `user:<id>` / `department:<id>` 时不能提交；输入非法格式时显示错误。
- [ ] 密钥明文只显示一次；未勾选“已安全保存”时弹窗不能关闭，刷新后只能看到掩码。
- [ ] 去掉 `delegate` 并保存，重新打开后委托范围为空。
- [ ] 在资源授权页指定资源，新增授权的主体固定为 `service_account:<id>`；撤销时保护来源与不可编辑回授不可被误删。
- [ ] 停用服务账号后，已有密钥在 5 秒内调用 v2 返回 401；重新启用不会恢复已撤销密钥。
- [ ] 非管理员账号看不到“服务账号”和“个人访问令牌”页签；直接访问 API 也被拒绝。

## Platform：PAT 台账与租户设置

- [ ] 进入“个人访问令牌”，确认列表只有持有人、掩码、权限位、时间、状态和管理员风险提示，没有明文。
- [ ] 部署级开关关闭时租户开关置灰；重新开启部署级开关后可设置租户 `enabled` 与 TTL。
- [ ] 关闭租户开关后，既有 PAT 数据仍在台账中，但 5 秒内无法调用 v2；重新开启且令牌未过期时恢复。
- [ ] 分别执行单 token 吊销和按持有人吊销；刷新列表验证最终状态。
- [ ] 切换到另一租户后看不到原租户台账数据。

## Client：个人访问令牌

- [ ] PAT 开关关闭时个人设置页不显示入口；开启后显示状态和操作入口。
- [ ] 首次获取或重新获取后只显示一次明文，必须确认已保存才能关闭；刷新页面后只显示掩码。
- [ ] 复制安装提示词，确认下载 URL 指向当前实例的 `bisheng-knowledge-search` 技能包，提示使用 `BISHENG_API_KEY`。
- [ ] 删除 PAT 后状态刷新为未获取；旧 token 在 5 秒内返回 401。
- [ ] 管理员持有人获取 PAT 时出现风险提示，过期时间不超过部署级管理员 TTL。

## Client：v3 匿名发布面

- [ ] 使用无痕窗口打开已发布工作流和知识助手 guest 页面，不携带 JWT、API Key 或分享参数。
- [ ] Network 中详情、invoke/stop、history/gen_title 全部使用 `/api/v3/**`，两个 WebSocket 也使用 `/api/v3/**`；不得出现 guest `/api/v2/**`。
- [ ] 页面能够建立新会话、续聊、读取历史并生成标题；工作流等待输入字段对外为 `input`。
- [ ] 猜测另一个资源、租户或来源的 `chat_id` 执行 history/title/stop/续聊，均得到同形 404。
- [ ] guest 请求携带 `X-On-Behalf-Of` 或 `X-End-User` 时被拒绝；`/api/v3/assistant/list` 为真 404。
- [ ] 关闭 guest access 或下线资源后，HTTP 与 WebSocket 均无法继续建立新调用。

## v2 日常会话与身份传递

- [ ] 仅携带具有 `chat:invoke` 的 SAK，依次调用 config、chat/list、chat/info、knowledge/upload、workstation/chat/completions；不需要 JWT。
- [ ] config 只含 `models[]`、`tools[]`；SSE 事件顺序、终态和持久化消息与 v1 日常会话一致。
- [ ] 请求保留 `files`；传 `task_mode`、`use_knowledge_base`、异步意图或其它未知字段时明确 400，不静默降级。
- [ ] 模式 S 的会话按服务账号与 `X-End-User` 隔离；模式 D/PAT 会话归属自然人；跨主体 chat/file 统一 404。
- [ ] SAK 使用合法 `X-On-Behalf-Of` 时权限完全按目标用户计算；SA 有权而目标无权时拒绝，反向场景允许。
- [ ] 旧品牌身份头和裸 `user_id` 明确返回 400 `26019`。

## WebSocket、审计与回归

- [ ] v2 工作流/知识助手 WebSocket 只接受 `Authorization: Bearer <API Key>` header；query key、JWT 和无 key 均以 1008 关闭。
- [ ] 已连接后撤销密钥或停用主体，5 秒内关闭连接；两个不同租户连续执行后 ContextVar 不串。
- [ ] `audit_log` 中管理操作 action 可见；逐调用 action 固定为 `open_api.call`，metadata 有 actor/subject 双归属且无 Authorization、明文密钥、请求体或文件内容。
- [ ] v3 发布示例全部匿名且为 v3；v2 密钥示例全部带 Bearer；既有 ChatLink 创建、打开、撤销流程及参数保持不变。
- [ ] 商业版网关分别验证 v3 HTTP 与 WS 可达，且 v3 不被登录或 API Key 网关拦截。

## 清理

- [ ] 删除本次所有 `e2e-f053-openapi-` 服务账号和临时资源；恢复测试前 PAT/guest 设置。
- [ ] 确认非测试数据、既有分享链接和其它租户数据未变化。
