# BiSheng 管理租户问题修复交接

> 2026-11-11实施状态更新：用户已确认最小范围；当前工作树已落地零新增业务表/四列的业务修复。本文原调查/方案叙述保留作历史依据，当前范围与接口以[design](../../features/v3.1.0-beta1/009-managed-tenant-consistency/design.md)及[scope-revision](../../features/v3.1.0-beta1/009-managed-tenant-consistency/scope-revision.md)为准。新增86项回归通过；真实集成、前端完整类型检查及发布线同步尚未完成，详见[verification](../../features/v3.1.0-beta1/009-managed-tenant-consistency/verification.md)。未提交、推送、合并或部署，不把原完整40条AC全标完成。

交接日期：2026-11-10。接收方：负责修复开发与回归验收的 agent。

请在已创建的独立工作区继续修复管理视角与账号所属租户混用造成的问题，覆盖角色保存、配额读取、工具创建、工作流创建、文档知识库复制及组织角色候选。前序工作完成了源码排查和本地隔离复现，尚未修改业务代码。

## 工作区和当前状态

| 项目 | 当前值 |
| --- | --- |
| BiSheng 主仓库 | `/Users/zhangguoqing/works/bisheng` |
| 接手工作区 | `/Users/zhangguoqing/works/bisheng/.worktrees/managed-tenant-bugfix` |
| 修复分支 | `codex/3.1.0-beta1/managed-tenant-bugfix` |
| 创建来源 | 本次 fetch 后的 `origin/feat/3.1.0-beta1` |
| 当前 HEAD | `24c02859e2582ed319281bb52285c99930daf81c` |
| 基线提交 | `feat(client): add marketplace entry to the app center` |
| 业务修复 | 尚未开始 |
| Git 提交和推送 | 尚未提交、尚未推送 |

以上为交接时的本地状态。接手先执行 `git status --short`、`git branch --show-current`、`git rev-parse HEAD`，若有后续变动，先识别归属再继续。无需重新创建修复工作区，也不要切换或重置主仓库工作区。

本分支有三份未跟踪的交接材料：

- 本交接文档。
- [问题核查报告](managed-tenant-investigation-20261110.md)：详细根因、定位及执行结果。
- [诊断脚本](managed_tenant_investigation_20261110_repro.py)：10 个捕获当前错误行为的观察性用例。

**这些材料尚未进入 Git，另一台机器仅 checkout 分支无法得到它们。跨机器交接须一并传递三份文件。** 主仓库原有文档 WIP 未修改；Desktop 仓库也未修改。保留这些内容及其他 agent 的工作，不使用 `git stash`、`git reset --hard` 或 `git clean` 清理工作区。

## 接手先读

按当前工作区中的版本阅读：

1. [仓库约束](../../AGENTS.md)、[后端约束](../../src/backend/AGENTS.md)。本任务属于 BiSheng 后端，不是 DSH Desktop。
2. [架构宪法](../constitution.md)，重点 C1 分层、C2 MySQL 与 DM8、C3 租户隔离、C4 权限投影与操作账本。
3. [多租户架构](../architecture/12-multi-tenant.md)、[开发流程分级](../SDD-Guide.md)。跨模块或改变契约的修复按实际范围选择流程；本交接文档不替代所需设计确认，也不表示已批准新的权限或恢复契约。
4. 问题核查报告与诊断脚本，然后阅读对应入口、调用者和既有测试。

## 必须保留的租户边界

典型复现条件是：账号真实归属租户 1，超管在管理界面选择租户 2。

- `LoginUser.tenant_id` 来自认证身份，仍表示账号所属租户 1。
- `management_tenant_scope(2)` 设置独立管理视角。管理 API 中 `get_current_tenant_id()` 返回 2，查询通常按 2 过滤。
- 两个值不是同一个概念。创建管理资源应采用已验证的目标租户；身份、审计及个人业务仍须保留各自归属。
- 自动填充只处理空/0 租户。显式写入租户 1 不会被改写；commit 可以成功，但紧接着的 refresh 被租户 2 的过滤规则挡住，造成“请求失败、数据已落库”。
- 全局角色是共享定义，其他租户的自定义角色不是。读取全局定义的例外不能扩大为读取所有租户角色的通行证。

