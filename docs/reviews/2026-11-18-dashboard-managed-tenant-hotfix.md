# 看板管理租户写入与 116 残留修复

日期：2026-11-18。基线：`5415ede9d52b02b1afd0dfaa970960f96b7404b9`
（`origin/feat/3.1.0-beta1`）。本次按无接口契约变化的 hotfix 处理。

## 根因与修改

超管的身份归属租户是 Root，但当前管理租户可以是子租户。
`create_dashboard` 和 `copy_dashboard` 原先把身份租户写入看板；116 日志确认
四次请求的上下文租户为 60，实际写入租户为 1。DAO 先提交再刷新，刷新被租户
过滤器阻止，接口报 `Could not refresh instance`，已提交的 SQL 行却保留下来，
尚未进入权限初始化。Root 列表随后加载这些行的权限版本，因没有权限模式记录
而整体报 25008。

- 创建和复制使用当前管理租户；无上下文的既有调用保留身份租户取值。
- DAO 插入先 flush、refresh，成功后才 commit；刷新失败由会话关闭回滚。
- 保留创建者身份、现有权限生命周期及投影失败补偿，不跳过列表权限检查。
- 没有接口、数据库结构或实际角色授权变化。

## 116 数据处理证据

用户已明确授权修复本次残留数据。仅删除看板 173、174、175、176，均属于
tenant 1 / user 3，名称“未命名看板”，状态 custom/draft。创建、修改时间分别为
2026-11-17 18:59:25、18:59:25、18:59:52、18:59:57，各行创建和修改时间相同。
布局均为 `{"layouts": []}`，样式均为 `{"theme": "light"}`，描述为空。

预检确认以下关联全部为零：组件、默认看板、权限模式（含父引用）、授权、投影操作、
可见性投影、业务资源引用、标签、审核标签、用户组和旧角色访问记录。
未把错误归属的数据迁移到子租户，也未补造权限。

备份和执行脚本在 116：
`/opt/server/bisheng-test/backups/dashboard-orphans-20261118/`
（`before.json`、`repair.py`、`result.json`）。备份规范化内容 SHA256：
`d0e8852c2fd65fea5d80367eb4bbf80c4b621bae07bae77fa44f4ce3ab629747`。
备份已复制到宿主机并核对摘要。

执行使用 SERIALIZABLE 事务、行及关联查询锁，重新核对精确 ID、租户、所有者、
内容、时间和备份摘要后才删除；受影响行数严格为 4。
执行后复查：四个 ID 全部不存在，全部剩余看板不存在缺失权限模式的记录。
Root 总看板数从 25 降至 21，其中商业版列表候选为 20。
使用部署代码的 `DashboardDaoPermissionLoader`、`SqlPermissionControlState.permission_version`
和 `F048DashboardPermissionAdapter.resolve_permission_target` 对这 20 条逐个校验，
20 条通过，无 25008；只做读取，没有修改其他看板或权限状态。

HTTP 复核使用 60 秒有效的临时维护凭据，未输出或保存 token。请求通过认证后返回
19703（管理租户尚未选择），未更改用户的管理视图以绕过该条件；因此不把上述业务层
与数据库核验描述为 HTTP 全链路验收。重新选择管理租户后需再验收页面列表。
本次没有部署或重启 116 服务，代码修复须随后端部署生效。

## 验证

执行：
`pytest -q test/telemetry_search/test_dashboard_managed_tenant.py test/permission/test_f048_dashboard_permissions.py test/permission/test_f048_preset_dashboard_bootstrap.py`

- **32 passed**，其中新增 9 项使用真实 SQLite 会话和实际租户事件。
- 创建/复制覆盖 Root、本租户普通用户、Root 超管管理子租户；成功路径同时使用
  实际看板权限适配器，验证目标租户及创建者身份。
- 覆盖创建和复制的权限失败补偿，以及跨租户刷新失败后数据库没有残留。
- 修改前代码的同组对照有 5 项新增用例失败，能重现刷新失败及已提交残留；修改后消除。
- 联跑 `test_dashboard_startup_tenant.py` 为 32 passed / 1 failed；该失败在基线也存在，
  原因是启动初始化仍在租户 9 上下文中执行，不属于本次请求链修复。
- 服务和新增测试 Ruff 通过；DAO 既有 34 项 Ruff 问题与基线规则/消息完全一致，无新增。
- 新增测试格式、Python 编译、三个变更 Python 文件架构守卫、`git diff --check` 通过。
- 无前端修改，未运行前端构建；未执行完整中间件集成或 DM8 现场测试。

## sdd-code-review

审查范围：两个逻辑文件、一个回归测试和本报告。无新增接口契约，hotfix 不要求独立
spec/design/tasks。既有启动测试及 DAO lint 存量问题如上，未扩大本次修复范围。

| 维度 | High | Medium | Low | 结论 |
|---|---|---|---|---|
| 边界条件 | 0 | 0 | 0 | PASS：无上下文兼容、失败回滚 |
| 权限与认证 | 0 | 0 | 0 | PASS：普通用户及超管，权限入口保留 |
| 并发安全 | 0 | 0 | 0 | PASS：刷新在提交前，现场清理锁定重验 |
| 信息泄漏 | 0 | 0 | 0 | PASS：未保存凭据或 token |
| 测试覆盖 | 0 | 0 | 0 | PASS：真实数据库刷新/回滚及权限适配器 |
| 代码风格 | 0 | 0 | 0 | PASS：无新增 lint 问题 |
| 文档同步 | 0 | 0 | 0 | PASS：根因、操作、备份、验证边界齐备 |

**Overall: PASS**，本地修复可合入；部署后仍需在 116 验收子租户创建/复制与 Root 列表。
