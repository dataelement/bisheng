# F080 本地验证

日期：2026-11-02。基线：`c4fc2316d791736efca6d8b6001814e474938631`。目标：本地 `feat/cofco-1028-3.0.0-beta1`。

## 自动化结果

- 最终专项回归：**253 passed、3 skipped**，无失败。3 项跳过均为显式启用的真实环境 E2E；未设置 `COFCO_MANAGED_E2E=1`。
- Ruff check、format check：11 个新增/修改 Python 文件全部通过；AST 解析、逐文件 architecture guard、`git diff --check` 通过。
- 额外应用启动套件 `test_f048_api_process_runtime.py` 在收集时失败：本机 MCP 的 `StreamableHTTPSessionManager` 不接受 `max_request_body_size`。在未修改的 1028 基线工作区运行同一套件得到同一错误，属于本机依赖限制，未用替身改写该启动入口以宣称通过。
- 使用本机 Python 3.11 与既有虚拟环境。临时 YAML 仅含 SQLite 内存库及不可用的 localhost Redis 地址；未复制部署凭据、未连接 109 或生产。

最终成功运行的测试：

```text
test/knowledge/test_managed_spaces_visible_edit.py
test/knowledge/test_space_listing_pin_source.py
test/knowledge/test_knowledge_space_service.py
test/knowledge/test_knowledge_space_info_optimization.py
test/knowledge/test_space_joined_visible_ids.py
test/knowledge/test_f048_preview_download_permissions.py
test/knowledge/test_knowledge_space_container_access.py
test/permission/test_f048_listing_batch_preparation.py
test/permission/test_f048_permission_service.py
test/permission/test_stale_projection_fail_soft.py
test/permission/test_f048_application_adapters.py
test/permission/test_f048_action_catalog_policy.py
test/permission/test_disabled_catalog_action_listing.py
test/permission/test_f048_knowledge_space_adapter.py
test/permission/test_f048_knowledge_file_adapter.py
test/permission/test_f048_consistency_marker.py
test/permission/test_data_scope_enforcement.py
test/permission/test_f048_list_action_cost.py
test/permission/test_f048_catalog_runtime.py
test/f040/test_static_scan.py
test/e2e/test_e2e_cofco_managed_spaces.py
```

## 验证到的行为

| AC | 证据 |
|---|---|
| AC-01 | 运行真实 service、容器 adapter 与 verified-action helper；edit-only 入选，viewer/manage-only 排除，visible 复核失败排除。 |
| AC-02 | 空可见集零业务读取；非法/非规范 ID、不完整/错误类型/容量超限及上游不可用均阻断，不回退全租户扫描。 |
| AC-03 | 1/100/101/1,001 候选分批预算；真实决策服务每批一次 Catalog readiness、一次 fence、一次 marker；每资源类型一次动作门禁。Redis sentinel 一次 GET、作用域键一次 MGET。 |
| AC-04 | 业务类型/状态/租户及权限快照守卫；全范围与收窄超管路径；stale 投影逐目标排除，degraded/Redis 异常提高一致性，发布或运行时故障传播。SQLite 实际执行证明仓储在继承可见多个租户时仍只返回当前租户。 |
| AC-05 | ASGI 真实路由与响应序列化，置顶、创建者/成员/无成员直接授权角色保留；字段封装与部门/计数装饰调用保留。 |
| AC-06 | 可见枚举、候选查询、成员、权限和装饰失败均传播并记录终态失败阶段；成功记录计数与阶段耗时。 |
| AC-07 | 未改 schema/索引/权限模型/前端/环境。E2E 默认跳过并单列部署验收步骤。 |

离线最不利路径设所有可见项可编辑、无成员，另查 manage_permission 展示角色：

| 可见候选 | 候选仓储调用 | 权限快照读取 | 动作逻辑批次（edit / visible / 角色） |
|---:|---:|---:|---:|
| 1 | 1 | 1 | 3 |
| 100 | 1 | 1 | 3 |
| 101 | 1 | 2 | 6 |
| 1,001 | 1 | 11 | 33 |

这是替换 I/O 边界后的确定性调用次数，**不是达梦实际 SQL 总数、实际 FGA HTTP 请求数或耗时**。底层传输仍按既有 50 条限制拆分，目录/根文件数量不参与该接口的逐文件权限扫描。租户总空间量不再作为普通用户的逐项检查输入，但可见集合枚举和大量可见/可编辑项仍有相应成本。

## 部署后的证据缺口

真实 JWT/OpenFGA、MySQL/DM8 执行计划、浏览器体验及生产 P50/P95 均待部署后按 [e2e-checklist.md](e2e-checklist.md) 验收。本次不把离线测试耗时作为接口加速倍数，也不宣称生产问题已经消除。
