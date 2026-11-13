# Tasks: 长期记忆

**关联规格**: [spec.md](./spec.md) · **设计**: [design.md](./design.md)
**版本**: v3.0.0（开发基线）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-11-13 用户确认；同日修订 AC-71、AC-87，移出 AC-11、AC-100 |
| design.md | ✅ 已评审 | 2026-11-13 用户确认第 4 稿；§10 的 V1–V8 待 Wave 0 验证后回写 |
| tasks.md | 🔲 草稿 | 待 `/sdd-review tasks` |
| 实现 | 🔲 未开始 | 0 / 70 完成 |

---

## 开发模式

**按 Wave 组织。** 同一个 Wave 内的任务互不依赖，可并行；Wave 之间按依赖顺序推进。每个 Wave 末尾有一条"Wave 验收"，写明用哪条命令、看到什么输出算完成，供自动化开发时当作完成条件。

**后端 Test-First。** 每对任务先写测试（红）再写实现（绿）。测试放在 `src/backend/test/memory/` 及各接入模块现有的测试目录下，不放 `test/` 根目录。命令的工作目录是 `src/backend/`。

**测试替身。** 标〔测〕的验收标准一律不依赖真实模型、Milvus、ES、MinIO：
- 模型用桩，返回固定的工具调用或固定文本。
- 索引用内存实现的假索引（T014 提供），接口与真实索引一致。
- 对象存储用内存实现的假存储。
- 关系库用测试夹具里的内存 SQLite（`test/conftest.py` 已有先例）。
真实中间件上的集成测试标记为需要中间件，在 CI 的中间件分组里跑。

**判断回归用基线差，不用失败总数。** 本地没有中间件时，后端测试本来就会成块失败。T001 先在未改动的代码上跑一次并保存结果，之后每个 Wave 验收都与它比较：不得出现新的失败。

**验收标准的两类。** spec 里标〔测〕的由本文的测试任务覆盖，每个测试函数在名字或文档字符串里写明所覆盖的 AC 编号。标〔评〕的依赖模型行为，由 Wave 12 的评测集覆盖，不作为任何 Wave 的完成条件。

**设计论证不在这里重复**，指向 design 的决策号。

**禁区。** 实现过程中不得：执行 `git push`；修改 `test/memory/` 与各任务点名的测试文件以外的任何既有测试；新增第三方依赖；改动 `core/vectorstore/`、`knowledge/` 下的检索行为；在 `common/` 或 `core/` 里引用 `memory`。

---

## Tasks

### Wave 0：基线与待验证项

这一 Wave 不写产品代码。每个验证任务用最小实验得出结论，写进 `features/v3.0.0/132-long-term-memory/verification.md`，并把结论回写 design 对应的决策与 §10。结论与 design 现有方案不一致时，停下来请用户确认（SDD-Guide §3）。

- [ ] **T001**: 测试基线与本地运行环境
  **文件**: `features/v3.0.0/132-long-term-memory/verification.md`（新建）
  **逻辑**: 在未改动的分支上跑 `uv run pytest test/ -m "not e2e" -q -p no:cacheprovider`，把通过、失败、报错的测试 id 清单存为 `verification.md` 的"基线"一节（失败清单可放同目录的 `baseline-failures.txt`）。记录运行所需的前置条件（`bisheng/config.yaml` 是否存在、代理环境变量等）。同样记录前端 `pnpm lint`、`pnpm typecheck`（在 `src/frontend/`）的现状。
  **依赖**: 无

- [ ] **T002**: V1 助手工具回调里的脱敏
  **文件**: `verification.md`
  **逻辑**: 读 `bisheng/api/v1/callback.py:472-495`、`:523-545`、`:572-585` 与挂载点 `common/chat/client.py:308-322`。写一个最小测试，注册一个名为 `memory_probe` 的假工具并触发一次调用，确认：回调在 `on_tool_start` 能拿到工具名；`on_tool_end` / `on_tool_error` 里如何关联到同一次调用（`run_id`）；落库的 `category=tool` 行和 `intermediate_steps` 字段里出现了哪些原文。
  **判据**: 给出"在回调处理器里按 `run_id` 识别记忆工具并替换内容"是否可行的结论，以及需要改的确切位置。
  **依赖**: T001

- [ ] **T003**: V2 助手连接的登记回调
  **文件**: `verification.md`
  **逻辑**: 读登录态助手 WebSocket endpoint、`chat_manager.dispatch_client`、`common/chat/client.py:230`、`:361-372`，以及免登录 `public_endpoints/api/endpoints/assistant.py:45` 与开放面 `open_endpoints/api/endpoints/assistant.py:160`。确认三条路径各自如何构造客户端对象，能否只在登录态路径上传入一个可调用对象，且 `ChatClient` 在 `chat_id` 确定或切换时调用它。
  **判据**: 给出注入点与调用点的确切位置；确认免登录与开放面路径不会拿到这个回调。
  **依赖**: T001

- [ ] **T004**: V3 深度研究步骤落库与工作区文件
  **文件**: `verification.md`
  **逻辑**: 读 `linsight/domain/services/stream_event_mapper.py:627-712`、`linsight/domain/models/linsight_execute_task.py:68`、`linsight/api/endpoints/linsight.py:579-615`，以及上下文压缩把历史写成工作区文件的路径（`linsight/domain/utils.py:104-117`、`context_budget.py:144`）和大工具结果卸载路径。确认工具的 `params`、`output` 在哪些位置落库或落文件。
  **判据**: 列出全部落点；对每个落点给出脱敏的切入位置；确认分享链接读取任务详情时走哪个接口。
  **依赖**: T001

- [ ] **T005**: V4 与 V8 工作流节点取 `chat_id`、开关与登记回调
  **文件**: `verification.md`
  **逻辑**: 读 `workflow/graph/graph_engine.py:207-231`、`workflow/nodes/base.py:21-60`、`common/chat/clients/workflow_client.py:97-98`、`:171-179`、`worker/workflow/tasks.py:40-82`、`worker/workflow/redis_callback.py:532-554`。确认：`chat_id` 从哪里进入工作流运行、能否放进 `graph_state`；登录态路径上执行的图是否来自客户端消息；按 `flow_id` 读上线版本的开始节点参数的现成方法；评测与调试运行时 `chat_id` 的取值。
  **判据**: 给出节点取 `chat_id` 与开关的确切实现位置；给出登录态 endpoint 注入登记回调的位置；确认免登录与开放面路径不登记。
  **依赖**: T001

- [ ] **T006**: V5 助手两种执行器下的系统消息注入
  **文件**: `verification.md`
  **逻辑**: 读 `api/services/assistant_agent.py:428-458`、`:548-601`。用桩模型分别在 ReAct 与 function call 两种执行器下跑一轮：在 `trim_messages` 之后向输入插入一条系统消息，确认模型收到的消息序列里包含它，且 `run()` 返回值经处理后 `client.py:393-400` 的切片偏移不受影响。
  **判据**: 两种执行器各给出可行或不可行的结论及注入代码的确切位置。
  **依赖**: T001

