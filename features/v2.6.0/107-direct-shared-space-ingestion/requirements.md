# F107 共享知识空间直接解析入库需求

**Feature ID**: `107-direct-shared-space-ingestion`  
**Status**: Confirmed  
**Mode**: Implement  
**Created**: 2026-09-03  
**Updated**: 2026-09-03

## 背景

当前 SPACE 文件解析仍通过 `Knowledge.collection_name/index_name` 写入旧的每空间
Milvus collection 与 Elasticsearch index，再由 document projection 从旧 collection
复制到租户共享存储。这使旧存储成为运行时 staging，并与“共享路由后新数据只写共享
存储”的目标冲突。

租户仍采用物理存储隔离：每个租户使用独立的共享 collection/index。查询侧只依赖物理边界，
不使用 `tenant_id` 过滤；为兼容当前共享 Milvus collection 的非空字段约束，writer 在 chunk
metadata 中固定补写 `tenant_id=1`。

## Requirements

### REQ-001 共享路由后的直接入库

当 SPACE 所属租户已开启共享路由时，上传解析与重解析必须在切片、embedding 后直接通过
`SharedSpaceStorageWriter` 写入该租户的共享 Milvus collection 与 ES index，不得初始化、
写入或失败回退到旧的每空间 collection/index。

### REQ-002 租户物理隔离与 metadata 精简

共享 collection/index 名称、路由版本、写冻结和 embedding 模型继续按 `tenant_id` 管理；
共享 chunk metadata 固定包含 `tenant_id=1` 以兼容既有物理 schema，Milvus 表达式和 ES 查询
不得依赖 `tenant_id` 过滤。

### REQ-003 canonical 身份与幂等状态

共享写入前必须取得稳定的 `canonical_document_id`、`canonical_version_id` 和
`content_generation`。同一解析 generation 重试必须幂等；只有共享 Milvus、ES 和 membership
写入均成功后，才允许把 projection 标记为 READY。

### REQ-004 projection 职责收口

正常上传完成后的 projection 只负责发布、引用、移动和删除导致的 `knowledge_ids` membership
收敛，不得再从旧 collection 加载新上传内容。旧 chunk loader 仅允许历史迁移或显式修复使用。

### REQ-005 兼容与失败关闭

未开启共享路由的 SPACE 和非 SPACE 知识库继续使用现有旧链路。已开启共享路由的租户若共享
组件、schema、embedding 或写入失败，文件解析必须失败关闭，不能静默回退旧存储。

## Acceptance Criteria

| ID | 验收结果 | Verification Method |
|---|---|---|
| AC-001 | 已路由 SPACE 上传只调用共享 writer，旧 Milvus/ES 初始化函数均不调用 | pytest 路由分支回归测试 |
| AC-002 | 共享 Milvus/ES metadata 固定写 `tenant_id=1`，查询表达式不含 tenant filter，物理名称仍带租户后缀 | shared storage contract tests |
| AC-003 | 共享写入失败时文件失败且没有旧库回退；重试复用 pending generation | service/state tests |
| AC-004 | 重解析写入新 generation，并由 writer 幂等清理旧 generation | writer + ingestion tests |
| AC-005 | 上传成功后正常 worker 不调用 legacy chunk loader；发布/引用仍可更新 membership | projection tests |
| AC-006 | 未路由 SPACE 与非 SPACE 继续使用原写入链路 | 参数化兼容测试 |
| AC-007 | metadata schema 保持既有非空 `tenant_id` 契约，旧共享 collection 可直接接收新 writer row | schema + writer row tests |

## Includes

- SPACE 上传解析与重解析写入路由。
- 共享 writer/reader 的 metadata、过滤、删除与 ES 文档 ID。
- canonical generation 的准备与完成状态。
- 正常 projection worker 的内容写入职责收口。
- 相关 pytest、lint 与验证记录。

## Excludes

- 删除关系型数据库中的 `tenant_id` 字段。
- 改为全系统单一 collection/index。
- 本次直接物理删除旧每空间存储。
- 自动执行生产 Milvus/ES 数据迁移或路由切换。

## Clarifications

- 2026-09-03：用户确认 collection/index 继续按租户物理隔离。
- 2026-09-03：用户确认 chunk metadata 不需要 `tenant_id`。
- 2026-09-03：用户确认共享路由后的上传解析不得经过旧 collection/index。
- 2026-09-03：根据现有 Milvus 非空 schema 的真实报错，用户调整为 writer 补写 `tenant_id`，默认值固定为 `1`；查询仍不使用 tenant filter。
