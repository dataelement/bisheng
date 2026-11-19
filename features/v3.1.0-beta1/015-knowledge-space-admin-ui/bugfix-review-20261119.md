# Code Review Report

**Feature**: 知识空间相似文档处理权限与引用来源入口修复
**Review scope**: 用户 2026-11-19 提出的两个缺陷，按 hotfix 流程实施。
**Base branch**: `origin/feat/3.1.0-beta1`，起点 `2afbe55601ab0e614b261ee7b679af63750b6fcd`
**Fix branch**: `codex/3.1.0-beta1/bugfixes-20261119`

## 修复结论

- 原 Client 的批量处理入口和卡片/列表相似标签、Platform 的批量入口和相似标签使用 `manage_permission`；统一改为所属知识空间的 `edit`。
- 后端关联、合并已有空间 `edit` 校验；补齐“不关联”的校验，从真实物理文件取得空间 ID，不接受请求方提供鉴权目标。拒绝发生在状态更新和成功审计前，重复请求也需要重新鉴权。
- 基线已删除文件/文件夹行菜单引用来源。本次删除遗漏的两个批量工具栏入口及目录 hook 中的无消费者方法；删除预检及引用展示沿原流程。
- 无 API 路径、请求响应格式、权限动作目录或数据库结构变化。候选/版本历史沿用原可见范围读取。

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

## 本地验证

- 后端 23 项通过：`test_knowledge_version_service_similar_dismiss.py`、`test_knowledge_version_service_link.py`、`test_knowledge_version_service_set_primary.py`、`test_knowledge_version_endpoint_similar.py`。普通用户身份覆盖真实文件所属空间、成功状态更新，以及拒绝时不写状态/审计；外部权限端口使用 mock。原开关关闭用例期望的 HTTPException 已过期，同步为现有 `VersionManagementDisabledError`，未改产品异常行为。
- Platform 51 项通过：`knowledgeAdminRegressions.test.tsx`、`KnowledgeDeletionDialog.test.tsx`、`useKnowledgeDeletion.test.tsx`。覆盖仅 edit / 仅 manage_permission、单项标签与批量入口、文件/文件夹的两种工具栏、删除引用展示及原预检流程。
- Client 17 项通过：`KnowledgeSpaceHeader.test.tsx`、`KnowledgeDeletionDialog.test.tsx`、`KnowledgeSpacePresentation.test.tsx`、`getKnowledgeBatchActions.test.ts`。覆盖桌面/移动批量权限、删除引用展示及独立入口隐藏。
- `pnpm lint`、`pnpm typecheck`、变更 Python 的 ruff、逐文件 arch-guard 与 `git diff --check` 通过。
- 独立 worktree 复用已有第三方依赖，并将 workspace 包链接到本 worktree 源码。Jest 用临时 Node preload 将未编译的可选 canvas 视为不可用，让 jsdom 使用原生降级；未修改依赖源码或提交测试运行环境配置。

## 验证边界

没有部署到 116，没有进行真实 OpenFGA 权限矩阵或浏览器端联调验收。上述为本地服务/组件回归与静态质量检查，不代表线上验收。

## Overall: PASS
