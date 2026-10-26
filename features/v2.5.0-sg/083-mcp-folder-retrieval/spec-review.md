# F083：完整规格静态评审

- Feature ID: `083-mcp-folder-retrieval`
- Reviewed: `2026-10-26`
- Mode: `spec`
- Status: `REVIEWED_USER_CONFIRMED`
- Reviewed scope: [spec-discovery.md](spec-discovery.md)、[spec.md](spec.md)、[requirements.md](requirements.md)、[design.md](design.md)。

## 评审结论

LGTM

按项目 [.claude/skills/sdd-review/SKILL.md](../../../.claude/skills/sdd-review/SKILL.md) 的 spec 模式及十四项清单执行静态自审，未使用独立评审 agent。没有发现阻塞完整规格确认的问题；该结论仅针对文档完整性、边界和设计，不代表功能实现或真实基础设施已通过验收。

| 检查项 | 结论 | 依据 |
|---|---|---|
| 1. 需求覆盖 | PASS | 单空间单目录、默认递归、false 当前层均有 AC-01/02，新增工具且保留旧工具 |
| 2. 边界与失败 | PASS | 参数拒绝、目录归属/权限、空集、超过单批、恰好 1000/1001、标签交集、严格回映射、异常/取消均明确 |
| 3. UI 交互 | N/A | 不新增 UI 或前端配置 |
| 4. AC 格式 | PASS | spec 使用 ID/角色/操作/预期结果四列，AC-01～07 唯一 |
| 5. AC 可验证性 | PASS | requirements 为全部 AC 提供验证组及主要证据落点，不逐 AC 重复运行同义测试 |
| 6. 版本不变量 | PASS | 继承自动租户过滤、现有权限、存储隔离和 canonical 约束，无全局 bypass 或额外授权 |
| 7. 技术覆盖 | PASS | D-01～05 对应 schema/注册、范围领域服务、内部限域/回映射、装配/错误和文档/验证 |
| 8. Owner 边界 | PASS | knowledge 提供目录/文件事实；权限与存储 Owner 不变，无领域数据写入或迁移 |
| 9. API 契约 | PASS | 定义 MCP endpoint/tool、严格参数、请求/响应例子、既有错误及新增 18007；保持 MCP 原生结果 |
| 10. 分层规范 | PASS | Endpoint → runtime/factory → 领域 Service → Repository，复用现有 scan_files；无 Service SQL、新 DAO 或手写索引条件 |
| 11. 文档职责 | PASS | spec 描述行为、决策和兼容；操作流程、文件计划及测试策略在 design；requirements 提供映射 |
| 12. ORM 与租户字段 | N/A | 无新 ORM/表/字段；资源校验与已有会话上下文继续生效 |
| 13. 错误码 | PASS | 新范围预算错误使用现有 180 模块内未分配的 18007，BaseErrorCode 子类；18040 及 Token 198xx 与当前源码核对 |
| 14. 资源授权入口 | PASS | 复用 knowledge 的细粒度权限及 resolver 最终授权，不直接读取 role_access，不复制 Token 用户权限 |

清单中的旧 DAO/JWT/REST 包装描述与当前仓库 P0 和既有 MCP 协议不一致时，以当前 AGENTS、版本契约和源码为准。项目架构文档仅作背景，不能据其旧描述引入新的权限旁路。

## 本次设计特别约束

- 空文件集合不能转为 None；空目录或标签空交集不执行无范围检索。
- 召回前由 resolver 构造文件约束；仅结果后置筛选不足以满足目录检索。
- 共享回映射默认仅优先显式入口；新模式使用已有 strict_explicit，旧调用保持默认值，不修改通用算法。
- 1000 预算针对权限/标签过滤前的成功文件候选，达到后还需探测下一条，不能无提示截断；它是待用户确认的设计预算，不是已验证吞吐。
- 目录成功候选与最终 canonical 可检索状态分别由各自 Owner 判断，不把投影、元数据或目录查看权当作正文授权。
- 预算拒绝采用专属 18007，不挪用其他业务含义的错误码；当前只是规格分配，尚未修改错误码实现。

## 证据与阶段边界

本次仅执行 V0：文档空白、引用目标、JSON 示例、REQ/AC/设计追溯和改动范围检查。行为验证统一为 NOT_RUN：未修改或执行新增功能测试，未启动服务或访问真实数据库/权限/检索基础设施。

| 证据 | 结果 | 范围 |
|---|---|---|
| Node 只读静态检查 | PASS | 五份文档、18 个本地引用目标、4 个 JSON 示例、7 条 AC、10 条 REQ 的设计及验证组映射 |
| 文档空白/结构及 Git 范围检查 | PASS | 无尾随空白/冲突标记；只有 F083 规格目录未跟踪，生产代码和暂存区无修改 |
| 新行为测试与真实环境验收 | NOT_RUN | 尚未进入实现，不能用静态证据替代 |

真实 MySQL/DM8、OpenFGA、MinIO、Milvus/ES、部署代理及业务后端账号绑定另行验证；受控 SDK/SQLite 验证也尚未执行。

项目 [AGENTS.md §6](../../../AGENTS.md) 要求 `spec.md → /sdd-review <dir> spec → ★ user confirms`，且 `★ pause points cannot be skipped.`；项目规格评审 Skill 也明确要求“等待用户确认”。因此当前等待完整规格确认，之后才能生成 tasks、任务评审并实施；本轮不提交、合并、推送或部署。

2026-10-26 用户回复“开始实施”，完整规格确认门禁已通过；后续实际实施和验证见 tasks.md、verification.md。
