# F081：规格自审记录

- Feature ID: `081-mcp-external-user-identity`
- Reviewed: `2026-10-22`
- Mode: `spec`
- Status: `REVIEWED_USER_CONFIRMED`
- 范围：[发现范围](spec-discovery.md)、[spec.md](spec.md)、[requirements.md](requirements.md)、[design.md](design.md)；不包含实现或生产验收。

## 规格检查结论

LGTM

按项目 [.claude/skills/sdd-review/SKILL.md](../../../.claude/skills/sdd-review/SKILL.md) 的 spec 模式及十四项清单执行静态自审，未使用独立评审 agent。当前没有阻塞完整规格确认的问题；该结论不代表实现已经符合规格。

| 检查 | 结论 | 依据 |
|---|---|---|
| 1. 用户范围覆盖 | PASS | 已确认发现范围及十二 REQ 覆盖十工具、目标账号、跨租户、可信后端与读写归属；十条 AC 对应 |
| 2. 边界及失败 | PASS | 严格账号、跨来源重复、无效当前关系/租户、配置/角色异常、超时/取消、并发隔离均明确 |
| 3. UI 交互 | N/A | 不新增 UI、Token 管理或可信后端登录系统 |
| 4. AC 格式 | PASS | spec 使用角色/操作/预期结果表，AC-01～10 唯一 |
| 5. AC 可验证性 | PASS | requirements 映射七个验证组，区分 SDK、仓储、目标权限、端到端和真实设施边界 |
| 6. 版本不变量 | PASS | 继承双版本契约的自动租户过滤、统一授权、创建补偿、配额和队列身份；仅明确覆盖 F070/F078 原 Token 用户执行约定 |
| 7. 技术覆盖 | PASS | D-01～06 对应参数注册、账号/租户仓储、目标上下文、两条 runtime、审计及文件范围 |
| 8. 领域所有权 | PASS | user/tenant 仓储读取身份；知识、权限、上传、存储和队列 Owner 不变，不新增领域事实或旁路写入 |
| 9. API 契约 | PASS | 保留 MCP 原生协议，明确 HTTP/参数/工具失败边界、十名称、请求及响应例子；只有工具调用新增必填账号 |
| 10. 架构规范 | PASS | Endpoint → Service → Repository；新查询无 DAO/Service SQL；沿用 MCP 原生响应，不改 REST 注入和包装 |
| 11. 文档职责 | PASS | spec 定义行为、兼容、决策和错误契约；装配步骤、文件计划及验证批次在 design，requirements 提供追溯 |
| 12. ORM 及租户 | N/A | 无新表、字段或迁移；新增只读 Repository，业务查询继续由已有上下文自动过滤 |
| 13. 错误码 | PASS | 保留既有 198xx HTTP 错误及领域错误；身份拒绝复用历史通用 UnAuthorizedError，不分配冲突的新数字 |
| 14. 统一资源授权 | PASS | 真实目标 UserPayload 注入现有 Owner/PermissionService；不直接查询 role_access 或复制 Token 权限 |

架构资料和清单中的旧 DAO、JWT/REST 包装描述与当前仓库 P0 或既有 MCP 协议不一致时，以 [AGENTS.md](../../../AGENTS.md)、版本契约和已读取源码为准；不将本特性扩展为旧架构迁移。

## 自审中明确的约束

- `StrictRequest` 同时被响应和嵌套 FolderScope 使用，故保留无身份基类；只让十个顶层工具请求继承 McpIdentityRequest，避免响应或目录筛选也被迫传账号。
- SQL 排序规则可能返回大小写/尾空格近似候选，须精确字符串复核后判断用户唯一性；当前租户关系也必须先数全部当前候选，再校验状态。
- 不照搬 REST 代理持续保留 bypass 的执行作用域；身份只读 session 关闭后，实际 SDK task 建立目标租户上下文，再装配业务 session。
- 旧检索和新九工具必须共用身份语义；旧检索身份阶段额外上限 30 秒，新九工具身份阶段纳入原总预算，不能遗漏审计或取消清理。
- Token 绑定用户/租户有效性检查仍保留，但其资源权限不再决定目标账号业务；包括管理员账号的代理能力及跨租户行为已写入升级风险。
- 固定账号/租户拒绝提示，执行身份失败时审计目标字段为空；不能用 Token 用户填充、回退或把基础设施异常解释为无权限/无结果。

## 门禁与证据边界

本阶段只执行 V0 文档检查：文件/引用、JSON 示例、REQ/AC/设计追溯、空白及改动范围。所有新增行为验证为 `NOT_RUN`，真实数据库、DM8、权限/存储/队列和可信后端身份绑定需实施后另行记录。

项目 [AGENTS.md §6](../../../AGENTS.md) 要求 `spec.md → /sdd-review <dir> spec → ★ user confirms`，且 `★ pause points cannot be skipped.`；项目规格评审 Skill 要求“等待用户确认”。发现范围确认已通过，规格评审时本次完整规格待确认；其后用户已确认并授权 tasks、任务评审和实施（记录见下）。本轮无代码提交、推送或部署。

2026-10-22 用户确认：“确认，按这份完整规格拆解任务并开始实施。”本确认点已通过；本文件保留规格自审记录，实施证据另见 verification.md。
