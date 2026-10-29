# 审计列表：用户部门、用户公司、用户科室

验证毕昇平台审计页「应用使用」和「系统操作」。门户运营后台嵌的是同一页。

## 要起的服务

- 毕昇后端，连 `config.yaml` 里的 MySQL
- 平台前端

## 数据

- 一个能打开审计列表的账号：超管，或角色里开了「审计」菜单
- 至少一条应用使用会话，创建人有主部门
- 至少一条系统操作，操作人有主部门
- 主部门沿 `department.path` 能解析出公司、部门或科室

表：读 `message_session.user_id`、`audit_log.operator_id`、`user_department`（`is_primary = 1`）、`department`（`name`、`path`、`org_level`、`status`）。无新表、无加列、无改字段。无 DDL。

名称是查询时按当前主部门算出来的，不是操作发生时的快照。

## 接口

- `GET /api/v1/audit/session` 每行有 `department_name`、`company_name`、`office_name`
- `GET /api/v1/audit` 同样三字段
- `GET /api/v1/audit/user-org-options` 只返回组织名称，不扫审计大表
- 查询参数 `user_department`、`user_company`、`user_office` 按名称精确匹配，三个条件同时生效
- `GET /api/v1/audit/session/export/data` 带同样的三个参数。CSV 不加这三列

## 页面

1. 打开审计「应用使用」。表尾三列依次是用户公司、用户部门、用户科室。
2. 点「更多」，出现这三个可搜索下拉。选一个部门后查询，列表只留该部门。重置后三个条件清空。
3. 打开「系统操作」，表尾同样三列，更多筛选同样生效。
4. 应用使用导出 CSV，表头没有这三列；导出的会话范围跟上一次带这三个条件的查询一致。

## 命令

本地实现时不跑。要跑时：

```bash
cd /Users/lkk/workplace/bisheng
BISHENG_E2E=1 \
BISHENG_BASE_URL=http://127.0.0.1:7860 \
BISHENG_TOKEN='登录后的 access_token' \
uv run --directory src/backend pytest ../../e2e/audit-user-org/test_audit_user_org_flow.py -q
```

`src/backend` 的 pytest 默认只收集 `test/`，所以要写明这个文件路径。
