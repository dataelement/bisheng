# 本地实现与验证记录

工作树：`/Users/zhangguoqing/works/bisheng/.worktrees/beta2-reference-simplification-20261123`。
分支：`codex/beta2-reference-simplification-20261123`，基于本次获取的 `origin/feat/3.1.0-beta2` 起点 `23c82f7769811b2e136e26e9e44839a64c8cb8e7`。

主体代码和回归适配已落地；已获用户授权合并到 beta2 并推送，未部署。环境 E2E 按用户安排，更新开发环境后由用户自行执行。最新结果及基线失败清单见 [回归适配记录](./regression-adaptation.md)。

## 已完成的本地验证

| 检查 | 实际结果 | 范围 |
| --- | --- | --- |
| 本轮最终适配组合 | 1302 passed，8 个基线既有失败，0 errors，0 新增失败 | 1310 项；命令、广组合对照和保留失败见 regression-adaptation.md |
| 后端主定向回归（前轮） | 229 passed，2112 warnings | 新 `test/resource_reference/` + 16 个知识、模型删除/恢复、应用原绑定、实际 source/target 读取及助手执行测试文件 |
| 默认模型槽位回归 | 21 passed | `test_model_default_slot_admission.py`，同步/异步；坏索引不拦截，实际类型、共享撤销仍拒绝 |
| 平台交互测试 | 37 passed，4 files | 知识/模型删除 Dialog 与 Hook；引用未知、已知引用、真实范围变化和重试等 |
| 前端 lint | 完整 `pnpm lint` 通过 | 既有 BatchTagDraftDialog 的 1 个 unused eslint-disable warning 未改 |
| 前端类型 | 完整 `pnpm typecheck` 通过 | platform、client 及各共享包 |
| 三语 | `pnpm check-i18n` 通过 | zh-Hans / en-US / ja；无新增漂移 |
| Python 静态 | 变更文件 compileall 通过；Ruff 无新增问题 | 旧 knowledge_service.py 保留 38 个存量 Ruff 问题，按原代码逐项比对，未把它们记为本次新增 |
| 架构守卫 | 无 VIOLATION | schemas.py 原有直接导入 models 的 RULE-3 WARNING 仍存在；没有增加此类 import |
| Diff | `git diff --check` 通过 | 未更改 ORM 表定义、Alembic 或数据库索引/约束 |

后端使用项目已有 venv：`/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest`；前端在 `src/frontend/` 执行 pnpm。工作树缺少依赖，离线安装因缓存包缺失未完成，之后仅在本工作树建立本地依赖链接和命令 shim，未改 package/lock 文件。

主回归命令：

```sh
cd src/backend
/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest \
  test/resource_reference \
  test/knowledge_unification/test_kn_model_creation.py \
  test/knowledge_unification/test_kn_model_mutation.py \
  test/knowledge_unification/test_kn_model_finalize.py \
  test/knowledge_unification/test_app_saved_capabilities.py \
  test/knowledge_unification/test_model_deletion_application.py \
  test/knowledge_unification/test_model_delete_plan_repo.py \
  test/knowledge_unification/test_kn_delete_plan.py \
  test/knowledge_unification/test_processing_deletion_fence.py \
  test/knowledge_unification/test_model_deletion_put.py \
  test/knowledge_unification/test_model_deletion_handoff.py \
  test/knowledge_unification/test_app_snapshot.py \
  test/knowledge_unification/test_source_read_native.py \
  test/knowledge_unification/test_source_read_target_batches.py \
  test/knowledge_unification/test_processing_deletion_http.py \
  test/knowledge_unification/test_as_execution_admission.py \
  test/knowledge_unification/test_as_runtime_admission.py -q
```

后续补充的任务模块不可用降级与租户删除后的刷新测试单独通过（`test_source_sync.py`：12 passed）；与上方两组去重合计 252 项本地后端用例通过。

默认模型单独执行：`python -m pytest test/knowledge_unification/test_model_default_slot_admission.py -q`。

## 关键行为证据

- `test_deletion_hints.py`：有引用仍可生成业务确认；全局 Coverage 故障无调用；孤儿租户不计入；移动后按实际文件归属；提示失败为未知，权限拒绝不被降级。
- `test_http.py`：真实 ASGI 预检/删除链路；在独立提示事务里执行失败 SQL 后业务计划和删除仍成功；跨租户返回实际 19802。
- `test_business_writes.py`：真实助手/工作流 SQL 写入成功后才通知；无旧索引和旧名称标记仍可编辑；实际提交失败不通知。
- `test_source_sync.py`：旧表替换、重复处理、来源删除、普通 Celery 重试和租户头校验；broker 故障不改变业务成功；禁用频道仍保留其已保存关系，元数据不提取。
- `test_app_bindings.py`：旧模型 ID 丢失不影响知识查看；已知模型调用和未知模型调用相互独立；新 JSON 不依赖辅助行。旧版本不由业务代码更新。
- `test_legacy_model_deletion.py`：模拟旧已 RESERVED 的真实删除和原 tombstone；无需升级账本重新验收即可恢复并完成其原删除标记。
- `test_model_selection.py`：真实 own/Root 目标查询；仅显式共享和直属子租户允许 Root 模型；真实权限运输失败不被吞掉。
- `test_metadata_tenant.py`：仅有业务表也能读元数据处理版本和初始化默认租户，不需要引用表、模型实体或 Run。

## 验证边界及合入前待办

这些是 SQLite + 本地 ASGI 测试，认证、FGA、Celery、对象/检索存储等外部运输有明确替身；未证明 MySQL/DM8 物理锁、真实 Worker 消费和浏览器完整链路。环境清单见 [e2e-checklist.md](./e2e-checklist.md)，不能据上述数字声称环境 E2E 已通过。

已执行广域 F118 对照，并完成本次相关回归适配；权限发布规模测试文件两侧均中断，不能声称完整后端套件通过。最新广组合及适配文件组合结果、原基线既有失败和复现参数文件见 [回归适配记录](./regression-adaptation.md)。

本轮按用户安排不执行真实环境 E2E；没有执行生产资源删除、历史账本清理、迁移或全量回填。

## 合入最新 beta2 的复核

目标基线：`f447b5a36d`；特性提交：`f4d7292a47`。独立合并工作树：`.worktrees/beta2-reference-merge-20261123`，分支 `feat/3.1.0-beta2`。

合并后适配组合：**1303 passed，8 failed，0 errors**（新增旧知识库模型名称提取用例 1 项）。8 个失败与本页列出的 node ID 一致，并已在最新目标基线的独立 `git archive` 源码中再次复现（8 failed，5 passed）；失败集合相同，无新增失败。

冲突修复定向组合（resource_reference、旧知识库模型名称与真实来源读取）：**71 passed**。目标新增的旧知识/空模型兼容及迁移源码、清单、目标相关组合：**105 passed**。未运行真实环境 E2E。

保留远端新增旧知识库模型名称兼容，但在线查看/重校验/修复不再要求引用保留标记；实际调用无法确定的模型仍报错，新建仍校验真实 Embedding ID。后台对旧名称不虚构模型引用。正式七维度审查见 [code-review.md](./code-review.md)，结论 PASS_WITH_WARNINGS。
