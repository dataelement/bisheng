# F107 共享知识空间直接解析入库设计

**Feature ID**: `107-direct-shared-space-ingestion`  
**Status**: Confirmed  
**Created**: 2026-09-03

## Goals

- 共享路由生效后，解析内容直接进入租户共享存储。
- 保持每租户独立 collection/index 和现有 routing version/write freeze 保护。
- 为兼容既有共享 schema，chunk metadata 固定补写 `tenant_id=1`；后端过滤器不使用它。
- 保持重试、重解析、membership 更新和旧链路兼容可验证。

## Non-goals

- 不移除 SQL/domain 多租户字段与过滤机制。
- 不改变知识空间权限模型。
- 不在本特性中清理生产旧库或自动切换生产路由。

## Current Architecture

`knowledge_imp.addEmbedding()` 在解析前初始化 `KnowledgeRag` 旧 Milvus/ES client，
`KnowledgeFilePipeline` 在 INGEST 阶段写旧存储。解析成功后 `file_worker` 推进 canonical
generation，projection worker 再通过 `load_shared_content_chunks_from_legacy()` 复制到共享存储。

共享 schema 当前包含非空 `tenant_id`，writer/delete/read 表达式和 ES filter 也重复使用它，
尽管 writer/reader 已经绑定到租户独立 collection/index。

## Target Flow

```text
resolve_space_shared_routing
  ├─ not routed -> existing legacy pipeline
  └─ routed
       -> pipeline LOAD + TRANSFORM only
       -> prepare canonical ingestion target (idempotent generation)
       -> tenant target embedding model
       -> SharedContentChunk[]
       -> writer.upsert_content
       -> writer.update_membership
       -> finalize projection READY
       -> persist KnowledgeFile SUCCESS
```

共享路径任何失败都进入原有 parse failure 状态，不执行 legacy fallback。

## Components

### SharedSpaceDirectIngestionService

新增 domain service，负责：

- 解析租户路由与目标 embedding model。
- 调用 distribution service 准备 canonical identity/generation。
- 将 `Document` 转为带 dense vector 的 `SharedContentChunk`。
- 顺序执行 content upsert 与 membership update。
- 成功后完成 projection generation；失败时保留 pending generation 供重试复用。

### KnowledgeDocumentDistributionService

新增直接入库的 prepare/finalize 方法。prepare 允许 PROCESSING 文件建立稳定 identity；当
`desired_content_generation > applied_content_generation` 且等于 document 当前 generation 时复用，
否则只递增一次。finalize 使用 generation 条件校验后写 READY。

### Shared Writer/Reader

Writer/Reader 仍由 `tenant_id` 绑定并校验 routing snapshot，但：

- schema 保留非空 `tenant_id`，writer 统一补写默认值 `1`；
- Milvus/ES 内容查询按 canonical document/version/generation；
- membership 查询只按 `knowledge_ids`；
- ES `_id`/routing 不再包含 tenant 前缀。

## Failure and Consistency

- canonical prepare 先提交 pending generation，外部写入失败后可安全重试。
- writer 使用 generation 和 deterministic ES `_id` 保证重复调用幂等。
- content 与 membership 均成功后才 finalize READY。
- 文件最终 SUCCESS 仍由现有 parse result owner 提交；查询侧继续按 projection readiness 失败关闭。
- 共享路由开启后不允许 fallback 到 legacy store。

## Schema Compatibility and Rollback

当前共享 collection 已把 `tenant_id` 定义为非空字段，因此直接移除会导致 Milvus
`DataNotMatchException`。本版本恢复原字段定义并由 writer 固定补写 `1`，不要求创建 v2 物理目标。
未来若要真正删除该字段，仍必须通过新 collection/index 迁移，不能在现有 collection 上混写。

## File Structure Plan

| File | Change |
|---|---|
| `knowledge/domain/contracts/metadata_schema.py` | 保留非空 tenant 兼容字段 |
| `knowledge/rag/shared_space_storage.py` | writer 固定补写 tenant_id=1，reader/filter 不使用 tenant 条件 |
| `knowledge/domain/services/shared_space_direct_ingestion_service.py` | 新增直接入库编排 |
| `knowledge/domain/services/knowledge_document_distribution_service.py` | canonical prepare/finalize |
| `api/services/knowledge_imp.py` | shared/legacy 路由分支 |
| `worker/knowledge/file_worker.py` | 避免 direct write 后重复 bump generation |
| `worker/knowledge/document_projection.py` | 正常运行不注入 legacy chunk loader |
| `test/knowledge/*shared*` | 契约、路由、失败与兼容回归 |

## Requirement Traceability

| Requirement | Design |
|---|---|
| REQ-001 | shared routing branch + direct ingestion service |
| REQ-002 | tenant-bound components, metadata compatibility + filter removal |
| REQ-003 | prepare/write/finalize state machine |
| REQ-004 | runtime projection loader removal |
| REQ-005 | explicit route split and fail-closed errors |

## Verification Strategy

- V1：纯 schema/filter/writer contract tests。
- V2：`addEmbedding` shared/legacy 路由与 direct ingestion service tests。
- V2：projection、retrieval、migration 相关测试文件回归。
- V3：不在本地连接真实 Milvus/ES；部署后以一次真实 SPACE 文件重试验证物理 schema 兼容。
