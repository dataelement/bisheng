# MCP Server：实现审查

**Feature ID**: 070-mcp-server  
**Reviewed**: 2026-10-08  
**Status**: PASS_WITH_NOTES  
**Base branch**: feat/2.5.0-sg（工作区 diff 与新增文件；没有新增提交）

## 范围与结论

按项目 task-review 与 code-review 清单自审本特性代码、规格映射和验证证据；未调用独立 agent。
没有发现阻塞本地交付的规格违背或新增高风险问题。
实际业务数据、DM8 与正式部署仍需按 verification.md 的 MANUAL_REQUIRED 验证。

## 任务级审查

| Task | 分层 | 命名 | 序列化 | 数据库 | 前端 | 信息泄漏 | 范围 / 依赖 / 配对测试 |
|------|------|------|--------|--------|------|----------|----------------------|
| T001 | N/A | PASS | N/A | N/A | N/A | PASS | PASS；先有新功能缺失证据，最终测试通过。 |
| T002 | PASS | PASS | PASS | PASS | N/A | PASS | PASS；共享检索与原 REST 回归覆盖。 |
| T003 | PASS | PASS | PASS | PASS | N/A | PASS | PASS；默认参数保留旧行为，真实服务路由参数化覆盖。 |
| T004 | PASS | PASS | PASS | PASS | N/A | PASS | PASS；继承权限、严格输入、实际 factory 会话关闭。 |
| T005 | PASS | PASS | PASS | N/A | N/A | PASS | PASS；默认配置、实际主 middleware 与 lifespan/TCP 覆盖。 |
| T006 | PASS | PASS | PASS | N/A | N/A | PASS | PASS；证据、接入说明和限制已记录。 |

MCP 采用原生 JSON-RPC/CallToolResult，为 spec AD-08 明确的协议包装例外；不强套 REST UnifiedResponseModel。
无新增业务表或查询，domain 层只通过现有仓储/服务与会话 helper 装配，未跨导入其他模块 API。

## 特性级审查

| 维度 | 结果 | 核查 |
|------|------|------|
| 边界条件 | PASS | 无结果、输入范围、未知工具/字段、Host/Origin、参数失败、超时。 |
| 认证与权限 | PASS | 每请求 Token、显式非空路由、绑定身份、业务权限原路径、拒绝不解析来源。 |
| 并发与资源 | PASS | SDK 的每请求 task group；真实 TCP 断开、取消、并发、继承 bypass 清理与同一 AsyncSession 释放。 |
| 信息泄漏 | PASS | 新代码不记录凭证、问题或签名；工具异常输出固定安全说明，日志包含 trace ID 与身份 ID。 |
| 测试覆盖 | PASS_WITH_NOTES | 相关回归与原生 SDK/TCP 通过；真实业务基础设施/DM8/正式代理不在本地证据内。 |
| 代码风格 | PASS_WITH_NOTES | 新模块完整 Ruff；既有大文件保留原 lint 诊断，新增诊断为零，不做无关格式化。 |

## 非阻塞说明

- SDK 默认参数模型会忽略未知字段，当前通过注册时更新其参数元数据启用 extra=forbid。
  该实现依赖锁定 1.27.1 的 `_tool_manager` 元数据接口；升级 SDK 时必须执行现有 schema/身份参数回归。
- 项目全局 pytest import stubs 不支持真实 assistant 路由继承和 JWT 异常类，主应用协议测试隔离了这些无关入口。
  没有把全部未修改业务路由的真实启动列为已经验证。
- 架构守卫 settings.py 的 RULE-7 警告与既有 lint 诊断是 baseline，本期未修改相关常量或尝试修复。
- 用户已有积分文件的 SHA-256 未变化；没有暂存、提交、推送、合并或部署。
