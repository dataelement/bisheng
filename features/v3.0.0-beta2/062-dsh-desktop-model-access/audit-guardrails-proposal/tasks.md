# 客户端模型调用审计任务清单

版本：1.1　日期：2026-10-14　服务端工作树：`feat/3.0.0-dsh-audit`

## 1 状态与执行边界

| 文档/交付 | 状态 | 说明 |
|---|---|---|
| spec.md 0.19 | 开发基线 | 本轮用户要求生成任务并交付客户端并行开发，按当前版拆解；不增加一期范围 |
| design.md 0.9 | 实现快照 | 已回写异步留存、共享存储、管理页面及本机双端联调；不是生产发布证明 |
| client-api-audit-extension.md 0.3 | 客户端并行开发契约 | 可以交付客户端；不是服务端能力已发布的证明 |
| tasks.md 1.1 | 开发与验证回写 | 测试合并到实际模块，未验收的环境和压力门禁保持未勾选 |
| 服务端/Platform | 功能代码及本机联调已接通 | 65/70 项完成；T063、T064、T065、T066、T068 含环境或扩展评估未执行部分，详见验证记录 |
| 桌面客户端 | C001 至 C009 完成 | C010 自动化及真实服务端代码联调通过，正式 Electron UI/Fork 等仍待操作验收 |
| 实现/隔离联调 | 本机真实存储通过 | MySQL/Redis/MinIO、客户端代码链路和实际页面通过；DM8、生产鉴权/供应商/容量门禁尚未通过 |

服务端/管理页 70 项，桌面客户端 10 项，共 80 项。每个任务最多 2 个文件，按依赖执行；Wave 是可启动层级，不要求等待同一 Wave 所有无关任务完成。基础设施先建，不在任务文档阶段提前实现代码。测试任务先提交可运行的失败用例，再完成其配对实现；禁止为了通过测试缩减审计边界。

一期只做专用模型入口的请求明细审计、租户三档模式、管理员范围查询及按需原文读取。安全围栏、敏感词、源消息 ID、气泡复刻、轮次/步骤、关系图、补报、全文检索、自动删除不实施。默认 OFF，读取模式失败本次 OFF；审计写入不阻塞/改变模型结果，不因审计失败重放模型请求。

<a id="client-work"></a>

## 2 客户端并行开发轨道

桌面客户端是外部 `bisheng-work` 仓库，不是本仓库 `src/frontend/client`。本轮独立 agent 使用 `/Users/zhangguoqing/works/bisheng-work/.worktrees/feat-3.0.0-dsh-audit`，分支 `feat/3.0.0-dsh-audit`，fetch 后最新 origin/main 基线为 `3f6f010b280e7e095a13f59d8e3faae2c6223ab2`。下文“客户端仓库/”指该工作树。旧 `.worktrees/codex-dsh-audit-poc` 只作调研参考，主检出及旧 PoC 的用户工作保持不变。

直接交给客户端：[接口契约](./client-api-audit-extension.md)。生产请求只附加服务端已公布的 `conversation_id` 与 `request_kind`，由真实 `GenerateOptions.sessionId/purpose` 取值；主进程使用可信企业连接能力快照，不相信任意模型请求自行声明服务端能力。账号身份和审计模式只由服务端决定。

| 客户端阶段 | 任务 | 前置 |
|---|---|---|
| 能力与缓存 | C001、C002、C003、C004 | 可以立即开始；mock config，不等服务端存储 |
| 两字段组装 | C005、C006 | 接通能力状态；普通/压缩/标题调用分别验证 |
| 主进程透传 | C007、C008 | 校验字段软降级，不放宽业务参数与图片/凭证校验 |
| mock 与客户端集成 | C009、C010 | C009 可立即开始；C010 在客户端链路完成后执行 |
| 真实服务端联调 | T064 | 双方候选版及隔离测试环境可用；不得用 mock 结果代替 |

责任划分：客户端开发者执行 C 任务；服务端开发者执行后端/Worker任务；管理页开发者执行 Platform任务。联调共同确认接口 C-A01 至 C-A12，记录两端提交号、能力响应、合成请求和服务端请求编号。请求不带 ID 时未关联，带有效 ID 时仅在认证租户/用户内按原值归组，服务端不验真会话。

## 3 共享接口与测试约定

### 3.1 桌面线协议

- 能力：`GET /api/v1/dsh/config`，在 enabled=true 响应增加可选 `audit_context.fields`；root 协议仍 `contract_version=0.5.0`，不增加 audit_context.version。
- 请求：`POST /api/v1/dsh/chat/completions`；顶层附加 audit_context，在严格校验模型 DTO 前分离，绝不发给模型。
- ID：非空字符串、最多 256 Unicode 码点、精确原值；kind：`chat`、`compaction`、`session-title`。扩展规范化紧凑 JSON UTF-8 最多 4096 字节。无效只忽略对应字段，整个非对象/超限扩展忽略；无字段时省略整个对象。
- 模型认证、请求主体、SSE、取消、工具与图片语义不改变。有效请求只生成一个 request_id，业务用量、审计和响应编号复用；不新增审计 ACK，不保证审计即时可查。
- 请求归组 `(authenticated_tenant_id, authenticated_user_id, conversation_id)`；没有 ID 的正文复用作用域是 `REQUEST + request_id`，有 ID 是 `CONVERSATION + conversation_id`，两者不得同值碰撞。

### 3.2 管理接口实现接口

