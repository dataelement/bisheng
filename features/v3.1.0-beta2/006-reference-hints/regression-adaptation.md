# 回归适配与基线比较（2026-11-23）

用户安排：本轮适配旧回归；用户更新开发环境后自行执行环境 E2E。未部署、未执行远端资源删除、数据迁移或账本清理。

## 适配范围

- 助手、工作流、频道、知识空间/QA、默认模型和继承恢复：保存真实业务数据；旧引用 writer 不再是同事务依赖；显式运行异步刷新后验证提示记录。
- 读取和实际调用：不依赖来源集合、Coverage 或历史 Run；保留实际实体、类型、共享、权限、身份和版本判断。无法确定原目标 ID 的托管应用仍只在相关能力调用时报错。
- 删除提示与计划：有记录仅提示；缺失/失败为未知，不影响真实业务确认。旧签名计划保留，引用字段退出执行资格判断。
- 移动：不读写引用表来完成业务切换；旧缓存的空间 ID 保留。另有真实当前文件归属查询测试。保留真实切换凭据、处理 lease、ready 标记和失败回滚测试。
- 元数据：从业务配置读取修订，不加载模型引用 runtime。历史迁移工具的严格验证用例仍单独保留；需要历史终态索引的测试显式构造旧版本快照。

未为通过测试恢复强一致逻辑，没有新增 skip/xfail，也没有把基线失败改记为通过。业务主路径残留的同步引用字段依赖被直接修复。

## 回归发现并修复的业务遗漏

1. 工作流下线分支没有提交状态：提交移到两条业务分支共同的事务末尾。
2. 重建预检仍访问已移除的 `preview.bindings`：仅保留文件版本、实际模型配置修订和 generation；旧签名确认中的引用字段不参与资格比较，不更新旧记录。新增旧格式确认的实际接受测试。
3. 知识空间删除/清空计划没有校验被修改的 `only_clear`：恢复资源身份及动作字段校验，并保留原事务限制。这是实际业务计划校验，不增加引用一致性。

## 验证方法

基线为当前独立分支的起点 `23c82f7769811b2e136e26e9e44839a64c8cb8e7`，用 `git archive HEAD` 导出到临时目录，使用同一个项目 venv 和各自源码、测试配置运行。对照原始文件的相同用例状态；重写/新增断言以本规格为准，不能拿旧的强一致期望作为产品要求。

广域基线结果（两段合并、去重）：**7518 passed，204 failed，8 skipped**。权限发布规模测试文件耗时很长，两侧均中断；该文件不计入上述对照汇总，不能据此声称完整后端套件通过。

广组合运行包含 104 个相关文件及新增引用测试：**1439 passed，24 failed，0 errors**。其中 23 个失败用例在原基线也失败；唯一新增失败是“未配置 embedding”的旧错误类型断言，已改为实际业务错误，并在包含该文件的 **67 passed** 组合中复验。新增引用测试目录在广组合中 **37 passed**。

最终适配文件组合（1310 项）：**1302 passed，8 failed，0 errors，0 新增失败**。8 个失败均在原基线中失败：预览身份 1 项、助手知识工具装配 1 项、缺少 processing fence 表 6 项。没有将其设为 skip/xfail。之前唯一新增的错误类型断言已在此组合中通过。广组合中的 1 万文件移动规模用例已通过（单项约 118 秒），没有通过删除或跳过该用例来掩盖失败。

复现广组合：

```sh
cd src/backend
/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest \
  @../../features/v3.1.0-beta2/006-reference-hints/regression-selection.txt -q
```

复现适配文件组合：

```sh
cd src/backend
/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest \
  @../../features/v3.1.0-beta2/006-reference-hints/adapted-regression-selection.txt -q
```

## 广组合中仍失败的基线用例

| 模块 | 数量 | 当前暴露的问题 |
| --- | ---: | --- |
| `test_app_model_binding.py` | 1 | 预览身份测试的角色策略依赖未接入本地测试数据库 |
| `test_kn_rag_model_admission.py` | 1 | 助手知识工具测试的身份/可用知识替身没有产出工具 |
| `test_kn_rebuild_write_entries.py` | 4 | 版本服务权限运输未装配，访问未初始化的 permission runtime |
| `test_kn_space_reference_lifecycle.py` | 6 | 测试库缺少已有 processing fence 表 |
| `test_rebuild_page.py` | 11 | 既有 worker 测试的文件替身、业务预期字段等装配问题 |

上述 23 个用例按相同 node ID 在原基线也失败；这里只确认失败状态的对照，不声称它们全部已定位为相同根因，也不声称这些业务场景完成验收。它们没有新增 skip/xfail，保留为可见失败。

## 环境及后续边界

Python 变更 compileall 通过，增量 Ruff 无新增问题，架构守卫无 VIOLATION，`git diff --check` 通过。原知识服务的 38 个 Ruff 问题及 schemas.py 的既有 RULE-3 WARNING 保留。前端本轮无新增实现改动，沿用已通过的 37 项交互测试和完整 lint/typecheck/i18n 结果。

SQLite、ASGI、Celery 生命周期替身和明确的外部传输替身不能替代真实 MySQL/DM8、Worker、FGA、检索/对象存储与浏览器验收。[环境 E2E 清单](./e2e-checklist.md) 保持由用户后续执行；正式合入前仍需要 SDD 特性审查。

## 最终适配文件组合的既有失败 node ID

- `test/knowledge_unification/test_app_model_binding.py::test_actual_preview_gateway_binds_pending_version_and_current_preview_facts`
- `test/knowledge_unification/test_kn_rag_model_admission.py::test_assistant_knowledge_initialization_reuses_publication_transaction`
- `test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_space_delete_clear_keep_projection_order_atomic_refs_and_sync_original_ids[False]`
- `test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_space_delete_clear_keep_projection_order_atomic_refs_and_sync_original_ids[True]`
- `test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_space_projection_failure_keeps_business_refs_and_does_not_purge`
- `test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_clear_does_not_require_deleted_model_execution_or_release_model_binding`
- `test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_folder_delete_does_not_silently_unbind_retained_channel_configuration[False]`
- `test/knowledge_unification/test_kn_space_reference_lifecycle.py::test_folder_delete_does_not_silently_unbind_retained_channel_configuration[True]`
