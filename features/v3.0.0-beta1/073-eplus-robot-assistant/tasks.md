# F073 中粮 E+ 智能机器人接入毕昇助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变毕昇内部助手行为的前提下，交付可管理、可单活运行、支持文字/图片/图文混排、严格受机器人绑定知识空间约束的 E+ 长连接机器人。

**Architecture:** 新增 `bisheng.eplus` 独立领域模块与常驻 Worker；SQL 保存配置、协议幂等和独立会话真相，Redis 只承担单活租约、快速通知与发送额度，MinIO 保存 CA/图片对象。E+ 路径通过显式执行上下文复用 `AssistantAgent` 的模型与普通工具，但使用机器人专属知识检索策略；内部助手入口继续走原默认上下文。

**Tech Stack:** Python 3.11、FastAPI、SQLModel/SQLAlchemy、Redis、MinIO、`websockets>=15`、`httpx>=0.28`、`cryptography>=46`、LangGraph/LangChain、React/TypeScript/Zustand、pytest、Vitest。

**Spec:** [spec.md](./spec.md) · [design.md](./design.md) · [test-focus.md](./test-focus.md)

## Global Constraints

- 本功能只进入中粮定制分支 `feat/cofco-909-3.0.0-beta1`，不得回流通用主线。
- 严格遵守 `docs/constitution.md` C1–C8：Router → Endpoint → Service → Repository → DB；MySQL/DM8 双库；租户自动隔离；配置权限只走 `require_business_action`；无硬编码凭据；无跨进程本地文件真相。
- 新增五张完整表由 `*/domain/models` 下 SQLModel + schema discovery 创建，不新增只负责建表的 Alembic revision；模型必须使用 `JsonType`、`LargeText`、`UPDATE_TIME_SERVER_DEFAULT`。
- 一个租户内助手与机器人一对一；机器人可绑定零到多个同租户有效知识空间；管理员只需助手 `edit`，不校验其个人空间权限。
- 机器人知识范围只认当前绑定；空间内暂不应用个人文件/文件夹权限；绑定为空时不得回退到助手原知识或用户权限。
- Secret 永不回显，使用既有 Fernet 能力加密落库；CA 与图片字节只存 MinIO，SQL 只保存对象引用与摘要。
- E+ 协议固定使用探针已验证的帧格式、图片解密算法、逐帧 ACK、30 秒心跳、连续两次失败判死、1–30 秒退避和 `disconnected_event` 不抢回规则。
- 单条流式回答使用同一 `req_id`/`stream.id`、累计全文、20,480 UTF-8 字节上限；首次占位后 5 分钟硬取消并在 6 分钟协议窗口前发送 `finish=true`。
- 同一会话按到达顺序串行执行；同一用户+机器人最多三条 `PREPARING/QUEUED/PROCESSING` 在途，第 4 条固定回复忙碌且不创建 Turn。
- 前端只改 Platform 助手设置页；使用已落地 `@bisheng/ui`/现有组件，三语 i18n 同步，不引入新 UI/状态库。
- 每个后端任务遵循 RED → GREEN；中间件、DM8 和客户真实 E+ 验证作为 CI/环境门禁，不用本地 mock 冒充通过。

## Review Focus

1. **租约丢失与旧连接仍发送**：T013/T014 必须证明租约失效后旧实例停止收发，且 `disconnected_event` 不自动抢回。
2. **空间绑定在检索或流式输出中途变化**：T008/T011/T015 必须证明本轮继续使用启动时空间快照且不中止，下一轮读取新绑定；历史跨版本完整保留。
3. **重复 `msgid`、接管恢复与排队重叠**：T002/T010/T011 必须证明只有一个执行者、队列顺序不乱、已开始任务不盲目重跑。
4. **图片 URL SSRF/跳转/过期/解密异常**：T003/T009 必须验证精确域名白名单、禁止未核验跳转、大小/魔数/时限和失败文案。
5. **流式限额耗尽后发不出终态**：T012 必须预留 `finish=true` 配额，覆盖 Unicode 截断、ACK 超时、长答案与 5 分钟硬取消。

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 2026-09-23 用户确认 |
| design.md | ✅ 已评审 | 2026-09-28 用户确认；客户环境协议探针全链路通过 |
| tasks.md | 🟡 待确认 | 17 个任务，按依赖分 7 个 Wave；已完成命令、依赖与 AC 覆盖自检 |
| 实现 | 🟡 进行中 | 11 / 17 完成 |

## 文件结构

