---
name: sdd-code-review
description: >-
  SDD 第 8 步：Feature 全部任务完成后、合入前的特性级多维度代码审查，对照 spec/design/tasks 按 7 个维度出 PASS / NEEDS_FIX 报告。
  用法：/sdd-code-review --base <目标分支>（通常是发版线，如 feat/3.0.0）。
  TRIGGER when: 用户运行 /sdd-code-review，或在 SDD feature 合入前要求特性级代码审查。
  与 Claude Code 自带的 /code-review（云端多 agent 找缺陷）不是同一个工具。
---

# Skill: sdd-code-review

## 描述

L2 特性级多维度代码审查。Feature 全部任务完成后执行（SDD 第 8 步）。

本 skill 是仓库内的唯一原件：`.cursor/skills` 与 `.agents/skills` 都是指向 `.claude/skills` 的软链接，改这里即可。

## 触发

```
/sdd-code-review --base feat/3.0.0
```

`--base` 取 Feature 要合入的目标分支，下文用 `<base>` 指代。

---

## 审查流程

1. 执行 `git diff <base>...HEAD --stat` 获取变更文件列表
2. 执行 `git diff <base>...HEAD` 获取完整 diff
3. 对照 Feature 的 `spec.md`、`design.md` 和 `tasks.md`
4. 按 7 维度逐一审查
5. 输出审查报告

---

## 7 维度审查框架

### 维度 1：边界条件

| 检查项 | 说明 |
|--------|------|
| null/None 处理 | 外部输入是否校验 None/空字符串 |
| 空集合 | 列表/字典为空时是否正确处理（不抛异常） |
| 数值边界 | 分页 page/size 合法性、ID 为 0/-1 |
| 字符串长度 | 数据库字段长度限制是否在 API 层校验 |
| 超时处理 | 外部调用（LLM/MCP/HTTP）是否设置超时 |
| 分页溢出 | 请求超出总页数时返回空列表而非错误 |

### 维度 2：权限与认证

> 以 `docs/constitution.md` C4 为准；本表只列审查时要看的点。

| 检查项 | 说明 |
|--------|------|
| 认证注入 | 需要认证的端点是否使用 `UserPayload = Depends(UserPayload.get_login_user)` |
| 资源动作鉴权 | 资源操作是否走 `permission.application` 的 `require_business_action` / `check_business_action`（F048 统一运行时），而不是直接查 `role_access`、OpenFGA 或旧的 relation/`permission_id` 模板（RULE-8） |
| 判定顺序 | 不自行重写 super_admin → 租户不匹配拒绝 → 租户管理员 → Catalog/动作闸 → OpenFGA 的短路顺序；RBAC 菜单权限不能当资源动作的兜底放行 |
| 资源生命周期 | 资源创建、移动、复制、删除与授权变更是否走权限模块的投影台账，而不是业务代码自己写 tuple（RULE-9） |
| tenant_id 隔离 | 跨租户访问被阻止；批量 `update()` / `delete()` 和原生 SQL 是否手写了 tenant 条件（自动过滤只拦 SELECT） |
| 普通用户验证 | 权限相关的测试或手动验证是否用了非管理员账号（super_admin 会短路） |
| WebSocket 认证 | WS 端点是否使用 `UserPayload.get_login_user_from_ws` |

### 维度 3：并发安全

| 检查项 | 说明 |
|--------|------|
| OpenFGA 双写 | MySQL + OpenFGA 写入是否有失败补偿（failed_tuples 表） |
| 数据库事务 | 多表写入是否在同一事务内 |
| Celery 幂等 | 异步任务是否支持重试不产生副作用 |
| 竞态条件 | 并发创建同名资源是否有唯一约束或乐观锁 |
| 会话状态 | Redis 缓存读写是否考虑过期和并发更新 |

### 维度 4：信息泄漏

| 检查项 | 说明 |
|--------|------|
| 硬编码敏感信息 | 代码中无明文密码/密钥/token |
| 错误信息 | 异常响应不暴露堆栈/SQL/内部路径 |
| 日志脱敏 | logger 输出中敏感字段已脱敏 |
| 前端暴露 | 前端代码不包含后端 IP/密钥/内部 API 路径 |
| tenant_id 泄漏 | API 响应不向前端返回其他租户的 tenant_id |

### 维度 5：测试覆盖

