# 知识库任务精简：执行计划

## 元信息 Metadata

- Feature ID: `knowledge-task-consolidation`
- Status: `local-verified`
- Related requirements: `requirements.md`
- Related design: `design.md`
- Created: `2026-09-23`
- Updated: `2026-09-23`

## 执行顺序

实际按 T001 → T002 → T003 → T004 串行实施。本清单勾选代表本地代码与回归完成，不代表真实服务联调或部署完成；相关限制见 verification.md。

| 批次 | 目标 | 可观察收益 | 主要风险 |
|---|---|---|---|
| T001 | 推荐池准备和重建合并 | 正常每次租户重建少一次消息 | generation 重试、重投递、并发激活 |
| T002 | 删除标题旧任务入口 | 少一个兼容入口 | 旧消息与路由残留，首次/重试区别 |
| T003 | 统一热搜入口 | 少一个重复任务定义 | 手动/定时失败策略与返回 task_name |
| T004 | 推荐投影统一批次 | 单一消费入口、去重、有界事务 | 更新/删除版本、部分批次失败 |

## 实施任务

- [x] T001 合并推荐池准备与重建，保护同一请求版本。
  - 实施前记录当前投递链与相关测试基线；针对重试/晚完成/重投递补回归。
  - 在既有 Redis 仓储增加原子请求上下文领取与读取，先完成并发和失败边界验证。
  - 唯一任务串行 await 准备和重建，调整配置变更生产者、普通重建 helper、fanout 映射及注册。
  - Done when: 正常租户路径一次投递；失败重试与同消息重投递不抢占新 generation；配置变化和不完整池无法激活；不增加 SQL Schema 或依赖。
  - _Requirements: REQ-001, REQ-005_
  - _Acceptance: AC-001, AC-002, AC-003, AC-012_
  - _Verification: V-001, V-005；主要文件 test_portal_recommendation_worker.py、test_portal_recommendation_redis_repository.py，真实 Redis 原子性另记录_
  - _Depends: none_
  - _Boundary: 推荐池 Worker、请求上下文 Redis 仓储、对应生产者/注册和测试；不改推荐算法_

- [x] T002 删除标题 Celery 兼容入口及路由引用。
  - 先完整检索代码、配置模板、注册和测试；仅删除任务包装及独有 import。
  - 更新旧包装测试，保留标题/别名普通函数测试及首次解析失败继续、重试不提取标题的回归。
  - Done when: 没有旧标题任务的活动引用，正式解析的交付跟踪与路由保持正确。
  - _Requirements: REQ-002, REQ-005_
  - _Acceptance: AC-004, AC-005, AC-012_
  - _Verification: V-002, V-005；test_file_title_worker.py、test_knowledge_file_parse_lifecycle.py、test_knowledge_parse_processing_lease.py、test_knowledge_parse_queue_routing.py_
  - _Depends: none_
  - _Boundary: 标题任务包装、任务注册、精确路由模板、解析相关测试；不删除普通标题函数_

- [x] T003 统一热搜租户重建任务及管理接口。
  - 两类生产者传递 trigger 和租户 header，采用同一个重建任务名。
  - 保留 scheduled 与 manual 的既有失败策略，更新 API 返回 task_name。
  - Done when: 同一租户互斥锁仍有效，管理员权限和返回结构不变，两种来源的任务名、重试行为均有证据。
  - _Requirements: REQ-003, REQ-005_
  - _Acceptance: AC-006, AC-007, AC-012_
  - _Verification: V-003, V-005；test_portal_hot_search_worker.py、test_portal_hot_search_api.py_
  - _Depends: none_
  - _Boundary: 热搜 Worker、管理 service、注册和定向测试；不改热搜生成或排序算法_

- [x] T004 统一推荐投影批次及调用内去重。
  - 回归先锁定源时间推导版本、显式版本、删除保护和失败回滚；不新建通用聚合器。
  - 单条/批量 helper 适配 events 消息，去除完全相同事件，每 100 条拆批，保持非等价事件顺序。
  - 核对知识空间和审批生产者；已有列表调用继续合批，单文件解析仍立即发单元素批次。
  - 删除单条 Celery 注册；保留资源级刷新、周期校准和既有投递失败日志。
  - Done when: 空批零消息、101 条非重复事件两批、单条普通更新版本不变；删除/乱序/重试结果正确；失败批次不撤销已成功批次。
  - _Requirements: REQ-004, REQ-005_
  - _Acceptance: AC-008, AC-009, AC-010, AC-011, AC-012_
  - _Verification: V-004, V-005；test_portal_recommendation_worker.py、test_portal_recommendation_projection.py 及实际受影响生产者测试_
  - _Depends: T001（同一 Worker 文件和注册落点，减少冲突）_
  - _Boundary: 推荐投影任务/helper、必要生产者参数和测试；不改审批业务、资源分页、全文/统计任务_

## 验证与交付检查点

- 每批完成后将命令、代码状态、实际结果写入实施阶段的 verification.md，复用同批证据，不按验收条目重复跑相同命令。
- 最终运行受影响测试并集一次、git diff --check、注册/模板一致性检查；未改变的无关全量测试不强制执行。
- V-006 发布步骤作为交付审阅项，映射 AC-013，不创建自动部署任务。真实依赖与生产切换未授权时标为 NOT_RUN / MANUAL_REQUIRED。
- 本地代码完成与生产生效分别报告；本计划不授权 purge、数据库操作或外部发布。

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks / Checkpoint | Verification |
|---|---|---|---|
| REQ-001 | AC-001, AC-002, AC-003 | T001 | V-001 |
| REQ-002 | AC-004, AC-005 | T002 | V-002 |
| REQ-003 | AC-006, AC-007 | T003 | V-003 |
| REQ-004 | AC-008, AC-009, AC-010, AC-011 | T004 | V-004 |
| REQ-005 | AC-012, AC-013 | T001–T004；交付检查点 | V-005, V-006 |

## 任务质量门

- [x] 每个任务均有需求、验收、验证、依赖与边界。
- [x] 所有验收标准由任务或交付检查点覆盖。
- [x] 测试按业务结果和风险分组，无独立重复跑测试任务。
- [x] 任务未扩展到发布、队列清理或其他知识库维护任务。

## 实际偏差记录

- 2026-09-23：本期使用仓库现有 specs/ 下 requirements/design/tasks 三文件形式；用户当前明确要求规划，先前已完成范围分析。本轮不创建分支、不实施代码、不执行发布；实施授权在规划交付后另行取得。
- 2026-09-23：进一步核对发现部分批量调用已存在，故不承诺所有批量业务进一步减少消息；超大列表切分作为有界处理收益单独验收。
- 2026-09-23：用户授权实施后完成四批本地改动，最终相关回归 139 项通过。生产者普通 helper 的接口保持，因此未修改知识空间/审批业务文件。
- 2026-09-23：本机无 redis-server/valkey-server，Docker daemon 不可连接；原子脚本以 fakeredis + Lupa 实际执行 Lua 进行本地验证。真实 Redis/Broker 与 MySQL/DM8 联调保留 MANUAL_REQUIRED，不将其记为已通过。
