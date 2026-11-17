# 空间复制权限投影竞态修复

日期：2026-11-16（UTC+8）。目标分支：`feat/3.1.0-beta1`。修复基线：`d6ddfb527a`。
范围：既有复制流程的执行互斥与回归，未更改接口、表结构或授权语义。

## 已核实的问题

116 在 14:23:40 复制空间 3439：确认接口提交任务后继续建立权限，Worker 同时进入 `aensure_logical`，在任务租约前恢复仍由 API 执行的投影。Worker 于 14:23:40.857 判定 `projection commit state is MIXED` 并封闭投影；API 于 14:23:40.915 尝试 STAGING CAS 时返回 25002。

任务 `58a4d9e9-f9c7-44a4-95ed-54953a4e6841` 的目标空间为 4399，10 个文件均在 pending 步骤被标记失败。投影 3488 对应 `knowledge_file:98235`，SQL 为 FAILED_CLOSED；定点 HIGHER_CONSISTENCY 读取确认原账本的 9 条 FGA 关系均已满足 AFTER。原子写入期间的两次独立读取可以分别观察提交前和提交后，并不构成跨请求的一致快照。

以上为只读排查时的现场状态，不代表已恢复。未部署本修复，也未修改该任务或权限数据。

## 修复

- 每个资源投影及最后的索引初始化/目标状态提交，均通过 `SpaceCopyOwner._logical_target` 在同一 SQL 事务中依次锁源空间、目标空间。
- 接口、Worker 和重试使用同一入口；执行者离开或异常回滚后，下一个执行者才读取、恢复原投影。
- 锁按单个资源释放，避免跨整个大空间的权限循环持锁；F048 操作和 tuple 继续独立持久化。
- 等待者使用锁后读取的目标状态决定是否初始化索引，避免旧快照重复初始化。
- 保留当前身份重验、原计划校验、完整 AFTER 验证及 FAILED_CLOSED 恢复，不吞掉 CAS 错误。

现状与重审条件同步于 F118 `design.md` §5.3。

## 验证

- 复制、复制索引、任务租约/派发、F048 投影与 Owner 相关回归：**82 passed**。
- 新增 3 项：确认接口/Worker 竞争；FAILED_CLOSED 原账本恢复及锁释放；提交后取消、原 STAGING 续跑。
- 同一新增测试在未修复基线：**1 failed / 2 passed**；失败为接口/Worker 互斥回归。
- SQLite 忽略 FOR UPDATE；单测仅替换该锁原语，业务、任务和投影账本仍使用原生 SQL。
- 116 真实 MySQL：临时内存副本执行修复的锁方法，两条独立 SQL 连接；`performance_schema.data_lock_waits` 观察到等待，释放后等待者进入。仅 SELECT/FOR UPDATE，无业务写入、部署或服务重启。这验证锁互斥，不代表完整线上复制验收。
- Ruff check/format、arch-guard、`git diff --check` 通过。真实 DM8 并发未执行，仍由中央回归覆盖。

## Code Review Report

**Feature**: space copy projection race hotfix  
**Base branch**: feat/3.1.0-beta1  
**Changed files**: 4（含本报告）

| Dimension | High | Medium | Low | Status |
| --- | ---: | ---: | ---: | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

**Overall: PASS**。修复后的完整线上复制和历史任务恢复尚未执行。

## 2026-11-17 根因复核与恢复补齐

以 beta1 `e249b3b42d` 为修复基线。重新只读读取 116 持久日志，确认原记录：API trace `664cec87041749b084a1728b91392ff4` 在 14:23:40.729 / .821 完成两次 OpenFGA 写入；同秒 Worker 进入 `SpaceCopyOwner.astart → aensure_logical → reconcile_operation → _resolve_commit`，于 .857 判 MIXED；API 于 .915 报 STAGING 并发 CAS。投影 3488 的 9 条关系现已达到 AFTER，但 SQL 仍 FAILED_CLOSED，空间 4399 没有权限模式或空间关系。116 的 owner 文件 SHA256 为 `1661bddd649c913c9ed4af1a3d1527d4bbd4b3fb23846aa878009d3eaf8451ad`；发版线已经包含 `27a0a96156` 的串行修复，不能把源码修复当作现场已部署。

本次保留上述串行算法，修复外围恢复闭环：

- `SpaceCopyAccess` 允许未初始化副本的真实创建者访问原复制任务；要求副本创建标识、原 Job/Plan 校验和当前源空间创建者/upload_file 资格。恢复不会授予通用目标 edit；已初始化副本仍走原 edit 检查，条目继续按 visible 脱敏。
- 当前源配置变化仍可读取任务状态，但恢复执行必须重新通过原冻结计划检查；撤权、换创建者、错租户或错目标继续拒绝。
- 后台详情在 25008 / state=0 / state=2 时显示复制任务，不依赖配置页签权限成功；沿既有 HTTP 任务详情/重试入口恢复原副本，刷新当前 scope。
- 弹窗遇到 25002/25008/25009 保留原确认信息；仅 18087/18088 清除计划并重新预检，避免错误重试产生新副本。空复制仍沿用原同步确认，不引入新的任务/接口。

