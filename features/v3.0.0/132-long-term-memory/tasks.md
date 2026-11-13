# Tasks: 长期记忆

**关联规格**: [spec.md](./spec.md) · **设计**: [design.md](./design.md)
**版本**: v3.0.0（开发基线）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-11-13 用户确认；同日修订 AC-71、AC-87，移出 AC-11、AC-67、AC-100，新增 AC-106 |
| design.md | ✅ 已评审 | 2026-11-13 用户确认第 4 稿，第 5 稿去掉租户级开关；§10 的 V1–V8 待 Wave 0 验证后回写 |
| tasks.md | ✅ 已拆解 | 第 4 稿（去掉租户级开关）。`/sdd-review tasks` 两轮：第二轮结论为可以开始 Wave 0，其余问题已在本稿修订，本稿未再复审 |
| 实现 | 🔲 未开始 | 0 / 96 完成 |

---

## 开发模式

**按 Wave 组织。** Wave 之间按依赖顺序推进；同一个 Wave 内没有相互依赖的任务可以并行。每个 Wave 末尾有一条"Wave 验收"，由下面定义的三条固定命令加该 Wave 自己的测试命令组成，全部能由命令输出判定。

**后端 Test-First。** 每对任务先写测试（红）再写实现（绿）。测试放在 `src/backend/test/memory/` 及各接入模块现有的测试目录下。后端命令的工作目录是 `src/backend/`。本 worktree 没有 `src/backend/.venv`，T001 按既有做法软链主检出的虚拟环境，不重新安装依赖。

**测试替身。** 标〔测〕的验收标准不依赖真实模型、Milvus、ES、MinIO：模型用桩；索引与对象存储用 T014 提供的内存实现（实现 T010 定义的接口）；关系库用内存 SQLite（`test/conftest.py` 已有先例）。

**三条固定命令**（下文各 Wave 验收引用它们的名字）：

- **〔架构检查〕** `scripts/arch-guard.sh` 一次只检查一个文件，不带参数时直接退出；基线代码里已有若干与本功能无关的违规。所以对全部源码逐文件检查，再与 T001 存下的基线输出比较，只数新增的行：
  ```bash
  { git ls-files -z src/backend/bisheng src/frontend; git ls-files -z -o --exclude-standard src/backend/bisheng src/frontend; } | xargs -0 -n1 bash scripts/arch-guard.sh | sort > /tmp/f132-arch.txt; comm -13 features/v3.0.0/132-long-term-memory/baseline/arch-guard.txt /tmp/f132-arch.txt | grep VIOLATION | wc -l
  ```
  工作目录是仓库根。预期输出 `0`。
- **〔分层检查〕** `common/` 与 `core/` 不得导入记忆模块：
  ```bash
  grep -rnE "^\s*(from bisheng\.memory|import bisheng\.memory|from bisheng import .*\bmemory\b)" src/backend/bisheng/common src/backend/bisheng/core | wc -l
  ```
  工作目录是仓库根。预期输出 `0`。`core/database/tenant_filter.py` 里登记模型模块的是字符串，不是导入语句，不会被匹配。
- **〔基线比对〕** 本地没有中间件时后端测试本来就成块失败，所以回归用"相对基线的新增失败"判定：
  ```bash
  uv run pytest test/ -m "not e2e" -q -p no:cacheprovider --junitxml=/tmp/f132-current.xml; python ../../features/v3.0.0/132-long-term-memory/baseline/compare_junit.py ../../features/v3.0.0/132-long-term-memory/baseline/backend.xml /tmp/f132-current.xml
  ```
  预期输出的最后一行是 `NEW FAILURES: 0`。脚本只把"基线里通过或不存在、现在失败或报错"的用例算作新增失败。

**验收标准的两类。** spec 里标〔测〕的由本文的测试任务覆盖，每个测试函数在名字或文档字符串里写明所覆盖的 AC 编号。标〔评〕的依赖模型行为，由 Wave 14 的评测集覆盖，不作为任何 Wave 的完成条件。

**设计论证不在这里重复**，指向 design 的决策号。接入类任务里的行号以实现时的代码为准。

**任务做不完时。** 单个任务在一次会话内做不完的，按它的测试文件里的测试分组分多次提交，不改任务编号，也不跳过测试。

**生产装配。** 服务只依赖接口；真实实现由 `memory/domain/services/factory.py`（T036）装配，四个接入点、管理接口、定时任务、检索节点都从它取服务实例，不自己构造。

**禁区。** 实现过程中不得：执行 `git push`；修改各任务点名的测试文件以外的任何既有测试；新增第三方依赖；改动 `core/vectorstore/`、`knowledge/` 下的检索行为；在 `common/` 或 `core/` 里导入 `memory`（〔分层检查〕）。

---

## Tasks

### Wave 0：基线与待验证项

这一 Wave 不写产品代码。验证结论写进 `features/v3.0.0/132-long-term-memory/verification.md`，再回写 design。结论与 design 现有方案不一致时，停下来请用户确认（SDD-Guide §3）。**这一 Wave 不适合无人值守**：它的产出可能推翻设计。

- [ ] **T001**: 测试环境、基线与比对脚本
  **文件**: `features/v3.0.0/132-long-term-memory/baseline/compare_junit.py`（新建）、`features/v3.0.0/132-long-term-memory/baseline/backend.xml`（生成）、`features/v3.0.0/132-long-term-memory/baseline/arch-guard.txt`（生成）、`features/v3.0.0/132-long-term-memory/verification.md`（新建）
  **逻辑**: 把主检出的 `src/backend/.venv` 与 `src/frontend` 下各级 `node_modules` 软链到本 worktree（只软链，不执行 `uv sync` 或 `pnpm install`）；确认 `src/backend/bisheng/config.yaml` 存在（没有就从主检出复制，它不进版本库）。按〔架构检查〕的前半段在未改动的代码上生成 `baseline/arch-guard.txt`。确认 `cd src/frontend/platform && pnpm exec vitest run --version` 与 `cd src/frontend/client && pnpm exec jest --version` 能执行。在未改动的代码上运行 `uv run pytest test/ -m "not e2e" -q -p no:cacheprovider --junitxml=<baseline/backend.xml>`。写 `compare_junit.py`：读两个 junit 文件，输出新增失败的用例 id 清单，最后一行固定为 `NEW FAILURES: <n>`。在 `verification.md` 的"基线"一节记录运行前置条件（代理环境变量等）与基线的通过、失败、报错数量。
  **依赖**: 无

- [x] **T002**: V1 助手工具回调里的脱敏
  **文件**: `src/backend/test/memory/spike/test_v1_callback.py`（新建，实验代码，Wave 9 完成后删除）、`verification.md`
  **逻辑**: 读 `bisheng/api/v1/callback.py:434-585` 与挂载点 `common/chat/client.py:308-322`。写一个最小测试：构造回调处理器，模拟一次名为 `memory_probe` 的工具从开始到结束，记录落库与下发的内容。确认 `on_tool_start` 能拿到工具名、能否按 `run_id` 在 `on_tool_end` / `on_tool_error` 里认出同一次调用、`intermediate_steps` 字段带了什么。
  **判据**: 实验测试能跑通，并给出"按 `run_id` 识别记忆工具并替换落库与下发内容"是否可行的结论与确切改动位置。
  **依赖**: T001

- [x] **T003**: V2 与 V8 登记回调的注入点
  **文件**: `verification.md`
  **逻辑**: 读登录态助手与工作流的 WebSocket endpoint、`chat_manager.dispatch_client`、`common/chat/client.py:230`、`:361-372`、`common/chat/clients/workflow_client.py:97-98`、`:171-179`，以及免登录 `public_endpoints/api/endpoints/assistant.py:45`、`workflow.py:23` 与开放面 `open_endpoints/api/endpoints/assistant.py:160`。确认三类路径各自如何构造客户端对象。
  **判据**: 给出只在登录态路径传入可调用对象的注入点、客户端里 `chat_id` 确定或切换的调用点；确认免登录与开放面路径拿不到它。
  **依赖**: T001

- [x] **T004**: V3 深度研究的落库与落文件路径
  **文件**: `src/backend/test/memory/spike/test_v3_linsight_paths.py`（新建，实验代码，Wave 11 完成后删除）、`verification.md`
  **逻辑**: 读 `linsight/domain/services/stream_event_mapper.py:627-712`、`linsight/domain/models/linsight_execute_task.py:68`、`linsight/api/endpoints/linsight.py:579-615`、`linsight/domain/utils.py:104-117`、`linsight/domain/services/context_budget.py:144` 以及大工具结果卸载的实现。写最小测试直接调用"步骤事件映射"与"上下文压缩写文件"两个函数，输入含一条工具消息，观察输出里工具入参与返回出现在哪。
  **判据**: 列出工具内容的全部落点（数据库字段、工作区文件），每个落点给出脱敏的切入位置；指出分享链接读取任务详情所走的接口。
  **依赖**: T001

- [x] **T005**: V4 工作流节点取 `chat_id` 与上线版本的开关
  **文件**: `src/backend/test/memory/spike/test_v4_graph_state.py`（新建，实验代码，Wave 10 完成后删除）、`verification.md`
  **逻辑**: 读 `workflow/graph/graph_engine.py:207-231`、`workflow/graph/graph_state.py`、`workflow/nodes/base.py:21-60`、`worker/workflow/tasks.py:40-82`、`worker/workflow/redis_callback.py:532-554`。写最小测试：实例化一个只含开始节点与一个假节点的图，确认能把 `chat_id` 与一个只读标志放进 `graph_state` 并在节点 `_run` 里取到。找出按 `flow_id` 读上线版本开始节点参数的现成方法，以及评测与调试运行时 `chat_id` 的取值。
  **判据**: 实验测试跑通；给出节点取这两个值的实现位置。
  **依赖**: T001

