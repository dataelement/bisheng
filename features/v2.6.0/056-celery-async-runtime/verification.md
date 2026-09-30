# 验证报告 Verification：Celery 异步运行时单循环收敛

## 元信息

- Feature ID: `056-celery-async-runtime`
- Date: `2026-07-15`
- Result: `PASS_WITH_MANUAL_FOLLOW_UP`
- Scope: Celery bridge loop、文件编码 Transformer、知识空间迁移异步删除

## 验收矩阵

| Acceptance ID | 状态 | 验证证据 |
|---|---|---|
| AC-REQ-001-01 | PASS | `test_run_async_safe_uses_registered_worker_loop` 断言 bridge 协程运行在 Worker loop |
| AC-REQ-001-02 | PASS | loop-bound fake resource 经 `run_async_safe` 与 `run_async_task` 连续使用，loop ID 一致 |
| AC-REQ-001-03 | PASS | 16 次多线程提交全部进入单一 loop，结果与上下文隔离 |
| AC-REQ-002-01 | PASS | 并发 `ContextVar` 测试返回各调用线程的 tenant probe 值 |
| AC-REQ-002-02 | PASS | `LookupError("bridge failure")` 原类型、原消息传播给同步调用方 |
| AC-REQ-002-03 | PASS | 文件编码 bridge 异常保留 warning 与原 documents 返回语义，超时参数为 120 秒 |
| AC-REQ-002-04 | PASS | 既有 `test_async_utils.py` AnyIO、timeout 路径回归通过 |
| AC-REQ-003-01 | PASS | `get_worker_loop()` 注册 preferred bridge loop，并由 loop ID 测试证明 |
| AC-REQ-003-02 | PASS | shutdown 子进程测试断言调用 `set_preferred_bridge_loop(None)` |
| AC-REQ-003-03 | PASS | 文件编码模块专项测试与 source scan 均证明无私有 Runner、loop 和旧线程名 |
| AC-REQ-003-04 | PASS | 空间迁移测试断言 `run_async_safe(coro, timeout=None)`，source scan 无 `asyncio.run()` |
| AC-REQ-004-01 | PASS | diff review 未发现 API、task 签名、Redis key/TTL、schema、配置或解析结果契约变化 |
| AC-REQ-004-02 | PASS | 未注册 Worker loop 时，同一 loop-bound resource 连续调用复用同一 fallback loop |
| AC-REQ-004-03 | PASS | 仅 Python 代码、测试和 SDD 文档变更，无 Alembic 或数据迁移 |

## 自动化证据

在 `src/backend` 执行：

```bash
./.venv/bin/python -m pytest \
  test/celery \
  test/knowledge/test_file_encoding_async_bridge.py \
  test/knowledge/test_space_migrate_async_bridge.py \
  test/test_async_utils.py \
  test/test_file_encoding_transformer.py \
  test/test_space_migrate_worker.py -q
```

结果：`46 passed in 10.14s`。

以下检查通过：

- `ruff check --select F,I`：PASS。
- `ruff format --check`：8 files already formatted。
- `python -m compileall -q`：PASS。
- `scripts/arch-guard.sh`：PASS，退出码 0。
- 目标模块 source scan：无 `asyncio.run(`、私有 `new_event_loop(` 或 `shougang-encoding-async`。
- `git diff --check`：PASS。

完整 Ruff 检查为 FAIL，共 16 项，均位于本次修改前已存在的旧代码：中文全角标点检查、`typing.List`、dict comprehension 和旧 `noqa`。本 Feature 未扩大到这些静态债务；新增桥接代码的 F/I 与格式门禁已通过。

## 人工验证项

状态：`MANUAL_REQUIRED`。

未在当前工作区启动真实 Redis/MySQL/MinIO 和 Celery Worker，因为真实解析与空间迁移会写入数据库、Redis 和对象存储，且当前没有已确认的隔离测试数据与清理策略。

发布前在可控环境执行：

1. 使用 `-P threads -c 20` 启动知识队列 Worker。
2. 连续触发带文件编码的知识文件解析和相似度候选刷新。
3. 并发触发至少两份文件，确认 tenant/trace 日志不串扰。
4. 确认日志中无 `Future attached to a different loop`、`Event loop is closed`。
5. 触发一次知识空间迁移，确认源空间异步删除成功且失败回滚语义不变。

## 结论

所有可在无外部状态写入条件下验证的验收标准均已通过。真实中间件 Worker 冒烟是发布前运行环境验证项，不影响代码级验收结论，但未执行前不能宣称生产链路已完成端到端验证。
