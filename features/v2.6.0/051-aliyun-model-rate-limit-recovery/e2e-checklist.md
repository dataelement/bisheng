# E2E 验证清单：阿里百炼模型限流与安全恢复

**功能**: F051  
**页面**: Client `/workspace` 及 `/workspace/linsight`  
**自动化入口**: `test/e2e/test_e2e_aliyun_model_rate_limit_state.py`、`test/e2e/test_e2e_model_call_recovery.py`  
**数据前缀**: `e2e-f051-`（只允许在专用测试租户创建和清理）

## 1. 环境与角色准备

- [ ] 使用独立测试租户 A、B；每个租户准备管理员和普通用户，不复用生产数据。
- [ ] 为租户 A 配置两个能力兼容的阿里百炼模型 A、B，并配置一个与 A 同名但 ID 不同的模型 C。
- [ ] 为租户 B 配置一个与模型 A 同名的模型 D；确认四个模型 ID 均不同。
- [ ] 将模型 A 指向可控 OpenAI-compatible fake provider；fake provider 支持按用例返回临时限流、永久错误、成功，以及查询调用记录和副作用计数。
- [ ] 后端、Redis 6、Celery default worker、Linsight worker、MySQL 或 DM8、OpenFGA 均就绪；不要仅用 `/health` 判断可用。
- [ ] 自动化执行前设置 `E2E_API_BASE`、`E2E_ADMIN_PASSWORD`、`E2E_F051_FAKE_PROVIDER_URL`、`E2E_F051_STATE_CASES_JSON`、`E2E_F051_RECOVERY_CASES_JSON`。case 中的 `data_prefix` 必须以 `e2e-f051-` 开头。
- [ ] fake provider 的 `/__e2e/scenario` 必须原子清空上个用例记录并装载结果序列；`/__e2e/observation` 返回 probe、用户恢复调用和副作用增量。

## 2. 模型级限流与后台检测

### AC-01～AC-07：分类与脱敏

- [ ] 配置模型 A 下一次返回阿里临时限流码，分别覆盖 RPM/TPM/瞬时流量限制。
- [ ] 从日常模式发送 `e2e-f051-rate-limit`，预期原消息位置出现中性“模型服务繁忙”状态，不显示供应商 code、request_id、响应体或 API key。
- [ ] 分别返回欠费、未购买、鉴权失败、内容安全错误，预期沿用既有错误语义，模型不进入 busy。
- [ ] 让非阿里模型返回 HTTP 429，预期不进入本恢复流程。
- [ ] 运维日志中按 `tenant_id/model_id/execution_id/attempt_id` 检索，确认能看到脱敏后的供应商分类和 request_id；日志中不得出现 prompt、附件、工具参数或 API key。

### AC-12～AC-19、AC-28～AC-36、AC-52～AC-54：投影、探测和零会话重放

- [ ] 模型 A 限流后，同时打开日常、任务、知识空间、订阅频道页面；预期同一模型均显示“· 服务繁忙”，模型 C、D 状态不受影响。
- [ ] Network 面板确认 busy/recovering 时 `/api/v1/workstation/config` 约每 5 秒轮询；状态恢复 normal 后停止持续轮询。
- [ ] 将 fake provider 设为 `首次 429 → probe success`；等待后台探测，预期模型恢复正常，但原消息仍停留在原位置且不会自动继续生成。
- [ ] 检查 fake provider probe 请求：最多 3 次、退避约 15/30/60 秒、`max_tokens=1`、无用户问题、会话上下文、execution/session/chat ID、工具或附件。
- [ ] 比较探测前后 ChatMessage、Linsight task、文件和工具副作用计数，预期全部零增量。
- [ ] 将 fake provider 设为 `首次 429 → probe 429 × 3`；预期本轮检测终止，模型仍繁忙，页面保留“重试”“更换模型”“稍后再试”入口。
- [ ] 停用或删除繁忙模型后再让旧 probe 返回成功，预期不会把停用/删除模型恢复为可选。
- [ ] 临时停止 Redis 或 Celery 再触发一次测试调用，预期业务请求按既定 fail-soft/fail-safe 行为收敛，后台不得扫描或排队用户会话；恢复组件后重新验证正常路径。

