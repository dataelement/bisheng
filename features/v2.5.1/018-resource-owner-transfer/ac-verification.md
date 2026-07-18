# F018 AC Verification — resource-owner-transfer

> Generated 2026-04-21. Mirrors F011 ac-verification.md format.
> spec §2 has 10 primary ACs + 3 sub-cases (AC-08b/c/d).

---

## AC 映射表

| AC | 描述 | 自动化测试 | 手工命令 / 验证 | 状态 |
|----|------|----------|----------------|------|
| AC-01 | 资源原 owner 自己交接成功；`transferred_count` 返回；audit_log 记录 | `test_resource_ownership_service.py::TestHappyAndRollback::test_happy_path_updates_mysql_fga_audit` + `test_resource_owner_transfer_api.py::TestTransferOwnerEndpoint::test_happy_path_returns_200_with_count` | 见下方"手工 QA 1" | 🔲 待跑 |
| AC-02 | Child Admin 代替下属 owner 交接 | `test_resource_owner_transfer_api.py::TestTransferOwnerEndpoint::test_child_admin_ok` | "手工 QA 3" | 🔲 |
| AC-03 | 非 owner 非 admin 尝试转交 → 403 错误码 19601 | `test_resource_ownership_service.py::TestValidations::test_non_owner_non_admin_rejected_19601` + `test_resource_owner_transfer_api.py::test_non_owner_non_admin_returns_403_19601` | "手工 QA 4" | 🔲 |
| AC-04 | `resource_ids=null` 自动转交 from_user 在 tenant_id 下所有可转移资源 | `test_resource_ownership_service.py::TestResolutionAndBatchLimit::test_resource_ids_null_selects_all_from_user` + API `test_resource_ids_null_accepted` | "手工 QA 1"（body 省略 `resource_ids`）| 🔲 |
| AC-05 | 指定 `resource_ids` 列表 → 仅转交列表中的资源 | `test_resource_ownership_service.py::TestResolutionAndBatchLimit::test_resource_ids_list_filters_to_named` + API `test_resource_ids_list_passed_through` | "手工 QA 5" | 🔲 |
| AC-06 | MySQL 成功但 OpenFGA 失败 → 事务回滚；写入 failed_tuples 队列 | `test_resource_ownership_service.py::TestHappyAndRollback::test_fga_failure_rolls_back_and_raises_19605` | "手工 QA 8"（模拟 OpenFGA 宕机）| 🔲 |
| AC-07 | 单次请求 > 500 条 → 400 + 19602 | `test_resource_ownership_service.py::TestResolutionAndBatchLimit::test_batch_over_500_rejected_19602` + API `test_batch_over_500_returns_400_19602` | "手工 QA 6" | 🔲 |
| AC-08 | `to_user` 叶子不在可见集合 → 400 + 19603 | `test_resource_ownership_service.py::TestValidations::test_receiver_cross_child_rejected_19603` | — | 🔲 |
| AC-08b | Child → Root（交回总部）允许 | `test_resource_ownership_service.py::TestValidations::test_receiver_child_to_root_allowed` | "手工 QA 11" | 🔲 |
| AC-08c | Child A → Child B 拒绝 | `test_resource_ownership_service.py::TestValidations::test_receiver_cross_child_rejected_19603` + API `test_receiver_cross_child_returns_400_19603` | "手工 QA 6" | 🔲 |
| AC-08d | Root → Child（资源下沉）拒绝；提示走 F011 migrate-from-root | `test_resource_ownership_service.py::TestValidations::test_receiver_root_to_child_rejected_19603` + API `test_root_to_child_returns_400_19603` | "手工 QA 7" | 🔲 |
| AC-09 | 用户个人中心 → "我的资源" → "转交给..." UI | **延后到前端 feature**（本期无 UI 实现）| N/A | ⏸️ 延后 |
| AC-10 | 超管访问"待交接资源"列表 | `test_resource_ownership_service.py::TestPendingTransfer::test_pending_includes_users_whose_leaf_moved` + API `test_super_admin_gets_list` | "手工 QA 10" | 🔲 |

**其他内部 invariant 测试**:

| 规则 | 测试 |
|------|------|
| `from_user_id == to_user_id` 拒绝 19606 | `TestValidations::test_self_transfer_rejected_19606` + API `test_self_transfer_returns_400_19606` |
| unsupported type 19604 | `TestValidations::test_unsupported_type_rejected_19604` + API `test_unsupported_type_rejected_at_dto_level` |
| 混批（workflow + knowledge_space）分表 UPDATE | `TestResolutionAndBatchLimit::test_mixed_types_grouped_by_type` |
| MAX_BATCH=500 常量锁 | `test_resource_ownership_service.py::test_max_batch_is_500` |
| ResourceRow frozen dataclass | `test_resource_ownership_service.py::test_resource_row_is_frozen` |
| Registry 7 类精确 | `test_resource_type_registry.py::test_supported_types_exactly_7` |

