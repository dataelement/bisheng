# F109 验证记录

Date: 2026-09-17
Code State: 基于 `43b287356` 的 F109 工作区改动；未提交、未部署。
Overall Status: LOCAL_VERIFIED / MANUAL_VERIFY_REQUIRED

## 实际执行

cwd: `/Users/wenruli/code/project/bisheng/bisheng/src/backend`
runtime: 项目 `.venv/bin/python`（Python 3.10），未新增依赖。

### E-001 回归

```bash
.venv/bin/python -m pytest \
  test/knowledge/test_shared_storage_reconcile.py \
  test/knowledge/test_shared_storage_reconcile_adapter.py \
  test/knowledge/test_shared_storage_reconcile_repository.py \
  test/knowledge/test_shared_storage_reconcile_worker.py \
  test/knowledge/test_shared_only_space_storage.py \
  test/knowledge/test_shared_space_storage_adapter.py \
  test/knowledge/test_shared_space_projection.py \
  test/knowledge/test_shared_space_direct_ingestion.py \
  test/knowledge/test_knowledge_document_projection_service.py \
  test/celery/test_celery_beat_task_registration.py \
  test/celery/test_knowledge_parse_queue_routing.py \
  -q --disable-warnings
```

结果：**172 passed, 186 warnings，18.50 秒，exit 0**。警告为 SQLModel 旧 execute 接口等弃用提示；并非真实外部存储集成结果。

验证了：整批比较后修改、READY 文档扫描、ORM 聚合、历史非入口 pending 不阻塞主版本、快照变更拒绝、内容缺失登记现有代次、提交消息失败保留 pending、正文差异重建、跨租户拒绝、查询失败不当作缺失、单篇/单批隔离、查询/写入熔断、整批失败拆分、两端回读、ES 逐项冲突和清空 JSON 属性、Milvus 响应丢失后去重且保留向量、分页资源关闭、锁防重入/失锁/续期失败、租户分发隔离、真实 Celery 注册与 02:00/Asia-Shanghai 配置、重建摘要及旧主版本代次清理。

测试编写阶段先观察缺模块的失败；旧版本清理回归也曾因原 writer 限定同一版本而失败。新增 worker 测试曾因全局 mock 模块恢复导致 ORM 重复注册，已修正为只恢复对应运行时替身，最终所有相关测试在同一进程组合通过。

### E-002 静态检查

`.venv/bin/ruff check` 对以下新文件执行，结果 **All checks passed / exit 0**：

- `bisheng/knowledge/domain/contracts/shared_storage_reconcile.py`
- `bisheng/knowledge/domain/repositories/interfaces/shared_storage_reconcile_repository.py`
- `bisheng/knowledge/domain/repositories/implementations/shared_storage_reconcile_repository_impl.py`
- `bisheng/knowledge/domain/services/shared_storage_reconcile_service.py`
- `bisheng/knowledge/rag/shared_storage_reconcile.py`
- `bisheng/worker/knowledge/shared_storage_reconcile.py`
- `test/knowledge/test_shared_storage_reconcile*.py`

`git diff --check`：exit 0。

## 验收对应

| AC | 本地证据 | 状态 |
|---|---|---|
| AC-001 | E-001 服务、SQLite Repository | PASS |
| AC-002 | E-001 adapter，保留正文/向量、清空属性和部分失败 | PASS |
| AC-003 | E-001 服务故障注入、拆批、熔断 | PASS |
| AC-004 | E-001 Repository、loader、writer | PASS |
| AC-005 | E-001 worker、Celery 注册/时区 | PASS |
| AC-006 | E-001 分页、回读、源变更拒绝 | PASS（本地）；真实服务 MANUAL_REQUIRED |

## 部署前隔离环境验证

未连接生产 MySQL、ES、Milvus、Redis，也未实际调度全量任务。

在隔离环境准备已初始化共享路由的测试租户及有效 SPACE 文档：

1. 修改 MySQL 名称、摘要、自定义属性、分享关系，执行 `reconcile_tenant_shared_storage`（携带相同租户 header）；核对两端所有切片及原向量。
2. 制造 ES 缺片、Milvus 重复片、旧版本残留；确认登记新内容代次、原投影重建最终 READY，下一轮对账无重复重建。
3. 注入 ES 单项失败、Milvus 插入成功但响应丢失、Redis 续期失败；核对其他文档仍被处理、无误删除、失锁后不发起新写入。
4. 执行过程中并发修改文章/主版本，检查锁等待和变更复核；观察 02:00 Beat 分发及重复启动防护。
5. Linux/DM8 环境验证查询、分页、FOR UPDATE 和嵌套事务。

## 边界

- 不新增表、不新增代次字段、不保存跨轮游标、不反向扫描孤儿数据；重跑从头扫描。
- 每轮按启动时 MySQL ID 上界扫描，期间新建文档由现有实时投影和下一轮覆盖。
- `repaired` 按“存储端 × 文档”计数，并有 `es_repaired`/`milvus_repaired`；重建提交仅代表消息已发送，不代表重建成功。
- `completed_with_pending` 表示扫描已结束但存在异步重建；`completed_with_errors` 包括失败/跳过项；`incomplete` 表示扫描中断。
- 不能证明两端同时缺失相同切片或向量语义正确；复杂损坏、源文件缺失仍需既有重建任务的错误日志定位。
- Milvus 已发出的请求无法通过取消本地协程撤回；请求使用 30 秒超时，失锁停止后续操作，下轮核验收敛。
- 工作区同时出现门户相关并行改动，未修改或回退这些文件。
- `features/` 被现有 `.gitignore` 忽略；本地规格文档已生成，但未强制暂存。
