# F108 设计

## 方案

以 SPACE 类型决定共享链路，以租户路由记录保存已初始化的物理目标。统一 resolver：非 SPACE 返回 None，SPACE 返回经过校验的路由或抛出初始化错误，永不返回 None。旧 enabled 配置忽略；SQL shared_enabled 保留兼容历史工具但不参与运行时判断。

创建使用路由表目标名；失败不能生成独立空间索引。共享 reader/writer、问答、工作流、全文同步移除开关判断。发布共享投影仅保留共享 writer，缺 writer 报错；版本切换始终推进共享 generation。非 SPACE 的原有适配器继续用于其他知识库和显式历史迁移。

不自动 bootstrap，防止创建空目标掩盖未迁移历史内容。保留模型、schema fingerprint、版本和迁移冻结校验。独立迁移脚本继续支持旧索引作为源，运行时不调用旧内容 loader。

## File Structure Plan

- `core/config/settings.py`、`knowledge/rag/shared_space_storage.py`：配置与强制路由契约。
- `knowledge/domain/services/{knowledge_service,shared_space_projection_support,knowledge_document_projection_service,knowledge_version_service,knowledge_space_chat_service,portal_qa_retrieval_service,portal_global_search_retrieval}.py`：入口与投影收口。
- `api/services/knowledge_imp.py`、`worker/knowledge/`：解析、删除和异步投影。
- `knowledge/domain/repositories/implementations/knowledge_fulltext_source_repository_impl.py`：共享全文分块源。
- `workflow/common/knowledge.py`、`workstation/domain/services/chat_service.py`：外部消费者不回退。
- `test/knowledge/`、`test/workstation/`：契约与相关模块回归。
- `scripts/migrate_shared_storage.py` 及迁移 service：仅必要兼容调整与明确离线边界。

## Verification

REQ-001/002 → AC-001/002/003：先添加无开关与缺路由测试，再实现。
REQ-003 → AC-004：非 SPACE 与混合类型测试。
REQ-004 → AC-005：复用共享 schema、writer、投影、迁移测试；真实 Milvus/ES、DM8 验证记为 MANUAL_REQUIRED。

## 授权与工作区

用户在说明范围与初始化策略后确认执行，复用该授权持续实现。直接在现有分支做最小修改，不切分支或触碰索引区；既有未提交 diff 保留。

## 最终落地补充

- `KnowledgeRag` 的按知识库适配器拒绝 SPACE，只有独立正向迁移可显式读取旧存储。
- 文件问答、目录问答和工作台 SPACE 分支统一进入共享 reader；已有文件授权只用于对应文件的精确范围，后续 canonical、成员代次与文件权限校验保留。
- 目录关键词筛选将共享 ES 命中的 canonical document 映射为当前空间的 READY 文件入口；分块预览使用 canonical document/version/content generation 与空间成员筛选。
- 原文件重建 loader 从 MinIO 解析并使用租户模型生成向量。版本切换、修复和重建不再复制旧索引内容；原文件不可用时失败并进入原有投影重试。
- 回收站恢复在 SQL 事务中推进条目代次并请求投影，提交后入队；跨空间恢复不复制/删除逐空间向量。
- 已初始化 SPACE 创建沿用路由中的目标名称和模型；逐空间模型重建不能替换租户共享模型。
- 离线脚本只保留正向迁移；去掉 reverse 和 switch_to_legacy，失败不解冻切回旧链路。投影修复脚本也不再检查 enabled。
- SQL `shared_enabled` 列和历史错误码保留兼容；不包含 Schema 迁移或线上物理存储清理。
