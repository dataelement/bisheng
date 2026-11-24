# Code Review Report

**Feature**: 工作流上线失败的资源定位提示（hotfix）
**Review scope**: 原实际模型/知识资源检查的错误上下文、平台通知文案和回归测试。
**Base branch**: `origin/feat/3.1.0-beta2`，基线 `6ca3d7d381`。
**Development branch**: `codex/beta2-workflow-publish-errors-20261124`。

## Summary

| Dimension | High | Medium | Low | Status |
|-----------|------|--------|-----|--------|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

## Evidence

- 实际模型存在性/所属租户/Root 提供商共享过滤及知识资源检查沿用原路径。入口 publish/unpublish 权限、根和版本锁、版本快照比较均保持；错误在构造执行图和写入前抛出，原事务回滚。
- 错误码 10996 与原 reason 保持，增加可选错误数据。仅使用已获授权工作流的节点名称与选择 ID，不查询不可用目标名称，不返回目标租户或凭据。其他错误原因原样抛出。
- 提示区分模型、重排模型、知识空间/旧知识库、QA 库；同一模型在多个节点出现时分别定位。节点名称限制 100 字，展示最多 5 项。前端只接受已知原因、类型、正整数 ID；旧响应和不合法数据保持原通用文案。
- 不新增数据库字段/迁移、索引准入、后台任务或依赖。设计快照更新于 `features/v3.1.0-beta2/006-reference-hints/design.md`。

## Validation

- 后端 `test_wf_current.py`、`test_wf_save.py`、`test_wf_management_scope.py`：**42 passed**。使用 SQLite 执行实际服务与仓储；覆盖模型删除、多节点、知识空间/QA 库缺失、重排模型、其他租户模型不披露名称，以及失败时状态/版本不变。原成功上线、下线及管理视图回归通过。
- 平台 `workflowReferenceErrors.test.ts`、`requestUserMessages.test.ts`、`requestErrors.test.ts`：**41 passed**。覆盖中英日三语、真实请求拦截器到通知、完整错误保留、去重、旧响应和异常数据。
- 后端改动 Ruff check / format、逐文件架构守卫、`git diff --check` 通过。
- 前端工作区完整 `pnpm lint`、`pnpm typecheck`、`pnpm locales:check`、`pnpm check-i18n` 通过。Lint 有一条既有 `BatchTagDraftDialog.tsx:58` unused eslint-disable 警告，不在本次修改范围。
- 未对 116 发布真实工作流或改动业务数据，未部署。MySQL/DM8 并发和真实页面通知不由上述本地测试证明。

## Deployment verification checklist

部署包含本次改动的前后端后，在 116 使用专用测试工作流验证：

1. 删除或取消共享所选测试模型，再上线，通知显示节点名、模型 ID 和重新选择提示；状态仍为草稿/下线。
2. 引用已删除测试知识空间或 QA 库，上线通知显示对应资源类型与节点；修改检索范围后可通过检查。
3. 高级检索配置中的失效重排模型显示“重排模型”及高级检索设置指引。
4. 普通有发布权限的用户与租户管理员都可看懂提示；其他租户资源名称不出现在通知或响应中。
5. 所有实际配置修复后正常上线；已有失效配置仍允许下线。

## Overall: PASS

本地代码审查与验证通过；提交及推送状态以 Git 远端为准。116 页面验收待部署后执行，本记录不作为部署完成证明。
