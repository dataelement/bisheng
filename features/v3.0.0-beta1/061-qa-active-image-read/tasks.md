# Tasks: F061 问答场景主动读图

**关联规格**: [spec.md](./spec.md)
**设计入口**: [design.md](./design.md) · [增量 · 知识空间/频道 ReAct](./design-增量-知识空间频道ReAct.md)
**版本**: v3.0.0-beta1 / F061

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-09-07 用户确认 |
| design.md | ✅ 已评审 | 2026-09-07 用户确认；2026-09-08 决策 3 ★ 推翻，见增量 |
| design-增量-知识空间频道ReAct.md | ✅ 已评审 | 2026-09-08 用户确认两条约束后继续拆 tasks |
| tasks.md | ✅ 已拆解 | T001–T015 初版；T016–T026 为知识空间/频道 ReAct 增量 |
| 实现 | 增量已完成 | T001–T015 完成。增量 11 / 11（T016–T026） |

---

## 开发模式

- 无新增 ORM / Alembic / 错误码 / HTTP API / 前端读图 UI。不改 `linsight/`，不改 `core/prompts/yaml/knowledge_space.yaml`。
- 共享能力先落地 `bisheng/common/image_view/`（C1：不 import `domain/`），三场景只接线。论证见 design §3 决策 1。
- 后端 Test-First：每个实现任务前有配对测试。`asyncio_mode=auto`。新测试放 `test/<module>/`，不用 `test/` 根目录。
- 日常动态 bind 见 design §3 决策 3 / 坑 2：不要改 `_prepare_tools` 固定表。
- **增量 T016–T026**（[增量 design](./design-增量-知识空间频道ReAct.md)）：知识空间 / 频道预组文不变，循环改 `create_react_agent`；工具只有 `view_image`；SSE 仍 STREAM。不要挂 `search_knowledge_bases` / 联网；不要抽 `common/chat_react/`；`recursion_limit=8`，不用日常的 50。`common/` 不 import 任何 `domain/`。
- 真模型 + MinIO + 浏览器 SSE 只在 T015 / T026 手工清单；单测一律 mock 存储与 LLM。
- 自包含：文件 / 逻辑 / AC 写在任务里。**为什么**只指向 design §X 或增量决策 RX，不抄决策。

---

## Tasks

### Wave 1：标注与注册表

- [x] **T001**: 标注与注册表单元测试
  **文件**: `src/backend/test/common/test_image_view_annotate.py`
  **逻辑**: 对 `annotate(text, registry)` 断言：单图在原 `![alt](url)` 后追加 `⟦img#1⟧`（U+27E6 / U+27E7）且 URL 不变；两张不同 URL 编为 img#1 / img#2；同一 URL 出现两次只占一个编号；无 `![...](url)` 时原文不变、registry 为空；正文含 citation 私用区 `\ue200` 时不被改写。不测取像素。
  **覆盖 AC**: AC-01, AC-08
  **验证**: `cd src/backend && uv run pytest test/common/test_image_view_annotate.py`
  **依赖**: 无

- [x] **T002**: 实现 annotate + ImageRegistry
  **文件**: `src/backend/bisheng/common/image_view/__init__.py`,
  `src/backend/bisheng/common/image_view/annotate.py`
  **逻辑**: 同一模块内提供 `ImageRegistry`（请求内 `img#N → {url}`，同 URL 去重）和 `annotate(text, registry) -> str`。只扫 markdown 图片，不解析 HTML `<img>`，不碰 citation 私用区。本包不 import 任何 `domain/`。`__init__.py` 再导出这两个名字给后续任务。
  **测试**: T001 全部通过。
  **覆盖 AC**: AC-01, AC-08
  **依赖**: T001

### Wave 2：取图、缩放与 view_image 工具