- [ ] **T007**: V6 管理端查看会话所用的接口
  **文件**: `verification.md`
  **逻辑**: 读 `src/frontend/platform/src/pages/LogPage/useAppLog/appChatDetail.tsx`、`dailyChatDetail.tsx`、`LabelPage/taskAppChats.tsx` 及它们调用的 API 函数，追到后端端点。列出每个页面读取的表与字段，是否读取 `category=tool` 的行、日常模式消息里的 `events`、深度研究的步骤。
  **判据**: 一张"页面 → 接口 → 返回的含工具内容的字段"对照表。
  **依赖**: T001

- [ ] **T008**: V7 深度研究追问轮的存储与前端轮次标识
  **文件**: `verification.md`
  **逻辑**: 读 `linsight/api/endpoints/linsight.py:174`、`:327-378`、`linsight/domain/utils.py:973-1019`、`linsight/domain/services/workbench_impl.py:345-402`，以及前端 `client/src/components/Linsight/Execution/TaskTurnPanel.tsx`、`ResultPanel.tsx`、`ExecutionFlow.tsx:305`。确认：追问的问题与每一轮的结果存在哪张表的哪个字段，能否按轮取出；前端渲染每一轮时手里有什么标识。
  **判据**: 给出"按轮读取问题与结果"的方法；给出把 `turn_id` 送到前端每一轮面板的途径。
  **依赖**: T001

- [ ] **T009**: 把验证结论回写 design
  **文件**: `features/v3.0.0/132-long-term-memory/design.md`
  **逻辑**: 按 T002–T008 的结论更新决策 6、7、10、11、15、17 与 §4.4、§10；§10 每一项写上结论与日期。任何一项结论推翻了 design 的现有方案，先停下来请用户确认。
  **依赖**: T002, T003, T004, T005, T006, T007, T008

**Wave 0 验收**: `verification.md` 含基线与 V1–V8 八项结论；design §10 每一项都有结论；没有待用户确认而未确认的推翻项。

### Wave 1：基础设施（无测试配对）

- [ ] **T010**: 错误码模块 121 与架构守卫名单
  **文件**: `src/backend/bisheng/common/errcode/memory.py`（新建）、`scripts/arch-guard.sh`、`docs/constitution.md`、`features/v3.0.0/release-contract.md`、`src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`
  **逻辑**: 定义 121 段错误码类（写成 `Code: int = 121NN`），本期至少包含：内容超长、内容含密钥类信息、内容含相对时间、目标条目不存在或状态已变、撤销失败（三种原因各一个码）、租户记忆关闭时禁止新增与编辑、检索不可用、检索数量参数非法、工作流含记忆检索节点而开关关闭。三语文案同批加入并运行 `pnpm locales:build`（在 `src/frontend/`）。把 `memory` 加进 `scripts/arch-guard.sh` 的领域模块名单。回写 C5 表与 release-contract 的"已分配模块编码"。
  **依赖**: T009

- [ ] **T011**: 六张表的 ORM 模型与租户过滤登记
  **文件**: `src/backend/bisheng/memory/domain/models/`（新建，每张表一个文件）、`src/backend/bisheng/core/database/tenant_filter.py`
  **逻辑**: 按 design §4.2 定义 `memory_item`、`memory_session_cursor`、`memory_user_setting`、`memory_turn_record`、`memory_resident_snapshot`、`memory_metric_daily`。JSON 用 `dialect_helpers.JsonType`，长文本用 `LargeText`，`update_time` 用方言辅助。索引按 design §4.2 的"索引要点"。把模型模块登记进 `tenant_filter.py` 的 `_TENANT_AWARE_MODEL_MODULES`。`assistant` 表模型加列 `memory_enabled`（布尔，默认关）。
  **依赖**: T009

- [ ] **T012**: Alembic 迁移
  **文件**: `src/backend/bisheng/core/database/alembic/versions/`（新增一个 revision）
  **逻辑**: 按同目录 `AGENTS.md` 的规范：`down_revision` 取当前唯一 head；只写 DDL；用 `table_exists` / `column_exists` 保证可重入；不写字符集；`assistant.memory_enabled` 带 `server_default`。`downgrade` 删除六张表与该列。运行 `uv run pytest test/ -k alembic_single_head`。
  **回滚**: `downgrade` 可逆，六张表为新增表，无数据迁移。
  **依赖**: T011

- [ ] **T013**: 运行期配置与默认值
  **文件**: `src/backend/bisheng/memory/domain/config.py`（新建）、`src/backend/bisheng/initdb_config.yaml`
  **逻辑**: 定义 `MemoryRuntimeConfig`，从 `settings.aget_from_db("memory")` 读取，缺键时用代码里的默认值（design 决策 19 的表）。`initdb_config.yaml` 增加带注释的 `memory` 段。不改 `config.yaml`。
  **依赖**: T009

- [ ] **T014**: 测试夹具
  **文件**: `src/backend/test/memory/__init__.py`、`src/backend/test/memory/conftest.py`（新建）
  **逻辑**: 提供：内存 SQLite 上建好六张表的会话夹具；假索引（内存实现，支持按租户与用户过滤、可注入"关键词路不可达""向量路不可达"）；假对象存储（可注入读取失败）；桩模型（按脚本返回工具调用或文本）；构造 `MemoryContext` 的工厂；两个租户、两个用户、一个全局超管身份的夹具。
  **依赖**: T011

**Wave 1 验收**: `uv run pytest test/ -k alembic_single_head -q` 通过；`bash scripts/arch-guard.sh` 无 VIOLATION；`cd src/frontend && pnpm check-i18n` 通过；与 T001 基线相比无新增失败。

### Wave 2：核心领域服务（Test-First 配对）

- [ ] **T015**: 内容校验的测试
  **文件**: `src/backend/test/memory/test_guard.py`
  **逻辑**: 覆盖：超过 200 字被拒；类型只接受 fact、preference、experience；密钥类内容被拒（常见密钥前缀与高熵串、18 位身份证号校验位、银行卡号 Luhn 校验、"密码是 / password:" 句式，各至少两个正例两个反例）；含相对时间词（今天、明天、下周二、本月、tomorrow、next week）被拒并返回对应原因码；合法内容通过。
  **覆盖 AC**: AC-12, AC-14, AC-16
  **依赖**: T014

- [ ] **T016**: 内容校验的实现
  **文件**: `src/backend/bisheng/memory/domain/services/guard.py`
  **逻辑**: `SensitiveContentGuard`、长度与类型校验、相对时间检查；每种拒绝返回一个原因码（对应 T010 的错误码）。设计见 design 决策 14 与 §4.1 末段。
  **测试**: T015 全部通过
  **覆盖 AC**: AC-12, AC-14, AC-16
  **依赖**: T015, T010

- [ ] **T017**: 数据访问层隔离的测试
  **文件**: `src/backend/test/memory/test_repository_isolation.py`
  **逻辑**: 用 T014 的身份夹具验证：用户甲读不到用户乙的条目；租户 A 的条目在租户 B 的上下文里读不到；"可见多租户"身份只读到当前租户的条目；全局超管身份只读到自己在当前租户的条目；批量更新与删除只影响当前租户当前用户的行；用户归属从 A 变到 B 再回到 A，A 里的条目先不可读后可读且未被迁移。
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-06, AC-07
  **依赖**: T014