不要通过统一改写 `LoginUser.tenant_id`、全局取消过滤、让所有 DAO 都 bypass、去掉 refresh 或吞掉异常来消除表面报错。调用者可能包含管理请求、个人业务、后台任务和普通租户账号，需分别核对目标与授权。

## 六项修复任务

下列源码行号以基线为准，后续以符号为准。建议先解决角色与配额，再处理创建和复制，最后补齐组织绑定链路。

| 编号 | 已确认的问题与入口 | 修复后必须满足的行为 |
| --- | --- | --- |
| MT01 | `database/models/role.py` 的 `aget_role_by_id()` 已允许管理视角读取全局定义，但 `RoleService.update_role_with_menu()`、`update_menu()` 的事务内第二次查询未沿用规则，抛 `RoleNotFoundError`。`update_role()` 则 commit 后 refresh 失败，修改已保留。 | 已授权的超管在子租户视角保存全局角色及菜单成功；事务内外解析规则一致；禁止普通用户/租户管理员修改全局角色；其他租户自定义角色仍不可越权访问。 |
| MT02 | `RoleDao.aget_role_by_ids()` 会过滤掉已绑定的全局角色；`QuotaService.get_effective_quota()` 因角色集合为空，将 `channel=0` 读为默认 10。 | 既定绑定下，全局角色配额不会因无关管理视角丢失；0、-1、未配置、多角色聚合及租户上限各遵循现有契约。不能只修数字聚合，因为保留 0 的聚合逻辑本身正常。 |
| MT03 | `ToolServices.add_tools()` 显式写 `self.login_user.tenant_id`；`GptsToolsDao.insert_tool_type()` 先 commit 父记录再 refresh，后续 children 与权限 hook 来不及执行。API=0、MCP=2 均复现。 | 父记录、非空 children 和权限投影按同一已验证目标租户创建；刷新及列表详情正常；错误路径不留下无法使用的半成品。涉及 SQL 与权限投影的恢复按现有宪法处理。 |
| MT04 | `api/v1/workflow.py:create_flow()` 显式写账号租户；`FlowDao.create_flow()` 自动创建的初始版本却落到管理视角租户，主记录 1 / 初始版本 2，commit 后 refresh 失败。 | 主记录和初始版本同属已授权目标租户；创建、列表、详情、版本读取及后置权限 hook 正常；失败时不留跨租户关联。检查配额装饰器与真实 HTTP 入口。 |
| MT05 | `KnowledgeService.copy_knowledge()` 先把源改为 COPYING；`create_knowledge_base()` 将目标覆盖为账号租户；目标 INSERT/refresh 或权限投影失败没有源状态恢复、目标补偿。 | 源与目标归属符合既定复制规则；建库、投影、审计或任务投递失败都有明确可恢复状态；成功可完成复制；不盲目删除已投影或已调度的目标，重试不产生重复/孤儿记录。 |
| MT06 | `DepartmentService.aget_assignable_roles()`、`_aget_assignable_roles_catalog()` 在 bypass 后按 `login_user.tenant_id` 筛选，导致租户 2 部门候选包含租户 1 自定义角色、遗漏租户 2 角色。 | 候选依据已验证部门及目标租户，保留合法全局角色和部门祖先作用域；单个/批量候选一致；最终绑定、默认角色等消费入口也拒绝其他租户角色。 |

主要定位均在 `src/backend/bisheng/` 下：

- 管理上下文：`core/context/tenant.py`；管理准入：`common/middleware/admin_scope.py`、`admin/domain/services/tenant_scope.py`。
- 自动过滤/填充：`core/database/tenant_filter.py`。
- 角色与配额：`database/models/role.py`、`role/domain/services/role_service.py`、`role/domain/services/quota_service.py`；API 位于 `role/api/endpoints/`。
- 工具：`tool/domain/services/tool.py`、`tool/domain/models/gpts_tools.py`。
- 工作流：`api/v1/workflow.py`、`database/models/flow.py`、`database/models/flow_version.py`。
- 知识库：`knowledge/domain/services/knowledge_service.py`、`knowledge/domain/models/knowledge.py`；同时追踪权限 adapter 和实际 Celery 复制任务。
- 组织成员：`department/domain/services/department_service.py`；追踪角色候选的前端消费者与绑定 API。

