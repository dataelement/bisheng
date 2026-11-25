# beta2 版本管理文件 edit 修复验证

目标：feat/3.1.0-beta2。基线：891292d4d0。实现分支：codex/beta2-version-file-edit-20261124。日期：2026-11-24。用户确认：版本管理的修改操作应校验文件 edit。继承原特性文档，仅在 beta2 修正，未回移 beta1。

## 最终行为

| 操作 | 权限目标 |
| --- | --- |
| 查看版本历史、候选 | 保留实际文件 visible 和既有可见范围过滤 |
| 设为主版本 | 所选历史版本的物理文件 edit |
| 关联 | 来源文件 edit 与目标文档主版本文件 edit |
| 合并 | 当前文件 edit 与来源文件 edit |
| 忽略相似文档 | 当前文件 edit |
| 删除历史版本 | 历史版本物理文件 edit，且原删除链路继续检查该文件 delete |

空间 edit 不代替文件 edit；有效文件 edit 不额外要求空间 edit。没有新增权限动作、API 请求/响应字段、配置项或生产数据库结构。版本开关、解析状态、租户隔离、主版本不可直接删除与处理互斥保持。

## 实现与并发

- `KnowledgeVersionService._require_file` 先验证实际文件、所属空间和租户，再调用统一 `require_business_action` 检查对应文件动作。原有链路无需复制鉴权逻辑。
- `KnowledgeVersionMutationRepository.aread_authorization_targets` 无锁解析来源/目标实际文件；读事务关闭后应用层逐文件授权，外部权限 I/O 不占写锁。取得原写锁后核对文件 ID、空间、租户；目标主版本或来源文件变化不能沿用旧授权。原单事务提交和未知提交结果处理保留。
- 独立历史删除应用自身补文件 edit；原物理删除计划、delete 权限、权限投影和可恢复清理继续执行。
- 两端行菜单与相似批量入口检查文件 edit；批量打开时只保留有 edit 的所选文件。Client 从现有文件权限摘要增加 edit 集合，避免混用 rename。共享历史对话框新增可选逐版本 `canSetPrimary` 回调，两端均接入文件 edit；删除回调要求 edit 与 delete。只读历史保持可用。
- Platform 批量处理已打开的弹窗在权限刷新期间保留原授权文件范围，成功刷新撤销授权后缩减或关闭；空权限集合不传入“空限制表示全部”的共享弹窗。服务端每次写入仍重新校验文件动作。

## 本地自动化结果

- 后端：`test/knowledge/test_knowledge_version_*.py` 与 `test/knowledge_unification/test_kn_version_mutation_*.py`，224 passed。覆盖 HTTP/DI/原生 SQL 写入、文件级允许/拒绝、关联/合并两侧授权、空间权限不能替代文件权限、租户隔离、授权期间移动/主版本替换、历史删除双动作与清理。
- Platform：`f118SpaceVersionOperations`、`f118SpaceVersionHistory`、`f118SpaceVersionDeleteRefresh`、`spaceSimilarDocumentDialog`、`knowledgeAdminRegressions`，73 passed。
- Client：`VersionHistorySheet`、`getKnowledgeBatchActions`、`KnowledgeSpaceHeader`、`useKnowledgeFilePermissions.downloads`、`KnowledgeSpaceContent.environment`、`useKnowledgeSpaceHeader.exit`，33 passed。
- 全前端 `pnpm lint`、`pnpm typecheck` 通过。lint 保留无关文件 `BatchTagDraftDialog.tsx` 的既有 unused-disable warning。
- 修改的 Python 文件 ruff format/check、架构守卫、diff whitespace 检查通过；修改的 TS/TSX 均不超过 600 行。新增五条 QA 用例均已核对八列和待执行结果。

测试环境修正：隔离 worktree 复用本机依赖，将 workspace 包链接指向本次源码；Client Jest 在进程内禁用本机未编译的可选 canvas，未修改业务代码或共享依赖。基线独立副本复现 7 项旧测试失败：两个 pending-similar 用例把迁入读取服务的方法误当成本服务鉴权，五个历史删除用例缺失处理 fence/artifact 表。当前修正读取委托测试、补齐删除 fixture 的两张表和被预 mock 掉的外部违规分块清理方法，实际版本写入与删除应用保持运行；最终相关套件全部通过。

边界：权限/对象存储/向量检索等外部运输在本地测试中受控替代；没有执行真实 OpenFGA + MySQL/DM8 中间件集成或线上普通用户验收。真实环境检查按 test-cases.md 的 TC-VER-001 至 TC-VER-005 待执行。未推送、未合入、未部署。

## Code Review Report

Feature：知识空间版本文件权限修正（AC-41、AC-42、AC-43、AC-44）。Scope：本分支完整 diff，对照继承的 spec/design/tasks/test-cases。Base：feat/3.1.0-beta2，891292d4d0。

| Dimension | High | Medium | Low | Status |
| --- | --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

审查重点：真实文件而非调用方空间 ID 决定授权；两个参与文件均通过统一入口；无空间 edit 兜底；权限调用在锁外，锁内目标变化拒绝；删除单动作不足无副作用；两端可见性与修改资格分开；版本链与删除成功后旧查询退役未回退。静态审查与本地测试 PASS，真实部署验收仍待执行。
