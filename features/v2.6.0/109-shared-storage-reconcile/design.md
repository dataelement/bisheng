# 技术设计

## 流程

Celery Beat → 租户分发 → Redis 租约 → MySQL ID 上界/游标分页（100 篇）→ 批量快照 → 两端分页读取 → 内存差异列表 → 小批锁定 MySQL 文档与入口并复核 → 两端属性修复/内容重建登记 → 回读 → 下一批 → 汇总。

## 文件落点

- `knowledge/domain/contracts/shared_storage_reconcile.py`：快照、差异与统计，无基础设施依赖。
- `knowledge/domain/repositories/{interfaces,implementations}/shared_storage_reconcile_repository*.py`：ORM 批量查询、锁定复核及复用现有内容代次重建登记。
- `knowledge/domain/services/shared_storage_reconcile_service.py`：纯编排、对比、有限重试、拆批隔离、熔断及日志。
- `knowledge/rag/shared_storage_reconcile.py`：复用共享 writer 校验，Milvus iterator/ES scroll 全量读取；ES bulk 属性更新；Milvus 保留向量插入后删除已观察的旧主键，失败重试重新读取，禁止盲目重复插入。
- `worker/knowledge/shared_storage_reconcile.py`：租户任务锁续期、Repository 注入、调度现有投影任务。
- `core/config/settings.py`、`worker/__init__.py`：注册默认 02:00 调度。
- `shared_space_content_loader.py`：重建补入已存摘要，避免修复后再次丢失。
- `rag/shared_space_storage.py`：新代次成功后按规范文档清理更旧代次（含旧主版本），避免对账重建后仍反复发现旧版本残留。

## 边界与决策

复用现有 schema，校正 document_name/abstract/upload_time/update_time/uploader/updater/user_metadata/knowledge_ids/knowledge_id/membership_generation。关系代次与检索 resolver 一致，取 content_generation 和有效入口 desired_entry_generation 的最大值；对账以锁定后的 MySQL 为准纠正错误代次。不新增分类、标签字段，不同步入口私有别名。属性来自当前主文件，人员来自 MySQL 用户；缺失主版本/解析中/进行中的投影单独记录跳过。关系从 active 且未软删除的 manager/publish/share 重新聚合。

修复只触及匹配版本/代次的已观察记录。检测内容问题时，在锁下推进现有 content_generation，复用 pending 扫描与现有投影任务，避免同代次 Milvus 完整性捷径。Celery 投递失败不会丢失 MySQL pending 意图。任务不自动删除数据库不存在的文档，也不改业务权限。

每端失败有限重试（最多 3 次），连续 3 批失败后本轮暂停该端，另一端继续；跨端内容比较必须两端均成功。修改失败只重试失败文档，批量整体失败拆分隔离。MySQL 分页失败终止本轮；单批快照读取失败跳过该批并统计。外部调用有客户端超时，线程写入不能靠 asyncio 取消假装完成，失锁停止后续写。每次写前检查 Redis 所有权和共享路由。

无跨库原子事务；源快照复核和有界数据库锁防止常规业务并发覆盖。失锁时正在发送的单次请求可能已生效，下轮幂等校验收敛。日志不打印正文、自定义属性值或凭据，只记录 ID、字段名、错误类型、阶段和计数。

## 发布、回退与验证

仅代码交付；发布后默认加入 02:00 调度，无共享链路开启开关。无 schema 迁移。代码回退停止新任务，不撤销已正确同步的属性。真实 ES/Milvus、Redis 及 DM8 集成验证需隔离环境，未执行不得标记通过。

REQ-001→AC-001；REQ-002→AC-002/004/006；REQ-003→AC-003；REQ-004→AC-005；REQ-005→AC-006。