## 复现证据及其限制

诊断脚本实跑结果为 **10 passed**。它的断言预期“出现错误、错误数据残留”，因此修好后相关用例应失效；不能保留这些断言当作正确行为回归。

| 观察性用例 | 当前证明的内容 | 修复阶段还要补的覆盖 |
| --- | --- | --- |
| `test_global_role_second_lookup_fails`，2 个参数 | 真实角色 ORM 查询及服务保存的第二次查询失败 | 实际授权、角色菜单关联表写入、HTTP 保存入口 |
| `test_role_update_commits_before_refresh_failure` | 真实 ORM 已保存 remark，后续 refresh 报错 | 成功保存与授权拒绝的正确结果，关联记录一致性 |
| `test_quota_zero_disappears_when_global_role_is_filtered` | 同一配置在批量角色被过滤后，函数结果由 0 变 10 | 真实用户角色绑定查询、显示/执行配额入口及非超管身份 |
| `test_tool_wrong_tenant_persists_before_refresh_failure`，API/MCP 两个参数 | 真实父记录 INSERT/refresh 失败；hook 未运行 | 非空 children、真实 schema 解析、权限投影和详情 |
| `test_workflow_wrong_tenant_persists_before_refresh_failure` | 真实 DAO 下主记录与初始版本租户不同，且提交后刷新失败 | HTTP 入口、配额、后置 hook、详情和版本操作 |
| `test_department_role_candidates_use_login_tenant` | 单个候选服务在错误租户中查询自定义角色 | 部门真实加载与授权、批量候选、最终绑定 API |
| `test_knowledge_copy_failure_leaves_source_and_target` | 投影失败注入后没有源/目标补偿；目标创建用替身 | 真实状态持久化、权限投影与可恢复操作 |
| `test_knowledge_copy_real_insert_refresh_leaves_target` | 真实目标 INSERT 后 refresh 失败且目标残留 | 源状态持久化、索引/文件清理及任务生命周期 |

脚本复用测试 premock 和 SQLite DDL 辅助函数。角色及部门授权部分被替换；工具 schema 校验、外部系统和知识库源状态更新使用替身。没有真实 OpenFGA、Celery、MySQL/DM8 或浏览器验收。

配额复现直接调用服务函数并手动建立管理上下文。`/api/v1/quota/effective` 会传 `login_user`，超管可能走无限配额短路；不能据此断言该超管 HTTP 请求一定显示 10。接手需追踪显示与创建限额的实际调用者，用非超管覆盖生效路径。

知识库当前复现针对文档库。QA 库的 `copy_qa_knowledge()` 是相邻风险路径，需要核对；本次没有证明其具有完全相同的落库行为。组织批量候选方法仅核对源码，最终绑定是否受影响仍待接口验证。

## 本地运行方法和基线

当前可用环境为主仓库已有 Python 3.11.13、pytest 9.0.3，没有安装或升级依赖。以下路径仅用于本机接手，换机器使用满足 `pyproject.toml`、`uv.lock` 的环境。

```bash
cd /Users/zhangguoqing/works/bisheng/.worktrees/managed-tenant-bugfix/src/backend
TEST_PYTHON=/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python
"$TEST_PYTHON" -c 'from pathlib import Path; Path("/tmp/bisheng-managed-tenant-test-config.yaml").write_text("{}\n")'
config=/tmp/bisheng-managed-tenant-test-config.yaml PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 "$TEST_PYTHON" -m pytest ../../docs/reviews/managed_tenant_investigation_20261110_repro.py --asyncio-mode=auto -p no:cacheprovider -q --disable-warnings
```

`{}` 配置仅用于隔离测试，不能拿来启动完整应用。默认缺少 `bisheng/config.yaml` 会导致收集失败；直接用 Docker 模板还会要求 `BISHENG_GATEWAY_HMAC_SECRET` 等环境变量。无需读取或复制用户真实配置解决这两个测试准备问题。

前序基线还运行过：

```bash
config=/tmp/bisheng-managed-tenant-test-config.yaml PYTHONDONTWRITEBYTECODE=1 "$TEST_PYTHON" -m pytest -p no:cacheprovider test/admin/test_management_view_filtering.py test/role/test_management_view_catalog.py test/quota/test_quota_service.py -q --disable-warnings --tb=short
```

