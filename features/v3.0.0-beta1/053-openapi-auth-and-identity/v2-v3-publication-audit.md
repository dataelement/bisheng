# F053 当前分支 v2 / v3 与免登录发布链路核对

> **后续范围更新（2026-09-10）**：用户正在确认 v2 是否保留。本轮已补齐三个 v3 语音入口和 client 调用，**未删除任何 v2 入口**。当前 v3 为 10 HTTP + 2 WS；v2 仍为 42 HTTP + 2 WS。下文保留的是补漏前的审计快照，其中“删除 v2”清单仅是待需求确认的候选方案，不是当前执行要求。新接口、请求参数与验证见 [design §5.F F5](./design.md) 和 [e2e-checklist.md](./e2e-checklist.md)。历史核对还确认：ASR/TTS 有匿名 v2 前身，语音配置未找到 v2 前身。

核对日期：2026-09-10。分支：`feat/3.0.0-beta1`，HEAD：`59b27d1c1`。

本报告根据本次用户提出的“发布接口迁到 v3、删除对应 v2 入口，其余 v2 继续密钥鉴权”口径整理。记录源码现状、旧文档要求和应调整范围，不将文档中的旧要求视为本次新指令。此次只新增审计报告，未修改应用代码和原 PRD / design / API 文档。工作区原有 API Markdown 文档修改保持原样。

## 1. 结论

1. 当前注册源码共 **53 个入口**：v2 **42 HTTP + 2 WebSocket**，v3 **7 HTTP + 2 WebSocket**。按方法与路径比对，v2 JSON 接口文档的 42 个 HTTP operation 与当前源码一致。
2. “为什么有 v3 还保留 v2”：**设计 §5.F F1 明文要求保留同能力的 v2 密钥版本**，并非单纯忘删文件。PRD 附录 B.1 也明确要求工作流、助手、ASR/TTS 加密钥鉴权。现有实现沿用了这套要求；它与本次用户明确的迁移口径不一致。
3. 当前免登录网页由 client 的 `StandaloneChatPage` 承载。详情、历史、标题、WebSocket 主链路已经选择 v3。
4. **语音属于工作流 / 助手页面共用的交互能力，迁移确有遗漏**：页面语音配置、ASR、TTS 仍固定请求 v1，v3 没有对应入口。v2 的 ASR/TTS 则仍在密钥文档里，标记 `assistant:invoke`、仅 S 模式。
5. **打开页面时加载的是语音配置；ASR/TTS 本身按交互触发**。ASR 在录音结束后调用，TTS 在点击朗读时调用。不能把“渲染语音按钮”写成“页面打开即请求两次语音转换”。
6. 页面还共用附件、反馈、引用等 v1 请求。应逐项按既有访问语义核对，不能将所有 v1 / 所有知识库接口一并改成匿名 v3。两条 v1 附件上传本来就未声明登录依赖；语音 v1 则明确声明了登录依赖。

## 2. 文档矛盾的准确位置

| 文件 | 当前写法 | 与本次口径的关系 |
|---|---|---|
| [PRD 附录 B.1](</home/highway/PycharmProjects/bisheng/docs/product/3.0 开放 API 鉴权与身份传递 PRD.md:2379>) | workflow invoke/stop/WS、assistant completions/WS/info、flows 详情全部列为 v2 加鉴权能力；2408 行将 ASR/TTS 列为加鉴权能力 | PRD 尚未体现“这组发布接口整体迁离 v2” |
| [spec §1](/home/highway/PycharmProjects/bisheng/features/v3.0.0-beta1/053-openapi-auth-and-identity/spec.md:11) | v2 全部密钥鉴权，工作流/助手免登录发布用 v3 allowlist | 没有明确写删除哪些旧 v2 入口，留下了双版本解释空间 |
| [design §5.F F1](/home/highway/PycharmProjects/bisheng/features/v3.0.0-beta1/053-openapi-auth-and-identity/design.md:318) | “相同业务能力的 v2 路由保留为密钥鉴权版本” | 直接造成 7 个重复发布入口；需要改为列明迁移、删除清单 |
| [design §5.F F1 allowlist](/home/highway/PycharmProjects/bisheng/features/v3.0.0-beta1/053-openapi-auth-and-identity/design.md:320) | 只列 9 个 v3 入口 | 未列语音配置、ASR/TTS，也没有逐项核对页面共用辅助请求 |
| [design 风险 12 / 前端验收](/home/highway/PycharmProjects/bisheng/features/v3.0.0-beta1/053-openapi-auth-and-identity/design.md:464) | 要求覆盖完整调用图、guest 页面无 v2 遗留 | 只检查 v2 遗留不够：当前实际漏项是仍需登录的 v1 |
| [v2 测试用 API 文档](/home/highway/PycharmProjects/bisheng/features/v3.0.0-beta1/053-openapi-auth-and-identity/openapi-v2-key-auth-api.md:1) | 42 HTTP + 2 WS，包括上述发布和语音接口 | 与现状匹配；但应随新迁移范围重新生成，不能仅改标题或藏掉文档条目 |

