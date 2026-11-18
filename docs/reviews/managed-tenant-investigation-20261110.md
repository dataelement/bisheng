# 管理视角与账号所属租户混用问题核查

日期：2026-11-10。范围：核查截图中的问题是否仍存在，未实施业务修复。

## 基线与隔离

- 从 `origin` 拉取 `feat/3.1.0-beta1` 后创建分支 `codex/3.1.0-beta1/managed-tenant-bugfix`。
- 基线：`24c02859e2`（`feat(client): add marketplace entry to the app center`）。
- 独立 worktree：BiSheng 主仓库下 `.worktrees/managed-tenant-bugfix`。
- 原 BiSheng 工作区的文档 WIP 和原分支均保留；没有修改 Desktop 仓库。
- 复现只使用内存 SQLite、合成账号/租户和测试替身；未连接真实业务数据库、Redis、OpenFGA、Milvus、ES 或 MinIO。

## 结论

**截图中的五类问题在当前基线上均有本地证据支持。** 其中知识库的源状态更新、权限投影等外部步骤使用替身/失败注入；工具和工作流等提交后刷新失败使用真实 ORM 与 SQLite 验证。没有进行 test 环境或浏览器端到端验收。

| 项目 | 本地结果 | 影响与证据边界 |
| --- | --- | --- |
| 全局角色保存、菜单保存 | 已复现 | 第一次 DAO 查询能看到全局角色，保存中的第二次查询受子租户过滤，抛 `RoleNotFoundError`。不带菜单的更新则先提交、后 refresh 失败，数据库已保留修改。 |
| 配额 0 变为默认 10 | 已复现 | 原全局角色配置 `channel=0`。切入子租户管理视角后批量角色查询为空，配额函数回退默认值 10；对照组读取同一角色得到 0。不是把数值 0 本身当成假值。 |
| API / MCP 工具创建 | 两种类型均已复现 | 服务将父记录显式写入登录用户所属租户 1，commit 成功后 refresh 被管理视角 2 过滤而失败；父记录仍在租户 1，后置权限 hook 未运行。使用空 children 与模拟 schema 校验，未请求真实 API/MCP 服务。 |
| 工作流创建 | DAO 提交/刷新路径已复现，入口赋值已核对 | 入口显式赋租户 1；DAO 提交后 refresh 失败，主记录仍在租户 1。额外发现：初始版本自动填入管理视角租户 2，主记录和版本归属不一致。未通过 HTTP 创建接口或配额装饰器运行。 |
| 文档知识库复制 | 已复现实际目标 INSERT/refresh 失败；另有投影失败注入 | 源状态先改为 COPYING，目标创建覆盖为登录用户租户 1。真实目标 INSERT 提交后 refresh 失败，目标残留；函数没有恢复源状态。投影异常也不会补偿源和目标。源状态写入用内存替身记录，未启动 Celery 复制任务。 |
| 组织与成员的角色候选 | 服务方法已复现 | 已授权读取的部门属于租户 2，但候选查询绕过自动过滤后按登录租户 1 筛选，包含根租户自定义角色，遗漏租户 2 自定义角色。部门加载与授权检查使用替身；没有验证最终绑定接口。 |

截图中“模型、助手、用户组、工作台配置未复现”的描述，不能作为这些模块没有问题的证明。本轮未对它们做全面验收。

## 根因与代码定位

