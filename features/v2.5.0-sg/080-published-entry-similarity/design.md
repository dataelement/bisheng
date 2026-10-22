# 设计

## 证据与根因

- `knowledge_file_repository_impl.py:find_main_version_files_in_space` 直接 join KnowledgeDocumentVersion.knowledge_file_id，只命中目标库的物理主版本。
- `KnowledgeDocumentDistributionService._create_publish_entry` 创建引用入口，没有独立 KnowledgeDocumentVersion。
- `KnowledgeVersionService` 计算、缓存读取和发布候选输出都假设入口 ID 等于物理主版本 ID，缓存读取还要求文档归属库等于目标库。
- `_fetch_chunk_texts` 在共享 SPACE 按 content_file_id 查询，不能把目标发布入口 ID 当成正文 ID。
- 当前刷新只从解析成功入口调用；发布投影 worker 没有相似刷新接点。
- 前端发布推荐把 target_document_id 直接作为可关联目标；库内相似项直接显示关联按钮。只修改 SQL 会引入预览无权、正文读空和关联报错。

## 实现策略

1. 专用相似候选上下文明确 `entry_file_id`、`content_file_id`、`document_id`、当前版本号与所在目标库。沿用普通物理文件路径；新增发布入口映射，不粗暴放宽所有主版本查询消费者。
2. 仓储按目标库枚举有效普通文件/管理文件及发布入口，解析到同租户当前主版本。校验主版本指针、文档生命周期及入口就绪状态；不包含本需求以外的分享入口新行为。
3. 按目标库入口校验查看权限，按当前内容计算相似度；正文读取仍限定目标库有效 membership。源入口也解析当前主版本，保留 F076 分类/二级分类/业务域分组及公司限制。不能为读取正文而绕过目标库过滤。
4. 候选缓存保存目标入口身份和 canonical 文档身份，读取时校验两者仍一致；入口与正文 ID 分离，不要求原文档归属库迁到目标库。签名包含当前主版本及 generation，按实际入口可用状态过滤撤回/失效项。

   无 Schema 变更：在文件现有 user_metadata 的保留键 `_similarity_snapshot` 保存当前比较签名，锁行合并，不覆盖并发业务元数据；正文解析排除该内部键。候选行与快照分步提交期间不匹配的结果安全隐藏，任务重试可重新计算。列表读取不重新执行全文复核；徽标对候选相关 ID 分批读取快照，避免逐条查询整个知识库。
5. 发布入口就绪后持久化刷新意图，复用后台任务/重试基础设施。刷新新增目标入口与目标库现有候选比较；并发发布、重复投递及任务发布失败均须有可恢复证据，不在列表读取里全库重算。不重开 similar_status=2 的已处理入口。

   发布可能迁入管理入口，因此在 `apply_projection_result` CAS 成功的同一事务为就绪管理/发布入口登记 `refresh_similarity`，按文件、所在库、文档及代次幂等；沿用默认后台任务 worker 的失败预算。旧代次任务不覆盖新代次状态。
6. 推荐结果增加兼容的入口/内容与可关联能力信息，旧普通文件默认行为不变。前端预览使用目标库入口；发布/库内版本选择器仅接受原业务允许关联的目标。禁止通过本次相似识别给原文档新增管理权限或为发布入口补造 V1。

## 文件范围

- `knowledge/domain/repositories/interfaces/knowledge_file_repository.py`、`implementations/knowledge_file_repository_impl.py`：专用候选枚举。
- `knowledge/domain/schemas/knowledge_version_schema.py`：候选上下文/兼容能力字段；必要时独立小文件。
- `knowledge/domain/services/knowledge_version_service.py`：最小接入，身份解析/缓存适配提取独立服务，避免继续扩大大文件。
- `knowledge/domain/services/knowledge_document_projection_service.py`、`worker/knowledge/document_projection.py` 及既有后台任务 owner：发布就绪后的持久刷新意图。具体事务接点在实现前进一步读取，不另起不受管理的任务状态。
- `src/frontend/client/src/pages/knowledge/SpaceDetail/SimilarDocumentDialog.tsx`、`FilePublishDialog.tsx` 与对应 API 类型：入口预览和能力约束；不引入新关联业务。
- `test/knowledge/`、`test/approval/` 与现有前端组件测试：一层主要服务集成，针对入口权限/正文身份和持久化边界补独立测试。

## 风险、验证与回退

V1 定向复现候选漏选；V2 覆盖实际仓储及共享正文过滤、入口预览/能力契约；V3 重点验证发布完成意图与候选刷新、撤回、重复投递、并发主版本变化及权限拒绝。真实 MySQL/DM8/OpenFGA/ES/部署需分别报告。无 Schema 迁移、线上重算或自动合并。

回退代码停止新候选行为及刷新接点；已有候选读取必须仍安全过滤失效入口，不通过批量删候选实现回退。新任务种类若产生旧 worker 不认识的消息，部署回退前先暂停/清空该类任务派发，持久记录保留供新 worker 接续。
