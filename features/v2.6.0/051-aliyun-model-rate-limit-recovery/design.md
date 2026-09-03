# Design: 阿里百炼模型限流状态与主动恢复

> **本文档定位 — 最终设计真相（Why this How）**
>
> - [spec.md](./spec.md) 规定业务行为和验收标准。
> - 本文档规定唯一实现口径、状态边界、调用链和并发保护。
> - [tasks.md](./tasks.md) 只记录实施过程，不得反向覆盖本文档。
>
> 本版是在 2026-08-28 最终设计上按 2026-09-02 已确认需求更新的完整当前口径，
> 覆盖此前 execution 聚合器、任务 429 特殊旁路和“任务模式不换模”等旧设计。
> 当前代码和旧测试必须重新按本文核对，不能反向定义设计；tasks.md、release-contract.md 和验收清单已据此同步。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)  
**版本**: v2.6.0  
**状态**: ✅ 设计变更已确认（2026-09-02）

**最后更新**: 2026-09-02

---

## 1. 目标与非目标

### 1.1 目标

F051 是叠加在既有模型调用和业务入口之上的**限流观察与展示层**：

1. 识别阿里百炼明确临时限流。
2. 维护租户内、实际模型配置级、带 TTL 的 Redis 限流展示状态。
3. 使用无用户上下文的有限 probe 检测模型是否恢复。
4. 为日常、知识、频道当前页面提供基于既有用户消息的主动重试与换模。
5. 任务模式的内部自动重试、失败处理和普通 Retry 全部保持原样；限流最终失败后可在原位置切换模型继续原问题。
6. 任务模式换模只扩展既有 continue 入口，不新增恢复状态机、队列协议或 checkpoint 分支。
7. F051 任一附加能力失败时，原模型异常和业务链路仍按旧逻辑工作。

### 1.2 非目标

- 不建立用户请求 execution 状态机，不新增数据库表或字段。
- 不保存、扫描、排队或自动执行触发过限流的用户会话。
- 不改变 <code>llm_model.status</code> 的既有健康语义。
- 不改变任务模式中间件对 429、超时、连接错误和 5xx 的原有分类、退避、降级或失败处理。
- 不改变模型在线状态、权限、能力、默认模型和入口候选集合。
- 不新增任务恢复 endpoint、command、attempt、checkpoint、队列字段或按轮次模型审计表。
- 不提供跨刷新、跨标签页、跨设备的严格次数和 exactly-once。
- 不扩展至非阿里供应商，不自动换模。

---

## 2. 关键约束与不可变行为

本设计遵循 [constitution.md](../../../docs/constitution.md) C1–C7，并沿用
[release-contract.md](../release-contract.md) 中 F051 对 <code>ModelRateLimitState</code> 和 INV-9 的归属约束。
版本契约已同步登记 probe_token、任务模式旧链路和恢复拒绝 12048。

### 2.1 七个状态/行为边界

| 边界 | 唯一真相 | F051 可以做什么 | F051 不得做什么 |
|---|---|---|---|
| 模型健康状态 | 既有模型调用装饰器维护的 <code>llm_model.status</code> | probe 作为真实模型调用自然参与旧更新 | 直接写、覆盖或从 Redis 推导健康状态 |
| 限流展示状态 | Redis <code>ModelRateLimitState</code> | 标记 <code>recovering/busy</code>、CAS 清除、TTL 自然恢复 | 代表模型在线/权限/配置可用性 |
| 任务内部自动重试 | <code>LinsightModelResilienceMiddleware</code> 既有分类和 retry 配置 | 在不影响结果的前提下旁路观察异常 | 对阿里 429 提前抛出、跳过或改变 retry/degrade |
| 任务失败处理 | <code>LinsightWorkflowTask</code> 既有失败落档和收敛 | 在现有错误 payload 上附加模型限流展示字段 | 保留特殊未完成状态、改变 terminate/checkpoint 语义 |
| 任务用户 Retry/换模 | 既有 <code>continueConversation(sessionVersionId, question)</code> | 普通 Retry 原样；换模只给既有 continue 增加可选目标模型并更新现有 session version 的 model | 新增 task recovery API、command、attempt、checkpoint 或 queue 字段 |
| 非任务用户恢复 | 既有 ChatMessage + 当前页面临时关联 | 重新鉴权、短时防重复、原位置恢复 | 建立持久 execution、保存次数或写失败回答 |
| 后台模型 probe | tenant + model 的 Celery 任务 | 更新健康状态和 Redis 投影 | 携带或查询任何用户会话，调用业务恢复器 |

### 2.2 Observer-not-interceptor 不变量

F051 对真实模型调用只能做 best-effort 观察，不能成为原调用的控制器：

    原模型调用/原异常
          |
          +--> 既有健康状态更新
          |
          +--> 原调用方既有成功/重试/失败逻辑
          |
          +--> F051 best-effort 观察
                 分类 + Redis + probe + 日志
                 任一步失败只记日志，不改变上面两条链

具体要求：

1. 观察失败不得吞掉原异常。
2. 观察不得把一个原本可重试的异常改成 fail-fast，也不得反向放宽永久错误。
3. 观察不得替换原异常类型、错误信息或堆栈；业务终端层只在原失败已确定后附加标准展示字段。
4. 成功观察只能按调用开始前看到的 Redis version 做 CAS 清除，不能无条件删除当前状态。
5. 删除 F051 观察代码后，除繁忙展示和主动恢复增强外，原调用次数、重试次数、失败落档和健康状态结果必须不变。

### 2.3 任务模式 429 的明确口径

任务模式中的“重试/恢复”拆成四个阶段；前三阶段沿用旧逻辑，只有第四阶段是本次新增能力：

