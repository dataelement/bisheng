# MCP Server：需求与验收方法

**Feature ID**: 070-mcp-server  
**Status**: CONFIRMED  
**Created**: 2026-10-08  
**Updated**: 2026-10-08

需求、用户故事、范围和唯一 API 契约以 [spec.md](spec.md) 为准。
本文只补充稳定的需求映射与验证方法，避免复制两份请求和响应定义。

## 确认记录 Clarifications

- 用户接受首期一个 MCP 入口和一个知识检索工具，确认使用 `X-Developer-Token` 并要求实施。
- 接入方能够配置远程 MCP 的自定义请求头；不将静态 Token 声称为完整 OAuth 兼容实现。
- 知识库 ID 由接入方配置；首期没有知识库发现、工作流执行、模型回答或工具管理页面。
- MCP 使用绑定用户；REST 的 `external_id` 身份代理能力不带入 MCP，也不修改原能力。
- 用户于 2026-10-08 回复“开始实施”，确认具体规格并授权实现。

## 需求追溯与验收方法

| Requirement | Acceptance | Verification method |
|-------------|------------|---------------------|
| REQ-001 | AC-01, AC-02, AC-12 | 对服务开关及生命周期执行 HTTP 集成测试；真实 SDK ClientSession 完成握手。 |
| REQ-002 | AC-03, AC-04, AC-05 | HTTP 边界参数化鉴权测试，复用 Token service 定向回归；拒绝路径断言业务未执行。 |
| REQ-003 | AC-04, AC-11 | 新入口空白名单拒绝测试，加原 REST 空白名单授权回归。 |
| REQ-004 | AC-02, AC-08, AC-10 | SDK tools/list、未知工具与身份参数拒绝；不同 Token 并发身份断言。 |
| REQ-005 | AC-06, AC-07, AC-11 | 共享检索编排契约测试与现有知识权限/检索/来源回归。 |
| REQ-006 | AC-06, AC-08, AC-09 | 真实 SDK HTTP 调用覆盖结构化结果、空结果、参数失败、超时和脱敏错误。 |
| REQ-007 | AC-10, AC-12 | SDK 任务上下文测试覆盖并发、业务异常和取消；断言资源释放及上下文复位。 |
| REQ-008 | AC-11 | 执行现有 REST 检索、external_id 和来源链接测试；新 MCP 输入限制不改变原 schema。 |
| REQ-009 | AC-13 | diff、架构守卫、Ruff；核对依赖与数据库目录未变化；DM8 实机标记待 CI/Linux 验证。 |

## 完成边界

实现测试未执行前，所有行为验收均为 `NOT_RUN`。协议端到端用锁定版本 SDK 的真实 HTTP 客户端覆盖，
业务基础设施可使用已有测试替身；替身结果不能证明真实部署的数据、权限配置和性能。
真实环境检查受条件限制时，提供步骤和 `MANUAL_REQUIRED`，不写成 `PASS`。
