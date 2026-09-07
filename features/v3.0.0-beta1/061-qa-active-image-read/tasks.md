# Tasks: F061 问答场景主动读图

**关联规格**: [spec.md](./spec.md)
**设计入口**: [design.md](./design.md)
**版本**: v3.0.0-beta1 / F061

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-09-07 用户确认 |
| design.md | ✅ 已评审 | 2026-09-07 用户确认；接手第一入口 |
| tasks.md | ✅ 已拆解 | 2026-09-07 `/sdd-review tasks` 通过 |
| 实现 | ✅ 完成 | 15 / 15。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3-§4 |

---

## 开发模式

- 无新增 ORM / Alembic / 错误码 / HTTP API / 前端读图 UI。不改 `linsight/`，不改 `core/prompts/yaml/knowledge_space.yaml`。
- 共享能力先落地 `bisheng/common/image_view/`（C1：不 import `domain/`），三场景只接线。论证见 design §3 决策 1。
- 后端 Test-First：每个实现任务前有配对测试。`asyncio_mode=auto`。新测试放 `test/<module>/`，不用 `test/` 根目录。
- 日常动态 bind 见 design §3 决策 3 / 坑 2：不要改 `_prepare_tools` 固定表。
- 真模型 + MinIO + 浏览器 SSE 只在 T015 手工清单；单测一律 mock 存储与 LLM。
- 自包含：文件 / 逻辑 / AC 写在任务里。**为什么**只指向 design §X，不抄决策。

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

---

## 实际偏差记录

> **只留一行指针**，论证在 design.md（决策 / 坑），这里不重复（见 `docs/SDD-Guide.md` §4）。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认（§3 第四个 ★），再记录。
