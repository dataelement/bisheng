# F084：需求与验证追溯

- Status: `IMPLEMENTED_LOCAL`
- Created: `2026-11-02`

| Requirement | 行为 | Acceptance | Verification |
|---|---|---|---|
| REQ-001 | 移除十工具 external_id 参数，未知字段拒绝且无业务副作用 | AC-01 | V-SDK：真实 SDK schema、合法/非法调用 |
| REQ-002 | Token principal 决定用户、角色、租户及全部读写身份，无账号/当前租户查询 | AC-02 | V-IDENTITY：身份服务/工厂；V-FLOW：SDK + SQLite 写入回查与拒绝 |
| REQ-003 | 保持接入校验、上下文恢复、并发/取消及绑定身份审计 | AC-03 | V-REGRESSION：MCP HTTP/SDK、Developer Token 相关回归 |
| REQ-004 | 保持 REST 代理及其他资源/内容/上传业务契约 | AC-04 | V-REGRESSION：Filelib 外部账号、知识 MCP、folder_id 和来源回归 |
| REQ-005 | 更新使用文档、SDK 示例和当前规格状态 | AC-05 | V-DOC：示例 JSON/Python 语法及引用检查 |

本地 SDK/SQLite/受控外部端口不代表真实 MySQL/DM8、OpenFGA/MinIO/Milvus/ES 或线上验收。实际命令与结果在 verification.md 记录。