| 阶段 | 429 行为 |
|---|---|
| 中间件内部自动重试 | 与其他 <code>Behavior.RETRYABLE</code> 异常进入相同退避、次数和降级逻辑 |
| 自动重试用尽后的失败处理 | 与其他执行错误进入相同 <code>_handle_task_failure</code>、失败轮次和任务收敛 |
| 用户点击 Retry | 与其他任务错误一样调用既有 <code>continueConversation</code> |
| 用户选择切换模型 | 给同一个 <code>continueConversation</code> 增加可选目标模型；继续同一 session version 和原问题，不新增恢复执行实体 |

禁止存在“确认是阿里 429 后跳过 resilience retry”的 provider-aware guard。阿里分类只负责附加 Redis
状态和 UI <code>error_type=rate_limit</code>，不负责控制任务执行。<code>/workbench/continue</code> 是 F035 已有的
同会话新一轮入口；F051 只扩展它的可选模型参数。统一工作台内嵌任务卡上的限流 Retry/换模按钮属于本期 UI 接线，
不得把这部分误写成 F035 已经具备的历史行为。

---

## 3. 方案对比与选定

### 决策 1：如何识别本期临时限流

- **备选**
  - A. 所有 HTTP 429 都进入 F051。
  - B. 只用通用错误关键词。
  - C. 同时校验实际供应商、HTTP 429、阿里临时子码/文案，并优先排除永久错误。
- **选定**：C。
- **原因**：阿里将频率、Token、突发限制以及欠费/未购买等不同语义都放在 429 下；只看状态码会误标永久错误，只看关键词会扩大到其他供应商。
- **规则**：仅 <code>Throttling.RateQuota</code>、<code>Throttling.AllocationQuota</code>、<code>Throttling.BurstRate</code>、<code>LimitRequests</code>、<code>limit_requests</code>、<code>limit_burst_rate</code>、<code>ResourceExhausted</code>、阿里兼容层的临时 <code>insufficient_quota</code> 及等价官方文案进入 F051。欠费、余额不足、未购买、401/402/403、内容安全优先排除。
- **何时重新考虑**：生产出现新的阿里官方临时码时，扩展白名单和契约测试；不得放宽为所有 429。

### 决策 2：F051 放在调用链中的角色

- **备选**
  - A. 特殊 429 拦截器：识别后提前抛出或改写原调用。
  - B. 异步聚合器：统一接管所有入口的调用和恢复状态。
  - C. best-effort observer：观察原调用结果，附加 Redis 状态和诊断，不改变原控制流。
- **选定**：C。
- **原因**：用户要求限流与业务逻辑解耦；A 会改变任务自动重试，B 会重新引入 execution 聚合和第二业务真相。C 允许四入口共享分类和状态，同时保持原逻辑。
- **实现约束**：任何入口调用 <code>observe_call_failure/success</code> 都必须放在不会阻止原成功/失败收敛的位置；观察服务自身捕获 Redis、解析、调度和诊断异常。
- **何时重新考虑**：只有所有模型调用统一迁入一个已有的、已验证不改变调用语义的基础设施层时，才合并 observer 接入点。

### 决策 3：限流展示状态存在哪里

- **备选**
  - A. 复用 <code>llm_model.status</code>。
  - B. 新建数据库状态表。
  - C. Redis 临时投影。
- **选定**：C。
- **原因**：限流是租户级、短时供应商观测，不是模型配置持久健康事实；Redis 可跨 API、Linsight worker、Celery 和多个页面共享，TTL 可自然恢复。
- **Key**：<code>model_rate_limit:{tenant_id}:{model_id}</code>。
- **TTL**：默认 300 秒；真实新限流刷新 TTL 和 <code>busy_until</code>。
- **何时重新考虑**：只有产品要求 Redis 灾难恢复后仍保留历史限流审计，才评估持久化；审计不能与当前繁忙状态混表。

### 决策 4：如何兼顾 single-flight、最新版本接管和 ABA

- **备选**
  - A. 只比较 <code>version</code>；旧任务 version 不同即拒绝。
  - B. 排队任务忽略 payload version，看到 <code>scheduled</code> 就接管。
  - C. <code>version</code> 保护结果 CAS，独立 <code>probe_token</code> 保护排队任务归属。
- **选定**：C。
- **原因**：A 会使同一轮排队期间的新 429 导致所有探测失效；B 会让 key 删除/重建后的旧任务接管新轮次，形成 ABA。两个令牌分别解决不同问题。
- **约束**
  - <code>version</code>：每次真实 429 生成新的 52 位随机 generation；probe/真实成功只按它 CAS 收敛。
  - <code>probe_token</code>：每次真正创建一个待执行探测槽位时生成新的不透明随机 token；同一 <code>scheduled</code> 槽位收到新 429 时保持不变。
  - Celery task claim 必须同时校验 key 存在、<code>probe_state=scheduled</code>、<code>probe_token</code> 和 <code>probe_attempt</code>。
  - claim 成功后返回 Redis 当前最新 <code>version</code>，使该任务在同一槽位内接管最新限流事实。
- **何时重新考虑**：若改用支持唯一任务键和 compare-and-set 的可靠调度基础设施，可用其原生 generation 替代 <code>probe_token</code>，结果 CAS 仍需保留。

### 决策 5：后台恢复检测如何运行

- **备选**
  - A. API/worker 进程内异步任务。
  - B. Celery 有界模型 probe。
  - C. 保存受限会话，模型恢复后逐个重放。