验证结果：

- 复制/索引、API 与 Worker 互斥、任务派发、F048 投影与 Owner 回归：77 passed。
- 新增 HTTP 路由回归通过原处理路由查询失败任务、验证源撤权拒绝、重试同一 Job，断言只保留一个任务且原副本进入 COPYING；数据库和权限投影账本使用原生 SQLite，OpenFGA/索引为传输替身，登录与管理域边界由测试夹具提供，不计完整部署 E2E。
- FAILED_CLOSED 回归改为通过 `SpaceCopyAccess` 的公开查询与重试入口恢复，保留原投影 ID。相同用例替换回旧 `_target` 实现时在 25008 处失败；新实现通过。另覆盖非创建者、源撤权和来源版本变化后只读/拒绝重放。
- 前端 54 passed：完整详情页在 25008 时展示任务、定向重试原任务并刷新成功；25002/25008/25009 原确认复用、18087/18088 重新预检；原任务进度与管理页签回归。
- 前端全量 lint/typecheck、三语言一致性、Ruff 和 arch-guard 通过。本轮未新增迁移、依赖或后端契约。

七维复审：边界、权限、并发、信息披露、测试、风格、文档均 PASS。现场 4399 的任务、权限及数据保持只读，未部署或恢复；真实双数据库并发及完整中间件业务 E2E 仍由环境验收覆盖。


## 2026-11-17 确认接口异步化、初始化锁复用与状态展示

修复基线：`68401498a1`。用户已在本聊天确认复制在后台执行、关闭弹窗/刷新后仍可发现副本并查看阶段、失败复用原任务、完成恢复正常空间的方案；需求与设计同步于F118 AC-124至126及design §5.3。

### 根因及现场边界

116源3439的副本4408在15:19:22创建，任务83196932-6ee9-4d17-8889-cbe2a9fcdcfa共10项，成功0、失败10，目标state=0。15:21:12 Worker堆栈为 `_logical_target` 持目标行锁 → `_initialize` → KnowledgeRag模型读取 → 新session → SourceOwner再次FOR UPDATE目标行。数据库锁超时为50秒，Worker该次耗时101.8秒。API确认提交任务后也同步运行相同初始化，所以既延迟响应又可与Worker竞争。

只读MySQL验证：两独立连接中第一条锁定4408，第二条设置仅本连接1秒等待后收到1205（1.002秒）；同一事务重复锁定成功（0.63毫秒）。仅SELECT/FOR UPDATE，连接最后全部回滚；未写业务记录、部署或重试任务。这个实验验证锁行为，不代表完整复制验收。

### 最终改动

- 新复制含空空间统一创建原space_copy任务。确认返回accepted；重试仅校验冻结输入并提交原重试回执。历史无任务空复制计划保留兼容完成路径。
- Worker先领取租约，重复投递在初始化前退出；启动异常用领取的原租约登记失败。空间权限投影仍逐资源按原SQL锁串行。Milvus及ES初始化都通过reference_session复用该事务的模型校验，不绕过引用验证。
- 新GET `/api/v1/knowledge/space/copy/tasks`按当前租户和实际创建者分页发现state=0/2原副本，每项重验原Job/Plan与当前来源资格，仅返回名称、阶段和汇总；未初始化文件明细保持为空。普通文件/空间授权入口不由此放行。
- 管理端侧栏补入未就绪副本，显示复制中/失败，复用同一进度和原任务重试。详情优先显示准备/初始化阶段，文件阶段显示计数；关闭弹窗或刷新后可重新发现。初始化期间不发普通详情/文件请求。完成后刷新正常空间并在当前详情提示完成；查询缓存按身份、租户、管理域隔离。
- 零文件失败任务可按原任务恢复；没有新表、依赖或权限模型。QA参考用例187至192保持待执行，不混填本地测试结果。

### 验证与七维复审

- 后端11个相关复制、任务内核、派发、元数据、移动重试/ready模块：168 passed；新增零文件失败/重试/完成路径另行验证通过。
- 前端4套侧栏、详情、复制弹窗和管理视图：64 passed，覆盖刷新发现初始化副本、关闭文件内容入口、失败状态、原job_id重试和完成回到正常文件。
- 本地ASGI HTTP经过实际路由、SQL及权限投影账本；登录/管理域为夹具，OpenFGA与索引为传输替身，不计真实中间件或浏览器全链路E2E。
- 模型读取回归经过实际KnowledgeRag的两种初始化入口，校验传入持锁session；另验证租约先领取、重复投递不启动初始化、失败不滞留running、其他创建者/错租户/来源撤权不能发现任务。
- 前端全量lint/typecheck、三语言一致性、Ruff、arch-guard、diff检查通过。

| Dimension | High | Medium | Low | Status |
| --- | ---: | ---: | ---: | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

**Overall: PASS（本次差异）**。116部署、4408原任务恢复、真实MySQL/DM8+OpenFGA/MinIO/ES/Milvus整链和浏览器人工验收仍未执行，由T1048跟踪；本次不修改现场业务数据。