```text
src/backend/bisheng/eplus/
├── api/{router.py,endpoints/bot_config.py}
├── domain/
│   ├── models/eplus.py
│   ├── repositories/eplus_repository.py
│   ├── schemas/{config.py,execution.py,protocol.py}
│   └── services/
│       ├── bot_config_service.py
│       ├── conversation_scheduler.py
│       ├── identity_service.py
│       ├── media_service.py
│       ├── message_service.py
│       ├── reply_stream.py
│       ├── robot_service.py
│       └── robot_space_retrieval.py
├── infrastructure/
│   ├── connection_client.py
│   ├── connection_supervisor.py
│   ├── credential_store.py
│   ├── media_store.py
│   └── protocol.py
└── worker.py
```

`domain` 不依赖 FastAPI/WebSocket/MinIO 实现；`infrastructure` 实现领域端口；API 与 Worker 只调用服务，不直接查询 ORM。

## Tasks

### Wave 0 · 契约与领域真相

### Task 1 (T001): 五张 E+ 表与 schema discovery

**Files:**
- Create: `src/backend/bisheng/eplus/domain/models/eplus.py`
- Create: `src/backend/bisheng/eplus/domain/models/__init__.py`
- Modify: `src/backend/bisheng/core/database/tenant_filter.py`
- Test: `src/backend/test/eplus/test_eplus_models.py`

**Interfaces:**
- Produces: `EPlusBotConfig`、`EPlusBotSpace`、`EPlusInboundMessage`、`EPlusConversation`、`EPlusTurn` 及状态枚举。
- Consumes: design §4.3.1 的字段、唯一键、索引和状态定义。

- [x] **Step 1 — RED:** 写模型元数据测试，断言五表可被 `discover_sqlmodel_module_names()` 发现；断言两项一对一唯一键、空间绑定唯一键、消息幂等键、会话键、轮次顺序键、全部 `tenant_id` 和 `update_time` 约束；补 `is_deleted=false` 逻辑删除字段。
- [x] **Step 2 — Verify RED:** `cd src/backend && .venv/bin/python -m pytest test/eplus/test_eplus_models.py -q`，预期因 `bisheng.eplus.domain.models.eplus` 不存在失败。
- [x] **Step 3 — GREEN:** 用 SQLModel 定义五表；JSON 字段使用 `JsonType`，长文本使用 `LargeText`；把模型模块加入 tenant-filter 强制导入表；不创建 Alembic revision。
- [x] **Step 4 — Verify GREEN:** 重跑模型测试，并执行 `test/database/test_model_registry.py`、`test/database/test_update_time_default_alignment.py`。
- [x] **Step 5 — Commit:** 仅提交本任务文件，提交信息 `feat(eplus): add robot persistence models`。

### Task 2 (T002): Repository、事务状态机与并发幂等

**Files:**
- Create: `src/backend/bisheng/eplus/domain/repositories/eplus_repository.py`
- Test: `src/backend/test/eplus/test_eplus_repository.py`

**Interfaces:**
- Consumes: T001 五表。
- Produces: `EPlusConfigRepository`、`EPlusMessageRepository`、`EPlusConversationRepository`；服务层不直接拼 ORM 查询。

- [x] **Step 1 — RED:** 测试原子插入 `(tenant_id, bot_id, msgid)` 只有一个创建者；条件状态迁移只允许 `RECEIVED→PREPARING→QUEUED→PROCESSING→终态`；事务内分配会话 `next_sequence`；统计用户+机器人三条在途；按 bot 恢复 `QUEUED` 且不把 `PROCESSING` 直接重跑。
- [x] **Step 2 — Verify RED:** 运行 `test/eplus/test_eplus_repository.py`，预期 Repository 缺失失败。
- [x] **Step 3 — GREEN:** 实现异步 Repository；写操作显式检查租户上下文，批量 update/delete 不依赖 SELECT tenant hook；唯一键冲突只返回既有记录，不吞其他完整性错误。
- [x] **Step 4 — Verify GREEN:** 重跑测试；SQLite 只验证语义，MySQL/DM8 并发唯一键进入 T017 环境门禁。
- [x] **Step 5 — Commit:** `feat(eplus): add durable message state repositories`。

### Task 3 (T003): 生产协议编解码与图片加解密基线

**Files:**
- Create: `src/backend/bisheng/eplus/domain/schemas/protocol.py`
- Create: `src/backend/bisheng/eplus/infrastructure/protocol.py`
- Test: `src/backend/test/eplus/test_eplus_protocol.py`
- Modify: `src/backend/test/eplus_robot/test_eplus_probe_protocol.py`（保持探针与生产实现对拍，不让探针成为运行依赖）

