# 任务拆分 Tasks: 知识空间内容统计索引重设计

## 阅读摘要
- 本文档用于指导 Agent 按任务实现文件快照覆盖写、预览日汇总、可恢复准实时投影、看板口径调整和受保护索引重建。
- 每个任务必须保持在声明边界内；不得直接执行真实索引删除，除非完成 dry-run 并获得单独最终确认。
- task metadata 字段保持英文固定格式，便于 Agent 稳定读取。
- 本任务计划不引用项目中已有 SDD spec。

## 元信息 Metadata
- Feature ID: `051-knowledge-space-content-index-redesign`
- Status: `implemented`
- Related requirements: `specs/051-knowledge-space-content-index-redesign/requirements.md`
- Related design: `specs/051-knowledge-space-content-index-redesign/design.md`
- Created: `2026-08-03`
- Updated: `2026-08-03`

## 任务格式 Task Format

Every implementation task must include:
- Checkbox and task ID.
- Requirement ID.
- Acceptance criterion ID when behavioral.
- Verification method or verification ID.
- Boundary when scope-sensitive or parallel-safe.

任务按共同可观察行为组织为八个任务。实现必须先完成测试契约，再修改生产逻辑；同一代码状态下的成功验证证据应复用。

## 阶段 1：测试契约与核心模型

- [x] T001 先更新知识空间内容索引回归测试，锁定双粒度文档契约
  - Done when: 测试明确断言文件 `_id=str(file_id)`、预览日 ID、UTC+8 日期、原子累计、维度冻结、失败无重试、清理范围、无 `tenant_id` 且不写入重复通用用户上下文字段；测试在旧实现上呈现与新行为对应的失败。
  - _Requirements: REQ-001, REQ-002, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-004-01, AC-REQ-006-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-03, V-AC-REQ-001-04, V-AC-REQ-002-01, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-002-05, V-AC-REQ-004-01, V-AC-REQ-006-03_
  - _Depends: none_
  - _Boundary: tests only: `test/test_knowledge_space_content_telemetry.py`_

- [x] T002 实现文件快照模型和预览日汇总原子更新
  - Done when: mapping 与模型区分 `file`/`preview_daily`；索引显式设置 `refresh_interval=1s`；文件快照用文件 ID 覆盖；预览从当前快照创建日汇总并只原子递增计数且不逐条强制 refresh；旧预览事件、viewer/event 字段和预览 Redis 重试入口已移除。
  - _Requirements: REQ-001, REQ-002, REQ-004, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-004-01, AC-REQ-008-02, AC-REQ-008-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-002-01, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-002-05, V-AC-REQ-004-01, V-AC-REQ-008-02_
  - _Depends: T001_
  - _Boundary: `bisheng/telemetry/domain/mid_table/knowledge_space_content.py`_

## 阶段 2：文件同步与并发协调

- [x] T008 先增加准实时队列、租约恢复和 owner lock 回归测试
  - Done when: 使用可控时钟和 fake Redis/ES 覆盖 pending 原子 claim、处理期间同 ID 再入队、成功 ack 只清 processing、失败不 ack、processing 正常续租、崩溃租约 5 分钟内恢复、owner 续租/释放、非 owner 拒绝、失锁停止、刷新设置和规定观测字段；旧实现应在关键竞态断言上失败。
  - _Requirements: REQ-006, REQ-008_
  - _Acceptance: AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-006-05, AC-REQ-006-06, AC-REQ-008-01, AC-REQ-008-03, AC-REQ-008-04, AC-REQ-008-05_
  - _Verification: V-AC-REQ-006-01, V-AC-REQ-006-03, V-AC-REQ-006-05, V-AC-REQ-006-06, V-AC-REQ-008-01, V-AC-REQ-008-02, V-AC-REQ-008-04, V-AC-REQ-008-05_
  - _Depends: T001_
  - _Boundary: tests only: `test/test_knowledge_space_content_realtime.py` and directly required telemetry fakes_