- **选定**：B；明确禁止 C。
- **原因**：Celery 提供跨进程延迟调度和有界执行；probe 只需要 tenant/model，不应持有请求进程或用户上下文。
- **调用**：固定系统消息、无历史、无工具、无文件、非流式、<code>max_tokens=1</code>，延迟依次为 15/30/60 秒。
- **终止**
  - 成功：按 claimed version 清 Redis；旧健康装饰器自然写 NORMAL。
  - 同类限流：未满三次则创建新 <code>probe_token</code> 调度下一次；第三次置 <code>busy/exhausted</code>。
  - 非限流错误或模型不可用：停止，不能声明恢复；Redis 等待真实成功或 TTL。
  - Redis/Celery 故障：记录日志，当前用户调用继续返回原错误；不增加补偿扫描器。
- **何时重新考虑**：供应商提供不消耗生成额度的健康端点时替换最小生成 probe；仍不得连接用户会话。

### 决策 6：原请求和页面 attempt 存在哪里

- **备选**
  - A. 新建统一 <code>model_call_execution</code> 表。
  - B. 把恢复内容和 attempt 放 Redis。
  - C. 业务事实读取既有记录；attempt 只在当前页面；后端仅做 5 秒短锁。
- **选定**：C。
- **原因**：ChatMessage、Linsight session version 已经拥有原问题和业务进度；另建 execution 会复制会话事实并产生清理、状态同步和迁移负担。产品接受刷新后限流 UI 消失，且不再需要手动重试次数。
- **ID 语义**
  - 日常、知识、频道：<code>execution_id = subject_id = 原用户 ChatMessage.id</code>，只是实时传输关联标识，不代表新的 execution 实体。
  - <code>attempt_id</code>：当前页面为一次主动恢复生成的临时标识，只用于过滤迟到结果。
  - 任务：继续只使用原 <code>sessionVersionId</code>，不进入上述 command；可选 <code>model_id</code> 只表示本次用户选择的执行模型，不形成新的执行或 attempt。
- **短锁**：<code>tenant:user:entry:subject</code>，TTL 5 秒，只抑制近同时点击；Redis 故障 fail-open，不承诺 exactly-once。
- **何时重新考虑**：只有产品明确要求长期幂等或 exactly-once，且业务自身无法承载时，才重新设计持久执行实体。

### 决策 7：各入口如何主动恢复

- **日常 Agent**
  - 首次请求先保存用户消息。
  - 限流不保存失败回答。
  - 用户点击重试或确认换模后，从原 ChatMessage 读取问题和模型、工具、知识库参数，启动一轮新的日常调用；带工具时重新创建本轮 Agent，不读取或续跑 checkpoint。
  - 复用原用户消息，不新增第二条问题记录；成功只保存一条正常回答。工具调用是否再次执行沿用普通日常调用语义，由本次用户主动操作触发。
- **知识空间 file/folder 与订阅频道**
  - 首次请求先保存用户消息。
  - 检索和生成链路为只读时，从原 ChatMessage 读取问题，在同一页面位置重新调用。
  - 限流不保存失败回答；成功只写一条正常回答，不增加第二条用户消息。
- **任务模式**
  - 内部自动重试、最终失败处理和普通 Retry 全部沿用旧逻辑。
  - 限流最终失败后，独立任务执行页和统一工作台内嵌任务卡复用同一个限流卡组件，提供 Retry 与常驻换模入口。
  - 普通 Retry 调用既有 <code>/api/v1/linsight/workbench/continue</code>，不携带目标模型；换模仍调用该接口，只额外携带可选 <code>model_id</code>。
  - 后端复用现有模型解析、租户权限、在线状态和任务模型能力规则校验目标；校验通过后把目标写入现有 <code>linsight_session_version.model</code>，再按原 <code>continue_question</code> 队列协议投递。
  - worker 不接收新模型字段，继续从 session version 读取 <code>model</code> 并在同一 LangGraph thread 创建下一轮 agent；不是 <code>Command(resume)</code>，不读取或新增 checkpoint 恢复分支。
  - 换模成功受理后才把所选模型同步到任务模式输入框并标记为用户手动选择；受理失败保留原失败卡、原模型和原输入框选择。
  - 不接入公共 recovery command，不新增 checkpoint 分支、队列字段或按轮次模型记录。session version 的 <code>model</code> 表示后续执行使用的当前模型；本期不提供每轮模型审计。
- **原因**：日常模式是用户主动重新执行原问题，不是任务执行流的断点续跑；LangGraph 只是日常工具编排实现，不能因此引入任务 checkpoint 语义。恢复方式必须服从入口既有业务边界，不能为了“统一”强迫四入口共享同一种执行状态机。
- **何时重新考虑**：只有产品明确要求日常模式从中断节点续跑，并同时定义工具副作用幂等边界时，才为日常模式单独设计 checkpoint 恢复。

### 决策 8：状态如何送达页面

- **选定**：复用 <code>/api/v1/workstation/config</code> 的模型列表，批量叠加 Redis 状态；存在 <code>recovering/busy</code> 时每 5 秒 refetch，全部 normal 后停止。
- SSE/WS 收到 <code>rate_limit</code> 时先在 Query Cache 中投影并 invalidate，使轮询立即启动。
- 普通模型选择器显示 busy 但不禁用；限流卡常驻换模列表排除当前模型和 busy 模型，不改变其他历史候选规则。
- 用户从常驻入口选择模型且业务端受理成功后，同步更新当前输入框模型并按任务/日常各自的用户手动选择规则记忆；不修改管理员默认模型。
- 旧请求在发送新消息后保留提示、关闭操作；页面刷新允许丢失限流卡。
- **原因**：模型列表已经是四入口公共数据源；不新增 Recoil/store 或服务端推送状态机。
- **何时重新考虑**：5 秒条件轮询造成可测压力或需要亚秒同步时，再考虑 tenant/model/statusVersion 推送。

### 决策 9：错误与诊断如何分层