- [x] **T003**: 取图分流与缩放单元测试
  **文件**: `src/backend/test/common/test_image_view_fetch.py`
  **逻辑**: mock MinIO `get_object` 与 `async_file_download`。断言 `/{public_bucket}/knowledge/images/...` 走 `get_object`；host 等于 `settings.minio.sharepoint` 或 `IntelligenceCenterConf.base_url` 的 http(s) 走下载；其它 host 失败且不 raise；不跟随 3xx 出白名单。内存生成长边 >512 的 PNG，断言缩放后长边 = 512、已小于 512 不放大。取图 / 解码失败返回错误结构，不抛到调用方。不写共享本地盘。
  **覆盖 AC**: AC-06, AC-15
  **验证**: `cd src/backend && uv run pytest test/common/test_image_view_fetch.py`
  **依赖**: 无

- [x] **T004**: 实现 fetch_and_encode
  **文件**: `src/backend/bisheng/common/image_view/fetch.py`
  **逻辑**: 按 design §4.4 分流；PIL 进程内缩放，长边 512；输出 data URI。禁止把中间图落到共享盘（C8）。失败返回给工具层，不 raise。
  **测试**: T003 全部通过。
  **覆盖 AC**: AC-06, AC-15
  **依赖**: T003

- [x] **T005**: view_image 工具单元测试
  **文件**: `src/backend/test/common/test_image_view_tool.py`
  **逻辑**: 构造已 annotate 的 registry。断言工具参数只有 `image_ids` + `quality="standard"`，没有 URL 字段；未知 / 未编号 id 不取图，观察文本说明不可用（不 raise）；一次传入超过 3 个 id 只处理 3 张，其余说明已达上限；`quality` 非 `standard` 拒绝。成功路径 mock `fetch_and_encode`，观察为短文本 ack，**不含** image block（像素由编排器另挂 HumanMessage，见 design §3 决策 4）。
  **覆盖 AC**: AC-05, AC-08, AC-09, AC-14, AC-19, AC-20
  **验证**: `cd src/backend && uv run pytest test/common/test_image_view_tool.py`
  **依赖**: T002

- [x] **T006**: 实现 view_image 工具
  **文件**: `src/backend/bisheng/common/image_view/tool.py`
  **逻辑**: LangChain StructuredTool；只查本轮 `ImageRegistry`；单轮最多 3 张；v1 只接受 `standard`。工具返回短文本 ack，不把 data URI 放进 ToolMessage。
  **测试**: T005 全部通过。
  **覆盖 AC**: AC-05, AC-08, AC-09, AC-14, AC-19, AC-20
  **依赖**: T002, T004, T005

### Wave 3：两轮循环与 HumanMessage 搬迁

- [x] **T007**: run_vision_tool_loop 与 relocate 单元测试
  **文件**: `src/backend/test/common/test_image_view_loop.py`
  **逻辑**: mock LLM：第一轮 `tool_call` view_image，第二轮文本答案。断言第一轮发给模型的消息**没有** image / data URI（只有 `⟦img#N⟧`）；对外 iterator **不 yield** 第一轮 content（AC-17）；第二轮消息含原问题 + 标注上下文 + 工具 ack + `HumanMessage`（text + `image_url` data URI），且不再 `bind_tools`。无图或调用方声明 `visual=false` 时退回单轮、不 bind。误把 image 放进 ToolMessage 的列表经 `relocate_images_to_human` 后，image 只出现在 HumanMessage。追加的读图规则含「回答里仍输出原始 `![](url)`」；无图路径不追加该规则。
  **覆盖 AC**: AC-04, AC-06, AC-07, AC-13, AC-16, AC-17
  **验证**: `cd src/backend && uv run pytest test/common/test_image_view_loop.py`
  **依赖**: T002, T006