补充：v2/v3 工作流都调用 `PublishedWorkflowService`，助手都调用 `PublishedAssistantService`。存在两个入口适配层，但不能据此说执行引擎整套复制了两份。删除重复路由时，共用服务仍需保留。

## 3. 从“对外发布 → 免登录地址”追踪实际页面

入口生成见 [ChatLink.tsx](/home/highway/PycharmProjects/bisheng/src/frontend/platform/src/components/bs-comp/apiComponent/ChatLink.tsx:78)：

- 工作流：`/workspace/chat/flow/{id}`
- 助手：`/workspace/chat/assistant/{id}`
- 带 `/auth/` 的链接是需要登录的另一条页面入口。

[client 路由](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/routes/index.tsx:278) 将前两者挂到 guest 模式；[版本选择](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/pages/standaloneChat/StandaloneChatContext.tsx:11) 返回 `v3`。platform 旧 `/chat/flow/`、`/chat/assistant/` 路由已重定向到 client，因此不能把 platform 旧组件中的 `v2` 字样直接当成当前发布页的真实请求。

| 阶段 | 当前请求 / 动作 | 结论 |
|---|---|---|
| 进入工作流页 | `GET /api/v1/env` | 读取自动重跑配置等；该接口原本免登录，不是 v2 漏迁 |
| 加载工作流详情 | `GET /api/v3/flows/{flow_id}` | 已切 v3 |
| 加载助手详情 | `GET /api/v3/assistant/info/{assistant_id}` | 已切 v3 |
| 加载 / 切换当前会话 | `GET /api/v3/chat/history` | 已切 v3 |
| 对话连接 | `WS /api/v3/workflow/chat/{id}` 或 `WS /api/v3/assistant/chat/{id}` | 已切 v3 |
| 执行、输入、停止 | 在上述 WS 发送消息，包括 `action: stop` | 当前网页主链路不依赖 HTTP invoke/stop |
| 生成会话标题 | `POST /api/v3/chat/gen_title` | 已切 v3 |
| 输入框 / 朗读按钮挂载 | `GET /api/v1/llm/workbench` | **漏项：需要登录；guest 未传版本，也未禁用该查询** |
| 录音结束 | `POST /api/v1/llm/workbench/asr` | **漏项：固定 v1，需要登录** |
| 点击朗读 | `POST /api/v1/llm/workbench/tts` | **漏项：固定 v1，需要登录** |

调用证据：

- [详情和历史](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/pages/appChat/index.tsx:148)、[WS 地址](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/pages/appChat/useChatHelpers.ts:36)、[会话标题](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/pages/appChat/useWebsocket.ts:96)。
- [输入框加载模型配置](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/pages/appChat/ChatInput.tsx:24) → [模型配置查询](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/hooks/queries/queries.ts:554) → [v1 配置 URL](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/api/index.ts:43)。
- [录音转换](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/components/Voice/SpeechToText.tsx:164) → [v1 ASR URL](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/api/index.ts:21)。
- [朗读按钮](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/components/Voice/TextToSpeechButton.tsx:30) → [v1 TTS URL](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/api/index.ts:34)。
- [后端三个 v1 接口均要求登录](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/llm/api/router.py:230)。

