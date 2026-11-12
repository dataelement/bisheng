# Design: 积分按模型真实价格扣除

**关联**：[spec.md](./spec.md) · [tasks.md](./tasks.md) · [runbook.md](./runbook.md) · [request.md](./request.md)
**版本**：v3.1.0-beta1（F015-credit-pricing）
**最后更新**：2026-11-12（初版，待用户确认；技术评审 v2.0 的 8 个阻塞项已纳入）
**核查基线**：Bisheng `feat/3.1.0-beta1@3254ab555`；在途分支对比 `feat/3.1.0-beta1-014-pptd-deck`；Desktop `V1.3.0@e9a5ca6b`。

---

## 1. 目标与非目标

- **目标**：把单次调用的扣费从「(输入 + 输出) × 倍率」改为「四类 token × 该模型单价 → 花费 ÷ 积分单价」；每次调用在开始时记录价格快照，结算、回放、对账只认快照；模型有价格（添加时按内置价格表带出），三端显示积分倍率；补齐工作台三处漏扣。
- **非目标**：不改额度分配（CreditRule）、额度检查与 Redis Lua（admit / settle / pressure）、月度汇总；不扩大到工作流、助手、知识库入库、开放 API、非聊天模型；不做分时段 / 分档计价、价格表联网更新、模型发现结果对应价格表。

---

## 2. 关键约束

遵循 `docs/constitution.md` C1–C8（分层、双库、多租户、权限、错误码、密钥、前端调用、多进程）。Constitution Check：新表登记租户感知清单（C3）；新接口鉴权沿用所在模块现有的管理员依赖（与现有 `/api/v1/llm`、`/api/v1/dsh/admin/*` 一致），不新增资源级授权（C4）；错误码 26176、10813 已登记（C5）；缺价时报错而不是静默按免费（C8 的「fail loudly」）。本功能特有的约束：

- **账本是 int64 整数**：Lua 只做整数比较和累加，不能引入浮点；账本单位保持「微积分」（1 积分 = 10⁶，`TOKENS_PER_CREDIT`）。
- **事件可回放、不可变**：`UsageEvent` 进入 Redis 和 SQL 投影，自动恢复与对账从事件重算；同一事件任何时候重算结果必须一致。`DshContract` 为 `extra="forbid", strict=True`。
- **事件哈希兼容**：`QuotaRedis._identity()` 的哈希不能因新增字段改变历史事件的值。
- **事件保留 ≥ 30 天、Redis 有内存水位**：已投影事件在 `quota_retention_seconds`（默认 2,592,000）之后才由 `cleanup.lua` 删除；`pressure.lua` 在用量超过「预算 − 余量」时拒绝新调用。新增到事件里的每个字节都乘以 5 份副本、30 天保留。
- **停服升级**：新版本写出的事件旧版本读不了（extra=forbid），升级不能新旧进程混跑，开放使用后不能换回旧镜像（§3 决策 18、runbook）。
- **多进程**：API 容器 2 个 uvicorn 进程（`entrypoint.sh` 第 56 行），另有 worker；进程内缓存不共享。
- **达梦无日常门禁**：DM8 只由发版前中心回归验证，CI 只构建镜像，macOS 无达梦驱动；本特性改动了大表结构，需单独做达梦演练（tasks T18b），通过前 PR 不合并。
- **客户端兼容**：桌面 `contract.js` 的 `parseModelEntry`、`parseUsage` 按白名单拷贝、忽略未知字段；服务端只加可选字段。
- **私有化部署**：内置价格表随包发布，不联网。路由路径不能出现 `config`（客户 WAF 会拦）。
- **前端**：`ModelConfig.tsx`（617 行）、`Cascader.tsx`（593 行）已接近或超过 `src/frontend/AGENTS.md` 的单文件上限，改动时需拆出逻辑；packages/ui 改动需负责人认可。

---

## 3. 方案对比与选定

### 决策 1：账本单位保持「微积分」整数