`/api/v1/dsh/admin/model-audit` 下的 requests/list/detail、conversations、settings 与 body-access 按 [design §6.2](./design.md#62-管理-api-与正文访问) 实现。T004 产出统一 DTO 供前后端 fixture/类型镜像，普通管理响应沿用 `resp_200`，列表 data 含 `items`、`next_cursor` 和非正文 `progress`；不为 keyset 页伪造精确总数。请求列表按开始时间/编号稳定排序，会话时间线同序，cursor 与过滤/目标租户绑定。

内部可替换组件接口在各任务中列明；相邻任务修改同一文件均是增量接线，不推翻已完成前驱。统一构建根负责注入仓储/存储/队列与时钟；Domain 不直接建客户端。平台普通 HTTP 走现有 request 包装，增量正文由共享 requestStream 扩展统一认证/错误策略，不在业务组件加 403 分支。

正文读取成功采用 NDJSON：`meta`（request_id、encoding_version、content_state）、`part`（全局递增 seq、channel、unit_index、fragment）、`end`（最后 seq、content_state、传输结果）。part.fragment 是同一有序原件单元的连续序列化文本片段，不是 LLM 摘要；增量组装当前单元后按角色展示消息，同请求流式输出合并，不逐存储分片展示 JSON，不修改底层原文。20Mi字符展示预算内缓存已解析消息及当前单元，不等整份正文才展示。channel 区分 input/output，unit_index 按原件记录顺序取值；无正文时 meta+end 明确未采集，未完整留存则部分。开始传输前失败用标准管理错误；开始后失败用不含正文的 error 事件并结束，缺 end 只能判传输未完成，不篡改服务器原件状态。每次 POST 先持久授权查看日志，禁止原件直链、列表预览、跨卡片预取。详细线格式归 design，前端测试使用同一 fixture。

### 3.3 测试环境与命令

后端假模型/可控 drain 验证确定性逻辑，SQLite 不证明双库兼容；真实 MySQL/DM8/Redis/MinIO 在隔离中央测试环境或 CI 执行。无环境须标未执行，不标完成。新工作树缺忽略的 config.yaml 时复用主工作树测试配置，不改真实生产配置，不输出凭证。

- 后端：从 `src/backend` 执行 `uv run pytest test/dsh/ -m "not e2e"`，新测试用 asyncio_mode=auto。
- Platform：从 `src/frontend/platform` 执行 `pnpm test`；从 `src/frontend` 执行 `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`。新增中文文案三语齐备，现有冻结违规只减不增。
- Desktop：在客户端工作树按既有 npm 脚本运行定向 Vitest 与 `npm run typecheck`；PoC 的 node 测试另行执行，不能代表完整应用验证。
- 所有实际 UI 实施前重读当前 UI spec/已落地组件；复用现有客户端管理表单、列表和组件，不自行更改设计规范/视觉体系。不恢复旧 operations 页签。
- 每项完成后执行 /task-review；最终 /e2e-test、架构守卫与实现代码评审必须执行，记录证据。本文生成阶段未运行这些实现测试。
- 共享改动（模型入口、request wrapper、运行关闭与 Worker注册）回归已有 F062 登录、用量、席位和操作审计。修改超出既定范围时重新确认偏差，不顺手改其他功能。

## 4 按依赖分批的任务

### Wave 0 基础设施与可独立启动的客户端任务

#### C001 字段能力和软解析测试

- [x] C001（客户端测试）
- 文件：`客户端仓库/test/enterprise-audit-context.test.ts`；`客户端仓库/test/enterprise-contract.test.ts`
- 依赖：无
- 工作与上下文：mock config 正常/缺扩展/字段子集/未知字段/坏可选能力，边界 256/257 码点与 4096/4097 字节；known-fields 交集，非对象附加字段省略，两个字段独立；根 config 错误保持既有身份语义。
- 覆盖 AC: AC-22, AC-34
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### C009 可切换能力的 mock 服务

- [x] C009（客户端 Desktop）
- 文件：`客户端仓库/scripts/mock-bisheng-enterprise.mjs`；`客户端仓库/scripts/mock-bisheng-enterprise.d.mts`
- 依赖：无
- 工作与上下文：为现有 mock 增加 config 两字段/仅会话/无能力/坏可选能力模式，记录净化后收到的两字段和请求次数，保留 SSE/工具/图片/错误及取消场景；不伪装成真实毕昇已持久化审计。
- 完成标准：客户端可独立用 mock 连通 C002–C008，模型请求计数证明无自动重放。

#### T001 租户模式与变更模型

- [x] T001（基础设施）
- 文件：`src/backend/bisheng/dsh/domain/models/model_audit_setting.py`；`src/backend/bisheng/core/database/tenant_filter.py`
- 依赖：无
- 工作与上下文：定义 dsh_model_audit_setting（tenant_id 唯一，mode/version/updated_by/at）和 setting_change（operation_id/actor/before/after/time）；OFF 为未配置默认，切换与留痕同事务。使用 SQLModel table=True 和双库兼容类型。新表由既有 model_discovery/create_all 发现，不向旧租户回填模式；回退应用时保留表和历史数据。
- 完成标准：类型/模型可加载，双库兼容约束和既有配置不受破坏；记录本任务验证。

#### T002 请求、证据与完整性清单模型

- [x] T002（基础设施）
- 文件：`src/backend/bisheng/dsh/domain/models/model_audit_request.py`
- 依赖：无
- 工作与上下文：定义 request、evidence、manifest 三张表；request 保存认证身份、模型展示快照、conversation_id/key、四轴状态及来源时间、状态版本；evidence 唯一(request_id,event_type)，MODE_READ_FAILED 不含用户/会话/模型正文；manifest 保存 input_complete/capture_failed、固定通道计数/末序号/校验和模型终止事实。新表发现与回退规则同 T001。
- 完成标准：类型/模型可加载，双库兼容约束和既有配置不受破坏；记录本任务验证。

#### T003 正文、出现与查看日志模型

- [x] T003（基础设施）
- 文件：`src/backend/bisheng/dsh/domain/models/model_audit_content.py`
- 依赖：无
- 工作与上下文：定义 content、occurrence、body_access；content 必含 tenant/user/scope_type/scope_id/编码与密钥版本/object_key/长度/摘要/写入状态，scope_type 为 CONVERSATION 或 REQUEST；occurrence 唯一(request_id,stage,channel,sequence)；查看日志保存 actor/target/time/result/trace。SQL 无输入输出文本列；新增表回退保留原件引用与密钥。
- 完成标准：类型/模型可加载，双库兼容约束和既有配置不受破坏；记录本任务验证。

#### T004 内部 DTO 与有界运行配置

- [x] T004（基础设施）
- 文件：`src/backend/bisheng/dsh/domain/schemas/model_audit.py`；`src/backend/bisheng/core/config/dsh.py`
- 依赖：无
- 工作与上下文：定义管理元数据/分页/四轴状态/模式命令 DTO（不含正文），模式写入含 operation_id 与 expected_version；DshSettings 添加审计分块、单请求/全局队列预算、配置读取/存储超时、有限重试、刷新/观察窗口及密钥引用参数。默认租户模式仍由 SQL 决定，密钥缺失只使 CONTENT 留存失败；不增加旧 YAML 不识别的新顶层键。运维默认值可调，不宣称 D-09 SLA。
- 完成标准：类型/模型可加载，双库兼容约束和既有配置不受破坏；记录本任务验证。

### Wave 1 前驱完成后可启动

#### C002 能力解析与共享组装规则

- [x] C002（客户端 Desktop）
- 文件：`客户端仓库/packages/dsh-desktop-enterprise/contract.js`；`客户端仓库/packages/dsh-desktop-enterprise/contract.d.ts`
- 依赖：C001
- 工作与上下文：parseConfig 保留校验后的 audit_context.fields（仅 conversation_id/request_kind），新增 normalizeAuditContext(raw,allowedFields) 供插件及主进程复用；不加 version，不因坏可选能力让有效根 config 失败。无有效字段省略，维持 0.5.0 原有解析。
- 完成标准：C001 通过。

#### T005 确定性测试设施

- [x] T005（基础设施）
- 文件：`src/backend/test/dsh/model_audit_fixtures.py`
- 依赖：T001、T002、T003、T004
- 工作与上下文：复用既有 test_model_service 的受控异步模型；提供时钟、手动 drain/drop 队列、假对象存储与活动状态；SQLite 隔离仓储注册租户 SELECT hook，恢复测试前监听器与表集合，显式 BEGIN 保证 savepoint 的原子回滚。末片/清单丢失通过删事件注入，冲突及故障通过仓储/假存储注入；外部环境仍受 conftest 的 dsh_test_ 限制，仅用合成内容。
- 完成标准：类型/模型可加载，双库兼容约束和既有配置不受破坏；记录本任务验证。

#### T052 Platform API/流式正文解析测试

- [x] T052（前端测试）
- 文件：`src/frontend/platform/src/controllers/API/dshModelAudit.test.ts`
- 依赖：T004
- 工作与上下文：mock 现有 request wrapper 验证路径/过滤/游标/AbortSignal、四轴未知值安全显示、列表 DTO 无正文；body-access 只对点开的 request_id 读取，处理 NDJSON 半包/合包/终止与错误并保持片段序号，不自动取其他请求。
- 覆盖 AC: AC-18, AC-21, AC-24, AC-33
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T069 共享流式传输认证与错误回归测试

- [x] T069（前端测试）
- 文件：`src/frontend/platform/src/controllers/requestStream.test.ts`
- 依赖：T004
- 工作与上下文：用 mock fetch/ReadableStream 校验 BASE、ws_token、cookie、AbortSignal、非 2xx/业务 envelope、会话失效/踢出/权限拒绝和取消；与现有 request wrapper 的相同行为对照。HTTP 发出前拒绝或日志失败不得开始原文渲染；半包/合包保持增量读取，不整段缓存正文。测试仅使用合成正文。
- 覆盖 AC: AC-18, AC-19, AC-26, AC-33
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

### Wave 2 前驱完成后可启动

#### C003 连接能力快照与失效测试

- [x] C003（客户端测试）
- 文件：`客户端仓库/test/enterprise-service.test.ts`；`客户端仓库/test/enterprise-contract-import.test.ts`
- 依赖：C002
- 工作与上下文：mock 现有 config fetch 与账号状态流，验证 BASE/账号切换、重新连接、重启不复用旧能力，刷新故障只清除可选扩展；主进程请求净化使用自身连接快照，不信任插件自报支持能力。
- 覆盖 AC: AC-22, AC-34
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### C005 sessionId/purpose 最终请求测试

- [x] C005（客户端测试）
- 文件：`客户端仓库/test/enterprise-openai-adapter.test.mjs`
- 依赖：C002
- 工作与上下文：真实序列化路径断言两字段：现有 Session ID、chat/compaction/session-title/未知 purpose、ID 缺失、字段子集；messages/tools/images 字节形态不因扩展改变。移除旧 PoC version/message_sources 的生产上报期望；维持局部序列化测试，不要求 source ID。
- 覆盖 AC: AC-01, AC-02, AC-03, AC-05, AC-07, AC-08, AC-10, AC-14, AC-22, AC-28, AC-34
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### C007 Electron 透传和恶意字段边界测试

- [x] C007（客户端测试）
- 文件：`客户端仓库/test/enterprise-chat.test.ts`；`客户端仓库/test/enterprise-chat-proxy.test.ts`
- 依赖：C002
- 工作与上下文：parseEnterpriseChatPayload(value,trustedAuditFields) 的附加字段净化测试：缺能力剥离、非法附加字段不拒绝合法模型、未知值不透传；原有未知模型业务键、凭证/header/图片限制仍拒绝，取消/错误编号保持。
- 覆盖 AC: AC-22, AC-23, AC-26, AC-34, AC-36
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T006 两字段解析与能力 DTO 测试

- [x] T006（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_contract.py`；`src/backend/test/dsh/contracts/model_audit_extension.json`
- 依赖：T004、T005
- 工作与上下文：以客户端接口文档 0.3 为样本，断言 256/257 Unicode 码点、4096/4097 UTF-8 字节、非对象、未知字段、request_kind 三种值/未知值、字段子集；非法附加字段被忽略，合法 conversation_id 与 request_kind 独立，业务字段仍严格校验。
- 覆盖 AC: AC-03, AC-22, AC-26, AC-34
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T012 租户模式与管理员范围测试

- [x] T012（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_setting.py`
- 依赖：T005
- 工作与上下文：默认无行 OFF，超管版本保护切换+日志原子；租户管理员只能读本租户，不能切换；配置读取超时按 OFF，不沿用缓存/改租户值；在途模式快照不变。
- 覆盖 AC: AC-18, AC-22, AC-29, AC-31
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T024 四轴状态与缺口判定测试

- [x] T024（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_runtime.py`；`src/backend/test/dsh/test_model_audit_flow.py`
- 依赖：T005
- 工作与上下文：独立测试模型成功+响应失败/结算未确认，失败/取消内容仍完整，模式未知、仅业务候选、独立进入证据、活动有效/失联、终态后正文缺片、迟到事实恢复及过期检查不能盖终态。
- 覆盖 AC: AC-09, AC-13, AC-15, AC-16, AC-24, AC-30, AC-31, AC-37, AC-38
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T032 活动租约与迟到刷新测试

- [x] T032（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_activity.py`
- 依赖：T005
- 工作与上下文：假 Redis/时钟验证 wait-first-token/空输出仍刷新、正常结束停止、代次/结束标记挡迟到续租、跨进程可查、容量/超时失败不影响模型；OFF 不登记，活动过期不证明失败。
- 覆盖 AC: AC-17, AC-22, AC-24, AC-27, AC-37
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T034 独立证据和最小诊断测试

- [x] T034（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_runtime.py`；`src/backend/test/dsh/test_model_audit_capture.py`
- 依赖：T005
- 工作与上下文：进入证据仅开启模式产生；MODE_READ_FAILED 仅 request_id/tenant/time/reason，拒绝 user/session/model/conversation/正文；独立队列和 SQL 故障均不阻断模型，共因丢失不伪称逐条覆盖。
- 覆盖 AC: AC-17, AC-22, AC-24, AC-28, AC-30, AC-31
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T070 共享请求层的有界流式扩展

- [x] T070（前端 Platform）
- 文件：`src/frontend/platform/src/controllers/request.ts`；`src/frontend/platform/src/controllers/requestStream.ts`
- 依赖：T069
- 工作与上下文：现有 Axios 浏览器封装未提供 ReadableStream，不能仅设置 responseType=stream。增加共享 requestStream 包装：fetch 增量读流，复用 request.ts 的 BASE/认证及集中错误处理（提取公共策略而非复制业务侧 403 分支）；POST 携带认证、credentials 与 AbortSignal，错误 envelope 仍走共享层，不把原文写 console。保持旧 Axios 调用语义；清理触碰到的中文注释/调试文案，既有错误码文案仍用共享 locales，不增补生成文件。
- 完成标准：T069 及原 request 拦截器回归通过。

### Wave 3 前驱完成后可启动

#### C004 连接状态到插件的能力桥

- [x] C004（客户端 Desktop）
- 文件：`客户端仓库/src/main/enterprise/enterprise-service.ts`；`客户端仓库/src/main/enterprise/enterprise-desktop.ts`
- 依赖：C003
- 工作与上下文：把 config 能力保存在当前 BASE 进程快照，并通过现有公开账号/provider 状态流传给插件；清除和重新获取时机按接口 §2.3。chat 调 parseEnterpriseChatPayload 时传入当前可信 fields；不暴露 access token/审计租户模式，不每请求抓 config。
- 完成标准：C003 通过。

#### T007 审计关联软解析与能力 DTO

- [x] T007（后端 Domain）
- 文件：`src/backend/bisheng/dsh/domain/schemas/model_audit_context.py`；`src/backend/bisheng/dsh/domain/schemas/contracts.py`
- 依赖：T006
- 工作与上下文：实现 parse_audit_context(raw,advertised_fields) 返回有效字段及缺失/无效诊断，不返回原始无效值；只支持 conversation_id 与 chat/compaction/session-title。DshEnabledConfig 可选 audit_context.fields，无独立 version，保持 0.5.0 基础契约；未知/无效扩展不转交业务 DTO。
- 完成标准：T006 通过。

#### T013 租户模式仓储与服务

- [x] T013（后端 Domain）
- 文件：`src/backend/bisheng/dsh/domain/repositories/model_audit_setting.py`；`src/backend/bisheng/dsh/domain/services/model_audit_setting.py`
- 依赖：T012
- 工作与上下文：仓储 read_mode/change_mode 内封装 SQL；服务 snapshot_mode(tenant,request_id) 在有界读取后固定模式，失败回 OFF 与最小降级诊断。管理读/写复用现有管理员身份与受限租户范围，切换只允许全局超管；模式变更与不可变日志同事务，不做新 F048 资源。
- 完成标准：T012 通过。

#### T025 统一状态/缺口判定器

- [x] T025（后端 Domain）
- 文件：`src/backend/bisheng/dsh/domain/services/model_audit_states.py`
- 依赖：T024、T004
- 工作与上下文：derive_audit_states 接收固定模式、模型/响应事实、真实用量状态、完整性核验、活动租约和时钟；OFF/METADATA 不误报正文缺口，模式未知只标适用性待核实，独立 entered 才证明进入。未知不填零或补造失败；状态 CAS 保护，已完整原件不因响应失联降级。
- 完成标准：T024 通过。

#### T053 类型与 API 层

- [x] T053（前端 Platform）
- 文件：`src/frontend/platform/src/types/dshModelAudit.ts`；`src/frontend/platform/src/controllers/API/dshModelAudit.ts`
- 依赖：T052、T070
- 工作与上下文：定义元数据、游标、模式/版本命令、NDJSON 正文事件类型；普通请求走 @/controllers/request.ts，正文走 T070 的 @/controllers/requestStream.ts，共用认证/错误策略，不能直接 import axios 或让 store 发 HTTP。参数/响应与 T004/T049 对齐。
- 完成标准：T052 通过。

### Wave 4 前驱完成后可启动

#### C006 企业适配器附加关联信息

- [x] C006（客户端 Desktop）
- 文件：`客户端仓库/packages/dsh-desktop-enterprise/openai.js`；`客户端仓库/packages/dsh-desktop-enterprise/index.js`
- 依赖：C004、C005
- 工作与上下文：注册 auditContext 回调读取当前能力快照，EnterpriseLlmAdapter.stream 取真实 options.sessionId/purpose，正常已确认生成→chat，compaction/session-title 原值映射，未知省略。只对毕昇企业请求附加两个字段，删除本期不需要的消息来源上报依赖；不响应后补报、不新增模型重试。
- 完成标准：C005 通过；现有企业 adapter 测试回归。

#### T008 能力入口和业务 JSON 分离测试

- [x] T008（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_contract_api.py`
- 依赖：T007
- 工作与上下文：通过真实 DshRoute + fake runtime 验证 config 裸 JSON 与字段能力；旧请求、字段子集和坏附加字段只调用一次模型；非法 JSON/模型业务参数仍返回既有 invalid_request；附加字段不进入适配器。
- 覆盖 AC: AC-22, AC-23, AC-26, AC-34
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T010 单请求编号贯通测试

- [x] T010（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_request_id.py`
- 依赖：T007、T005
- 工作与上下文：构造上游异常、模型成功但结算异常、调用前拒绝、正常 JSON/SSE；断言错误体 request_id 与完成 id 的 chatcmpl-后缀、用量事件及可用审计编号同源；前置拒绝无模型已调用审计。
- 覆盖 AC: AC-15, AC-23, AC-36
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T014 规范化编码、作用域与清单测试

- [x] T014（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_codec.py`
- 依赖：T005、T007
- 工作与上下文：对照真实统一有效值，验证角色/顺序/工具/图片或引用；稳定消息单元复用，CONVERSATION:X 与 REQUEST:X 不碰撞，ID 大小写精确；入队前计数、空输出、最后片/清单丢失及 capture_failed 禁止完整。
- 覆盖 AC: AC-04, AC-06, AC-07, AC-08, AC-10, AC-12, AC-14, AC-25, AC-26, AC-38
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T035 证据旁路写入

- [x] T035（Worker）
- 文件：`src/backend/bisheng/dsh/domain/repositories/model_audit_write.py`；`src/backend/bisheng/dsh/audit_runtime.py`
- 依赖：T034、T013
- 工作与上下文：独立有界队列/消费者按唯一键尽力写 entered 或降级诊断，有限重试与失败指标；每批使用事件内可信 tenant_id 建 ContextVar，无正文或客户端身份覆盖。配置 OFF 不启动进入事件写入，模式读取故障的系统诊断仍可尽力落库。
- 完成标准：T034 通过。

#### T054 列表/时间线与按需正文组件测试

- [x] T054（前端测试）
- 文件：`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditPanel.test.tsx`；`src/frontend/platform/src/controllers/API/dshModelAudit.test.ts`
- 依赖：T053
- 工作与上下文：mock 子组件及 API；覆盖两轮只有两卡片、重复历史不铺开、长会话分页、默认无原文、单卡片点击才 POST body-access、切租户清空原文、租户管理员不能改模式、四轴与缺口提示独立。
- 覆盖 AC: AC-18, AC-19, AC-21, AC-24, AC-29, AC-32, AC-33
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

### Wave 5 前驱完成后可启动

#### C008 主进程净化与类型补齐

- [x] C008（客户端 Desktop）
- 文件：`客户端仓库/src/main/enterprise/enterprise-chat.ts`；`客户端仓库/packages/dsh-desktop-enterprise/index.d.ts`
- 依赖：C004、C006、C007
- 工作与上下文：白名单显式加入 audit_context，用 C002 共享规则和主进程可信能力过滤后发送；坏扩展逐字段忽略，不放宽其他业务键和图片限制。给公开非敏感连接能力及适配器回调补类型，鉴权仍由已有主进程凭证机制注入。
- 完成标准：C007 通过；主进程 chat/typecheck 回归。

#### T009 公开能力及模型入口软解析

- [x] T009（后端 API）
- 文件：`src/backend/bisheng/dsh/api/endpoints/identity.py`；`src/backend/bisheng/dsh/api/endpoints/models.py`
- 依赖：T008
- 工作与上下文：enabled config 公布已实施的两字段，关闭部署保持旧响应；Chat Completions 读取一次 JSON，先分离 audit_context 再严格 DshChatRequest.model_validate，并保持现有错误映射和 DSH 认证。模型路由把 request.state.request_id 与解析结果交给服务，逐请求不探测/重放。
- 完成标准：T008 通过；主客户端旧版 config/模型契约测试通过。

#### T015 版本化分块编码与事件清单

- [x] T015（后端 Domain）
- 文件：`src/backend/bisheng/dsh/infrastructure/model_audit_codec.py`；`src/backend/bisheng/dsh/domain/schemas/model_audit_events.py`
- 依赖：T014
- 工作与上下文：定义 entered/input/output/terminal 事件与固定通道清单；分块前后保留统一接口实际值。作用域编码含 tenant/user/scope_type/scope_id/version，conversation_key 使用稳定 SHA-256 后再精确核对原值；计数、末序号和增量摘要在入队尝试前更新，编码/投递失败置 capture_failed。不额外复制完整正文。
- 完成标准：T014 通过。

#### T055 审计列表容器与查询 hook

- [x] T055（前端 Platform）
- 文件：`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditPanel.tsx`；`src/frontend/platform/src/pages/SystemPage/dsh/useModelAudit.ts`
- 依赖：T054
- 工作与上下文：实现请求筛选状态、稳定分页和详情定位、当前模式/写入进度/积压/缺口说明；只读元数据，切租户/筛选取消旧请求清空原文。遵循当前 UI SSOT、bs-ui 和既有 dsh 页面模式，不新增状态/数据请求库。
- 完成标准：手动：/dsh?tab=model-audit 查询空/多页/未知模式，Network 无 body-access；对应 T054 列表用例通过。

#### T057 有界正文解析与展开组件

- [x] T057（前端 Platform）
- 文件：`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditBody.tsx`；`src/frontend/platform/src/controllers/API/dshModelAudit.ts`
- 依赖：T054、T053
- 工作与上下文：按 tasks 头的 NDJSON 契约增量解析，输入/输出保序，长原件分段渲染且仍可完整查看；不执行模型 HTML/脚本，不自动加载外部引用目标，不预取其他请求。收起/切页取消当前浏览读取并清理不再展示的原文状态，原件不被修改。
- 2026-10-15 展示修正（AC-10、AC-12、AC-14、AC-19、AC-21）：补 `auditMessages` 按单元组装与 `ModelAuditMessage` 内容阅读；首条参数单元仅保留在底层原件，思考默认折叠，流式文本/工具调用合并；每页100条消息、单条16000字符分段，缺口/未知/读取中断不冒充完整记录；补真实 NDJSON 解析到 UI 的合成数据回归，不使用109业务凭证。
- 完成标准：T054 正文用例通过；手动断流/部分/未采集，不把流中断显示完整。

#### T058 租户模式控件

- 补充 AC-39：读取/保存返回本实例密钥可用性；缺合法活动密钥时禁用正文采集并提示，后端拒绝新 CONTENT 变更且不落模式或变更历史；OFF/METADATA 不受影响。已配置后密钥失效则保留模式并在打开/刷新时告警，模型主流程继续；覆盖保存时重校验、恢复后重试、幂等重放、旧响应状态未知和三语错误码。
- [x] T058（前端 Platform）
- 文件：`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditMode.tsx`
- 依赖：T054、T053
- 工作与上下文：OFF/METADATA/CONTENT 当前值对两类管理员可见，只有全局超管可切换所选租户；生成 operation_id 并携 expected_version，成功后刷新模式；冲突/日志写失败显示既有错误并重新读取实际值。CONTENT 提示持续留存运营风险，保持已有样式。
- 完成标准：手动：超管切换、租户管理员只读、并发冲突，失败不伪显示已成功。

### Wave 6 前驱完成后可启动

#### C010 客户端集成、续接与交付证据

- [ ] C010（客户端测试）
- 文件：`客户端仓库/test/enterprise-audit-integration.test.ts`；`客户端仓库/docs/dsh-model-audit-validation.md`
- 依赖：C008、C009
- 工作与上下文：贯穿 config→状态→插件→适配器→主进程→mock；实测持久 Session 跨重启/登录续接、普通/标题/压缩/Fork、字段子集、无 ID、切 BASE、取消和失败编号。记录哪些是局部/mock证据；真实毕昇归组和持久化由 T064 联调验证，不在本任务伪称通过。
- 覆盖 AC: AC-01, AC-02, AC-03, AC-05, AC-07, AC-08, AC-22, AC-28, AC-34, AC-36
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T011 请求编号只生成一次

- [x] T011（后端 API）
- 文件：`src/backend/bisheng/dsh/api/responses.py`；`src/backend/bisheng/dsh/domain/services/model.py`
- 依赖：T009、T010
- 工作与上下文：DshRoute 在请求入口设置 request.state.request_id，error 接收同一编号；complete 接收路由传入编号，直接内部调用可显式给编号或采用单次缺省生成，API 链不二次生成。UsageEvent 与 SSE/JSON 均沿用；错误分支不依赖退出后已复位的日志 trace。
- 完成标准：T010 通过；既有模型错误和刷新语义回归通过。

#### T016 加密原件与跨节点读取测试

- [x] T016（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_storage.py`
- 依赖：T015、T005
- 工作与上下文：假 MinIO/密钥来源验证 AEAD、作用域绑定、编码版本、原件校验、有界读取与写超时；密钥/存储失败不写明文、不返回预签名直链，不靠本地文件。
- 覆盖 AC: AC-06, AC-10, AC-14, AC-17, AC-20, AC-26
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T018 SQL 事实幂等与隔离测试

- [x] T018（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_writer.py`；`src/backend/test/dsh/test_sql_portability.py`
- 依赖：T005、T015
- 工作与上下文：真实隔离 SQLite 仓储测试 request/occurrence/manifest/content 引用、幂等重投、相同键不同载荷冲突、跨用户/跨会话/无会话引用隔离，版本保护不让晚到 RUNNING 覆盖终态；加入双库 SQL 构造检查。
- 覆盖 AC: AC-04, AC-05, AC-06, AC-08, AC-09, AC-20, AC-21, AC-38
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T020 有界采集及 OFF 行为测试

- [x] T020（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_capture.py`
- 依赖：T005、T015
- 工作与上下文：注入队列满、编码异常、大正文预算耗尽，断言主流程仍输出一次、不阻塞远程存储；OFF 无 entered/活动/请求正文，降级 OFF 仅最小诊断；METADATA 无消息/图片/增量，CONTENT 丢片不能完整。
- 覆盖 AC: AC-09, AC-11, AC-12, AC-17, AC-22, AC-27, AC-28, AC-31, AC-38
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T056 筛选与简洁会话时间线

- 补充 AC-21：超管默认选中经目录确认的默认租户（编号 1），不跟随个人归属或列表顺序；租户管理员直接加载当前身份管理的租户，兼容身份信息延迟加载。覆盖默认选择、空身份恢复、目录缺失/失败、手动切换与原文清理。
- [x] T056（前端 Platform）
- 文件：`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditPanel.tsx`
- 依赖：T054、T055
- 工作与上下文：模型候选只读当前租户开放目录；选择后按 model_id，手填按完整历史名称摘要+原值等值查询，二者互斥；审计大表不做名称模糊匹配、候选去重或全量计数。常用筛选仅显示当前租户用户下拉、时间、模型名称；用户按需搜索与分页，不手填编号或用户名。请求/会话编号、提供方、四轴和关联状态默认收进高级筛选，标明生效条件数量并可重置；切租户清空用户、条件、分页和原文。会话采用认证用户+原始会话 ID，每个请求一张折叠卡片，展示非正文统计/调用种类/四轴。默认不显示输出预览，不标推断的新气泡；选择项过滤空 ID。用户选择接口沿用审计鉴权，只返回所选租户的用户编号与名称，不放宽租户管理接口权限。
- 完成标准：手动：R1/R2 两卡片、20+请求分页；相同正文不增加气泡，缺种类显示未知。

### Wave 7 前驱完成后可启动

#### T017 共享对象原件与密钥适配

- [x] T017（后端 Domain）
- 文件：`src/backend/bisheng/dsh/infrastructure/model_audit_storage.py`；`src/backend/bisheng/dsh/infrastructure/model_audit_keys.py`
- 依赖：T016
- 工作与上下文：实现 put_verified_block/open_verified_blocks，复用共享 MinIO 与已有加密依赖；AEAD 关联数据含带类型作用域，密钥引用/版本独立于 License/HMAC。用有限超时与有限重试，失败显式回报留存结果，浏览器经服务读取；本地盘仅可作可丢缓存，原件真相在 MinIO。
- 完成标准：T016 通过。

#### T019 写入仓储

- [x] T019（后端 Domain）
- 文件：`src/backend/bisheng/dsh/domain/repositories/model_audit_write.py`
- 依赖：T018
- 工作与上下文：提供 upsert_request/append_occurrence/save_manifest/link_verified_content/compare_and_set_states；SQL 事务中保留每次出现及唯一键摘要，不覆盖冲突原件；对象核验后才建已就绪引用，tenant ContextVar 自动过滤，SQL 不含正文。
- 完成标准：T018 通过。

#### T021 AuditCapture 有界观察器

- [x] T021（后端 Domain）
- 文件：`src/backend/bisheng/dsh/domain/services/model_audit_capture.py`
- 依赖：T020
- 工作与上下文：实现请求固定模式的 Noop/Metadata/Content capture；entered/input/output/terminal 只做有界本地工作及非阻断投递。维护入队前预期清单、失败标志、模型结果来源；非关键故障明确记录计数并继续模型，不吞/重放响应，不生成替代摘要。
- 完成标准：T020 通过。

#### T059 新增客户端管理模型审计入口

- [x] T059（前端 Platform）
- 文件：`src/frontend/platform/src/pages/DshPage/sections.ts`；`src/frontend/platform/src/pages/SystemPage/dsh/index.tsx`
- 依赖：T055、T056、T057、T058
- 工作与上下文：新增 model-audit section 并挂 ModelAuditPanel，沿现有管理角色入口与启用状态展示；旧 operations 审计仍隐藏。只增量接入，菜单不替代后台授权；保持 license/models/usage/access/plugins 导航及历史页签回退。
- 完成标准：手动：访问 /dsh?tab=model-audit；现有管理页签及旧隐藏 operations 行为不变。

### Wave 8 前驱完成后可启动

#### T022 后台写入及 COMPLETE 判定测试

- [x] T022（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_writer.py`
- 依赖：T019、T017、T021
- 工作与上下文：确定性 drain 顺序/乱序/重复事件；先模型首字后 SQL 行、PENDING 可见、空输出及失败/取消完整留存、末片/清单丢失、MinIO/SQL 故障和有限重试；完整必须清单与所有引用核对，不依赖业务成功。
- 覆盖 AC: AC-09, AC-10, AC-11, AC-12, AC-13, AC-17, AC-20, AC-24, AC-25, AC-35, AC-38
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T026 统一接口适配观察点测试

- [x] T026（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_flow.py`；`src/backend/test/dsh/test_model_audit_capture.py`
- 依赖：T015、T021
- 工作与上下文：使用受控 llm 与真实 DshChatAdapter/ChatExecution 核对适配后有效消息、默认工具选择、参数、多模态引用、reasoning 与统一返回增量；确认 audit_context/凭证剥离，stream 未迭代无 entered。
- 覆盖 AC: AC-10, AC-12, AC-14, AC-23, AC-25, AC-26
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T033 活动集合与后台刷新器

- [x] T033（Worker）
- 文件：`src/backend/bisheng/dsh/infrastructure/model_audit_activity.py`
- 依赖：T032、T021
- 工作与上下文：提供 register_active/finish/read_activity 和 API 进程后台批量刷新；固定容量/超时/代次，Redis 为共享证据，本地集合可丢；开始/终止的租户取认证快照，每次数据库/Redis 分区操作显式恢复对应 ContextVar，不等待模型路径远程 ACK。
- 完成标准：T032 通过。

#### T044 请求查询、归组与缺口展示测试

- [x] T044（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_flow.py`
- 依赖：T019、T025、T035
- 工作与上下文：组合时间/用户名/提供方/模型/四轴/关联过滤、request_id 定位及三元组稳定分页；误复用 ID 按声明合组、换 ID 分组、无 ID 未关联；无正文默认响应。合并业务候选/进入证据/活动不谎称未调用，管理员历史记录按记录 tenant 授权。
- 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-11, AC-15, AC-16, AC-18, AC-21, AC-24, AC-32, AC-33, AC-34
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T060 审计文案中文与英文

- [x] T060（前端 Platform）
- 文件：`src/frontend/platform/public/locales/zh-Hans/bs.json`；`src/frontend/platform/public/locales/en-US/bs.json`
- 依赖：T059
- 工作与上下文：添加 dsh.modelAudit.* 文案覆盖模式、四轴、未关联、部分、未知适用性、进度及原文查看；中文用业务词，不在标签塞内部表名/缩写。保留既有 key，无 API 错误文案重复。
- 完成标准：新组件全部 t()；与 T061 同一交付波次，交付前键集合一致。

### Wave 9 前驱完成后可启动

#### T023 异步写入器与完整性核验

- [x] T023（后端 Domain）
- 文件：`src/backend/bisheng/dsh/domain/services/model_audit_writer.py`；`src/backend/bisheng/dsh/domain/services/model_audit_integrity.py`
- 依赖：T022
- 工作与上下文：write(event) 组合 T019/T017，先核验原件再提交引用；按清单核对连续序号、数量、顺序摘要、input_complete/capture_failed 与模型终止证据。已有行未完成为 PENDING，超窗判定交给状态器；有限重试耗尽报告部分/未采集，队列不无限积压。
- 完成标准：T022 通过。

#### T027 适配器/统一返回观察接入

- [x] T027（后端 Domain）
- 文件：`src/backend/bisheng/dsh/infrastructure/chat_adapter.py`
- 依赖：T026
- 工作与上下文：prepare 暴露业务值与已绑定工具快照；invoke/stream 真正调用时 entered，统一结果/增量产出时观察，正常/异常/可核验取消时终止；观察器异常隔离。保持当前工具解析、能力校验、usage 和供应商调用次数。
- 完成标准：T026 通过。

#### T040 租户状态扫描与失联恢复测试

- [x] T040（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_worker.py`；`src/backend/test/dsh/test_model_audit_runtime.py`
- 依赖：T025、T033、T019
- 工作与上下文：参数 tenant_id 与 Celery header 不一致拒绝；按租户恢复 ContextVar、分页扫描和 CAS；当前模式已 OFF 的历史 PENDING 仍收敛，活动有效长流不误报，失联未知、迟到事实及已完整内容保持。
- 覆盖 AC: AC-09, AC-13, AC-24, AC-29, AC-37, AC-38
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T045 管理查询仓储与服务

- [x] T045（后端 Domain）
- 文件：`src/backend/bisheng/dsh/domain/repositories/model_audit_queries.py`；`src/backend/bisheng/dsh/domain/services/model_audit_queries.py`
- 依赖：T044
- 工作与上下文：list_requests/get_request/list_conversation 返回任务头约定元数据 DTO 和稳定游标、模式/水位/积压说明；先现有 authorize_admin 限定所选租户，再恢复 ContextVar，用户模糊匹配仅本范围。按 request_id 引用既有用量与独立证据，当前模式不倒推历史；不按消息文本识别来源或输出正文预览。
- 完成标准：T044 通过。

#### T061 日文文案与语言完整性

- [x] T061（前端 Platform）
- 文件：`src/frontend/platform/public/locales/ja/bs.json`
- 依赖：T060
- 工作与上下文：补齐 T060 同一 key 集合日文；执行三语言 parity 与前端质量门禁。新组件无硬编码中文、新文件无 @ts-strict-ignore；若触及冻结中文或 lint 违规按 i18n-localizer/现有 prune 规则处理。
- 完成标准：pnpm check-i18n、pnpm lint、pnpm typecheck 通过；三语手动核对状态和动作。

### Wave 10 前驱完成后可启动

#### T028 模型主流程和真实用量关联测试

- [x] T028（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_flow.py`；`src/backend/test/dsh/test_model_audit_request_id.py`
- 依赖：T013、T027、T025
- 工作与上下文：真实 model service 注入 fake policy/usage 与 capture，核对模式快照、调用前拒绝、流式未开始关闭、模型失败/取消、结算异常、真实用量缺失以及审计失败不改变返回/计费。
- 覆盖 AC: AC-11, AC-13, AC-15, AC-16, AC-17, AC-22, AC-23, AC-27, AC-28, AC-29, AC-31, AC-36
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T030 ASGI 响应结果与取消测试

- [x] T030（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_flow.py`
- 依赖：T011、T027
- 工作与上下文：受控 ASGI send/receive 验证 JSON 正常发送、SSE 错误、部分输出断开、未迭代关闭、取消和 send 异常；每轴独立，响应完成不表述客户端收到，编号沿用 request.state。
- 覆盖 AC: AC-13, AC-15, AC-23, AC-24, AC-36
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T036 运行时组装与有限关闭测试

- [x] T036（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_runtime.py`
- 依赖：T023、T025、T033、T035
- 工作与上下文：验证 lazy capture/writer/evidence/activity 装配、每 API 进程消费者启动、关闭有限 drain、队列丢失明确指标；MinIO/密钥不可用不拒绝业务，OFF 不采集。
- 覆盖 AC: AC-17, AC-22, AC-27, AC-31, AC-35
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T046 正文逐次授权留痕测试

- [x] T046（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_flow.py`；`src/backend/test/dsh/test_model_audit_storage.py`
- 依赖：T017、T045
- 工作与上下文：超管选定租户及租户管理员本范围可读，普通/菜单权限/跨租户拒绝；查看日志提交失败不得传任何正文；共享对象仍按目标请求独立授权、METADATA 无正文、部分原件按实际范围展示。
- 覆盖 AC: AC-09, AC-10, AC-18, AC-19, AC-20, AC-26, AC-33
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

### Wave 11 前驱完成后可启动

#### T029 模型服务采集与结算轴接入

- [x] T029（后端 Domain）
- 文件：`src/backend/bisheng/dsh/domain/services/model.py`
- 依赖：T028、T011
- 工作与上下文：complete 固定模式及认证身份，prepare/invoke/PreparedStream 接 T021/T027；在结算确认、未知或不确定分支独立记录真实状态来源。读模式失败 OFF；前置拒绝/未迭代关闭无 entered。用量仍走既有唯一链路，不改变额度准入或生成第二账本。
- 完成标准：T028 通过；现有 model_service/model_quota/settlement 测试回归。

#### T047 正文读取服务与日志仓储

- [x] T047（后端 Domain）
- 文件：`src/backend/bisheng/dsh/domain/services/model_audit_body_access.py`；`src/backend/bisheng/dsh/domain/repositories/model_audit_queries.py`
- 依赖：T046
- 工作与上下文：open_body_access 验证已授权记录和对象可读性，先提交 durable attempt/result，再有界读取原件；授权日志失败 fail closed。响应逐块保序、无直链/跨请求预取/批量导出，附加传输结果只报告服务观察值；不能声称客户端收到。
- 完成标准：T046 通过。

### Wave 12 前驱完成后可启动

#### T031 响应发送观察接入

- [x] T031（后端 API）
- 文件：`src/backend/bisheng/dsh/api/responses.py`；`src/backend/bisheng/dsh/api/endpoints/models.py`
- 依赖：T030、T029
- 工作与上下文：在 API/ASGI 边界采集 COMPLETED/ERROR/INTERRUPTED 与来源时间，非流式错误关联同一编号；DshStreamingResponse finally 维持 PreparedStream 关闭语义。此项只增量改响应观察，T009 的软解析和 T011 的编号规则保持。
- 完成标准：T030 通过。

#### T048 管理 HTTP 契约与权限测试

- [x] T048（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_flow.py`；`src/backend/test/dsh/test_model_audit_e2e.py`
- 依赖：T045、T047、T013
- 工作与上下文：真实 FastAPI + fake services 覆盖 requests 列表/详情、conversations、body-access、settings GET/PUT 的认证、租户范围、稳定分页、无默认正文和 body-access 禁缓存；模式变更日志失败返回错误，不让租户管理员改模式。
- 覆盖 AC: AC-18, AC-19, AC-21, AC-24, AC-29, AC-33
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T050 管理运行时工厂测试

- [x] T050（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_admin_runtime.py`
- 依赖：T045、T047、T013
- 工作与上下文：验证现有 DSH 管理运行时可提供查询/正文/模式服务，权限入口复用、无第二 FGA/Catalog；共享 MinIO、数据库和模式故障按各自边界处理。
- 覆盖 AC: AC-18, AC-19, AC-29
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

### Wave 13 前驱完成后可启动

#### T037 审计运行时与模型依赖装配

- [x] T037（后端 Domain）
- 文件：`src/backend/bisheng/dsh/audit_runtime.py`；`src/backend/bisheng/dsh/runtime.py`
- 依赖：T036、T029、T031
- 工作与上下文：组装 T013/T017/T019/T021/T023/T025/T033/T035，现有 get_model_runtime 向模型服务注入 capture_factory 和旁路依赖；通过业务运行时协调每进程后台任务，设置有限写入重试/关闭；不增加普通毕昇业务启动门禁。
- 完成标准：T036 通过。

#### T049 管理端点与路由组合

- [x] T049（后端 API）
- 文件：`src/backend/bisheng/dsh/api/endpoints/model_audit_admin.py`；`src/backend/bisheng/dsh/api/router.py`
- 依赖：T048
- 工作与上下文：实现 /api/v1/dsh/admin/model-audit 下设计 §6.2 六种路径/六个方法，依赖 UserPayload.get_tenant_admin_user，Endpoint 委托服务；PUT 模式额外全局超管判断，tenant_id 由服务核对范围。元数据沿 resp_200，正文走已授权有界响应；新路径不含 config。
- 完成标准：T048 通过。

### Wave 14 前驱完成后可启动

#### T038 DshRuntime.close 生命周期测试

- [x] T038（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_lifecycle.py`；`src/backend/test/dsh/test_model_audit_runtime.py`
- 依赖：T037
- 工作与上下文：测试 API 运行时关闭调用审计 close 一次、有界超时返回、消费者未创建时关闭安全、存储不可用主业务启动/停止仍可进行。
- 覆盖 AC: AC-17, AC-22, AC-27
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T041 审计状态检查任务与 worker runtime

- [x] T041（Worker）
- 文件：`src/backend/bisheng/worker/dsh/model_audit.py`；`src/backend/bisheng/dsh/operations_runtime.py`
- 依赖：T040、T037
- 工作与上下文：提供 dsh.scan_model_audit/dsh.inspect_model_audit 及有界租户分派扫描；trusted Celery headers.tenant_id 必与参数一致，进入异步桥前取 headers，profile_scope 恢复 ContextVar。扫描 pending/unknown 与历史在途记录，不按当前租户 OFF 跳过；复用 T025/CAS，不改用量巡检或账本。
- 完成标准：T040 通过。

#### T051 管理服务装配

- [x] T051（后端 Domain）
- 文件：`src/backend/bisheng/dsh/audit_admin_runtime.py`
- 依赖：T050、T049
- 工作与上下文：为新管理路由暴露 query/body_access/settings 服务工厂，复用 authorize_admin 与共享依赖；读原文按记录租户，不能按被审计用户当前 membership 改历史归属；不恢复旧操作审计隐藏页签或改变现有管理 API。
- 完成标准：T050 通过。

#### T065 D-09 评估口径测试

- [ ] T065（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_measurement.py`
- 依赖：T025、T037
- 工作与上下文：测量解析器/报告测试：独立请求清单为分母、分模式/正常失败取消、降级 OFF 单列、元数据/正文分别计时、固定 Token 用量查询基线；不把已写行作唯一分母，不把估计写全量，不内置开发前硬阈值。
- 覆盖 AC: AC-17, AC-24, AC-27, AC-30, AC-31
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

### Wave 15 前驱完成后可启动

#### T039 沿现有 DSH close 关闭旁路

- [x] T039（后端 API）
- 文件：`src/backend/bisheng/dsh/runtime.py`
- 依赖：T038
- 工作与上下文：在 DshRuntime.close 的既有生命周期中关闭已创建审计运行时；main.lifespan 已调用此 close，无须新增主应用启动强依赖。保留 Gateway/身份运行时关闭与异常处理。
- 完成标准：T038 通过。

#### T042 Worker/Beat 注册测试

- [x] T042（后端测试）
- 文件：`src/backend/test/dsh/test_operations_runtime.py`；`src/backend/test/dsh/test_model_audit_worker.py`
- 依赖：T041
- 工作与上下文：验证任务在非 API 进程可注册、Beat 调用有界租户分派、子任务 header 传递、关闭清理；DSH 未启用时不注册无效循环，现有 usage/profile/operation 任务保持。
- 覆盖 AC: AC-17, AC-24, AC-37
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

### Wave 16 前驱完成后可启动

#### T043 注册状态任务与调度

- [x] T043（Worker）
- 文件：`src/backend/bisheng/worker/dsh/registry.py`；`src/backend/bisheng/worker/config.py`
- 依赖：T042
- 工作与上下文：沿 register_dsh_tasks 添加审计注册与关闭，worker.config 添加可调状态检查分派周期；无 tenant_id 的扫描只发现租户并为每个子任务写可信 header，不在业务查询绕过租户过滤。API 活动刷新仍属 API runtime，Celery 只收敛审计状态。
- 完成标准：T042 通过。

#### T062 确定性端到端留存与故障矩阵

- [x] T062（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_flow.py`；`src/backend/test/dsh/test_model_audit_runtime.py`
- 依赖：T037、T039、T051
- 工作与上下文：贯穿真实路由→适配器→有界采集→仓储/对象 stub→管理读取，以独立 entered 清单为分母；健康小请求 drain 后必须有行/完整原件，关闭与降级无调用审计；工具/图片/压缩/重试、多租户、异常、全失写、预算满载及丢尾片不造 COMPLETE。
- 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-20, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-31, AC-34, AC-35, AC-36, AC-38
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

### Wave 17 前驱完成后可启动

#### T063 真实共享存储与双库回归

- [ ] T063（后端测试）
- 文件：`src/backend/test/dsh/audit_local_server.py`；`src/backend/test/dsh/test_sql_portability.py`
- 依赖：T043、T051
- 工作与上下文：隔离测试环境 MySQL/MinIO/Redis 验证跨 API/worker 读取、租户筛选、精确 ID、AES/密钥恢复、对象与 SQL 引用、原文日志失败；Linux 中央回归用 DM8 重跑关键仓储与索引。缺环境记录未执行，不能以 SQLite 或仅编译 SQL 宣称 DM8 实测通过。
- 覆盖 AC: AC-04, AC-06, AC-10, AC-14, AC-17, AC-18, AC-19, AC-20, AC-21, AC-24, AC-29, AC-37, AC-38
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T066 测试环境评估脚本与指标

- [ ] T066（后端 Domain）
- 文件：`src/backend/scripts/measure_dsh_model_audit.py`；`src/backend/bisheng/dsh/infrastructure/model_audit_telemetry.py`
- 依赖：T065、T043、T051
- 工作与上下文：脚本仅接受显式测试 BASE/合成样本/独立 entered 清单，对比 OFF/METADATA/CONTENT 首字/总时长 P95/P99、内存、可见时效及覆盖；以模式快照分组并保存基线来源。指标记录预算/队列/存储/清单/活动/查看失败，不带正文、凭证或高基数请求 ID。
- 完成标准：T065 通过；开发后测试环境产出实测报告，D-09 数值后续据实决定。

### Wave 18 前驱完成后可启动

#### T064 API E2E 与真实双端验收

- [ ] T064（后端测试）
- 文件：`src/backend/test/dsh/test_model_audit_e2e.py`；`features/v3.0.0-beta2/062-dsh-desktop-model-access/audit-guardrails-proposal/audit-acceptance.md`
- 依赖：T061、T062、T063、C010
- 工作与上下文：按 e2e-test 技能生成/执行 API 验收和页面手动清单；使用测试租户/超管/租户管理员/普通用户与真实客户端候选版，完成接口文档 C-A01 至 C-A12。记录客户端真实 Session ID、服务端编号和 SQL/正文结果，不宣称客户端真实会话关系由服务端验证。
- 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-07, AC-08, AC-10, AC-12, AC-13, AC-14, AC-15, AC-18, AC-19, AC-21, AC-22, AC-24, AC-28, AC-29, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37, AC-38
- 完成标准：新增用例先失败；配对实现完成后全部通过，记录测试命令与实际结果，不跳过故障断言。

#### T067 启用与回退运行说明

- [x] T067（交付文档）
- 文件：`features/v3.0.0-beta2/062-dsh-desktop-model-access/audit-guardrails-proposal/audit-rollout.md`
- 依赖：T063、T066
- 工作与上下文：说明默认 OFF、新表发现、各进程注册、密钥版本/备份恢复和 MinIO 运维责任；测试后超管逐租户切模式，变更不影响在途快照。回退先 OFF 并有限停止消费者、保留表/对象/密钥，不提供过期删除；记录只在测试验证的容量/窗口，普通业务和席位账本回归。
- 完成标准：列明的行为完成，配对测试及相关回归通过；记录实际修改和验证，未验证项不勾选。

### Wave 19 前驱完成后可启动

#### T068 完成验证与实现评审记录

- [ ] T068（交付文档）
- 文件：`features/v3.0.0-beta2/062-dsh-desktop-model-access/audit-guardrails-proposal/validation-results.md`；`features/v3.0.0-beta2/062-dsh-desktop-model-access/audit-guardrails-proposal/implementation-review.md`
- 依赖：T064、T066、T067
- 工作与上下文：执行目标后端测试、前端 lint/typecheck/i18n、arch-guard、e2e-test 与相对 origin/feat/3.0.0 的代码评审；记录每个 AC/双端用例的证据和未执行项，回写 design 当天实际系统与 tasks 偏差。未验证环境不标绿，不自动 commit/push/部署。
- 完成标准：列明的行为完成，配对测试及相关回归通过；记录实际修改和验证，未验证项不勾选。

## 5 AC 追溯矩阵

只列测试任务，不把实现描述当作已验收。

| AC | 测试任务 |
|---|---|
| AC-01 | T044、T062、T064、C005、C010 |
| AC-02 | T044、T062、T064、C005、C010 |
| AC-03 | T006、T044、T062、T064、C005、C010 |
| AC-04 | T014、T018、T044、T062、T063、T064 |
| AC-05 | T018、T044、T062、T064、C005、C010 |
| AC-06 | T014、T016、T018、T062、T063 |
| AC-07 | T014、T062、T064、C005、C010 |
| AC-08 | T014、T018、T062、T064、C005、C010 |
| AC-09 | T018、T020、T022、T024、T040、T046、T062 |
| AC-10 | T014、T016、T022、T026、T046、T062、T063、T064、C005 |
| AC-11 | T020、T022、T028、T044、T062 |
| AC-12 | T014、T020、T022、T026、T062、T064 |
| AC-13 | T022、T024、T028、T030、T040、T062、T064 |
| AC-14 | T014、T016、T026、T062、T063、T064、C005 |
| AC-15 | T010、T024、T028、T030、T044、T062、T064 |
| AC-16 | T024、T028、T044、T062 |
| AC-17 | T016、T020、T022、T028、T032、T034、T036、T038、T042、T062、T063、T065 |
| AC-18 | T012、T044、T046、T048、T050、T052、T054、T063、T064、T069 |
| AC-19 | T046、T048、T050、T054、T063、T064、T069 |
| AC-20 | T016、T018、T022、T046、T062、T063 |
| AC-21 | T018、T044、T048、T052、T054、T063、T064 |
| AC-22 | T006、T008、T012、T020、T028、T032、T034、T036、T038、T062、T064、C001、C003、C005、C007、C010 |
| AC-23 | T008、T010、T026、T028、T030、T062、C007 |
| AC-24 | T022、T024、T030、T032、T034、T040、T042、T044、T048、T052、T054、T062、T063、T064、T065 |
| AC-25 | T014、T022、T026、T062 |
| AC-26 | T006、T008、T014、T016、T026、T046、T062、C007、T069 |
| AC-27 | T020、T028、T032、T036、T038、T062、T065 |
| AC-28 | T020、T028、T034、T062、T064、C005、C010 |
| AC-29 | T012、T028、T040、T048、T050、T054、T063、T064 |
| AC-30 | T024、T034、T065 |
| AC-31 | T012、T020、T024、T028、T034、T036、T062、T065 |
| AC-32 | T044、T054、T064 |
| AC-33 | T044、T046、T048、T052、T054、T064、T069 |
| AC-34 | T006、T008、T044、T062、T064、C001、C003、C005、C007、C010 |
| AC-35 | T022、T036、T062、T064 |
| AC-36 | T010、T028、T030、T062、T064、C007、C010 |
| AC-37 | T024、T032、T040、T042、T063、T064 |
| AC-38 | T014、T018、T020、T022、T024、T040、T062、T063、T064 |

## 6 任务审查与偏差记录

本轮任务审查检查 AC 完整追溯、测试先行、DAG 依赖、每项最多两文件、双库/租户/权限边界、无高级关系或删除功能以及双端独立开发。实施前的 LGTM 仅针对计划，不表示代码或接口已发布。

审查结论：LGTM。38 条规格 AC 全部由明确列举 AC 的测试任务覆盖；80 项任务 ID 唯一且依赖无环，依赖均在先前 Wave，每项最多 2 个文件；后端及客户端配对测试先于实现。基础设施先建，Worker 传租户上下文，模型回退不删除表/原件，已有账本与管理员授权入口不被替换。修复了共享流式传输缺少任务的问题；未发现剩余 high/medium 计划问题。Markdown 文件链接、客户端锚点及 JSON 示例已校验；未执行任何本功能实现测试。

| 日期 | 记录 | 处理 |
|---|---|---|
| 2026-10-14 | 当前 Platform 请求包装没有浏览器 ReadableStream 能力 | 明确 T069/T070 的测试先行共享扩展，T053 依赖它；不在业务层复制权限错误处理 |
| 2026-10-14 | 旧接口草案含高级关联，现有客户端 config 丢弃可选字段 | 交付 0.3 两字段契约；C001 至 C010 覆盖能力状态与安全边界 |

后续偏差在此增量记录；变更验收或权限/采集边界先确认并同步 spec/design，不以实施便利削弱已确认需求。勾选只代表该任务验证完成；提交、推送、部署均须用户另行授权。

### 2026-10-14 首批实现与 L1 审查

证据见 [implementation-progress.md](./implementation-progress.md)。T001 增加租户过滤的模型强制导入注册（第二文件）。T037 的 runtime 参数透传已预接线，但采集工厂/消费者尚未接入，不标完成。T020/T021 独立采集器已通过用例，降级诊断、真实模型主流程及全局队列须在 T028、T034、T037 完成，保持未勾选。

客户端基于新 main，而非旧 PoC。C004 的 enterprise-desktop.ts 已完整透传公开状态，无需重复映射；C006 使用 auditFields 白名单回调，线协议不变。新 main 没有旧 PoC 测试，不新增该历史文件；C009 同步 mock 声明。C010 只完成真实插件/主进程的合成 mock 和实际 JSONL 重开自动化，真实 Electron、Fork、并行 Agent 操作及 T064 仍待执行，保持未勾选。

L1 逐项审查 T001、T002、T003、T004、T005、T006、T007、T008、T009、T010、T011、T012、T013、T014、T015、T016、T017：文件范围、配对测试、依赖、租户隔离、无正文 SQL/日志、密钥来源与设计同步通过；双库仅做约定审查，未声称 DM8/真实 MinIO 实测。28 个后端文件静态架构检查无发现。旧 task-checklist 的 DAO/状态库要求与当前 constitution/AGENTS 冲突处，以当前规范为准，使用 Repository、不新增 F048 资源。整体代码评审、E2E 和发布门禁未执行，L1 不等于完整功能验收。


### 2026-10-14 最终开发与隔离联调回写

上面的“首批实现”是历史时点；当前以本节、design.md 0.9 及 validation-results.md 为准。T018 至 T061、T062、T067、T069、T070 的实现和对应定向验证已完成；测试聚合到 flow/writer/runtime 等真实链路文件，文件路径已按落点调整，不为原计划标题制造重复测试文件。共享 request 层保留原语义，清理触碰的中文调试/注释，prune 仅缩减 6 行 suppression。单个事件仓储事务与增量计数取代全量重复扫片；去重及清单统一采用作用域 HMAC。

仍未勾选的任务不是缺失核心功能：T063 的本机 MySQL/Redis/MinIO 和 SQL 编译通过，真实 DM8 未执行；T064 本机 HTTP 验收、真实客户端代码链路和页面通过，正式 JWT/FGA/供应商/Electron 验收待执行；T065/T066 的安全评估脚本、分母/分轴测试和正常小样本已完成，但并发长流、故障/取消/读取降级的量化报告尚未完成；T068 文档/代码评审已产出，全面质量门禁仍有与干净基线相同的既有失败，不能标全绿。C010 正式 Electron UI/Fork/Windows 等保留未执行。

对应证据与门禁：[validation-results.md](./validation-results.md)、[audit-acceptance.md](./audit-acceptance.md)、[implementation-review.md](./implementation-review.md)、[audit-rollout.md](./audit-rollout.md)。不提交、不推送、不部署、不删除历史审计表/业务数据。