- [x] **T006**: V5 助手两种执行器下的系统消息注入
  **文件**: `src/backend/test/memory/spike/test_v5_assistant_inject.py`（新建，实验代码，Wave 9 完成后删除）、`verification.md`
  **逻辑**: 读 `api/services/assistant_agent.py:428-458`、`:548-601`。用桩模型分别在 ReAct 与 function call 执行器下跑一轮：在裁剪之后向输入插入一条系统消息，断言桩模型收到的消息序列里包含它；确认 `run()` 返回值经处理后 `client.py:393-400` 的切片偏移不受影响。
  **判据**: 两种执行器下消息序列的结论与注入代码的确切位置。**本任务只能证明消息能送达模型**；多条系统消息在真实模型端点上是否被接受，要在 T094 用 test 环境的模型验证，届时回写。
  **依赖**: T001

- [x] **T007**: V6 管理端查看会话所用的接口
  **文件**: `verification.md`
  **逻辑**: 读 `src/frontend/platform/src/pages/LogPage/useAppLog/appChatDetail.tsx`、`dailyChatDetail.tsx`、`LabelPage/taskAppChats.tsx` 及其调用的 API 函数，追到后端端点。
  **判据**: 一张"页面 → 接口 → 返回的含工具内容的字段"对照表，并指出渲染这些字段的组件。
  **依赖**: T001

- [x] **T008**: V7 深度研究追问轮的存储与前端轮次标识
  **文件**: `verification.md`
  **逻辑**: 读 `linsight/api/endpoints/linsight.py:174`、`:327-378`、`linsight/domain/utils.py:973-1019`、`linsight/domain/services/workbench_impl.py:345-402`，前端 `client/src/components/Linsight/Execution/TaskTurnPanel.tsx`、`ResultPanel.tsx`、`ExecutionFlow.tsx`。
  **判据**: 给出"按轮读取问题与结果"的数据来源与方法；给出把 `turn_id` 送到前端每一轮面板的途径。
  **依赖**: T001

- [x] **T009**: 把验证结论回写 design
  **文件**: `features/v3.0.0/132-long-term-memory/design.md`
  **逻辑**: 按 T002–T008 的结论更新决策 6、7、10、11、15、17 与 §4.4、§10；§10 每一项写上结论与日期。有任何一项推翻了 design 的现有方案，先停下来请用户确认，再继续。
  **依赖**: T002, T003, T004, T005, T006, T007, T008

**Wave 0 验收**: `uv run pytest test/memory/spike -q` 通过；`verification.md` 含基线与 V1–V8 的结论；`baseline/backend.xml` 与 `baseline/arch-guard.txt` 存在。是否有需要用户确认的推翻项，由人判断。

### Wave 1：基础设施（无测试配对）

- [x] **T010**: 错误码 121、架构守卫名单与三个接口定义
  **文件**: `src/backend/bisheng/common/errcode/memory.py`（新建）、`scripts/arch-guard.sh`、`src/backend/bisheng/memory/domain/ports.py`（新建，含 `MemoryContext`）
  **逻辑**: 定义 121 段错误码类（写成 `Code: int = 121NN`）：内容超长、内容含密钥类信息、内容含相对时间、目标条目不存在或状态已变、撤销失败（三种原因各一个码）、检索不可用、检索数量参数非法、工作流含记忆检索节点而开关关闭。把 `memory` 加进 `scripts/arch-guard.sh` 的 `DOMAIN_MODULES`。在 `ports.py` 里定义三个 `Protocol`：`MemoryIndex`（写入、删除、检索、按用户删除）、`DetailStore`（写、读、删、按用户删、按用户列出对象键）、`MemoryLLM`（整理调用、embedding 调用）。同一文件里定义 `MemoryContext` 数据类（`tenant_id`、`user_id`、时区、`chat_id`、`turn_id`、场景、应用 id 与名称）和唯一的范围过滤函数 `build_scope_filter(ctx)`，两路检索的过滤条件只能由它生成。后续的真实实现与测试替身都实现这三个接口，以此解开"服务依赖索引、索引依赖服务"的环。
  **依赖**: T009

- [x] **T011**: 错误码文案与登记
  **文件**: `src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`、`docs/constitution.md`、`features/v3.0.0/release-contract.md`
  **逻辑**: T010 的每个错误码三语文案同批加入，运行 `pnpm locales:build`（在 `src/frontend/`）。回写 C5 表与 release-contract 的"已分配模块编码"。
  **依赖**: T010

- [x] **T012**: 六张表的 ORM 模型
  **文件**: `src/backend/bisheng/memory/domain/models/`（新建，每张表一个文件）、`src/backend/bisheng/database/models/assistant.py`、`src/backend/bisheng/core/database/tenant_filter.py`
  **逻辑**: 按 design §4.2 定义 `memory_item`（含 `index_model_id`，记录建索引时所用的 embedding 模型）、`memory_session_cursor`、`memory_user_setting`、`memory_turn_record`、`memory_resident_snapshot`、`memory_metric_daily`。JSON 用 `dialect_helpers.JsonType`，长文本用 `LargeText`，`update_time` 用方言辅助。`assistant` 模型加列 `memory_enabled`（布尔，默认关）。把记忆的模型模块路径（字符串）登记进 `tenant_filter.py` 的 `_TENANT_AWARE_MODEL_MODULES`。
  **依赖**: T009

- [x] **T013**: Alembic 迁移
  **文件**: `src/backend/bisheng/core/database/alembic/versions/`（新增一个 revision）
  **逻辑**: 按同目录 `AGENTS.md`：`down_revision` 取当前唯一 head；只写 DDL；用 `table_exists` / `column_exists` 保证可重入；不写字符集；`assistant.memory_enabled` 带 `server_default`。运行 `uv run pytest test/database/test_alembic_single_head.py -q`。
  **回滚**: `downgrade` 删除六张新表与该列。六张表是新增表，没有数据迁移，可逆。
  **依赖**: T012

- [x] **T014**: 运行期配置、应用类型与测试夹具
  **文件**: `src/backend/bisheng/memory/domain/config.py`（新建）、`src/backend/bisheng/common/constants/enums/telemetry.py`、`src/backend/bisheng/initdb_config.yaml`、`src/backend/test/memory/conftest.py`（新建，含 `__init__.py`）
  **逻辑**: `MemoryRuntimeConfig` 从 `settings.aget_from_db("memory")` 读取，缺键时用代码里的默认值（design 决策 19 的表）；`bisheng/initdb_config.yaml` 增加带注释的 `memory` 段，不改 `config.yaml`。`ApplicationTypeEnum` 增加 `MEMORY = "memory"`。夹具提供：内存 SQLite 上建好六张表的会话；实现 `MemoryIndex` 的内存索引（可注入"关键词路不可达""向量路不可达""写入失败""超时"）；实现 `DetailStore` 的内存存储（可注入读取失败）；实现 `MemoryLLM` 的桩（按脚本返回候选、工具调用或抛错）；`MemoryContext` 工厂；两个租户、两个用户、一个"可见多租户"身份、一个全局超管身份。
  **依赖**: T010, T012

**Wave 1 验收**: `uv run pytest test/database/test_alembic_single_head.py -q` 通过；`cd src/frontend && pnpm check-i18n` 通过；〔架构检查〕为 `0`；〔分层检查〕为 `0`；〔基线比对〕为 `NEW FAILURES: 0`。

### Wave 2：校验、数据访问、配置开关与启用判定

- [x] **T015**: 内容校验的测试
  **文件**: `src/backend/test/memory/test_guard.py`
  **逻辑**: 超过 200 字被拒；类型只接受 fact、preference、experience；密钥类内容被拒（常见密钥前缀与高熵串、18 位身份证号校验位、银行卡号 Luhn 校验、"密码是 / password:" 句式，各至少两个正例两个反例）；含相对时间词（今天、明天、下周二、本月、tomorrow、next week）被拒并返回对应原因码；合法内容通过。
  **覆盖 AC**: AC-12, AC-14, AC-16
  **依赖**: T014

- [x] **T016**: 内容校验的实现
  **文件**: `src/backend/bisheng/memory/domain/services/guard.py`
  **逻辑**: `SensitiveContentGuard`、长度与类型校验、相对时间检查；每种拒绝返回一个原因码（T010 的错误码）。设计见 design 决策 14 与 §4.1 末段。
  **测试**: T015 全部通过
  **覆盖 AC**: AC-12, AC-14, AC-16
  **依赖**: T015

- [x] **T017**: 数据访问层隔离的测试
  **文件**: `src/backend/test/memory/test_repository_isolation.py`
  **逻辑**: 用户甲读不到用户乙的条目；租户 A 的条目在租户 B 的上下文里读不到；"可见多租户"身份只读到当前租户的条目；全局超管身份只读到自己在当前租户的条目；批量更新与删除只影响当前租户当前用户的行；用户归属从 A 变到 B 再回到 A，A 里的条目先不可读后可读且未被迁移；`memory_user_setting` 并发建行不报错；条目变更与 `rev` 加一同时生效。
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-06, AC-07
  **依赖**: T014

- [x] **T018**: 数据访问层的实现
  **文件**: `src/backend/bisheng/memory/domain/repositories/item_repository.py`、`src/backend/bisheng/memory/domain/repositories/setting_repository.py`
  **逻辑**: 条目与用户设置的读写方法，签名都接收 `MemoryContext`，查询与写操作显式带 `tenant_id` 与 `user_id`（design 决策 9）。用户设置首次需要时建行，捕获唯一键冲突后重读；`rev` 的自增与条目变更在同一事务。
  **测试**: T017 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-06, AC-07
  **依赖**: T017

- [x] **T019**: 整理模型配置的测试
  **文件**: `src/backend/test/workstation/test_memory_config.py`
  **逻辑**: 工作台配置里的 `memory_model_id` 可保存与读取；只有能修改工作台配置的管理员能改；没有该字段或为空时，取模型的函数返回工作台模型列表的第一个；模型列表也为空时返回"无可用模型"；子租户没有自己的工作台配置时沿用根租户的值（工作台配置的既有行为）。工作台配置里没有任何记忆开关字段。
  **覆盖 AC**: AC-106
  **依赖**: T014

- [x] **T020**: 整理模型配置的实现
  **文件**: `src/backend/bisheng/api/v1/schemas.py`、`src/backend/bisheng/memory/domain/services/consolidation_model.py`（新建）
  **逻辑**: `WorkstationConfig` 增加 `memory_model_id: int | None = None`；沿用现有工作台配置接口与读写入口，不新开配置键。`consolidation_model.py` 提供按当前租户取整理模型的函数。设计见 design 决策 17、18。
  **测试**: T019 全部通过
  **覆盖 AC**: AC-106
  **依赖**: T019

