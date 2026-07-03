# Design: 结构化日志埋点 + 监控层解析(DB / 对象存储 / 模型调用 / E+ 站内信 指标)

> **本文档定位 — 现状快照（Why this How）**
>
> - `spec.md` 回答 **做什么**（目标、AC、边界）
> - `design.md`（本文）回答 **为什么这么实现**：关键决策、运行时不直观的事实、对外契约
> - `tasks.md` 是 **流水账**：拆了哪些任务、做了什么改动

**关联**: spec.md（N/A —— 本 feature 经 brainstorming 定案，目标/AC 见 §1，未单独出 spec；如需走 `/sdd-review spec` 可回填）· [tasks.md](./tasks.md)
**版本**: v2.6.0
**最后更新**: 2026-07-03（同步实现变更时一并更新）

---

## 1. 目标与非目标

- **目标**：为四类子系统埋结构化指标日志,由**外部监控层**（ELK / Loki / ES 等日志管线）采集并解析出指标。四类：
  1. **数据库**：查询耗时 P95、QPS、慢查询明细、连接池等待数
  2. **对象存储**：上传/下载请求成功率（排除 401/403 签证过期，只计超时/500/连接失败）、上传/下载耗时
  3. **模型调用**：TTFT（首 Token 延迟）、调用成功/失败
  4. **E+ 站内信**：接口调用事件（成功/失败/被短路、耗时）
- **非目标**：
  - **不**引入 `prometheus_client`、**不**建 `/metrics` 端点、**不**搭 Grafana——指标的聚合、存储、看板、告警**全部是监控层的职责**。本 feature 只负责"把每条原始测量打成契约化日志"。
  - **不**做进程内百分位计算（预算好的 P95 跨进程不可合并，见决策 2）。
  - **不**改动模型调用现有 ES telemetry 链路（仅并行补一行日志）。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C7（分层 / 双 DB / 多租户 / 错误码 / 安全）。
- **多进程部署**：FastAPI web 进程 + Celery workers + Linsight worker，各进程独立。大量 DB 查询 / 模型调用 / 文件存储发生在 worker 内，不只 web 进程。→ 采集方案必须对"多进程"透明。
- **DB 超高频**：每条 SQL 一行日志在高 QPS 下日志量不可接受（决策 3）。
- **双 DB**：达梦(DM) + MySQL。埋点走 SQLAlchemy 通用 event，不依赖具体方言。DM 的 `dmAsync` 假异步特性（内部同步阻塞事件循环）意味着埋点代码本身必须零阻塞。
- **对外数据格式依赖**：日志契约（字段名、marker）一旦发布即被监控层解析规则依赖，属对外契约，变更需通知监控团队（见 §6.1）。
- **不记录 SQL 原文 / bind 参数**（C6 泄密/PII + 大 IN 参数序列化开销，见 §5 坑 11）：`db_query` 只记语句类型 `op`（从 SQL 前缀取首个关键词 SELECT/INSERT/… 后即弃），绝不打完整 SQL 文本或参数值。

---

## 3. 方案对比与选定

### 决策 1：指标交付方式 —— 写日志 vs Prometheus /metrics vs ES telemetry

- **备选**：
  - A. **结构化日志 + 监控层解析**：各进程往日志打契约化行，日志管线采集解析。优点：零新依赖；对多进程天然透明（各写各的，采集端集中汇）；复用已有 `HTTP_ACCESS_METRIC` 先例。缺点：依赖外部日志管线具备解析/聚合能力；指标有采集延迟。
  - B. **Prometheus `/metrics` 进程内注册表**：`prometheus_client` + Histogram/Gauge/Counter。优点：业界标准、P95 由 `histogram_quantile` 算。缺点：多进程需 multiproc 模式（共享目录）；Celery/Linsight worker 非 HTTP 服务，暴露 `/metrics` 需额外端口或 Pushgateway，部署复杂；引入新依赖。
  - C. **复用现有 ES telemetry 事件流**：沿用 `telemetry_service→ES`。优点：模型调用已在用；跨进程天然。缺点：DB 超高频不能逐条写 ES；需进程内预聚合再落，反而更重。