- [ ] **T018**: 数据访问层的实现
  **文件**: `src/backend/bisheng/memory/domain/repositories/item_repository.py`、`setting_repository.py`
  **逻辑**: 条目与用户设置的全部读写方法，签名都接收 `MemoryContext`，查询与写操作显式带 `tenant_id` 与 `user_id`（design 决策 9）。`memory_user_setting` 首次需要时建行，并发建行时捕获唯一键冲突后重读；`rev` 的自增与条目变更在同一事务。
  **测试**: T017 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-06, AC-07
  **依赖**: T017

- [ ] **T019**: 条目写入与状态机的测试
  **文件**: `src/backend/test/memory/test_memory_service_write.py`
  **逻辑**: 覆盖：记下后同一用户立即可读，来源标记含场景、应用、会话与写入方式，应用名称为写入时的快照；更正后新条目有效、旧条目为已被取代并记录取代关系；忘掉后条目不可读；目标不存在或状态已变时更正与忘掉返回失败且不新建；三种撤销各自的结果；三种撤销失败情形（已清空、新条目已被再次取代或删除、已撤销过）；被取代与被删除的条目不出现在列表里；被取代的条目行仍保留；清空后该用户在当前租户的全部行与详情对象都不存在，另一租户与另一用户的不受影响；长正文写成详情对象且条目内容为概括；两个并发写入都保留；索引写入失败时写入仍成功且条目标为待建索引；来源会话被删除（`message_session.is_delete` 置位）后，由它产生的条目仍可读。
  **覆盖 AC**: AC-04, AC-22, AC-24, AC-25, AC-26, AC-44, AC-91, AC-92, AC-93, AC-98, AC-97
  **依赖**: T014

- [ ] **T020**: 条目写入与状态机的实现
  **文件**: `src/backend/bisheng/memory/domain/services/memory_service.py`、`src/backend/bisheng/memory/domain/services/detail_store.py`
  **逻辑**: `write`（remember / correct / forget）、`edit`、`delete`、`clear`、`undo`、`list`。新增是 INSERT；更正与忘掉是带状态条件的 UPDATE，影响行数为 0 即失败。详情对象先写后插行，键为 `memory/{tenant_id}/{user_id}/{item_id}.md`，`item_id` 由应用侧生成。删除是软删除，清空是硬删除（先索引与对象，后行）。每次变更使 `rev` 加一。设计见 design 决策 3、4、5。
  **测试**: T019 全部通过
  **覆盖 AC**: AC-04, AC-22, AC-24, AC-25, AC-26, AC-44, AC-91, AC-92, AC-93, AC-98, AC-97
  **依赖**: T019, T016, T018

- [ ] **T021**: 资格登记与启用判定的测试
  **文件**: `src/backend/test/memory/test_gate.py`
  **逻辑**: 覆盖：没有登记行时 `resolve` 返回空；`open` 新建行时水位初值等于会话当前最大消息 id；同一用户同一租户再次 `open` 不改行（时区变化除外）；租户或用户与已登记不同则置为无资格；`chat_id` 对应的会话属于别人时不登记；启用判定的全部组合（租户开关、我的记忆、助手开关、工作流开关各自开与关）；用户停用时返回空、重新启用后恢复；任一开关关闭后再开，之前的条目仍可读；一轮开始时取得的结果在该轮内不随开关变化。
  **覆盖 AC**: AC-10, AC-40, AC-66, AC-72, AC-73, AC-74, AC-99
  **依赖**: T014

- [ ] **T022**: 资格登记与启用判定的实现
  **文件**: `src/backend/bisheng/memory/domain/services/gate.py`、`src/backend/bisheng/memory/domain/repositories/cursor_repository.py`
  **逻辑**: `MemoryGate.open(chat_id, login_user, timezone)` 与 `resolve(chat_id, scene, app_enabled)`，`MemoryContext` 数据类（含 `tenant_id`、`user_id`、时区、`turn_id`）。登记行的写入规则与并发写语义见 design 决策 6、7；下游以登记行上的租户与用户为准。
  **测试**: T021 全部通过
  **覆盖 AC**: AC-10, AC-40, AC-66, AC-72, AC-73, AC-74, AC-99
  **依赖**: T021, T018

- [ ] **T023**: 常驻记忆的测试
  **文件**: `src/backend/test/memory/test_resident.py`
  **逻辑**: 覆盖：带入的条目数与总字数都不超过上限，先到者生效；到达上限时没有任何条目被截断，未带入的条目仍有效并可被检索；经验类条目不出现在日常模式与助手的常驻文本里；深度研究的带入在常驻之外另含经验类条目且受独立上限约束；带详情的条目只带入概括；文本首行是背景信息说明且每条带记录日期；事件时间已过（按用户时区）的条目不再带入但仍可检索；缓存键随 `rev` 与日期变化，条目变更后下一次读取反映变更；存在很久且从未被读取的条目没有被任何逻辑删除；缓存未命中时写入一行常驻快照。
  **覆盖 AC**: AC-52, AC-53, AC-54, AC-55, AC-56, AC-57, AC-94, AC-96
  **依赖**: T014

- [ ] **T024**: 常驻记忆的实现
  **文件**: `src/backend/bisheng/memory/domain/services/resident.py`
  **逻辑**: `resident(ctx, scene_class)` 与 `experience(ctx)`，渲染文本块，Redis 缓存（键含租户、用户、`rev`、用户时区下的日期、场景类别，TTL 1 小时），缓存未命中时写 `memory_resident_snapshot`。设计见 design 决策 8。
  **测试**: T023 全部通过
  **覆盖 AC**: AC-52, AC-53, AC-54, AC-55, AC-56, AC-57, AC-94, AC-96
  **依赖**: T023, T020

- [ ] **T025**: 索引与检索的测试
  **文件**: `src/backend/test/memory/test_search.py`
  **逻辑**: 覆盖：只返回当前用户当前租户的有效条目；返回内容、类型、记录时间、事件时间，并可按 id 取回详情全文；待建索引的条目被追加进结果；一路不可达时用另一路并计一次降级；两路都不可达时抛检索不可用；租户未配置 embedding 时只走关键词且不计失败；索引里残留已删除条目的 id 时回表后不返回；详情读取失败时返回条目自身内容并计一次失败；过滤条件只由一个函数生成（断言两路检索收到的过滤条件都含租户与用户）。
  **覆盖 AC**: AC-58, AC-59, AC-61, AC-62
  **依赖**: T014

- [ ] **T026**: 索引与检索的实现
  **文件**: `src/backend/bisheng/memory/domain/services/index.py`、`src/backend/bisheng/memory/domain/services/search.py`
  **逻辑**: 索引的写入、删除、检索、重建；唯一的过滤条件生成函数；倒数排名融合；回表校验；embedding 调用 3 秒超时；ES 索引 `bisheng_memory_item`，Milvus collection `bisheng_memory_item_{embedding_model_id}`。不复用 `core/vectorstore/multi_retriever.py`。设计见 design 决策 5、12。
  **测试**: T025 全部通过
  **覆盖 AC**: AC-58, AC-59, AC-61, AC-62
  **依赖**: T025, T020