- [x] T003 调整文件增量、全量同步和删除路径
  - Done when: Redis Cluster 同 slot 的 pending/processing 队列通过 Lua 原子 claim/ack/reclaim；处理期间同 work item 再入队不会被旧 ack 删除；过期租约由 60 秒检查任务恢复；全量、增量和重建使用可续租 owner lock；任一工作项均重读 MySQL 当前状态，有效时覆盖、无效时只删除 `file`；任务输出完整延迟/积压字段并在异常条件标记 degraded。
  - _Requirements: REQ-001, REQ-002, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-001-03, AC-REQ-001-04, AC-REQ-002-04, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-006-05, AC-REQ-006-06, AC-REQ-007-05, AC-REQ-008-01, AC-REQ-008-04, AC-REQ-008-05_
  - _Verification: V-AC-REQ-001-03, V-AC-REQ-001-04, V-AC-REQ-002-04, V-AC-REQ-006-01, V-AC-REQ-006-03, V-AC-REQ-006-05, V-AC-REQ-006-06, V-AC-REQ-007-05, V-AC-REQ-008-01, V-AC-REQ-008-04, V-AC-REQ-008-05_
  - _Depends: T002, T008_
  - _Boundary: `bisheng/telemetry/domain/mid_table/knowledge_space_content.py`, `bisheng/worker/telemetry/mid_table.py`, `bisheng/core/config/settings.py` and directly related telemetry tests_

- [x] T007 先补生命周期触发测试，再实现更新、删除、恢复和版本变化后的完整入队
  - Done when: 参数化测试和实现覆盖文件属性/标签变化、单个/批量/文件夹级联删除、回收站删除/恢复/冲突替换、主版本切换和版本删除；只在业务状态成功且可读后入队实际受影响 ID；失败或回滚不提前入队，入队失败有完整日志且不回滚业务。
  - _Requirements: REQ-001, REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04, AC-REQ-007-05_
  - _Verification: V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-03, V-AC-REQ-007-04, V-AC-REQ-007-05_
  - _Depends: T003_
  - _Boundary: `bisheng/knowledge/domain/services/knowledge_space_service.py`, `bisheng/knowledge/domain/services/knowledge_recycle_service.py`, `bisheng/knowledge/domain/services/knowledge_version_service.py` and directly related tests only_

## 阶段 3：看板聚合与权限范围

- [x] T004 先更新数据集和 scope filter 测试，再调整看板配置
  - Done when: 测试和实现证明文件指标只查 `file`、预览指标为 `preview_daily` 的 `sum(preview_count)`；知识空间 admin 无 tenant filter、部门管理员只有 space filter；QA/参与度租户行为不变。
  - _Requirements: REQ-003, REQ-004_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-003-03, V-AC-REQ-004-02_
  - _Depends: T002_
  - _Boundary: `bisheng/telemetry_search/domain/init_dataset.py`, `bisheng/telemetry_search/domain/models/dashboard_dataset.py`, `bisheng/telemetry_search/domain/services/component.py`, `bisheng/telemetry_search/domain/services/dashboard.py`, `test/test_realtime_dashboard.py`_

## 阶段 4：受保护索引重建能力

- [x] T005 为重建脚本先增加 dry-run、确认保护和调用编排测试
  - Done when: 测试覆盖默认只读、错误确认拒绝、精确索引删除调用、`refresh_interval=1s`、旧/新队列状态、owner lock、建索引/全量重建编排、失败返回非零和结果报告；测试不连接或删除真实 ES。
  - _Requirements: REQ-005, REQ-006, REQ-008_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-06, AC-REQ-008-03, AC-REQ-008-04, AC-REQ-008-05_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-03, V-AC-REQ-005-05, V-AC-REQ-006-01, V-AC-REQ-006-06, V-AC-REQ-008-02, V-AC-REQ-008-04, V-AC-REQ-008-05_
  - _Depends: T003_
  - _Boundary: tests only for rebuild command_

- [x] T006 实现重建脚本和运行说明，但不执行真实删除
  - Done when: 脚本默认 dry-run，只接受精确索引确认，报告旧/新队列与 refresh 设置，按设计使用 owner lock、删除、以 `refresh_interval=1s` 建索引、重建、报告并释放后处理 pending；README 明确部署前提、不可回滚风险、SLO 降级、预检和运行后验证。
  - _Requirements: REQ-005, REQ-006, REQ-008_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-06, AC-REQ-008-03, AC-REQ-008-04, AC-REQ-008-05_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-03, V-AC-REQ-005-05, V-AC-REQ-006-01, V-AC-REQ-006-06, V-AC-REQ-008-02, V-AC-REQ-008-04, V-AC-REQ-008-05_
  - _Depends: T005_
  - _Boundary: `scripts/rebuild_knowledge_space_content_stat.py`, `scripts/README.md`; no real Elasticsearch mutation_

## 阶段 5：验证检查点

完成 T001-T008 后创建或更新 `verification.md`，按当前代码状态记录一次定向测试、一次相关模块回归、一次 ruff 检查、一次重建脚本 dry-run，以及部署后文件 30 秒/预览 5 秒的人工计时证据。真实索引清空不属于默认实现批次，必须等待运行时预检和单独最终确认。

建议验证命令：

