# BiSheng 指标日志契约（BS_METRIC）

> 给**监控团队**的解析依据。后端各进程（web / Celery / Linsight worker）向标准日志输出结构化行，marker 为 `BS_METRIC`，由日志管线（ELK / Loki / ES）采集并聚合成指标。后端**只打原始测量**；P95 / QPS / 成功率等聚合全部在监控层完成。
>
> 设计与埋点位置见 `features/v2.6.0/042-metric-log-observability/design.md`（F042）。

## 行格式

统一 marker + `domain` + logfmt `key=value`：

```
BS_METRIC domain=<域> key=value key=value ...
```

- 数值字段 `*_ms` 为毫秒；`bool` 渲染为 `1`/`0`；含空格/引号的字符串值加双引号并转义。
- `None` 字段省略不打（解析时按缺省处理）。
- 采集正则建议锚 `BS_METRIC domain=`；用 `domain=` 的**精确 token**（后接空格或行尾）分流，避免 `db_query` 误匹配 `db_query_agg`。

## 字段字典

| domain | 触发时机 | 字段 |
|---|---|---|
| `db_query` | 单条 SQL 且 `elapsed_ms >= db_slow_query_ms`（慢查询明细）；失败查询也打 | `op`(SELECT/INSERT/UPDATE/DELETE/OTHER) `elapsed_ms` `status`(ok/error) |
| `db_query_agg` | 每进程每 `db_agg_window_s` 秒 | `window_s` `count` `sum_ms` `le_5 le_10 le_25 le_50 le_100 le_250 le_500 le_1000 le_inf`（**累积**桶计数，单位 ms） |
| `db_pool` | 周期采样（由查询驱动）；池等待超时时 | `engine`(sync/async) `checked_out` `idle` `size` `capacity` `at_capacity`(0/1) `result`(可选=wait_timeout) |
| `obj_storage` | 每次上传/下载完成 | `op`(put/get) `result`(ok/error/excluded) `http_status` `err_code` `elapsed_ms` |
| `model_invoke` | 每次模型调用结束 | `model_id` `status`(success/failed) `is_stream`(0/1) `ttft_ms` `total_ms` |
| `eplus_notify` | E+ 每次真实调用（ok/error）；forwarder 过白名单后的收件人 skip（skipped） | `result`(ok/error/skipped) `http_status` `biz_code` `err_code` `elapsed_ms` `action` `reason`(skipped 时) |

### 示例行

```
BS_METRIC domain=db_query op=SELECT elapsed_ms=253.1 status=ok
BS_METRIC domain=db_query_agg window_s=10 count=8421 sum_ms=41230 le_5=6100 le_10=7300 le_25=8000 le_50=8250 le_100=8360 le_250=8408 le_500=8418 le_1000=8420 le_inf=8421
BS_METRIC domain=db_pool engine=async checked_out=37 idle=63 size=100 capacity=120 at_capacity=0
BS_METRIC domain=obj_storage op=put result=ok http_status=200 elapsed_ms=45.2
BS_METRIC domain=obj_storage op=get result=error http_status=500 err_code=InternalError elapsed_ms=1203.4
BS_METRIC domain=model_invoke model_id=123 status=success is_stream=1 ttft_ms=340.0 total_ms=5200.0
BS_METRIC domain=eplus_notify result=ok http_status=200 biz_code=0 elapsed_ms=88 action=request_channel
```

> **`le_*` 是累积桶**（Prometheus histogram 语义）：`le_10` 含 `le_5`，`le_inf == count`。累积桶跨进程、跨窗口可直接相加，聚合后用 `histogram_quantile` 得真实全局 P95。

## 指标算法口径

设采集周期内某窗口跨所有进程汇总。

- **DB QPS** = `sum(db_query_agg.count) / 时间跨度秒`。
- **DB 查询耗时 P95** = 对 `db_query_agg` 各 `le_*` 桶**按进程/窗口求和**后 `histogram_quantile(0.95, buckets)`。P50/P99 同理。
- **DB 慢查询 TopN / 错误率** = `db_query` 明细行按 `op` 分组；错误率 = `count(status=error) / count(*)`。
- **连接池饱和度** = `db_pool.checked_out / capacity`；**排队告警** = `at_capacity==1` 持续 N 个采样，或出现 `db_pool result=wait_timeout`（池已耗尽、等待超时）。
- **存储成功率** = `count(result=ok) / (count(result=ok) + count(result=error))`，按 `op`(put/get) 分。**`result=excluded` 不进分母**（401/403 签证过期）。
- **存储耗时** = 对 `obj_storage.elapsed_ms` 原始样本按 `op` 分组算分位。
- **模型 TTFT P95** = 对 `model_invoke.ttft_ms` 原始样本算分位；**调用成功率** = `count(status=success) / count(*)`。
- **E+ 调用事件** = `eplus_notify` 按 `result`(ok/error/skipped) 分组计数；`elapsed_ms` 分位；错误细分看 `biz_code` / `err_code`。

## 查询示例

### Loki (LogQL)

DB QPS（5 分钟速率）：
```logql
sum(rate({app="bisheng"} |= "BS_METRIC domain=db_query_agg" | logfmt | unwrap count [5m]))
```

存储成功率（put，排除 excluded）：
```logql
sum(count_over_time({app="bisheng"} |= "BS_METRIC domain=obj_storage" | logfmt | op="put" | result="ok" [5m]))
/
sum(count_over_time({app="bisheng"} |= "BS_METRIC domain=obj_storage" | logfmt | op="put" | result=~"ok|error" [5m]))
```

模型 TTFT P95：
```logql
quantile_over_time(0.95, {app="bisheng"} |= "BS_METRIC domain=model_invoke" | logfmt | unwrap ttft_ms [5m])
```

> DB 查询 P95 需对 `le_*` 桶跨进程求和再做 histogram_quantile；若管线支持，把 `db_query_agg` 的桶转成 Prometheus histogram 系列（每个 `le_x` 一条）后用 `histogram_quantile(0.95, sum by (le)(...))`。

### ES（聚合思路）

- 用 ingest/grok 把 `BS_METRIC domain=... k=v` 解析成结构化字段（`domain`、`op`、`result`、`elapsed_ms`…）。
- 成功率：`filter result:ok / (result:ok OR result:error)`；耗时分位：`percentiles` agg on `elapsed_ms`。
- DB P95：对 `db_query_agg` 的 `le_*` 求 `sum` agg 后在可视化层做 histogram_quantile（或转 Prometheus remote-write）。

## 后端开关（运维）

`config.yaml` 的 `metric_log` 段（默认全开）：

| 键 | 默认 | 说明 |
|---|---|---|
| `enabled` | true | 总开关，关闭后不打任何 `BS_METRIC` |
| `db` / `obj_storage` / `model_invoke` / `eplus` | true | 各域独立开关 |
| `db_slow_query_ms` | 200 | 慢查询明细阈值（ms）；调小可看到更多 `db_query` 明细 |
| `db_agg_window_s` | 10 | `db_query_agg` 汇总 + `db_pool` 采样窗口（秒） |

## 契约变更约束

- **新增字段**：向后兼容，可直接加。
- **重命名 / 删除字段、改 `domain`、改 marker `BS_METRIC`**：破坏性变更，**必须通知监控团队**同步解析/告警规则。
- 字段单位固定：`*_ms` 恒为毫秒；`le_*` 桶恒为累积计数。
