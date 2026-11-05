# 文件夹删除状态 Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development to implement the backend and client work, with focused review and whole-change verification. Preserve all existing uncommitted work; do not commit or push automatically.

**Goal:** 复用文件夹 status，使删除中及未知状态在刷新后可恢复。
**Architecture:** KnowledgeFile 的目录专用状态与已有 user_metadata 保存当前尝试；根目录行锁和编号保护提交。成功证据复用既有直接删除账本；前端消费列表范围状态和批量查询，保留第一阶段守卫。
**Tech Stack:** FastAPI/SQLModel/SQLAlchemy/MySQL+DM8；React/TypeScript/现有请求封装。
**Spec:** spec.md AC-01～08；design.md（不含原 §5.4 loading 补充）。

## 状态及约束

| 文档 | 状态 | 说明 |
| --- | --- | --- |
| spec.md | ✅ 状态需求已确认 | 用户要求本次只加文件夹删除状态；loading 待复现 |
| design.md | ✅ 状态方案已实现并复核 | 2026-11-05 用户授权实施，不加表/字段/索引 |
| tasks.md | ✅ 已实施并复核 | 后端先测后改；不动 loading 性能方案 |

- 不实现 20 秒读取超时、不改变刷新清空列表策略、不优化清理并发/列表性能。
- 不改 OpenFGA 模型或直接操作其数据；权限仍走现有入口。
- 保留原服务账号/admin 脚本及第一阶段改动，在用户持续使用的当前分支工作；不创建替代 worktree、未经用户明确要求不提交、不推送；不操作真实业务目录。
- 所有新后端 ORM 在 repository；bulk 写显式 tenant/space/type 条件；使用已有 JsonType，无 DDL/回填。
- 前端不新增依赖、状态库或本地测试/构建；文案三语齐全。

## Review Focus

- 长事务根行锁阻塞续报：不得误报失败或等待自身连接形成死锁。
- 过期旧请求与新尝试交错：只有相同 token 可写，核对失效后旧请求不能删除。
- 目录标记被元数据编辑/旧快照覆盖或泄露：保护 status/保留键且对外剔除。
- 目录成功后原行消失：只凭精确 token 的账本/DB_CUTOVER 证据报成功；无证据不伪造终态。
- 空目录/深链/搜索/多标签及换空间：范围状态先于操作放行；旧响应不污染新范围。

## T1 后端状态数据与测试

- [x] 在 `src/backend/test/knowledge/test_folder_delete_status.py` 先写失败测试，覆盖 AC-01, AC-04, AC-05, AC-06, AC-07：独立提交可见、目录专用状态、重复 claim、失败恢复、token 替换、元数据合并、过期核对和成功账本精确匹配。
- [x] 新增 `knowledge/domain/repositories/knowledge_folder_deletion_repository.py` 及 `knowledge/domain/services/knowledge_folder_deletion_service.py`；NORMAL=2/DELETING=8，保留键 `_folder_delete`；10 秒续报/60 秒未知，核对最多等待 5 秒，锁忙保持未知；不依赖 JSON 路径 SQL。
- [x] 运行聚焦 pytest，记录结果；MySQL/DM8 实际锁语义另列环境验收，不宣称 SQLite 已证明双库行为。

## T2 后端生命周期接入（依赖 T1）

- [x] 新增/扩展删除服务聚焦测试，覆盖 AC-01, AC-03, AC-04, AC-05, AC-07：完整检查前可见、同 token 账本、明确回滚恢复、提交未知不恢复、审批不误标删除中、旧 token fence。
- [x] 在 `knowledge_space_service.py`、`knowledge_space_file_change_service.py`、`knowledge_space_direct_delete_service.py` 和 `knowledge_space_mutation_repository.py` 按原锁顺序接入；单删/批删统一路径，不绕过原完整授权；直接删除 token 贯穿原账本；审批有原子交接，绝不改变 worker/FGA 执行语义。
- [x] 运行直接删除/文件变更既有聚焦测试。

## T3 后端读取契约（依赖 T1/T2）

