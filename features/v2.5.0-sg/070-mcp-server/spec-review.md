# MCP Server：规格评审记录

**Feature ID**: 070-mcp-server  
**Status**: REVIEWED_USER_CONFIRMED  
**Reviewed**: 2026-10-08  
**Mode**: spec

## 结论

规格静态评审通过，可以提交用户确认。尚未实现业务代码，尚未执行行为测试。
按项目 `.claude/skills/sdd-review/SKILL.md` 的 spec 模式完成需求覆盖与架构合规检查，
结合当前源码复核；没有使用其他 agent 独立评审，不把自审表述为独立审查。

## 审查范围与依据

- `spec.md`、`requirements.md`、`design.md`。
- 本次会话用户确认的首期范围；无独立 PRD 文件。
- 当前版本与继承版本的 release-contract，重点为资源授权、租户隔离、知识入口/版本/投影与文件可见性边界。
- `docs/architecture/02-backend-modules.md`、`10-permission-rbac.md`。
  文档中的旧权限描述与当前 P0 规则冲突时，以 AGENTS.md 及 PermissionService 源码为准。
- 当前 REST retrieve、external_id、Token service、配置读取、主应用 lifespan、官方 SDK 1.27.1 本地源码。
- 官方 SDK 1.27.1 服务端文档与 Streamable HTTP 规范；不按 SDK main 分支的新接口编写本版本设计。

## 项目检查清单

| 检查项 | 结果 | 依据 |
|--------|------|------|
| 1. 用户场景覆盖 | PASS | REQ-001～009 与 AC-01～13，限于知识检索。 |
| 2. 边界与错误覆盖 | PASS | 空结果、鉴权、权限、输入、限流、异常、超时、并发与取消。 |
| 3. UI 场景覆盖 | N/A | 首期不新增 UI；使用现有 Token 管理。 |
| 4. AC 格式与稳定 ID | PASS | 唯一 AC-NN，四列角色/操作/结果表。 |
| 5. AC 可验证 | PASS | requirements.md 指定验证方法，不能以静态阅读替代行为验证。 |
| 6. 版本不变量 | PASS | 不绕过权限、租户或知识版本规则；不写其他 Owner 的对象。 |
| 7. 技术覆盖 | PASS | 每个 REQ 有组件映射，每个 AC 有验证方法。 |
| 8. 领域所有权 | PASS | 只复用 Token、知识、权限与来源服务，不取得业务实体所有权。 |
| 9. 协议契约 | PASS | HTTP、工具输入输出、已有业务码、SDK 协议错误与失败结果均明确。 |
| 10. 分层与响应 | PASS | API → Service → 既有 Repository；MCP 原生协议包装例外已明确，REST 包装不变。 |
| 11. 规格与设计职责 | PASS | 规格保留 What/Why 与契约；文件装配和验证策略另列 design.md。 |
| 12. ORM/租户字段 | N/A | 不新增 ORM；按绑定租户上下文复用现有仓储。 |
| 13. 错误码分配 | PASS | 复用 19801～19806、19812，不申请新模块业务码。 |
| 14. 权限入口 | PASS | 复用既有知识权限服务；不读写 role_access，不授予新资源权限。 |

## 审查中校正的事实

锁定 SDK 的无状态模式不会自动拒绝 GET SSE。
最终规格明确由 MCP 入口在鉴权后对 GET/DELETE 返回 405，避免把 SDK 行为误写成已有保证。
会话管理器后台任务的 ContextVar 继承不能凭调用顺序假设，设计要求在工具实际任务内建立身份并执行并发/取消验证。

## 证据限制与下一步

- 本轮仅新增规格文档，没有修改 Token、配置、后端或测试代码，也没有运行生产操作。
- 当前积分模块两处用户已有 diff 保留。
- 业务验收 AC-01～13 均为 `NOT_RUN`；本记录的 PASS 仅表示规格内容检查通过。
- 等待用户确认 spec；确认后再生成并评审 tasks.md、创建分支、实施及验证。

## 后续状态

用户于 2026-10-08 回复“开始实施”确认规格；任务、实现及本地验证已完成，当前证据见 verification.md。
上面的 NOT_RUN 是规格评审时的状态，不是当前实现状态。