- [ ] **T027**: 本轮记录的测试
  **文件**: `src/backend/test/memory/test_turn_record.py`
  **逻辑**: 覆盖：一次成功的显式写入产生一行写入记录，失败的不产生；`bind_turn` 后可按消息 id 取回；按 `turn_id` 在绑定前可取回；取回接口只对条目主人返回，其他用户（含租户管理员、全局超管）取到空；取回的归因分两部分：检索取回的条目与常驻快照的条目；清空后该用户的本轮记录与快照被删除；同步版本的 `bind_turn` 与异步版本结果一致。
  **覆盖 AC**: AC-08, AC-09, AC-21, AC-23, AC-87
  **依赖**: T014

- [ ] **T028**: 本轮记录的实现
  **文件**: `src/backend/bisheng/memory/domain/services/turn_record.py`、`src/backend/bisheng/memory/domain/repositories/turn_repository.py`
  **逻辑**: 写入记录、检索记录、概要行；`bind_turn` 的异步与同步实现；按消息 id 或 `turn_id` 取回并校验主人。设计见 design 决策 15、16。
  **测试**: T027 全部通过
  **覆盖 AC**: AC-08, AC-09, AC-21, AC-23, AC-87
  **依赖**: T027, T024, T026

- [ ] **T029**: 审计与指标的测试
  **文件**: `src/backend/test/memory/test_audit_metrics.py`
  **逻辑**: 覆盖：删除、清空、忘掉、撤销、管理页编辑与新增各写一条审计，含操作人、时间、动作，`metadata` 里没有条目内容；各类计数（三种来源的新增、被取代、被删除、被带入、被检索返回、撤销、带入失败、检索失败、详情读取失败、整理失败）在事件发生时增加；计数落库后可按租户、场景、应用取出；清空后已发生的计数不丢；指标表与审计记录里没有任何条目内容；从未被读到的条目数与详情被取回过的比例可以算出。
  **覆盖 AC**: AC-101, AC-102, AC-103
  **依赖**: T014

- [ ] **T030**: 审计与指标的实现
  **文件**: `src/backend/bisheng/memory/domain/services/audit.py`、`src/backend/bisheng/memory/domain/services/metrics.py`
  **逻辑**: 审计调用 `AuditLogDao.ainsert_v2`，动作名 `memory.item.*`。指标在 Redis 计数，提供落库方法供定时任务调用；被读条目集合与详情被取回集合批量更新条目上的 `last_read_at`、`detail_read_at`。设计见 design 决策 20。
  **测试**: T029 全部通过
  **覆盖 AC**: AC-101, AC-102, AC-103
  **依赖**: T029, T020

**Wave 2 验收**: `uv run pytest test/memory -q` 全部通过且输出里没有 skipped；`bash scripts/arch-guard.sh` 无 VIOLATION；与 T001 基线相比无新增失败。

### Wave 3：本人的管理接口（Test-First 配对）

- [ ] **T031**: 管理接口的测试
  **文件**: `src/backend/test/memory/test_memory_api.py`
  **逻辑**: 覆盖：列表只含本人当前租户的有效条目，每条含内容、类型、记录时间、事件时间、来源标记、是否常驻，手动新增的来源为手动添加；编辑后原条目为已被取代、新内容有效；新增超长或含密钥类内容时返回对应错误码且不保存；删除单条；清空；接口没有任何按用户 id 取他人数据的参数，传入他人条目 id 时返回不存在；租户记忆为关时新增与编辑被拒、查看与删除与清空可用、读取"我的记忆"返回不可用；"我的记忆"为关时全部接口照常；修改"我的记忆"只影响本人。
  **覆盖 AC**: AC-08, AC-68, AC-88, AC-89, AC-90
  **依赖**: T020, T022, T028

- [ ] **T032**: 管理接口的实现
  **文件**: `src/backend/bisheng/memory/api/endpoints/memory.py`、`src/backend/bisheng/memory/api/router.py`
  **逻辑**: `/api/v1/memory` 下：条目列表、新增、编辑、删除、清空、读取与修改"我的记忆"、按 `turn_id` 或消息 id 取操作提示与归因、撤销。登录态取主体，委托 Service，`UnifiedResponseModel` 包装。在主路由注册。
  **测试**: T031 全部通过
  **覆盖 AC**: AC-08, AC-68, AC-88, AC-89, AC-90
  **依赖**: T031

**Wave 3 验收**: `uv run pytest test/memory -q` 全部通过；`bash scripts/arch-guard.sh` 无 VIOLATION。

### Wave 4：自动整理（Test-First 配对）

- [ ] **T033**: 活跃登记与水位的测试
  **文件**: `src/backend/test/memory/test_activity.py`
  **逻辑**: 覆盖：`end_turn(enabled=true)` 使登记行待整理；`end_turn(enabled=false)` 推进水位，这一轮此后不在整理范围内；水位只增不减（并发场景：整理结束与 `end_turn(enabled=false)` 交错，水位取较大者）；整理期间来了新消息时，整理结束后登记行仍为待整理；安静期内的行不被扫描选中，过了安静期才被选中；会话被软删除或开关在整理前被关闭时，整理把水位推到当前并且不产生条目；清空记忆后该用户的登记行水位被推到当前。
  **覆盖 AC**: AC-37, AC-38, AC-39, AC-40, AC-41
  **依赖**: T022

- [ ] **T034**: 活跃登记的实现
  **文件**: `src/backend/bisheng/memory/domain/services/activity.py`
  **逻辑**: `MemoryActivity.end_turn` 的异步与同步实现；选取到期登记行的查询；全部用按列的条件更新。设计见 design 决策 7。
  **测试**: T033 全部通过
  **覆盖 AC**: AC-37, AC-38, AC-39, AC-40, AC-41
  **依赖**: T033

- [ ] **T035**: 整理器的测试
  **文件**: `src/backend/test/memory/test_consolidator.py`
  **逻辑**: 用桩模型返回固定候选，覆盖：只读取水位之后、本次终点之前的消息；条目落库与水位推进在同一事务，模拟中途异常后重跑不产生重复条目；同一段对话处理两次只落一次；候选不合规（超长、密钥类、相对时间）被丢弃；四类场景的会话都被处理，条目的来源标记取自会话的场景与应用；整理失败时记录失败并计数，登记行保持待整理且有退避时间，之后可重跑；没有可用的整理模型按失败处理；任务一次处理该用户所有到期的会话；拿不到用户锁时不处理且不改登记行；运行中状态超过锁时限的行被重新选中。
  **覆盖 AC**: AC-39, AC-42, AC-44, AC-45
  **依赖**: T034, T026

- [ ] **T036**: 整理器的实现
  **文件**: `src/backend/bisheng/memory/domain/services/consolidator.py`、`src/backend/bisheng/memory/domain/services/consolidation_prompt.py`
  **逻辑**: 取用户锁（带令牌、定时续期）；逐会话读增量消息；调用租户配置的整理模型（未配置时用工作台模型列表的第一个），调用标记为"记忆"应用类型、不计个人额度；候选过 `guard`；与现有有效条目比对后落库并调整常驻；推进水位。深度研究轮次按本轮概要行处理（实现方式以 T008 的结论为准）。设计见 design 决策 7、18。
  **测试**: T035 全部通过
  **覆盖 AC**: AC-39, AC-42, AC-44, AC-45
  **依赖**: T035