- **备选**：A. 保持 `billed_tokens`（= 10⁻⁶ 积分）整数，只改单次扣多少；B. 账本改存金额。
- **选定**：A
- **原因**：额度规则、Redis 计数、`DshMonthlyUsage.used_tokens`、桌面换算都已是这个单位；改单位牵动 Lua、恢复、统计和桌面。
- **何时重新考虑**：需要按金额直接设定额度时。

### 决策 2：调用开始时把价格写成快照，结算不查价格

- **备选**：A. 开始时把生效价格写入 `UsageEvent.pricing` 并落库；B. 结算时按「模型 + 时间」查价格历史表。
- **选定**：A
- **原因**：与原先快照 `credit_rate` 的做法一致；回放不依赖外部数据；「改价只影响之后的调用」天然成立（AC-06）；不需要价格历史表。
- **何时重新考虑**：Redis 容量成为瓶颈且快照无法再精简时。

### 决策 3：全部用整数微单位，向上取整，结果有上限校验

- **备选**：A. 单价、积分单价、汇率在快照里都是 ×10⁶ 整数，结果 `⌈raw ÷ 分母⌉`；B. Decimal / 浮点。
- **选定**：A
- **原因**：回放确定；MySQL / 达梦一致；直接对接整数账本。中间值可超 int64（Python 不溢出），只校验 `cost_micro`、`billed_tokens` ≤ 2⁶³−1，超出按用量异常处理（结算为用量未知、不扣费、告警）。
- **何时重新考虑**：需要分档计价时。

### 决策 4：模型价格存 `llm_model.config.pricing` ★待产品确认

- **备选**：A. 存进模型已有的 `config` JSON；B. 新表 `dsh_model_pricing`（租户 + 模型一行）。
- **选定**：A
- **原因**：价格在「添加模型」表单填写，随现有保存流程走；已核实 `config` 中只有 `user_kwargs` 会传给模型 SDK（`llm/domain/llm/llm.py _get_user_kwargs`）。
- **代价**：Root 共享模型只能由 Root 定价，子租户只读。
- **何时重新考虑**：产品要求子租户各自定价 → 改 B（S2 约多 1 天）。

### 决策 5：旧倍率从产品与计算中删除，只为升级前事件保留一行旧公式

- **备选**：A. 删除，`billed_tokens` 在 `pricing is None` 时沿用旧公式；B. 保留开关。
- **选定**：A
- **原因**：产品决定不留开关。升级当月同时存在无快照的旧记录，对账恢复要用它们重算，必须保留旧公式；新事件一律带快照，`credit_rate` 固定 100。数据库 `credit_rate` 列保留到下个版本。
- **何时重新考虑**：升级满一个账期、旧事件被清理后，可删除旧公式与列。

### 决策 6：「没有价格记录」与「价格为 0」分开 ★AC-22 待产品确认

- **备选**：A. 缺失 pricing = 未迁移，计费范围内的调用拒绝（错误码 26176）；四价全 0 = 免费，走 unmetered；B. 缺失按 0（v2.0 方案）。
- **选定**：A
- **原因**：B 会在漏跑升级回填或任何异常写入路径下静默免费（技术评审阻塞项 1）。升级门禁要求缺失数为 0 才开服，正常情况下不会出现。
- **何时重新考虑**：产品拒绝 AC-22 时，退回「缺失按 0 + 告警」，门禁仍保留。

### 决策 7：积分设置单独建表、单独读取，不进策略快照

- **备选**：A. 新表 `dsh_credit_setting`，计费时按租户主键读；B. 放进 `DshPolicySnapshot`。
- **选定**：A
- **原因**：`DshPolicySnapshot.recovery_payload()` 包含 `model_dump()`，加字段会改变恢复协议。
- **何时重新考虑**：恢复协议本身重构时。

### 决策 8：积分倍率由服务端统一计算，口径固定 3:1

- **备选**：A. 服务端算出字符串，前端只展示；B. 前端各自计算。
- **选定**：A
- **原因**：三处显示要一致，且依赖基准模型与汇率。产品已确认 3:1（AC-12）。
- **何时重新考虑**：产品要求按员工实际用量结构（而非固定 3:1）展示倍率时。

### 决策 9：工作台倍率只在响应中注入，不加到 `WSModel`