**Interfaces:**
- Produces: `EPlusCallback`、有序 `EPlusContentBlock`、订阅/心跳/累计流回复构造器、稳定 stream ID、AES 图片解密和日志脱敏函数。
- Consumes: 已通过客户环境验证的探针帧和算法。

- [x] **Step 1 — RED:** 覆盖 text/image/mixed 顺序、缺 `msgtype` 的混排项、群聊首部 @ 剥离、必填字段拒绝、稳定 stream ID、累计帧上限、未补齐 base64 key、非 16 倍数密文、17–32 字节填充、敏感字段与 URL query 脱敏。
- [x] **Step 2 — Verify RED:** 运行 `test/eplus/test_eplus_protocol.py`，预期模块缺失失败。
- [x] **Step 3 — GREEN:** 从探针抽取纯协议能力，不复制网络循环；生产日志默认不保留消息原文、Secret、aeskey、完整临时 URL。
- [x] **Step 4 — Verify GREEN:** 生产协议测试与 `test/eplus_robot/test_eplus_probe_protocol.py` 同跑，证明算法无漂移。
- [x] **Step 5 — Commit:** `feat(eplus): add verified protocol codec`。

### Wave 1 · 配置管理

### Task 4 (T004): 凭据、CA、空间绑定与目标状态服务

**Files:**
- Create: `src/backend/bisheng/eplus/infrastructure/credential_store.py`
- Create: `src/backend/bisheng/eplus/domain/schemas/config.py`
- Create: `src/backend/bisheng/eplus/domain/services/bot_config_service.py`
- Test: `src/backend/test/eplus/test_eplus_bot_config_service.py`

**Interfaces:**
- Consumes: T001/T002；既有 `encrypt_token/decrypt_token`、MinIO、Assistant/Knowledge 业务服务或只读端口、`require_business_action`；不得从本服务直接查询其 ORM。
- Produces: `get_config()`、`save_config()`、`disable_config()`、`resolve_connection_target()`；返回值只含 `secret_configured`、CA 摘要和连接状态，不含 Secret/CA 正文。

- [x] **Step 1 — RED:** 测试助手 `edit` 是唯一管理授权；无空间个人权限也可绑定同租户有效空间；跨租户/删除/不存在空间拒绝；助手与 bot 双唯一；Secret 缺省保持旧值、传新值递增 `credential_version`；空间集合变化递增 `scope_version`，仅排序变化不递增；CA 只接受 PEM CA 且存 MinIO；解除接入逻辑删除并断开目标状态；仅“助手在线+enabled+完整+未删除”返回应连接。
- [x] **Step 2 — Verify RED:** 运行本测试，预期服务缺失失败。
- [x] **Step 3 — GREEN:** 实现配置事务、凭据加密和内容寻址 CA 对象；配置变更后向 Redis channel `eplus:config_changed` 发布 `{tenant_id, bot_config_id, credential_version, scope_version}`，发布失败不回滚 SQL，worker 周期对账兜底。
- [x] **Step 4 — Verify GREEN:** 重跑测试，并断言日志/响应中没有明文 Secret 或 CA。
- [x] **Step 5 — Commit:** `feat(eplus): add secure robot configuration service`。

### Task 5 (T005): 配置 API 与助手上下线通知

**Files:**
- Create: `src/backend/bisheng/eplus/api/router.py`
- Create: `src/backend/bisheng/eplus/api/endpoints/bot_config.py`
- Modify: `src/backend/bisheng/api/router.py`
- Modify: `src/backend/bisheng/api/services/assistant.py`
- Test: `src/backend/test/eplus/test_eplus_bot_config_api.py`

**Interfaces:**
- Produces: `GET/PUT/DELETE /api/v1/eplus/assistants/{assistant_id}/bot`；PUT JSON 包含 `bot_id`、`connection_url`、可选 `secret`、可选 `ca_pem/remove_ca`、`media_hosts`、`space_ids`、`enabled`。
- Consumes: T004；`AssistantService.update_status` 成功提交后只发目标状态变化通知。