- **选定**：A
- **原因**：用户所在企业环境已有日志管线；日志方案一次性绕开多进程 `/metrics` 聚合的全部复杂度；与代码库既有 `HTTP_ACCESS_METRIC` 埋点范式一致；本次不追求进程内暴露端点，只要监控层能从日志算出指标即可。
- **何时该重新考虑**：若未来要进程内实时暴露 `/metrics` 供 Prometheus 拉取（如无集中日志管线），改走 B（multiproc 模式）。

### 决策 2：打原始测量值，不打进程内算好的百分位

- **备选**：
  - A. **每事件打原始值**（elapsed_ms 等），P95 由监控层在汇总的原始/桶样本上算。
  - B. **进程内算好 P95 再打**：每进程每窗口打自己的 P95。
- **选定**：A
- **原因**：**预算好的百分位跨进程不可合并**——把各 worker 的 P95 再平均/取max 都是错的。原始样本（或直方图桶计数）可跨进程汇总成一个池子算真实全局 P95。这也正是"写日志、监控层聚合"分工的技术前提。
- **何时该重新考虑**：若某指标确定单进程产生（不存在），可例外。

### 决策 3：DB 指标拆两种日志行（慢查询明细 + 周期汇总）

- **备选**：
  - A. **全量**：每条 SQL 打一行。最准最简单，但高 QPS 下日志量爆炸。
  - B. **仅慢查询**（阈值可配）：只打超阈值的。日志量最小，但**算不出 QPS**（没有总数）也**算不出完整 P95**（只有尾部）。
  - C. **慢查询明细 + 周期汇总行**：慢查询逐条打（含 op / elapsed_ms，供排查）；另每进程每 N 秒打一行汇总，携带 `count`（→QPS）+ **延迟直方图桶计数**（→P95）。
- **选定**：C
- **原因**：用户明确要"能从日志算出 P95 和 QPS"，同时要求 DB 明细走慢查询阈值。纯 B 满足不了 QPS/P95；C 用一条极廉价的周期行补齐：桶计数**跨进程、跨窗口可直接相加**，监控层 sum 后 `histogram_quantile(0.95)` 得真实全局 P95，`count/window` 得 QPS，而进程内只是给几个整数计数器 +1、每 N 秒打一行，开销与日志量都极小。这本质是"用日志搬运 Prometheus histogram"。
- **何时该重新考虑**：若 DB QPS 很低且监控团队更想要逐条明细，可退回 A（全量），去掉汇总行。

### 决策 4：对象存储成功率口径 —— 排除 401/403 签证过期

- **备选**：
  - A. 所有非 2xx 都算失败。
  - B. **401/403（签证/权限过期）单列 `result=excluded`，不进失败分母**；只有超时 / 5xx / 连接失败算 `result=error`。
- **选定**：B（用户明确要求）
- **原因**：签证过期是预期内的客户端侧刷新场景，不代表存储服务不可用，计入失败率会污染 SLA。`http_status` 取 `S3Error.response.status`、`err_code` 取 `S3Error.code`，供监控层复核分类。
- **何时该重新考虑**：若出现新的"应排除"错误类别（如特定 NoSuchKey 业务预期），扩 `excluded` 判定集合。

### 决策 6：连接池"等待数"用饱和度反推,不直接计数

- **备选**：
  - A. **饱和度 Gauge + 等待超时计数**：周期采样 `pool.checkedout()/size()`（公开 API,非阻塞），`checked_out >= capacity` 即视为有请求在排队；并在 session 上下文捕获 `TimeoutError` 计"等不到连接"次数。
  - B. **精确排队数 / 等待时长**：模块级 `_waiters` 原子计数器 + `wait_ms`，子类化 `QueuePool._do_get` 注入。
