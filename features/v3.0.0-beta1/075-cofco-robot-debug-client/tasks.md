# F075 Robot Debug Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if the user selects delegation. Read spec.md and design.md before implementing task-by-task.

**Goal:** 管理员不经过客户 E+ App，即可观察真实机器人助手的知识问答。

**Architecture:** 配置区按钮打开独立页面；独立 FastAPI 进程复用登录身份和助手执行器。仅允许机器人知识工具，每轮读取真实绑定，返回答案与请求局部追踪，不启动正式 Worker。

**Tech Stack:** Python 3.11 / FastAPI / LangChain / Redis；Platform React / TypeScript / 既有组件与请求层，不新增库。

**Spec:** [spec.md](./spec.md)、[design.md](./design.md)。

## Global Constraints

- 第一版仅文字问答，工具聚焦机器人知识检索；其他有业务副作用的工具不执行。
- 不伪造模型或检索结果，不改提示词以使诊断测试“通过”。
- 不向浏览器返回 Bot Secret、模型 APIKey、配置全文或认证头。
- 不修改正式 E+ 会话/轮次，不建立客户连接；不新增表或数据库迁移。
- 默认关闭，仅授权管理员使用；校验助手 edit、租户、有效绑定和测试用户。
- 本地不执行前端测试或构建；这些检查交给镜像构建阶段，后端验证照常。
- 独立启动命令不得使用正式 main.py 的 lifespan，不运行初始化数据、迁移或默认数据回填。
- 开发分支 `feat/075-cofco-robot-debug-client-3.0.0-beta1`，最终仅合入 909。标准目录式分支名与已有 `feat/3.0.0-beta1` ref 冲突，因此换为不冲突名称，不重命名既有分支。

## Review Focus

1. 手工访问地址、伪造用户 ID、跨租户和管理员离任：每轮重新校验，不能仅靠按钮隐藏。
2. 请求期间改绑：本轮快照完成、下一轮重新读取；不得额外加入在途撤权或历史过滤。
3. 多次调用、同名文件和来源字段缺失：完整顺序追踪，元数据与实际模型结果分开展示。
4. 老 ReAct 将工具异常转为文字：即便最终回复成功，追踪中仍明确显示本次工具失败。
5. 断开、超时与多进程争抢：取消计算并释放仅属于调试服务的 Redis 准入；不得清理正式租约。

## 状态与依赖

| 文档 | 状态 |
|---|---|
| spec.md | 用户已确认 |
| design.md | 用户已确认 |
| tasks.md | 用户批准 native 当前分支执行，实施中 |

顺序：T01 → T02 → T03 → T04 → T05 → T06 → T07 → T08 → T09。每个测试先写、运行观察失败，再实现；每个任务完成记录结果与提交。

## T01：准入契约与失败测试（后端 Domain）

**文件：** 新增 `src/backend/bisheng/eplus/domain/schemas/debug.py`；新增 `src/backend/test/eplus/test_eplus_debug_admission.py`。

**产出接口：** `DebugHistoryTurn(question: str, answer: str)`；`DebugRunRequest(query: str, test_user_id: int, history: list[DebugHistoryTurn])`；`DebugContext` 包含租户、操作人、测试用户、助手、绑定快照及脱敏展示信息。请求禁止额外字段，不接受 space_ids 或模型覆盖。

**覆盖 AC:** AC-01, AC-04, AC-09。

- [ ] 请求约束：query 去除空白后 1–4096 字；history 最多 20 轮、总计 64000 字；正数用户 ID；仅完整问题/回答对，不接收任意 system/tool 消息。
- [ ] 写准入替身与失败测试：普通用户、跨租户、禁用/不存在测试用户、无助手 edit、离线/删除助手、删除/无绑定机器人和失效空间均拒绝；管理员当前租户内的有效用户可通过，不要求存在客户 Bot Secret。
- [ ] 使用依赖注入的读取/授权协议，测试不得连真实数据库或模型。例如：