- [x] **Step 1 — RED:** TestClient 覆盖 GET 无配置、创建、更新不回显 Secret、删除/关闭、无 edit 权限、跨租户空间、重复 assistant/bot 冲突、上线/下线通知；验证 URL 仅 `ws/wss` 且 `ws` 返回风险标志。
- [x] **Step 2 — Verify RED:** 运行 API 测试，预期 404/模块缺失。
- [x] **Step 3 — GREEN:** Endpoint 只做认证/Schema/响应包装，业务委托 Service；错误复用现有 assistant/NotFound/Unauthorized/validation，不占新模块码。
- [x] **Step 4 — Verify GREEN:** 重跑 API 测试和现有 `test/api/test_assistant_*` 回归。
- [x] **Step 5 — Commit:** `feat(eplus): expose robot configuration api`。

### Task 6 (T006): Platform 助手设置页

**Files:**
- Create: `src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/EPlusRobotSettings.tsx`
- Create: `src/frontend/platform/src/controllers/API/eplus.ts`
- Create: `src/frontend/platform/src/types/eplus.ts`
- Modify: `src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/Setting.tsx`
- Modify: `src/frontend/platform/public/locales/zh-Hans/bs.json`
- Modify: `src/frontend/platform/public/locales/en-US/bs.json`
- Modify: `src/frontend/platform/public/locales/ja/bs.json`
- Test: `src/frontend/platform/src/test/eplusRobotSettings.test.tsx`

**Interfaces:**
- Consumes: T005 API。
- Produces: 机器人 ID、地址、Secret 轮换、可选 CA、下载域名、多个知识空间、启用开关和连接状态 UI。

- [x] **Step 1 — RED:** 组件测试覆盖加载/保存、Secret 不回填、空间多选、CA 文件 PEM 读取、`ws://` 风险提示、启用前必填校验、绑定影响所有机器人用户的明确提示、连接状态/错误分类展示。
- [x] **Step 2 — Verify RED:** `cd src/frontend && pnpm --filter bisheng test -- eplusRobotSettings.test.tsx`，预期组件缺失失败。
- [x] **Step 3 — GREEN:** 先读 UI specs；使用现有 Input/Switch/Accordion/KnowledgeSelect/Dialog，不把 HTTP 放进 Zustand；主 `Setting.tsx` 只挂载独立组件；三语同 PR。
- [x] **Step 4 — Verify GREEN:** 运行组件测试、`pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`。
- [x] **Step 5 — Commit:** `feat(eplus): add assistant robot settings ui`。

### Wave 2 · 助手核心与知识安全边界

### Task 7 (T007): 助手显式执行上下文与多模态消息

**Files:**
- Create: `src/backend/bisheng/assistant/domain/schemas/execution.py`
- Modify: `src/backend/bisheng/api/services/assistant_agent.py`
- Test: `src/backend/test/eplus/test_assistant_execution_context.py`

**Interfaces:**
- Produces: `AssistantExecutionContext`（入口类型、真实用户、有序 LangChain 内容块、机器人空间快照、scope_version、取消检查）；`AssistantAgent.run/astream` 兼容旧 `query: str`，新增可选 context。
- Consumes: 内部入口默认 `None`；后续 T008/T009/T015 注入 E+ context。

- [x] **Step 1 — RED:** 测试旧字符串输入构造结果字节级不变；多模态列表作为同一个 HumanMessage；token 裁剪可处理字符串与内容块；E+ 上下文不修改 Assistant/AssistantLink；取消信号在 Agent/工具循环边界传播。
- [x] **Step 2 — Verify RED:** 运行本测试，预期 context 类型不存在。
- [x] **Step 3 — GREEN:** 抽出内容 token 计数与输入组装；旧 `run/astream(query=...)` 保持；E+ 相关协议字段不得进入 AssistantAgent。
- [x] **Step 4 — Verify GREEN:** 重跑本测试及现有 assistant runlog/citation/LLM executor 回归。
- [x] **Step 5 — Commit:** `refactor(assistant): support explicit execution context`。

### Task 8 (T008): RobotSpaceRetrievalPolicy 与工具防旁路

**Files:**
- Create: `src/backend/bisheng/eplus/domain/services/robot_space_retrieval.py`
- Modify: `src/backend/bisheng/api/services/assistant_agent.py`
- Test: `src/backend/test/eplus/test_robot_space_retrieval.py`
- Test: `src/backend/test/eplus/test_eplus_tool_scope.py`

**Interfaces:**
- Consumes: T002 当前绑定、T007 context、KnowledgeRag/Milvus/ES。
- Produces: `RobotSpaceRetrievalPolicy.build_tool()`；只按本轮空间快照中的有效空间 ID 检索并对结果做文件状态/空间归属后过滤，不在执行中重读机器人绑定。

