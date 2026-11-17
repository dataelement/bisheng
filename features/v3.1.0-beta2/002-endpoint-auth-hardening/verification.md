# 端点认证/授权修复验证

对应 GHSA-p2wv-9g25-xrqr。范围：仅修 4 个报告端点 + 路由级登录依赖护栏，不改中间件行为。

## 修复

| 端点 | 修复 |
|---|---|
| `GET /api/v1/report/report_temp` | 增加 `get_login_user` 依赖；`check_business_action(workflow, flow_id, visible)` 通过后才读取/返回预签名链接 |
| `DELETE /api/v1/dataset/del` | 校验 `dataset.user_id == login_user.user_id` 或管理员；DAO 按 id 删除 |
| `DELETE /api/v1/mark/del` | 仅管理员、创建人、`process_users` 中的标注人可删；不存在返回 404 |
| `GET /api/v1/knowledge/file_bbox` | 先按 id 取文件（不存在 404），再 `require_business_action(knowledge_file, download)`，与 `file_share` 一致 |

护栏：`test/api/test_route_login_guard.py` 冻结当前无登录依赖的 `/api/v1` 路由（shrink-only），新增匿名路由会失败；`report_temp` 已从该集合移除。

## 证据（Python 3.11.14）

RED（修复前）：
- `test_endpoint_authorization.py` + `test_route_login_guard.py`：7 failed / 3 error，其中 `report_temp` 匿名返回 200、护栏报出 `GET /api/v1/report/report_temp`。

GREEN（修复后）：
- 两个新测试文件：14 passed。
- `test/api` + `test/citation/test_access_scope_tiering.py`：123 passed，4 failed。
- 基点对照（clean HEAD worktree，同一解释器）：那 4 个失败在基线同样失败 →
  `test_audit_query_entry_surface::test_audit_reads_are_one_route_family`、
  `test_build_managed_tenant_scope` 两例、`test_route_path_naming::test_no_new_route_contains_config` 均为既有失败。
- `test/citation`：292 passed。
- `knowledge.py` Ruff 错误数基线 31 / 当前 31，未新增；`scripts/arch-guard.sh` exit 0。

## 边界与遗留

- `/api/v1/dataset/*` 当前**未在 app 注册**（`app.routes` 无该前缀），属不可达模块；本次仍做了防御性加固，并顺带修复该模块两处既存缺陷（`from ast import List` 导入错误、service 调用不存在的 `DatasetDao.get_dataset_by_id`、把对象传给按 id 删除的 DAO）。
- 护栏基线包含使用其它认证机制或本就公开的路由（服务账号、分享令牌、HMAC 回调、登录/注册等），是债务清单而非安全背书，仍需逐条复核。
- `report_temp` 的 `visible` 检查沿用 F048：已公开发布的 workflow 对登录用户可见属预期行为；匿名仍拒绝。
- 未执行真实部署/网关验证；本轮为代码级契约测试。