```python
def test_run_request_cannot_expand_space_scope():
    with pytest.raises(ValidationError):
        DebugRunRequest(query="find source", test_user_id=1, space_ids=[999])
```

- [ ] 在 backend 执行 `uv run pytest test/eplus/test_eplus_debug_admission.py -q`；准入实现尚不存在时记录失败，约束测试应先通过。

## T02：真实配置准入（后端 Domain）

**文件：** 新增 `src/backend/bisheng/eplus/domain/services/debug_admission.py`；新增 `src/backend/bisheng/eplus/infrastructure/debug_adapters.py`。依赖 T01。

**产出接口：** `DebugAdmissionService.context(operator, assistant_id: str, test_user_id: int) -> DebugContext`。输入只认认证用户和当前租户；读取适配器复用 `EPlusConfigRepository`、助手读取、有效用户和成员关系查询，服务不写 ORM。

- [ ] 使用既有管理员身份检查及 `require_business_action(..., resource_type="assistant", action="edit")`，不把后台菜单权限当管理员身份。
- [ ] 读取已保存、在线助手和非删除配置、有效空间；展示默认测试用户，其他用户需查询并校验当前租户活动成员资格；输出明确测试身份和外部身份字段是否存在，不模拟 IAM 推送成功。
- [ ] 仅返回列举的安全展示字段，禁止序列化完整 ORM/config。最小流程：

```python
await authorization.require_admin(operator)
await authorization.require_assistant_edit(operator, assistant_id)
snapshot = await reader.load_context(assistant_id, test_user_id)
return validate_debug_context(snapshot, operator)
```

`authorization`、`reader` 在本任务定义为明确的异步 Protocol；`validate_debug_context` 同文件实现 T01 所列状态检查。

- [ ] 重跑 T01，新增改绑前后连续两轮返回不同快照、只读调用无 commit/新增业务记录的测试并通过。
- [ ] 局部 ruff、任务自审、记录提交。

## T03：真实工具结果追踪（后端 Domain / Infrastructure）

**文件：** 新增 `src/backend/bisheng/eplus/infrastructure/debug_trace.py`；新增 `src/backend/test/eplus/test_eplus_debug_trace.py`。依赖 T01。

**产出接口：** `DebugTrace` 持有 run_id、递增 seq、有界事件队列；`observe_robot_tool(tool, trace) -> BaseTool` 返回请求局部工具实例。工具名、description、args_schema 和结果不变。

**覆盖 AC:** AC-05, AC-06, AC-07, AC-09。

- [ ] 先测试工具输入输出原样相同、两次调用顺序、相同文件名不同空间、空结果、缺字段和异常：

```python
observed = observe_robot_tool(real_wrapper, trace)
result = await observed.ainvoke({"query": "model reformulated question"})
assert result == expected_formatted_output
assert trace.events[-1].data["model_tool_output"] == result
assert trace.events[-1].data["retrieval_metadata"][0]["document_id"] == 101
```

测试工具使用现有 `AssistantCitationToolWrapper` 和测试 Document，只替换检索资源，不绕开真实包装与格式化。

- [ ] 在真实包装器的请求局部子类中捕获格式化前 Document 元数据；通过工具调用边界记录 tool_start/end/error。内部检索不另开模型可见工具，不添加 prompt。
- [ ] 同步/异步调用均追踪；异常记录脱敏类别后原样抛出，不改变旧 ReAct 捕获行为。显示观察器类和被观察的原工具类，避免误称观察器就是生产实例类型。
- [ ] 回调产生事件不使用全局替换。事件超过 2 MiB 时明确失败，不静默截断后伪装成完整模型输入；正文不默认进服务日志。
- [ ] 执行 `uv run pytest test/eplus/test_eplus_debug_trace.py test/eplus/test_eplus_robot_citation_boundary.py -q`，记录红绿结果及提交。