- **选定**：A（档位 1）；B 列为后续（§8）。
- **原因**：SQLAlchemy **不提供**"当前排队数"的公开方法，`PoolEvents.checkout` 在**拿到连接之后**才触发、拿不到等待时长。A 全走公开 API、零框架侵入，已能回答"池是否打满 / 是否有请求在等 / 是否等超时"。B 要同步池 + 异步池（`AsyncAdaptedQueuePool`，协程等待）各注入一次，代价高，留待 A 不够用再上。
- **何时该重新考虑**：需要等待时长 P95 分布、或要精确到"此刻几个在排队"时，上 B。

### 决策 5：埋点收敛点选在"最细统一 choke point"

- **备选**：
  - A. **ASGI / 中间件层按请求埋**（类似现有 `HTTP_ACCESS_METRIC`）——优点：一处覆盖所有请求；缺点：拿不到子系统内部粒度（一个请求内多次 SQL/存储被压平），且 Celery/Linsight worker 无请求上下文、完全覆盖不到。
  - B. **每个调用点手动埋**——优点：灵活；缺点：调用点极多、必漏、维护灾难。
  - C. **各子系统最细统一边界埋**：
    - DB → SQLAlchemy engine 的 `before/after_cursor_execute`（cursor 级）+ pool 采样（双 DB 通用）。
    - 存储 → `MinioStorage` 的 `put_object* / get_object* / download_object_sync` 方法层切面（全仓都经 `get_minio_storage()` 拿实例）。
    - 模型 → `bisheng/llm/domain/utils.py` 4 个 wrapper 的 `finally`（TTFT / status 数据**已存在**）。
    - E+ → `CofcoEPlusClient.send_textcard` + `forwarder.maybe_forward_external` 的 skipped 分支。
- **选定**：C
- **原因**：这些是各子系统唯一无旁路的统一边界，一处埋点全覆盖、跨 web/worker 进程都生效，改动最小；A/B 分别栽在"粒度不足 + worker 盲区"和"必漏 + 难维护"。
- **何时该重新考虑**：若出现**绕过该边界**的调用路径（不经 engine 的裸 DBAPI 连接、不经 `get_minio_storage()` 直接 new minio client、旁路 wrapper 的模型调用），该路径不会被采集——需补埋或收敛回统一边界。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（埋点后）

```
业务代码
  ├─ SQL 执行  → engine before/after_cursor_execute → emit_metric(db_query 慢查询 / 计数器+1)
  │             └─ 每 N 秒 flush → emit_metric(db_query_agg 汇总行)
  │             └─ 每 N 秒采样 pool.checkedout()/checkedin() + 捕获 TimeoutError → emit_metric(db_pool)
  ├─ 文件读写  → MinioStorage.put/get 切面 → emit_metric(obj_storage)
  ├─ 模型调用  → llm wrapper finally    → emit_metric(model_invoke)  (与现有 ES telemetry 并行)
  └─ E+ 推送   → CofcoEPlusClient.send_textcard / forwarder skipped → emit_metric(eplus_notify)
                                    ↓
                        loguru logger 输出到 stdout/日志文件
                                    ↓
                    【监控层】采集 → 按 domain 解析 → 算 P95 / rate / success-ratio → 看板/告警
```

### 4.2 埋点锚点（现状代码位置）