- **备选**：A. 端点在 `model_dump` 之后往 `models[]` 字典加 `pricing_hint`；B. 给 `WSModel` 加字段。
- **选定**：A
- **原因**：`WSModel` 也是工作台配置的存储结构，加字段会在管理员保存配置时写回数据库；`WSModel` 默认忽略未知字段，前端回传会被丢弃。
- **何时重新考虑**：工作台配置的存储结构与响应结构拆开后，可改为响应模型字段。

### 决策 10：计费范围按调用场景补齐

- **备选**：A. `governed()` 加 knowledge_space；回答溯源、频道看图在工作台调用处改传 daily_chat；B. 整类放开 rag_traceability。
- **选定**：A
- **原因**：knowledge_space 只被知识空间问答与看图默认值使用；rag_traceability 工作流也在用，产品决定工作流不计费。
- **何时重新考虑**：产品决定工作流、助手等也计费时，改为按场景整类纳入。

### 决策 11：回答溯源「扣但不拦」

- **备选**：A. `chat_credits` 提供公开的 `unmetered()` 上下文，溯源在其中调用模型，并捕获额度异常降级；B. 正常拦截。
- **选定**：A
- **原因**：溯源由 `asyncio.create_task` 在回答发出后执行，拦截只会让已发出的回答报错（AC-15）。不从外部写私有 ContextVar（评审应修项）。
- **何时重新考虑**：溯源改为在回答前同步执行时，应改为正常拦截。

### 决策 12：桌面 Work 下拉框用 Harness 插槽，不打补丁

- **备选**：A. 注册 `conversation.input.model.label` 插槽；B. 改 `patches/@deepseek-ai+dsh-client-ui-model-selection`。
- **选定**：A，`priority: -1`
- **原因**：插槽是 single 类型，DeepSeek 官方插件已占优先级 0，同优先级注册会抛错；数字小的优先级渲染。代价是员工自带 DeepSeek 账号时 deepseek-flash 的 1017 小标被遮住。
- **何时重新考虑**：Harness 把该插槽改为 chain 类型时。

### 决策 13：价格表与模型价格放 llm 模块，计费与倍率放 dsh 模块

- **备选**：A. 价格在 llm、计费在 dsh；B. 全部放 dsh。
- **选定**：A
- **原因**：价格是模型属性，保存流程在 llm；扣费、额度、倍率是企业客户端职责；llm 已依赖 dsh（chat_credits），方向不变。dsh 端点不 import llm，经 dsh 服务调用 `LLMService`。
- **何时重新考虑**：非企业客户端场景（工作流、助手）也要用价格时，价格表仍留 llm，计价函数下沉到公共层。

### 决策 14：新逻辑放新文件，老文件只加调用

- **备选**：A. 新文件承载逻辑；B. 直接改老文件。
- **选定**：A
- **原因**：在途分支大改 `llm.py`（约 800 行）、`llm/api/router.py`（约 110 行）、`ModelConfig.tsx`（约 130 行），减少合并冲突。
- **何时重新考虑**：在途分支全部合入后，可按模块整理收拢。

### 决策 15：计费取价不经缓存

- **备选**：A. 两个入口在调用开始时按主键直接读模型价格与积分设置；B. 沿用 `model_info`（60 秒进程内缓存）并定义「60 秒内生效」；C. 做跨进程缓存失效广播。
- **选定**：A
- **原因**：网页入口的 `model_info` 来自 `LLM_CACHE`（`llm/domain/const.py` 第 51 行，`base.py` 第 67、80 行 `cache=True`），只清本进程；AC-06、AC-10 要求下一次调用生效；C 要引入新机制。代价是每次调用多 1–2 次主键查询。
- **何时重新考虑**：取价查询成为热点时，改为带版本号的跨进程缓存。

### 决策 16：适配器出口统一 token 口径 ★边界规则待产品确认

- **备选**：A. 在适配器出口按「输入含缓存命中与写入」统一；逐来源映射；缓存 > 输入时按排他口径加回并打点；B. 计价时把未命中的负数截断为 0（v2.0 / 需求文档边界）。
- **选定**：A
- **原因**：B 对排他口径来源静默少扣（评审阻塞项 2）；`langchain-anthropic` 1.4.7 在分桶上报缓存写入时把通用 `cache_creation` 置 0，现有适配器漏读。映射见 §4.4。
- **何时重新考虑**：接入新的用量来源时补映射与夹具。