因此，在没有登录态的新浏览器中，即便 v3 对话正常，模型配置查询仍会被登录依赖拒绝，语音按钮可能不显示；已有登录态或查询缓存可能掩盖问题。[请求拦截器](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/api/request.ts:226) 已对 guest 链接停止 401 登录跳转，但这只避免跳转，并不让语音接口变为可用。

2026-09-11 用户纠正范围：platform“API 访问”是对接文档，已恢复 F053 修改前的完整 v2 说明。误增的 `POST /api/v3/workflow/invoke`、`POST /api/v3/workflow/stop`、`POST /api/v3/assistant/chat/completions` 已移除；免登录页面通过 v3 WebSocket 完成执行和交互，不需要这三个 HTTP 入口。

## 4. 页面辅助请求：哪些还需要纳入核对

| 能力 | 当前请求 | 代码现状与处理边界 |
|---|---|---|
| 通用聊天附件上传 | `POST /api/v1/knowledge/upload` | [uploadChatFile](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/api/apps.ts:271) 接收版本参数但生成 URL 时没有使用。后端端点本来就无登录依赖；不能误报为 v2 密钥阻断。若发布调用统一收口 v3，需要新增受发布资源约束的上传入口，保留站内/日常对话原入口 |
| 工作流文件节点上传 | `POST /api/v1/upload/{flow_id}`；部分分支用上述 knowledge/upload | [InputFileComponent](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/pages/appChat/components/InputFileComponent.tsx:85) 的两类上传均需覆盖；后端旧上传端点未声明登录依赖 |
| 点赞、复制、反馈 | `POST /api/v1/liked`、`/chat/copied`、`/chat/comment` | [MessageButtons](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/pages/appChat/components/MessageButtons.tsx:21) 仍会触发；这些旧端点未声明登录依赖，没有对应 v3；如迁移，应绑定发布会话和消息 |
| 点赞 / 复制的埋点 | `POST /api/v1/session/chat/message/telemetry` | [前端调用](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/api/apps.ts:110) 附带发出，而 [后端](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/chat_session/api/endpoints/session.py:45) 要求登录；这是另一项 guest 交互下的登录依赖残留 |
| 引用卡片及详情 | `POST /api/v1/citations/resolve`、`GET /api/v1/citations/{id}` | 有引用内容时可能自动批量补齐，点击时再查详情。可选登录；当前 F054 规则明确限制匿名读取知识/文章来源。不能把 v2 的单数 `/citation/{id}` 直接迁成匿名接口来替换这条链路 |
| 应用失效后的信息回退 | `GET /api/v1/chat/info` | [应用初始化失败分支](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/pages/appChat/index.tsx:162) 仍调用站内接口；guest 应使用发布资源失效信息，不应依赖登录态补救 |
| 公共环境、品牌、静态资源 | 如 `/api/v1/env`、图片和对象存储地址 | 按已有公共能力保留，不因 URL 含 v1 就判定迁移失败 |
| 导出、导入知识库、管理及分享功能 | 站内相应 v1 请求 | 不是本次发布 API 迁移的自动开放范围；guest 页面应按能力控制，尤其不能把知识库写入接口直接开放到 v3 |

引用证据：[client 引用 URL](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/api/chatApi.ts:25)；[有引用时批量补齐](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/components/Chat/Messages/Content/CitationReferencesDrawer.tsx:289)；[匿名知识引用规则](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/citation/domain/services/citation_resolve_service.py:301)。

## 5. 按本次口径应落地的迁移清单

### 5.1 删除 7 个已有 v3 对应项的 v2 入口

- `POST /api/v2/workflow/invoke`
- `POST /api/v2/workflow/stop`
- `WS /api/v2/workflow/chat/{workflow_id}`
- `POST /api/v2/assistant/chat/completions`
- `GET /api/v2/assistant/info/{assistant_id}`
- `WS /api/v2/assistant/chat/{assistant_id}`
- `GET /api/v2/flows/{flow_id}`

