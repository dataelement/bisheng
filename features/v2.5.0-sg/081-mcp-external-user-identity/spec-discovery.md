# F081：MCP 指定业务账号身份

- Feature ID: `081-mcp-external-user-identity`
- Status: `DISCOVERY_CONFIRMED`
- Created: `2026-10-22`
- 阶段：用户于 2026-10-22 确认“按这份范围进入完整规格设计”；发现范围已确认，完整规格待确认，尚未修改鉴权代码。
- 前置：[F070](../070-mcp-server/spec.md)、[F078](../078-mcp-knowledge-tools/spec.md)、[版本契约](../release-contract.md)。本特性经确认后覆盖 F070/F078 中 MCP 禁止业务账号身份切换的原约定，不改变原 REST 行为。

## 1. 目标与已明确选择

用户希望十个 MCP 工具都增加指定账号参数，Token 负责接入校验，指定账号决定业务权限。

| 问题 | 用户选择 |
|---|---|
| 账号字段 | `external_id`，与登录账号一致，字符串精确匹配 |
| 允许跨租户 | 允许以目标用户身份切换到其所属租户，不受 Token 绑定用户的资源权限限制 |
| 账号可信来源 | 可信业务后端先验证真实登录用户，再传入对应账号 |
| 多租户选择 | 沿用用户唯一当前归属租户；无法唯一确定有效当前租户时拒绝 |
| 单租户模式 | 使用默认租户，不新增 `tenant_id` 参数 |

本轮澄清结果为 `READY_FOR_PLAN`，发现范围已获用户确认。本文件保留确认依据，不代表已经实现；当前完整规格见 [spec.md](spec.md)。

## 2. 现有事实与调用边界

| 文件/组件 | 当前行为 | 本次涉及 |
|---|---|---|
| `bisheng/mcp_server/domain/services/auth_service.py` | 每 HTTP 请求调用开发者 Token 校验；实际工具任务恢复 Token 租户上下文 | 保留入口校验，区分接入身份与目标业务身份 |
| `bisheng/developer_token/domain/services/developer_token_service.py` | 校验 Token、归属/绑定有效性、IP、路由、限流，返回 principal | 保留这些有效性检查；不拿其绑定用户授权 MCP 业务资源；不改变 REST Token 语义 |
| `bisheng/mcp_server/domain/services/tool_runtime.py` | 九个新工具的 factory 使用 `principal.user` | 改为解析后的目标账号及目标租户 |
| `bisheng/mcp_server/domain/services/search_service.py`、`api/endpoints/tools.py` | 原 `search_knowledge` 通过独立链路使用 Token 用户 | 同样纳入目标身份，不能遗漏原工具 |
| `bisheng/mcp_server/domain/services/factory.py` | 每调用组装知识 Owner、Repository、入口解析及检索服务 | 保持请求专属装配，传入目标用户 |
| `bisheng/user/domain/models/user.py` | 登录账号仅匹配 `external_id`；唯一约束是 `source + external_id` | 跨来源可能重名；必须检查全部有效候选，不能任选第一条 |
| `bisheng/user/domain/repositories/implementations/user_repository_impl.py` | 已有按 external_id 查询全部有效用户的方法 | 复用仓储边界；需要的新查询必须留在 Repository，不能新增 DAO 或 Service SQL |
| `bisheng/database/models/tenant.py` | `is_active=1` 标记唯一当前归属租户；保留历史关系 | 多租户模式校验唯一当前关系及租户启用状态，不按历史/默认记录猜选 |
| `bisheng/open_endpoints/domain/services/filelib_user_context_service.py` | REST 已有 external_id 代理，但使用默认租户且代理作用域内保留跨租户 bypass | 不直接照搬到 MCP，也不修改其已有 REST 行为 |

项目已有正常登录身份构造 `UserPayload.init_login_user`，可按目标用户加载角色与管理员身份；具体装配、仓储及异常类型在完整设计中确定。

## 3. 需求边界

### 包含

1. 所有十个已注册工具新增必填字符串 `external_id`，包括旧 `search_knowledge` 和两个写工具。
2. `initialize`、`tools/list` 继续只做 Token 入口校验，不要求尚未发起工具调用的业务账号。
3. 每次工具调用先通过 Token 校验，再解析指定有效账号；缺失、空值、未找到、禁用或多候选时拒绝，不回退 Token 绑定用户。
4. 账号保持字符串身份，保留前导零，不转数字、不模糊匹配、不回退到 `external_code` 或 `user_name`。
5. 多租户开启时，只选择目标用户唯一有效当前归属关系及启用租户；缺失、冲突、失效时拒绝，不补建关系或自动回退其他租户。单租户模式使用默认租户。
6. 业务权限由目标用户的现有角色、组、部门与资源授权决定。接入 Token 的绑定用户只保留校验与审计意义，其权限不与目标用户取交集，也不向目标用户额外授予权限。
7. 跨租户表示按目标用户切换业务作用域，不能把整个工具执行放入全局 bypass。文件归属、目录/上传、预览/下载及 canonical 约束继续由现有领域 Owner 校验。
8. 创建文档、上传文件的操作者、归属、授权、配额和异步任务租户均按目标身份进入既有业务流程，不新增 Owner 绕过路径。
9. 每次调用独立建立/恢复目标上下文；并发、异常和取消后恢复，禁止后续调用继承其他账号/租户。客户端传入的 `external_id` 由统一入口消费，不直接成为领域服务未声明参数。
10. 审计区分接入 Token ID/归属身份与执行用户 ID/执行租户；不输出 Token 明文或用户候选详情。
11. 同步工具 schema、规格、使用文档与受影响测试，保留 folder_id 字符串兼容、Token 空白名单语义及当前跨域策略。