- [x] **Step 1 — RED:** 覆盖零绑定为空、多个空间合并去重、发送者拥有额外空间也不能扩大、配置管理员无文件权限仍可读绑定空间 CUSTOM 文件、已删除/非成功/移出空间文件剔除、执行中 scope_version 改变仍使用本轮快照、内部入口仍走原 F041 visibility。
- [x] **Step 2 — RED:** 工具矩阵测试覆盖：E+ 不加载 AssistantLink 原知识入口；普通外部工具保留原授权；含毕昇知识节点的 Flow 必须接收同一 scope，否则 E+ 入口拒绝装载；API/MCP 明确命中毕昇知识接口但无法注入范围时失败关闭。
- [x] **Step 3 — Verify RED:** 运行两份测试，预期 policy 缺失/AssistantAgent 行为错误。
- [x] **Step 4 — GREEN:** 实现机器人专属检索，不调用 `KnowledgeFileVisibilityService`；每次检索只使用本轮启动时的空间快照并做结果后过滤；AssistantAgent 仅在 E+ context 分支替换知识工具。
- [x] **Step 5 — Verify GREEN:** 重跑两份测试及 F041 `test_space_flow_retrieval.py`、`test_assistant_knowledge_auth_gate.py`。
- [x] **Step 6 — Commit:** `feat(eplus): enforce robot knowledge scope`。

### Task 9 (T009): 图片下载、MinIO 与能力分流

**Files:**
- Create: `src/backend/bisheng/eplus/infrastructure/media_store.py`
- Create: `src/backend/bisheng/eplus/domain/services/media_service.py`
- Test: `src/backend/test/eplus/test_eplus_media_service.py`

**Interfaces:**
- Consumes: T003 image block/decrypt、T004 CA/allowlist、T007 content blocks；参考 workstation 日常模式图片能力，不调用其整条业务流程。
- Produces: 持久 `EPlusMediaRef`（MinIO key/hash/type/size）和视觉块或 OCR 文本块。

- [x] **Step 1 — RED:** 覆盖精确 host 白名单、IP/私网重绑定和未核验重定向拒绝、TLS CA、5 分钟下载超时、20 MiB 上限、魔数、AES 失败、内容寻址 MinIO key；视觉模型走 image block，非视觉走已配置 OCR，两者均不可用返回明确能力错误；同条 mixed 保序。
- [x] **Step 2 — Verify RED:** 运行本测试，预期服务缺失失败。
- [x] **Step 3 — GREEN:** 下载后立即解密校验并写 MinIO；SQL/日志不存 URL query、aeskey 或字节；对象读取不依赖本地文件。
- [x] **Step 4 — Verify GREEN:** 重跑测试和现有 MinIO/日常对话图片回归。
- [x] **Step 5 — Commit:** `feat(eplus): add secure media ingestion`。

### Wave 3 · 消息准入、排队与回复

### Task 10 (T010): 身份映射、消息准入与三条在途

**Files:**
- Create: `src/backend/bisheng/eplus/domain/services/identity_service.py`
- Create: `src/backend/bisheng/eplus/domain/services/message_service.py`
- Test: `src/backend/test/eplus/test_eplus_message_admission.py`

**Interfaces:**
- Consumes: T002/T003/T009；`WECOM_SOURCE='wecom'` + `UserDao.aget_by_source_external_id`。
- Produces: `AdmissionResult`（duplicate/no_permission/busy/queued）与已持久化 inbound/turn。

- [x] **Step 1 — RED:** 覆盖 aibotid 不符拒绝、缺 msgid 拒绝、重复 msgid 复用原状态不重答、用户不存在/禁用/跨租户固定「无权限使用」且不创建 Turn、群聊逐消息验人、前三条入队、第 4 条 `REJECTED_BUSY`、图片在排队前保存、失败图片仍保留可处理文字。
- [x] **Step 2 — Verify RED:** 运行本测试，预期服务缺失失败。
- [x] **Step 3 — GREEN:** 先落 inbound 唯一键再验人；准入与在途统计在同事务完成；拒绝结果只生成安全终态任务，不触发助手/工具/检索。
- [x] **Step 4 — Verify GREEN:** 重跑测试，增加并发 `gather` 断言只有一个 queued owner。
- [x] **Step 5 — Commit:** `feat(eplus): add durable message admission`。

### Task 11 (T011): 独立会话历史、串行消费与崩溃恢复

**Files:**
- Create: `src/backend/bisheng/eplus/domain/services/conversation_scheduler.py`
- Test: `src/backend/test/eplus/test_eplus_conversation_scheduler.py`