- [ ] **T037**: 定时任务的测试
  **文件**: `src/backend/test/memory/test_worker_tasks.py`
  **逻辑**: 覆盖：扫描任务在没有租户上下文时能跨租户枚举到期登记行，并为每个用户投一个带租户头的整理任务；部署配置里的安静期与扫描周期改变后行为随之改变；自动整理总开关为关时不投任务；索引对账任务把待建索引的条目补建；指标落库任务把 Redis 计数写入日表；遗留的无消息 id 且超过一天的本轮记录被清理。
  **覆盖 AC**: AC-43
  **依赖**: T036, T030

- [ ] **T038**: 定时任务的实现
  **文件**: `src/backend/bisheng/worker/memory/tasks.py`（新建）、`src/backend/bisheng/core/config/settings.py`（Beat 默认调度）
  **逻辑**: 扫描、整理、索引对账、指标落库、遗留记录清理五个任务，走默认 `celery` 队列。**租户传递**：扫描任务的枚举查询包在 `bypass_tenant_filter()` 里；投整理任务时 `apply_async(args=[tenant_id, user_id], headers={"tenant_id": tenant_id})`，任务执行前由 `task_prerun` 恢复租户上下文。Beat 调度项用 `setdefault` 方式追加。
  **测试**: T037 全部通过
  **覆盖 AC**: AC-43
  **依赖**: T037

**Wave 4 验收**: `uv run pytest test/memory -q` 全部通过且无 skipped；`bash scripts/arch-guard.sh` 无 VIOLATION；与 T001 基线相比无新增失败。

### Wave 5：模型工具与脱敏（Test-First 配对）

- [ ] **T039**: 工具工厂与脱敏函数的测试
  **文件**: `src/backend/test/memory/test_tools.py`
  **逻辑**: 覆盖：工厂返回 `memory_write` 与 `memory_search` 两个工具；`memory_write` 三种动作各自调用到服务并返回含 `ok`、原因码、条目 id 的结果；写入被拒时返回原因码且不产生本轮写入记录；`memory_search` 把取回的 id 记入本轮记录，结果以背景信息说明开头且每条带记录日期；脱敏函数把名称以 `memory_` 开头的工具的入参与返回替换为只含 `redacted`、动作、条目 id 的结构，其他工具原样返回；脱敏结果里不含任何条目内容。
  **覆盖 AC**: AC-09, AC-23, AC-57
  **依赖**: T028

- [ ] **T040**: 工具工厂与脱敏函数的实现
  **文件**: `src/backend/bisheng/memory/domain/services/tools.py`、`src/backend/bisheng/memory/domain/services/redaction.py`
  **逻辑**: `build_memory_tools(ctx)`；工具说明里给出用户时区下的今天日期，并写明只在用户当前这句话明确要求时调用写入；`redact_tool_event(name, payload)`。设计见 design 决策 10。
  **测试**: T039 全部通过
  **覆盖 AC**: AC-09, AC-23, AC-57
  **依赖**: T039

**Wave 5 验收**: `uv run pytest test/memory -q` 全部通过；`bash scripts/arch-guard.sh` 无 VIOLATION。

### Wave 6：接入日常模式（Test-First 配对）

- [ ] **T041**: 租户记忆配置的测试
  **文件**: `src/backend/test/workstation/test_memory_config.py`
  **逻辑**: 覆盖：工作台配置里没有 `memory` 字段时按开启处理；保存 `memory.enabled=false` 后读取为关；只有租户管理员能改，未开多租户时由系统管理员改；`memory.model_id` 可保存与读取；子租户没有自己的配置时沿用根租户的值。
  **覆盖 AC**: AC-67, AC-76
  **依赖**: T022

- [ ] **T042**: 租户记忆配置的实现
  **文件**: `src/backend/bisheng/api/v1/schemas.py`（`WorkstationConfig` 加 `memory` 字段）、`src/backend/bisheng/memory/domain/services/gate.py`（读取租户开关）
  **逻辑**: `memory: {enabled: bool = True, model_id: int | None}`；沿用现有工作台配置接口与读写入口，不新开配置键。设计见 design 决策 17。
  **测试**: T041 全部通过
  **覆盖 AC**: AC-67, AC-76
  **依赖**: T041

- [ ] **T043**: 日常模式接入的测试
  **文件**: `src/backend/test/workstation/test_memory_integration.py`
  **逻辑**: 用桩模型驱动一轮对话，覆盖：登录态入口登记后，系统提示词里含常驻记忆文本块，工具列表里有两个记忆工具；未登记（模拟开放面入口直接调用服务函数）时两者都没有；无工具直连分支同样带上常驻记忆；模型调用 `memory_write` 成功后流里出现 `memory` 信号，落库的消息 `events` 里该工具的入参与返回已脱敏、不含条目内容；带入失败或检索失败时本轮回答仍完成并记录失败计数；正常结束与中断两条路径都完成本轮记录绑定与活跃登记；在助手 A 所在的会话里记下的条目在日常模式新会话的常驻文本里出现。
  **覆盖 AC**: AC-03, AC-09, AC-10, AC-21, AC-27, AC-28, AC-51, AC-61
  **依赖**: T040, T034, T042

- [ ] **T044**: 日常模式接入的实现
  **文件**: `src/backend/bisheng/workstation/api/endpoints/chat.py`、`src/backend/bisheng/workstation/domain/services/chat_service.py`、`src/backend/bisheng/workstation/domain/services/chat_helpers.py`
  **逻辑**: endpoint 里调 `MemoryGate.open`（请求体带时区）；`chat_service.py:2099-2111` 之后追加常驻文本块，`:2407-2411` 的直连分支同样处理；`_prepare_tools` 追加记忆工具；`:2311-2319` 与 `:2343-2344` 写入 `events` 前调脱敏函数；`_sse_resp` 增加 `memory` 类别；`:2558-2575` 与中断路径 `:1955-1980`（同步）调 `bind_turn` 与 `end_turn`。行号以实现时为准。
  **测试**: T043 全部通过
  **覆盖 AC**: AC-03, AC-09, AC-10, AC-21, AC-27, AC-28, AC-51, AC-61
  **依赖**: T043

**Wave 6 验收**: `uv run pytest test/memory test/workstation -q` 中本功能新增的测试全部通过；与 T001 基线相比 `test/workstation` 无新增失败；`bash scripts/arch-guard.sh` 无 VIOLATION。

### Wave 7：接入助手（Test-First 配对）

- [ ] **T045**: 助手接入的测试
  **文件**: `src/backend/test/assistant/test_memory_integration.py`
  **逻辑**: 用桩模型在 ReAct 与 function call 两种执行器下各跑，覆盖：助手记忆开关默认关，新建助手不带入常驻记忆、没有记忆工具；开关打开且已登记时，每轮输入里含常驻记忆系统消息、工具列表里有记忆工具，作者没有配置任何工具也如此；同一连接内作者把开关关掉后，下一轮不再带入、工具消失，再打开后恢复且之前的条目可读；历史超长触发裁剪时常驻记忆仍在输入里；`run()` 的返回值里不含注入的系统消息；两条工具落库路径（`run()` 返回值构造的行、回调插入的行）里记忆工具的内容都已脱敏；回答落库后本轮记录绑定到消息 id，中断时同样；用户乙在同一个助手里读不到用户甲的条目；免登录与开放面的连接不登记，记忆不工作。只有对助手有编辑权限的用户能改开关。
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-51, AC-69, AC-71, AC-72, AC-73, AC-74, AC-77
  **依赖**: T040, T034, T042

