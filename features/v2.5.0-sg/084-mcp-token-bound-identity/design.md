# F084：Token 绑定身份回退设计

- Status: `IMPLEMENTED_LOCAL`
- Created: `2026-11-02`

## D-01 参数契约（REQ-001）

mcp_server/domain/schemas/identity.py 保留 StrictRequest、无账号字段的公共工具请求基类和执行身份 DTO；移除 ExternalAccount。api/endpoints/{tools,query_tools,content_tools,write_tools}.py 的函数签名及 DTO 构造不接收 external_id。响应和嵌套 FolderScope 不变；旧 search_knowledge 继续原业务范围。

## D-02 执行身份（REQ-002/003）

user_context_service.py 改为从认证 principal 构造不可变执行身份，仅使用已有 principal.user/tenant_id，不查账号、当前关系或默认租户。拒绝用户/租户不一致的内部 principal，不重载角色，不提升管理员身份。factory.resolve_execution_identity 改为仅接收 principal 的异步适配，去除独立身份 DB session 和 user/tenant Repository 装配；保留受管理业务 session。

runtime 和旧 search service 只传 principal 给身份适配，不从工具参数决定身份。保持 McpAuthService.use_identity 六个 ContextVar 的隔离和 finally 恢复，保留原双身份日志字段，此时执行用户/租户与 Token 绑定身份一致；SDK 参数拒绝的执行身份仍可为空。只读 30 秒/写 120 秒及检索运行时预算不放大，不新增身份数据查询。

## D-03 文件计划和边界（REQ-004/005）

允许修改 mcp_server 的 identity/schema、user_context_service、factory、tool_runtime、search_service 和相关测试装配；Router 仅内部身份回调签名随一参数适配保持。test/mcp_server 下将 F081 代理专属测试改为 Token 绑定身份、schema 拒绝和写入回查；保留并发/取消、Token、大小限制、folder_id 和预览断言。更新 docs/api/mcp-usage.md 及 F081 当前入口的被替代说明。

不改变 DeveloperTokenService、共享 Repository、REST、细粒度权限、队列或存储实现；不删除共享身份查询仓储。无表/迁移/依赖/配置，MySQL/DM8 查询逻辑保持。权限风险先写新拒绝/绑定身份测试，再实现；全部相关回归和受控端到端验证后记录证据与自审。