```bash
cd src/backend
uv run pytest test/test_knowledge_space_content_telemetry.py -q
uv run pytest test/test_knowledge_space_content_realtime.py -q
uv run pytest test/test_realtime_dashboard.py -q
uv run pytest \
  test/knowledge/test_knowledge_space_content_projection_events.py \
  test/knowledge/test_knowledge_recycle_bin.py \
  test/knowledge/test_knowledge_version_service_set_primary.py \
  test/knowledge/test_knowledge_version_service_delete.py -q
uv run ruff format \
  bisheng/telemetry/domain/mid_table/knowledge_space_content.py \
  bisheng/worker/telemetry/mid_table.py \
  bisheng/knowledge/domain/services/knowledge_space_service.py \
  bisheng/knowledge/domain/services/knowledge_recycle_service.py \
  bisheng/knowledge/domain/services/knowledge_version_service.py \
  bisheng/core/config/settings.py \
  bisheng/telemetry_search/domain/init_dataset.py \
  bisheng/telemetry_search/domain/services/dashboard.py \
  scripts/rebuild_knowledge_space_content_stat.py \
  test/test_knowledge_space_content_telemetry.py \
  test/test_knowledge_space_content_realtime.py \
  test/test_realtime_dashboard.py \
  test/knowledge/test_knowledge_space_content_projection_events.py \
  test/knowledge/test_knowledge_recycle_bin.py \
  test/knowledge/test_knowledge_version_service_set_primary.py \
  test/knowledge/test_knowledge_version_service_delete.py
uv run ruff check \
  bisheng/telemetry/domain/mid_table/knowledge_space_content.py \
  bisheng/worker/telemetry/mid_table.py \
  bisheng/knowledge/domain/services/knowledge_space_service.py \
  bisheng/knowledge/domain/services/knowledge_recycle_service.py \
  bisheng/knowledge/domain/services/knowledge_version_service.py \
  bisheng/core/config/settings.py \
  bisheng/telemetry_search/domain/init_dataset.py \
  bisheng/telemetry_search/domain/services/dashboard.py \
  scripts/rebuild_knowledge_space_content_stat.py \
  test/test_knowledge_space_content_telemetry.py \
  test/test_knowledge_space_content_realtime.py \
  test/test_realtime_dashboard.py \
  test/knowledge/test_knowledge_space_content_projection_events.py \
  test/knowledge/test_knowledge_recycle_bin.py \
  test/knowledge/test_knowledge_version_service_set_primary.py \
  test/knowledge/test_knowledge_version_service_delete.py
```

## 覆盖矩阵 Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..04 | T001, T002, T003 | V-AC-REQ-001-01, V-AC-REQ-001-03, V-AC-REQ-001-04 |
| REQ-002 | AC-REQ-002-01..05 | T001, T002, T003 | V-AC-REQ-002-01, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-002-05 |
| REQ-003 | AC-REQ-003-01..04 | T004 | V-AC-REQ-003-01, V-AC-REQ-003-03 |
| REQ-004 | AC-REQ-004-01..04 | T001, T002, T004 | V-AC-REQ-004-01, V-AC-REQ-004-02 |
| REQ-005 | AC-REQ-005-01..05 | T005, T006 | V-AC-REQ-005-01, V-AC-REQ-005-03, V-AC-REQ-005-05 |
| REQ-006 | AC-REQ-006-01..06 | T001, T003, T005, T006, T008 | V-AC-REQ-006-01, V-AC-REQ-006-03, V-AC-REQ-006-05, V-AC-REQ-006-06 |
| REQ-007 | AC-REQ-007-01..05 | T003, T007 | V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-03, V-AC-REQ-007-04, V-AC-REQ-007-05 |
| REQ-008 | AC-REQ-008-01..05 | T002, T003, T005, T006, T008 | V-AC-REQ-008-01, V-AC-REQ-008-02, V-AC-REQ-008-04, V-AC-REQ-008-05 |

## 任务质量门 Task Quality Gate
- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] Tasks sharing one behavior or command use a verification batch instead of duplicate verification tasks.
- [x] Test work covers distinct outcomes/risks and does not duplicate the same behavior across test layers.
- [x] No task implements work outside requirements or design.

## 实现记录 Implementation Notes
- 已实现文件快照覆盖写、预览日原子累计、leased queue、owner lock、生命周期触发、看板聚合和受保护重建入口。
- 已完成自动化定向验证、只读 dry-run、静态检查和架构守卫；证据见 `verification.md`。
- 未执行真实索引删除或重建；该不可逆操作仍需审核 dry-run 后单独最终确认。
- 文件 30 秒和预览 5 秒可见性需要部署新版本并完成重建后在运行环境人工计时，当前不声称已验证。