- [ ] **T046**: 助手接入的实现
  **文件**: `src/backend/bisheng/api/services/assistant_agent.py`、`src/backend/bisheng/api/v1/callback.py`、`src/backend/bisheng/common/chat/client.py`
  **逻辑**: `AssistantAgent.run` / `astream`：每轮重读 `memory_enabled`、做启用判定、状态变化时重建 agent、裁剪之后插入常驻记忆系统消息、返回前剔除注入的系统消息并对工具消息脱敏；新增 `after_answer_persisted(message_id, interrupted)`。`callback.py` 的工具回调里对记忆工具脱敏。`client.py` 只做两件事：接收并调用登录态 endpoint 注入的登记回调；回答落库后调用 `after_answer_persisted`。`client.py` 不得引用 `memory`。登录态助手 WebSocket endpoint 注入登记回调。实现位置以 T002、T003、T006 的结论为准。助手保存接口沿用现有编辑权限检查。
  **测试**: T045 全部通过
  **覆盖 AC**: AC-02, AC-09, AC-10, AC-51, AC-69, AC-71, AC-72, AC-73, AC-74, AC-77
  **依赖**: T045

**Wave 7 验收**: `uv run pytest test/memory test/assistant -q` 中本功能新增的测试全部通过；`grep -rn "bisheng.memory" src/backend/bisheng/common src/backend/bisheng/core` 无输出；`bash scripts/arch-guard.sh` 无 VIOLATION；与 T001 基线相比无新增失败。

### Wave 8：接入工作流（Test-First 配对）

- [ ] **T047**: 记忆检索节点的测试
  **文件**: `src/backend/test/workflow/test_memory_retriever_node.py`
  **逻辑**: 覆盖：节点类型已注册，同一工作流可放多个；`query` 可为纯文字、纯变量引用、两者混写，引用的变量不是文字时转成文字；`limit` 默认 20，保存与上线时 1 到 100 以外的整数、非整数被拒并返回对应错误码；执行时只在当前使用者本人的记忆里检索，包含在其他场景产生的条目，按相关程度排序且不超过 `limit`；输出每一项含内容、类型、记录时间、来源标记，有事件时间的带事件时间，带详情的内容为详情全文，每项内容带背景信息前缀与记录日期；没有命中、运行时 `query` 为空、没有登记、租户记忆为关、"我的记忆"为关、工作流开关为关时输出空数组且节点正常结束；检索不可用时节点失败并给出原因；运行日志含检索内容与返回条数、不含条目内容；两个用户运行同一工作流各自只得到本人的条目；工作流的其他节点不会自动收到常驻记忆。
  **覆盖 AC**: AC-02, AC-57, AC-60, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83, AC-84, AC-86
  **依赖**: T026, T022

- [ ] **T048**: 记忆检索节点的实现
  **文件**: `src/backend/bisheng/workflow/nodes/memory_retriever/memory_retriever.py`（新建）、`src/backend/bisheng/workflow/common/node.py`、`src/backend/bisheng/workflow/nodes/node_manage.py`
  **逻辑**: 新增 `NodeType.MEMORY_RETRIEVER` 与节点类；`_run` 从 `graph_state` 取 `chat_id` 与开关（取法以 T005 的结论为准），过启用判定后调 `MemoryService.search`；`parse_log` 返回检索内容与返回条数；参数校验。输出变量 `retrieved_memory`，结构见 design §4.2。
  **测试**: T047 全部通过
  **覆盖 AC**: AC-02, AC-57, AC-60, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83, AC-84, AC-86
  **依赖**: T047

- [ ] **T049**: 工作流开关、上线校验与登记的测试
  **文件**: `src/backend/test/workflow/test_memory_switch.py`
  **逻辑**: 覆盖：新建工作流的开始节点里记忆开关为关；开关随工作流版本保存，没有该参数的历史版本按关处理；含记忆检索节点而开关为关时上线被拒并返回对应错误码，开关为开时可上线；运行时的开关取自数据库里的上线版本，客户端送来一个开关为开的图而数据库为关时节点输出空数组；登录态运行被登记，免登录与开放面运行不被登记；停在等待输入返回时与成功、失败结束时各登记一次活跃；工作流会话在安静期后进入整理；只有对工作流有编辑权限的用户能改开关。
  **覆盖 AC**: AC-10, AC-42, AC-70, AC-71, AC-85
  **依赖**: T048, T034

- [ ] **T050**: 工作流开关、上线校验与登记的实现
  **文件**: `src/backend/bisheng/workflow/graph/graph_engine.py`、`src/backend/bisheng/api/services/workflow.py`、`src/backend/bisheng/worker/workflow/tasks.py`
  **逻辑**: 实例化时按 `flow_id` 读上线版本的开始节点参数 `memory_enabled`，与 `chat_id` 一起放进 `graph_state` 的只读字段；`update_flow_status` 的上线分支加校验；任务函数每次让出控制时调 `end_turn`；登录态工作流 WebSocket endpoint 注入登记回调，`common/chat/clients/workflow_client.py` 在拿到 `chat_id` 时调用（该文件不得引用 `memory`）。实现位置以 T005 的结论为准。
  **测试**: T049 全部通过
  **覆盖 AC**: AC-10, AC-42, AC-70, AC-71, AC-85
  **依赖**: T049

**Wave 8 验收**: `uv run pytest test/memory test/workflow -q` 中本功能新增的测试全部通过；`grep -rn "bisheng.memory" src/backend/bisheng/common src/backend/bisheng/core` 无输出；`bash scripts/arch-guard.sh` 无 VIOLATION；与 T001 基线相比无新增失败。

### Wave 9：接入深度研究（Test-First 配对）

- [ ] **T051**: 深度研究接入的测试
  **文件**: `src/backend/test/linsight/test_memory_integration.py`
  **逻辑**: 用桩模型覆盖：已登记且启用时，模型每次调用收到的提示词末段含常驻记忆与经验类条目，文本在任务开始时取一次、任务中途条目变化不改变它，该中间件排在引用与语言两个尾部中间件之前；首次执行、恢复、继续三条路径的工具列表里都有记忆工具；未登记（开放面、无人值守）时都没有；步骤落库的内容里记忆工具的入参与返回已脱敏；每一轮（首次提交与追问）各有一条本轮概要、各登记一次活跃，追问两次的任务三轮各被整理一次；显式写入成功后下发记忆事件。
  **覆盖 AC**: AC-09, AC-10, AC-21, AC-28, AC-42, AC-51, AC-55
  **依赖**: T040, T036

- [ ] **T052**: 深度研究接入的实现
  **文件**: `src/backend/bisheng/linsight/domain/services/agent_factory.py`、`src/backend/bisheng/linsight/domain/task_exec.py`、`src/backend/bisheng/linsight/domain/services/stream_event_mapper.py`
  **逻辑**: 新增记忆中间件（`wrap_model_call` 追加，文本任务开始时取一次）；`_generate_tools` 的三个调用点之后追加记忆工具，并按 `linsight/AGENTS.md` 让提示词与工具同步出现；步骤事件落库前脱敏；每一轮开始建本轮概要行、结束调 `end_turn`；`MessageEventType` 增加记忆事件。深度研究的三个登录态 endpoint（`linsight/api/endpoints/linsight.py`）调 `MemoryGate.open`。实现方式以 T004、T008 的结论为准。
  **测试**: T051 全部通过
  **覆盖 AC**: AC-09, AC-10, AC-21, AC-28, AC-42, AC-51, AC-55
  **依赖**: T051

