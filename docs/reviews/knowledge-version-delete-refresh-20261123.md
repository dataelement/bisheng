# Code Review Report

**Feature**: 删除知识文件历史版本后不再请求已删除文件的权限
**Base**: feat/3.1.0-beta2 / e3baf7e5e7
**Branch**: codex/beta2-version-delete-refresh-20261123
**Track**: 已确认缺陷修复，保留现有 API、权限与交互合同。

## Problem and change

116 的记录显示，2026-11-23 20:50:44 删除版本 12327（物理文件 99099）已成功，随后历史列表刷新尚未完成，页面又请求了 99099 的 my-permissions。已删除文件返回 25022，因此用户同时看到成功和错误提示。V1/V2 仍然存在，删除任务已完成。

根因是 SpaceVersionHistorySheet 在写入后按空间前缀统一 invalidate，旧历史数据仍驱动已删文件的删除权限和批量下载检查。

- 删除接口成功后立即更新本次打开的历史缓存，并记录已确认删除的物理文件 ID。迟到的旧历史响应不重新显示该版本。
- 取消仍包含这些 ID 的删除权限和批量下载检查；后续空间刷新排除这些过期查询，其余查询继续刷新。
- 历史文件权限请求透传 AbortSignal，取消能够传递到 HTTP 层。
- 删除失败不改历史缓存；其他文件的权限错误继续显示。未全局忽略 25022，未放宽后端权限，未再次删除现场文件。
- 保留原弹窗、确认流程和文案，不改样式；设计现状同步到 015-knowledge-space-admin-ui/design.md。

## Review

| Dimension | High | Medium | Low | Status |
|-----------|------|--------|-----|--------|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

缓存和已删除 ID 按身份、租户、空间、目录、文件及本次打开隔离。未确认成功、范围已退役或信号已取消时不更新缓存。查询取消和失效过滤仅针对已确认删除的物理文件，剩余文件的权限查询及空间刷新仍走原流程。版本写入锁、失败冻结及主版本约束沿用共享 VersionHistoryDialog。

## Validation

新增回归先在旧逻辑上复现两个慢刷新/旧响应失败，再验证修复：

1. 历史列表慢返回时，已删除版本立刻移出，且不再请求其权限或下载检查。
2. 刷新返回旧版本列表时，不恢复已确认删除的版本。
3. 删除失败继续保留原历史并展示原错误。
4. 已在途的权限请求在删除成功后收到取消信号。
5. 剩余文件的真实权限错误继续展示。

验证命令（platform 目录；Node 25 关闭实验 webstorage，使用 jsdom 的 Storage）：

```sh
NODE_OPTIONS=--no-experimental-webstorage pnpm exec vitest run \
  src/test/f118SpaceVersionDeleteRefresh.test.tsx \
  src/test/f118SpaceVersionOperations.test.tsx \
  src/test/f118SpaceVersionHistory.test.tsx \
  src/test/f118SpaceDirectoryHistory.test.tsx \
  src/controllers/requestErrors.test.ts \
  src/controllers/requestCompatibilityMatrix.test.ts \
  -t '^(?!opens the shared pending dialog for the selected similar files from the workspace batch menu)' \
  --maxWorkers=1 --minWorkers=1
```

上述范围共 67 项：66 项通过；目录批量菜单的 1 项原有失败单独排除。该用例在修改前的 SpaceVersionHistorySheet 上也复现 `detail.batch` 按钮定位失败，对照日志在本机 `/private/tmp/bisheng-version-delete-refresh-20261123/directory-baseline.log`。未修改其断言以掩盖失败。

前端全工作区 lint、typecheck，变更文件定向 ESLint、arch-guard、git diff --check 均作为交付检查；lint 原有 BatchTagDraftDialog 的未使用 disable 警告未扩大修改。依赖复用本机已安装 store，workspace 包链接到本开发工作区，未修改依赖清单/锁文件。

未在 116 执行新删除操作或部署；本地回归不代表真实浏览器现场验收。

## Overall: PASS