- 真实限流：
  - 日常、知识、频道使用统一 SSE 错误 envelope，<code>status_code=12046</code>、<code>error_type=rate_limit</code>。
  - 任务模式沿用既有 11090/任务错误事件，只附加 <code>error_type=rate_limit</code>、<code>rate_limit_state</code>、<code>model_id</code>。
- 恢复拒绝：
  - 使用统一 SSE 错误 envelope，<code>status_code=12048</code>、<code>error_type=recovery_rejected</code>。
  - 前端必须把 12048 的 i18n 文案作为主要提示，不得落入 unknown，也不得继续显示 Retry。
- 终端字段只含稳定状态和关联 ID，不含 provider raw detail。
- provider code、request_id、脱敏且限长的详情只进结构化日志/telemetry；不记录 prompt、历史、附件、工具参数、API key。
- **何时重新考虑**：形成业务用户诊断权限模型后才允许受控详情端点，不能直接复用终端错误卡。

---

## 4. 系统调用链与状态机

### 4.1 通用真实模型调用

每次实际模型尝试都遵循同一顺序：

    读取调用开始前的 Redis statusVersion（读取失败视为无投影）
      -> 调用模型
           -> 既有装饰器按成功/失败更新 llm_model.status
           -> 成功：
                F051 best-effort clear_if_version(调用前看到的 version)
                返回原成功结果
           -> 异常：
                F051 best-effort classify + mark_busy + schedule probe
                向原调用方重新抛出同一个异常

注意：

- F051 的读取、分类、Redis、Celery、日志异常全部在 observer 内收敛。
- observer 不返回“是否应该 retry/fail-fast”的控制决策。
- 业务入口只在原错误最终需要呈现给用户时，把 observer 产生的标准字段加入原 SSE/WS 错误。

### 4.2 任务模式 429 调用链

    Linsight middleware 调用 handler
      -> 模型返回阿里临时 429
      -> 既有健康装饰器写 ERROR
      -> F051 observer best-effort 标记 Redis / 投递 probe
      -> 原异常进入既有 classify_behavior
           -> RETRYABLE：按既有 retry_num/retry_sleep 再调用同一 handler
           -> retry 成功：旧健康逻辑写 NORMAL，F051 CAS 清 Redis
           -> retry 用尽：按既有 degrade_or_raise
      -> 最终失败进入既有 _handle_execution_error/_handle_task_failure
           -> 原 status/output_result/失败轮次/错误事件/任务收敛不变
           -> 若 observer 有结果，只附加 rate_limit_state/model_id
      -> 用户点击 Retry
           -> 既有 continueConversation(sessionVersionId, question)，不携带 model_id
      -> 用户选择目标模型
           -> 同一 continueConversation(sessionVersionId, question, model_id)
           -> 更新现有 session version.model 后投递原 continue_question
           -> worker 从 session version 读取目标模型，在同一 thread 开始下一轮

以下实现均违反本设计：

- 在 <code>classify_behavior</code> 之前用 provider guard 对阿里 429 直接抛出。
- 为 rate_limit 跳过或替换 <code>_handle_task_failure</code>。
- 为 rate_limit 保留不同于其他任务错误的 unfinished/checkpoint 状态。
- 让任务模式进入日常/知识/频道的 recovery endpoint。
- 为任务换模新增 queue 字段、恢复 command、checkpoint resume 或新的 session version。
- 只更新前端输入框或只把模型塞进队列 payload，导致 worker 与页面的当前模型不一致。

### 4.3 模型限流投影与探测状态机

Redis JSON：

| 字段 | 说明 |
|---|---|
| <code>state</code> | <code>recovering/busy</code>；key 不存在即 normal |
| <code>version</code> | 每次真实 429 生成的新 52 位随机 generation；保护结果 CAS |
| <code>limited_at</code> | 最近一次真实 429 时间 |
| <code>busy_until</code> | TTL 对应的绝对时间 |
| <code>probe_state</code> | <code>scheduled/running/exhausted</code> |
| <code>probe_attempt</code> | 当前或下一探测序号 |
| <code>probe_token</code> | 当前排队探测槽位的不透明随机 token；保护 claim 和 key ABA |
| <code>last_probe_at</code> | 最近一次实际探测时间 |

<code>mark_busy</code> 原子规则：

1. key 不存在：新 version、新 probe_token、<code>scheduled/attempt=1</code>，投递第一次 probe。
2. 当前 <code>scheduled</code>：刷新 version/TTL，保留 probe_token 和 attempt，不重复投递；现有排队任务可接管最新 version。
3. 当前 <code>running</code>：刷新 version/TTL，创建新 probe_token 和 <code>scheduled/attempt=1</code>，投递后继 probe；旧运行结果因 version 不匹配空操作。
4. 当前 <code>exhausted</code> 且收到真实新 429：新 version、新 probe_token，重新开始有限探测。

<code>begin_probe</code> claim 规则：

    key 存在
    AND probe_state == scheduled
    AND probe_token == task.probe_token
    AND probe_attempt == task.probe_attempt

满足后原子切换为 running，并返回 Redis 当前 version。任何条件不满足均为空操作。

probe 收敛规则：

- 成功：<code>clear_if_version(claimed_version)</code>。
- 再次限流：只有 version、running、attempt 均匹配才收敛；未到第三次则生成新 probe_token 和下一 attempt，第三次置 busy/exhausted。
- 非限流错误：停止，不清 Redis，不安排下一次。
- task 重复投递、迟到或 key 重建：probe_token 不匹配，空操作。

该组合同时满足：

- 同一 scheduled 槽位内接管最新 version；
- 运行中真实新 429 使旧结果失效；
- key 删除/重建后旧任务不能接管新状态；
- Celery at-least-once 重复投递不能抢占新探测槽位。