**Interfaces:**
- Consumes: T002/T010。
- Produces: 单聊键 `(bot,single,sender)`、群聊键 `(bot,group,chatid)`；每会话单消费者；`next_ready_turn()`、`complete_and_wake_next()`、`recover_queued()`。

- [x] **Step 1 — RED:** 覆盖不同单聊/群互不串历史、群内发送者共享群会话但逐条身份记录、同会话严格序号执行、前一轮完成后自动取下一轮、scope_version 变化仍加载完整成功历史、QUEUED 恢复、PROCESSING 标记失败/人工恢复而不自动重跑。
- [x] **Step 2 — Verify RED:** 运行本测试，预期 scheduler 缺失失败。
- [x] **Step 3 — GREEN:** 内存 Event 只做唤醒，SQL 是队列真相；媒体处理前用 `PREPARING` 预占顺序；执行领取时刷新最新范围快照并生成 fencing token；消费者退出/接管后可从数据库恢复；不使用 Celery。
- [x] **Step 4 — Verify GREEN:** 重跑测试，并执行取消/异常路径确保释放在途。
- [x] **Step 5 — Commit:** `feat(eplus): serialize robot conversations`。

### Task 12 (T012): 流式组包、ACK 串行、限额与硬超时

**Files:**
- Create: `src/backend/bisheng/eplus/domain/services/reply_stream.py`
- Test: `src/backend/test/eplus/test_eplus_reply_stream.py`

**Interfaces:**
- Consumes: T003 帧构造器；发送端口 `EPlusFrameSender.send_with_ack(frame)`。
- Produces: `EPlusReplyStream`，接收模型片段并输出占位/累计刷新/最终帧。

- [x] **Step 1 — RED:** 覆盖首帧 ACK 失败不启动下游、1–2 秒或阈值刷新、不是逐 token 发送、累计全文、同 req_id/id、UTF-8 安全截断、每会话 30/min 与 1000/hour、终态配额预留、errcode/ACK 超时终止、5 分钟取消并 `finish=true`。
- [x] **Step 2 — Verify RED:** 运行本测试，预期模块缺失失败。
- [x] **Step 3 — GREEN:** Redis 限额键只做速率状态；所有终态持久化 sent/error 分类；回复流不因空间配置变化中止。
- [x] **Step 4 — Verify GREEN:** 使用 fake clock 重跑完整边界测试，禁止真实 sleep。
- [x] **Step 5 — Commit:** `feat(eplus): add bounded cumulative reply stream`。

### Wave 4 · 长连接与单活

### Task 13 (T013): 正式 WebSocket connection client

**Files:**
- Create: `src/backend/bisheng/eplus/infrastructure/connection_client.py`
- Test: `src/backend/test/eplus/test_eplus_connection_client.py`

**Interfaces:**
- Consumes: T003/T012；配置提供 URL、解密 Secret、可选 CA bytes。
- Produces: `EPlusConnectionClient` 实现 `EPlusFrameSender`，向上抛 message/event，管理 ACK future。

- [x] **Step 1 — RED:** 本地 fake E+ 覆盖 ws、带自签 CA 的 wss、订阅成功/失败、每 30 秒 ping、连续两次 ACK 失败关闭、同 req_id 串行、不同 req_id 可独立等待、`disconnected_event` 分类为 TAKEN_OVER、Secret/URL query 不入日志。
- [x] **Step 2 — Verify RED:** 运行本测试，预期 client 缺失失败。
- [x] **Step 3 — GREEN:** 把探针经过真实环境验证的连接行为移植到生产客户端；不依赖 `aibot` SDK；收发循环与消息执行任务隔离。
- [x] **Step 4 — Verify GREEN:** 重跑 connection 与 probe runtime 两套 fake-server 测试。
- [x] **Step 5 — Commit:** `feat(eplus): add production websocket client`。

### Task 14 (T014): Redis 单活租约与目标状态对账

**Files:**
- Create: `src/backend/bisheng/eplus/infrastructure/connection_supervisor.py`
- Test: `src/backend/test/eplus/test_eplus_connection_supervisor.py`

**Interfaces:**
- Consumes: T004 `resolve_connection_target()`、T013 client、`TokenSafeRedisLock`。
- Produces: 每机器人一条连接任务；订阅 Redis 变更通知并周期扫描 SQL；连接状态写回 DB。

