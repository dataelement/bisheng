# 实施任务 Tasks: 知识空间内容统计数据集重建

## 元信息 Metadata

- Feature ID: `055-knowledge-space-content-stat-rebuild`
- Status: `implementation-awaiting-destructive-confirmation`
- Inputs: `requirements.md`, `design.md`
- Created: `2026-08-20`
- Updated: `2026-08-20`
- Execution gate: 代码实施确认已满足；T014 删除并重建索引仍需基于 dry-run 结果单独确认

## 执行原则

- 严格限制在 `REQ-001` 至 `REQ-007`；发现新增口径先更新规格，不直接扩范围。
- 先补回归测试或契约测试，再修改对应实现。
- 保留工作区现有无关改动，不格式化无关文件。
- 破坏性索引重建不属于普通代码实现步骤；完成代码验证后必须单独展示 preflight 并再次确认。
- 后端定向测试从 `src/backend` 目录使用 `uv run pytest ...`。

## Phase 1：数据契约与组织解析

### [x] T001 建立新记录契约和 Mapping 测试

_Requirements: REQ-001, REQ-004, REQ-007_  
_Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-007-05_  
_Verification: V-ORG-SCHEMA-001_  
_Depends: none_  
_Boundary: 仅调整内容统计记录模型、序列化与新索引 Mapping，不接入业务事件。_

- 修改/新增测试，先固定：
  - `file`、`preview_daily`、`download_daily`、`favorite_daily` 的字段集合；
  - 8 个组织名称字段为 `keyword`；
  - `favorite_count` 为 `long`；
  - 无旧组织字段、组织 ID 和 `tenant_id`；
  - 可选字段序列化时被省略。
- 重构 `KnowledgeSpaceContentRecord`，新增三个日统计记录模型和公共维度常量。
- 修改 `KnowledgeSpaceContentStat._mappings`，删除旧 Mapping，新增组织和收藏字段。
- 验证：
  - `uv run pytest test/test_knowledge_space_content_telemetry.py -q`
- 覆盖：`REQ-001`、`REQ-004`、`REQ-007`；`V-ORG-SCHEMA-001`。
- 依赖：无。

### [x] T002 实现统一四级组织和日统计 ID 解析器

_Requirements: REQ-001, REQ-002, REQ-004, REQ-007_  
_Acceptance: AC-REQ-001-03, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-004-02, AC-REQ-007-06_  
_Verification: V-ORG-RESOLVE-001, V-ORG-NAME-GROUP-001_  
_Depends: T001_  
_Boundary: 只实现纯维度解析和稳定 ID，不查询数据库或写 ES。_

- 新增 `src/backend/bisheng/telemetry/domain/mid_table/knowledge_space_content_dimensions.py`。
- 先新增参数化单测，覆盖完整四级、科室起点、班组下级、缺层、无起点、同名组织。
- 实现按路径和 `org_level` 解析名称；班组固定取公司向下首个 `squad`。
- 实现固定字段集合、JSON `null` 缺失编码和 SHA-256 日统计 ID。
- 建议测试落点：`src/backend/test/telemetry/test_knowledge_space_content_dimensions.py`。
- 验证：
  - `uv run pytest test/telemetry/test_knowledge_space_content_dimensions.py -q`
- 覆盖：`REQ-001`、`REQ-002`、`REQ-004`、`REQ-007`；`V-ORG-RESOLVE-001`、`V-ORG-NAME-GROUP-001`。
- 依赖：`T001`。

### [x] T003 改造五类空间的文件快照构建

_Requirements: REQ-003, REQ-005_  
_Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-005-01, AC-REQ-005-05_  
_Verification: V-ORG-OWNERSHIP-001, V-ORG-REFRESH-001_  
_Depends: T002_  
_Boundary: 只改当前 file 快照构建与覆写，暂不接入日统计事件。_

- 为当前批量构建补充五类空间参数化测试：公共库、部门库、科室库、团队库、个人库。
- 在 Worker 查询层批量加载：
  - 上传人主组织；
  - 团队创建者/个人空间 owner 主组织；
  - 部门/科室绑定；
  - 路径涉及的组织节点和唯一公司节点。