结果为 **47 passed / 28 failed**：27 个管理中间件用例返回 19705，错误中包含缺少数据库上下文，现有 fixture 未提供当前租户解析需要的数据；另 1 个角色目录用例仍断言旧全租户视角，而当前 `is_management_all_tenants()` 固定返回 False。这是未修复基线，不能直接当作本次新增回归。修正 fixture 或旧断言时说明对应的新旧契约，不能跳过测试或放宽租户隔离来刷绿。

前序 `git diff --check` 和材料链接/空白校核通过。未运行完整后端测试、前端构建/测试或真实环境验收。

## 开发顺序和验收

1. 保留现状证据，按当前指令和实际契约确定修复范围、流程及权限边界。优先复用已有目标租户/权限解析协议。
2. 将观察用例转为正式行为回归，放入 `test/role/`、`test/quota/`、`test/tool/`、`test/workflow/`、`test/knowledge/`、`test/department/` 对应目录；先让正确断言在旧实现失败，再随实现修复。
3. 修复角色/配额与创建路径；知识库额外明确状态恢复、投影和任务投递的幂等边界。关联审计必须区分操作者所属租户与操作目标租户。
4. 对同一测试选择保留前后基线，运行相关测试的组合，排查 ContextVar 或 premock 泄漏。相关既有测试入口可从以下文件开始扩展：
   - `test/role/test_role_service.py`、`test_role_api.py`、`test_management_view_catalog.py`。
   - `test/quota/test_quota_service.py`、`test_quota_service_check_chain.py`、`test_quota_service_tenant_tree.py`。
   - `test/tool/test_f048_tool_permissions.py`、`test/workflow/test_flow_dao_tenant_isolation.py`。
   - `test/knowledge/test_upload_permission_rollback.py`、`test_unified_permission_creation.py`。
   - `test/department/test_department_scope_parity.py`、`test_dept_member_add_sync.py`。
5. 根据后端规则执行 ruff、架构检查及适当回归；真实 MySQL/DM8 与中间件环境下验证提交、刷新、失败恢复和任务状态。若修改前端，再遵守前端目录约束并做浏览器验证。

验收至少覆盖以下条件：

| 场景 | 必须观察的结果 |
| --- | --- |
| 超管账号归属 1、管理视角 2 | 合法管理资源写入 2，主子记录一致，身份审计仍保留账号真实归属 |
| 管理视角由 2 切回 1 | 新旧资源列表、详情、配额、编辑结果符合目标视角，不借缓存混租户 |
| 租户管理员及普通用户 | 合法功能可用；无权修改全局角色或绑定其他租户角色 |
| 全局角色与其他租户自定义角色 | 合法共享定义可读取，其他租户自定义角色不可因 bypass 暴露 |
| 配额 0、-1、缺省及多角色 | 显示、创建检查与实际限制遵循各自既定契约 |
| 创建失败及重试 | 不出现无恢复入口的残留记录、主子租户错位或错误后继续返回成功 |
| 复制失败及重试 | 源可恢复；目标、权限投影、外部索引及任务状态一致或有可执行恢复路径 |
| 无管理视角的个人业务和后台任务 | 保持既定所属租户语义，不受管理修复误伤 |

历史环境中是否已经有残留资源需要另行取证。开发修复不包含生产数据清理、批量迁移、部署、合并或发布；不要默认删除真实数据。

## 完成交付内容

修复 agent 应交付代码与对应正确行为测试、按 MT01 至 MT06 的完成情况、实际运行的检查与基线差异、未完成的真实环境验收、提交/分支状态，以及知识库失败后的恢复办法。若范围扩展，说明新的调用者或证据，不把尚未核查的模块标为安全。

可给接手 agent 的任务说明：

> 请在本文指定工作区和分支继续 BiSheng 多租户 bug 修复。先读本文、核查报告及复现脚本；保留未提交材料和无关 WIP。按 MT01 至 MT06 核对当前契约，补正确行为回归并实施修复，重点保证账号归属与管理目标分离、主子记录租户一致，以及知识库复制失败可恢复。诊断脚本 10 passed 是缺陷复现结果，不是验收。完成后按仓库流程评审，报告实际测试、基线差异、未验收项和提交状态。
