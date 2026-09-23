# 本地验证

Overall: VERIFIED（本地代码与隔离测试）；真实 ES/Milvus/MySQL/DM8/OpenFGA 联调：MANUAL_REQUIRED。

环境：`src/backend/.venv/bin/python`，Python 3.10.19。未提交、未部署、未执行真实迁移。

| Evidence | Code State | Command / Step | Result | Scope |
|---|---|---|---|---|
| E-001 | 实现前，新增保留物理 ID 断言 | `.venv/bin/python -m pytest test/knowledge/test_knowledge_migration_runtime_repository.py -q -k version_chain_switch --disable-warnings` | FAIL，2 个参数场景均在新物理 ID 断言失败，原因符合预期 | AC-1 |
| E-002 | 完成元数据迁移与批量执行后的工作树 | 下方相关回归命令 | PASS，217 passed，561 warnings，6.34s | AC-1/2/3/4 |
| E-003 | 增加迭代器关闭、ES 部分删除失败、来源快照恢复验证；生产逻辑与 E-002 相同 | `.venv/bin/python -m pytest test/knowledge/test_migration_metadata_writer.py test/knowledge/test_knowledge_migration_runtime_repository.py -q --disable-warnings --tb=short` | PASS，10 passed，11 warnings，0.90s；与 E-002 重叠 8 项，新增 2 项 | AC-1/2/4 |
| E-004 | 最终工作树 | 修改范围 Ruff `--select F,E9`、19 个文件 arch-guard、`git diff --check` | PASS。只格式化修改区间，17 个文件格式化前后 AST 相同；最后只给测试 helper 增加已有导入类型注解 | 全部 |

E-002 可重现命令（工作目录 `src/backend`）：

```sh
.venv/bin/python -m pytest $(rg --files test/knowledge | rg 'test_knowledge_migration|test_migration_|test_shared_space_storage_adapter|test_knowledge_document_distribution_publish|test_shared_space_projection|test_fulltext_migration_lifecycle') -q --disable-warnings --tb=short
```

主要可观察结果：

- 普通迁移保留 1001/1002 物理文件 ID、版本 ID、文档 ID 和内容代次；清理阶段仍保留原物理行。
- 迁移适配器未调用原文件内容加载器；存储有状态替身验证正文/向量保持不变、其他知识库成员保留、重复执行去重、合并前保留来源。
- ES Bulk 返回部分失败、共享内容缺失、覆盖内容删除部分失败均抛错；不会把这些情况标记为完成，也不会退回解析。
- 普通发布默认行为保持；迁移发布单独验证不增内容代次，合并允许规范文档/代次切换但保留物理文件和版本。
- 批量仓储实际 SQL 计数：领取 20 个单元为 2 次 SELECT；批量检查点校验为 1 次 SELECT。25 单元按 20+5 领取；过期执行令牌不能写检查点或继续数据库切换。
- 一份文档失败不阻断批内其他文档。保留链接发布先提交、迁移记录恢复时，来源快照不因目标补偿而丢失。

## 未验证与部署边界

- 未运行真实双存储、真实权限服务或 MySQL/DM8 并发锁测试；SQLite/替身不能证明生产延迟与吞吐。
- 部署需要统一更新迁移 Worker，不混跑旧执行逻辑；原已切换且没有来源身份快照的批次会明确报错，需单独检查恢复。
- 数据库与外部存储仍非原子事务，保留原有检查点恢复机制；MinIO 历史删除函数的日志式失败处理未纳入本次重解析/批量修复。