## T04：真实助手调试执行（后端 Infrastructure）

**文件：** 新增 `src/backend/bisheng/eplus/infrastructure/debug_runtime.py`；新增 `src/backend/test/eplus/test_eplus_debug_runtime.py`。依赖 T02、T03。

**产出接口：** `DebugAssistantRuntime.run(context: DebugContext, request: DebugRunRequest, trace: DebugTrace) -> AsyncIterator[str]`；只对该实例创建助手，不导入/启动 worker supervisor。

**覆盖 AC:** AC-02, AC-03, AC-04, AC-05, AC-07, AC-10。

- [ ] 先测试使用配置模型和 prompt、EPLUS 上下文、独立随机会话标识、历史转换、知识工具外其他工具不执行、无调用计数 0、两种模式均记录真实工具结果。
- [ ] 初始化现有 `AssistantAgent` 模型和 E+ 工具；读取正式工具清单，再仅保留 `robot_scope_enforced` 的知识工具，包装追踪，之后创建原执行器：

```python
await agent.init_llm()
await agent.init_tools(context=execution_context)
formal_tools = tuple(agent.tools)
agent.tools = [observe_robot_tool(t, trace) for t in formal_tools if is_robot_knowledge_tool(t)]
await agent.init_agent()
```

`is_robot_knowledge_tool` 在本文件校验包装器内部工具的 robot_scope_enforced 标志，不靠工具名猜测。不得添加知识工具以外的可调用入口。

- [ ] 用 `HumanMessage/AIMessage` 转换测试历史，调用原 `agent.astream`，只返回助手 AI 文本；旧 ReAct 整段返回如实显示。禁止开启历史文件记录，调试运行不调用正式消息存储。
- [ ] 测试旧 ReAct 调用报错但最终回答成功时 trace 仍保留 tool_error；函数调用模式多次工具调用、无结果和取消都能观察。替身模式测试与真实模型现场验收分开记录。
- [ ] 执行新 runtime/trace 和 `test/eplus/test_assistant_execution_context.py`，任务自审并提交。

## T05：独立进程、事件 API 与取消（后端 API）

**文件：** 新增 `src/backend/bisheng/eplus/api/debug_router.py`；新增 `src/backend/test/eplus/test_eplus_debug_api.py`。依赖 T04。

**产出接口：** `create_debug_router(service, runtime, admission_gate) -> APIRouter`；GET context 和 POST run 路径见 design；增加 GET `/robot-debug/api/status`，仅已登录管理员返回 enabled，其他身份不提供调试配置。

**覆盖 AC:** AC-01, AC-03, AC-08, AC-09。

- [ ] 先写 HTTP/SSE 测试：未登录、直访普通用户、伪造用户、非法额外空间、run 前重新鉴权、开始/结果/结束序号，以及没有模型调用时提前拒绝。
- [ ] 使用 `UserPayload` 和既有租户中间件认证，不接受浏览器自报租户；管理员身份不依赖前端字段。
- [ ] 使用请求任务与 StreamingResponse 取消，完成/失败只产生一个终态；断开后取消 producer 并 await 清理，不留下无引用后台任务：

```python
try:
    async with admission_gate.acquire():
        async with asyncio.timeout(180):
            await execute_debug_run()
finally:
    await close_request_tasks()
```

本文件实现 `execute_debug_run` 和 `close_request_tasks`，分别处理 producer/事件队列与请求局部任务清理。

- [ ] 入站请求大小在读取正文前限制，history 及工具事件另有上限；SSE 不缓存、不自动重试问答，失败不回传供应商原始认证错误内容。
- [ ] 用 ASGI 断开消息证明执行取消；超时和取消不会调用正式 turn/message/连接逻辑。执行 `uv run pytest test/eplus/test_eplus_debug_api.py -q` 并提交。

## T06：独立启动与全局准入（后端 Infrastructure）

