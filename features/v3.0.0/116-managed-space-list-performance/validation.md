# F116 主线验证记录

日期：2026-11-02。来源修复：`a8602ada9effc0718313eb22f66a3c9aef8f358e`。

## 基线与分支整合

远端主线起点：`368894d9a45f265a47903e2b6d08a90f5418b607`。本地主线另有 `22220ed98` 检索修复；远端已有同一修复的后续版本。隔离工作区以普通合并保留双方历史，唯一冲突是注释；整合提交 `94f3b7b8b` 的代码树与远端起点完全一致。

只应用来源提交的 backend 性能代码和回归补丁，未合并 COFCO 其它提交、客户材料或部署配置。真实 E2E 改为主线命名并使用显式预期 tenant_id；主线额外补 contextmanager 导入及租户管理员可见范围回归。

并行整合：提交前检测到本地主线新增 `f13c29489` 成员来源重新激活修复。已普通合并并保留其版本递增/冲突围栏，再额外联合运行相关三组测试；没有用性能补丁覆盖它。

## 自动化结果

- 变更前同环境基线：**253 passed**。
- 适配后联合回归：**351 passed、3 skipped**，无失败。跳过项均为默认关闭的真实部署 E2E。
- 原两个绑定已删除扫描/formatter 的测试移除，其目标改由服务/adapter/统一 runtime 的行为和批次预算测试保护。
- 新增/修改的 11 个 Python 文件 Ruff check、format check、AST 解析和架构守卫通过；diff 空白及冲突标记检查通过。
- 函数级 AST 对比确认：存量生产文件只变更 managed 编排/formatter、构造注入，以及批量快照/门禁/标记入口。get_space_info、广场/退出重入、公开应用 guest-link 及文件 adapter 原有方法保持原实现。主线 runtime.py 未修改。

使用本机既有 Python 3.11 虚拟环境和临时 SQLite 内存/localhost 不可用 Redis 配置；测试以 fixture 替换外部 I/O，未复制部署凭据、未连接或更改任何运行环境。部分仓储和 Catalog 测试实际执行 SQLite SQL，不能代表 MySQL/DM8 联调。

## 联合回归范围

```text
test/knowledge/test_knowledge_space_service.py
test/knowledge/test_space_joined_visible_ids.py
test/knowledge/test_space_listing_pin_source.py
test/knowledge/test_knowledge_space_container_access.py
test/knowledge/test_space_preview_access.py
test/knowledge/test_square_revoked_membership.py
test/knowledge/test_knowledge_space_chat_service_retrieve.py
test/knowledge/test_managed_spaces_visible_edit.py
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
test/permission/test_f048_listing_batch_preparation.py
test/permission/test_creation_rollback.py
test/permission/test_creation_rollback_repository.py
test/permission/test_f048_membership_reactivation.py
test/permission/test_f048_business_source_projection.py
test/permission/test_f048_projection_sql_runtime.py
test/f040/test_static_scan.py
test/public_endpoints/test_guest_policy.py
test/public_endpoints/test_guest_link.py
test/open_api/test_service_account_creator_delete.py
test/open_api/test_service_account_absent_resource_grants.py
test/open_api/test_service_account_grant_query.py
test/e2e/test_e2e_managed_spaces.py
```

## 已验证与待验收

AC-01/AC-02：visible ∩ edit、无成员直接授权、viewer/manage-only 排除；空/错误/超限枚举不回退。

AC-03：1/100/101/1,001 可见候选均只调用一次候选仓储；权限快照按 1/1/2/11 批读取，动作与 Redis/围栏准备有界，不对租户总空间逐页展开。这是离线调用预算，不能宣称实际数据库查询总数或性能倍数。

AC-04/AC-05：普通用户、租户管理员、全范围/收窄超管，状态/租户/版本围栏及数据库排序、置顶、角色/计数装饰通过；主线专有服务账号创建者删除、回滚、公开访问和退出重入回归通过。

AC-06：成功/失败阶段及计数、异常传播通过。AC-07：没有 schema、模型、前端或运行环境变更。

真实 JWT/OpenFGA、MySQL/DM8、浏览器及主线性能对比尚未执行，部署后按 [e2e-checklist.md](e2e-checklist.md) 验收。109 COFCO 的冒烟数据不当作本主线的实测结果。
