# Code Review Report

**Feature**: 修复批量标签候选遗漏及可见失败项名称隐藏
**Base branch**: `origin/feat/3.1.0-beta1`，基线 `065914f440`
**Branch**: `codex/3.1.0-beta1/bugfixes-20261119`
**Track**: 已授权的知识空间权限 UI bugfix；继续使用本轮独立 worktree。

## 修复行为与原因

- Platform 和 Client 的批量标签弹窗在空间有效动作包含 `visible` 后，读取既有空间标签列表。候选合并所选文件已有标签，因此空间已有、所选文件尚未使用的标签也能选择。没有根空间可见权限时不读根标签字典，文件上的已知标签仍可选择。
- `visible` 不开放创建或删除标签；新建/删除仍要求空间 `edit`，文件关联仍要求文件 `rename`。批量新标签仍只在确认成功时创建。
- 标签列表加载失败提供重试，保留已选标签；Platform 查询键带完整身份、租户、管理范围与空间，Client effect 退役后丢弃旧空间或已关闭弹窗的迟到响应。
- 后端 ordinary batch 通过同一个 F048 批量入口请求操作动作和 `visible`，分别保存判定。失败项仅按可见性决定名称：可见但缺操作权限显示名称与 `no_permission`；真正不可见时隐藏名称。覆盖标签、重试、下载及不支持标签操作的选中文件夹。
- 未改数据库、接口字段、权限模型或拒绝原因。签名计划、最终重新鉴权、回放和业务写入事务继续使用原实现，名称可见不会授予操作资格。

## 七维审查

| 维度 | High | Medium | Low | 证据与结论 |
|---|---:|---:|---:|---|
| 边界条件 | 0 | 0 | 0 | PASS：空候选、去重、读取失败重试、迟到响应及未授权输入均有回归 |
| 权限与认证 | 0 | 0 | 0 | PASS：F048 唯一授权入口；普通用户测试区分 visible、rename、edit，拒绝后无业务写入 |
| 并发安全 | 0 | 0 | 0 | PASS：读取权限不持有业务事务；最终鉴权、计划签名及幂等回放保持原规则 |
| 信息泄漏 | 0 | 0 | 0 | PASS：不可见文件不返回失败项名称；无根可见资格不请求空间标签字典；旧范围结果不回填 |
| 测试覆盖 | 0 | 0 | 0 | PASS：92 项专项服务和组件回归通过，覆盖新增两个缺陷与相关拒绝路径 |
| 代码风格 | 0 | 0 | 0 | PASS：完整前端 lint/typecheck、i18n、Ruff、arch-guard、diff 检查 |
| 文档同步 | 0 | 0 | 0 | PASS：design.md 更新当前候选来源、权限分离和已知坑；旧审查明确标注补充纠正 |

## 验证

- Backend `test/knowledge_unification/test_kn_batch.py`：22 项通过。普通用户可关联已存在且未使用的空间标签；tag/retry/download 可见但动作拒绝时保留名称，不可见时隐藏；强行确认拒绝且 Tag/TagLink、文件状态和任务分发没有业务变更。选中文件夹的 unsupported 原因与名称按自身可见性处理。
- Platform：`knowledgeTagPermissions.test.tsx`、`knowledgeTagSelectControlled.test.tsx`、`knowledgeAdminRegressions.test.tsx`、`useKnowledgeBatch.test.tsx`，51 项通过。覆盖空间查看权限下的完整候选、无根可见资格的文件标签、读取失败重试和租户切换。
- Client：`EditTagsModal.batch.test.tsx`、`EditTagsModal.errors.test.tsx`、`useKnowledgeSpaceHeader.exit.test.tsx`，19 项通过。覆盖空间仅查看时追加其他已有标签、无根可见资格不读取字典、重试保留选择和跨空间迟到响应退役。
- 完整前端 `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n` 通过；修改 Python 的 Ruff、逐文件架构守卫及 `git diff --check` 通过。
- 第三方依赖复用已有本机安装，workspace 包仍链接当前 worktree。Jest 使用临时 preload 隔离本机不可用的可选 canvas，不提交环境文件。

## 验证边界

这是本地原生 SQLite 仓储、应用层和组件验证；权限端口由普通用户权限矩阵 mock，未运行 116 的 1001 真实账号/OpenFGA 浏览器联调，也未部署或重启服务。此前确认的无关接口契约测试按用户指示保持不变，本次没有宣称整个历史测试套件全部通过。

**Overall: PASS**
