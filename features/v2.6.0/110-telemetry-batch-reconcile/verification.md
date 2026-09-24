# 验证记录

Date: 2026-09-22
Overall: LOCALLY_VERIFIED / production MANUAL_REQUIRED
Code State: 当前未提交工作区；E-001 至 E-003 验证批处理实现，随后仅调整三个默认调度表达式，补充 E-004 定向验证。

## E-001 相关模块回归

在 `src/backend` 使用现有 Python 3.10.19 环境执行：

```bash
.venv/bin/python -m pytest test/telemetry test/test_realtime_dashboard.py test/test_knowledge_space_content_telemetry.py test/test_rebuild_knowledge_space_content_stat.py test/telemetry_search/test_login_participation.py test/user/test_user_repository_external_id.py test/user/test_user_primary_department_contract.py -q --disable-warnings
```

结果：**150 passed, 6 warnings in 3.78s**，退出码 0；另有已有 swig 类型弃用提示。

| 验收 | 状态 | 可观察证据 |
|---|---|---|
| AC-1 复用查询 | PASS | 1001 人、两天补算只扫描一轮名单；部门批次 1000＋1；目标批次 1000＋1000＋2；同一登录记录一次生成，第二次零写入 |
| AC-2 差异/部分失败 | PASS | 未变零写入；ES 部分 bulk 成功项已 ACK；失败项独立重试；原始事件/计数查询/日统计三种部分失败均验证 |
| AC-3 并发与快照 | PASS | 实时登录字段和 event_time 部门保留；更新/清理均用 CAS；原始事件重放不覆盖旧快照；读取失败不当缺失 |
| AC-4 重试上限 | PASS | fakeredis + Lua 实际执行原子脚本，6 次执行后停止；新任务实例、Beat、租约回收、普通入队、全量文件对账均不能复活 dead；迟到 ACK 不清预算 |
| AC-5 恢复 | PASS | 固定失败窗口和原参数；崩溃后 owner 隔离；恢复器补发到期任务且不补发 dead；检查工具默认只读、apply 单项恢复 |
| AC-6 回归 | PASS | 上述 150 项覆盖参与率、共享索引、问答契约、内容统计、事件、维度、触发器、手工重建脚本和用户 Repository |

SQLite 验证批量用户加载：100 人及三类关联维度共 4 次 SELECT，Session 关闭后维度可用，避免逐用户查询。

## E-002 真实 Celery 离线执行

执行 `/tmp/verify_telemetry_integrations.py`，使用真实 Celery、内存 broker/backend 和 fakeredis，不访问外部服务。真实 task 包装连续 6 次失败后，第 7 次返回 `retry_state=dead`，业务函数不执行。检查已安装 ES 客户端确实支持本次使用的 `msearch(searches=...)` 和 `bulk(operations=...)` 参数。

结果：PASS，退出码 0。日志：`/tmp/telemetry_integrations_20260922.log`。

## E-003 静态与结构

- 新文件 Ruff 全检查通过。
- 修改的既有生产文件与 HEAD 完整 Ruff 诊断对比：0 条新增问题；未顺手修复既有格式/Optional 诊断。
- `git diff --check` 通过。
- architecture guard 与 HEAD 对比：0 条新增违规；common telemetry 对用户 Repository 的既有依赖未增加新的跨层导入。
- Python 语法编译通过。

## E-004 调度降频与错峰

2026-09-22 按用户确认修改三个默认调度表达式；历史补算、分钟恢复和实时入口保持不变。

- 使用 `.venv/bin/python` 实际实例化 `CeleryConf`，断言五项任务的分钟、小时及每日范围、历史补算两天参数，并逐项验证五个同名自定义调度仍优先；PASS。
- 验证人员和问答两个定时对账合计每天 96 次；PASS。
- `.venv/bin/python -m pytest test/celery/test_knowledge_parse_queue_routing.py -q --disable-warnings`：**35 passed in 2.94s**，退出码 0。
- `git diff --check`：PASS。未启动 Beat 或派发任务；线上生效需部署并重新加载 Beat，核对同名自定义覆盖。

## 未执行与限制

- MANUAL_REQUIRED：真实 ES 的 Painless、CAS、refresh/msearch 可见性；测试采用协议 fake，不能证明真实服务行为。
- MANUAL_REQUIRED：Redis Cluster、真实 broker 投递/Worker 进程退出、Redis 持久化策略；Lua 逻辑和真实 Celery 包装已离线执行。
- MANUAL_REQUIRED：MySQL/DM8 集成；SQL 查询采用现有 ORM 与 selectinload，SQLite 已验证批量加载。
- 未部署、未派发线上任务、未运行状态重置/重放脚本。运行说明见 operations.md。
- 保留原统计口径及全量/增量共享锁。减少重复写入不等同于减少所有查询：目标 ES 对账和安全清理仍需要读取。
