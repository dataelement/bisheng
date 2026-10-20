# 设计

## 当前链路

`FilelibSyncService` 写入 `filelib_sync_endpoint` 和开发者令牌 ID → 入队 → `KnowledgeFilePipeline` 下载原件 → 解析/切分/入索引 → `persist_parse_result_with_fulltext_intent` 同事务写最终状态及全文意图。现有失败没有明确区分原文件不可读；`KnowledgeBackgroundService` 已有持久化 `delete_file` 补偿。

## 实现

1. 新增 `knowledge/domain/services/knowledge_source_file_validation.py`：仅对带接口来源和令牌标记的文件执行本地原件校验；PDF 使用现有 PyMuPDF，现代 Office 校验 ZIP/必要 XML，Office OLE 使用已有 xlrd 的容器读取。只有明确加密/结构损坏抛专用 `10958` 错误；I/O、资源上限、未知格式/转换工具问题不归类。无新增依赖。

   Office 校验预算为原件及展开内容各 128 MiB、最多 10000 个条目；超过预算仍走既有解析流程，不因预算不足自动删除。老式 DOC/PPT 的专有加密、企业 DRM 或未被上述结构校验识别的损坏继续保留；不声称覆盖所有不可读格式。
2. `KnowledgeFilePipeline.prepare_local_file` 下载完成后、解析器前校验；独立于问答附件管线。
3. 新增 `UnreadableSyncFileRepository` 接口和实现。解析最终状态提交前，专用错误 + 接口来源同时满足才尝试锁行校验。仅删除未分发、无历史的初始物理文件；初始 V1 及其空文档随单条清理。跨租户、已回收、对象/状态变化、已有内容产出、任何版本或引用/审批/纠错关系均拒绝。仓储内 ORM 查询自动租户隔离，兼容 MySQL/DM8。
4. 删除与持久化 `delete_file` 清单、全文删除意图同事务提交，失败整体回滚。清单保留原元数据、失败原因及产物快照，不删除审计。成功删除后不再 refresh 已删模型。
5. `delete_file` 仅在新增 `cleanup_permissions` 标志下先清理文件权限元组，使用统一 PermissionService 严格调用；失败由已有任务预算补偿，完成检查点后才清理对象。现有任务行为不变；共享 SPACE 未经正文装载，不存在新增向量内容，全文按既有 outbox 删除；有既往正文/分发痕迹则不自动删。

## 文件计划

- `common/errcode/knowledge.py`：专用原因。
- `knowledge/rag/knowledge_file_pipeline.py`：原件校验接点。
- `knowledge/domain/services/knowledge_fulltext_parse_hook.py`：最终状态事务接点。
- `knowledge/domain/repositories/{interfaces,implementations}/unreadable_sync_file_repository*.py`：锁、关系保护、删除和持久清单。
- `knowledge/domain/repositories/implementations/knowledge_background_repository_impl.py`、`knowledge_background_service.py`：可选权限清理阶段。
- `test/knowledge/`：真实原件、SQLite 事务与后台恢复；复用既有解析生命周期和后台测试。

## 验证与回退

AC-01 使用真实加密 PDF/损坏压缩包和有效文件；AC-02/03/04 以 SQLite 仓储为主要层，参数化拒绝、回滚、幂等；AC-05 使用现有后台任务服务的受控外部替身。真实 DM8/ES/Milvus/OpenFGA 在本机不做线上验证，保留部署验收项。仅后端行为，无新增页面，不制作与业务无关的浏览器演示。

回退代码可停止后续自动删除；已删除记录和已清理原件不可通过代码回退恢复。部署须同时更新解析和默认 worker。新权限阶段标志对旧任务无影响；无 Schema/运行配置修改。
