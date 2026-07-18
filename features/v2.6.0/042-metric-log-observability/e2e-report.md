# E2E 覆盖报告: 042-metric-log-observability

**模式**: SDD（无 spec.md，AC 取自 design §1 四类指标目标）
**结论**: PASS（真链路集成 e2e + 方法级覆盖）

## 模式说明（为何不是标准 API/UI e2e）

F042 **无 HTTP 端点、无 UI 页面**（design §1 非目标：不建 /metrics、不引 Prometheus）。因此标准 e2e 框架（JWT 认证 / UnifiedResponseModel 断言 / 权限配对 / 多租户隔离 / UI 清单）**整体 N/A**——没有可驱动的 API/页面。

F042 的"端到端"= 驱动**真实集成代码路径**、断言 `BS_METRIC` 日志行真的产出且业务行为不变。

## 覆盖矩阵

| 目标(design §1) | e2e 方式 | 状态 | 证据 |
|---|---|---|---|
| ① DB 查询 P95/QPS/慢查询/连接池 | **真链路 e2e**：真 `DatabaseConnectionManager` + 真 SQLAlchemy engine + 真 cursor 事件 + 真配置（仅 SQLite 当 DB，F042 代码零 mock） | ✅ 通过 | `test/metric_log/test_e2e_metric_log.py`(3) |
| ② 存储成功率(排除401/403)/耗时 | 方法级：真 `MinioStorage` 方法 + 真装饰器/分类器（仅 mock 外部 minio client——本地无 minio） | ✅ 通过 | `test_storage_metric.py`(12) |
| ③ 模型 TTFT + 成功/失败 | 方法级：真 `upload_telemetry_log` 全路径（仅 mock ES/self——本地无 LLM） | ✅ 通过 | `test_model_metric.py`(3) |
| ④ E+ 站内信调用事件 | 方法级：真 `send_textcard`/`maybe_forward_external`（仅 mock httpx/UserDao——本地无 E+ 网关） | ✅ 通过 | `test_eplus_metric.py`(5) |

**真链路 e2e 断言要点**（DB 域）：
- 真 engine 执行 `SELECT 1` → 结果 `[(1,)]` 正确（埋点透明，不改查询语义）
- 产出 `db_query op=SELECT status=ok`，且 **SQL 原文不泄**（§5 坑 11）
- 产出 `db_query_agg`（含 `count`→QPS、累积 `le_*`→P95、`sum_ms`）
- **关开关验收**：`enabled=False` → 零 `BS_METRIC` 行，查询仍正常（"关掉开关行为与改前一致"）
- **域开关验收**：`db=False` → 只静默 DB 域

## 自动化测试结果

```
test/metric_log/  51 passed
  ├─ test_e2e_metric_log.py   3  (真链路 DB 集成 e2e)
  ├─ test_metric_log.py      21  (工具/直方图/sql_op)
  ├─ test_db_metric.py        9  (DB 记录/事件/pool/wait_timeout)
  ├─ test_storage_metric.py  12  (存储分类/叶子方法)
  ├─ test_model_metric.py     3  (模型 TTFT/status)
  └─ test_eplus_metric.py     5  (E+ ok/error/skipped)
回归: bisheng.main 导入干净 + 89 相关测试 + 7 s3error_thaw 全过
```

## 手动验证清单（真实部署，需 middleware）

标准 UI 清单 N/A。以下为**运维在真实环境**确认埋点落地的步骤（本地无 minio/LLM/E+ 网关，故列为手动）：

- [ ] 起后端，`db_slow_query_ms` 调小(如 1) → `grep 'BS_METRIC domain=db_query' <log>` 出现慢查询明细；等一个窗口 → `domain=db_query_agg` 出现（桶计数非零）
- [ ] MySQL/DM(QueuePool) 环境 → `grep 'BS_METRIC domain=db_pool'` 有 `checked_out/capacity/at_capacity`；压满连接池 → 出现 `result=wait_timeout`
- [ ] 上传/下载文件 → `domain=obj_storage op=put/get result=ok elapsed_ms=...`；构造 500/超时 → `result=error`；签证过期 → `result=excluded`
- [ ] 触发一次模型调用 → `domain=model_invoke ttft_ms=... status=success`，且与既有 ES telemetry 并存
- [ ] 触发一条 forwardable 站内信 → `domain=eplus_notify result=ok/error`；非 E+ 用户收件人 → `result=skipped`
- [ ] 监控层按 `docs/observability/metric-log-contract.md` 口径能算出 P95/QPS/成功率

## 整体状态: **PASS**