### 4.4 非任务入口的主动恢复

    当前页面收到 rate_limit SSE
      -> 原用户消息已存在；不写 bot 失败回答
      -> 页面保留 execution_id/subject_id/attempt_id 临时关联
      -> 用户点击 Retry 或确认换模
           -> 入口按 subject_id 读取原 ChatMessage
           -> 校验当前 user/tenant/resource 和 URL execution_id 一致
           -> 换模时只额外拒绝 recovering/busy；其他模型规则沿用旧链路
           -> 获取 5 秒短锁
           -> 日常：按原问题和原参数启动一轮新的日常调用
              RAG：按原问题只读重新调用
           -> SSE 结果携带当前 attempt_id
           -> 当前页面只接受仍在等待的 attempt
           -> 成功按旧格式写一条正常回答

恢复校验失败或短锁未获准均返回 12048/recovery_rejected；该结果结束当前 attempt，
不标记模型 busy，不继续展示 Retry。

### 4.5 页面模型状态更新

    rate_limit SSE/WS
      -> Query Cache 将对应 model 标成 recovering/busy
      -> invalidate workstation config
      -> 存在 busy/recovering 时每 5 秒 refetch
           -> Redis key 仍在：刷新展示
           -> probe/用户成功或 TTL 后 key 不在：显示 normal，停止轮询

页面模型 normal 只表示 Redis 限流投影已消失；模型是否在线、可见、可选仍由原模型列表规则决定。

### 4.6 任务模式换模继续

任务模式换模复用现有 continuation，而不是通用 recovery：

    TaskTurnPanel / ExecutionFlow 收到最终 rate_limit 失败
      -> 从 workstation config 的原任务候选集合中
         排除当前模型和 recovering/busy 模型
      -> 用户选择 target model
      -> POST /api/v1/linsight/workbench/continue
           { session_version_id, question, model_id }
      -> 校验 session version 存在、归属当前用户且处于 COMPLETED/FAILED
      -> 按任务模式既有模型解析规则校验 model_id
      -> 记录 original_status/original_model
      -> 同一次数据库更新写 IN_PROGRESS + target model
      -> 按原协议 enqueue encode_queue_item(session_version_id, continue_question=question)
           -> 成功：返回 accepted；前端开启新一轮并同步任务输入框模型
           -> 失败：恢复 original_status + original_model；返回既有统一错误，前端保留原失败轮次
      -> worker async_continue/_continue_workflow
           -> 从 session version.model 读取 target model
           -> 同一 thread 追加既有 continue_question 并执行

关键约束：

1. <code>model_id</code> 缺省时与当前 F035 continue 行为完全一致，普通 Retry 和普通后续提问不受影响。
2. 目标模型校验只能复用现有任务模型解析、权限、在线状态和能力规则，不新增另一套模型列表或 F051 专属可用性规则；前端 busy 过滤只是体验优化，不能替代后端校验。
3. DB 和 Redis queue 无法形成单一事务，因此必须保存原状态和原模型；enqueue 异常时两者一起回滚，不能固定回滚成 COMPLETED，也不能留下“输入框已切换但任务未受理”。
4. 不携带 <code>model_id</code> 的普通 Retry 维持当前乐观归档/Running 交互；携带目标模型的换模分支必须在变更前保存完整轮次快照，接口拒绝或网络失败时完整恢复。输入框模型只在 accepted 后同步，不能因一次未受理的选择漂移。
5. 同一操作不新增外层 ChatMessage、session version 或用户气泡；LangGraph thread 仅按既有 continue 语义接收一次原问题。任务工具副作用和上下文语义与普通 Retry 相同。
6. 两个 carrier 行为一致：
   - 统一工作台内嵌 <code>TaskTurnPanel</code>：受理后更新共享 <code>chatModel</code> 为 <code>manual=true, mode=task</code>，底部任务输入框随之更新。
   - 独立执行页 <code>ExecutionFlow</code>：将同一已受理模型值传给底部 <code>TaskModeInput</code>；历史/分享只读页不显示 Retry 或换模。
7. UI 复用 <code>ChatErrorCard -> ServiceBusyNotice</code> 的常驻 dropdown；不增加弹窗、点击计数或“三次后自动换模”。

---

## 5. 已知坑与处理位置