- [x] **T008**: 实现 loop + relocate + 读图规则文本
  **文件**: `src/backend/bisheng/common/image_view/loop.py`,
  `src/backend/bisheng/common/image_view/relocate.py`
  **逻辑**: `run_vision_tool_loop` 供知识空间 / 频道：有图且 visual 才 bind、缓冲首轮、最多 1 次额外请求、第二轮不绑工具。读图规则四条口径见 design §4.3，**仅在即将暴露工具时**追加，不写进 yaml / DB 默认稿。`relocate_images_to_human` 供日常每次模型调用前使用。图片进 HumanMessage，不进 ToolMessage（design §3 决策 4）。
  **测试**: T007 全部通过。
  **覆盖 AC**: AC-04, AC-06, AC-07, AC-13, AC-16, AC-17
  **依赖**: T006, T007

### Wave 4：三场景接线（共享层完成后再接）

- [x] **T009**: 知识空间接线单元测试
  **文件**: `src/backend/test/knowledge/test_knowledge_space_chat_image_view.py`
  **逻辑**: mock 检索上下文与 LLM。`visual=true` 且 chunk 含 `![...](url)` 时：`_prepare_rag_citation_context` 之后的正文带 `⟦img#N⟧`，走 `run_vision_tool_loop`，且默认 yaml 未被改写。`visual=false` 或无 markdown 图：不 annotate、不 bind、退回今天的单轮 `astream`。不新增鉴权函数（沿用现有 `view_file` 过滤后的 chunk）。覆盖 `chat_single_file` / `chat_folder`（`folder_id=0` 即整空间）共用的 `space_rag` / `_render_rag_response` 入口即可，不必各写一条 E2E。
  **覆盖 AC**: AC-02, AC-03, AC-11, AC-13, AC-14
  **验证**: `cd src/backend && uv run pytest test/knowledge/test_knowledge_space_chat_image_view.py`
  **依赖**: T008

