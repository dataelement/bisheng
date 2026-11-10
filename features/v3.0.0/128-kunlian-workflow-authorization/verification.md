# 昆联 Workflow 授权管理验证记录

- **日期** 2026-11-10
- **范围** F128 T001–T014，本地隔离候选 HTTP、权限夹具和既有 Workflow 入口。
- **状态** V-01、V-02 为 `PASS`。V-03、V-04 为 `NOT_RUN`，待执行。

## 批次证据

| 证据 | 验证结果 | 覆盖 |
| --- | --- | --- |
| E-001 · W1 权限读取 | `test_kunlian_workflow_authorization_reads.py` 批次初验 8 项通过。最终复验覆盖 9 项，增加停用操作者拒绝。管理者清单、本人动作、分页、受信身份、跨租户及读期间修订变化均有断言。 | AC-01、AC-04 |
| E-002 · W2 单条变更 | `test_f048_kunlian_workflow_grant_lookup.py` 与 `test_kunlian_workflow_authorization_changes.py` 批次初验 16 项通过。核对本地直接来源、保护来源、目标用户与资源范围、F048 变更请求及修订拒绝。 | AC-04、AC-05 |
| E-003 · W3 查回及 HTTP 闭环 | F128 最终 37 项通过。测试先行时观察到查回与候选写路由缺失。验证相同键重复、不同键并发争同一修订、投影 `COMMITTED` 保持待确认、`FINALIZED` 查回原生效修订，以及撤权后拒绝回执。两个闭环用例复用既有 Workflow 列表、详情及授权入口，分别验证最后来源撤销和保留独立组来源。HTTP 测试验证 `202 PENDING` 与 `409 REVISION_CONFLICT`。 | AC-01 至 AC-07 |
| E-004 · 相邻回归 | 联合执行 93 项通过、3 项失败。失败全部来自 `test_f048_grant_api.py`。在同一 `HEAD` `b870baa3f` 的未修改规划工作区单独运行该文件，复现相同 3 项失败、1 项通过。三项均因测试夹具未初始化 `permission_runtime`，权限查询返回 `25021`。 | F048 API、授权策略、投影、资源适配及 Workflow 既有动作和登记 |
| E-005 · 静态检查 | 9 个相关 Python 文件的 Ruff 检查与格式检查通过。架构守卫、Git 差异检查通过。 | 代码静态门禁 |

## 复跑命令

从 `src/backend` 执行，使用现有 Python 3.11 环境与隔离测试配置。分别设置 `BISHENG_TEST_PYTHON` 和 `BISHENG_TEST_CONFIG` 后复跑联合选择。

```sh
config="$BISHENG_TEST_CONFIG" PYTHONPATH="$PWD" "$BISHENG_TEST_PYTHON" -m pytest \
  test/workflow/test_kunlian_workflow_authorization*.py \
  test/permission/test_f048_kunlian_workflow_grant_lookup.py \
  test/permission/test_f048_grant_api.py \
  test/permission/test_f048_grant_policy.py \
  test/permission/test_f048_projection_service.py \
  test/permission/test_f048_resource_api.py \
  test/workflow/test_workflow_action_map.py \
  test/workflow/test_kunlian_workflow_registration_e2e.py \
  -q --disable-warnings --tb=short -rs
```

仅验证 F128 时选取命令中的前两个测试路径，实际结果为 `37 passed`、退出码 `0`。联合选择与基线单文件因上述既有失败退出码为 `1`。

## 待执行

| 范围 | 状态 | 前置 |
| --- | --- | --- |
| T015、T016 正式契约与适配 | `WAITING_EXTERNAL` | 实际用户委托、角色及身份映射、正式 OpenAPI 和可跨实例恢复的回执。见 [设计](./design.md) 中的正式 TODO。 |
| T017 · V-03 受控权限环境 | `NOT_RUN` | 受控 SQL、Redis 一致性标记、OpenFGA 与测试身份，验证实际投影、并发写入和撤权传播。 |
| T018 · V-04 昆联联调 | `NOT_RUN` | 昆联测试环境、正式委托、同租户及跨租户测试身份。 |

测试装配以隔离权限事实连接候选 HTTP 与现有入口。真实 OpenFGA、跨实例回执和生产路由启用属于后续验收。本轮未部署。