**Wave 9 验收**: `uv run pytest test/memory test/linsight -q` 中本功能新增的测试全部通过；`bash scripts/arch-guard.sh` 无 VIOLATION；与 T001 基线相比无新增失败。

### Wave 10：前端 Platform

前端任务每个都带自动化测试（Vitest）。命令的工作目录是 `src/frontend/platform/`，lint 与类型检查在 `src/frontend/`。

- [ ] **T053**: 工作流记忆检索节点与开始节点开关
  **文件**: `src/frontend/platform/src/controllers/API/workflow.ts`、`src/frontend/platform/src/pages/BuildPage/flow/FlowNode/NodeLogo.tsx`、`src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/flow.json`
  **逻辑**: `workflowTemplate` 增加 `memory_retriever` 节点（`query` 用 `var_textarea` 控件、必填；`limit` 用 `number` 控件、默认 20，校验 1 到 100 的整数；输出 `retrieved_memory`）；开始节点增加"记忆"分组与 `memory_enabled` 开关（`switch` 控件，默认关），开关旁显示 AC-75 的说明；图标与三语文案。上线前校验（`hooks/useNodeEvent.ts`）：含该节点而开关为关时提示。
  **测试**: `src/frontend/platform/src/pages/BuildPage/flow/__tests__/memoryRetrieverNode.test.tsx`：模板里有该节点及默认值；`limit` 越界时校验不通过；开关为关且含该节点时上线校验给出提示；开关说明文案存在。
  **覆盖 AC**: AC-70, AC-75, AC-78, AC-79, AC-80, AC-85
  **依赖**: T048, T050

- [ ] **T054**: 助手设置页的记忆开关
  **文件**: `src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/Setting.tsx`、`src/frontend/platform/src/types/assistant.ts`（或 `AssistantDetail` 所在文件）、`src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`
  **逻辑**: 参照同页的 `knowledge_auth` 开关新增 `memory_enabled`，默认关，旁边显示 AC-75 的说明；写入 `assistantState`，随现有保存接口提交。
  **测试**: `src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/__tests__/memorySwitch.test.tsx`：默认关；切换后状态里的字段变化；说明文案存在。
  **覆盖 AC**: AC-69, AC-75
  **依赖**: T046

- [ ] **T055**: 工作台配置的记忆区
  **文件**: `src/frontend/platform/src/pages/BuildPage/bench/index.tsx`、`src/frontend/platform/src/pages/BuildPage/bench/DailyChatConfig.tsx`、`src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`
  **逻辑**: 用 `ToggleSection` 新增"记忆"区：开关（配置里没有该字段时显示为开）与"整理使用的模型"下拉。补 `ChatConfigForm` 类型、初始值、加载时合并、保存时的数据四处。
  **测试**: `src/frontend/platform/src/pages/BuildPage/bench/__tests__/memoryConfig.test.tsx`：没有字段时开关为开；关闭后保存的数据里 `memory.enabled` 为 false；模型下拉的值进入保存数据。
  **覆盖 AC**: AC-67
  **依赖**: T042

- [ ] **T056**: 管理端查看会话时的记忆操作占位
  **文件**: `src/frontend/platform/src/components/bs-comp/appChat/PlatformConversationMessages.tsx`、`src/frontend/platform/src/pages/LogPage/useAppLog/DailyMessageContent.tsx`
  **逻辑**: 渲染到脱敏后的记忆工具事件（含 `redacted: true`）时显示"记忆操作"占位，不显示其他内容。这些页面不调用任何 `/api/v1/memory` 接口。实际涉及的组件以 T007 的结论为准。
  **测试**: `src/frontend/platform/src/pages/LogPage/__tests__/memoryPlaceholder.test.tsx`：给定一条含脱敏记忆工具事件的消息，渲染结果只有占位文案；渲染过程中没有对 `/api/v1/memory` 的请求。
  **覆盖 AC**: AC-09
  **依赖**: T044, T046

**Wave 10 验收**: `cd src/frontend/platform && pnpm test` 中本功能新增的测试全部通过；`cd src/frontend && pnpm lint && pnpm typecheck && pnpm check-i18n` 通过。

### Wave 11：前端 Client

每个任务带自动化测试（Jest）。命令的工作目录是 `src/frontend/client/`。不要为了跑测试执行 `pnpm install`（见 `src/frontend/client/AGENTS.md`）。

- [ ] **T057**: 记忆接口封装与对话请求带时区
  **文件**: `src/frontend/client/src/api/memory.ts`（新建）、`src/frontend/client/src/hooks/useAiChatSSE.ts`
  **逻辑**: 封装 `/api/v1/memory` 的全部接口；发起日常模式对话的请求体里带上浏览器的 IANA 时区（`Intl.DateTimeFormat().resolvedOptions().timeZone`）；SSE 解析增加 `memory` 类别，把 `turn_id` 与标志写入消息状态。
  **测试**: `src/frontend/client/src/api/__tests__/memory.test.ts`：各接口的路径与参数；请求体含时区；收到 `memory` 事件后消息状态里有 `turn_id`。
  **覆盖 AC**: AC-14, AC-21
  **依赖**: T032, T044

- [ ] **T058**: 个人设置的记忆页
  **文件**: `src/frontend/client/src/pages/settings/sections/MemoryPane.tsx`（新建）、`src/frontend/client/src/pages/settings/settingsSections.ts`、`src/frontend/client/src/pages/settings/SettingsPage.tsx`、`src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`
  **逻辑**: 新增"记忆" section：顶部是"我的记忆"开关；下面是条目列表（内容、类型、记录时间、事件时间、来源、是否常驻），支持编辑、新增、删除、清空（二次确认）。租户记忆为关时不显示开关，列表只保留查看、删除、清空。新增与编辑被拒时显示接口返回的原因。
  **测试**: `src/frontend/client/src/pages/settings/sections/__tests__/MemoryPane.test.tsx`：列表渲染各字段；手动新增的条目来源显示为手动添加；清空需要二次确认；租户记忆为关时没有开关、没有新增与编辑入口；被拒时显示原因。
  **覆盖 AC**: AC-68, AC-88, AC-89, AC-90
  **依赖**: T057

- [ ] **T059**: 日常模式气泡的操作提示与归因
  **文件**: `src/frontend/client/src/components/Chat/MemoryNotice.tsx`（新建）、`src/frontend/client/src/components/Chat/AiMessageBubble.tsx`、`src/frontend/client/src/components/Chat/Messages/ToolCallDisplay.tsx`
  **逻辑**: 消息带有记忆标志时，在气泡操作区显示操作提示（记下、更正、忘掉三种），可展开看到条目原文并撤销；归因入口展开后分两部分：检索取回的条目逐条列出、常驻记忆整份查看，每条可就地删除。条目原文按 `turn_id` 或消息 id 向记忆接口取。脱敏后的记忆工具事件在工具卡片里显示为"记忆操作"。撤销失败时显示接口返回的原因。
  **测试**: `src/frontend/client/src/components/Chat/__tests__/MemoryNotice.test.tsx`：有写入标志时出现提示，展开后显示接口返回的条目；撤销调用接口并在成功后更新显示，失败时显示原因；归因分两部分；就地删除调用接口；没有标志的消息不显示任何记忆入口。
  **覆盖 AC**: AC-21, AC-22, AC-87
  **依赖**: T057

