# 工作流逻辑删除验证记录

日期：2026-11-04。代码在 `codex/004-workflow-soft-delete` 完成，合入目标为 `feat/3.1.0-beta1`。尚未部署；MySQL/DM8 实机与部署 API 验收待完成。

## 实现结果

- 工作流主记录以 `is_delete=1` 保留，与关联版本在同一事务更新；其他类型维持物理删除。
- 普通查询、UNION 列表及计数、模板来源、推荐、权限迁移、原始 SQL 归属/共享扫描、配额排除已删除记录。
- 新操作与草稿预览不可使用已删除工作流；主记录旧对象保存、版本创建/保存/切换受父资源未删除检查和行锁保护。
- 历史使用原有快照或有限元数据 Repository，原会话/审计/文件权限不变；不对外返回内部删除字段。
- 保留正常工作流的单版本恢复功能。不新增删除协调、在途状态机或自动补偿。

## 已执行

使用 `UV_CACHE_DIR=/private/tmp/bisheng-workflow-uv-cache uv run --no-sync ...`，cwd 为 `src/backend`。

| 检查 | 结果 |
|---|---|
| 针对性回归：`test/workflow/test_flow_soft_delete.py`、`test_workflow_offline_input.py`、`test_flow_dao_tenant_isolation.py`、`test_flow_dao_square_params.py`、`test/database/test_alembic_single_head.py`、`test/app_template/test_template_api.py`、新 F004 部署 E2E 文件 | 72 passed，1 skipped；跳过的是 opt-in 部署 E2E |
| 工作流目录全选 + 迁移单 head 回归 | 247 passed，5 failed，7 skipped；相同选择在变更前基线为 227 passed，6 failed，7 skipped，无新增失败 |
| 新行为 RED → GREEN | 首轮 9 项失败复现物理删除/未过滤/旧对象保存；新增版本恢复同步异步用例先失败后修复通过 |
| 迁移 SQLite 行为 | 存量默认 0、非空、重复 upgrade、拒绝无保护 downgrade 均通过；不替代双库实机验证 |
| `alembic heads` | 单一 `v310b1_f004_workflow_soft_delete`，父为实测原 head `v310b1_f003_audit_operator_dept` |
| Ruff format / lint 对照 | 23 个变更 Python 文件已格式化；0 新增 lint，106 个存量诊断，未宣称全仓 lint 通过 |
| 架构守卫对照 | 0 新增发现；原 `api/v1/workflow.py` 直接模型导入 warning、`common/chat/clients/workflow_client.py` 层依赖 violation 仍与基线一致，未在本特性重构 |
| `git diff --check` | 通过 |

## 基线失败明细

变更前代码通过 `git archive HEAD src/backend` 导出到 `/private/tmp/bisheng-workflow-baseline`，复用现有依赖且指定基线 PYTHONPATH 执行相同工作流选择。

现工作区与基线共有的 5 项失败：

- `test/workflow/nodes/test_docx_replace.py::TestDocxReplacer::test_case`
- `test/workflow/nodes/test_docx_string.py::TestDocxStringClassification::test_patterns`
- `test/workflow/nodes/test_docx_string.py::TestDocxStringClassification::test_text_classification`
- `test/workflow/test_retrieval_question.py::test_knowledge_retriever_skips_retriever_setup_for_empty_questions`
- `test/workflow/test_retrieval_question.py::test_rag_node_skips_retrieval_for_empty_questions`

基线还失败 `test_workflow_offline_input.py::test_same_connection_rechecks_status_for_each_card`：helper 通过 `__new__` 绕过初始化，未 stub 现有部门并发租约服务。本次只补 helper stub，未修改部门并发生产逻辑。

全套 `pytest test/ --maxfail=1` 在收集 `test/api/test_audit_query_entry_surface.py` 时出现 `StreamableHTTPSessionManager.__init__()` 不支持 `max_request_body_size`。同文件在变更前基线也复现该收集错误，因此全套未能执行完成。

## 未执行与发布要求

- 真实 MySQL/DM8 升级、并发事务/行锁及完整权限服务集成尚未验证；SQLite 不证明实际行锁行为。
- 部署 API E2E 已生成并执行到 skip：`test/e2e/test_e2e_f004_workflow_soft_delete.py`，需 `F004_E2E=1`、`E2E_API_BASE` 及专用普通创建者/无授权同租户/其他租户账号 token；仅操作自己创建的唯一前缀工作流。
- 上线前迁移并清退旧进程；保留过滤和禁止物理删除的兼容行为后才能回滚，不能直接移除标记。
- 手工检查：列表/搜索/数量、新调用、同名新建、配额释放、分享失效、历史会话和附件，使用非管理员、管理员及跨租户账号；不把在途任务必停或必成作为验收条件。

## AC 追溯

AC-01、AC-02、AC-06、AC-07、AC-10、AC-11 由真实 SQL 和迁移测试覆盖主要行为；AC-03 有新预览与模板来源测试；AC-04 有历史元数据保留与不返回定义断言，原历史接口/附件授权待实机回归；AC-05、AC-09 有真实删除入口与 SQL、外部权限边界 stub 的顺序测试；AC-08 有既有租户谓词回归，真实非管理员与跨租户 API 留待部署 E2E。局部验证不等同所有 AC 的真实环境验收完成。