## 3. 三入口主动恢复与任务重试/换模

### 工作台日常模式（AC-37～AC-51、AC-55）

- [ ] 在 `/workspace` 触发限流；预期用户消息、部分回答和未完成标记均保留在原气泡。
- [ ] 点击“重试”并快速双击，预期只有一个 recover 请求，且 URL 携带原 execution；不得走普通 regenerate。
- [ ] 当前页面点击重试；预期从同一原业务记录恢复。刷新后限流卡和失败片段允许消失，历史只显示原用户问题；不要求两个标签页共享状态。
- [ ] 首次限流即常驻显示“更换模型”，连续点击任意次数的 Retry 都不得自动弹出换模弹窗，页面和接口均无手动重试次数。
- [ ] 从常驻入口选择模型 B，预期恢复请求受理后输入框当前模型同步为 B，并在原位置继续原请求；该选择属于用户手动选择，不修改管理员默认模型。
- [ ] 选择后将模型 B 改为繁忙，预期返回统一 `12048/recovery_rejected` SSE 终态并提示恢复被拒绝；让 B 返回 auth_error 等普通模型错误时只显示原错误卡，不额外弹“所选模型不可用”。
- [ ] 删除原消息、撤销资源权限或移除日常恢复必要参数，再点击重试；预期统一返回 `12048/recovery_rejected`，不创建新的 busy 状态、不显示 provider detail，当前 Retry 入口结束。
- [ ] 在旧请求繁忙时新发一条请求；预期旧提示仍保留，但“重试”和“更换模型”入口消失，新请求独立执行。

### 工作台任务模式（AC-20～AC-27）

- [ ] 在 `/workspace/linsight` 使用 `e2e-f051-task` 运行一个先创建测试文件、随后调用模型的任务，并在第二次模型调用触发限流。
- [ ] 将同一任务配置为“前两次阿里临时 429、第三次成功”，预期调用次数、退避和最终成功结果与既有 retryable 错误完全相同；不得在识别 429 后提前失败。
- [ ] 将重试次数耗尽，预期仍经过既有失败落档、失败轮次、任务收敛和错误事件，只附加标准 `rate_limit_state/model_id` 展示字段。
- [ ] 任务模式触发 429 后点击“重试”；预期与其他任务执行错误一致，调用既有 `continueConversation(sessionVersionId, question)`，不调用独立 recover endpoint。
- [ ] 分别在独立灵思执行页和统一工作台内嵌任务卡触发最终限流失败；预期可操作页面同时显示“重试”和常驻“更换模型”，分享/历史只读页面不显示操作。
- [ ] 打开任务换模列表，预期复用任务模式现有模型集合，排除当前模型、重复模型和 `recovering/busy` 模型；连续 Retry/换模不显示次数，也不自动弹出换模弹窗。
- [ ] 选择模型 B，确认请求仍为 `POST /api/v1/linsight/workbench/continue`，body 使用原 `session_version_id/question` 并额外携带 `model_id=B`；普通 Retry body 不含 `model_id`。
- [ ] 换模请求受理后，确认仍是同一 session version 和 LangGraph thread，`linsight_session_version.model` 更新为 B，独立页及统一页当前任务输入框同步为 B 且按手动任务模型记忆；不得新建外层用户消息或 session version。
- [ ] 检查 Linsight 队列 item；预期仍为既有 `continue_question` 协议，不出现 `recovery/execution_id/attempt_id/target_model_id` 等任务专用恢复字段。
- [ ] 在打开候选后删除、停用、收回权限或使模型 B 不满足任务能力，再提交换模；预期复用现有模型校验拒绝，原失败轮次、session status/model 和输入框选择均不变，不产生 queue item。
- [ ] 模拟 queue enqueue 失败，并分别准备原状态 FAILED/COMPLETED；预期恢复各自的 original status 和 original model，不永久停留 IN_PROGRESS，页面保留原失败卡。
- [ ] 让模型 B 继续返回 429 或其他执行错误；预期仍经过任务原自动 retry、失败落档和错误事件，不进入换模专用失败分支。
- [ ] 任务模式 429 使用中性繁忙提示；非 429 执行错误的旧提示和 Retry 行为保持不变。

