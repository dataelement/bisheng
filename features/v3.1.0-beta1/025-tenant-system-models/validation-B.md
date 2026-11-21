# B 共享生命周期与管理草稿修复验证

验证日期：2026-11-18。工作区：`/Users/zhangguoqing/works/bisheng/.worktrees/beta1-tenant-system-models-20261118`。基线 HEAD：`c36ba672be0ff2f79d0e7358954e77973d2495f2`。以下均为本地隔离验证，不代表部署、真实 OpenFGA、DM8 或 116 现场验收。

## 1. 后端原 B 选择：216 passed

从工作区根目录执行的准确命令：

```bash
config=/Users/zhangguoqing/works/bisheng/src/backend/bisheng/config.yaml \
PYTHONPATH=src/backend \
/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest \
  src/backend/test/knowledge_unification/test_model_delete*.py \
  src/backend/test/knowledge_unification/test_model_deletion*.py \
  src/backend/test/knowledge_unification/test_model_provider*.py \
  src/backend/test/knowledge_unification/test_model_mount*.py \
  src/backend/test/knowledge_unification/test_model_shar*.py \
  src/backend/test/tenant/test_model_mount_fanout.py \
  src/backend/test/tenant/test_tenant_disable_jwt_revoke.py \
  src/backend/test/tenant/test_tenant_archived_terminal.py \
  src/backend/test/tenant/test_tenant_service_root_protect.py \
  src/backend/test/llm/test_llm_tenant_isolation_dao.py \
  src/backend/test/llm/test_llm_create_share_audit.py \
  -q --disable-warnings --maxfail=1
```

原终端结果：`216 passed, 8581 warnings in 14.68s`，退出码 0。原完整 stdout/stderr 未另存；终端结果摘录保存在 `/private/tmp/bisheng-f025-B-backend-216-result.txt`，该文件明确标为摘录，不是全量日志。配置只引用既有开发文件，没有复制或输出凭据。

真实 SQL 生命周期新增 9 条测试位于 `src/backend/test/knowledge_unification/test_model_sharing_lifecycle.py`，覆盖：

1. 历史未知与没有子租户时的显式 on/off 持久意图。
2. 仅新增接收差集初始化；历史已共享缺行不自动开放。
3. 权限投影已完成而 SQL 接收初始化失败时，保留原计划；相反命令冲突；管理员中途限制不被重试覆盖。
4. 冻结后出现的新接收差异可查询，再由原授权命令补齐。
5. 受保护提供商更新新增 LLM，对既有接收者初始化；embedding 不误送 DSH LLM 可见策略；既有本地限制保留。
6. 实际租户重新启用入口消费明确 on 意图，重复命令可恢复。
7. 原增量 writer 在提供商事务中消费意图，权限网络读取发生在 SQL 事务之外。
8. 旧 RESERVED 计划没有新 receipt 时可恢复，不借重试回填历史可见默认。
9. 事务外快照后有新的子租户共享完成时，通过意图版本变化拒绝旧快照；新模型写入回滚，重试覆盖新接收者。

新增独立 SQLModel 表走标准发现和 `create_all(checkfirst=True)`；没有旧表 DDL、历史回填或重签旧计划摘要。原共享/更新 COMPLETED、持久意图与接收默认处于原 SQL 事务中。

## 2. 给 Root 最终集成选择的 B 最小组

建议将下面四个文件与 A 的槽位/来源读取 HTTP、C 的视觉/价格和 Root 诊断测试放入同一次 pytest。该组共 17 条，不必再次运行上述全部后台删除回归：

```text
test/knowledge_unification/test_model_sharing_lifecycle.py
test/knowledge_unification/test_model_provider_sharing_writers.py
test/knowledge_unification/test_model_mount_share_recovery.py
test/tenant/test_model_mount_fanout.py
```

这里的真实 SQL/投影测试用 SQLite 和隔离权限传输适配器，保留原身份、原命令、SQL 计划、冻结 BEFORE/AFTER 与事务约束；它们不证明 MySQL/DM8 的实际锁调度或真实 OpenFGA 接线。

## 3. 后端旧挂载单元测试的基线边界

扩大选择时遇到两个旧测试的创建工厂 mock 不匹配：

- `test/tenant/test_tenant_mount_service.py::TestMountChild::test_happy_path_creates_child_and_sets_mount`
- `test/tenant/test_tenant_mount_service_transaction.py::test_mount_child_writes_root_dept_id_and_single_commit`

两者仍 mock 旧创建路径；目标模块 HEAD 已在第 244 行要求 `_creation_factory`，测试没有提供该工厂。为避免仅凭源码推定基线，另执行了定向基线比较：进程内用 `git show HEAD:src/backend/bisheng/tenant/domain/services/tenant_mount_service.py` 替换目标模块定义，再跑以上两个原测试。

```bash
# cwd: 工作区 src/backend
config=/Users/zhangguoqing/works/bisheng/src/backend/bisheng/config.yaml \
PYTHONPATH=. \
/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python \
  /private/tmp/bisheng-f025-B-mount-baseline-check.py
```

脚本：`/private/tmp/bisheng-f025-B-mount-baseline-check.py`。完整日志：`/private/tmp/bisheng-f025-B-mount-baseline.log`。结果：HEAD 目标模块同样 `2 failed, 8 warnings in 0.34s`，均在 `<HEAD tenant_mount_service.py>:244` 抛出 `TenantTreeMountConflictError`。

