# F002 知识模型配置收敛：需求发现

状态：2026-11-27 用户已确认范围，并修正历史溯源兼容要求；尚未修改业务代码。确认后的需求以 [spec.md](./spec.md) 为准。

## 基线与隔离

- 2026-11-27 已执行 `git fetch origin feat/3.1.0`。
- 基线：`49dde8a70d79407c459bdd0d7651754bc9d37002`。
- 分支：`codex/knowledge-model-config-20261127`。
- 工作区：`/private/tmp/bisheng-knowledge-model-config-20261127`。
- 原工作区既有修改保持原样。

## 用户要求

1. 删除系统模型配置 / 其他模型配置中的工作台向量模型，删除修改该配置后重建全部知识空间的逻辑。
2. 将“知识库模型”栏目改为“知识模型”；新建知识空间使用该栏目的默认 embedding 模型。
3. 本栏目中原文档知识库的表述统一为知识空间，修正文案与提示；保留 QA 知识库的概念。
4. 排查溯源模型是否还有使用；无使用时删除配置项。

## 已核实的代码现状

以下结论来自上述基线的静态调用链检查，未对部署环境执行验收。

### 默认 embedding 来源仍然分裂

- `knowledge/application/creation_settings.py:get_space_creation_settings` 从 `linsight_llm` 的 `embedding_model` 提供新建弹窗初值。
- `knowledge/domain/services/knowledge_space_service.py:create_space` 在未显式指定 embedding 时读取相同的工作台配置。
- 同文件 `_prospective_creation_access` 还以工作台 embedding 是否配置作为创建前置条件。
- `knowledge_llm.embedding_model_id` 已存在，也被 QA / 开放 API 默认模型等既有路径使用；此次将新建知识空间统一到这个来源。
- `llm/domain/services/system_model_autofill.py` 仍会分别自动补齐知识 embedding 和工作台 embedding。

### 全量重建后端派发已从本基线退出，前端与探测残留

- `llm/application/model_default.py:_asave` 明确仅保存默认值，不读取或改写既有 Knowledge 根及引用槽。
- `llm/domain/services/llm.py:_save_model_default` 在工作台 embedding 变更时只调用 `aembed_query("test")` 探测，未派发知识空间全量重建。
- `WorkbenchModel.tsx` 仍有 embedding 必填校验、变更检测、全量重建确认弹窗及该选择器。
- 三语 `model.json` 仍声称更换工作台向量模型会重新处理全部空间。
- 工作台 embedding 仍参与配置 schema、自动补齐、模型引用提取与引用目标校验；移除配置时必须同步处理这些直接依赖，不能只隐藏控件。

2026-11-27 对照用户提供的另一 agent 排查截图，追加历史核实：

- 截图描述的“探测 → 全部空间设为重建中 → 派发任务”确实存在于历史实现；`b83e5e9a7c` 的父版本中 `update_workbench_llm` 可见相应实现。
- 2026-11-06 的 `7bd8afa15b825e2ce83b369d05517a9a22d868eb`（`fix(f118): decouple space embeddings and batch app model resolution`）移除了默认配置变更时的空间批量修改计划及 `_dispatch_model_default_commands` 派发。
- `git merge-base --is-ancestor 7bd8afa15b HEAD` 返回成功，该删除已在本次开发基线中。不能将截图作为当前 `feat/3.1.0` 的行为结论；仅凭截图无法确定另一 agent 实际读取的分支或提交。
- `test/knowledge_unification/test_workbench_reference_atomicity.py:test_default_save_does_not_read_or_mutate_existing_spaces_or_bindings` 已有对应回归用例，覆盖 0 / 1 / 25 个空间时保存默认值不读写空间、返回无后台任务。这里只核查测试源码，未执行该用例。

### 溯源关键词仍有旧入口消费者，新引用链路不依赖它

同步路径：

`worker/workflow/tasks.py` / `workflow/domain/services/published_workflow_service.py`
→ `RedisCallback`
→ `worker/workflow/redis_callback.py` 保存回复并提交 `sync_process_source_document`
→ `common/chat/utils.py:sync_process_source_document`
→ `LLMService.get_knowledge_source_llm`
→ 读取 `knowledge_llm.source_model_id`，提取答案关键词并保存 `RecallChunk`。

读取路径：`knowledge/api/endpoints/qa.py` → `QaRecallService.keywords` → `QaRecallRepository.chunks`，读取已保存的关键词供溯源使用。

异步路径仍定义在 `chat_helpers.py:final_message` 中，但全仓搜索未发现该工作台函数的调用方，不能以此证明当前工作台主链路使用该配置。