**文件：** 新增 `src/backend/bisheng/eplus/debug_app.py`；新增 `src/backend/bisheng/eplus/infrastructure/debug_gate.py`。依赖 T05；向 T05 测试文件追加启动及准入测试。

**产出接口：** `debug_app.create_app() -> FastAPI`（uvicorn --factory）；`RedisDebugGate.acquire()` 异步上下文管理器。

**覆盖 AC:** AC-03, AC-08, AC-09。

- [ ] 先测试默认关闭、显式开启、不得挂载正式 router、不得调用初始化数据/worker/迁移、数据库/Redis/检索初始化和关闭、两个准入对象争抢。
- [ ] 必须设置 `EPLUS_DEBUG_ENABLED=true` 才启动；监听默认 localhost:7871，单 worker。生命周期调用 `initialize_app_context(settings)` / `close_app_context()`，注册既有权限运行时，不执行 main.py lifespan。
- [ ] Redis 键专用 `eplus:debug:active-run`，随机 token，SET NX EX 210；释放使用 token 比较删除，180 秒总超时覆盖准备与推理，绝不删除他人/正式 Worker 的租约：

```python
acquired = await redis.set("eplus:debug:active-run", token, nx=True, ex=210)
if not acquired:
    raise HTTPException(status_code=429, detail="debug capacity reached")
```

- [ ] 主动禁止或检测 `BISHENG_RECORD_HISTORY` 的本地完整记录开关；注册认证异常处理，启动/错误日志不带正文、密钥或配置全文。
- [ ] 执行 T05 测试和后端 E+ 回归；真实 Redis 准入在现场验证，单元测试不能冒充跨进程验证。提交本任务。

## T07：页面请求层与事件消费（前端 Platform）

**文件：** 新增 `src/frontend/platform/src/controllers/API/eplusDebug.ts`；新增 `src/frontend/platform/src/pages/BuildPage/assistant/robotDebug/useRobotDebug.ts`。依赖 T05。

**产出接口：** `getRobotDebugContext(assistantId, testUserId?)`；`runRobotDebug(request, onEvent, signal)`；`useRobotDebug` 管理临时历史和一次一轮，不使用新状态库。

- [ ] SSE 传输能力放在 API 层，复用既有认证/错误处理策略；不直接 import axios。处理多行 data、任意网络分片、UTF-8、连续多个事件、序号和 run_id，禁止重试 POST 导致重复模型执行。
- [ ] 暴露类型化事件 union、取消 AbortSignal；结束后只将成功回答存入当前页面内存。改助手/测试用户、清空或卸载时先取消并清空，不把旧请求内容写入新身份历史。
- [ ] 从挂载当前助手的页面调用：

```typescript
await runRobotDebug({ assistantId, query, testUserId, history }, handleEvent, controller.signal)
```

- [ ] 编写网络分片/取消用例随代码交镜像阶段验证；按用户约定不在本地运行前端测试或构建。静态检查请求目标固定同源，不拼接外部任意 URL。
- [ ] 自审并提交。

## T08：配置区入口和独立页面（前端 Platform）

**文件：** 新增 `src/frontend/platform/src/pages/BuildPage/assistant/robotDebug/index.tsx`；新增 `src/frontend/platform/src/pages/BuildPage/assistant/robotDebug/DebugTracePanel.tsx`。依赖 T07。入口接线另修改 `EPlusRobotSettings.tsx`、`src/frontend/platform/src/routes/index.tsx`，分独立小提交。