### 决策 17：价格只有一条写入边界，带 revision 比较交换

- **备选**：A. 改价与保存提供方共用同一服务入口和事务（Root 只读、提供方行锁、空闲检查、租户校验、审计、清缓存）；价格带 `revision`；B. 独立改价接口（v2.0）。
- **选定**：A
- **原因**：B 绕过在途 F118 加在 `update_server_with_models` 上的 `alock_provider`、`arequire_idle` 与删除目标锁，且与「编辑提供方」互相覆盖价格（评审阻塞项 5）。
- **依赖**：F118 合并顺序（tasks T04）。
- **何时重新考虑**：模型配置拆成独立表或引入统一的配置版本号时，revision 改用通用机制。

### 决策 18：停服升级；开放使用后只前向修复

- **备选**：A. 停服 → 备份 → 迁移 → 回填 → 门禁 → 仅管理员冒烟 → 开服；开服前失败整库 + Redis 恢复；开服后不回滚；B. 滚动升级、换镜像回滚。
- **选定**：A（★「开服后是否必须可回滚」待拍板）
- **原因**：事件协议不向后兼容且保留 ≥ 30 天；即使旧代码能读，旧公式重算新事件也与汇总对不上，恢复会拒绝（评审阻塞项 6）。
- **何时重新考虑**：要求开服后可回滚 → 加「降级转换脚本」（约 1–1.5 天）。

### 决策 19：快照精简，只放计费字段

- **备选**：A. 快照只含币种、积分单价、四个单价（发生换算时加汇率）；B. 完整快照（含来源、价格表 key 与版本）。
- **选定**：A
- **原因**：2026-11-12 本机 Docker Redis 7 按 admit / settle / confirm_projection 字段模拟 2 万次调用：现在每次约 5.3 KB，B 为 +34%，A 为 +15%。AC-07 只要求记录单价、币种、积分单价和花费。来源信息保留在模型配置与审计记录中。
- **何时重新考虑**：需要在调用记录里直接查询价格来源时，在 SQL 列中单独记录来源，不进 Redis 事件。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（本特性改动后）

1. **入口 A（网页）**：`BishengLLM._generate/_agenerate/_stream/_astream` → `@account_*`（`dsh/domain/services/chat_credits.py`）→ `governed()`：dsh 开启且 `app_type ∈ {daily_chat, linsight, knowledge_space}`。
2. **入口 B（桌面 Work）**：`POST /api/v1/dsh/chat/completions`、`/responses` → `DshModelService.complete()`（`dsh/domain/services/model.py`）。
3. **取价**：两个入口在调用开始时调用 `read_model_pricing(model_id)`、`read_credit_setting(tenant_id)`（`dsh/runtime.py`，按主键直读，不经缓存）→ `build_snapshot()`（`dsh/domain/services/pricing.py`）：缺失 → 26176；全 0 → `mode="unmetered"`。
4. **准入**：`QuotaRedis.check_and_start(event, mode)` → `lua/admit.lua`（不变）。
5. **用量归一**：`chat_adapter.normalize_usage` / `responses_adapter.normalize_responses_usage` → `usage_contract`（统一口径，§4.4）。
6. **结算**：`settle_usage()` → `UsageEvent.billed_tokens`（有快照按 §4.3，无快照按旧公式）→ `lua/settle.lua`（不变）。
7. **投影**：`DshUsageRepository.project_batch()` → `dsh_model_call`（新增 pricing、cost_micro、currency）、`dsh_monthly_usage`。
8. **恢复**：`recovery_snapshot()` 由每行构造 `UsageEvent` 后取 `billed_tokens` 重算，与月度汇总比对。

### 4.2 关键数据结构