- 使用 `T002` 解析器构建两套相互独立的组织名称。
- 将文件写入固定为 `_id=str(file_id)` + `exclude_none=True` 覆盖。
- 保留现有有效文件判断和所有已存在文件生命周期触发点。
- 验证：
  - `uv run pytest test/telemetry/test_knowledge_space_content_dimensions.py test/test_knowledge_space_content_telemetry.py -q`
- 覆盖：`REQ-003`、`REQ-005`；`V-ORG-OWNERSHIP-001`。
- 依赖：`T002`。

## Phase 2：事件快照、日统计和收藏次数

### [x] T004 建立带事件快照的可重试投影基础设施

_Requirements: REQ-004, REQ-006, REQ-007_  
_Acceptance: AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-007-05, AC-REQ-007-06_  
_Verification: V-ORG-EVENT-SNAPSHOT-001, V-ORG-REPLAY-001, V-FAVORITE-DAILY-001_  
_Depends: T002, T003_  
_Boundary: 只建立事件 Schema、可靠队列、原始事件幂等写和日统计投影，不接具体业务入口。_

- 先补队列、lease、重试和并发幂等测试。
- 扩展门户事件 Schema，加入 `content_stat_schema_version`、日期、daily ID 和完整快照。
- 为遥测服务新增 Worker 专用严格写入口：显式 `event_id`、ES `_id=event_id`、失败抛错；不改变现有普通 `log_event_sync` 行为。
- 在 `KnowledgeSpaceContentStat` 增加独立事件 payload hash、pending/processing zset、claim/ack/reclaim 和状态统计。
- 新增事件 Worker：原始事件确定性写入 → 查询 daily ID 绝对数量 → scripted upsert 单调最大值 → ack。
- 新增 `REPLAY_FLOOR_KEY`，事件消费和手工重放都过滤旧起点。
- 将事件 lease 恢复并入每分钟恢复任务；注册 Worker import。
- 建议测试落点：
  - `src/backend/test/telemetry/test_knowledge_space_content_event_projection.py`
  - `src/backend/test/test_knowledge_space_content_realtime.py`
- 验证：
  - `uv run pytest test/telemetry/test_knowledge_space_content_event_projection.py test/test_knowledge_space_content_realtime.py -q`
- 覆盖：`REQ-004`、`REQ-006`、`REQ-007`；`V-ORG-EVENT-SNAPSHOT-001`、`V-ORG-REPLAY-001`。
- 依赖：`T002`、`T003`。

### [x] T005 接入成功预览与下载事件

_Requirements: REQ-004, REQ-006_  
_Acceptance: AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03_  
_Verification: V-ORG-EVENT-SNAPSHOT-001, V-ORG-REPLAY-001_  
_Depends: T004_  
_Boundary: 保持现有预览/下载成功范围，只替换内容统计事件生成方式。_

- 先补事件时组织变化和同日拆桶测试。
- 预览成功时重新查询文件、空间和组织权威数据，生成事件快照；不得读取 ES `file` 快照作为维度来源。
- 下载保持当前被计入看板的业务入口和 `source_app` 范围，只替换日统计生成方式，不扩大指标口径。
- 更新预览、下载原始事件，使其携带 schema v2 快照并进入 `T004` 队列。
- 删除旧的直接 `preview_count += 1` 和“按当前文件维度重建下载历史”依赖。
- 确认任何统计异常均被捕获，不改变预览/下载成功响应。
- 验证：
  - `uv run pytest test/test_knowledge_space_content_telemetry.py test/telemetry/test_knowledge_space_content_event_projection.py -q`
- 覆盖：`REQ-004`、`REQ-006`；`V-ORG-EVENT-SNAPSHOT-001`、`V-ORG-REPLAY-001`。
- 依赖：`T004`。

### [x] T006 接入实际成功收藏状态变化

_Requirements: REQ-007_  
_Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04, AC-REQ-007-05, AC-REQ-007-06_  
_Verification: V-FAVORITE-COUNT-001, V-FAVORITE-DAILY-001_  
_Depends: T004, T005_  
_Boundary: 只统计真实新建收藏关系，不改变收藏状态接口或普通客户端遥测语义。_