| # | 反直觉事实 | 不处理的后果 | 设计处理 |
|---|---|---|---|
| 1 | 阿里欠费和临时频率限制都可能是 429 | 永久错误被标 busy | 永久信号优先排除，再匹配阿里临时白名单 |
| 2 | <code>llm_model.status</code> 和 Redis busy 都会随模型调用变化，但语义不同 | 状态互相覆盖、离线模型被误恢复 | 两套状态独立；F051 不直接写健康状态 |
| 3 | 任务有内部自动 retry、失败落档、用户 Retry、用户换模四个阶段 | “沿用旧重试”被实现成只保留其中一层，或让换模绕过旧链 | §2.3、§4.2 和 §4.6 分阶段固定行为 |
| 4 | observer 若在原失败处理前抛错，会让任务永远停在执行中 | 限流附加能力破坏主业务 | observer 全部 fail-soft，原异常/成功优先 |
| 5 | 只用 version 无法同时满足“接管最新版本”和“拒绝重建 key 的旧任务” | Celery 旧 attempt=3 可耗尽新轮次 | version 管结果，probe_token 管排队归属 |
| 6 | Celery 是 at-least-once，旧任务和重复任务都可能迟到 | probe single-flight 被破坏 | claim 校验 token + attempt + state |
| 7 | 成功与新 429 可以并发 | 旧成功误删新 busy | 每次真实成功只按调用前观察 version CAS |
| 8 | 换模入口已在限流卡常驻 | 继续保留无意义的页面三次计数和自动弹窗 | 删除页面计数；换模只由用户点击常驻入口触发 |
| 9 | 12048 envelope 有 i18n 不等于页面一定展示该文案 | 用户只看到 unknown 或英文详情 | error_type 映射和 SSE 翻译纳入前端契约测试 |
| 10 | focused test 可以把错误设计写成正确预期 | 全部测试通过仍违背业务口径 | 测试先比较“接入 F051 前后原行为不变”，再验证新增状态 |
| 11 | probe 成功不是用户请求恢复 | 后台无授权地自动生成回答 | probe 依赖图禁止任何会话 repository 和 recovery service |
| 12 | enqueue 失败后没有可靠 task | 状态可能只能等 TTL | 产品接受该降级；记录日志，不增加会话扫描或复杂补偿 |
| 13 | 现有 continue enqueue 失败固定回滚为 COMPLETED | 原来是 FAILED 的任务被改错状态；换模还会留下错误 model | 捕获 original_status/original_model，失败时一起恢复 |
| 14 | Linsight worker 从 session version.model 解析模型，不读取前端选择器或新 queue 参数 | 只改 UI/queue 会继续调用旧模型，形成假换模 | 受理时更新现有 model，队列协议保持不变 |
| 15 | 独立 ExecutionFlow 与内嵌 TaskTurnPanel 是两个 carrier | 只修一个页面会再次出现按钮或输入框不一致 | 共用候选过滤和错误卡契约，并分别覆盖组件测试 |
| 16 | session version 只有一个 model 字段 | 换模后无法按轮次审计历史模型 | 接受“当前/后续执行模型”语义；本期不新增表或轮次字段 |
| 17 | 当前 continue 前端先乐观归档失败轮次 | 接口校验或 enqueue 失败会留下伪 Running/重复轮次 | 保留不可变快照；accepted 后提交 UI，失败则不变或完整回滚 |

---

## 6. 对外契约与依赖

### 6.1 模型列表投影

<code>GET /api/v1/workstation/config</code> 的 <code>models[]</code> 只增加：

    {
      "rateLimitState": "normal | recovering | busy",
      "busyUntil": "ISO-8601 | null",
      "statusVersion": 0
    }

这些字段不改变模型顺序、默认项、权限、在线状态或能力集合。

### 6.2 SSE/WS 错误

| 场景 | 状态码/类型 | 必要字段 | 禁止字段 |
|---|---|---|---|
| 日常/知识/频道真实限流 | <code>12046/rate_limit</code> | execution_id、attempt_id、recovery_subject_id、model_id、rate_limit_state | provider raw code/detail/request_id |
| 非任务恢复拒绝 | <code>12048/recovery_rejected</code> | execution_id、attempt_id、recovery_subject_id、model_id（若可得） | 新的 rate_limit 语义、provider detail |
| 任务最终限流失败 | 既有任务错误码 + <code>rate_limit</code> | 原任务错误字段，可附加 model_id/rate_limit_state | recovery command/attempt 状态 |

所有 SSE 校验和运行时错误均使用 <code>BaseErrorCode.to_sse_event_instance_str()</code> 同构 envelope。Client 必须先按
<code>status_code</code> 解析 i18n，再用 <code>error_type</code> 选择卡片；<code>recovery_rejected</code> 是明确终态，不得回退到 unknown。

### 6.3 主动恢复 API

仅日常、知识、频道提供入口内 recovery API：

- <code>POST /api/v1/workstation/chat/executions/{execution_id}/recover</code>
- <code>POST /api/v1/knowledge/space/{space_id}/chat/executions/{execution_id}/recover</code>
- <code>POST /api/v1/channel/chat/executions/{execution_id}/recover</code>

统一 body：

    {
      "attempt_id": "page-local UUID",
      "subject_id": "original ChatMessage.id",
      "action": "manual_retry | switch_model",
      "target_model_id": 17
    }

<code>execution_id</code> 和 <code>subject_id</code> 必须与读取到的业务记录一致。它们是授权与结果归位字段，不形成持久 execution。

任务模式不使用上述三个 recovery API，而是扩展既有接口：

    POST /api/v1/linsight/workbench/continue
    {
      "session_version_id": "existing session version id",
      "question": "original failed question",
      "model_id": "optional target model id"
    }

- <code>model_id</code> 缺省：普通 Retry/后续提问，行为与 F035 当前实现相同。
- <code>model_id</code> 存在：在既有归属、终态校验之后，复用任务模式原模型解析规则校验目标；更新现有 session version 的 <code>model</code> 后投递未变更的 <code>continue_question</code>。
- queue payload 仍只有 <code>session_version_id + continue_question</code>，不增加 <code>model_id/action/attempt</code>。
- enqueue 失败：恢复进入请求前的 session status 和 model，返回既有统一响应错误；不得留下 IN_PROGRESS。
- 接口 accepted 只代表 continuation 已入队；执行结果仍通过原任务消息流返回。

### 6.4 Celery probe 契约

- task body：<code>model_id/probe_token/probe_attempt</code>。
- 叶子 <code>tenant_id</code>：只通过可信 Celery header 传递。
- 禁止字段：execution_id、attempt_id、subject_id、chat_id、session_version_id、user_id、prompt、messages、files、tools。
- task 只依赖模型配置解析、LLM 调用、Redis 状态和诊断，不得依赖 ChatMessage、Linsight repository 或 recovery service。

### 6.5 模块职责