### 不包含

- 改造 Token 管理界面/表结构，取消 Token 归属记录或迁移真实 Token。
- 修改现有 REST 的 external_id 代理行为，或自动将 REST 替换成新身份策略。
- 自动注册用户、修正账号关系、同步主部门/租户、创建个人库等身份解析副作用。
- 新增 `tenant_id` / `user_id` / `source` 等身份选择参数、账号模糊匹配、跨来源首条匹配。
- 新增 OAuth、用户密码验证或可信后端登录系统。MCP 不将账号字符串视为本人身份证明。
- 自动部署、修改真实权限或执行远程写入验证。

## 4. 验收标准与验证方向

| ID | 可观察结果 | 验证方向 |
|---|---|---|
| AC-01 | 十工具 schema 均声明必填 external_id；缺失不会回退 Token 用户 | 真实 SDK tools/list、tools/call 参数拒绝 |
| AC-02 | Token 无效、禁用、归属失效、IP/非空路由/限流拒绝时不进入业务账号解析或资源操作 | Token / MCP HTTP 回归 |
| AC-03 | 唯一有效账号解析成功；空值、禁用、不存在、跨来源重复均安全拒绝 | 身份服务参数化测试与真实仓储最小集成 |
| AC-04 | Token 用户无目标资源权限、目标用户有权时成功；目标用户无权时即使 Token 用户有权也拒绝 | 知识权限受控集成与两个检索链路验证 |
| AC-05 | Token 属于租户 A、目标用户当前归属 B 时，业务按 B 执行；无有效/唯一当前租户时拒绝 | 身份/租户服务及真实 ORM 查询 |
| AC-06 | 单租户模式使用默认租户；不读取历史关系猜选或执行身份同步写入 | 多/单租户模式等价案例与无副作用断言 |
| AC-07 | 原检索、新九工具、预览与两写工具均使用目标身份；写入操作者/归属/任务租户保持一致 | SDK 连续流程及既有上传服务边界测试 |
| AC-08 | 并发不同账号/租户，含异常及断连取消，调用彼此隔离且上下文/会话释放 | SDK/HTTP 并发与取消测试 |
| AC-09 | 审计可区分 Token 与实际执行用户，无 Token 明文、账号候选或无权正文/链接泄漏 | 安全日志与拒绝路径断言 |
| AC-10 | 原 REST、folder_id 兼容、Token 路由/IP/限流、MCP CORS 等既有契约不变 | 相关回归；真实基础设施未执行项单独记录 |

验收按独立业务结果分组复用证据，不按十个工具重复同义单测；真实数据库/权限/存储/队列或 DM8 未执行时不得用替身结果宣称通过。

## 5. 风险、兼容性与回退

- **授权能力变化**：有权访问 MCP 的 Token 持有方可代理任意能唯一解析的有效账号，包括具有管理权限的账号。可信业务后端必须保护 Token，并从已认证登录身份导出 external_id，不能直接信任终端或模型自行提交的账号。MCP 不证明该字符串属于当前真人。
- **跨租户变化**：Token 的租户不再限定目标业务租户；业务始终使用目标用户的正常隔离与资源授权。只在必要的账号/租户解析查询中临时跨范围读取，结束后恢复，禁止将其延续到业务。
- **调用兼容性**：工具调用新增必填参数是接口变化；现有不传账号的 MCP 客户端需升级并刷新工具清单。缺参拒绝是预期行为，不提供隐藏兼容回退。
- **写入影响**：创建者、Owner、配额、授权与任务租户将随目标用户变化，必须覆盖真实领域调用边界；仅在受控测试中验证，不直接使用正式业务数据。
- **可逆性**：本特性不需要数据迁移；可回退本次应用代码恢复 Token 用户执行方式。已通过新方式创建的业务文件不会因代码回退而被删除或改回归属。

## 6. 下一阶段

发现阶段已获用户确认，进入完整 `spec.md` / requirements / design 及规格评审。按仓库 [AGENTS.md](../../../AGENTS.md) §6，完整规格确认后再拆 tasks、测试先行实施和端到端验证；当前未修改鉴权、工具定义、Token 或业务数据。

后续状态：完整规格已获用户确认并完成本地实施；本文件保留发现阶段事实，最新结果见 [verification.md](verification.md)。
