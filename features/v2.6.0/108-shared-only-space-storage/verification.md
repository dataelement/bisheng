# F108 验证记录

状态：本地代码完成；定向回归存在已复现的基线失败。未部署、未操作线上数据。

## 代码与环境

- 基线：`a04cf9ab8`；当前未提交 diff 与新增代码/测试 SHA-256：`55c781af2064115e5bd4529c828083bc687b894d5cf4ff15d2771c8f80319fa0`。
- 目录：`src/backend`；解释器：`.venv/bin/python`（Python 3.10）。
- 保留执行前已有的门户分类浏览修改和前端工作区；暂存区仍为空。

## E-001 定向模块回归

每个模块独立运行，避免现有全局 mock / tenant 事件夹具污染：

```bash
.venv/bin/python -m pytest <下表文件> -q --disable-warnings
```

| 模块 | 结果 | 日志 |
|---|---|---|
| `test/knowledge/test_shared_only_space_storage.py` | 26 passed, 8 warnings in 3.63s | `/tmp/f108-regression-00.log` |
| `test/knowledge/test_shared_space_storage_adapter.py` | 40 passed, 6 warnings in 2.62s | `/tmp/f108-adapter-final.log` |
| `test/knowledge/test_shared_space_direct_ingestion.py` | 8 passed, 6 warnings in 2.53s | `/tmp/f108-regression-02.log` |
| `test/knowledge/test_shared_space_projection.py` | 22 passed, 114 warnings in 2.01s | `/tmp/f108-regression-03.log` |
| `test/knowledge/test_knowledge_document_projection_service.py` | 10 passed, 52 warnings in 0.39s | `/tmp/f108-regression-04.log` |
| `test/knowledge/test_shared_storage_migration.py` | 14 passed, 6 warnings in 2.66s | `/tmp/f108-regression-05.log` |
| `test/knowledge/test_knowledge_retrieval_scope_resolver.py` | 40 passed, 1 warning in 0.22s | `/tmp/f108-regression-06.log` |
| `test/knowledge/test_knowledge_space_chat_service_retrieve.py` | 48 passed, 8 warnings in 3.90s | `/tmp/f108-regression-07.log` |
| `test/knowledge/test_portal_global_search_shared_retrieval.py` | 35 passed, 6 warnings in 2.97s | `/tmp/f108-regression-08.log` |
| `test/workstation/test_portal_qa_required_strategy.py` | 10 passed, 6 warnings in 3.41s | `/tmp/f108-regression-09.log` |
| `test/workstation/test_portal_qa_knowledge_scope.py` | 19 passed, 8 warnings in 3.72s | `/tmp/f108-regression-10.log` |
| `test/knowledge/fulltext/test_fulltext_source_repository.py` | 6 passed, 7 warnings in 1.96s | `/tmp/f108-regression-11.log` |
| `test/knowledge/test_knowledge_recycle_bin.py` | 15 passed, 14 warnings in 2.61s | `/tmp/f108-regression-12.log` |
| `test/knowledge/test_knowledge_version_service_set_primary.py` | 6 passed, 15 warnings in 0.63s | `/tmp/f108-regression-13.log` |
| `test/knowledge/test_knowledge_version_service_similar_scan.py` | 1 failed, 25 passed, 157 warnings in 2.44s | `/tmp/f108-similar-final.log` |
| `test/knowledge/test_knowledge_document_distribution_delete.py` | 13 passed, 480 warnings in 0.86s | `/tmp/f108-regression-15.log` |
| `test/knowledge/test_portal_qa_pipeline.py` | 6 passed, 8 warnings in 3.90s | `/tmp/f108-regression-16.log` |
| `test/knowledge/test_shougang_portal_advanced_search.py` | 12 passed, 6 warnings in 3.00s | `/tmp/f108-regression-17.log` |
| `test/knowledge/test_portal_search_batch_filters.py` | 15 passed, 6 warnings in 3.12s | `/tmp/f108-regression-18.log` |
| `test/test_knowledge_space_chat_service.py` | 11 passed in 1.19s | `/tmp/f108-regression-19.log` |

合计：381 passed，1 failed。失败为 `test_version_recommendations_skip_cached_multi_version_candidates`，原始 HEAD 同一命令为 25 passed / 1 failed，日志 `/tmp/f108-baseline-similar.log`。这是既有多版本候选缓存过滤问题，本次未修改。

## E-002 扩展检查与基线对照

- 工作流 `test_knowledge_space_scope.py`（12 passed / 1 failed）、`test_user_selected_knowledge.py`（20 passed / 1 failed）均在原始 HEAD 复现，原因分别是用字符串冒充 SQL session、绕过构造函数后缺少 retrieval_runtime。新 shared-only 测试直接验证了工作流按类型选路及混合类型拒绝。
- 旧 `test/knowledge/test_knowledge_space_chat_service.py` 的 5 个失败、`test_portal_qa_tree_selection.py` 的 2 个失败均在原始 HEAD 复现。
- 扩展运行旧 `test/test_knowledge_space_service.py`，原始 HEAD 有 116 failed / 100 passed。本次初次结果新增的 2 个失败均调用已移除的逐空间查询函数，对应用例已移除；共享查询的批量召回、embedding 复用、筛选和授权由共享检索测试覆盖。其余失败名称集合与基线一致，不声称旧整套测试通过。
- 基线运行位于独立临时 worktree `/tmp/bisheng-f108-baseline`，没有覆盖当前工作区。

## E-003 静态与边界核对

- 43 个涉及的 Python 文件语法编译通过。
- `git diff --check`：exit 0。
- Ruff 检查 `E9,F63,F7,F82,F401,F841`：新增问题 0；5 个既有问题与原始 HEAD 对照一致，详见 `/tmp/f108-static-results.json`。
- 运行时无 `knowledge_space_shared_storage.enabled`、`shared_enabled` 条件分支。旧向量读取仅出现在显式离线正向迁移。
- 未修改 Milvus metadata schema，保留历史 `tenant_id` 非空字段；未修改 SQL schema。

## 验收映射

| 验收 | 本地证据 | 结论 |
|---|---|---|
| AC-001 无需启用开关 | shared-only 路由测试；adapter 的历史 shared_enabled 默认 False，覆盖共享读写 | PASS |
| AC-002 缺初始化/后端异常不回退 | shared-only、adapter、portal required strategy | PASS |
| AC-003 入口共享路由与自定义目标 | ingestion、projection、fulltext、shared-only、workstation、portal | PASS |
| AC-004 非 SPACE 与混合请求边界 | shared-only 参数化类型用例、组织知识库原路径回归 | PASS |
| AC-005 版本、冻结、权限和 CAS | adapter、resolver、projection、distribution delete | PASS（本地） |

## 线上验证与部署前提

MANUAL_REQUIRED：真实 Milvus / ES / MinIO / DM8 的端到端验证没有执行。部署前需确认每个租户共享路由已有 collection_name、index_name、embedding_model_id、schema_fingerprint，并完成历史内容迁移和投影收敛。
建议在测试环境验证：上传/重解析 → 发布/分享 → 三类检索与文件问答 → 主版本切换 → 撤回/回收站跨空间恢复，检查旧索引无新增写入和共享成员收敛。
回退代码使用原版本；共享写入后的数据回退需要独立迁移，旧开关不能切回旧存储。本次没有执行迁移、删除存储、部署、提交或推送。