- [ ] 实现顶部脱敏配置摘要、合法测试用户选择、文字聊天/停止/清空，以及每轮追踪；不把检索元数据混入模型结果，也不补猜缺失空间。
- [ ] 一轮结束摘要明确显示 0/多次调用；工具错误与最终回答分开，ReAct 显示整段返回说明；保存配置后再测试，未保存内容不参与。
- [ ] 配置区按钮使用同源固定路径携带 assistantId，不传 secret/token；只在 `VITE_EPLUS_DEBUG_ENABLED=true` 且 status 确认管理员时显示，不增加一级菜单。独立页面同样有服务器准入。
- [ ] 所有新组件 named exports，使用现有/已落地组件；不改变 UI 规范或新增视觉样式。新增文字提取到 zh-Hans/en-US/ja 现有 build 语言文件，分小提交处理三份语言文件，不编辑 api_errors 生成产物。
- [ ] 前端测试覆盖关闭时无按钮、非管理员无入口、当前助手带入、失败/停止/清空、缺失来源及历史隔离；提交测试但本地不运行。镜像构建阶段和部署后验证，未执行不能标通过。

## T09：部署说明、后端回归及现场验收（运维 / 验证）

**文件：** 新增 `docs/cofco-robot-debug-client.md`；更新本任务文档及设计现状。依赖 T06、T08。

**覆盖 AC:** AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10。

- [ ] 说明独立启动和同源代理：仅将 `/robot-debug/api/` 转给独立服务，`/robot-debug/` 页面由前端 SPA 路由提供；关闭代理缓冲，转发原认证头/cookie，不设置固定管理员，不暴露独立服务到公网。
- [ ] 示例启动命令（backend 目录，沿用本环境 config，不嵌密钥）：

```bash
EPLUS_DEBUG_ENABLED=true uv run uvicorn bisheng.eplus.debug_app:create_app --factory --host 127.0.0.1 --port 7871 --workers 1 --no-access-log
```

- [ ] 文档列启停、前端构建开关、健康检查和五类真实问答验收。停止独立服务/移除调试代理即可回收，正式服务无需改配置/数据库回滚；代码发布仍按现有镜像流程，不能把新增前端路由说成零部署。
- [ ] `uv run pytest test/eplus/ -q`；新增测试局部 ruff；运行 `scripts/arch-guard.sh`；保留结果与既有失败证据，不将基线失败归因本次。
- [ ] 使用 e2e-test 技能生成与 AC 对应的现场验收；本地前端运行按用户约定跳过，真实模型/部门空间等验收未执行则明确挂起，不把替身成功作为验收完成。
- [ ] 实施结束做整体代码评审；合入 909 前读合并手册并检查更新。推送、tag 和部署按用户指示，不自动合入主版本。

## 实际偏差记录

- 2026-10-10：分支前缀存在 Git ref 冲突，改用 `feat/075-cofco-robot-debug-client-3.0.0-beta1`，不影响代码或合入方向。
- 2026-10-10：现有 uv 依赖环境缺少离线同步缓存，验证使用已有 `.venv/bin/python -m pytest`，不改依赖锁；镜像阶段校验锁定环境。
- 2026-10-10：上下文预览不初始化模型和全部工具；实际模型、执行模式及工具差异在执行的 context 事件提供。忙碌在流内 failed/HTTPException 事件结束，不把已开始 SSE 的响应再改为 HTTP429。
- 2026-10-10：Platform 尚未接入共享 UI preset/tokens，本次按已确认的“既有组件和页面布局”采用现有 Platform 控件；不为诊断页迁移全站主题或新增库。前端检查按用户明确约定不在本地执行。

## 计划自审

AC-01/04/09 → T01/T02/T05；AC-02/03/04/05/07/10 → T04；AC-05/06/07/09 → T03；AC-08 → T05/T06；页面入口、历史与展示 → T07/T08；全部真实场景 → T09。

五个 Review Focus 分别由 T01/T02、T02/T04、T03、T04、T05/T06 的测试覆盖。无数据库变更，不需要降级脚本；无 Celery/正式 Worker 任务，不新增队列。任务较大的页面接线和语言修改分小提交，不并行编辑同一文件。当前仅文档和开发分支已建立，产品代码与测试尚未编写。
