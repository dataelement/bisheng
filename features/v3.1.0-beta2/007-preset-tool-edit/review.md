# Code Review Report

**Feature**: 预置工具编辑按动作授权
**Base branch**: feat/3.1.0-beta2
**Track**: 单模块小功能；无新 API、权限模型或数据库契约。

| Dimension | High | Medium | Low | Status |
|-----------|------|--------|-----|--------|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 1 | 0 | PASS_WITH_WARNINGS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

## Findings

MEDIUM：已覆盖本地业务鉴权与 SQL 链路，真实登录、Grant 投影和 OpenFGA 的部署环境验收仍待执行，见 e2e-checklist.md。模拟传输的允许结果不能作为真实所有者授权已验收的证据。

## 验证

- 后端：98 passed，覆盖工具鉴权、密钥投影、搜索配置、图像配置、本地 API 链路、统一动作运行时和预置初始化。
- 前端：9 passed，覆盖页面权限懒加载、编辑入口与纯权限判断。
- 架构守卫：无 VIOLATION；密钥投影测试内原有合成 canary 被 RULE-7 标为 WARNING，非真实凭据。
- 前端 lint：通过（保留无关文件已有的 unused-disable 警告）。
- 前端 platform/client 与共享包的类型检查：通过。
- `git diff --check`：通过。

## Overall: PASS_WITH_WARNINGS

默认系统授权仍仅 `visible`；本次仅让预置工具的 `edit` 进入现有统一动作运行时，编辑资格由实际授权决定。

## 2026-11-24 补充：隐藏系统预置关系行

按用户截图要求，仅删除权限列表合成的系统预置展示行及对应条件。历史空用户所有者继续过滤，真实授权行、全员可用开关及默认系统授权均保留。空列表回归通过；未引入权限变更请求。

本轮前端 22 项回归通过，覆盖系统行隐藏、真实用户控件、空态、搜索、部门页签、全员可用、可见权限提示和工具编辑入口。前端 lint、platform 类型检查及架构守卫通过。代码审查未发现新增问题。

## 2026-11-24 补充：空用户遗漏与所有者边界核对

漏项是前端把空用户过滤绑到了 owner 模型。现在按空用户身份识别，服务端也拒绝对历史空用户来源执行 MOVE。对照工作流、知识库和统一 OwnerProjectionService，确认受保护的是从业务 user_id 生成的创建者来源，不是所有绑定 owner 模型的授权；现有真实所有者保护机制保持不变。

验证：62 项后端测试、25 项前端测试通过，包含创建者来源拒绝修改/删除、普通工具 owner 来源可移动或删除且不影响创建者、空用户自定义模型隐藏、空用户 MOVE 在投影 prepare 前拒绝。Ruff 和架构守卫通过，无新增审查问题。未修改或清理部署环境数据。