| 域 | 文件:位置 | 现状 |
|---|---|---|
| DB engine / pool | `core/database/connection.py:133`(sync)/`:148`(async) engine property；pool 参数 `_get_default_engine_config():47-73` | 无任何 cursor event listener（需新增）；已有 tenant_filter 的 ORM 级 listener 在 `core/database/tenant_filter.py` |
| DB 配置 | `core/config/settings.py` `DatabasePoolConf:612-630` | 现有池配置范式，`MetricLogConf` 照此新增 |
| 对象存储 | `core/storage/minio/minio_storage.py` `put_object*`/`get_object*`/`download_object_sync`；实例入口 `minio_manager.py:get_minio_storage()` | 仅区分 `NoSuchKey`（`_is_no_such_key_error:32`）；`S3Error.code` / `.response.status` 可用但未消费；frozen S3Error 在存储边界已 thaw |
| 模型调用 | `llm/domain/utils.py` `TelemetryCallback.on_llm_new_token:169` + 4 wrapper finally；出口 `upload_telemetry_log:182` | **TTFT / status / is_stream 已采集**，已写 ES `MODEL_INVOKE`（`ModelInvokeEventData`）。仅需并行补一行日志 |
| E+ 站内信 | `notification/external/cofco_eplus_client.py:26 send_textcard`（成功 106 / 失败 112 / 异常 117）；`notification/forwarder.py:99 maybe_forward_external` skipped 分支 | 已有 `forward.result` 结构化日志（elapsed_ms/code/http_status），规整为契约即可 |

### 4.3 关键模块职责（新增）

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `common/services/metric_log.py`（新增） | `emit_metric(domain, **fields)`：统一格式化 + 转义 + marker + 用 loguru 打一行；内含 DB 直方图计数器与周期 flush | 不聚合成 P95（那是监控层）；不做 IO 阻塞 |
| `core/config/settings.py` `MetricLogConf`（新增） | 开关 + 阈值 + 窗口配置 | — |
| 4 处埋点接入 | 在各 choke point 调 `emit_metric` | 不改业务逻辑、不吞异常语义 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | **进程内算好的 P95 跨进程不可合并**（平均/取max 都错） | 多 worker 下 P95 完全失真 | 只打原始值/桶计数，聚合交监控层（决策 2） |
| 2 | 纯"仅慢查询"日志**算不出 QPS 也算不出完整 P95**（缺总数与百分位定位） | 以为选了 C 就万事大吉，结果监控层拿不到 QPS | DB 必须配周期汇总行 `db_query_agg`（决策 3） |
| 3 | 对象存储 401/403 是签证过期的**预期场景**，非服务故障 | 计入失败率污染 SLA、误告警 | `result=excluded` 单列，不进失败分母（决策 4） |
| 4 | DM `dmAsync` 是**假异步**（内部同步阻塞事件循环） | 埋点里任何同步 IO/锁竞争会放大成 worker 冻结 | `emit_metric` 必须零阻塞：只做内存计数 + 非阻塞日志，周期 flush 不加全局锁 |
| 5 | 模型调用 TTFT/status **已经在采集**（写 ES） | 重复造轮子、埋错地方 | 复用 `utils.py` 4 wrapper 的 finally，仅并行补日志行 |
| 6 | minio `S3Error` 是 frozen dataclass，逃逸存储层后重抛会掩盖真错 | 埋点若在存储层外读 `.__traceback__` 会崩 | 埋点在存储层**边界内**读 `.code`/`.response.status`（此时未逃逸） |
| 7 | SQLAlchemy `sessionmaker` 每次调用新建，只有 engine 是单例 | 若把计数器挂 session 会丢数据 | 计数器/直方图挂在 `metric_log` 模块级单例，按进程聚合 |
| 8 | SQLAlchemy **不提供**"当前排队等连接数"的公开 API，`PoolEvents` 也没有 checkout **之前**的事件（`checkout` 在拿到连接后才触发） | 想 `pool.waiting()` 直接拿等待数会发现没有，或误以为 `checkout` 事件能测等待时长 | 用饱和度反推（`checked_out >= capacity`）+ 捕获 `TimeoutError` 计等待超时；精确 `wait_ms` 需子类化 `QueuePool._do_get`（档位 2，后续） |
| 9 | 异步 engine 的池要从 `async_engine.sync_engine.pool` 取，不是 `async_engine.pool` | 直接取报错/拿错对象，池指标打空 | 采样处对 async 走 `sync_engine.pool`（`AsyncAdaptedQueuePool` 同样有 `checkedout/checkedin/size`） |
| 10 | `pool.overflow()` 语义随版本可能为负、不直观；`max_overflow` 无公开方法 | 用 `overflow()` 反推容量会算错 | 只用稳定的 `checkedout()/checkedin()/size()`；`max_overflow` 从 `DatabasePoolConf` 读，不读私有 `pool._max_overflow` |
| 11 | `db_query` 若打完整 SQL 文本 / bind 参数，会泄露密码等敏感值（C6）、PII，且大 `IN(...)` 参数序列化本身极慢（memory `dm-async-fake-blocks-loop-large-in`：3.6w 参数 11.9s） | 泄密 + 日志爆炸 + 埋点反而拖慢主流程 | 只从 SQL 前缀提取 `op`（首关键词）后立即丢弃 SQL 文本，永不记参数值 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）—— 日志契约（监控层解析依据）