- [x] 先写 API/投影测试，覆盖 AC-02, AC-03, AC-04, AC-06, AC-07, AC-08：列表/空范围/搜索/树、祖先状态、权限隐藏、未知编号、已删除精确终态与普通观察者结束。
- [x] 列表项增量 `deletion_status:{state,operation_id,root_folder_id,retry_after_ms}`；data 分页对象 `scope_deletion_status`，无范围状态为 null；running/unknown 之外不限制普通可用目录。
- [x] `POST /knowledge/space/{space_id}/folder-deletions/status` 输入 folder_ids≤100/known_operations；返回标准 resp_200 data.items，状态 idle/running/unknown/succeeded/failed/approval_pending/untracked/unavailable，带 can_reconcile。`POST .../{operation_id}/reconcile` 输入 folder_id，同项返回。
- [x] env capabilities 增量 `folder_delete_status:true`。新增字段不得要求旧前端消费；旧后端不误启用。
- [x] 本任务产出冻结的 JSON 契约供 T5 消费，运行测试并记录。

## T4 元数据保护与兼容审计（依赖 T1；可与 T2/T3不同文件实施）

- [x] 先测试元数据单改/批改保护、对外输出过滤，覆盖 AC-05, AC-07；测试为真实字典合并/序列化行为，不镜像实现。
- [x] 检查 `knowledge_file_service.py`、目录更新/复制/移动、解析任务及列表枚举；禁止覆盖目录状态和保留键，不把内部删除标记传播进 RAG/索引/复制件。
- [x] 对发现的实际入口做局部保护，不重构无关模块；测试与架构检查。

## T5 Client 状态恢复（依赖冻结 T3 契约）

- [x] 修改 `src/frontend/client/src/api/knowledge.ts`，在 KnowledgeFile 映射保留 deletionStatus；children/search 响应保留 scopeDeletionStatus；增加批量状态/核对 API及能力读取。
- [x] 扩展 `pages/knowledge/hooks/useFolderDeletion.ts`，把服务器结果合入本页 Map；running/unknown 恢复范围守卫；旧后端保留原行为；新增服务端模式不得用“路径存在”解除未知删除锁。
- [x] `useFileManager.ts`/`pages/knowledge/index.tsx` 传递当前范围状态并在加载未知前保持范围操作守卫；不改现有 loading 展示/刷新策略。活动页面3秒批量轮询，隐藏暂停，未知核对最多一个/10秒重查，账号/租户/空间变化失效旧响应；不得自动 DELETE。
- [x] `FolderDeletingStatus.tsx` 与列表/卡片/树显示“状态待确认”；补 zh-Hans/en/ja，不改设计组件样式。
- [x] 不执行前端测试/构建。完成代码审阅、三语 JSON/键一致性检查和人工清单。

## T6 收尾

- [x] 更新 spec/design/tasks/HTML，只保留本次状态范围；loading 明确延期。
- [x] 读 e2e-test 技能，补并执行能本地安全运行的 API 端到端覆盖；外部环境删除只在授权独立测试数据上运行；无法执行的环境验收明确列出。
- [x] 新鲜上下文分别复核 backend/client，再全变更检查；修复重要问题并重新跑受影响后端测试。
- [x] 更新 ledger；未经用户明确要求不 commit/push/部署。说明需要更新后端才能体验跨刷新状态。

## 实际偏差记录

- loading 补充移出本次范围；等客户问题可复现后再定位，不能把兜底超时写成已实施修复。

## 验证结论

后端 212 项主回归和 26 项补充回归通过（部分重叠），前后端独立复核完成；前端运行检查依约未执行，真实双库/浏览器验收待部署后执行。全量知识模块探索性回归出现 4 项既有失败，未宣称全量通过；详见 verification.md。验证时未部署；提交/推送状态以 Git 记录为准。

## T7 用户追加：loading 诊断日志

- [x] 复用 trace ID，为 children/search 增加目录/来源及请求开始、固定阶段、结束耗时。
- [x] 为删除可见性读取增加 footprint/checkpoint 阶段和数量，不增加查询、不记录清单内容。
- [x] Client 仅添加固定来源请求头，不改加载/删除行为；前端检查依约跳过。
- [x] 75 项配置完整的后端聚焦测试、独立代码复核、Ruff/差异检查与排查说明。