- [x] **T021**: 资格登记与启用判定的测试
  **文件**: `src/backend/test/memory/test_gate.py`
  **逻辑**: 没有登记行时 `resolve` 返回空；`open` 新建行时水位初值等于会话当前最大消息 id，租户与用户取自当前登录上下文；同一用户同一租户再次 `open` 不改行，用户设置里的时区变了才更新行上的时区；租户或用户与已登记不同则置为无资格；`chat_id` 对应的会话属于别人时不登记；时区的三级回落（登记行 → 用户设置 → 部署默认）；启用判定的全部组合（我的记忆、助手开关、工作流开关各自开与关）；没有用户设置行时"我的记忆"按开处理（升级后的默认）；用户停用时返回空、重新启用后恢复；任一开关关闭后再开，之前的条目仍可读；一轮开始时取得的结果在该轮内不随开关变化；下游以登记行上的租户与用户为准，不读租户上下文变量。
  **覆盖 AC**: AC-10, AC-40, AC-66, AC-72, AC-73, AC-74, AC-76, AC-99
  **依赖**: T018

- [x] **T022**: 资格登记与启用判定的实现
  **文件**: `src/backend/bisheng/memory/domain/services/gate.py`、`src/backend/bisheng/memory/domain/repositories/cursor_repository.py`
  **逻辑**: `MemoryGate.open(chat_id, login_user)` 与 `resolve(chat_id, scene, app_enabled)`。登记行的写入规则、会话归属核对、时区回落见 design 决策 6、13；登记行的更新全部是按列的条件更新。
  **测试**: T021 全部通过
  **覆盖 AC**: AC-10, AC-40, AC-66, AC-72, AC-73, AC-74, AC-76, AC-99
  **依赖**: T021

**Wave 2 验收**: `uv run pytest test/memory test/workstation/test_memory_config.py -q` 全部通过且输出里没有 skipped；〔架构检查〕、〔分层检查〕为 `0`；〔基线比对〕为 `NEW FAILURES: 0`。

### Wave 3：审计、指标与本轮记录

- [x] **T023**: 审计与指标的测试
  **文件**: `src/backend/test/memory/test_audit_metrics.py`
  **逻辑**: 审计函数被调用后写入一条记录，含操作人、时间、动作，`metadata` 里没有条目内容；各类计数（三种来源的新增、被取代、被删除、被带入、被检索返回、撤销、带入失败、检索失败、检索降级、详情读取失败、整理失败）调用后在 Redis 增加；落库后可按租户、场景、应用取出；被读条目集合与详情被取回集合落库后更新条目上的两个时间列，由此可算出"从未被读到的条目数"与"详情被取回过的比例"；指标表里没有任何条目内容。
  **覆盖 AC**: AC-101, AC-102, AC-103
  **依赖**: T018

- [x] **T024**: 审计与指标的实现
  **文件**: `src/backend/bisheng/memory/domain/services/audit.py`、`src/backend/bisheng/memory/domain/services/metrics.py`
  **逻辑**: 审计调用 `AuditLogDao.ainsert_v2`，动作名统一为 `memory.item.<动作>`，在 `audit.py` 里用常量集中定义；这些动作**不加入**管理端审计页面的可见白名单（`_UI_VISIBLE_V2_ACTIONS`），因为本期不向管理员展示任何与用户记忆有关的界面。指标在 Redis 计数，提供落库方法。设计见 design 决策 20。
  **测试**: T023 全部通过
  **覆盖 AC**: AC-101, AC-102, AC-103
  **依赖**: T023

- [x] **T025**: 本轮记录的测试
  **文件**: `src/backend/test/memory/test_turn_record.py`
  **逻辑**: 写入记录、检索记录、概要行各自能写入并按 `turn_id` 取回；`bind_turn` 后可按消息 id 取回，同步版本与异步版本结果一致；取回接口只对条目主人返回，其他用户（含租户管理员、全局超管）取到空；按用户删除本轮记录与常驻快照；遗留的无消息 id 且超过一天的记录可被清理方法删除。
  **覆盖 AC**: AC-08, AC-09
  **依赖**: T018

- [ ] **T026**: 本轮记录的实现
  **文件**: `src/backend/bisheng/memory/domain/services/turn_record.py`、`src/backend/bisheng/memory/domain/repositories/turn_repository.py`
  **逻辑**: 三类行的写入；`bind_turn` 的异步与同步实现；按消息 id 或 `turn_id` 取回并校验主人；常驻快照的写入与读取；按用户删除；遗留记录清理。设计见 design 决策 15。
  **测试**: T025 全部通过
  **覆盖 AC**: AC-08, AC-09
  **依赖**: T025

**Wave 3 验收**: `uv run pytest test/memory -q` 全部通过且无 skipped；〔架构检查〕、〔分层检查〕为 `0`。

### Wave 4：条目写入与状态机

- [ ] **T027**: 记下、更正、忘掉的测试
  **文件**: `src/backend/test/memory/test_service_write.py`
  **逻辑**: 记下后同一用户立即可读；来源标记含场景、应用、会话与写入方式，应用名称为写入时的快照，之后应用改名或被删除不影响；事实与偏好类的显式写入默认常驻且排在最前，经验类不常驻；更正后新条目有效、旧条目为已被取代并记录取代关系，旧条目行仍保留；忘掉后条目不可读；目标不存在或状态已变时更正与忘掉返回失败且不新建；被取代与被删除的条目不出现在列表里；长正文写成详情对象且条目内容为概括；两个并发写入都保留；每次成功写入产生一行本轮写入记录、一条审计、一次计数，失败的都不产生；索引写入失败或超时时写入仍成功、条目标为待建索引；被取代或被忘掉时索引项被删除；来源会话被软删除后条目仍可读。
  **覆盖 AC**: AC-04, AC-21, AC-23, AC-24, AC-25, AC-26, AC-44, AC-91, AC-92, AC-97, AC-98, AC-101
  **依赖**: T024, T026, T016

- [ ] **T028**: 记下、更正、忘掉的实现
  **文件**: `src/backend/bisheng/memory/domain/services/memory_service.py`
  **逻辑**: `write`（remember / correct / forget）与 `list`。新增是 INSERT；更正与忘掉是带状态条件的 UPDATE，影响行数为 0 即失败。详情对象先写后插行，`item_id` 由应用侧生成。事务里同时：`rev` 加一、写本轮记录。提交后：通过 `MemoryIndex` 同步建或删索引（失败置待建）、写审计、计数。依赖以构造参数注入 `MemoryIndex` 与 `DetailStore`。设计见 design 决策 3、4、5、8。
  **测试**: T027 全部通过
  **覆盖 AC**: AC-04, AC-21, AC-23, AC-24, AC-25, AC-26, AC-44, AC-91, AC-92, AC-97, AC-98, AC-101
  **依赖**: T027

- [ ] **T029**: 编辑、删除、清空、撤销的测试
  **文件**: `src/backend/test/memory/test_service_manage.py`
  **逻辑**: 编辑后原条目为已被取代、新内容有效；手动新增的来源为手动添加；删除单条后不可读；三种撤销各自的结果（撤销记下则删除、撤销更正则新条目删除旧条目恢复、撤销忘掉则恢复），恢复的条目重新建索引；三种撤销失败情形（已清空、新条目已被再次取代或删除、已撤销过）各返回对应原因码且不做部分恢复；清空后该用户在当前租户的全部行（含已被取代与已删除的）、详情对象、索引项、本轮记录、常驻快照都不存在，其所有登记行的水位被推到当前，另一租户与另一用户的数据不受影响；清空中途失败后可重入；每种操作各写一条审计并计数，清空之后此前的计数仍在。
  **覆盖 AC**: AC-22, AC-89, AC-93, AC-101, AC-102
  **依赖**: T028, T022

- [ ] **T030**: 编辑、删除、清空、撤销的实现
  **文件**: `src/backend/bisheng/memory/domain/services/memory_service.py`、`src/backend/bisheng/memory/domain/services/detail_store.py`、`src/backend/bisheng/memory/domain/repositories/cursor_repository.py`
  **逻辑**: `edit`、`add_manual`、`delete`、`clear`、`undo`。删除是软删除；清空是硬删除，顺序为索引、对象、本轮记录与快照、条目行，最后推进该用户登记行的水位。`detail_store.py` 是 `DetailStore` 的 MinIO 实现，对象键 `memory/{tenant_id}/{user_id}/{item_id}.md`。设计见 design 决策 4、7。
  **测试**: T029 全部通过
  **覆盖 AC**: AC-22, AC-89, AC-93, AC-101, AC-102
  **依赖**: T029

**Wave 4 验收**: `uv run pytest test/memory -q` 全部通过且无 skipped；〔架构检查〕、〔分层检查〕为 `0`；〔基线比对〕为 `NEW FAILURES: 0`。

### Wave 5：常驻记忆、检索与模型调用

- [ ] **T031**: 常驻记忆的测试
  **文件**: `src/backend/test/memory/test_resident.py`
  **逻辑**: 带入的条目数与总字数都不超过上限，先到者生效，上限取自运行期配置；到达上限时没有任何条目被截断，未带入的条目状态仍为有效（可检索性在 T033 验证）；已被取代与已删除的条目不被带入；经验类条目不出现在日常模式与助手的常驻文本里；深度研究的带入在常驻之外另含经验类条目，按最近被读时间与记录时间排序并受独立上限约束；带详情的条目只带入概括；文本首行是背景信息说明且每条带记录日期；事件时间已过（按用户时区）的条目不再带入、状态仍为有效；缓存键随 `rev` 与日期变化，条目变更后下一次读取反映变更；存在很久且从未被读取的条目没有被删除；缓存未命中时写一行常驻快照，并记一次带入计数。
  **覆盖 AC**: AC-52, AC-53, AC-54, AC-55, AC-56, AC-57, AC-91, AC-94, AC-96
  **依赖**: T028