| 模块 | 职责 | 明确不做 |
|---|---|---|
| <code>aliyun_rate_limit_classifier.py</code> | 供应商感知的临时限流分类 | 不决定 retry/fail-fast，不写状态 |
| <code>model_rate_limit_state.py</code> | Redis TTL、version/probe_token CAS、批量读取 | 不读取模型、会话或用户业务数据 |
| <code>model_rate_limit.py</code> | best-effort 观察编排和标准 DTO | 不吞异常，不执行用户恢复 |
| <code>worker/model_rate_limit.py</code> | 有界无上下文 probe | 不接触 execution/session/chat |
| 三个非任务业务入口 | 读取并鉴权自己的 ChatMessage，执行自己的安全恢复 | 不把恢复事实交给公共聚合器 |
| Linsight API/既有 workbench service | 原自动 retry、失败处理和 continue 链路；可选校验并更新现有 session model；enqueue 失败回滚状态和模型 | 不接入通用 recovery command，不新增 DAO/queue 协议 |
| Linsight worker | 继续从 session version.model 解析当前模型并消费原 continue_question | 不解析新的换模 payload，不新增 checkpoint resume |
| Client Query | 轮询模型投影 | 不成为模型状态第二真相 |
| Client bubble/hook | 页面 attempt、常驻换模入口和输入模型联动；任务 accepted 后同步 taskModel | 不持久化次数，不修改管理员默认模型，不在受理前提交选择 |

### 6.6 数据、发布与回滚

- 不新增数据库表、字段、迁移、回填或会话删除联动。
- 任务换模只更新既有 <code>linsight_session_version.model</code>；该字段是后续执行的当前模型，不承诺按轮次审计。
- Redis 限流 key、probe token、5 秒短锁均按 TTL 清理。
- 发布时 API、默认 Celery、Linsight worker 必须为同一版本；旧 worker 不得消费新 probe payload。
- 回滚前停止新 worker；回滚后 Redis 临时 key 等待 TTL，不需要业务数据清理。

### 6.7 Constitution Check

| 条款 | 设计结论 |
|---|---|
| C1 DDD 分层 | 不新增 API 层跨域查询或 DAO；在现有 Linsight workbench service 中编排模型校验、session 更新与 enqueue，endpoint 只解析参数和返回统一响应。既有 DAO 方法复用，不新增 repository 入口。 |
| C2 双数据库 | 不新增 SQL/迁移；现有 SQLModel update 同时适用于 MySQL/DM8。 |
| C3 多租户 | session 先按现有用户归属校验；目标模型通过租户上下文中的现有 LLM 解析服务校验，禁止信任前端候选。 |
| C4 OpenFGA | 不扩展模型权限边界；目标模型继续走现有模型可见性/授权链路，任务本身继续走 owner 校验。 |
| C5 审计日志 | 不记录 prompt、原问题、历史或凭证；只记录 tenant/user/session_version/original_model/target_model/result 的结构化标识，敏感字段按现有规则脱敏。 |
| C6 错误码 | 新参数校验复用既有统一响应/error code；不裸抛 HTTPException，不把校验失败伪装成 rate_limit。 |
| C7 前端边界 | HTTP 仍由 <code>api/linsight.ts</code> 封装，Recoil/store 不直接请求；复用现有 Client 组件和状态，不引入新库。 |

---

## 7. 测试与可观测

### 7.1 测试原则

测试顺序必须是：

1. 先证明原业务行为在接入 F051 前后不变。
2. 再验证新增分类、Redis、probe、页面展示。
3. 最后验证 F051 故障时原行为仍不变。

不得仅根据当前实现编写测试预期。

### 7.2 后端关键契约

1. 阿里临时白名单与欠费/鉴权/内容安全强排除；非阿里 429 不创建 F051 状态。
2. 429 和普通失败都继续触发旧健康 ERROR；成功和 probe 成功继续触发旧 NORMAL。
3. 任务模式中，相同 <code>Behavior.RETRYABLE</code> 的普通异常和阿里临时 429：
   - handler 调用次数一致；
   - delay/retry/degrade 分支一致；
   - 最终失败写入、失败轮次、事件和任务收敛一致；
   - 唯一差异是 429 可附加 F051 展示字段。
4. observer/classifier/Redis/Celery/日志分别抛错时，任务原异常、自动重试和失败处理不变。
5. Redis 状态覆盖：
   - 首次 mark、并发 refresh、TTL、版本 CAS；
   - scheduled 期间新 429，旧 task 接管最新 version；
   - running 期间新 429，旧结果无效、后继任务唯一；
   - key 删除/重建，旧 queued task claim 失败；
   - Celery 重复投递，旧 probe_token 不能接管新槽位；
   - attempt=3 迟到不能把新轮次置 exhausted。
6. probe payload 和依赖图不含任何用户执行标识；probe 调用对消息、任务、文件、工具写入为零。
7. 日常/知识/频道限流不写 bot answer；成功恢复只写一条正常回答且不新增用户消息。
8. 12046 与 12048 都使用统一 SSE envelope；恢复拒绝不被分类成 rate_limit。
9. 任务 continue 不传 <code>model_id</code> 时，请求、session 更新、queue payload 和 worker 行为与现有 F035 完全一致。
10. 任务 continue 传目标模型时：
    - 复用现有模型解析规则拒绝无权限、离线、不存在或不满足任务能力的模型，且不更新 session、不 enqueue；
    - 合法目标写入现有 session version.model，queue payload 仍不含 model_id，worker 从 DB 解析并使用目标模型；
    - 同一 session version、同一 thread 和原问题继续，不创建新 session version 或外层 ChatMessage。
11. continue enqueue 失败时，原 status 为 COMPLETED/FAILED 的两种情况都分别恢复原值，并恢复 original_model；触碰 session、日志和错误响应符合现有约定。
12. target model 执行再次 429 或其他错误时，仍进入 §2.3 的原自动 retry、失败落档和错误事件，不存在换模专用失败旁路。

