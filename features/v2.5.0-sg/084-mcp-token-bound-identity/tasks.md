# F084：回退实施任务

- Status: `IMPLEMENTED_LOCAL`
- 用户已确认范围与实施；不提交、合并、推送或部署。
- 按当前项目规格/任务清单自审：范围对应已确认的权限回退，保留所有 Owner，无 Schema 或配置变更，测试先行，无新增待确认行为。

- [x] T001 身份/schema 安全测试先行：test/mcp_server/test_mcp_user_context_service.py、test_mcp_tools.py。将账号代理测试替换为 principal 绑定身份、完整上下文恢复、十工具 external_id 拒绝/无账号可用。覆盖 AC: AC-01, AC-02, AC-03
  _Requirements: REQ-001, REQ-002, REQ-003_
  _Acceptance: AC-01, AC-02, AC-03_
  _Verification: V-SDK, V-IDENTITY；记录实现前失败_
  _Depends: none_
  _Boundary: 仅更新回退语义的测试，其他业务断言保留_

- [x] T002 请求/注册回退：mcp_server/domain/schemas/identity.py，四个顶层请求模块及四个 endpoints 移除账号字段/构造，未知字段仍拒绝。
  _Requirements: REQ-001_
  _Acceptance: AC-01_
  _Verification: V-SDK_
  _Depends: T001_
  _Boundary: 相同机械参数变更作为一个可观察批次，不改其他参数或返回_

- [x] T003 绑定身份解析：user_context_service.py、factory.py 移除账号查询/当前租户选择，以 principal 生成执行 DTO，保持绑定 UserPayload。
  _Requirements: REQ-002, REQ-003_
  _Acceptance: AC-02, AC-03_
  _Verification: V-IDENTITY_
  _Depends: T001, T002_
  _Boundary: 不改 Developer Token 认证、REST 或共享仓储_

- [x] T004 两执行链路：tool_runtime.py、search_service.py 仅向解析器传 principal，移除账号消费，保持会话/ContextVar/超时和审计。
  _Requirements: REQ-001, REQ-002, REQ-003_
  _Acceptance: AC-01, AC-02, AC-03_
  _Verification: V-SDK, V-REGRESSION_
  _Depends: T003_
  _Boundary: 无旁路授权或角色提升_

- [x] T005 SDK/端到端 fixture 和回查适配：test_mcp_server.py、test_search_factory.py、test_mcp_knowledge_flow.py、test_main_integration.py；请求不传账号，fixture Token 绑定身份决定允许/拒绝，覆盖实际 SDK 与 SQLite 写入及无权/跨租户拒绝。覆盖 AC: AC-02, AC-03, AC-04
  _Requirements: REQ-002, REQ-003, REQ-004_
  _Acceptance: AC-02, AC-03, AC-04_
  _Verification: V-FLOW, V-REGRESSION_
  _Depends: T001_
  _Boundary: 测试先于对应批次最终验证，不移除其他工具回归断言_

- [x] T006 文档、相关回归与交付：更新 docs/api/mcp-usage.md、F081 被替代提示；执行 MCP/Token/REST/知识相关回归、静态检查；记录 verification.md 和 code-review.md。
  _Requirements: REQ-003, REQ-004, REQ-005_
  _Acceptance: AC-03, AC-04, AC-05_
  _Verification: V-REGRESSION, V-DOC_
  _Depends: T002, T003, T004, T005_
  _Boundary: 无外部数据或部署；未验证设施如实标注_

## 实际偏差记录

参数删除涉及八个小型声明文件，按同一 schema 行为批次处理，避免为相同字段制造重复验证。测试 fixture 适配按共享 SDK harness 组成批次。用户已明确确认安全与接口范围并要求实施，因此复用本次确认和 F070/F078 原绑定用户模式，不对同一范围重复申请确认。

最终检查点：T001～T006 本地完成，相关回归 346 passed；Ruff、架构守卫、文档示例检查通过。实际设施和上线验证仍需单列执行，见 verification.md、code-review.md。