统一 marker `BS_METRIC` + `domain=<域>` + logfmt 风格 `key=value`。字段字典：

**通用规则**：数值单位 `_ms` 为毫秒（float）；`status`/`result` 为枚举字符串；未知/缺省字段省略不打。

| domain | 触发 | 字段 |
|---|---|---|
| `db_query` | 单条 SQL 且 `elapsed_ms >= db_slow_query_ms`（慢查询明细） | `op`(SELECT/INSERT/UPDATE/DELETE/OTHER) `elapsed_ms` `status`(ok/error) |
| `db_query_agg` | 每进程每 `db_agg_window_s` 秒 | `window_s` `count`(窗口内总查询数→QPS) `sum_ms` `le_5 le_10 le_25 le_50 le_100 le_250 le_500 le_1000 le_inf`(累积/分桶计数→P95) |
| `db_pool` | 每进程每 `db_agg_window_s` 秒周期采样（由查询事件驱动）+ 池等待超时时 | `engine`(sync/async) `checked_out`(使用中) `idle`(空闲) `size`(pool_size) `capacity`(size+max_overflow) `at_capacity`(0/1) `result`(可选=wait_timeout) |
| `obj_storage` | 每次 put/get 完成 | `op`(put/get) `result`(ok/error/excluded) `http_status` `err_code` `elapsed_ms` |
| `model_invoke` | 每次模型调用结束（finally） | `model_id` `status`(success/failed) `is_stream`(0/1) `ttft_ms`(首 token) `total_ms` |
| `eplus_notify` | 每次 E+ 接口调用 / 被短路 | `result`(ok/error/skipped) `http_status` `biz_code` `elapsed_ms` `action` |

示例行：
```
BS_METRIC domain=db_query op=SELECT elapsed_ms=253.1 status=ok
BS_METRIC domain=db_query_agg window_s=10 count=8421 sum_ms=41230 le_5=6100 le_10=1200 le_25=700 le_50=250 le_100=110 le_250=48 le_500=10 le_1000=2 le_inf=0
BS_METRIC domain=db_pool engine=async checked_out=37 idle=63 size=100 capacity=120 at_capacity=0
BS_METRIC domain=obj_storage op=put result=ok http_status=200 elapsed_ms=45.2
BS_METRIC domain=obj_storage op=get result=error http_status=500 err_code=InternalError elapsed_ms=1203.4
BS_METRIC domain=model_invoke model_id=123 status=success is_stream=1 ttft_ms=340.0 total_ms=5200.0
BS_METRIC domain=eplus_notify result=ok http_status=200 biz_code=0 elapsed_ms=88.0 action=knowledge_join
```

**监控层如何算（示例口径，供监控团队参考）**：
- **DB QPS** = `sum(db_query_agg.count) / 窗口跨度`（跨进程直接加）。
- **DB P95** = 对 `db_query_agg` 的 `le_*` 桶跨进程/跨窗口求和后 `histogram_quantile(0.95)`。
- **存储成功率** = `count(result=ok) / (count(result=ok) + count(result=error))`；`result=excluded` 不进分母。
- **存储耗时 P95** = 对 `obj_storage.elapsed_ms` 原始样本按 op 分组算分位。
- **模型 TTFT P95** = 对 `model_invoke.ttft_ms` 原始样本算分位；成功率 = `status=success` 占比。
- **E+ 调用事件** = 按 `result` 分组计数（ok/error/skipped）+ `elapsed_ms` 分位。

