# Code Review Report

Feature：110-dsh-local-access。范围为本次 DSH 代码和文档（审查时为工作区差异和新增文件）；实现基线 a2b7860d8efed08fdee41e9ecdf46560ed5ef0bb，Desktop 基线 origin/V1.1.0。

## 结论

本地实现审查无未修复 HIGH；发布验收仍待完成。以下按 code-review / task-review 框架自审，未经独立审查者复核。验证边界与完整门禁问题见 [validation.md](./validation.md)。

| 维度 | 结果 |
| --- | --- |
| 边界 | 回调、PKCE、身份、Token 形状/用途、绝对过期、请求参数与分页边界受限 |
| 权限与认证 | 浏览器接口保留原 JWT 管理权限；DSH 依赖独立；本地会话用 strict_tenant_filter，摘要定位为最小专用全局读取 |
| 并发 | SQL 会话行锁、refresh 代际唯一约束、旧摘要保留；重放撤销提交后抛错；真实双库并发待验证 |
| 信息泄漏 | 无生产密钥；只持久化 refresh 摘要；认证 no-store，日志不记录请求正文，旧别名路径同样去 query 日志 |
| 测试 | 本地后端、管理端和客户端回归及跨仓库响应解析通过；真实端到端未覆盖项明确列出 |
| 风格与架构 | 改动 Python Ruff / TS ESLint通过；分层和单迁移 head 通过；没有新增依赖、组件样式或 i18n key |
| 文档 | spec/design/tasks、发布说明、验证记录及原技术评估已同步当前实现 |

## 已修复发现

1. SQLModelSerializable.model_dump 产生时间字符串：事务 snapshot 改保留原生 datetime，避免过期比较报错。
2. refresh 重放需要撤销状态提交后才抛公共错误，避免事务回滚撤销。
3. 会话不能沿用模型的 Root 可见集合：使用 strict_tenant_filter 自动精确注入，增加真实过滤事件下的跨租户分页及撤销测试。
4. 旧 compatibility router 必须挂应用层，避免 /api/v1/api/dsh 路径。
5. 清理已退休的 profile Beat 任务、远程恢复动作与 worker HTTP 关闭引用，新增关闭路径回归。
6. 角色迁移不能用 max 抬高个人值：显式历史来源读取器只供运维脚本，保留个人值（包括零），验证后停用 ROLE。
7. 旧席位 UI/API 测试以无商业化、继承、幂等和本地失败恢复测试替代；保留历史用量和操作审计读取。

## 任务级审查

T001：本地模型与 Repository、一次性票据和 Token 行为一致；无 Gateway 调用。
T002：双路径注册、精确 middleware 名单、新表发现和历史列 DDL 一致；未扩大租户绕过。
T003：额度优先级、成员独立、新成员继承、无占席和退休任务一致；操作历史保留。
T004：管理端商业入口退出，模型审计保留；Desktop 审计字段和既有安全存储维持。
T005：本地检查已执行，外部资源和原生 UI 检查未标记通过；完整前端门禁存在已核对的原有失败。

## 发布阻塞

真实无 Gateway Electron 到 Python 的全流程、真实 Redis 与 MySQL/DM 并发/迁移验收、全仓既有前端 lint/typecheck 问题仍未关闭。因此本报告不代表已可部署或正式发版。