| 结构 | 格式 | 说明 | 消费方 |
|---|---|---|---|
| `llm_model.config.pricing` | `{currency, input, cache_read, cache_write, output, source, catalog_key, catalog_version, ref_key, revision}`，单价为十进制字符串（最多 6 位小数，上限 999999.999999），`cache_write` 可空 | 模型价格；`source` ∈ CATALOG / MANUAL / DEFAULT，由服务端判定 | 后台、计费取价、升级脚本 |
| `UsageEvent.pricing` / `dsh_model_call.pricing` | `{currency, credit_value_micro, input_micro, cache_read_micro, cache_write_micro, output_micro[, usd_cny_rate_micro]}`，全部整数（×10⁶，计价币种） | 精简快照，不可变 | 结算、投影、恢复、身份哈希 |
| `dsh_model_call.cost_micro` / `currency` | BIGINT / VARCHAR(3)，可空 | 本次花费 | 用量页、对账 |
| `dsh_credit_setting` | 每租户 ≤ 1 行：currency、credit_value_micro（默认 10,000）、usd_cny_rate_micro、base_model_id、version、updated_by、时间 | 积分设置；无行时用默认值 | 计费、倍率、后台 |
| `pricing_hint` | `{ratio: "0.28" | "<0.01" | null, base: bool, free: bool}` | 积分倍率展示 | 网页工作台、桌面、后台 |

### 4.3 计价

```
miss          = input − cache_read − cache_creation        （口径已统一，不变式保证 ≥ 0）
raw           = miss·input_micro + cache_read·cache_read_micro + cache_creation·cache_write_micro + output·output_micro
cost_micro    = ⌈raw ÷ 10⁶⌉
billed_tokens = ⌈raw ÷ credit_value_micro⌉
换算（快照生成时一次）：USD→CNY ⌈p × rate ÷ 10⁶⌉；CNY→USD ⌈p × 10⁶ ÷ rate⌉
倍率：(3·input + output) ÷ (3·base_input + base_output)，两位小数，<0.01 显示 "<0.01"
```

### 4.4 token 口径（`dsh/infrastructure/usage_contract.py`）

统一契约：`input_tokens` 含缓存命中与写入；`cache_creation_tokens` 含 5 分钟、1 小时分桶之和；`total = input + output`；不变式 `cache_read + cache_creation ≤ input`。

| 来源 | 输入口径 | 命中 | 写入 | 处理 |
|---|---|---|---|---|
| LangChain `usage_metadata`（ChatOpenAI 系） | 含缓存 | `input_token_details.cache_read` | `input_token_details.cache_creation` | 直接用 |
| `langchain-anthropic` `usage_metadata` | 库已加回为含缓存 | `cache_read` | `cache_creation` 或 `ephemeral_5m_input_tokens + ephemeral_1h_input_tokens` | 读分桶之和，不重复计 |
| 原始 OpenAI 兼容 `token_usage`（兜底） | `prompt_tokens` 含缓存 | `prompt_tokens_details.cached_tokens`、`prompt_cache_hit_tokens` | `prompt_tokens_details.cache_creation_input_tokens` | 直接用 |
| 原始 Anthropic 命名 `cache_*_input_tokens`（中转网关） | 不确定 | 同名 | 同名 | 有原生 `input_tokens` 时按排他加回；否则先按含缓存，违反不变式再加回 |
| Responses API | `input_tokens` 含缓存 | `input_tokens_details.cached_tokens` | `input_tokens_details.cache_creation_tokens` | 直接用 |

违反不变式时判定为排他口径：缓存数加回输入、重算 total，打点 `dsh_usage_contract_corrected{source}` 并告警。

