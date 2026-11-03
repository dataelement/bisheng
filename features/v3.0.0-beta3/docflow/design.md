# Design

## 1. Goals

Use DocFlowLoader at BaseFilePipeline's existing PDF/image entry. A synchronous client is reused by the async loader through asyncio.to_thread. Domain services own orchestration and ORM access; the client owns HTTP; the converter is deterministic and independent of storage. Configuration defaults leave DocFlow disabled. The implementation follows constitution C1-C7 and introduces no public endpoint or production dependency.

## 2. Constraints

The successful MK protocol requires an explicit Host, curl-shaped headers and UTF-8 JSON serialization. API and worker processes may run on different machines. DocFlow returns upright image pixels, not inherently PDF points. Unknown split-task source-page transforms cannot be invented.

## 3. Decisions and alternatives

Use the native Loader rather than the new chunks_string endpoint: that endpoint splits prepared text again and is not the file-preview lifecycle. Reconsider only for a standalone external preprocessing product.

Use SQL checkpoints + temporary MinIO artifacts rather than local caches or Redis-only remote IDs. A worker crash must not discard the only task identity. The existing temporary bucket lifecycle bounds artifact storage; SQL checkpoints require operational retention management.

Persist remote checkpoints in a new SQLModel table, discovered by the existing create_all upgrade flow. A Redis lock with ownership checks protects each tenant/content/configuration key. Raw results reside in MinIO, never in process-local files. A missing artifact is refetched from the known task. Mark the submission boundary before the HTTP call: a crash or ambiguous response requires operator reconciliation instead of duplicate billable work.

Generate Markdown and source spans together. Native four-corner image coordinates become rectangles; PDF positions require an explicit verified transform. Structured fields supplement rather than replace document lines. Unspecified table JSON shapes and split tasks must be surfaced, not silently omitted. Spaces in the old layout_markdown prototype are not the ingestion representation.

Serialize file processing and retries independently of fair scheduling. Persist ingestion checkpoints keyed by tenant, file, chunk digest and target configuration. Confirmed Milvus and ES stages are skipped on recovery. An interrupted write is cleaned by document_id before replay. No cross-store transaction or exactly-once external model-call claim is made.

Use existing error codes for file failures, retaining provider-specific stage text and remote trace IDs; never log credentials, request bodies, or token-bearing URLs. Rollback switches loader_provider back to the previous provider. Operational credentials and middleware tests are environment supplied.

## 4. Current system

### 4.1 Data flow

BaseFilePipeline → DocFlowLoader → DocFlowService/DocFlowClient → converter → standard transformers/splitter → DocFlowIngest → Milvus then Elasticsearch BM25. Preview stops before embedding and shares tenant-scoped raw OCR artifacts with later ingestion.

### 4.2 Contracts

`knowledges.loader_provider=docflow` in the database-backed system settings YAML selects the provider. `ConfigService.get_knowledge()` reads `get_all_config()['knowledges']`; a singular `knowledge` block in the mounted config.yaml does not activate it. Required credentials can use `env:NAME` references. `parser_revision` invalidates cached OCR after changing remote workspace behavior. `max_concurrency` shares local polling slots per account/workspace, but does not bound remote tasks after timeout (see the 2026-11-02 verification report). The loader emits Documents, final-text half-open source offsets and TextBbox artifacts. No parallel text/layout outputs are ingested.

`knowledge_docflow_job` stores a tenant-scoped fingerprint, scope, JSON checkpoint and timestamps. The table is created by the existing discovered-model schema bootstrap. A new whole table does not need a standalone create-table revision under current repository rules.

### 4.3 Responsibilities

| Module | Responsibility |
| --- | --- |
| docflow/client.py | Redacted MK HTTP protocol, token cache, upload/submit/query |
| docflow/converter.py | Deterministic Markdown, conservative columns, explicit grid tables, source spans |
| domain/services/docflow_state.py | SQL state, MinIO artifacts, Redis leases and shared account slots |
| domain/services/docflow_service.py | Remote task checkpoints, recovery and operator reconciliation |
| domain/services/docflow_ingest.py | Chunk snapshots, vector cache, dual-index recovery |
| domain/services/docflow_file_guard.py | Serialize DocFlow file parsing and retry entry points |
| rag/pipeline/loader/docflow.py | Existing loader contract and guarded PDF coordinate scaling |
| rag/pipeline/transformer/docflow_structure.py | Heading-aware sections using the existing character splitter |

## 5. Known pitfalls

| Fact | Consequence if missed | Handling |
| --- | --- | --- |
| Attachment success can return fdId rather than fdAttachFileId | A successful upload is misreported as failed | client.upload |
| Standard preview chunks are consumed after Loader runs | Preview then upload can OCR twice | Persist raw OCR; scope preview keys by tenant/provider/configuration |
| Existing PDF/image extensions do not enable hierarchical splitting | Markdown headings alone have no structural split effect | DocFlow-specific structure transformer |
| Milvus uses auto_id=True | Passing stable IDs does not make Milvus upsert | Cleanup uncertain writes by document_id; stable IDs apply to ES |
| File status updates change timestamps and summaries can be regenerated | A retry can unexpectedly reembed | Restore the confirmed chunk snapshot; exclude generated summary/status time from source identity |
| Token-bearing URLs can appear in requests exceptions | Credentials leak through tracebacks | Raise credential-free stage errors without chaining transport exceptions |
| Artifact expiry and external index deletion are different events | A done checkpoint can refer to a manually dropped index | Coordinate checkpoint invalidation during operational index rebuilds |

## 6. Dependencies and release

Incoming: existing file authorization/tenant context, local original file and file metadata. Outgoing: MK token, fileStream upload, registered submit/query functions, existing SQL/Redis/MinIO/Milvus/ES services. There is no new public authorization bypass or route.

No credentials are committed. Remote deletion APIs, arbitrary table schemas, child-task page mapping and rotated PDF highlighting require provider contracts/samples. Unsupported mappings preserve text or explicitly fail rather than pretending the full feature is supported. See docs/architecture/docflow-ocr.md for configuration, expiry, reconciliation and rollout.

## Revision history

- 2026-10-26: Implemented the approved native provider design and documented verified protocol differences and recovery boundaries. Local mocked integration and SQLite checks are separate from pending live MySQL/DM8 and middleware acceptance.

## 前端引用契约补充（2026-10-26）

平台与客户端解析器白名单接入 docflow。正文坐标页码从 1 开始，DocFlow PDF 查看器使用 startIndex=1；旧 ETL 保留 startIndex=0。OFD 采用已有转换后 PDF，图片使用原图。若忽略此区别，PDF 引用可能偏移一页。实际页面定位仍须目标环境手动验收。