以上保留现有 v3 实现。v2 撤销注册后应成为不存在的路由，而非继续要求密钥，也不应给这些旧 v2 路径加匿名豁免或重定向。

### 5.2 语音补齐

- 将 `POST /api/v2/llm/workbench/asr`、`POST /api/v2/llm/workbench/tts` 迁入 v3，并删除这两个 v2 入口和 scope 映射。
- 为发布页提供最小语音能力配置，可并入已发布应用详情；无需把整个管理侧 `GET /llm/workbench` 配置复制开放。
- client 录音、朗读、配置读取跟随 guest 通道。站内 v1 功能继续使用原登录接口。
- v3 语音请求需要关联正在访问的发布应用，沿用现有发布开关、上线状态、租户和默认操作员解析。无需用户申请密钥、登录或传 v2 身份头。仅换路径而丢失应用/租户上下文不足以完成迁移。

只计算上述确定的 9 项迁出：v2 将从 **42 HTTP + 2 WS** 变为 **35 HTTP、0 WS**；v3 从 9 项增至至少 11 项。语音配置若独立成接口，以及辅助请求最终收口项，另计。

### 5.3 其余 v2 的边界

保留密钥体系、知识库/知识空间读写、QA、元数据、日常对话、日常附件、whoami。当前 `GET /api/v2/assistant/list` 不在单个发布页调用链中，保留密钥查询能力；它不是删除 7 个重复入口时应顺带开放到 v3 的接口。

`GET /api/v2/citation/{citation_id}`、`POST /api/v2/knowledge/upload` 也有独立的密钥 API 用途。页面出现相似业务功能，不能作为自动删除它们或转匿名的依据。

### 5.4 必须同步修改的配套文件

- PRD 附录 B.1、spec 范围裁定、design §5.F/§6.2/风险/测试/发布说明：统一写明“迁移后删除旧入口”，去掉“双版本保留”的要求。
- v2 router 注册、endpoint scope 标记、`OPEN_API_SCOPES` 清单、相关 schema/身份传递测试；避免服务账号界面还显示已不存在的权限能力。
- v3 allowlist、guest 请求链路和辅助能力契约。
- `generate_openapi_contract.py`、JSON 与 Markdown 文档：重新生成剩余密钥端点清单；单独列发布入口。
- 测试从“固定只有 9 个 v3”改为实际完整的发布链路；前端验收同时检查“未混入 v2”和“未请求依赖登录的 v1”。
- 商业网关若在其他仓库配置白名单，需同步新的 v3 HTTP/WS 路径；本仓库核对不能替代网关环境验证。

## 6. 验证结果与限制

已完成：源码路由装饰器静态枚举、全局注册与鉴权依赖检查、v2 JSON 的 42 个 HTTP operation 与源码逐项比对、发布链接到 client 组件/API 的静态调用链核对。

已尝试执行后端 v3 allowlist 与 v2 路由矩阵测试；测试在加载 conftest 时因缺少 `BS_MILVUS_CONNECTION_ARGS` 环境变量而终止，未执行测试用例。此次没有浏览器 Network 实测、真实 ASR/TTS 调用或商业网关联调。页面表现按代码路径推断，未将其记作已复现结果。

现有测试的覆盖缺口：

- [v3 路由测试](/home/highway/PycharmProjects/bisheng/src/backend/test/public_endpoints/test_http_allowlist.py:5) 将 9 个路由写成精确允许清单，语音遗漏因此不会被这个测试检出。
- [前端 guest 测试](/home/highway/PycharmProjects/bisheng/src/frontend/client/src/pages/standaloneChat/StandaloneChatPage.test.ts:7) 虽名为 “every guest URL”，实际仅测版本选择与标题 URL，没有挂载语音/附件/反馈组件，也没有检查完整请求集合。

修复验收应使用清空 cookie、localStorage 和查询缓存的独立浏览器，覆盖两类应用的首次加载、历史、发送、停止、录音、朗读、附件、引用、反馈；同时验证已迁移的旧 v2 入口不存在，剩余 v2 无密钥仍拒绝，v3 不要求密钥。