1. `src/backend/bisheng/core/context/tenant.py:247` 的 `management_tenant_scope()` 保留认证归属，单独设置管理视角；`get_current_tenant_id()` 在管理 API 中返回管理视角。`LoginUser.tenant_id` 则来自 JWT，仍是账号归属。这两个值各有用途，不能随意互换。
2. `src/backend/bisheng/core/database/tenant_filter.py:258` 的自动填充只处理空/0 租户。显式写入错误租户仅记警告，仍提交；后续查询与 refresh 却受有效管理视角过滤。该组合造成“请求失败但数据已保存”。
3. `src/backend/bisheng/database/models/role.py:192` 已对全局角色的单条管理查询做例外处理，但 `role_service.py:439`、`:516` 的第二次查询没有沿用该契约。`:150` 的 DAO 更新在 commit 后执行受过滤的 refresh。批量查询 `role.py:181` 也未沿用全局角色规则。
4. `src/backend/bisheng/role/domain/services/quota_service.py:137` 先查询角色，再由 `_compute_role_quotas()`（`:564`）聚合。角色丢失时返回默认值；单独聚合能正确保留 0。
5. `src/backend/bisheng/tool/domain/services/tool.py:263` 写 `self.login_user.tenant_id`；`tool/domain/models/gpts_tools.py:469` 先提交父记录，再 refresh，然后才插入 children。
6. `src/backend/bisheng/api/v1/workflow.py:443` 写 `login_user.tenant_id`；`database/models/flow.py:174` 创建主记录和初始版本、提交、refresh。版本未显式继承主记录租户，自动填充到管理视角。
7. `src/backend/bisheng/knowledge/domain/services/knowledge_service.py:2553` 的复制流程先设置源 COPYING，然后创建目标，再投影权限、审计和调度任务；缺少失败补偿。目标创建 `:886` 覆盖为账号租户，`knowledge/domain/models/knowledge.py:227` 先 commit 再 refresh。
8. `src/backend/bisheng/department/domain/services/department_service.py:2294` 和 `:2378` 的候选查询在 bypass 内按 `login_user.tenant_id` 过滤。复现执行前一个方法；后一个方法仅核对源码。

## 复现与检查结果

随附 [诊断脚本](managed_tenant_investigation_20261110_repro.py) 包含 **10 个观察性用例，10 个通过**。这里的“通过”表示成功捕获当前错误行为，不能当作修复验收；修复时应将断言转换成正确契约，并纳入 `test/<module>/`。

复现使用主仓库已有 Python 3.11.13 / pytest 9.0.3 环境，没有安装或升级依赖。脚本使用仓库测试的 `premock_import_chain()` 和 DDL 辅助函数。单条角色授权检查、部门权限和外部服务被替换，不证明权限系统整体正常。

在仓库 `src/backend/` 下，使用具备现有项目依赖的 Python：

```bash
python -c 'from pathlib import Path; Path("/tmp/bisheng-managed-tenant-test-config.yaml").write_text("{}\n")'
config=/tmp/bisheng-managed-tenant-test-config.yaml PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 python -m pytest ../../docs/reviews/managed_tenant_investigation_20261110_repro.py --asyncio-mode=auto -p no:cacheprovider -q --disable-warnings
```

另执行现有测试：

```bash
config=/tmp/bisheng-managed-tenant-test-config.yaml PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider test/admin/test_management_view_filtering.py test/role/test_management_view_catalog.py test/quota/test_quota_service.py -q --disable-warnings --tb=short
```

结果：**47 passed / 28 failed**，均在未改业务代码的基线上。27 个管理中间件用例在管理租户解析阶段返回 19705，现有 fixture 未提供当前协议要求的租户归属/状态查询数据库上下文；另 1 个角色目录用例仍期望全租户视角，而当前 `is_management_all_tenants()` 固定为 False。不能把这批失败都算作截图缺陷，也不能声称相关回归全绿。最初仅执行角色目录与配额两文件为 46 passed / 1 failed。

未运行：完整后端测试、前端构建/测试、真实 MySQL/DM8、浏览器、Celery 及 test 环境接口验收。本次仅新增诊断材料，不改业务或正式测试契约。

## 后续修复建议

1. 明确角色全局定义、角色绑定和管理资源各自的读取/写入租户，避免统一改写 `LoginUser.tenant_id` 或全局扩大 bypass。
2. 将角色单条、批量、事务内读取和菜单保存的全局定义规则对齐，保证配额读取不会因视角切换丢失已绑定角色。
3. 工具和工作流创建采用已经验证的目标管理租户，主子记录租户一致；保留账号真实归属用于审计。
4. 知识库复制以明确的复制状态机/恢复路径处理建库、权限投影和任务投递失败，保证异常后源可恢复、目标可识别及可清理。
5. 组织角色候选按已验证部门/目标租户获取，并验证绑定入口拒绝其他租户角色。
6. 修正过时测试 fixture 后，以“账号归属 1、管理视角 2”为基础补正确行为回归，再做非超管、超管和真实环境验收。