- [x] **Step 1 — RED:** 覆盖两个实例只有一个获得租约、续租失败立即取消连接、持有者宕机 TTL 后接管、普通断线按 1/2/4…30 秒退避重连且退避期间持续监控租约、启用但助手离线不连、上线后连接、下线/关闭/逻辑删除断开、凭据版本变化重连、通知丢失被周期对账修复、TAKEN_OVER 冻结且不抢回。
- [x] **Step 2 — Verify RED:** 运行本测试，预期 supervisor 缺失失败。
- [x] **Step 3 — GREEN:** 每 bot 使用 token-safe lease，监控覆盖连接与重连退避；租约丢失时关闭连接并取消本机该机器人任务；RUNNING 完成回写校验 execution token；普通重连切换队列共享发送端；本地 task map 不是状态真相；Supervisor 停止时逐连接关闭并释放自己持有的 token。
- [x] **Step 4 — Verify GREEN:** 重跑测试并开启 asyncio debug 检查无泄漏 task。
- [x] **Step 5 — Commit:** `feat(eplus): supervise single-active robot connections`。

### Wave 5 · 完整业务编排与部署

### Task 15 (T015): EPlusRobotService 完整消息执行

**Files:**
- Create: `src/backend/bisheng/eplus/domain/schemas/execution.py`
- Create: `src/backend/bisheng/eplus/domain/services/robot_service.py`
- Test: `src/backend/test/eplus/test_eplus_robot_service.py`

**Interfaces:**
- Consumes: T007–T013。
- Produces: `handle_message(bot_context, callback)` 与 `run_turn(turn_id, sender)`；connection client 不直接调用 AssistantAgent。

- [x] **Step 1 — RED:** 端到端 fake Assistant 覆盖四类消息、无权限、重复、忙碌、图片失败+文字继续、零绑定知识为空、执行中改绑本轮继续且下一轮使用新绑定、模型/工具异常安全终态、同会话后续轮加载跨版本完整历史、不同会话并发、首帧失败不启动 Agent。
- [x] **Step 2 — Verify RED:** 运行本测试，预期 orchestrator 缺失失败。
- [x] **Step 3 — GREEN:** 按“协议→幂等→身份→预占顺序→媒体→排队→占位→最新 scope snapshot→Assistant→buffer→终态”编排；外层硬超时覆盖模型/工具无输出场景；每个异常落明确终态并释放在途；日志仅记录脱敏 ID/分类/耗时。
- [x] **Step 4 — Verify GREEN:** 重跑 T015 及 T007–T014 全部 eplus 测试。
- [x] **Step 5 — Commit:** `feat(eplus): integrate robot assistant orchestration`。

### Task 16 (T016): Worker 入口、容器服务与生命周期

**Files:**
- Create: `src/backend/bisheng/eplus/worker.py`
- Modify: `src/backend/entrypoint.sh`
- Modify: `docker/bisheng/entrypoint.sh`
- Modify: `docker/docker-compose.yml`
- Modify: `docker/docker-compose-office.yml`
- Test: `src/backend/test/eplus/test_eplus_worker_lifecycle.py`

**Interfaces:**
- Consumes: T014/T015、`initialize_app_context/close_app_context`。
- Produces: `python -m bisheng.eplus.worker` 独立常驻进程与 `eplus` entrypoint mode；独立 `backend_eplus_worker` 服务。

- [x] **Step 1 — RED:** 测试启动初始化 DB/Redis/MinIO/权限运行时、Supervisor 启动、SIGTERM 有界关闭、关闭连接/租约/HTTP client、鉴权恢复完成前不准入新消息、同一连接回调严格按到达顺序准入；compose 静态测试断言独立服务使用同一配置但不依赖共享本地数据。
- [x] **Step 2 — Verify RED:** 运行 lifecycle 测试，预期 worker/compose 配置缺失失败。
- [x] **Step 3 — GREEN:** 新进程不运行 Celery/Linsight；API、Celery 和 E+ Worker 可部署在不同主机；所有共享字节通过 MinIO。
- [x] **Step 4 — Verify GREEN:** shell 语法、lifecycle、YAML 解析与最小 import smoke 通过；本机未安装 Docker CLI，`docker compose config` 记入 T017 未验证项。
- [x] **Step 5 — Commit:** `feat(eplus): add dedicated connection worker deployment`。

### Wave 6 · 门禁、回归与交付

### Task 17 (T017): 安全回归、E2E 与上线记录

