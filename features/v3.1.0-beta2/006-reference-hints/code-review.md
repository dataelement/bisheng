# Code Review Report

**Feature**: F006 引用关系辅助提示
**Review scope**: spec/design/tasks、完整特性差异、最新 beta2 合并结果与语义冲突修复
**Base branch**: `origin/feat/3.1.0-beta2`，`f447b5a36d`（合并前最新远端）
**Feature commit**: `f4d7292a47`（原起点 `23c82f7769`）
**Changed files**: 192（相对目标基线，含本报告；不包含目标分支自身已合入的历史修复）

## Summary

| Dimension | High | Medium | Low | Status |
| --- | ---: | ---: | ---: | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 2 | 0 | PASS_WITH_WARNINGS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync (design.md) | 0 | 0 | 0 | PASS |

## Findings

### HIGH

无未解决项。合入时发现的语义冲突已修复：目标分支新增的旧知识库模型名称兼容仍要求引用集合保留标记，与 AC-07 冲突。已保留按原名称查看/有权修复的兼容，取消在线标记准入；无法确定 ID 时仅相关调用失败，不按当前名称重新绑定。新建仍严格校验真实 Embedding ID，异步提取不虚构旧名称的模型目标。对应原测试已改为验证无标记也可查看和重校验；新刷新测试验证该名称不产生模型引用。

### MEDIUM

- **测试覆盖**：最新 beta2 基线仍有 8 个既有失败，本地未完成这些场景验收。对目标基线 `f447b5a36d` 的独立源码导出运行相同 node ID，8 项均失败，与合并后失败集合完全一致；详见 regression-adaptation.md。未新增 skip/xfail，也未把失败记为通过。
- **测试覆盖**：真实 MySQL/DM8、Worker、FGA 与浏览器环境 E2E 尚未执行。用户明确安排更新开发环境后自行测试；本次合并授权包含该安排，清单保留在 e2e-checklist.md。本地通过不代表环境验收通过。

## 七维度检查依据

1. **边界**：空引用、缺失索引、孤儿租户/Run、坏 JSON、旧业务绑定丢失、目标已删除、提示超时/SQL 失败均有定向覆盖；未知提示独立于业务确认，不返回全量无引用的保证。旧模型名称从原业务值识别，未知格式不猜测。
2. **权限**：保留 UserPayload、PermissionService 资源动作判断、实际目标/Root 共享和租户校验；辅助查询只披露原权限可见来源。异步任务校验租户参数与 header，替换/删除明确限定来源租户；旧账本不提供授权。
3. **并发**：业务自身版本、计划签名、处理 lease、事务和权限投影恢复保留。提示使用独立 Session 与 2 秒预算；同步任务读取当前配置后在自身事务替换旧表，重复任务/失败重试有覆盖。允许提示滞后，未增加 outbox、顺序锁或完整性签证。
4. **信息泄漏**：新增日志仅记录资源身份、任务与异常类型；无新凭据或配置载荷日志。提示沿用可见详情与受限聚合；无权来源不暴露名称、路径等详情。
5. **测试**：合并后适配组合 1303 passed / 8 基线失败 / 0 errors；冲突定向 71 passed；目标新增的旧知识/空模型兼容及迁移源码/清单/目标相关组合 105 passed。前端代码与已验证特性提交一致，目标仅调整 package 版本；沿用 37 项交互、lint/typecheck/i18n 的已记录结果。
6. **风格**：158 个变更 Python 文件编译通过、Ruff 无新增问题，架构守卫无 VIOLATION。knowledge_service.py 的 38 个存量 Ruff 问题保持可见；schemas.py 既有 RULE-3 warning 未新增。删除合并后无调用的旧名称标记查询及模型 `_source` 辅助方法，无新 schema、依赖或迁移。
7. **文档**：spec AC-01–14 与实现对齐；design 记录原表复用、业务 JSON 绑定、异步普通重试、独立提示事务、旧计划恢复、旧名称兼容决策与重新考虑条件。任务状态、发布契约和验证边界已同步。

## Overall: PASS_WITH_WARNINGS

未发现新增阻断缺陷；保留既有失败与用户后续环境 E2E 的验证限制，按用户授权合并到 beta2 并推送。未部署，未执行线上资源删除、历史账本清理、迁移或回填。
