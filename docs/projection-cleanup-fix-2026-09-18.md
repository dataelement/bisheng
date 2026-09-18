# 文档投影与清理恢复修复记录

## 范围和结论

本次完成本地代码修复，不部署，不操作线上记录，不自动重置历史失败次数。
搜索隔离内部入口的已有修复予以保留。其余已存在的自动发布二级分类改动不属于本次修复。

此前线上只读排查发现：文档 35999 的管理入口 128749 曾因内容加载器不可用耗尽重试；
依赖它的发布入口 128788 和库 3637 中的清理占位 128805，也因等待管理入口就绪耗尽重试。
内部 `projection_tombstone` 被搜索结果装配链路当作业务文件处理，引发搜索报错。
这些是此前采样的证据，本轮未重新查询线上，记录当前状态可能已变化。

## 修复内容

| 问题 | 修复行为 |
| --- | --- |
| 内部占位进入文件搜索 | 搜索和统计使用可浏览入口过滤，保留已有错误提示及请求竞态修复 |
| 等待依赖消耗失败次数 | `ProjectionDependencyPending` 独立处理，保留失败次数并释放租约，按 30 秒起步退避至配置上限；等待超过 5 分钟写告警 |
| 最终清理失败无法记录 | 投影完成后保留租约和失败次数，最终清理成功才释放；权限或数据库清理失败进入原有有界重试 |
| 中断、旧任务误清理 | 最终清理校验租约、租户、文档、类型和代次；清理期间取消时，租约到期可接管；较旧代次不能删除较新入口 |
| 管理入口等待其他入口清理也被算作失败 | 采用相同依赖等待机制，且最终删除要求所有入口代次已追平 |
| 主文档/版本缺失发生在失败处理范围外 | 将校验移入已持久化租约的异常处理范围，使错误落库并受重试上限约束 |
| 前 100 条陈旧记录阻塞后续恢复 | 固定截止时间、按主键游标逐页处理；只对 preparing 调度权限/回滚补偿，对耗尽清理记录输出数量和有限样本 |
| 耗尽记录仅重新派发仍不能执行 | 维护工具提供显式 `--recover-failed --apply`，先验证直接依赖和租约、落盘原状态审计，再重置单条失败入口并派发 |

未增加数据库字段或改变外部 API。等待详情存入现有错误字段；复用现有租约和代次字段。
生产 Worker 原本已装配原文件内容加载器，本次保留并运行对应装配回归测试。

## 实施与验证

先新增行为回归，确认等待耗尽、清理末尾失败不落库、旧代次清理、扫描分页及恢复工具缺口出现预期失败，再修复实现。

在 `src/backend` 使用现有 Python 3.10 虚拟环境运行：

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  test/knowledge/test_knowledge_document_projection_service.py \
  test/knowledge/test_knowledge_document_permission_reconcile_worker.py \
  test/knowledge/test_projection_recovery_script.py \
  test/knowledge/test_knowledge_document_distribution_delete.py \
  test/knowledge/test_knowledge_document_permission_activation.py \
  test/knowledge/test_shared_space_projection.py \
  test/knowledge/test_shared_space_direct_ingestion.py \
  test/knowledge/test_space_search_internal_entries.py \
  -q -o asyncio_mode=auto --disable-warnings --tb=short
```

结果：**87 passed**。测试使用实际仓库实现和 SQLite 事务，外部 ES/Milvus/OpenFGA/任务队列以测试替身隔离。
包括实际 Worker 最终清理回调发生权限失败后重试、原文件与其他入口保留、租约过期接管、管理入口先恢复再清理依赖入口，
以及审计写入失败、提交后派发失败。`--help` 可正常运行，差异检查通过。

已有前端定向验证证据未因本次后端修改失效；本轮未重复执行无变更的前端测试。
本地未连接真实 ES/Milvus/MinIO/OpenFGA，也未在 MySQL/达梦环境验证行锁和并发；不能将本地测试等同于生产验收。

## 后续上线和数据处理

1. 发布匹配版本的 API 与默认 Celery Worker，确认周期扫描正常运行；滚动期间不要提前恢复历史失败记录。
2. 先检查源文件、解析/向量服务及共享存储可用性，再预览需要恢复的入口。维护工具只检查元数据和直接依赖，不替代外部服务检查。
3. 按“管理入口恢复并追平代次 → 依赖的待清理入口恢复”的顺序单条操作，保存审计。
4. 复验库 3637 的搜索接口、有效文件数量和预览；确认待清理入口已消失、共享成员关系正确、权限及全文删除任务完成。
5. 观察至少两个扫描周期，确认没有重复异常或持续等待告警，原文件和有效入口保持可用。

工具用法和提交后失败的判定见 [维护脚本说明](../src/backend/scripts/README.md#reconcile_knowledge_document_projectionpy)。
工具恢复会允许 Worker 随后写入共享存储或清理入口；执行后的撤销不能仅靠恢复重试次数。
审计文件应置于持久存储。只有 `prepared` 记录时，先核对数据库与 Worker 日志，不能假定事务未提交。

代码可回退到发布前版本，但回退会重新暴露本次修复的故障；本轮没有数据变更需要回滚。