## 7. 全部 v2 路由清单（44 项）

本表“处理”列是按本次用户口径给出的目标，尚未改动生产代码。S/D 规则仍以当前代码为准，ASR/TTS 与 download_statistic 目前只允许 S；whoami 不要求业务 scope。

| 方法与路径 | 当前权限位 | 处理 | 源码 |
|---|---|---|---|
| `WS /api/v2/assistant/chat/{assistant_id}` | `assistant:invoke` | 按本次口径删除 v2，保留 v3 | [assistant.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/assistant.py:123) |
| `POST /api/v2/assistant/chat/completions` | `assistant:invoke` | 按本次口径删除 v2，保留 v3 | [assistant.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/assistant.py:33) |
| `GET /api/v2/assistant/info/{assistant_id}` | `assistant:read` | 按本次口径删除 v2，保留 v3 | [assistant.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/assistant.py:92) |
| `GET /api/v2/assistant/list` | `assistant:read` | 保留 v2 密钥鉴权 | [assistant.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/assistant.py:101) |
| `GET /api/v2/auth/whoami` | 仅鉴权 | 保留 v2 密钥鉴权 | [auth.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_api/api/endpoints/auth.py:13) |
| `GET /api/v2/chat/info` | `chat:invoke` | 保留 v2 密钥鉴权 | [chat.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/chat.py:26) |
| `GET /api/v2/chat/list` | `chat:invoke` | 保留 v2 密钥鉴权 | [chat.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/chat.py:15) |
| `GET /api/v2/citation/{citation_id}` | `knowledge:read` | 保留 v2 密钥鉴权 | [citation.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/citation.py:21) |
| `GET /api/v2/filelib/` | `knowledge:read` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:204) |
| `POST /api/v2/filelib/` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:121) |
| `PUT /api/v2/filelib/` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:170) |
| `DELETE /api/v2/filelib/{knowledge_id}` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:245) |
| `POST /api/v2/filelib/add_qa` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:583) |
| `POST /api/v2/filelib/add_relative_qa` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:606) |
| `POST /api/v2/filelib/chunks` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:486) |
| `POST /api/v2/filelib/chunks_string` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:534) |
| `DELETE /api/v2/filelib/clear/{knowledge_id}` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:275) |
| `POST /api/v2/filelib/delete_file` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:409) |
| `GET /api/v2/filelib/detail_qa` | `knowledge:read` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:677) |
| `GET /api/v2/filelib/download_statistic` | `knowledge:read` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:569) |
| `DELETE /api/v2/filelib/file/{file_id}` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:400) |
| `POST /api/v2/filelib/file/{knowledge_id}` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:304) |
| `GET /api/v2/filelib/file/list` | `knowledge:read` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:418) |
| `DELETE /api/v2/filelib/qa/{qa_id}` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:623) |
| `POST /api/v2/filelib/query_qa` | `knowledge:read` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:738) |
| `POST /api/v2/filelib/retrieve` | `knowledge:read` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:687) |
| `POST /api/v2/filelib/update_qa` | `knowledge:write` | 保留 v2 密钥鉴权 | [filelib.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/filelib.py:647) |
| `GET /api/v2/flows/{flow_id}` | `workflow:read` | 按本次口径删除 v2，保留 v3 | [flow.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/flow.py:13) |
| `POST /api/v2/knowledge/add_metadata_fields` | `knowledge:write` | 保留 v2 密钥鉴权 | [knowledge.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/knowledge.py:46) |
| `DELETE /api/v2/knowledge/delete_metadata_fields` | `knowledge:write` | 保留 v2 密钥鉴权 | [knowledge.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/knowledge.py:92) |
| `POST /api/v2/knowledge/file/add_user_metadata` | `knowledge:write` | 保留 v2 密钥鉴权 | [knowledge.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/knowledge.py:140) |
| `DELETE /api/v2/knowledge/file/delete_user_metadata` | `knowledge:write` | 保留 v2 密钥鉴权 | [knowledge.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/knowledge.py:193) |
| `POST /api/v2/knowledge/file/list_user_metadata` | `knowledge:write` | 保留 v2 密钥鉴权 | [knowledge.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/knowledge.py:220) |
| `PUT /api/v2/knowledge/file/modify_user_metadata` | `knowledge:write` | 保留 v2 密钥鉴权 | [knowledge.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/knowledge.py:166) |
| `GET /api/v2/knowledge/get_metadata_fields/{knowledge_id}` | `knowledge:write` | 保留 v2 密钥鉴权 | [knowledge.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/knowledge.py:118) |
| `PUT /api/v2/knowledge/modify_metadata_fields` | `knowledge:write` | 保留 v2 密钥鉴权 | [knowledge.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/knowledge.py:68) |
| `POST /api/v2/knowledge/upload` | `chat:invoke` | 保留 v2 密钥鉴权 | [knowledge.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/knowledge.py:26) |
| `POST /api/v2/llm/workbench/asr` | `assistant:invoke` | 按本次口径迁至 v3，删除 v2 | [llm.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/llm.py:11) |
| `POST /api/v2/llm/workbench/tts` | `assistant:invoke` | 按本次口径迁至 v3，删除 v2 | [llm.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/llm.py:20) |
| `WS /api/v2/workflow/chat/{workflow_id}` | `workflow:invoke` | 按本次口径删除 v2，保留 v3 | [workflow.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/workflow.py:136) |
| `POST /api/v2/workflow/invoke` | `workflow:invoke` | 按本次口径删除 v2，保留 v3 | [workflow.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/workflow.py:33) |
| `POST /api/v2/workflow/stop` | `workflow:invoke` | 按本次口径删除 v2，保留 v3 | [workflow.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/workflow.py:118) |
| `POST /api/v2/workstation/chat/completions` | `chat:invoke` | 保留 v2 密钥鉴权 | [workstation.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/workstation.py:27) |
| `GET /api/v2/workstation/config` | `chat:invoke` | 保留 v2 密钥鉴权 | [workstation.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/open_endpoints/api/endpoints/workstation.py:18) |