- 先扩展 `test/knowledge/test_favorite_service.py` 或现有收藏测试，覆盖首次收藏、重复幂等、取消、取消后再收藏。
- 仅在 `_create_favorite_reference` 成功且知识更新时间更新完成后生成 `favorite_daily` 事件。
- existing early return 不生成事件；取消不生成负数或删除历史。
- 收藏事件使用被收藏的源文件/源空间，不使用个人收藏引用文件作为指标文件。
- 普通客户端 `portal_favorite` 遥测不驱动 `favorite_daily`。
- 验证：
  - `uv run pytest test/test_favorite_service.py test/telemetry/test_knowledge_space_content_event_projection.py -q`
- 覆盖：`REQ-007`；`V-FAVORITE-COUNT-001`、`V-FAVORITE-DAILY-001`。
- 依赖：`T004`、`T005`。

## Phase 3：组织变化和最终一致性

### [x] T007 扩展当前快照队列的 `user` 与 `department` 工作项

_Requirements: REQ-005_  
_Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-04, AC-REQ-005-05_  
_Verification: V-ORG-REFRESH-001_  
_Depends: T003_  
_Boundary: 只扩展队列与 Worker 扇出，不修改组织业务事务。_

- 先扩展投影队列测试，覆盖合法 kind、非法 kind、lease、ack、失败重试。
- 新增 `enqueue_user_stat_async`、`enqueue_department_stat_async`。
- Worker 对 `user` 分页查找上传文件及由该用户决定所属组织的团队/个人空间。
- Worker 对 `department` 分页展开子树主组织用户、绑定空间和必要的公共库刷新，再入队 `user/space`。
- 保持一个批次最多处理配置数量，避免大组织变化在请求线程直接扫描全量文件。
- 验证：
  - `uv run pytest test/test_knowledge_space_content_realtime.py test/knowledge/test_knowledge_space_content_projection_events.py -q`
- 覆盖：`REQ-005`；`V-ORG-REFRESH-001`。
- 依赖：`T003`。

### [x] T008 接入组织、主组织和知识库绑定变更触发

_Requirements: REQ-003, REQ-005_  
_Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04_  
_Verification: V-ORG-REFRESH-001_  
_Depends: T007_  
_Boundary: 只在已确认变更入口提交后旁路入队，不改变原业务事务结果。_

- 先为每个真实变更入口补“提交后入队、无变化不入队、入队失败不回滚业务”测试。
- 接入：
  - 部门实际改名；
  - 部门移动；
  - 公司根设置/清空和四级标签重算；
  - 用户主组织实际切换；
  - 部门/科室知识库绑定、重绑、解绑。
- 对重绑增加显式空间刷新，补齐解绑当前缺失触发。
- 不修改既有预览、下载和收藏日记录。
- 建议验证组合：
  - `uv run pytest test/knowledge/test_knowledge_space_content_projection_events.py test/test_knowledge_space_content_realtime.py -q`
  - 以及各被修改 Service 的现有定向测试文件。
- 覆盖：`REQ-005`；`V-ORG-REFRESH-001`。
- 依赖：`T007`。

### [x] T009 将每日全量任务收敛为 file-only 校准

_Requirements: REQ-005, REQ-006_  
_Acceptance: AC-REQ-005-05, AC-REQ-006-04_  
_Verification: V-ORG-REFRESH-001, V-ORG-REBUILD-001_  
_Depends: T003, T007_  
_Boundary: 全量任务只校准 file，不恢复、改写或清理事件日统计。_

- 先修改全量任务测试，断言不会扫描、重建或清理任何日统计。
- 从 `rebuild_knowledge_space_content_file_projection` 移除旧下载原始事件聚合调用。
- 删除或隔离不再使用的“用当前文件维度构造 download_daily”代码，避免后续误调用。
- 全量结果只报告当前文件同步、stale file 删除、收藏引用空间删除和队列状态。
- 用同一数据源分别执行增量与全量构建，断言当前 `file` 快照一致。
- 验证：
  - `uv run pytest test/test_knowledge_space_content_telemetry.py test/test_knowledge_space_content_realtime.py -q`
- 覆盖：`REQ-005`、`REQ-006`；`V-ORG-REFRESH-001`。
- 依赖：`T003`、`T007`。

## Phase 4：看板契约与重建工具

### [x] T010 更新看板数据集指标和维度

_Requirements: REQ-001, REQ-007_  
_Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-007-08_  
_Verification: V-ORG-SCHEMA-001, V-FAVORITE-REGRESSION-001_  
_Depends: T001, T006_  
_Boundary: 只刷新系统数据集 seed，不迁移自定义看板。_