### 4.5 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `llm/domain/pricing/catalog.py`、`catalog.json` | 价格表加载、校验、精确别名匹配 | 不去日期后缀；计费路径不读 |
| `llm/domain/pricing/service.py` | 保存时补价、来源判定、revision 比较交换 | 不直接写 ORM |
| `llm/domain/repositories/model_pricing_repository.py` | 不经缓存读价格；事务内加锁写价格 | 不新增 DAO 入口 |
| `llm/api/pricing.py` | 价格表、匹配、改价接口的参数与鉴权 | 不写业务逻辑 |
| `dsh/domain/schemas/pricing.py`、`services/pricing.py` | 快照、算价、倍率 | 不访问数据库 |
| `dsh/infrastructure/usage_contract.py` | 统一 token 口径 | 不算价 |
| `dsh/domain/repositories/credit_setting.py` | 积分设置读写、乐观锁、审计 | 不缓存 |
| `dsh/api/endpoints/credit_pricing.py` | 积分设置、价格摘要接口 | 不 import llm 模块 |
| `scripts/backfill_model_pricing.py` | 升级补价：预检 / `--apply` / `--check` 门禁 | 不在 Alembic revision 里改数据 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 网页入口的 `model_info` 来自 60 秒进程内缓存，只清本进程 | 改价在其他进程最多 60 秒后才生效，违反 AC-06 / AC-10 | 决策 15，`read_model_pricing` |
| 2 | 对账恢复在 `repositories/usage.py` 第 201 行内联了 `total × credit_rate` | 升级后对账失败，恢复被拒绝 | T10 改为由事件重算 |
| 3 | `update_llm_server` 用请求体整体替换模型 config | 老前端或其他保存入口把价格冲掉 | T03「没带就保留」+ revision |
| 4 | 新租户表必须登记到 `core/database/tenant_filter.py` 的 `_TENANT_AWARE_MODEL_MODULES` | 自动过滤、自动填充 tenant_id 失效，跨租户读写 | T05 |
| 5 | `UsageEvent` 禁止未知字段，已投影事件保留 ≥ 30 天 | 换回旧镜像后旧代码读不了事件 | 决策 18、runbook |
| 6 | 每次调用的事件 JSON 在 Redis 里有 5 份并保留 30 天，超水位拒绝新调用；默认 512 MB 只够每天约 2,970 次持续调用 | 快照加大会提前触发背压 | 决策 19、runbook 容量检查 |
| 7 | `langchain-anthropic` 分桶上报缓存写入时通用 `cache_creation` 为 0 | 缓存写入按输入价计，少扣 | §4.4、T12b |
| 8 | 回答溯源由 `asyncio.create_task` 在回答发出后执行 | 积分刚用完时溯源报错 | 决策 11 |
| 9 | `WSModel` 也是工作台配置存储结构 | 倍率被写进数据库 | 决策 9 |
| 10 | 老管理后台每次保存可见范围都带 `credit_multiplier: "1"`，入参 `extra="forbid"` | 删字段后老前端保存失败 | T17 保留入参并忽略 |
| 11 | `knowledge_space` 场景只有知识空间问答和看图默认值在用；`rag_traceability` 工作流也在用 | 整类放开会让工作流也扣费 | 决策 10 |
| 12 | 桌面模型名插槽是 single 类型，DeepSeek 官方插件占用优先级 0 | 同优先级注册直接抛错 | 决策 12 |
| 13 | 达梦 JSON 落 CLOB，往返后是字符串反序列化的字典 | 快照不可变比较误报冲突 | T10 规范化比较 |
| 14 | API 容器启动时自动执行 `alembic upgrade head`，失败拒绝启动 | 升级手册的迁移步骤可单独先跑 | runbook |
| 15 | 不限额员工 `/dsh/usage` 返回 int64 上限，桌面要求安全整数（读代码推断，未实测） | 账号页可能显示「用量暂不可用」 | 与本特性无关，单独提 |

---

## 6. 对外契约与依赖

### 6.1 提供给别人的