### 知识空间 file/folder（AC-37～AC-43、AC-49～AC-55）

- [ ] 在单文件 AI 会话触发限流并重试，预期重新执行只读检索和模型调用，不新增第二条用户消息或回答占位。
- [ ] 在文件夹 AI 会话重复上述流程；限流时确认数据库仅新增用户问题、不新增 bot answer；刷新后限流卡消失，重试成功后仅新增一条正常回答。
- [ ] 打开常驻换模列表，预期复用当前模型列表并排除当前模型和 busy 模型，不新增离线、权限或配置集合判断。
- [ ] 展开换模列表后撤销文件/空间权限再选择，预期服务端拒绝并保留原请求。

### 订阅频道（AC-37～AC-43、AC-49～AC-55）

- [ ] 在订阅文章 AI 会话触发限流，点击“稍后再试”，预期零请求且原文章会话不变。
- [ ] 点击“重试”或确认模型 B，预期按原问题 ID 继续，不新增用户消息；限流失败不新增回答，成功后只新增一条正常回答。
- [ ] 展开换模列表后撤销文章访问权限再选择，预期服务端拒绝，原消息和部分回答保留。

## 4. 回归与可访问性

- [ ] 四入口普通成功调用、timeout、5xx、非阿里 429 的现有重试/错误详情行为不变。
- [ ] busy 模型在普通模型选择器中仍可选；“更换模型”候选列表额外排除 busy，不改变其他历史筛选逻辑。
- [ ] 键盘可打开常驻换模列表、选择候选并关闭列表；状态卡有可读语义，焦点正确返回触发按钮。
- [ ] zh-Hans/en/ja 切换后新增文案完整，无 key 泄漏或布局溢出。
- [ ] 页面无新增 console error；正常态无持续 config 轮询。

## 5. 真实阿里与回滚验证

- [ ] 在隔离环境用真实阿里百炼低配额模型触发至少一种已知临时码，确认分类结果与 fake provider 一致；只保留脱敏日志证据。
- [ ] 先停止新版本 Worker，再回滚应用；确认旧版本不再读取新 Redis 状态。F051 无新增数据库表或字段，不需要 DDL 回滚。
- [ ] 回滚后验证普通模型调用、日常/任务/知识/频道入口和模型配置页面仍可用。
- [ ] 若需清理测试数据，只按 `e2e-f051-` 前缀和专用租户删除；不得做全表/全租户清理。

## 6. 未自动化项

- [ ] 真实阿里百炼配额触发、运维日志脱敏目检、Radix 弹窗焦点/键盘、三语视觉布局、真实浏览器双标签竞态、停 Redis/Celery 的降级演练、Linsight 已写真实文件后的人工内容核对、MySQL/DM8 双环境部署 smoke 均保留为手工项。
- [ ] 本清单执行人记录环境、镜像 SHA、数据库类型、时间、通过/失败项和证据链接；未执行项不得标记通过。

## 7. 本地自动化执行记录（2026-09-02）

- [x] 后端 F051 focused 回归：152 项通过。
- [x] Client 任务换模专项：5 个测试文件、13 项通过；完整 lint 与 i18n 检查通过。
- [x] 外部 E2E harness 成功收集 15 项，其中新增任务换模 case <code>task_continue_switch</code> 验证同一 continue endpoint、同一 session version 和 model 更新。
- [ ] 当前机器未提供 <code>E2E_F051_STATE_CASES_JSON</code>、<code>E2E_F051_RECOVERY_CASES_JSON</code> 及 fake provider/full middleware 环境，因此 15 项全部跳过；本记录不代表真实环境 E2E 通过。