> **契约变更约束**：新增字段向后兼容可直接加；重命名/删除字段或改 marker 属破坏性变更，必须通知监控团队同步解析规则。

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| loguru logger 输出被日志管线采集 | 部署约定 | 若日志被丢弃/未采集，指标静默缺失 |
| `S3Error.response.status` / `.code` 字段存在 | minio SDK 隐式契约 | SDK 升级若改字段，存储 http_status 打空 |
| SQLAlchemy `engine.pool.status()` / checkout 事件 | SQLAlchemy API | 版本升级需复核 pool 事件签名 |
| 监控层具备日志解析 + 直方图分位聚合能力 | 外部系统能力 | 若监控层不支持桶聚合，DB P95 拿不到（需退回原始样本方案 A） |

---

## 7. 测试与可观测

- **单元**：`emit_metric` 格式化/转义/字段省略；DB 直方图桶归类与周期 flush 计数正确性；存储 result 分类（ok/error/excluded 的 401/403 边界）；op 从 SQL 前缀解析。
- **集成**：真实跑一条慢 SQL 断言 `db_query` 行；连续查询后断言 `db_query_agg` 桶计数与 count；put/get 一次断言 `obj_storage` 行；mock 401/403 断言 `excluded`。
- **手动验证**：本地起后端（`cd src/backend && uv run uvicorn bisheng.main:app`），制造流量后 grep 日志——`grep 'BS_METRIC domain=' <stdout / 日志文件>`。分域确认：`domain=db_query_agg`（每 `db_agg_window_s` 秒一行、桶计数非零→QPS/P95）、`domain=db_pool`（采样字段齐）、上传/下载文件看 `domain=obj_storage`、跑一次模型调用看 `domain=model_invoke`（与既有 ES telemetry 并存）、触发一次站内信看 `domain=eplus_notify`。把 `db_slow_query_ms` 调小（如 1）可强制产出 `db_query` 慢查询明细行。
- **可观测**：本 feature 产出的就是可观测数据；自身健康度看 `emit_metric` 是否有异常吞没（应有兜底 try/except，埋点绝不影响业务主流程）。

---

## 8. 后续改进 / 不打算做的事

- 暂不做：进程内 `/metrics` 端点、Grafana 看板、告警规则（监控层职责）。
- 暂不做：存储/模型也走"周期直方图汇总"（当前它们是低中频，原始样本足够；若未来 QPS 上升到日志量成问题，再照 DB 的 `*_agg` 模式扩展）。
- 暂不做：连接池**精确等待时长** `wait_ms` 全分布 / "此刻几个在排队"精确计数（档位 2，需子类化 `QueuePool._do_get`，同步+异步各一次）。当前用饱和度 Gauge（`checked_out`/`capacity`/`at_capacity`）+ 等待超时计数（档位 1）反推"是否在排队"，足够；档位 1 不够用时再上档位 2。
- 触发重写：若企业无集中日志管线、要求进程内暴露指标端点 → 迁移到决策 1 的方案 B（Prometheus multiproc）。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-07-03 | 初版设计（brainstorming 定案：日志方案 + 契约 + DB 双行 + 存储口径 + 配置项） | 需求评审 |
| 2026-07-03 | 连接池澄清回填（§3 决策 6、§5 坑 8-10、§6.1 db_pool 契约由 waiters 改饱和度 Gauge） | 用户追问 checkout 语义 |
| 2026-07-03 | /sdd-review design 过审：决策 5 补备选/触发条件、显式声明不记 SQL 原文（§2 + 坑 11）、§7 补具体命令、spec 标 N/A | Constitution Check PASS |