2026-11-27 用户指出当前溯源已统一由模型生成的引用标记渲染，继续追踪读取端后，修正此前“后端仍有调用，所以保留配置”的判断：

- 新路径为引用标记 → Citation Registry → `/api/v1/citations/**` → 引用预览，不读取 `RecallChunk` 或答案关键词。工作流 `save_chat_message` 在 `save_message_citations_sync` 后仍并行提交旧关键词任务，二者是独立处理。
- 旧关键词用于给召回段落计算匹配分数、排序来源文件，并在旧弹窗中展示可增删的关键词标签和来源定位；不是生成或渲染引用标记所必需。
- 旧入口尚未完全退出：`PlatformConversationMessages.tsx` 的 `SourceEntry` 在文件来源消息上打开 `ResouceModal`，该组件实际调用 `splitWordApi` / `getSourceChunksApi`，对应 `/api/v1/qa/keyword` 和 `/api/v1/qa/chunk`。`BuildPage/flow/FlowChat/ChatMessages.tsx` 使用这个消息组件，管理端工作流调试存在可达入口。
- `LogPage/useAppLog/dailyChatDetail.tsx` 在 `source === 1` 时也提供旧弹窗入口；平台还注册 `/resouce/:cid/:mid` 页面。
- client 的 `splitWordApi` / `getSourceChunksApi` 只找到声明，没有业务调用；新引用的 service 只请求 citation 接口。
- 因此它不是完全没有消费者的死代码，而是仍挂在管理端的旧溯源机制。用户最终确认：保留已有旧按钮、弹窗、页面和读取接口，使历史数据继续可用；只停止新数据生成并移除生成模型配置。不能只隐藏模型选择器，否则会继续调用分词回退路径。

## 用户已确认的业务范围

1. 删除工作台向量模型的设置、必填校验、变更确认、探测与自动补齐；历史工作台 embedding 值退出默认选择与有效引用判断，不将它自动回填到知识模型配置。
2. 新建弹窗初值、后端未传模型时的默认值、创建前置检查统一读取“知识模型”的默认 embedding。用户在新建空间时显式选择的模型继续优先。
3. 保存默认 embedding 只影响后续新建的空间；已有空间保留各自模型和索引。单空间主动更换模型及重建功能继续保留。
4. 沿用现有租户配置继承、共享检查、模型可用性与资源权限流程，不增加另一套兜底来源。
5. 移除旧关键词提取任务和溯源模型配置；新消息不再产生旧格式数据或旧式文件溯源按钮。保留历史消息已有旧按钮、弹窗、页面和读取接口，历史数据继续可用。新引用注册、标记渲染、来源预览保持完整，不清理历史数据、不转换历史会话。
6. 保留 QA 知识库相似问配置等 QA 功能。只修改本需求涉及的系统模型配置文案，三语同步。

## 文案方向

| 项目 | 拟用表述 |
| --- | --- |
| 栏目 | 知识模型 |
| 默认 embedding 标签 | 默认 embedding 模型 |
| 默认 embedding 提示 | 新建知识空间默认使用此模型进行文件向量化和检索，也可在创建时选择其他模型。修改默认值不会更换已有知识空间的模型或触发重建。 |
| 摘要提示词标签 | 知识空间文件摘要提示词 |
| 摘要提示词提示 | 为知识空间中的文件生成摘要时使用的提示词。 |
| 溯源模型配置 | 移除生成模型设置，历史读取功能保留。 |
| QA 相似问 | 保留 QA 知识库相似问模型及对应提示。 |

摘要/标签模型的完整提示将在设计阶段对照实际处理链路核实，删除“总结为标题并与 chunk 合并”等未经当前实现支持的旧描述。

## 后续验证重点

- 工作台配置不含 embedding 也能保存；不存在旧选择器与全量重建确认。
- 知识与工作台 embedding 配置不同时，新建空间使用知识模型默认值；弹窗初值与实际创建一致。
- 显式指定模型、未配置默认值、无效模型、租户继承及共享失效路径。
- 保存默认值不修改已有空间模型、引用和索引，不触发重建任务。
- 删除旧配置槽后，模型引用/删除检查和历史配置读取保持一致。
- 三语文案一致；QA 相似问配置仍然可用；新引用标记与来源定位不依赖旧关键词路径。
- 历史旧溯源按钮仍能读取原关键词、来源和文件定位；删除模型配置不影响其读取。新消息无旧溯源生成调用及无法使用的旧式按钮。

## 流程

本需求跨系统模型配置与知识空间创建，并改变默认模型来源，依 `docs/SDD-Guide.md` §1 采用 Full SDD。需求发现确认已完成，进入 `spec.md` 编写与审查；随后进入设计确认与实现。