- [ ] **T032**: 常驻记忆的实现
  **文件**: `src/backend/bisheng/memory/domain/services/resident.py`
  **逻辑**: `resident(ctx, scene_class)` 与 `experience(ctx)`；渲染文本块；Redis 缓存（键含租户、用户、`rev`、用户时区下的日期、场景类别，TTL 1 小时）；未命中时写常驻快照；计数。设计见 design 决策 8。
  **测试**: T031 全部通过
  **覆盖 AC**: AC-52, AC-53, AC-54, AC-55, AC-56, AC-57, AC-91, AC-94, AC-96
  **依赖**: T031

- [ ] **T033**: 检索的测试
  **文件**: `src/backend/test/memory/test_search.py`
  **逻辑**: 只返回当前用户当前租户的有效条目；返回内容、类型、记录时间、事件时间，并可按 id 取回详情全文；待建索引的条目被追加进结果（上限 20）；一路不可达时用另一路并计一次降级；两路都不可达时抛检索不可用并计一次失败；租户未配置 embedding 时只走关键词且不计失败；索引里残留已删除条目的 id 时回表后不返回；详情读取失败时返回条目自身内容并计一次失败；两路检索收到的过滤条件都含租户与用户，且等于 `build_scope_filter(ctx)` 的结果；已被移出常驻的条目与事件时间已过的条目都能被检索到；每次返回都更新被读条目集合；倒数排名融合的顺序正确。
  **覆盖 AC**: AC-58, AC-59, AC-61, AC-62
  **依赖**: T028

- [ ] **T034**: 检索的实现
  **文件**: `src/backend/bisheng/memory/domain/services/search.py`
  **逻辑**: `search(ctx, query, limit, detail_ids)`：调用 `MemoryIndex` 的两路、倒数排名融合、追加待建索引的条目、回表校验、计数。过滤条件只用 T010 的 `build_scope_filter`。设计见 design 决策 12。
  **测试**: T033 全部通过
  **覆盖 AC**: AC-58, AC-59, AC-61, AC-62
  **依赖**: T033

- [ ] **T035**: 真实索引与模型调用的测试
  **文件**: `src/backend/test/memory/test_index_llm_adapters.py`
  **逻辑**: 用打桩的 ES、Milvus 客户端与 LLM 服务验证适配层：ES 索引名 `bisheng_memory_item`，Milvus collection 名含 embedding 模型 id；写入与检索都带租户与用户过滤；embedding 调用超过 3 秒按超时处理；embedding 与整理的模型调用以记忆主人的用户 id 发起、应用类型为 `memory`、写入 token 用量记录、不触发个人额度扣减；模型调用被拒绝时抛出可识别的失败；整理模型取工作台配置的 `memory_model_id`，未配置时取工作台模型列表的第一个，都没有时抛"无可用模型"；装配函数返回的服务实例使用的是真实的三个实现。
  **覆盖 AC**: AC-45, AC-58
  **依赖**: T020, T034

- [ ] **T036**: 真实索引与模型调用的实现
  **文件**: `src/backend/bisheng/memory/domain/services/index.py`、`src/backend/bisheng/memory/domain/services/llm.py`、`src/backend/bisheng/memory/domain/services/factory.py`
  **逻辑**: `index.py` 是 `MemoryIndex` 的实现，经 `MilvusFactory`、`ElasticsearchFactory` 取客户端，不复用 `core/vectorstore/multi_retriever.py`，写入时在条目上记下 `index_model_id`。`llm.py` 是 `MemoryLLM` 的实现：取模型、发起调用、标记应用类型、记 token 用量；调用路径不经过个人额度扣减（现有额度检查只作用于日常对话与深度研究两种应用类型，见 `dsh/domain/services/chat_credits.py:20-23`，用测试钉住这一点）。`factory.py` 提供 `get_memory_service()` 等装配函数，把真实的索引、详情存储、模型调用装进服务。设计见 design 决策 12、18。
  **测试**: T035 全部通过
  **覆盖 AC**: AC-45, AC-58
  **依赖**: T035

**Wave 5 验收**: `uv run pytest test/memory -q` 全部通过且无 skipped；〔架构检查〕、〔分层检查〕为 `0`；〔基线比对〕为 `NEW FAILURES: 0`。

### Wave 6：管理接口、模型工具与脱敏

- [ ] **T037**: 管理接口的测试
  **文件**: `src/backend/test/memory/test_memory_api.py`
  **逻辑**: 列表只含本人当前租户的有效条目，每条含内容、类型、记录时间、事件时间、来源标记、是否常驻，手动新增的来源为手动添加；新增与编辑超长或含密钥类内容时返回对应错误码且不保存；删除单条、清空、撤销可用；传入他人条目 id 时返回不存在，接口没有按用户 id 取数的参数；"我的记忆"为关时全部接口照常；修改"我的记忆"只影响本人且只有本人能改；上报时区只在值变化时写库；按 `turn_id` 或消息 id 取回的归因分两部分：检索取回的条目与常驻快照的条目；非主人取回为空；按 `chat_id` 批量取回本人在该会话各条消息的记忆标志（有操作提示、有归因、`turn_id`），供前端加载历史消息时使用；`/api/v1/memory` 下没有任何返回指标或统计的接口。
  **覆盖 AC**: AC-08, AC-09, AC-68, AC-87, AC-88, AC-89, AC-90, AC-103
  **依赖**: T030, T032, T034

- [ ] **T038**: 管理接口的实现
  **文件**: `src/backend/bisheng/memory/api/endpoints/memory.py`、`src/backend/bisheng/memory/api/router.py`、`src/backend/bisheng/api/router.py`
  **逻辑**: `/api/v1/memory` 下：条目列表、新增、编辑、删除、清空、读取与修改"我的记忆"、上报时区、按 `turn_id` 或消息 id 取操作提示与归因、按 `chat_id` 批量取记忆标志、撤销。登录态取主体，委托 Service，`UnifiedResponseModel` 包装，在主路由注册。
  **测试**: T037 全部通过
  **覆盖 AC**: AC-08, AC-09, AC-68, AC-87, AC-88, AC-89, AC-90, AC-103
  **依赖**: T037

- [ ] **T039**: 工具工厂与脱敏函数的测试
  **文件**: `src/backend/test/memory/test_tools.py`
  **逻辑**: 工厂返回 `memory_write` 与 `memory_search` 两个工具；工具说明里含用户时区下的今天日期（时区取不到时用部署默认时区），并写明只在用户当前这句话明确要求时写入；`memory_write` 三种动作各自调用到服务并返回含 `ok`、原因码、条目 id 的结果；写入被拒时返回原因码；`memory_search` 把取回的 id 记入本轮检索记录，结果以背景信息说明开头且每条带记录日期；检索不可用时工具返回错误说明而不是抛出，并计一次失败；脱敏函数把名称以 `memory_` 开头的工具的入参与返回替换为只含 `redacted`、动作、条目 id 的结构，其他工具原样返回；脱敏结果里不含条目内容；回放用的中性说明文本生成函数；与记忆工具同名的外部工具被识别出来。
  **覆盖 AC**: AC-09, AC-14, AC-57, AC-61
  **依赖**: T030, T034

- [ ] **T040**: 工具工厂与脱敏函数的实现
  **文件**: `src/backend/bisheng/memory/domain/services/tools.py`、`src/backend/bisheng/memory/domain/services/redaction.py`
  **逻辑**: `build_memory_tools(ctx)`；`redact_tool_event(name, payload)`；`replay_placeholder()`；`is_memory_tool(name)`（`memory_` 为保留前缀）。设计见 design 决策 10。
  **测试**: T039 全部通过
  **覆盖 AC**: AC-09, AC-14, AC-57, AC-61
  **依赖**: T039

**Wave 6 验收**: `uv run pytest test/memory -q` 全部通过且无 skipped；〔架构检查〕、〔分层检查〕为 `0`；〔基线比对〕为 `NEW FAILURES: 0`。

### Wave 7：自动整理

- [ ] **T041**: 活跃登记与水位的测试
  **文件**: `src/backend/test/memory/test_activity.py`
  **逻辑**: `end_turn(enabled=true)` 使登记行待整理；`end_turn(enabled=false)` 推进水位；水位只增不减（整理结束与 `end_turn(enabled=false)` 交错执行，结果取较大者）；整理期间来了新消息时，结束后登记行仍为待整理；安静期内的行不被"到期查询"选中，过了安静期才被选中；有退避时间且未到的行不被选中；运行中状态超过锁时限的行被重新选中；同步版本与异步版本结果一致。
  **覆盖 AC**: AC-37, AC-38, AC-40, AC-41
  **依赖**: T022

- [ ] **T042**: 活跃登记的实现
  **文件**: `src/backend/bisheng/memory/domain/services/activity.py`、`src/backend/bisheng/memory/domain/repositories/cursor_repository.py`
  **逻辑**: `MemoryActivity.end_turn` 的异步与同步实现；选取到期登记行并按用户分组的查询；全部用按列的条件更新。设计见 design 决策 7。
  **测试**: T041 全部通过
  **覆盖 AC**: AC-37, AC-38, AC-40, AC-41
  **依赖**: T041

- [ ] **T043**: 整理调度语义的测试
  **文件**: `src/backend/test/memory/test_consolidator_run.py`
  **逻辑**: 任务一次处理该用户所有到期的会话；拿不到用户锁时不处理且不改登记行；锁带令牌，运行中续期，释放时只释放自己持有的锁；条目落库与水位推进在同一事务，模拟中途异常后重跑不产生重复条目；同一段对话处理两次只落一次；整理失败时记录失败并计数，登记行保持待整理并带退避时间，之后可重跑；"没有可用的整理模型"与"模型调用被拒绝"都按失败处理；会话已软删除或开关在整理前被关闭时，把水位推到当前且不产生条目；同一原因连续失败时只在首次和之后每小时记一次日志；内容处理以可注入的函数传入，本测试用假的内容处理函数；两个用户的整理并发进行互不影响，同一用户两个节点同时触发时只有一个在处理且两边的显式写入都保留。
  **覆盖 AC**: AC-39, AC-41, AC-44, AC-45
  **依赖**: T042, T036