**Files:**
- Create: `features/v3.0.0-beta1/073-eplus-robot-assistant/e2e-checklist.md`
- Modify: `features/v3.0.0-beta1/073-eplus-robot-assistant/test-focus.md`
- Modify: `features/v3.0.0-beta1/073-eplus-robot-assistant/customer-checklist.md`
- Modify: `features/v3.0.0-beta1/073-eplus-robot-assistant/tasks.md`
- Test: `src/backend/test/eplus/test_eplus_security_guards.py`

**Interfaces:**
- Consumes: T001–T016。
- Produces: 可复跑的自动化/环境验收证据与发布门禁。

- [x] **Step 1 — RED:** 静态/行为守卫断言无硬编码 Bot Secret、日志禁消息原文/Secret/aeskey/完整 URL、E+ 路径不调用 `KnowledgeFileVisibilityService`、内部入口不读取 E+ 表、连接 Worker 不使用本地文件作为跨进程真相。
- [x] **Step 2 — Verify RED:** 守卫发现既有 ReAct 调试日志会输出完整模型结果并明确失败。
- [x] **Step 3 — GREEN:** 修复日志泄露；backend E+、assistant/F041、frontend lint/i18n/E+ UI、arch-guard、单头检查通过；Client typecheck 被两处既有无关错误阻断，已记录在 `e2e-checklist.md`。
- [ ] **Step 4 — Environment gates:** 在 MySQL 与 105 DM8 验五表/唯一键；Redis 双实例租约接管；MinIO 跨进程图片；客户 E+ 验文本/图片/mixed/群聊、重复 msgid、三条排队、第 4 条忙碌、断线、执行中改绑本轮继续且下一轮生效、无用户、互斥空间越权；不能完成的项必须标“未验证”，不得写“通过”。
- [x] **Step 5 — E2E:** 使用 `/e2e-test features/v3.0.0-beta1/073-eplus-robot-assistant` 生成环境只读 E2E 与手工清单；本地无运行中目标环境，结果为 PARTIAL，未冒充通过。
- [ ] **Step 6 — Final review:** `/code-review --base <909 分支合入前基线>`，Important/Critical 全部 RED→GREEN 修复；更新任务状态与偏差记录。
- [ ] **Step 7 — Commit:** `test(eplus): close integration and security gates`。

## 依赖图

```text
T001 → T002 → T004 → T005 → T006
  │      │       └────────────→ T014 ─→ T016
  │      └→ T010 → T011 ─────────┐
T003 → T009 ─────────────────────┤
  ├→ T012 ─→ T013 ───────────────┤
T007 → T008 ─────────────────────┤
                                 └→ T015 → T016 → T017
```

## 验收标准覆盖

| 验收标准 | 主任务 | 核心证明 |
|---|---|---|
| AC-01 | T004、T005、T015 | 助手/机器人一对一，消息走绑定助手并回原会话 |
| AC-02～04 | T010、T015 | `wecom` + 原始 userid 精确映射，逐消息校验真实发送者 |
| AC-05 | T002、T010、T015 | `(tenant, bot, msgid)` 持久幂等，不重复执行/回复 |
| AC-06 | T011、T015 | 单聊/群聊会话键和历史隔离 |
| AC-07～10 | T003、T007、T009、T015 | 文字/图片/混排保序、下载解密、视觉或 OCR、失败不编造 |
| AC-11 | T004～06、T014、T016 | 完整配置、Secret/CA 安全、上线连接/下线断开、状态可见 |
| AC-12～16 | T004、T008、T011、T015 | 机器人绑定空间是新一轮检索上限，本轮使用启动快照、历史跨版本保留，知识工具不可旁路 |
| AC-17 | T007、T008、T017 | 内部助手默认路径与既有权限/历史保持不变 |
| AC-18 | T010、T015 | 非目标机器人或来源不明时失败关闭 |
| AC-19 | T003、T012～15 | 协议时限、频率、ACK 和明确失败终态 |
| AC-20 | T002、T009～12、T015 | 同会话串行、图片入队前保存、三条在途和第 4 条忙碌 |

## 实际偏差记录

> 推翻已确认的产品/安全决策时必须先停下与用户重确认；普通实现裁决记录为 `T<NNN> 偏离 → design 决策/坑 <X>（原因）`。

- T016 偏离 → 本机未安装 Docker CLI，无法执行 `docker compose config`；已用 PyYAML 解析、服务静态约束和 shell 语法测试代替本地检查，正式环境仍需执行 Compose 门禁。
- T017 偏离 → 本地没有客户数据库、双 Worker 或真实毕昇+E+ 集成环境；环境项明确保留为未验证，仅记录已通过的客户协议探针，不将其等同于完整验收。