- [x] **T010**: 知识空间接入 run_vision_tool_loop
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py`
  **逻辑**: `_prepare_rag_citation_context` 后 annotate；按 `model_id` 读工作台 `WSModel.visual`（与 Linsight `_resolve_model` 同源）；`space_rag` / `_render_rag_response` 换 `run_vision_tool_loop`。不改 `knowledge_space.yaml`，不加联网 / 多工具 Agent。
  **测试**: T009 全部通过；既有 `test_knowledge_space_chat_citations.py` 保持通过。
  **覆盖 AC**: AC-02, AC-03, AC-11, AC-13, AC-14
  **依赖**: T008, T009

- [x] **T011**: 频道接线单元测试
  **文件**: `src/backend/test/channel/test_channel_chat_image_view.py`
  **逻辑**: mock 文章正文与 LLM。截断后正文含 markdown 图且 `visual=true` 时：Service 内 annotate + `run_vision_tool_loop`，首轮 tool token 不进入对外 stream。无图 / `visual=false` 与今天单轮一致。断言编排函数在 `ChannelChatService`，不在 endpoint。不新增鉴权（敏感文检查仍在既有入口）。
  **覆盖 AC**: AC-02, AC-03, AC-12, AC-14
  **验证**: `cd src/backend && uv run pytest test/channel/test_channel_chat_image_view.py`
  **依赖**: T008

- [x] **T012**: 频道编排迁入 ChannelChatService
  **文件**: `src/backend/bisheng/channel/domain/services/channel_chat_service.py`,
  `src/backend/bisheng/channel/api/endpoints/channel_chat.py`
  **逻辑**: 把今天 endpoint 里的截断 + `astream` 迁到 Service：annotate、`visual` 门控、`run_vision_tool_loop`、读图规则仅在暴露工具时追加。Endpoint 只做鉴权 / SSE 包装（C1）。不引入向量检索。不改灵思。
  **测试**: T011 全部通过。
  **覆盖 AC**: AC-02, AC-03, AC-12, AC-14
  **依赖**: T008, T011

- [x] **T013**: 日常动态 bind 单元测试
  **文件**: `src/backend/test/workstation/test_daily_chat_image_view.py`
  **逻辑**: 不拉起完整 `create_react_agent` 图（成本高且不稳定）。测三件事：① `DailyChatCitationToolWrapper._dump_knowledge_chunks` 在 `format_retrieved_chunk` 之后 annotate，同 URL 去重；② `_prepare_tools` 返回的工具名**不含** `view_image`；③ `VisionToolBindWrapper(llm, registry, base_tools)`（T014 加在同文件 `chat_service.py`）：`len(registry)==0` 时模型侧 `bind_tools` 只有 `base_tools`、不追加读图规则；registry 非空时为 `base_tools + [view_image]` 并追加规则。断言没有新的 SSE event type（日常仍走已有 `agent_tool_call`）。只改日常路径，不影响灵思 / 知识空间 / 频道。
  **覆盖 AC**: AC-02, AC-03, AC-10, AC-18
  **测试降级**: 不测真 LangGraph `astream_events` 全图，只测 annotate 挂钩与 `VisionToolBindWrapper`。完整日常 SSE 见 T015。
  **验证**: `cd src/backend && uv run pytest test/workstation/test_daily_chat_image_view.py`
  **依赖**: T008

- [x] **T014**: 日常接入 annotate + VisionToolBindWrapper
  **文件**: `src/backend/bisheng/workstation/domain/services/chat_service.py`
  **逻辑**: `_agent_stream_chat_completion` 建请求级 `ImageRegistry`。`DailyChatCitationToolWrapper._dump_knowledge_chunks` 在 format 之后 annotate。`_prepare_tools` **不加** `view_image`。新增 `VisionToolBindWrapper(llm, registry, base_tools)`：每次模型调用前 `relocate_images_to_human`，按 `len(registry)` 动态 `bind_tools`，仅此时追加读图规则。把该 wrapper 交给 `create_react_agent`，不要把读图规则写进 `prompt=sys_prompt`。ToolNode 用 `base_tools + [view_image]` 以便执行，但 wrapper 忽略编译期那次 bind（design 坑 2）。只动日常 agent 路径，不改灵思。
  **测试**: T013 全部通过。
  **覆盖 AC**: AC-02, AC-03, AC-10, AC-18
  **依赖**: T008, T013

### Wave 5：手工验收清单

- [x] **T015**: 三场景手工 E2E 清单
  **文件**: `features/v3.0.0-beta1/061-qa-active-image-read/e2e-checklist.md`
  **逻辑**: 把 design §7 的 7 步写成可勾选清单（启动命令、`/workspace` 日常、知识空间文件/文件夹/整空间、频道文章、关视觉、无图、MinIO 缺对象）。不改业务代码。真模型 + MinIO + client SSE 只在本任务做。
  **覆盖 AC**: AC-10, AC-11, AC-12, AC-15, AC-18
  **测试降级**: 依赖本地 / 测试环境中间件与已开视觉的工作台模型，不进 PR 单测门禁。
  **依赖**: T010, T012, T014

### Wave 6：VisionToolBindWrapper 迁到 common，补 pop_viewed

> 论证：增量决策 R3、坑 R1 / 主 design 坑 13。步骤 1 未合就切知识空间，会把「看不见像素」带进预组文场景。

- [x] **T016**: VisionToolBindWrapper pop_viewed 单元测试
  **文件**: `src/backend/test/common/test_image_view_vision_llm.py`
  **逻辑**: 从 `bisheng.common.image_view.vision_llm` import `VisionToolBindWrapper`（T017 才落地）。用 Recording LLM（记录 `bind_tools` 名与 `ainvoke` 收到的 messages）。① `len(registry)==0`：bind 只有传入的 `base_tools`，messages 不含读图规则。② registry 非空：bind 为 `base_tools + [view_image]`，messages 含读图规则。③ `registry.record_viewed("img#1", data_uri)` 之后 `_prepare` / `ainvoke` 的 messages 含一条 `HumanMessage`，其 content 列表里有 `type=image_url` 且 url 为该 data URI；不得把该块放在 `ToolMessage` 里。④ wrapper 必须是普通 callable，不是 `Runnable`。不拉 `create_react_agent`。不测知识空间 / 频道。
  **覆盖 AC**: AC-03, AC-04, AC-06, AC-07
  **验证**: `cd src/backend && uv run pytest test/common/test_image_view_vision_llm.py`
  **依赖**: 无（T001–T015 已完成）

- [x] **T017**: 实现 common VisionToolBindWrapper
  **文件**: `src/backend/bisheng/common/image_view/vision_llm.py`,
  `src/backend/bisheng/common/image_view/__init__.py`
  **逻辑**: 把 `workstation/.../chat_service.py` 里的 `VisionToolBindWrapper` / `_VisionCallRunnable` / `_messages_from_model_input` **复制**到 `vision_llm.py`（本任务不改 chat_service，避免日常 import 空窗；T018 再删本地类并改 import）。复制时补上 `_prepare` 的 `pop_viewed`：追加 HumanMessage 图片块（与 `loop.py` `_image_human_message` 同形）→ `relocate_images_to_human` → 若本轮将 bind `view_image` 则 `prepare_vision_messages`。`len(registry)>0` 才把 `view_image` 加进 bind 列表。本文件不 import 任何 `domain/`，不 yield `ChatResponse`。`__init__.py` 导出 `VisionToolBindWrapper`。
  **测试**: T016 全部通过。
  **覆盖 AC**: AC-03, AC-04, AC-06, AC-07
  **依赖**: T016

- [x] **T018**: 日常改从 common import wrapper
  **文件**: `src/backend/bisheng/workstation/domain/services/chat_service.py`,
  `src/backend/test/workstation/test_daily_chat_image_view.py`
  **逻辑**: 删除 chat_service 本地 `VisionToolBindWrapper` / `_VisionCallRunnable` / `_messages_from_model_input`，改为 `from bisheng.common.image_view import VisionToolBindWrapper`（或 `vision_llm`）。`_prepare_tools` **仍不加** `view_image`；`create_react_agent` 仍把 wrapper 当动态工厂；读图规则仍不写进 `prompt=`。日常测试改为从 common import wrapper；原有 empty-registry / bind view_image / relocate 三条保持通过。不改日常 SSE 类别。不改知识空间 / 频道。
  **测试**: T013 文件 + T016 全部通过。
  **覆盖 AC**: AC-02, AC-03, AC-10, AC-18
  **依赖**: T017

### Wave 7：知识空间 / 频道 ReAct 读图循环

> 论证：增量决策 R1、R2、R4、R5。对外 yield 的仍是 LangChain chunk，不是 `ChatResponse`。

- [x] **T019**: run_react_vision_stream 单元测试
  **文件**: `src/backend/test/common/test_image_view_react_loop.py`
  **逻辑**: mock `fetch_and_encode`。用可 `bind_tools` 的 Fake `BaseChatModel`（可参考 `test/workstation/test_agent_tool_error_handling.py` 的 `_FakeToolCallingModel`）驱动真实 `create_react_agent`，不要测日常 `agent_*` SSE。① 第一轮 `tool_calls=view_image`：对外 iterator **不 yield** 该轮 content（AC-17）；后续作答 chunk 才 yield；发给第二轮模型的 messages 含原标注上下文 + 工具 ack + `HumanMessage` `image_url` data URI，第一轮请求仍无像素（AC-04, AC-06, AC-07）。② 问题匹配「表单|字段」等且 suggested 非空、模型第一轮纯文本无 tool_call：注入 `view_image`，**不 yield** 该轮散文；注入后的 `image_ids` 为 suggested。③ `visual=false` 或 registry 空：只走 `llm.astream`，**不**调用 `create_react_agent`（monkeypatch 后者，误调用则失败）。④ 已成功 view 过一轮后，下一轮模型若再出纯文本，视为答案并 yield，不得再次注入。⑤ 断言 `recursion_limit==8`（读 create_react_agent / `astream_events` 的 config）。不测知识空间 citation、不改前端。
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-06, AC-07, AC-13, AC-16, AC-17
  **验证**: `cd src/backend && uv run pytest test/common/test_image_view_react_loop.py`
  **依赖**: T017

- [x] **T020**: 实现 run_react_vision_stream
  **文件**: `src/backend/bisheng/common/image_view/react_loop.py`,
  `src/backend/bisheng/common/image_view/__init__.py`
  **逻辑**: `run_react_vision_stream(llm, messages, registry, *, visual)`：无图 / 未开视觉 → `llm.astream` 后 return。否则 `ToolNode([view_image])` + `create_react_agent(VisionToolBindWrapper(llm, registry, base_tools=[]), tool_node)`，`prompt` 不要拼读图规则。`RunnableConfig(recursion_limit=8)`，禁止读 `daily_chat.agent_max_iterations`。`astream_events` v2：tool 事件不对外 yield；尚未完成读图的模型轮次先缓冲，确认是 tool_call / 即将注入则丢弃 prose（增量坑 R3 / 决策 R4）。`needs_pixels && view_call_count==0 && suggested` 时才 `tool_choice` / 注入；看完图的下一轮普通 bind。yield 的对象与今天 `run_vision_tool_loop` 相同（模型 chunk / `AIMessage`），禁止 import workstation / knowledge / channel，禁止构造 `ChatResponse`。`__init__.py` 导出 `run_react_vision_stream`。本任务不接线场景、不删 `run_vision_tool_loop`。
  **测试**: T019 全部通过。
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-06, AC-07, AC-13, AC-16, AC-17
  **依赖**: T017, T019

### Wave 8：知识空间接线

- [x] **T021**: 知识空间改走 react stream 的单元测试
  **文件**: `src/backend/test/knowledge/test_knowledge_space_chat_image_view.py`
  **逻辑**: 把 `_render_rag_response` 路径上 monkeypatch 的 `run_vision_tool_loop` 改为 `run_react_vision_stream`（patch 点仍是 `knowledge_space_chat_service` 模块全局名）。`visual=true` 且 chunk 含 markdown 图：断言调用了 `run_react_vision_stream`，registry 非空，正文含 `⟦img#N⟧`，yaml 仍无 `view_image`。`visual=false` / 无 markdown 图：registry 空、不 annotate。不新增鉴权。不测真 graph（fake helper yield 一条 `AIMessage` 即可）。既有 `test_knowledge_space_chat_citations.py` 不在本文件改。
  **覆盖 AC**: AC-02, AC-03, AC-11, AC-13, AC-14
  **验证**: `cd src/backend && uv run pytest test/knowledge/test_knowledge_space_chat_image_view.py`
  **依赖**: T020