- [ ] **T044**: 整理调度语义的实现
  **文件**: `src/backend/bisheng/memory/domain/services/consolidator.py`
  **逻辑**: `consolidate_user(tenant_id, user_id)`：取锁与续期、逐会话重新做启用判定、确定本次终点、调用以参数注入的内容处理函数（真实实现在 T046，装配在 `factory.py`）、事务内落库并推进水位、失败退避与日志节流。设计见 design 决策 7。
  **测试**: T043 全部通过
  **覆盖 AC**: AC-39, AC-41, AC-44, AC-45
  **依赖**: T043

- [ ] **T045**: 整理内容处理的测试
  **文件**: `src/backend/test/memory/test_consolidator_content.py`
  **逻辑**: 用桩模型返回固定候选：只读取水位之后、本次终点之前的非任务消息，`category='task'` 的行被跳过；候选不合规（超长、密钥类、相对时间）被丢弃且不影响其余候选；模型标为"与某条重复"的候选不新增，标为"与某条矛盾"的候选新增并把旧条目标为已被取代；自动整理的条目来源为自动整理，场景与应用取自会话的类型与应用 id；助手、工作流、日常模式三种会话都能处理；工作流会话只取使用者输入与工作流输出的消息；整理提出的常驻调整被执行且常驻不超过上限。
  **覆盖 AC**: AC-04, AC-39, AC-42
  **依赖**: T044

- [ ] **T046**: 整理内容处理的实现
  **文件**: `src/backend/bisheng/memory/domain/services/consolidation_content.py`、`src/backend/bisheng/memory/domain/services/consolidation_prompt.py`
  **逻辑**: 读增量消息并按场景筛选；组织提示词；经 `MemoryLLM` 调用；候选过 `guard`；与现有有效条目比对后产出"新增、取代、调整常驻"的操作清单，交 T044 在事务里执行。
  **测试**: T045 全部通过
  **覆盖 AC**: AC-04, AC-39, AC-42
  **依赖**: T045

- [ ] **T047**: 定时任务的测试
  **文件**: `src/backend/test/memory/test_worker_tasks.py`
  **逻辑**: 扫描任务在没有租户上下文时能跨租户枚举到期登记行，为每个用户投一个带租户头的整理任务；部署配置里的安静期与扫描周期改变后行为随之改变；自动整理总开关为关时不投任务；对账任务补建待建索引的条目、把 `index_model_id` 与租户当前 embedding 模型不一致的有效条目重建索引、删除没有对应条目行的详情对象；指标落库任务把 Redis 计数写入日表并更新条目上的两个时间列；清理任务删除遗留的本轮记录；后三个任务逐租户设置上下文后再处理。
  **覆盖 AC**: AC-43, AC-102
  **依赖**: T046, T024, T026

- [ ] **T048**: 定时任务的实现
  **文件**: `src/backend/bisheng/worker/memory/tasks.py`（新建，含 `__init__.py`）、`src/backend/bisheng/memory/domain/services/reconcile.py`（新建）、`src/backend/bisheng/core/config/settings.py`
  **逻辑**: 对账的业务逻辑（补建索引、换模型后重建、清理孤儿详情对象）放在 `reconcile.py`，任务文件只负责调度。扫描、整理、对账、指标落库、遗留清理五个任务，走默认 `celery` 队列；Beat 调度项按现有方式追加。**租户传递**：扫描、对账、指标落库、遗留清理四个任务的跨租户枚举查询包在 `bypass_tenant_filter()` 里，之后逐租户调用 `set_current_tenant_id()` 再处理；投整理任务时 `apply_async(args=[tenant_id, user_id], headers={"tenant_id": tenant_id})`，由 `task_prerun` 恢复租户上下文。`settings.py` 只追加调度项，不导入记忆模块（任务以字符串名引用）。
  **测试**: T047 全部通过
  **覆盖 AC**: AC-43, AC-102
  **依赖**: T047

**Wave 7 验收**: `uv run pytest test/memory -q` 全部通过且无 skipped；〔架构检查〕、〔分层检查〕为 `0`；〔基线比对〕为 `NEW FAILURES: 0`。

### Wave 8：接入日常模式

- [ ] **T049**: 日常模式带入与工具的测试
  **文件**: `src/backend/test/workstation/test_memory_inject.py`
  **逻辑**: 用桩模型驱动一轮：登录态 endpoint 调用后会话被登记；已登记且启用时系统提示词含常驻记忆文本块，工具列表含两个记忆工具；直接调用服务函数而不经登录态 endpoint（模拟开放面入口）时两者都没有；无工具直连分支同样带上常驻记忆；带入失败时本轮回答仍完成并计一次失败；在别的场景记下的条目出现在日常模式新会话的常驻文本里。
  **覆盖 AC**: AC-03, AC-10, AC-27, AC-28, AC-51, AC-61
  **依赖**: T040, T032

- [ ] **T050**: 日常模式带入与工具的实现
  **文件**: `src/backend/bisheng/workstation/api/endpoints/chat.py`、`src/backend/bisheng/workstation/domain/services/chat_service.py`
  **逻辑**: endpoint 里调 `MemoryGate.open`；`_agent_stream_chat_completion` 开头做启用判定并生成 `turn_id`；系统提示词拼装处（`chat_service.py:2099-2111` 之后）追加常驻文本块，直连分支（`:2407-2411`）同样处理；`_prepare_tools` 的调用处追加记忆工具。
  **测试**: T049 全部通过
  **覆盖 AC**: AC-03, AC-10, AC-27, AC-28, AC-51, AC-61
  **依赖**: T049

- [ ] **T051**: 日常模式事件与一轮结束的测试
  **文件**: `src/backend/test/workstation/test_memory_events.py`
  **逻辑**: 模型调用 `memory_write` 成功后流里出现 `memory` 类别的事件，载荷含 `turn_id` 与标志、不含条目内容；一轮里只带入了常驻记忆或只做了检索、没有显式写入时，结束前同样下发带"有归因"标志的事件，并已写入本轮概要行（含常驻版本与日期）；落库消息的 `events` 里记忆工具的入参与返回已脱敏；流式下发的工具事件同样已脱敏；正常结束时本轮记录绑定到回答的消息 id，登记行变为待整理；中断路径同样完成绑定与登记；记忆未启用的一轮结束时水位被推进。
  **覆盖 AC**: AC-09, AC-21, AC-37, AC-41, AC-87
  **依赖**: T050, T042

- [ ] **T052**: 日常模式事件与一轮结束的实现
  **文件**: `src/backend/bisheng/workstation/domain/services/chat_service.py`、`src/backend/bisheng/workstation/domain/services/chat_helpers.py`
  **逻辑**: 工具事件写入 `events` 与下发前（`chat_service.py:2311-2319`、`:2343-2344`）调脱敏函数；`_sse_resp` 增加 `memory` 类别；一轮结束前写本轮概要行并下发归因标志；正常结束（`:2558-2575`）与中断路径（`:1955-1980`，同步函数，用同步实现）调 `bind_turn` 与 `end_turn`。
  **测试**: T051 全部通过
  **覆盖 AC**: AC-09, AC-21, AC-37, AC-41, AC-87
  **依赖**: T051

**Wave 8 验收**: `uv run pytest test/memory test/workstation/test_memory_config.py test/workstation/test_memory_inject.py test/workstation/test_memory_events.py -q` 全部通过且无 skipped；〔架构检查〕、〔分层检查〕为 `0`；〔基线比对〕为 `NEW FAILURES: 0`。

### Wave 9：接入助手

实现位置以 T002、T003、T006 的结论为准。

- [ ] **T053**: 助手每轮处理的测试
  **文件**: `src/backend/test/assistant/test_memory_turn.py`
  **逻辑**: 用桩模型在 ReAct 与 function call 两种执行器下各跑：新建助手开关默认关，不带入常驻记忆、没有记忆工具；开关打开且已登记时，每轮输入里含常驻记忆系统消息、工具列表里有记忆工具，作者没有配置任何工具也如此；同一个 `AssistantAgent` 对象上，数据库里的开关被关掉后下一轮不再带入且工具消失，再打开后恢复且之前的条目可读；历史超长触发裁剪时常驻记忆仍在输入里；`run()` 返回值里不含注入的系统消息；带入失败时本轮仍完成并计一次失败；作者配置了与记忆工具同名的工具时以记忆工具为准并记一条告警；用户乙在同一个助手里读不到用户甲的条目；没有登记行时记忆不工作。
  **覆盖 AC**: AC-02, AC-10, AC-51, AC-61, AC-71, AC-72, AC-73, AC-74, AC-77
  **依赖**: T040, T032

- [ ] **T054**: 助手每轮处理的实现
  **文件**: `src/backend/bisheng/api/services/assistant_agent.py`
  **逻辑**: `run` / `astream` 开头：按主键重读 `assistant.memory_enabled`、做启用判定、状态与上一轮不同则重建 agent；裁剪之后插入常驻记忆系统消息；返回前剔除注入的系统消息。`init_tools` 在启用时追加记忆工具并处理同名工具。设计见 design 决策 11、10。
  **测试**: T053 全部通过
  **覆盖 AC**: AC-02, AC-10, AC-51, AC-61, AC-71, AC-72, AC-73, AC-74, AC-77
  **依赖**: T053

- [ ] **T055**: 助手工具事件脱敏与信号的测试
  **文件**: `src/backend/test/assistant/test_memory_redaction.py`
  **逻辑**: 调用一次记忆工具后：由 `run()` 返回值构造的 tool_call、tool_result 行里内容已脱敏；回调插入的 `category=tool` 行与 `intermediate_steps` 字段里内容已脱敏；回调经 WebSocket 下发的工具消息里内容已脱敏；非记忆工具的三处内容不变；下一轮回放历史时，记忆工具的结果被渲染成中性说明；显式写入成功后经 WebSocket 下发一条 `memory` 消息，载荷含 `turn_id` 与标志、不含条目内容；只带入常驻或只检索的一轮同样下发带"有归因"标志的消息并写入本轮概要行。
  **覆盖 AC**: AC-09, AC-21, AC-87
  **依赖**: T054

