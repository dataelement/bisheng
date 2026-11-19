# Code Review Report

**Feature**: 文件可修改、空间不可编辑时的标签权限提示
**Base branch**: `origin/feat/3.1.0-beta1`，基线 `c3319b0550`
**Branch**: `codex/3.1.0-beta1/bugfixes-20261119`
**Track**: 现有授权规则下的 bugfix；不新增权限动作、不放宽写入资格。

## 结果

- 文件标签关联沿用 `knowledge_file.rename`，空间标签新建/删除沿用 `knowledge_space.edit`。
- 前后台的单文件/批量窗口提示“可选择已有标签，创建或删除空间标签需要空间编辑权限”，并限制相应控件。已有标签的选择、移除与保存继续可用。
- Platform 的空间动作请求按完整身份、租户、管理范围和空间分区；检查中或失败时不开放创建，失败提供重试，重试保留已有标签选择。
- 批量预检不再因缺空间编辑权限清空文件授权结果。可修改文件保留名称并说明缺少新建标签所需的空间权限，真正缺文件权限的条目继续隐藏名称。
- 接口结构不变，仅在已有字符串 reason 字段补充 `space_tag_permission_required` 诊断，两端均提供中英日文案；已有混合选择、签名计划和确认时重新鉴权保持不变。
- 禁用的删除图标不会冒泡触发标签选择；批量草稿不新增根标签字典读取或提前创建标签。

## 七维审查

| 维度 | High | Medium | Low | 结论 |
|---|---:|---:|---:|---|
| 边界条件 | 0 | 0 | 0 | PASS |
| 权限与认证 | 0 | 0 | 0 | PASS |
| 并发安全 | 0 | 0 | 0 | PASS |
| 信息泄漏 | 0 | 0 | 0 | PASS |
| 测试覆盖 | 0 | 0 | 0 | PASS |
| 代码风格 | 0 | 0 | 0 | PASS |
| 文档同步 | 0 | 0 | 0 | PASS |

## 本地验证

- Backend：`test/knowledge_unification/test_kn_batch.py`，13 项通过。新增普通用户场景：允许文件 rename、拒绝空间 edit，区分混合选择原因与名称可见性；强行确认被拒，Tag/TagLink 无业务写入。已有仅关联已知标签不请求根 edit 的回归继续通过。
- Platform：`knowledgeTagPermissions.test.tsx`、`knowledgeTagSelectControlled.test.tsx`、`knowledgeAdminRegressions.test.tsx`、`useKnowledgeBatch.test.tsx`，合计 47 项通过。覆盖检查中、受限、失败重试、租户切换、允许创建、已有标签保存、禁用删除及预检原因展示。
- Client：`EditTagsModal.batch.test.tsx`、`EditTagsModal.errors.test.tsx`，12 项通过。覆盖仅有文件权限时的提示、已有标签确认、新建/删除阻断及原错误处理。
- 完整前端 `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`，修改 Python 的 Ruff、逐文件 arch-guard 和 `git diff --check` 通过。
- 独立 worktree 复用已有第三方依赖、链接本 worktree 的 workspace 包；Jest 使用临时可选 canvas 隔离配置，未提交运行环境改动。

## 验证边界

上述为本地服务和组件验证；没有进行 116 真实 OpenFGA 权限矩阵或浏览器联调，没有部署到 116。权限端口在专项服务用例中 mock，原生 SQLite 仓储验证拒绝时零业务写入。

**Overall: PASS**