- [x] **T022**: `_render_rag_response` 接入 run_react_vision_stream
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py`
  **逻辑**: import 与循环从 `run_vision_tool_loop` 换成 `run_react_vision_stream`；`_prepare_rag_citation_context`、prompt、citation 落库、SSE `ChatResponse(STREAM)` 不动。不加 `search_knowledge_bases` / `web_search`。不改 `knowledge_space.yaml`。单文件 / 文件夹 / `space_rag` 已共用此函数，不必各改入口。
  **测试**: T021 全部通过；`test/knowledge/test_knowledge_space_chat_citations.py` 保持通过。
  **覆盖 AC**: AC-02, AC-03, AC-11, AC-13, AC-14
  **依赖**: T020, T021

### Wave 9：频道接线

- [x] **T023**: 频道改走 react stream 的单元测试
  **文件**: `src/backend/test/channel/test_channel_chat_image_view.py`
  **逻辑**: `stream_article_reply` 的 monkeypatch 目标改为 `run_react_vision_stream`。含图且 `visual=true`：Service 内 annotate + 调用 react helper，yield 的是模型 chunk。无图 / `visual=false` 与今天一致。endpoint 文件仍不含 `run_vision_tool_loop` / `run_react_vision_stream` / `create_react_agent`（编排留在 Service）。不新增鉴权。
  **覆盖 AC**: AC-02, AC-03, AC-12, AC-14
  **验证**: `cd src/backend && uv run pytest test/channel/test_channel_chat_image_view.py`
  **依赖**: T020

- [x] **T024**: `stream_article_reply` 接入 run_react_vision_stream
  **文件**: `src/backend/bisheng/channel/domain/services/channel_chat_service.py`
  **逻辑**: 循环从 `run_vision_tool_loop` 换成 `run_react_vision_stream`。截断、annotate、`visual` 门控不变。不改 `channel_chat.py` endpoint SSE 包装（仍 STREAM）。不引入向量检索 / 联网。不改灵思。
  **测试**: T023 全部通过。
  **覆盖 AC**: AC-02, AC-03, AC-12, AC-14
  **依赖**: T020, T023

### Wave 10：删除手写 loop，回写 design

- [x] **T025**: 删除 run_vision_tool_loop
  **文件**: `src/backend/bisheng/common/image_view/loop.py`,
  `src/backend/bisheng/common/image_view/__init__.py`,
  `src/backend/test/common/test_image_view_loop.py`
  **逻辑**: 删除 `run_vision_tool_loop` 及其仅被该函数使用的编排私有函数；**保留** `suggest_image_ids`、`question_needs_pixels`、`drop_image_catalog_history`、`prepare_vision_messages`、注入 / 覆盖 `image_ids` 等纯函数（react_loop 仍要调用）。`__init__.py` 不再导出 `run_vision_tool_loop`。`test_image_view_loop.py` 去掉对 `run_vision_tool_loop` 的编排用例，保留选图 / catalog / relocate 纯函数用例（relocate 若已在 T007 本文件，继续留）。全仓 grep 确认无残留引用。不改场景 service。
  **测试**: `cd src/backend && uv run pytest test/common/test_image_view_loop.py test/common/test_image_view_react_loop.py test/common/test_image_view_vision_llm.py test/knowledge/test_knowledge_space_chat_image_view.py test/channel/test_channel_chat_image_view.py test/workstation/test_daily_chat_image_view.py`
  **依赖**: T022, T024

- [x] **T026**: 回写 design §4 与 e2e 清单
  **文件**: `features/v3.0.0-beta1/061-qa-active-image-read/design.md`,
  `features/v3.0.0-beta1/061-qa-active-image-read/e2e-checklist.md`
  **逻辑**: 覆盖更新主 design §4 / §6：知识空间 / 频道接线改为 `run_react_vision_stream`，删掉「今天仍是 loop」的过渡句；增量 design 状态改为已落地。e2e-checklist 知识空间 / 频道两项补一句：SSE 仍是 `stream`，**没有** `agent_tool_call`；联调题「开户申请表单上有哪些字段？」仍应读 `img#10` / `img#9` 量级。不改业务代码、不改前端。
  **覆盖 AC**: AC-11, AC-12, AC-17
  **测试降级**: 真模型 + MinIO + client SSE 只在本任务按 e2e-checklist 手工勾；不进 PR 单测门禁（与 T015 相同理由）。
  **依赖**: T025

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认（§3 第四个 ★），再记录。

- 2026-09-08 决策 3 ★ 推翻 A → C：知识空间 / 频道改预组文 + LangGraph ReAct（仅 `view_image`，SSE 仍 STREAM）。论证见 design.md 决策 3 与 [增量 design](./design-增量-知识空间频道ReAct.md)。T016–T026 已落地。
