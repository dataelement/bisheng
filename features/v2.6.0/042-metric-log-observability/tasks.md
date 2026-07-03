# Tasks: 结构化日志埋点 + 监控层解析(DB / 对象存储 / 模型调用 / E+ 站内信 指标)

**关联规格**: [design.md](./design.md)（本 feature 经 brainstorming 定案，目标/AC 见 design §1，未单独出 spec.md；如需走 `/sdd-review spec` 可回填）
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| design.md | ✅ 已评审 | /sdd-review design 过审（Constitution Check PASS，2 medium+1 low 已修）；接手第一入口 |
| tasks.md | ✅ 已拆解 | /sdd-review tasks 过审（21 项，1 medium+2 low 已修） |
| 实现 | 🚧 进行中 | 3 / 12 完成（Wave 1 ✅）。偏差处理见 design.md 顶部调整原则 |

---

## 开发模式

- **后端 Test-First（务实版）**：先写测试（红）→ 实现（绿）。首个测试任务一并搭 pytest 基础设施（若缺）。
- **纯后端 feature**：无前端、无新 HTTP 端点、无 DAO/ORM/错误码——不引入 prometheus 端点（design §1 非目标）。
- **自包含任务**：文件/逻辑/覆盖内联；设计论证指向 design §X 不复制。
- 测试放 `test/metric_log/`（新目录），`asyncio_mode=auto`。中间件/DM8/e2e 在 CI 跑。
- **⚠️ 共享基础设施文件**：T005/T007/T009/T011 改的是全仓公用的 DB/存储/LLM/E+ 边界文件——埋点一律 **additive + 异常隔离**（design §5 坑 4：`emit_metric` 整体 try/except 兜底、零阻塞），**不改任何原有控制流 / 返回值 / 异常语义**。影响范围 = 全仓所有 DB 查询 / 文件读写 / 模型调用 / E+ 推送，故每个此类任务验收都含「关掉 `MetricLogConf` 对应开关后，行为与改动前完全一致」。
- **Worker 上下文**：埋点代码在 Celery/Linsight worker 内也会执行，`metric_log` **不得依赖** request/tenant ContextVar（worker 无请求上下文），只做进程级内存计数 + 打日志。
- **AC 标注**：本 feature 无 spec.md，测试任务用「覆盖: <指标域>」对应 design §1 的四类指标目标（DB / 对象存储 / 模型 / E+），等价于 AC 追溯。

---

## Tasks

### Wave 1 — 核心工具与配置（基础设施）

- [x] **T001**: `MetricLogConf` 配置项
  **文件**: `src/backend/bisheng/core/config/settings.py`
  **逻辑**: 参照 `DatabasePoolConf`(:612) 新增 `class MetricLogConf`，字段：`enabled`(总开关，默认 True) + 各 domain 开关(`db`/`obj_storage`/`model_invoke`/`eplus`，默认 True) + `db_slow_query_ms`(慢查询阈值，默认 200) + `db_agg_window_s`(汇总/池采样窗口，默认 10)。挂到全局 `Settings`（`metric_log: MetricLogConf`）。
  **覆盖**: design §3 决策 3、§6.1 配置约束
  **依赖**: 无

- [x] **T002**: `metric_log` 工具单元测试
  **文件**: `src/backend/test/metric_log/test_metric_log.py`（+ 本目录 `conftest.py` 若缺）
  **逻辑**: 测 `emit_metric`：marker 前缀固定、logfmt `key=value` 转义（含空格/引号/换行安全）、缺省字段省略、总开关/domain 开关关闭时不打；测 DB 直方图：`record_query(elapsed_ms)` 桶归类正确、`flush()` 产出 `count/sum_ms/le_*` 且跨窗口清零；测 pool 采样格式化。
  **覆盖**: design §6.1 契约、§5 坑 7（模块级单例计数器）
  **依赖**: T001

- [x] **T003**: `metric_log.py` 实现
  **文件**: `src/backend/bisheng/common/services/metric_log.py`
  **逻辑**: `emit_metric(domain, **fields)`（格式化 + 转义 + loguru 打一行，**整体 try/except 兜底，埋点绝不影响业务主流程**——design §5 坑 4 零阻塞）；模块级 `_DbQueryHistogram`（原子计数 `record_query` + 周期 `maybe_flush(now)` 产 `db_query_agg`）；`maybe_emit_pool_gauge(now, pools)`（读 `checkedout/checkedin/size`，容量 = size + `settings.database_pool.max_overflow`，异步池走 `sync_engine.pool`——design §5 坑 9/10）。
  **测试**: T002 全通过
  **覆盖**: design §3 决策 2/3、§4.3
  **依赖**: T001, T002

### Wave 2 — 四类埋点接入（均依赖 T003，四组彼此独立、可并行）

- [ ] **T004**: DB 埋点单元测试
  **文件**: `src/backend/test/metric_log/test_db_metric.py`
  **逻辑**: 注册 listener 后跑真实 SQL（SQLite in-memory）断言：慢查询（超阈值）产 `db_query` 行且 `op` 解析对（SELECT/INSERT/...）、快查询不产明细但计入直方图；连续查询后触发 `db_query_agg` 桶与 count；`db_pool` 采样字段齐全；session 上下文捕获 `sqlalchemy.exc.TimeoutError` → `db_pool result=wait_timeout`。
  **覆盖**: DB P95/QPS/慢查询/连接池等待（design §3 决策 3/6）
  **依赖**: T003