### 7.3 前端关键契约

1. rate_limit 到达即启动 config polling；normal 后停止。
2. 普通模型选择器 busy 可点击；限流卡的常驻换模列表过滤当前和 busy，其他筛选规则不变。
3. 当前页面 Retry 双击禁用，attempt 迟到结果不覆盖当前气泡。
4. 不维护手动重试次数，不自动打开换模弹窗；用户从常驻入口选择模型后同步更新当前输入框模型。
5. 恢复调用返回普通模型错误时只展示原错误卡；只有 12048/recovery_rejected 被解释为换模/恢复操作拒绝。
6. 发送新消息后旧卡保留但无 Retry/换模操作；刷新不重建限流卡。
7. 12048/recovery_rejected 显示对应语言的主要终态文案，不显示 unknown，不提供继续 Retry。
8. 所有新 UI 使用 Client 设计系统 Button size、语义字体和颜色 token；三语 key parity。
9. 独立 <code>ExecutionFlow</code> 与内嵌 <code>TaskTurnPanel</code> 在任务 rate_limit 失败时都显示 Retry 和换模；分享/历史只读页面均不显示操作。
10. 任务换模候选复用既有任务模型列表，排除当前模型、重复模型和 recovering/busy；普通 Retry 不携带 model_id，换模携带所选 model_id。
11. 任务换模可沿用现有乐观归档，但必须保存并在拒绝、网络失败或 enqueue 失败时恢复完整失败轮次；输入框仅在 accepted 后同步为 <code>manual=true, mode=task</code>。普通 Retry 的现有 UI 时序保持不变。
12. 按钮 pending 防止同页面双击；没有手动次数上限，不自动打开换模弹窗。

### 7.4 E2E/手工矩阵

使用可控 fake provider：

- 任务：普通 retryable 错误与阿里 429 使用相同自动重试次数；最终失败均走相同旧链，用户 Retry 均走同一 continue API。
- 任务换模成功：同一 session version/thread 使用目标模型继续原问题，独立页与内嵌页输入框同步，零新外层用户消息。
- 任务换模目标失效或 enqueue 失败：保留原 FAILED/COMPLETED 状态、原模型和失败卡，不产生 queue item。
- <code>429 -> 内部 retry success</code>：任务不落失败，健康恢复，Redis busy 被 CAS 清除。
- <code>429 -> probe success</code>：模型展示恢复，原用户请求不自动执行。
- <code>429 -> probe 429 x3</code>：状态转 busy，零用户业务写入。
- <code>429 -> user retry/switch success</code>：原位置完成，无第二条用户消息；日常模式重新启动一轮调用并按普通日常语义执行工具。
- <code>旧 task -> key clear -> 新 429</code>：旧 task 空操作。
- 两租户同 model_id、同租户同名不同 model_id：状态隔离。
- Redis/Celery 故障：原错误、任务 retry 和失败处理仍工作。
- 恢复记录删除、必要参数缺失、目标模型变 busy：统一 12048 SSE，页面显示明确终态。

### 7.5 可观测

- <code>aliyun_rate_limit_detected_total</code>
- <code>model_rate_limit_probe_total{result}</code>
- <code>model_rate_limit_busy_seconds</code>
- <code>model_call_recovery_total{entry,action,result}</code>
- <code>rate_limit_state_write_failed</code>
- <code>stale_probe_total{reason}</code>

日志必须包含 tenant/model/server/entry、provider code、脱敏 request_id、probe attempt/token 摘要和结果；禁止记录用户内容与密钥。

### 7.6 完成门槛

- Spec AC-01–56 均能映射到自动测试或明确的手工步骤。
- 任务模式“调用次数、失败落档、用户 Retry”三层均有接入前后对比测试。
- 任务模式“换模受理、worker 实际模型、双 carrier 输入联动、失败回滚”均有契约测试。
- Redis ABA、Celery 重复投递和 probe/user success 与新 429 并发均有测试。
- 后端 focused、前端 component、ruff、lint、typecheck、i18n、arch-guard、diff check 通过；环境阻断项必须单独报告，不得写成通过。
- 至少在一个可控环境完成四入口 E2E；未执行前不得把 feature 标记为完成。

---

## 8. 后续改进与明确延期

- 使用供应商 Retry-After 或专用健康端点替代固定 probe。
- 将其他供应商接入同一 observer contract，但必须另立 Spec。
- 服务端主动推送模型状态，只有条件轮询产生可测压力时再引入。
- 跨设备严格次数、长期幂等和 exactly-once；需要独立业务论证，不能复活本期已否决的 execution 聚合器。
- 管理员限流趋势面板；本期只提供日志和 telemetry。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-02 | 任务模式限流失败新增换模继续：扩展既有 continue 的可选 model_id，更新现有 session model，队列协议/worker/checkpoint 不变；补齐双任务界面、输入框联动和 enqueue 失败双字段回滚 | 产品确认任务模式也需要常驻换模能力，同时要求复用旧任务恢复语义、保持限流与任务业务解耦 |
| 2026-09-01 | 日常模式主动恢复改为读取原 ChatMessage 后重新执行一轮日常调用，移除日常 checkpoint 续跑 | 用户确认日常模式不是任务模式；现场验证 checkpoint 子图语义导致 Retry 在模型调用前失败 |
| 2026-08-28 | 完整重写：F051 定位为 observer-not-interceptor；任务三层重试全部沿用旧逻辑；移除 execution 聚合；Redis 增加 probe_token 解决 ABA；恢复拒绝纳入统一 SSE 和前端终态契约 | 多轮评审发现旧文档保留互相冲突的决策，无法作为实现与测试的唯一判据 |