| 契约 | 形式 | 消费方 |
|---|---|---|
| `POST / PUT /api/v1/llm`：`models[].config.pricing` 可选；已有模型带价格时须带 revision | HTTP（扩展） | 管理后台 |
| `GET /api/v1/llm/price-catalog` | HTTP（新） | 管理后台 |
| `GET /api/v1/llm/price-catalog/match?server_type=&model_name=` → `{matched, via_name, catalog_version, entry}` | HTTP（新） | 管理后台 |
| `PUT /api/v1/llm/models/{model_id}/pricing`（带 revision；冲突返回 10813；Root 共享模型子租户 19801） | HTTP（新） | 管理后台 |
| `GET / PUT /api/v1/dsh/admin/credit-settings`（PUT 带 version，冲突 `DshOperationConflictError`） | HTTP（新） | 管理后台 |
| `GET /api/v1/dsh/admin/model-pricing` → `[{model_id, pricing, effective, edited, missing, hint}]` | HTTP（新） | 管理后台 |
| `GET /api/v1/workstation/config`：`models[].pricing_hint`（企业客户端开启时） | HTTP（扩展） | 网页工作台、桌面 Chat |
| `GET /api/v1/dsh/models`：`data[].pricing_hint` | HTTP（扩展） | 桌面 |
| `PUT /api/v1/dsh/admin/models/{id}/visibility`：`credit_multiplier` 仍接受、忽略 | HTTP（兼容） | 老管理后台 |
| 错误码 26176「模型价格未配置」；10813「模型价格修改冲突」 | 错误码（新，已登记 release-contract，实施前再核对） | 网页、桌面 |
| `chat_credits.unmetered()` | 内部 Python API | 回答溯源 |

### 6.2 依赖别人的

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F062 统一额度账本（admit / settle / pressure / cleanup Lua、投影、恢复） | 内部协议 | 本特性不改 Lua；事件格式变化须同时满足哈希兼容与恢复重算 |
| F118 提供方锁（`alock_provider`、`arequire_idle`） | 在途分支 | 合并顺序影响 T04 的锁实现 |
| `langchain-anthropic` 的 `usage_metadata` 结构 | 第三方库 | 升级库版本须重跑口径夹具 |
| 厂商用量字段（OpenAI、千问、DeepSeek、Anthropic、Responses） | 外部 API | 字段变化静默影响计价；违反不变式会打点 |
| Harness `conversation.input.model.label` 插槽 | 桌面上游 | 插槽类型或优先级规则变化 |
| `@bisheng/ui` Cascader | 共享组件库 | 需负责人认可 suffix / footer |

---

## 7. 测试与可观测

- **单元**：快照、算价、换算、倍率、口径映射用逐位算例；价格表匹配；保存补价与 revision。
- **集成（本机）**：sqlite + fakeredis 跑全部；另用 Docker MySQL 8 + Redis 7 跑 test/dsh 的 external 用例（`DSH_TEST_DATABASE_URL`、`DSH_TEST_REDIS_URL`、`DSH_TEST_REDIS_ISOLATED=1`），覆盖真实 SQL 与真实 Lua。
- **演练**：MySQL 迁移计时（本机）、达梦迁移计时（同事环境）、Redis 容量复测（本机），结果写入 validation.md。
- **联调**：测试服务器按 runbook 停服升级后逐条验收（tasks T32）。手动验证入口：管理后台「模型管理 → 添加模型 / 用户可选模型」「系统设置 → 企业客户端 → 积分」；网页工作台 `/workspace` 的模型下拉框、知识空间问答、频道问答；桌面开发版连接测试服务器。账号使用测试服务器的管理员与普通员工账号（凭据不写入文档）。
- **本机复现命令**：A 组 `cd src/backend && uv run pytest test/dsh test/llm test/database test/workstation test/channel test/common`；B 组另设 `DSH_TEST_DATABASE_URL`（库名以 `dsh_test_` 开头，预建 `user` 表）、`DSH_TEST_DATABASE_ISOLATED=1`、`DSH_TEST_REDIS_URL`、`DSH_TEST_REDIS_ISOLATED=1` 后跑 test/dsh 中使用真实库的文件。
- **可观测**：`dsh_usage_contract_corrected{source}` 打点与警告日志；升级脚本 `--check` 输出缺价清单；后台「价格缺失」「默认 0」标签。

---

## 8. 后续改进 / 不打算做的事

- 分时段 / 分档计价、Anthropic 1 小时缓存写入单独定价、价格表联网更新：本期只有单一写入价，服务端未设置 `cache_control`。
- 模型发现结果自动对应价格表：下一版。
- 删除旧公式与 `credit_rate` 列：升级满一个账期后。
- 额度 Redis 容量（默认配置约每天 2,970 次调用到顶）：与本特性无关，建议单独评估。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-11-12 | 初版 | 需求定稿 + 技术评审 v2.0 意见 |