## 8. 全部 v3 路由清单（9 项，2026-09-11 更新）

所有 v3 入口均不要求 API Key / JWT，依赖现有发布资源准入；“免登录”不等于取消资源上线、发布开关和会话归属校验。

| 方法与路径 | 当前准入 | 处理 | 源码 |
|---|---|---|---|
| `WS /api/v3/assistant/chat/{assistant_id}` | 发布准入 | 保留免登录发布入口 | [assistant.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/public_endpoints/api/endpoints/assistant.py) |
| `GET /api/v3/assistant/info/{assistant_id}` | 发布准入 | 保留免登录发布入口 | [assistant.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/public_endpoints/api/endpoints/assistant.py) |
| `POST /api/v3/chat/gen_title` | 发布准入 | 保留免登录发布入口 | [chat.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/public_endpoints/api/endpoints/chat.py:27) |
| `GET /api/v3/chat/history` | 发布准入 | 保留免登录发布入口 | [chat.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/public_endpoints/api/endpoints/chat.py:14) |
| `GET /api/v3/flows/{flow_id}` | 发布准入 | 保留免登录发布入口 | [flow.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/public_endpoints/api/endpoints/flow.py:15) |
| `WS /api/v3/workflow/chat/{workflow_id}` | 发布准入 | 保留免登录发布入口 | [workflow.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/public_endpoints/api/endpoints/workflow.py) |
| `GET /api/v3/llm/workbench` | 发布准入及 flow_id 绑定 | 保留发布页语音配置 | [llm.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/public_endpoints/api/endpoints/llm.py) |
| `POST /api/v3/llm/workbench/asr` | 发布准入及 flow_id 绑定 | 保留录音转文字 | [llm.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/public_endpoints/api/endpoints/llm.py) |
| `POST /api/v3/llm/workbench/tts` | 发布准入及 flow_id 绑定 | 保留文字朗读 | [llm.py](/home/highway/PycharmProjects/bisheng/src/backend/bisheng/public_endpoints/api/endpoints/llm.py) |
