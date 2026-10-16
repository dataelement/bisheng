# MCP 知识空间工具：规格自审

- Feature ID: `078-mcp-knowledge-tools`
- Reviewed: `2026-10-16`
- Mode: `spec`
- Status: `REVIEWED_USER_CONFIRMED`
- 范围：本目录 discovery、spec、requirements、design；不包含实现审查。

## 规格检查结论

LGTM

按项目 [.claude/skills/sdd-review/SKILL.md](../../../.claude/skills/sdd-review/SKILL.md) 的 spec 模式及其 14 项清单自审；未使用独立 agent，不把自审表述为独立评审。

| 检查 | 结论 | 依据 |
|---|---|---|
| 1. 截图功能覆盖 | PASS | 九工具均有输入、结果和验收；旧工具保留 |
| 2. 边界和失败 | PASS | 权限、目录越界、超限、重复、版本变化、断连和投递不确定状态 |
| 3. UI 场景 | N/A | 本期无 UI；现有 Token 管理流程不变 |
| 4. AC 格式与编号 | PASS | spec 为唯一 AC-01～18 的角色/操作/预期结果表 |
| 5. AC 可观察性 | PASS | requirements 提供六组验证目标，每个 AC 均有方法 |
| 6. 版本不变量 | PASS | 继承双版本契约；调用 Owner，维持租户、权限、配额、canonical 和下载策略 |
| 7. 技术覆盖 | PASS | design 的十二条 REQ 追溯与文件计划、批次、验证策略对应 |
| 8. 领域所有权 | PASS | 不新增领域事实对象；原知识、权限、存储及任务 Owner 不变 |
| 9. API 契约 | PASS | 十名称兼容关系、九工具参数结果、请求及输出例子、协议/错误映射明确 |
| 10. 分层及包装 | PASS | endpoint → domain service → repository；MCP 延续 F070 原生协议包装，REST 不变 |
| 11. 文档职责 | PASS | spec 定义行为和对外契约；具体装配和测试策略分列 design |
| 12. ORM 与租户 | N/A | 无新表或迁移；既有自动上下文与过滤保持 |
| 13. 错误码 | PASS | 业务错误复用既有 109xx / 180xx / 198xx / 配额错误，传输校验不另造业务表 |
| 14. 统一授权 | PASS | 统一权限入口与现有细粒度业务权限；不读取旧 role_access 授权，不把权限 ID 当 FGA relation |

## 审查时校正的设计

- 不将旧 `search_knowledge` 强制收窄到空间，以免破坏原调用；新 `retrieve_chunks` 单独校验空间范围后共享核心。
- 不包装会按规则改目标、切换责任人、同名清理覆盖的 `file/sync`；不把 legacy 的默认操作人带入 MCP。
- 不将只检查 `view_file` 的原件链接接口当成新下载授权依据；新工具继续受下载、水印和分发政策限制。
- 不将带超时状态写入的 legacy 文件列表方法当作纯只读查询。
- 正文候选 helper 的 10000 桶上限不满足完整分页；设计补充可继续候选读取和预算耗尽的明确结果。
- 不在无权限的原始候选上计算总量或分页后再删除目录；不沿用后台失效入口的展示例外。
- 用户要求增大限制后，规格同步为文件 50 MiB、文本 10 MiB、请求体 80 MiB；保留既有更严格上传规则，并补齐 Base64/JSON 膨胀及边界验证计划。此调整未修改代码、运行设置或验收状态。

架构参考文档中旧 role_access、DAO 或鉴权描述与当前 P0 规则冲突时，以 AGENTS.md、版本契约及当前源码为准。

## 证据边界与用户确认

规格评审阶段只进行了静态评审，行为 AC 当时为 `NOT_RUN`。用户整体确认后，已连续实施和运行本地测试，最终证据、六个存量失败对照及真实环境边界见 [verification.md](verification.md)。本文件保留规格评审记录，不作为生产验收证明。

依照项目 `AGENTS.md §6`：`spec.md → /sdd-review <dir> spec → ★ user confirms`。
规格评审后的确认范围包括已有 `/mcp` Token 新增的写入能力、传输上限、默认冲突拒绝和原件来源边界。整体确认后已创建和评审 tasks.md，按 `sdd-implement` 完成本地实现；回退代码不删除已创建文件。

2026-10-16 用户确认：“确认，按调整后的限制开始实施图片中的九个 MCP 工具。”上述确认点已通过，进入任务评审和实现。