- [ ] **T005**: DB 埋点接入
  **文件**: `src/backend/bisheng/core/database/connection.py`（engine 创建 :133/:148），`src/backend/bisheng/core/database/manager.py`（session 上下文 :163/:179）
  **逻辑**: 在 sync+async engine 上 `event.listen(before_cursor_execute)` 记 start、`after_cursor_execute` 算 elapsed → 慢查询打 `db_query` + `histogram.record_query` + `maybe_flush` + `maybe_emit_pool_gauge`（同一时间窗驱动，design §4.1）；在 `get_sync/async_db_session` 包 `except TimeoutError` 打 `db_pool result=wait_timeout` 再重抛。**受 `MetricLogConf.db` 开关控制**；**共享文件 additive + 异常隔离，不改原有 session/查询控制流（见 开发模式）**。
  **测试**: T004 全通过
  **覆盖**: design §3 决策 5/6、§5 坑 4/7/9/10
  **依赖**: T003, T004

- [ ] **T006**: 对象存储埋点单元测试
  **文件**: `src/backend/test/metric_log/test_storage_metric.py`
  **逻辑**: mock minio client，断言 put/get 成功打 `obj_storage result=ok http_status=200`；抛 500/超时/连接错 → `result=error` 带 `err_code`/`http_status`；**401/403 → `result=excluded`（不进失败分母，design §3 决策 4）**；`elapsed_ms` 存在。
  **覆盖**: 存储成功率（排除 401/403）+ 上传/下载耗时
  **依赖**: T003

- [ ] **T007**: 对象存储埋点接入
  **文件**: `src/backend/bisheng/core/storage/minio/minio_storage.py`（`put_object*`/`get_object*`/`download_object_sync` 方法层）
  **逻辑**: 统一切面（装饰器或内部 helper）包裹上传/下载：计时 + 分类 result（`http_status` 取 `S3Error.response.status`、`err_code` 取 `S3Error.code`；401/403→excluded；NoSuchKey 归 ok 语义业务侧，不算 error）→ `emit_metric(obj_storage, op=put/get, ...)`。**在存储层边界内读 S3Error 字段（design §5 坑 6，避免逃逸后 frozen 崩）**。受 `MetricLogConf.obj_storage` 开关控制。
  **测试**: T006 全通过
  **覆盖**: design §3 决策 4/5、§5 坑 6
  **依赖**: T003, T006

- [ ] **T008**: 模型调用埋点单元测试
  **文件**: `src/backend/test/metric_log/test_model_metric.py`
  **逻辑**: mock 一次流式/非流式模型调用，断言 finally 产 `model_invoke` 行含 `ttft_ms`(首 token)/`status`(success/failed)/`is_stream`/`total_ms`/`model_id`；失败路径 `status=failed`。
  **覆盖**: TTFT + 调用成功/失败
  **依赖**: T003

- [ ] **T009**: 模型调用埋点接入
  **文件**: `src/backend/bisheng/llm/domain/utils.py`（4 个 wrapper 的 finally + `TelemetryCallback`）
  **逻辑**: 在现有 `upload_telemetry_log`（:182）同一 finally 处**并行补一行** `emit_metric(model_invoke, ...)`，复用已采集的 `first_token_cost_time`/`status`/`is_stream`（design §5 坑 5，不重复造轮子、不动 ES 链路）。受 `MetricLogConf.model_invoke` 开关控制。
  **测试**: T008 全通过
  **覆盖**: design §3 决策 5、§5 坑 5
  **依赖**: T003, T008

- [ ] **T010**: E+ 站内信埋点单元测试
  **文件**: `src/backend/test/metric_log/test_eplus_metric.py`
  **逻辑**: mock httpx，断言 `send_textcard` 成功打 `eplus_notify result=ok biz_code/http_status/elapsed_ms/action`；失败/异常 → `result=error`；`maybe_forward_external` 各短路分支 → `result=skipped`。
  **覆盖**: E+ 站内信接口调用事件
  **依赖**: T003

- [ ] **T011**: E+ 站内信埋点接入
  **文件**: `src/backend/bisheng/notification/external/cofco_eplus_client.py`（`send_textcard`），`src/backend/bisheng/notification/forwarder.py`（`maybe_forward_external` skipped 分支）
  **逻辑**: 把现有 `forward.result` 结构化日志规整为 `emit_metric(eplus_notify, ...)` 契约（ok/error + biz_code/http_status/elapsed_ms/action）；skipped 分支补 `result=skipped`。保持 fire-and-forget、不改吞异常语义。受 `MetricLogConf.eplus` 开关控制。
  **测试**: T010 全通过
  **覆盖**: design §3 决策 5、§4.2
  **依赖**: T003, T010

### Wave 3 — 监控层契约文档

- [ ] **T012**: 监控层解析契约文档
  **文件**: `docs/observability/metric-log-contract.md`（新增）
  **逻辑**: 从 design §6.1 提炼给监控团队：`BS_METRIC domain=*` 字段字典 + 每类指标算法口径 + Loki LogQL / ES 查询示例（DB QPS=Σcount/窗口、DB P95=Σle_* 桶后 histogram_quantile、存储成功率排除 excluded、TTFT P95、E+ 事件计数、pool 饱和度告警 `at_capacity`/`wait_timeout`）。标注契约变更约束（新增字段兼容、重命名/删字段/改 marker 需通知监控团队）。
  **覆盖**: design §6.1
  **依赖**: T005, T007, T009, T011（字段最终定型后落文档）

---

## 实际偏差记录

> 只留一行指针，论证在 design.md（决策/坑），这里不重复。

- T003 实现细节：直方图类取名 `DbQueryHistogram`（公开，便于单测）+ 模块级单例 `db_histogram`；方法签名为 `record(elapsed_ms, now)` / `maybe_flush(now, window_s)`，`maybe_emit_pool_gauge(now, pools, window_s)` —— `now`/`window_s` 均由调用方传入（本模块不读时钟，保证窗口可确定性测试）。另新增 `sql_op(statement)`（只取首关键词）。纯实现细节，不改 design 决策。