- [ ] **T056**: 助手工具事件脱敏与信号的实现
  **文件**: `src/backend/bisheng/api/v1/callback.py`、`src/backend/bisheng/api/services/assistant_agent.py`
  **逻辑**: 回调处理器在工具开始时按 `run_id` 记下是否为记忆工具，在结束、出错、下发、落库处调脱敏函数；`AssistantAgent` 在返回前对结果里的记忆工具消息脱敏，并在回放历史时替换为中性说明；每轮写本轮概要行；有显式写入或归因时通过现有回调下发 `memory` 消息。
  **测试**: T055 全部通过
  **覆盖 AC**: AC-09, AC-21, AC-87
  **依赖**: T055

- [ ] **T057**: 助手登记与一轮结束的测试
  **文件**: `src/backend/test/assistant/test_memory_session.py`
  **逻辑**: 登录态连接在 `chat_id` 确定时被登记，连接内切换到另一个会话后新会话也被登记；免登录与开放面的连接无论如何切换都不产生登记行；回答落库后本轮记录绑定到消息 id，登记行变为待整理；中断落库时同样；记忆未启用的一轮结束时水位被推进；助手会话在安静期后能被整理出条目；只有对助手有编辑权限的用户能修改 `memory_enabled`，新建助手该字段为关。
  **覆盖 AC**: AC-10, AC-37, AC-42, AC-69
  **依赖**: T056, T046

- [ ] **T058**: 助手登记与一轮结束的实现
  **文件**: `src/backend/bisheng/common/chat/client.py`、`src/backend/bisheng/api/services/assistant_agent.py`、登录态助手 WebSocket endpoint 所在文件（以 T003 的结论为准）、`src/backend/bisheng/api/v1/schemas.py`、`src/backend/bisheng/api/services/assistant.py`
  **逻辑**: 登录态 endpoint 构造客户端时传入登记回调（一个可调用对象）。`client.py` 做两件事：`chat_id` 确定或切换时调用该回调；回答落库后（正常与中断）调用 `self.gpts_agent.after_answer_persisted(message_id, interrupted)`。`client.py` 里不出现对记忆模块的导入。`AssistantAgent.after_answer_persisted` 里调 `bind_turn` 与 `end_turn`。助手更新是逐字段白名单：`AssistantUpdateReq`（`api/v1/schemas.py`）加 `memory_enabled`，`api/services/assistant.py` 的更新逻辑逐字段赋值处同样加上，详情返回带出该字段。沿用现有编辑权限检查。
  **测试**: T057 全部通过
  **覆盖 AC**: AC-10, AC-37, AC-42, AC-69
  **依赖**: T057

- [ ] **T059**: 删除助手相关的实验测试
  **文件**: `src/backend/test/memory/spike/test_v1_callback.py`、`src/backend/test/memory/spike/test_v5_assistant_inject.py`
  **逻辑**: 这两个实验测试的结论已由 T053–T058 的正式测试覆盖，删除它们。
  **依赖**: T058

**Wave 9 验收**: `uv run pytest test/memory test/assistant/test_memory_turn.py test/assistant/test_memory_redaction.py test/assistant/test_memory_session.py -q` 全部通过且无 skipped；〔架构检查〕、〔分层检查〕为 `0`；〔基线比对〕为 `NEW FAILURES: 0`。

### Wave 10：接入工作流

实现位置以 T003、T005 的结论为准。

- [ ] **T060**: 记忆检索节点的测试
  **文件**: `src/backend/test/workflow/test_memory_retriever_node.py`
  **逻辑**: 节点类型已注册，同一工作流可放多个；`query` 可为纯文字、纯变量引用、两者混写，引用的变量不是文字时转成文字；`limit` 默认 20，节点的参数校验对 1 到 100 以外的整数与非整数返回检索数量参数非法的错误码；执行时只在当前使用者本人的记忆里检索，包含在其他场景产生的条目，按相关程度排序且不超过 `limit`；输出每一项含内容、类型、记录时间、来源标记，有事件时间的带事件时间，带详情的内容为详情全文，每项内容以背景信息前缀与记录日期开头；没有命中、运行时 `query` 为空、没有登记、"我的记忆"为关、工作流开关为关时输出空数组且节点正常结束；检索不可用时节点失败并给出原因；运行日志含检索内容与返回条数、不含条目内容；两个用户运行同一工作流各自只得到本人的条目；节点不写本轮记录；工作流的其他节点没有收到常驻记忆；工作流运行中没有任何记忆写入能力（没有 `memory_write`）。测试里直接给 `graph_state` 的两个只读字段赋值。
  **覆盖 AC**: AC-02, AC-28, AC-57, AC-60, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83, AC-84, AC-86
  **依赖**: T034, T022

- [ ] **T061**: 记忆检索节点的实现
  **文件**: `src/backend/bisheng/workflow/nodes/memory_retriever/memory_retriever.py`（新建，含 `__init__.py`）、`src/backend/bisheng/workflow/common/node.py`、`src/backend/bisheng/workflow/nodes/node_manage.py`、`src/backend/bisheng/workflow/graph/graph_state.py`
  **逻辑**: 新增 `NodeType.MEMORY_RETRIEVER` 与节点类；参数校验函数；`graph_state` 增加 `chat_id` 与 `memory_enabled` 两个只读字段（默认空与关，T063 负责在实例化时填值）；`_run` 从 `graph_state` 取 `chat_id` 与开关，过启用判定后调检索；`parse_log` 返回检索内容与返回条数。输出变量 `retrieved_memory`，结构见 design §4.2。
  **测试**: T060 全部通过
  **覆盖 AC**: AC-02, AC-28, AC-57, AC-60, AC-78, AC-79, AC-80, AC-81, AC-82, AC-83, AC-84, AC-86
  **依赖**: T060

- [ ] **T062**: 工作流开关与上线校验的测试
  **文件**: `src/backend/test/workflow/test_memory_switch.py`
  **逻辑**: 新建工作流的开始节点里记忆开关为关；开关随工作流版本保存，没有该参数的历史版本按关处理；上线时：含记忆检索节点而开关为关被拒并返回对应错误码，开关为开时可上线，节点的 `limit` 非法被拒；运行时的开关取自数据库里的上线版本，客户端送来一个开关为开的图而数据库为关时节点输出空数组；只有对工作流有编辑权限的用户能保存开关。
  **覆盖 AC**: AC-70, AC-71, AC-80, AC-85
  **依赖**: T061

- [ ] **T063**: 工作流开关与上线校验的实现
  **文件**: `src/backend/bisheng/workflow/graph/graph_engine.py`、`src/backend/bisheng/api/services/workflow.py`
  **逻辑**: 实例化时按 `flow_id` 读上线版本的开始节点参数 `memory_enabled`，与 `chat_id` 一起填进 `graph_state` 的两个只读字段；`update_flow_status` 的上线分支加两项校验（开关、`limit`）。保存时的 `limit` 校验在前端（T077），后端以上线时为准。
  **测试**: T062 全部通过
  **覆盖 AC**: AC-70, AC-71, AC-80, AC-85
  **依赖**: T062

- [ ] **T064**: 工作流登记与一轮结束的测试
  **文件**: `src/backend/test/workflow/test_memory_session.py`
  **逻辑**: 登录态运行在拿到消息体里的 `chat_id` 时被登记；免登录与开放面运行不产生登记行；评测与调试运行（`chat_id` 为空）不登记、节点输出空数组；任务函数停在等待输入返回时登记一次活跃，成功或失败结束时各登记一次；记忆未启用时水位被推进；工作流会话在安静期后能被整理出条目。
  **覆盖 AC**: AC-10, AC-37, AC-42
  **依赖**: T063, T046

- [ ] **T065**: 工作流登记与一轮结束的实现
  **文件**: `src/backend/bisheng/common/chat/clients/workflow_client.py`、`src/backend/bisheng/worker/workflow/tasks.py`、登录态工作流 WebSocket endpoint 所在文件（以 T003 的结论为准）
  **逻辑**: 登录态 endpoint 构造客户端时传入登记回调；`workflow_client.py` 在拿到 `chat_id` 时调用它，文件里不出现对记忆模块的导入；任务函数每次让出控制时调 `end_turn`。
  **测试**: T064 全部通过
  **覆盖 AC**: AC-10, AC-37, AC-42
  **依赖**: T064

- [ ] **T066**: 删除工作流相关的实验测试
  **文件**: `src/backend/test/memory/spike/test_v4_graph_state.py`
  **逻辑**: 结论已由 T060–T065 的正式测试覆盖，删除。
  **依赖**: T065

**Wave 10 验收**: `uv run pytest test/memory test/workflow/test_memory_retriever_node.py test/workflow/test_memory_switch.py test/workflow/test_memory_session.py -q` 全部通过且无 skipped；〔架构检查〕、〔分层检查〕为 `0`；〔基线比对〕为 `NEW FAILURES: 0`。

### Wave 11：接入深度研究

实现位置以 T004、T008 的结论为准。

- [ ] **T067**: 深度研究登记与轮次的测试
  **文件**: `src/backend/test/linsight/test_memory_turns.py`
  **逻辑**: 三个登录态 endpoint（提交、继续、补充输入）调用后会话被登记；开放面与无人值守运行不登记；每一轮（首次提交与每次追问）开始时各建一条本轮概要并有各自的 `turn_id`；每一轮结束（成功、部分完成、终止、直接回答四种）各登记一次活跃；记忆未启用时不建概要。
  **覆盖 AC**: AC-10, AC-37
  **依赖**: T042, T026

- [ ] **T068**: 深度研究登记与轮次的实现
  **文件**: `src/backend/bisheng/linsight/api/endpoints/linsight.py`、`src/backend/bisheng/linsight/domain/task_exec.py`
  **逻辑**: 三个 endpoint 调 `MemoryGate.open`；任务开始处做启用判定、建本轮概要行；四个结束点调 `end_turn`。只加调用，不改既有流程。
  **测试**: T067 全部通过
  **覆盖 AC**: AC-10, AC-37
  **依赖**: T067

- [ ] **T069**: 深度研究带入与工具的测试
  **文件**: `src/backend/test/linsight/test_memory_inject.py`
  **逻辑**: 用桩模型：已登记且启用时，模型每次调用收到的提示词末段含常驻记忆与经验类条目；文本在任务开始时取一次，任务中途条目变化不改变它；记忆中间件排在引用与语言两个尾部中间件之前；首次执行、恢复、继续三条路径的工具列表里都有记忆工具，提示词里同步出现工具的使用说明；未登记时都没有；带入失败时任务仍继续并计一次失败；显式写入成功后下发记忆事件；只带入或只检索的一轮结束时下发带"有归因"标志的事件。
  **覆盖 AC**: AC-21, AC-28, AC-51, AC-55, AC-61, AC-87
  **依赖**: T068, T040