---

## 手工 QA 清单（spec §8）

执行前提：
```bash
# 确保 F011 已 merge，Tenant=2 存在 + Child A 挂到某部门
ssh root@192.168.106.114
cd /opt/bisheng/src/backend
```

1. **owner 本人发起交接成功**
   - 登录 user 100（拥有 3 个 workflow 在 tenant=2）
   - `curl -X POST .../api/v1/tenants/2/resources/transfer-owner -H "Cookie: access_token_cookie=<JWT>" \
      -d '{"from_user_id":100,"to_user_id":200,"resource_types":["workflow"]}'`
   - 预期：200 + `transferred_count: 3`
   - DB 检查：`SELECT user_id FROM flow WHERE user_id=200` 返回 3 行
   - FGA 检查：`fga tuple read user:200 owner` 含 3 条 workflow
   - audit_log：`SELECT * FROM auditlog WHERE action='resource.transfer_owner' ORDER BY create_time DESC LIMIT 1`

2. **Admin 代发交接成功** — 用 tenant admin token 调同样接口 → 200

3. **无权限调用拒绝 403** — 用普通 user 999（不是 owner、不是 admin）→ `{status_code: 19601}` + HTTP 403

4. **批量 501 条请求拒绝**
   - 先批量创建 501 个 workflow owned by user 100
   - 调接口 → 400 + `status_code: 19602`

5. **`resource_ids` 精确控制**
   - user 100 有 5 个 workflow；调接口传 `resource_ids=["wf-a","wf-c"]`
   - 预期：`transferred_count: 2`；其余 3 个 workflow 的 user_id 不变

6. **to_user 非本 Tenant 成员拒绝**（AC-08c）
   - tenant_id=2, to_user 叶子=3 → 400 + 19603

7. **Root→Child 场景拒绝**（AC-08d）
   - tenant_id=1, to_user 在 Child → 400 + 19603
   - response body 提示："使用 F011 /tenants/{child_id}/resources/migrate-from-root 改 tenant_id 后再于 Child 内交接"

8. **MySQL 成功 OpenFGA 失败时整批回滚**
   - 临时 stop openfga Docker 容器 → 调接口 → 500 + 19605
   - `SELECT user_id FROM flow WHERE id='wf-1'` 确认 user_id 仍是 from_user（回滚生效）
   - `SELECT * FROM failed_tuple WHERE status='pending'` 应有 2N 条（N=资源数）— crash_safe 预写记录
   - 重启 openfga，等后台 retry worker 清空 failed_tuple（F004 既有行为）

9. **audit_log 完整** — AC-01 执行后 `SELECT tenant_id, operator_id, operator_tenant_id, action, target_type, target_id, reason, metadata FROM auditlog` 检查字段齐全

10. **超管"待交接"清单展示调岗用户**
    - user 100 有 3 条 workflow 在 tenant=2
    - 模拟其主部门变更到 Child 5（更新 user_tenant.is_active）
    - `curl GET .../api/v1/tenants/2/resources/pending-transfer` → 返回 `[{user_id: 100, resource_count: 3, current_leaf_tenant_id: 5}]`

11. **Child → Root 交接成功**（AC-08b）
    - tenant_id=2 (Child), to_user 叶子=1 (Root) → 200
    - 典型"交回总部"场景

12. **`user_tenant_sync.enforce_transfer_before_relocate=true` 开关验证** —— 本开关由 F012 拥有，本 feature 不直接验证；spec §8 原条目移交 F012 E2E 时一并检查。

---

## 执行日志

```bash
# 在 worktree /Users/lilu/Projects/bisheng-f018 内运行：
# 本地 SQLite 单元测试（不依赖 MySQL/OpenFGA）
.venv/bin/pytest test/test_resource_type_registry.py \
                 test/test_resource_ownership_service.py \
                 test/test_resource_owner_transfer_api.py -v

# 远程 114 全量回归（rsync 同步后）
./bisheng-sync.sh up
ssh root@192.168.106.114 "cd /opt/bisheng/src/backend && .venv/bin/pytest test/ -q"
```

| 运行时间 | 命令 | 结果 |
|---------|------|------|
| — | F018 unit | 待跑 |
| — | 全量回归 | 待跑 |
| — | 手工 QA 1-11 | 待跑 |