| 检查项 | 说明 |
|--------|------|
| Service 测试 | 核心 Service 方法有单元测试（mock DAO） |
| API 测试 | 新端点有集成测试（happy path + 主要 error path） |
| AC 覆盖 | spec 中每条 AC 都有对应测试或手动验证 |
| 错误路径 | 权限拒绝、参数校验失败等错误路径有测试 |
| 测试质量 | mock 合理，不 mock 掉核心逻辑 |

> **务实适配**：核心 Service 方法必须有测试。
> 前端：可抽成纯函数的逻辑（数据转换、校验、兼容升级）要有 vitest 单测；交互与视觉走 `/e2e-test` 的手动验证清单，tasks.md 只写「手动验证」不算覆盖。

### 维度 6：代码风格

| 检查项 | 说明 |
|--------|------|
| DDD 分层 | 新代码在正确的层级（domain/services vs api/endpoints） |
| 命名一致 | DAO/Service/错误码命名遵循项目约定 |
| 代码重复 | 无复制粘贴式重复逻辑（应提取到 Service 或工具函数） |
| 未使用代码 | 无 dead code、注释掉的代码块、空函数 |
| 格式化 | Python 代码通过 ruff check（hook 自动处理） |

### 维度 7：文档同步（design.md 现状快照）

> **目的**：确保 feature 合入后，新 agent 接手时读 design.md 能 5 分钟建立准确认知 —— 没有过期描述、没有缺失的反直觉坑、没有未声明的对外契约。

| 检查项 | 说明 | 严重度 |
|--------|------|--------|
| design.md 存在 | feature 目录下有 `design.md`（按 `features/_templates/design.md` 起的稿） | HIGH（缺失直接 NEEDS_FIX） |
| 决策同步 | diff 中新增/替换的关键技术决策（数据格式、配对/匹配策略、同步 vs 异步、二进制依赖等）在 §3 方案对比有记录，且给出"何时该重新考虑" | HIGH |
| 数据流/契约同步 | diff 触及 API 路径 / 请求响应字段 / 内部 Service 入参出参 / 数据库新表新字段 / 关键文件职责变化 → §4.1 数据流、§4.2 字段约定、§4.3 模块职责对应章节已更新 | HIGH |
| 已知坑同步 | 修了一个"代码里看不出的"反直觉 bug（典型：上游字段格式不符合直觉、运行时值与文档不符、必须的兜底逻辑）→ §5 已知坑 表新增一行（带"如果不知道会怎样"+"在哪处理"） | HIGH |
| 契约/依赖同步 | 新增对外 endpoint / 新依赖 chat/knowledge/permission 等模块的隐式契约 / 新增系统二进制依赖 → §6 Outgoing / Incoming 已补 | HIGH |
| 修订历史 | §修订历史 末尾追加了本次 feature 完成的条目（日期 + 改动 + 触发原因） | MEDIUM |
| 与 spec 不冲突 | design.md 对当前实现的描述未与 spec.md AC 矛盾（spec 是不变目标，design 是当前实现，二者口径必须对齐） | HIGH |

**判定要点**：
- 若 design.md 与代码现状偏离 → 必须修复（视为 HIGH），不能合入
- 仅本地小修小补（不改变对外行为、不引入新坑、不动决策）→ 本维度全 PASS 即可
- design.md 不存在但已在 SDD 流程要求之内 → HIGH，要求按模板补全后再审

---

## 判定规则

| 结果 | 条件 | 动作 |
|------|------|------|
| **PASS** | 无 HIGH 或 MEDIUM | 可合并 |
| **PASS_WITH_WARNINGS** | 仅 MEDIUM 级 | 可合并，记录待改进 |
| **NEEDS_FIX** | 有 HIGH 级 | 修复后重审（最多 2 轮） |

---

## 输出格式

```markdown
# Code Review Report

**Feature**: <feature_name>
**Review scope**: <描述>
**Base branch**: <base>
**Changed files**: <数量>

## Summary

| Dimension | High | Medium | Low | Status |
|-----------|------|--------|-----|--------|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync (design.md) | 0 | 0 | 0 | PASS |

## Findings（如有）

### HIGH
- [Permission] `xxx_endpoint.py:42` — 资源删除前未调用 require_business_action(action="delete")

### MEDIUM
- [Style] `xxx_service.py:18` — DAO 方法未使用 @classmethod

## Overall: PASS / PASS_WITH_WARNINGS / NEEDS_FIX
```