- [ ] **T070**: 深度研究带入与工具的实现
  **文件**: `src/backend/bisheng/linsight/domain/services/agent_factory.py`、`src/backend/bisheng/linsight/domain/task_exec.py`、`src/backend/bisheng/linsight/domain/services/state_message_manager.py`
  **逻辑**: 新增记忆中间件（`wrap_model_call` 追加，文本任务开始时取一次，排在两个尾部中间件之前）；`_generate_tools` 的三个调用点之后追加记忆工具，并按 `linsight/AGENTS.md` 让提示词与工具同步出现；`MessageEventType` 增加记忆事件，在显式写入成功后与一轮结束有归因时下发。
  **测试**: T069 全部通过
  **覆盖 AC**: AC-21, AC-28, AC-51, AC-55, AC-61, AC-87
  **依赖**: T069

- [ ] **T071**: 深度研究脱敏的测试
  **文件**: `src/backend/test/linsight/test_memory_redaction.py`
  **逻辑**: 调用一次记忆工具后：步骤事件写入任务历史的内容里记忆工具的入参与返回已脱敏；触发一次上下文压缩后写出的工作区文件里没有条目内容；大工具结果卸载路径不会把记忆工具的结果写成工作区文件；分享链接读取任务详情所走的接口返回里没有条目内容；非记忆工具的内容不变。
  **覆盖 AC**: AC-09
  **依赖**: T070

- [ ] **T072**: 深度研究脱敏的实现
  **文件**: `src/backend/bisheng/linsight/domain/services/stream_event_mapper.py`、`src/backend/bisheng/linsight/domain/utils.py`（及 T004 列出的其他落点文件）
  **逻辑**: T004 列出的每个落点在写出前调脱敏函数。
  **测试**: T071 全部通过
  **覆盖 AC**: AC-09
  **依赖**: T071

- [ ] **T073**: 深度研究轮次整理的测试
  **文件**: `src/backend/test/memory/test_consolidator_linsight.py`
  **逻辑**: 用桩模型：一个任务追问两次后，三轮各有一条本轮概要、各被整理一次且只一次；每一轮读到的是该轮自己的问题与结果；进行中或停在等待用户补充的轮不整理；超过 24 小时未结束的轮被标记为放弃且不再尝试；整理出的条目来源为深度研究；同一会话里的日常消息仍按消息水位整理，两种方式互不干扰。
  **覆盖 AC**: AC-39, AC-42
  **依赖**: T068, T046

- [ ] **T074**: 深度研究轮次整理的实现
  **文件**: `src/backend/bisheng/memory/domain/services/consolidation_linsight.py`（新建）、`src/backend/bisheng/memory/domain/services/consolidator.py`
  **逻辑**: 找出该用户未整理的深度研究轮（本轮概要行的 `consolidated` 标志），按 T008 的方法读取每一轮的问题与结果，交内容处理，处理后置位；超时放弃。`consolidator.py` 里加一步调用。读取深度研究数据通过深度研究模块的 Service 方法，不直接查它的表。
  **测试**: T073 全部通过
  **覆盖 AC**: AC-39, AC-42
  **依赖**: T073

- [ ] **T075**: 删除深度研究相关的实验测试
  **文件**: `src/backend/test/memory/spike/test_v3_linsight_paths.py`
  **逻辑**: 结论已由 T071、T072 覆盖，删除；`test/memory/spike/` 目录此时应为空，一并删除。
  **依赖**: T072

**Wave 11 验收**: `uv run pytest test/memory test/linsight/test_memory_turns.py test/linsight/test_memory_inject.py test/linsight/test_memory_redaction.py -q` 全部通过且无 skipped；`ls src/backend/test/memory/spike` 报不存在；〔架构检查〕、〔分层检查〕为 `0`；〔基线比对〕为 `NEW FAILURES: 0`。

### Wave 12：前端 Platform

每个任务带 Vitest 测试。测试命令的工作目录是 `src/frontend/platform/`；lint、类型检查与 i18n 检查在 `src/frontend/`。新增文案三语同批加入，源码里不写中文字面量。

- [ ] **T076**: 工作流的记忆检索节点模板
  **文件**: `src/frontend/platform/src/controllers/API/workflow.ts`、`src/frontend/platform/src/pages/BuildPage/flow/FlowNode/NodeLogo.tsx`、`src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/flow.json`
  **逻辑**: `workflowTemplate` 增加 `memory_retriever` 节点：`query` 用 `var_textarea` 控件、必填；`limit` 用 `number` 控件、默认 20；输出 `retrieved_memory`。图标与三语文案。
  **测试**: `src/frontend/platform/src/pages/BuildPage/flow/__tests__/memoryRetrieverTemplate.test.ts`：模板里有该节点、参数类型与默认值正确、三语文案的 key 都存在。
  **覆盖 AC**: AC-78, AC-79
  **依赖**: T061

- [ ] **T077**: 工作流的开关、参数校验与上线提示
  **文件**: `src/frontend/platform/src/controllers/API/workflow.ts`、`src/frontend/platform/src/pages/BuildPage/flow/hooks/useNodeEvent.ts`、`src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/flow.json`
  **逻辑**: 开始节点增加"记忆"分组与 `memory_enabled` 开关（`switch` 控件，默认关），旁边显示 AC-75 的说明；`limit` 不是 1 到 100 的整数时保存校验不通过并提示合法范围；含记忆检索节点而开关为关时上线校验给出提示。
  **测试**: `src/frontend/platform/src/pages/BuildPage/flow/__tests__/memorySwitchValidate.test.ts`：开关默认关；说明文案存在；`limit` 为 0、101、1.5 时校验失败并带范围提示；开关为关且含该节点时上线校验失败。
  **覆盖 AC**: AC-70, AC-75, AC-80, AC-85
  **依赖**: T076, T063

- [ ] **T078**: 助手设置页的记忆开关
  **文件**: `src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/Setting.tsx`、`AssistantDetail` 类型所在文件（用 `grep -rn "AssistantDetail" src/frontend/platform/src` 定位）、`src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`
  **逻辑**: 参照同页的 `knowledge_auth` 开关新增 `memory_enabled`，默认关，旁边显示 AC-75 的说明；写入 `assistantState`，随现有保存接口提交。
  **测试**: `src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/__tests__/memorySwitch.test.tsx`：默认关；切换后状态里的字段变化；说明文案存在。
  **覆盖 AC**: AC-69, AC-75
  **依赖**: T058

- [ ] **T079**: 工作台配置的整理模型选项
  **文件**: `src/frontend/platform/src/pages/BuildPage/bench/index.tsx`、`src/frontend/platform/src/pages/BuildPage/bench/DailyChatConfig.tsx`、`src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`
  **逻辑**: 新增一项"记忆整理使用的模型"下拉，没有开关；未选择时显示"使用工作台默认模型"。补 `ChatConfigForm` 类型、初始值、加载时合并、保存时的数据四处。
  **测试**: `src/frontend/platform/src/pages/BuildPage/bench/__tests__/memoryConfig.test.tsx`：下拉的值进入保存数据的 `memory_model_id`；未选择时保存为空；页面上没有记忆开关。
  **覆盖 AC**: AC-106
  **依赖**: T020

- [ ] **T080**: 管理端查看会话时的记忆操作占位
  **文件**: T007 指出的渲染组件（预期为 `src/frontend/platform/src/components/bs-comp/appChat/PlatformConversationMessages.tsx` 与 `src/frontend/platform/src/pages/LogPage/useAppLog/DailyMessageContent.tsx`）、`src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`
  **逻辑**: 渲染到脱敏后的记忆工具事件（含 `redacted: true`）时显示"记忆操作"占位，不显示其他内容。这些页面不调用任何 `/api/v1/memory` 接口。
  **测试**: `src/frontend/platform/src/pages/LogPage/__tests__/memoryPlaceholder.test.tsx`：给定一条含脱敏记忆工具事件的消息，渲染结果只有占位文案；渲染过程中没有对 `/api/v1/memory` 的请求。
  **覆盖 AC**: AC-09
  **依赖**: T052, T056

**Wave 12 验收**: `cd src/frontend/platform && pnpm exec vitest run memoryRetrieverTemplate memorySwitchValidate memorySwitch memoryConfig memoryPlaceholder` 全部通过；`cd src/frontend && pnpm lint && pnpm typecheck && pnpm check-i18n` 退出码为 0。

### Wave 13：前端 Client

每个任务带 Jest 测试。测试命令的工作目录是 `src/frontend/client/`。不要为了跑测试执行 `pnpm install`（见 `src/frontend/client/AGENTS.md`）。新增文案三语同批加入 `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`。

- [ ] **T081**: 记忆接口封装、时区上报与流式信号
  **文件**: `src/frontend/client/src/api/memory.ts`（新建）、`src/frontend/client/src/hooks/useMemoryTimezone.ts`（新建）、`src/frontend/client/src/hooks/useAiChatSSE.ts`
  **逻辑**: 封装 `/api/v1/memory` 的全部接口。应用加载后取浏览器的 IANA 时区，与本地记住的上次上报值不同才调用上报接口；这一处覆盖日常模式、应用聊天与深度研究，对话请求本身不带时区。SSE 解析增加 `memory` 类别，把 `turn_id` 与标志写入消息状态。加载一个会话的历史消息时，按 `chat_id` 批量取记忆标志并合并进消息状态。
  **测试**: `src/frontend/client/src/api/__tests__/memory.test.ts`：各接口的路径与参数；时区未变时不重复上报、变化时上报；收到 `memory` 事件后消息状态里有 `turn_id`；加载历史后带标志的消息状态里有标志。
  **覆盖 AC**: AC-14, AC-21
  **依赖**: T038, T052