- 先新增数据集 seed 契约测试。
- 删除六个旧组织维度入口，加入 8 个新组织名称维度。
- 新增“收藏次数”指标：`record_type=favorite_daily` + `sum(favorite_count)`。
- 保持总文件数、新增文件数、内容贡献人数、预览次数、下载次数的过滤条件不变。
- 验证数据集刷新对系统数据集生效，不实现自定义看板迁移。
- 建议测试落点：`src/backend/test/telemetry_search/test_knowledge_space_content_dataset.py`。
- 验证：
  - `uv run pytest test/telemetry_search/test_knowledge_space_content_dataset.py test/telemetry_search/test_dashboard_enum_labels.py -q`
- 覆盖：`REQ-001`、`REQ-007`；`V-ORG-SCHEMA-001`、`V-FAVORITE-REGRESSION-001`。
- 依赖：`T001`、`T006`。

### [x] T011 改造安全重建脚本和回放边界

_Requirements: REQ-006, REQ-007_  
_Acceptance: AC-REQ-006-04, AC-REQ-007-07, AC-REQ-007-08_  
_Verification: V-ORG-REBUILD-001, V-FAVORITE-REBUILD-001, V-FAVORITE-REGRESSION-001_  
_Depends: T004, T009_  
_Boundary: 只改脚本与测试；实现阶段不得实际执行 --apply。_

- 先扩展 `test/test_rebuild_knowledge_space_content_stat.py`：
  - preflight 分别统计 `file/preview_daily/download_daily/favorite_daily/portal_engagement_daily`；
  - apply 设置回放起点；
  - 只恢复当前文件；
  - 四类历史不恢复；
  - 新起点之后的待处理事件保留；
  - 确认值错误、锁忙和异常路径不误删。
- 修改脚本报告，明确列出将清空和实际清空的各记录类型数量。
- 重建函数只调用 file-only 全量校准，不读取旧预览、下载或收藏事件。
- 保留精确索引名确认、owner lock、legacy key 白名单清理和最终 reschedule。
- 验证：
  - `uv run pytest test/test_rebuild_knowledge_space_content_stat.py -q`
- 覆盖：`REQ-006`、`REQ-007`；`V-ORG-REBUILD-001`、`V-FAVORITE-REBUILD-001`。
- 依赖：`T004`、`T009`。

## Phase 5：集成验证与交付

### [x] T012 执行定向模块回归和静态检查

_Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007_  
_Acceptance: all acceptance criteria in requirements.md_  
_Verification: all verification IDs in requirements.md_  
_Depends: T001-T011_  
_Boundary: 只验证已确认范围，不运行无关全量测试。_

- 运行一次与最终代码状态对应的定向回归：

```bash
cd src/backend
uv run pytest \
  test/telemetry/test_knowledge_space_content_dimensions.py \
  test/telemetry/test_knowledge_space_content_event_projection.py \
  test/test_knowledge_space_content_telemetry.py \
  test/test_knowledge_space_content_realtime.py \
  test/test_rebuild_knowledge_space_content_stat.py \
  test/test_favorite_service.py \
  test/knowledge/test_knowledge_space_content_projection_events.py \
  test/telemetry_search/test_knowledge_space_content_dataset.py \
  -q
```

- 对实际修改的 Python 文件执行：

```bash
uv run ruff format --check <changed-python-files>
uv run ruff check <changed-python-files>
```

- 运行 `bash scripts/arch-guard.sh`，任何 VIOLATION 必须修复。
- 记录实际命令、通过数、失败数和未覆盖的外部环境限制。
- 覆盖：全部 `V-*` 的代码级证据。
- 依赖：`T001`～`T011`。

### [x] T013 执行 dry-run 并形成破坏性操作检查单

_Requirements: REQ-006, REQ-007_  
_Acceptance: AC-REQ-006-04, AC-REQ-007-07_  
_Verification: V-ORG-REBUILD-001, V-FAVORITE-REBUILD-001_  
_Depends: T011, T012_  
_Boundary: 只读 dry-run，不删除或覆盖索引。_

- 在目标环境只执行 dry-run：

```bash
cd src/backend
PYTHONPATH=./ python scripts/rebuild_knowledge_space_content_stat.py
```

