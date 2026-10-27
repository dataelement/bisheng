# MCP Server 工具面（已合并）

2026-10-10 起，平台只有一个 MCP 服务：`POST /api/v2/mcp`，由 F067 统一远程 MCP 服务（`bisheng/open_mcp/`）提供。
F052 原有的身份/组织工具与应用工具已并入该服务，工具名不变。

- 对外契约见 [`src/backend/docs/api/open-mcp.md`](../../src/backend/docs/api/open-mcp.md)，其中「应用工场工具」一节列出了从 F052 并入的 9 个工具。
- F052 的 `bisheng_knowledge_search` 由 F067 的 `bisheng_knowledge_retrieve` 取代，两者走同一个统一检索门面。
- F052 的 `bisheng_model_list` 已移除，查询模型名请调用 `GET /api/v2/model/v1/models`。