- [ ] **T082**: 个人设置的记忆页
  **文件**: `src/frontend/client/src/pages/settings/sections/MemoryPane.tsx`（新建）、`src/frontend/client/src/pages/settings/settingsSections.ts`、`src/frontend/client/src/pages/settings/SettingsPage.tsx`
  **逻辑**: 新增"记忆" section：顶部是"我的记忆"开关；下面是条目列表（内容、类型、记录时间、事件时间、来源、是否常驻），支持编辑、新增、删除、清空（二次确认）。新增与编辑被拒时显示接口返回的原因。文案进三语文件。
  **测试**: `src/frontend/client/src/pages/settings/sections/__tests__/MemoryPane.test.tsx`：列表渲染各字段；手动新增的条目来源显示为手动添加；清空需要二次确认；"我的记忆"关闭后列表与全部操作仍可用；被拒时显示原因。
  **覆盖 AC**: AC-68, AC-88, AC-89, AC-90
  **依赖**: T081

- [ ] **T083**: 操作提示与归因组件
  **文件**: `src/frontend/client/src/components/Chat/MemoryNotice.tsx`（新建）、`src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`
  **逻辑**: 给定 `turn_id` 或消息 id：显示操作提示（记下、更正、忘掉三种），可展开看到条目原文并撤销，撤销失败时显示接口返回的原因；归因入口展开后分两部分：检索取回的条目逐条列出、常驻记忆整份查看，每条可就地删除。没有任何记忆标志时不渲染。
  **测试**: `src/frontend/client/src/components/Chat/__tests__/MemoryNotice.test.tsx`：有写入标志时出现提示，展开后显示接口返回的条目；撤销调用接口并在成功后更新显示，失败时显示原因；归因分两部分；就地删除调用接口；没有标志时不渲染。
  **覆盖 AC**: AC-21, AC-22, AC-87
  **依赖**: T081

- [ ] **T084**: 日常模式气泡接入
  **文件**: `src/frontend/client/src/components/Chat/AiMessageBubble.tsx`、`src/frontend/client/src/components/Chat/Messages/ToolCallDisplay.tsx`
  **逻辑**: 气泡操作区挂 `MemoryNotice`；脱敏后的记忆工具事件在工具卡片里显示为"记忆操作"。
  **测试**: `src/frontend/client/src/components/Chat/__tests__/memoryBubble.test.tsx`：带标志的消息渲染出 `MemoryNotice`；脱敏的工具事件渲染为占位、不显示原始结构。
  **覆盖 AC**: AC-21, AC-87
  **依赖**: T083

- [ ] **T085**: 应用聊天接入
  **文件**: `src/frontend/client/src/pages/appChat/components/ClientMessageFooter.tsx`、`src/frontend/client/src/pages/appChat/useWebsocket.ts`
  **逻辑**: 解析 WebSocket 的 `memory` 消息；助手聊天的消息底部挂 `MemoryNotice`。工作流聊天不显示归因。
  **测试**: `src/frontend/client/src/pages/appChat/__tests__/memoryFooter.test.tsx`：收到 `memory` 消息后助手的回答底部出现提示与归因入口；工作流的回答不出现归因入口。
  **覆盖 AC**: AC-21, AC-87
  **依赖**: T083, T056

- [ ] **T086**: 深度研究结果面板接入
  **文件**: `src/frontend/client/src/components/Linsight/Execution/ResultPanel.tsx`、`src/frontend/client/src/components/Linsight/Execution/TaskTurnPanel.tsx`
  **逻辑**: 每一轮的结果面板按该轮的 `turn_id` 挂 `MemoryNotice`，与点赞操作并列。`turn_id` 的来源以 T008 的结论为准。
  **测试**: `src/frontend/client/src/components/Linsight/Execution/__tests__/memoryResult.test.tsx`：一个任务的两轮各自显示各自的提示与归因，互不混淆。
  **覆盖 AC**: AC-21, AC-87
  **依赖**: T083, T070

**Wave 13 验收**: `cd src/frontend/client && pnpm exec jest --ci api/__tests__/memory MemoryPane MemoryNotice memoryBubble memoryFooter memoryResult` 全部通过；`cd src/frontend && pnpm lint && pnpm typecheck && pnpm check-i18n` 退出码为 0。

### Wave 14：评测集（〔评〕类验收标准）

这一 Wave 需要真实可用的模型端点。T087、T088 可以本地完成；T089 与 T094 需要 test 环境，**不作为自动化开发的完成条件**。通过线由用户在看到首次结果后确认。

- [ ] **T087**: 评测运行器
  **文件**: `tools/memory_eval/runner.py`、`tools/memory_eval/tests/test_runner.py`（新建，结构参照 `tools/taskmode_eval/`）
  **逻辑**: 用例格式：若干轮预置对话、一个提问、判定规则、所覆盖的 AC 编号。运行器对同一批用例跑两种条件（带记忆、不带记忆），输出每题得分、每条 AC 的通过率与两组对比，并统计两类计数：回答声称已记下而没有成功写入、未经要求而写入。自测用桩模型跑通一条用例。
  **覆盖 AC**: AC-104, AC-105
  **依赖**: T052

- [ ] **T088**: 评测用例
  **文件**: `tools/memory_eval/cases/`（新建）
  **逻辑**: 取材自 bisheng 的真实使用场景，不含真实用户的个人信息。为下列每条验收标准至少写两条用例并标注编号。自测：`tools/memory_eval/tests/test_cases.py` 校验每个用例格式合法，且下列每个编号都至少有两条用例。
  **覆盖 AC**: AC-13, AC-15, AC-17, AC-18, AC-19, AC-20, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-46, AC-47, AC-48, AC-49, AC-63, AC-64, AC-65
  **依赖**: T087

- [ ] **T089**: 首次评测
  **文件**: `features/v3.0.0/132-long-term-memory/verification.md`
  **逻辑**: 在 test 环境用其工作台默认模型跑全部用例，把每条〔评〕类 AC 的通过率、两组得分对比、两类计数写入 `verification.md`，交用户确认通过线。
  **覆盖 AC**: AC-104, AC-105
  **依赖**: T088

**Wave 14 验收（本地部分）**: `uv run pytest -c pyproject.toml --rootdir . ../../tools/memory_eval/tests -q` 通过（工作目录 `src/backend/`）。T089 由人在 test 环境执行。

### Wave 15：P1

- [ ] **T090**: 经验类自动整理的测试
  **文件**: `src/backend/test/memory/test_consolidator_experience.py`、`tools/memory_eval/cases/`（增加两条标注 AC-50 的用例）、`tools/memory_eval/tests/test_cases.py`（把 AC-50 加入必备编号）
  **逻辑**: 用桩模型返回经验类候选：深度研究轮次整理出的经验类条目类型为 experience、不常驻、来源为深度研究；下一个深度研究任务开始时它被带入；日常模式的常驻文本里没有它。
  **覆盖 AC**: AC-50, AC-54, AC-55
  **依赖**: T074

- [ ] **T091**: 经验类自动整理的实现
  **文件**: `src/backend/bisheng/memory/domain/services/consolidation_prompt.py`、`src/backend/bisheng/memory/domain/services/consolidation_linsight.py`
  **逻辑**: 深度研究轮次使用单独的整理提示词，关注用户对产出的固定要求与任务中已验证有效或无效的做法。
  **测试**: T090 全部通过
  **覆盖 AC**: AC-50, AC-54, AC-55
  **依赖**: T090

- [ ] **T092**: 过期事件改写的测试
  **文件**: `src/backend/test/memory/test_consolidator_expired_event.py`、`tools/memory_eval/cases/`（增加两条标注 AC-95 的用例）、`tools/memory_eval/tests/test_cases.py`（把 AC-95 加入必备编号）
  **逻辑**: 用桩模型返回改写后的表述：事件时间已过的有效条目在下一次整理中被新条目取代，新条目保留日期且通过校验，旧条目为已被取代；同一条目不被重复改写。
  **覆盖 AC**: AC-95
  **依赖**: T046

- [ ] **T093**: 过期事件改写的实现
  **文件**: `src/backend/bisheng/memory/domain/services/consolidation_content.py`
  **逻辑**: 整理时找出该用户事件时间已过且未改写的有效条目，交模型改写为过去时，按"更正"落库。
  **测试**: T092 全部通过
  **覆盖 AC**: AC-95
  **依赖**: T092

**Wave 15 验收**: `uv run pytest -c pyproject.toml --rootdir . test/memory ../../tools/memory_eval/tests -q` 全部通过且无 skipped；〔基线比对〕为 `NEW FAILURES: 0`。

### Wave 16：收尾

- [ ] **T094**: test 环境验证与真实模型上的注入兼容性
  **文件**: `features/v3.0.0/132-long-term-memory/verification.md`
  **逻辑**: 在 test 环境按 design §7 的手动验证六步走一遍，用两个非管理员账号加一个租户管理员账号。补完 V5：用 test 环境的工作台默认模型分别在助手的两种执行器下跑一轮，确认带多条系统消息的请求被端点接受且模型用上了常驻记忆。结果写入 `verification.md`。
  **覆盖 AC**: AC-02, AC-03, AC-09, AC-24, AC-66, AC-85
  **依赖**: T086

- [ ] **T095**: 文档回写
  **文件**: `features/v3.0.0/132-long-term-memory/design.md`、`features/v3.0.0/release-contract.md`、`src/backend/AGENTS.md`
  **逻辑**: design §4 从"目标形态"改为实现后的现状，行号按实际更新，修订历史记一行；release-contract 的 F132 段更新状态，候选不变量 INV-44 到 INV-47 转正；`src/backend/AGENTS.md` 的 Quick Map 增加 `memory` 模块一行。
  **依赖**: T094

- [ ] **T096**: 端到端测试
  **文件**: 由 `/e2e-test features/v3.0.0/132-long-term-memory` 生成
  **逻辑**: 生成接口级端到端测试与页面验证清单。需要运行中的后端与中间件，在 test 环境或 CI 的中间件分组里跑。
  **覆盖 AC**: AC-02, AC-03, AC-09, AC-24, AC-66, AC-85
  **依赖**: T095

**Wave 16 验收**: 由人在 test 环境判定。本地可验证的部分：〔架构检查〕、〔分层检查〕为 `0`，〔基线比对〕为 `NEW FAILURES: 0`。

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已确认的决策时，先停下与用户重新确认，再记录。

（暂无）
