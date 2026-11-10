# 昆联反向调用毕昇 Workflow 的运行控制验证

- **日期** 2026-11-10
- **范围** T001–T019，隔离候选 HTTP、SQLite 临时库、真实本地 Redis 队列和独立 Celery Worker。
- **状态** V-01、V-02 为 `PASS`。V-03、V-04 为 `NOT_RUN`，待执行。

## 按批次验证

| 批次 | 证据 | 覆盖 |
| --- | --- | --- |
| W1 · 取消与终态竞争 | 12 项通过。排队、等待和待恢复立即取消。执行中的取消先返回 `202`，确认后返回 `200`。取消和成功并发只提交一个终态。失败及已到期运行沿用原裁决。重复取消、事务回滚、旧答复查回和旧会话查询均通过。 | AC-01、AC-02、AC-03、AC-06、AC-08 |
| W2 · 执行边界与跨 Worker 补偿 | 6 项通过。同步、异步节点入口及恢复材料读取前拦截取消。等待点写入被拒绝后，原 Worker 确认取消。原 Worker 退出后，第二个 Worker 按原截止确认原会话取消，错误租户扫描、重复扫描和旧队列消息均无法推进执行。 | AC-01、AC-02、AC-06、AC-08 |
| W3 · 事件续读与权限 | 10 项通过。验证单条分页、重读、空页、游标超前、窗口裁剪与过期后从授权快照重新定位。验证不同租户、用户和接入方，以及撤权、停用、权限未知和独立投影。默认查询在结果授权期间到期的用例，修复前返回 `200`，修复后返回 `404` 且无结果。 | AC-04、AC-05、AC-06、AC-07、AC-08 |
| W4 · 完整链路与兼容回归 | 1 项新端到端用例及 76 项相邻回归通过。取消等待中的固定 V1 后断线续读至终态，异租户无权续读。另一次运行在发布 V2 后由另一 Worker 恢复 V1，保留原启动回执与答复回执，输出一次。 | AC-01、AC-02、AC-04、AC-05、AC-06、AC-07、AC-08 |

### 独立 Worker 证据

| 场景 | 实际结果 |
| --- | --- |
| 取消补偿 | Worker `44084` 在取消已受理时退出。Worker `44097` 处理原会话 `d6c3622558ca470dadf2813778e36a2f`，可控时钟达到原截止 `1060` 后确认取消。版本为 `1`，取消终态事件出现一次，输出次数为 `0`。 |
| 取消续读及固定版本恢复 | Worker `44137` 保存两个 V1 等待点后退出。会话 `783444539fe64ab1a118284a8d14016b` 取消后续读到受理和终态。发布 V2 后，Worker `44164` 在会话 `d818107ea1444d1d9e66484823695195` 恢复 V1，结果保留原 Worker 的起始变量和新答案。重复恢复消息无第二次输出。 |

## 执行命令与结果

从 `src/backend` 执行。使用现有 Python 3.11 虚拟环境、隔离后端配置和本地 Redis 7.2.17 可执行文件，分别传给 `BISHENG_TEST_PYTHON`、`BISHENG_TEST_CONFIG`、`F126_REDIS_SERVER`。测试夹具启动回环 Redis 和独立 Worker，并负责退出。

```sh
config="$BISHENG_TEST_CONFIG" PYTHONPATH="$PWD" F126_REDIS_SERVER="$F126_REDIS_SERVER" \
  "$BISHENG_TEST_PYTHON" -m pytest \
  test/workflow/test_kunlian_workflow_run_control*.py \
  test/workflow/test_kunlian_workflow_invocation.py \
  test/workflow/test_kunlian_workflow_interaction.py \
  test/workflow/test_kunlian_workflow_interaction_e2e.py \
  test/workflow/test_platform_agent_long_task_resume*.py \
  test/workflow/test_workflow_action_map.py test/tenant/test_tenant_filter.py \
  -q -s --disable-warnings --tb=short -rs
```

最终复验 `105 passed`，退出码 `0`，无跳过。相关文件 Ruff 格式、`F,E9` 检查、架构守卫和 Git 差异检查通过。候选接口、运行域、Worker 及新增测试通过完整 Ruff 检查。两个共享图文件的完整 Ruff 检查仍有 14 条既有告警，已与 `HEAD` 核对。

## 待执行

| 项目 | 状态 | 前置 |
| --- | --- | --- |
| T020、T021 正式契约和适配 | `WAITING_EXTERNAL` | 待双方确认身份委托、取消合同、事件续读和 OpenAPI 样例。替换点见 [设计](./design.md#run-control-contract)。 |
| V-03 受控基础设施验收 | `NOT_RUN` | 待 MySQL／DM8、OpenFGA、受控 Broker 和测试身份，核对行锁、真实权限及跨进程补偿。 |
| V-04 昆联真实联调 | `NOT_RUN` | 待正式契约、昆联测试租户和真实授权样例。 |

候选路由只在隔离应用装配。本轮使用现有运行表，无数据库迁移或部署。