- [ ] **T060**: 应用聊天的操作提示与归因
  **文件**: `src/frontend/client/src/pages/appChat/components/ClientMessageFooter.tsx`、`src/frontend/client/src/pages/appChat/useWebsocket.ts`
  **逻辑**: 解析 WebSocket 的 `memory` 消息；在助手聊天的消息底部复用 T059 的 `MemoryNotice`。工作流聊天不显示归因。
  **测试**: `src/frontend/client/src/pages/appChat/__tests__/memoryFooter.test.tsx`：收到 `memory` 消息后助手的回答底部出现提示与归因入口；工作流的回答不出现归因入口。
  **覆盖 AC**: AC-21, AC-87
  **依赖**: T059, T046

- [ ] **T061**: 深度研究结果面板的操作提示与归因
  **文件**: `src/frontend/client/src/components/Linsight/Execution/ResultPanel.tsx`、`src/frontend/client/src/components/Linsight/Execution/TaskTurnPanel.tsx`
  **逻辑**: 每一轮的结果面板按该轮的 `turn_id` 复用 `MemoryNotice`，与点赞操作并列。`turn_id` 的来源以 T008 的结论为准。
  **测试**: `src/frontend/client/src/components/Linsight/Execution/__tests__/memoryResult.test.tsx`：一个任务的两轮各自显示各自的提示与归因，互不混淆。
  **覆盖 AC**: AC-21, AC-87
  **依赖**: T059, T052

**Wave 11 验收**: `cd src/frontend/client && pnpm test:ci` 中本功能新增的测试全部通过，与 T001 基线相比无新增失败；`cd src/frontend && pnpm lint && pnpm typecheck && pnpm check-i18n` 通过。

### Wave 12：评测集（〔评〕类验收标准）

这一 Wave 的产出是评测工具与一次评测结果，不是产品代码。它需要一个真实可用的模型端点，不作为自动化开发的完成条件。通过线由用户在评测集定稿时确认。

- [ ] **T062**: 评测集框架
  **文件**: `tools/memory_eval/`（新建，结构参照 `tools/taskmode_eval/`）
  **逻辑**: 用例格式：若干轮预置对话、一个提问、判定规则。运行器对同一批用例跑两种条件：带记忆、不带记忆，输出每题得分与两组对比。统计两类计数：回答声称已记下而没有成功写入、未经要求而写入。
  **测试**: `tools/memory_eval/tests/test_runner.py`：用桩模型跑通一条用例并产出两组得分与两类计数。
  **覆盖 AC**: AC-104, AC-105
  **依赖**: T044

- [ ] **T063**: 评测用例
  **文件**: `tools/memory_eval/cases/`
  **逻辑**: 取材自 bisheng 的真实使用场景，为每条〔评〕类验收标准至少写两条用例，并在用例里标注所覆盖的 AC 编号。用例不含真实用户的个人信息。
  **覆盖 AC**: AC-13, AC-15, AC-17, AC-18, AC-19, AC-20, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-46, AC-47, AC-48, AC-49, AC-63, AC-64, AC-65
  **依赖**: T062

- [ ] **T064**: 跑一次评测并记录结果
  **文件**: `features/v3.0.0/132-long-term-memory/verification.md`
  **逻辑**: 在 test 环境用其工作台默认模型跑全部用例，把每条〔评〕类 AC 的通过率、两组得分对比、两类计数写入 `verification.md`。把结果交用户确认通过线。
  **覆盖 AC**: AC-104, AC-105
  **依赖**: T063

**Wave 12 验收**: `tools/memory_eval` 的自测通过；`verification.md` 有一次完整评测结果。通过线未经用户确认前，不得宣称〔评〕类验收标准通过。

### Wave 13：P1

- [ ] **T065**: 经验类自动整理的测试
  **文件**: `src/backend/test/memory/test_consolidator_experience.py`
  **逻辑**: 用桩模型返回经验类候选，覆盖：深度研究轮次整理出的经验类条目类型为 experience、不常驻、来源为深度研究；下一个深度研究任务开始时它被带入。评测用例两条加入 `tools/memory_eval/cases/` 并标注 AC-50。
  **覆盖 AC**: AC-50, AC-54, AC-55
  **依赖**: T052

- [ ] **T066**: 经验类自动整理的实现
  **文件**: `src/backend/bisheng/memory/domain/services/consolidation_prompt.py`、`src/backend/bisheng/memory/domain/services/consolidator.py`
  **逻辑**: 深度研究轮次使用单独的整理提示词，关注用户对产出的固定要求与任务中已验证有效或无效的做法。
  **测试**: T065 全部通过
  **覆盖 AC**: AC-50, AC-54, AC-55
  **依赖**: T065

- [ ] **T067**: 过期事件改写的测试
  **文件**: `src/backend/test/memory/test_consolidator_expired_event.py`
  **逻辑**: 用桩模型返回改写后的表述，覆盖：事件时间已过的条目在下一次整理中被新条目取代，新条目保留日期且通过校验；旧条目为已被取代。评测用例两条加入 `tools/memory_eval/cases/` 并标注 AC-95。
  **覆盖 AC**: AC-95
  **依赖**: T036

- [ ] **T068**: 过期事件改写的实现
  **文件**: `src/backend/bisheng/memory/domain/services/consolidator.py`
  **逻辑**: 整理时找出该用户事件时间已过且未改写的有效条目，交模型改写为过去时，按"更正"落库。
  **测试**: T067 全部通过
  **覆盖 AC**: AC-95
  **依赖**: T067

**Wave 13 验收**: `uv run pytest test/memory -q` 全部通过且无 skipped。

### Wave 14：收尾

- [ ] **T069**: 文档回写
  **文件**: `features/v3.0.0/132-long-term-memory/design.md`、`features/v3.0.0/release-contract.md`、`src/backend/AGENTS.md`
  **逻辑**: design §4 从"目标形态"改为实现后的现状，行号按实际更新，修订历史记一行；release-contract 的 F132 段更新状态，候选不变量 INV-44 到 INV-47 转正；`src/backend/AGENTS.md` 的 Quick Map 增加 `memory` 模块一行。
  **依赖**: T044, T046, T050, T052, T056, T061

- [ ] **T070**: 端到端测试
  **文件**: 由 `/e2e-test features/v3.0.0/132-long-term-memory` 生成
  **逻辑**: 按 design §7 的手动验证六步生成接口级端到端测试与页面验证清单；用两个非管理员账号加一个租户管理员账号。
  **覆盖 AC**: AC-02, AC-03, AC-09, AC-24, AC-66, AC-85
  **依赖**: T069

**Wave 14 验收**: `/e2e-test` 产出的接口级测试通过；`bash scripts/arch-guard.sh` 无 VIOLATION；与 T001 基线相比全量无新增失败。

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已确认的决策时，先停下与用户重新确认，再记录。

（暂无）