- 保存并人工核对：
  - 关系库有效文件数；
  - 五类现有索引记录数；
  - 当前和 legacy Redis 队列状态；
  - owner lock 可用性；
  - 预计清空数据及不可恢复说明；
  - 维护窗口和回退限制。
- 不在本任务内执行 `--apply`。
- 依赖：`T011`、`T012`。

### [ ] T014 经单独确认后执行实际索引重建和验收

_Requirements: REQ-001, REQ-004, REQ-006, REQ-007_  
_Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-004-04, AC-REQ-006-04, AC-REQ-007-07, AC-REQ-007-08_  
_Verification: V-ORG-SCHEMA-001, V-ORG-REBUILD-001, V-FAVORITE-REBUILD-001, V-FAVORITE-REGRESSION-001_  
_Depends: T013 and explicit destructive-operation confirmation_  
_Boundary: 仅在展示目标环境 preflight 并取得单独确认后执行精确索引重建。_

- **强制暂停点**：向用户展示 `T013` 的实际 preflight，重新确认不可恢复清空影响后才能执行。
- 获得确认后执行：

```bash
cd src/backend
PYTHONPATH=./ python scripts/rebuild_knowledge_space_content_stat.py \
  --apply \
  --confirm-index mid_knowledge_space_content_stat
```

- 验收：
  - `file` 数量与脚本数据源有效文件数一致；
  - 每个文件最多一条 `record_type=file` 且 `_id=file_id`；
  - 旧 `preview_daily/download_daily/favorite_daily/portal_engagement_daily` 均未恢复；
  - 新成功预览、下载、收藏可以生成对应日统计；
  - 当前队列无不可恢复 lease，积压可继续消费；
  - 看板可选择 8 个组织维度和收藏次数。
- 依赖：`T013` + 用户对实际破坏性操作的单独确认。

## 需求追踪矩阵

| Requirement | Tasks |
|---|---|
| `REQ-001` | `T001`, `T002`, `T003`, `T010`, `T012` |
| `REQ-002` | `T002`, `T003`, `T012` |
| `REQ-003` | `T003`, `T008`, `T012` |
| `REQ-004` | `T001`, `T002`, `T004`, `T005`, `T012` |
| `REQ-005` | `T003`, `T007`, `T008`, `T009`, `T012` |
| `REQ-006` | `T004`, `T005`, `T009`, `T011`, `T012`, `T013`, `T014` |
| `REQ-007` | `T001`, `T004`, `T006`, `T010`, `T011`, `T012`, `T014` |

## 实际偏差记录

- `T008` 的组织刷新入口测试落在 `test/telemetry/test_knowledge_space_content_refresh_triggers.py`，并复用组织标签、主组织、绑定和移动 Service 的现有定向测试；计划中的 `test/knowledge/test_knowledge_space_content_projection_events.py` 在项目中不存在，未创建同义重复文件。
- `T012` 对新增核心文件执行 `ruff check` 和 `ruff format --check` 均通过；对所有修改文件执行全文件 `ruff check` 时发现 239 个既有历史规则问题，主要位于本功能未改动的旧代码行。为避免扩大范围，本次使用“新增核心文件 lint + 全部生产改动 `py_compile` + 定向测试 + arch-guard”作为静态验证证据，详见 `verification.md`。
- `T013` 首次 dry-run 发现总记录数比五类已知记录多 5 条，因此补充了未知类型聚合预检。复验确认这 5 条均为旧 `record_type=preview`，并非缺失 `record_type` 的文档。根据暂停条件，`T014` 保持未执行，等待用户明确确认该旧类型随索引一起不可恢复清空。

## 风险与暂停条件

- 如果发现实际下载指标包含当前设计未覆盖的成功入口，暂停 `T005`，先更新调用链清单和设计，不自行扩大统计范围。
- 如果组织变更存在绕过已列 Service 的直接 DAO 写入，记录为偏差并评估是否补入口或依赖每日校准。
- 如果 Redis 无法满足事件 payload/lease 持久化要求，暂停 `T004`，不得退化为只记录日志后丢事件。
- 如果目标环境 dry-run 数量与门户/看板口径不一致，暂停 `T014`，先定位有效文件查询差异。
- 如果实际索引存在未识别的其他 `record_type`，暂停重建并请用户确认，不默认删除未知业务数据。