这是目标模块的定向基线比较，依赖仍来自当前工作区，不宣称是完整干净基线树的全套测试。未修改旧测试或业务工厂来掩盖失败。216 选择不包含这两个旧文件；本次真实 native 挂载恢复及新 fanout 测试通过。

## 4. UI 独审修复与新交互验证：42 passed

限定修改五个模型栏目及 `useSystemConfigEnvelope`，未改 SharedToolSettings 或 locale JSON。

- Workbench 仍保留失效原模型元数据；页面另列失效配置，只有管理员点击移除才从草稿删除。移除元数据不会自动清掉同 ID 的其它默认槽位。
- `image_read_model` 增加可选择、可清空的 LLM picker；旧不可用值继续显示占位。
- 四简易栏目获得稳定 `reload`；只有保存成功后刷新当前栏目的配置来源。失败保留草稿和来源，不重挂其它栏目。
- 继承栏目提供“保存为本租户配置”动作，草稿期间继续显示已保存的继承来源。
- 五栏保存及 Knowledge 单 prompt 保存均使 `system-model-settings` 与 `system-model-settings-impact` 失效。写入已提交但后续刷新失败时，也先完成诊断失效。
- Knowledge 单 prompt 保存刷新来源而保留本栏目其它未保存字段。过期或卸载后的 envelope 响应不会写回来源，也不会弹出旧请求错误。

从 `src/frontend/platform` 执行：

```bash
pnpm exec vitest run \
  src/pages/ModelPage/manage/tabs \
  src/pages/ModelPage/manage/useSystemConfigEnvelope.test.tsx \
  --maxWorkers=1 --minWorkers=1
```

最终结果：8 个文件、`42 passed`，14.58 秒。完整日志：`/private/tmp/bisheng-f025-B-ui-final.log`。包含 SharedToolSettings 既有回归；B 没有修改该实现文件。

新增/补充交互：Workbench 失效模型显式移除、image_read_model 改/清；四简易栏目成功刷新来源和失败保留草稿；保存一栏不影响另一栏草稿；单 prompt 保存不丢本栏目未保存模型修复；hook 稳定 reload、失败保留、过期响应隔离；Workbench 已提交但刷新失败时诊断与影响缓存仍失效。

该选择不含 ModelAccessDialog；其旧按钮 role 测试由 Root 独立核实，不能把这 42 条称为整页或浏览器 E2E 全通过。日志保留既有 DialogTrigger 嵌套按钮与 React Router future warning，以及预期的请求失败用例日志。

## 5. 静态检查与交付边界

- 后端：B 涉及的 17 个 Python 文件 Ruff 全过；12 个业务文件逐个架构守卫无输出。
- UI：本次 11 个 hook/tab/test 文件 ESLint（使用现有 suppression 文件）通过；未新增 suppression。
- 平台严格类型检查：`pnpm typecheck`，`Found 1362 strict files`，`All files passed`。
- `git diff --check` 通过。
- 使用 Root 分配的五个新增文案 key；三语言由 Root 同批交付。
- 未提交、推送、部署、SSH、操作现场共享或修复 116 存量。

## 6. 最终 C3 登记复核：14 passed

启动租户过滤器的合同是先导入 `_TENANT_AWARE_MODEL_MODULES` 中的模块，再仅扫描当时 `SQLModel.metadata`，且监听器只注册一次。一般建表自动发现不等于这个租户过滤登记；不能依赖 API 路由碰巧先导入新模型。

已在 `src/backend/bisheng/core/database/tenant_filter.py` 明确登记 `bisheng.llm.domain.models.model_sharing_intent`。两个新表的 Python `tenant_id` 缺省值也从 `1` 改成 `None`：省略时由原 `before_flush` 按真实上下文填充；Root 仓储仍显式写入其已验证的 Root 所属租户。未增加旧表 DDL 或历史写入。

在 `test/database/test_model_registry.py` 补一个冷进程测试，使用生产 `register_tenant_filter_events`，验证：模块被建表发现且在租户导入名单、两表被自动登记、Root/Child 直接 ORM SELECT 自动隔离、未指定 tenant_id 的新增行按当前租户自动填充、仅显式 bypass 能读到两租户行。它不以仓储的 Root 拒绝逻辑代替 SQL 层隔离。

```bash
# cwd: 工作区根目录
config=/Users/zhangguoqing/works/bisheng/src/backend/bisheng/config.yaml \
PYTHONPATH=src/backend \
/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest \
  src/backend/test/database/test_model_registry.py \
  src/backend/test/knowledge_unification/test_model_sharing_lifecycle.py \
  -q --disable-warnings --maxfail=1
```

结果：`14 passed, 679 warnings in 9.31s`。完整日志：`/private/tmp/bisheng-f025-B-tenant-registry.log`。本次三文件 Ruff 通过，两个实现文件架构守卫无输出，`git diff --check` 通过。

Root 最终集成可在 §2 的 B 最小 17 条中再加：`test/database/test_model_registry.py::test_sharing_intent_tables_are_registered_and_isolated_in_a_cold_process`，共 18 条；无需为了这个登记修正再运行后台删除全集。
