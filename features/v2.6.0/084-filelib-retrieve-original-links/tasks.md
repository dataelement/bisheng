# Tasks: F084-Filelib 检索返回原文件直链

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0
**状态**: Automated Verified（T001-T006 完成；T007 为 MANUAL_REQUIRED）

---

## 阅读摘要

- 本计划只改变 `POST /api/v2/filelib/retrieve` 既有 `source_url`、`source_full_url` 的值语义。
- `source_url` 是相对预签名路径，`source_full_url` 是同一签名的绝对 URL，有效期固定 7 天。
- 只有最终通过 F069 用户上下文和 `view_file` 可见性过滤、进入 Top-K 响应的文件才允许签发链接。
- 按用户确认，链接签发不检查 `download_file`，不进入下载额度、审计、水印、审批或分发限制链路。
- 原对象缺失时保留 Chunk 并返回两个空字符串；其他 MinIO 异常必须使请求失败。
- 同一响应按唯一文件批量查库，每个唯一文件只检查一次对象、签发一次绝对 URL。
- 不新增数据库、migration、错误码、依赖、配置、前端或其他端点改动。
- 当前工作区有大量与 F084 无关的未提交改动，实施时必须保持不变。

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| `spec.md` | ✅ 已确认 | 用户于 2026-08-21 确认 1B、2B 和 7 天有效期。 |
| `tasks.md` | ✅ 已授权 | 用户于 2026-08-21 授权按 T001-T006 实施。 |
| 实现 | ✅ 自动化范围完成 | 6 / 7 完成；T007 为隔离环境人工门禁。 |
| 验证 | ⚠️ 人工门禁待执行 | V-001 至 V-007 通过；V-008 为 `MANUAL_REQUIRED`。 |

---

## 开发模式与边界

- **后端 Test-First**：原对象解析、签名参数、URL 复用、对象缺失、存储异常和权限边界均先写失败测试。
- **分层约束**：`Endpoint → FilelibRetrieveSourceService → KnowledgeFileRepository / MinioStorage`；Endpoint 不查 ORM，Service 不写 ORM 查询，不新增 DAO。
- **安全边界**：只向链接 Service 传最终可见 Chunk 的合法 `document_id`；测试必须证明无权或过滤掉的文件不会被查询或签名。
- **签名安全**：绝对 URL 只生成一次，相对 URL从它派生；完整 URL、查询串、签名和 Token 不得进入日志、异常文本或测试快照。
- **失败语义**：文件记录/对象不存在降级为空链接；网络、认证、服务端或签名异常不得吞并。
- **兼容性**：除两个 URL 的值外，状态码、响应包装、Chunk 数量、顺序、内容、文件字段和 `total` 保持不变。
- **共享文件约束**：T003-T004 会串行编辑 `filelib.py`、依赖注入与相关测试，禁止并发修改共享文件。
- **环境约束**：自动化测试使用 Fake Repository/Storage 和依赖覆盖，不连接真实数据库、MinIO、OpenFGA、Milvus 或 Elasticsearch。
- **范围控制**：不得顺手修改门户下载、水印、权限模型、MinIO 通用默认值或与 F084 无关的遗留格式问题。

---

## Tasks

### 阶段 1：原文件链接 Service 契约

- [x] **T001**: 编写 `FilelibRetrieveSourceService` 失败测试
  - Done when: 参数化测试先定义持久化 `object_name` 优先、空值回退 `original/{file_id}.{ext}`、无法解析为空、Repository 单次批量读取、非法/重复 ID 去重、同文件单次存在性检查和单次绝对签名、`clear_host=False`、`expire_days=7`、相对 URL 从同一绝对 URL 派生、文件记录/对象缺失为空、非缺失存储异常传播，以及日志不包含完整预签名值；当前 Service 缺失导致测试按预期失败。
  - _Requirements: REQ-002, REQ-003, REQ-005, REQ-006, REQ-007, REQ-009, REQ-010_
  - _Acceptance: AC-01, AC-02, AC-05, AC-06, AC-07, AC-08, AC-09, AC-11, AC-12_
  - _Verification: V-001, V-002, V-005, V-006_
  - _Depends: none_
  - _Boundary: new `src/backend/test/open_endpoints/test_filelib_retrieve_source_service.py` only; use fake repository/storage, no production code or live MinIO_

- [x] **T002**: 实现原文件链接 Service
  - Done when: 新 Service 接收 `KnowledgeFileRepository` 和 MinIO Storage；规范化并去重正整数文件 ID，调用 `find_by_ids()` 一次；复用 `KnowledgeUtils.resolve_source_object_name()`；每个唯一文件至多一次 `object_exists()` 和一次 `get_share_link(clear_host=False, expire_days=7)`；用 `clear_minio_share_host()` 派生相对值；缺失返回空链接，其他异常原样传播；不记录敏感 URL；T001 全部转绿。
  - _Requirements: REQ-002, REQ-003, REQ-005, REQ-006, REQ-007, REQ-009, REQ-010_
  - _Acceptance: AC-01, AC-02, AC-05, AC-06, AC-07, AC-08, AC-09, AC-11, AC-12_
  - _Verification: V-001, V-002, V-005, V-006_
  - _Depends: T001_
  - _Boundary: new `src/backend/bisheng/open_endpoints/domain/services/filelib_retrieve_source_service.py` only; no Knowledge retrieval, permission, repository implementation, storage implementation or global expiry changes_

### 阶段 2：Endpoint 可见性与响应契约

- [x] **T003**: 编写 `/retrieve` 原文件链接 Endpoint 失败测试
  - Done when: Endpoint/Service 边界测试先定义只收集最终 `results` 中的合法唯一 `document_id`；过滤前、无权和 Top-K 外文件不会传给链接 Service；同文件多个 Chunk 复用映射；缺失映射写两个空字符串；F069 目标用户上下文覆盖链接解析；只有 `view_file`、没有 `download_file` 的结果可获得链接；未调用门户下载/额度/审计/水印/审批/分发链路；除 URL 值外固定响应的状态、包装、顺序、字段和 `total` 不变；当前 Endpoint 仍返回门户页面地址导致测试按预期失败。
  - _Requirements: REQ-001, REQ-004, REQ-005, REQ-006, REQ-008, REQ-009, REQ-010_
  - _Acceptance: AC-03, AC-04, AC-07, AC-08, AC-10, AC-11, AC-12_
  - _Verification: V-003, V-004, V-005, V-006_
  - _Depends: T002_
  - _Boundary: `src/backend/test/knowledge/test_knowledge_space_chat_service_retrieve.py` and `src/backend/test/open_endpoints/test_filelib_external_user_context.py` test changes only; no production endpoint edits_

- [x] **T004**: 注入链接 Service 并改造 `/retrieve` 响应组装
  - Done when: `open_endpoints/api/dependencies.py` 复用现有 `get_knowledge_file_repository` 与 `get_minio_storage()` 构造链接 Service；`/retrieve` 在 F069 用户上下文内完成检索和链接解析，只向 Service 传最终 Chunk 的文件 ID；按映射填充相对/绝对 URL，无映射为空；删除当前 Portal Base URL 查询和 `_build_portal_source_urls()` 使用及无效导入；不改变其他字段或异常行为；T003 与既有 Filelib/Knowledge 定向回归转绿。
  - _Requirements: REQ-001, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12_
  - _Verification: V-003, V-004, V-005, V-006_
  - _Depends: T003_
  - _Boundary: `src/backend/bisheng/open_endpoints/api/dependencies.py` and the `/retrieve`-local URL logic/imports in `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py` only; no other Filelib handler, schema, Knowledge permission or portal download changes_

### 阶段 3：接口文档与安全说明

- [x] **T005**: 更新 Filelib API 文档和 SDD 状态
  - Done when: 两份接口文档把门户跳转语义替换为原文件相对/绝对预签名 URL，说明固定 7 天、仅 `view_file`、不要求 `download_file`、不进入额度/审计/水印/分发链路、对象缺失为空、非缺失异常失败、URL 为不可提前撤销的 Bearer 凭证、调用方不得记录完整值，并提供全部脱敏示例；核对 Release Contract INV-16 与最终实现一致；把 spec/tasks 状态更新为真实进度。
  - _Requirements: REQ-003, REQ-004, REQ-006, REQ-007, REQ-008, REQ-009_
  - _Acceptance: AC-01, AC-02, AC-03, AC-08, AC-09, AC-10, AC-11_
  - _Verification: V-006, V-007_
  - _Depends: T004_
  - _Boundary: `docs/api/filelib-openapi-interfaces.md`, `docs/api/filelib-retrieve.md`, F084 SDD metadata and consistency-only review of `features/v2.6.0/release-contract.md`; no source, configuration or live-system mutation_

### 阶段 4：自动化验收与人工门禁

- [x] **T006**: 执行 V3 定向回归并创建 `verification.md`
  - Done when: 相关 Open Endpoints/Knowledge pytest、Ruff format/check、架构守卫、敏感 URL/Token 扫描、文档一致性和 `git diff --check` 均记录实际命令、退出码和摘要；AC-01 至 AC-12 分别标记 `PASS`、`FAIL`、`MANUAL_REQUIRED` 或 `NOT_RUN`；确认未修改其他端点、数据库、migration、配置、依赖、前端、门户下载或权限模型；不把静态阅读冒充真实 URL 可访问性证据。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12_
  - _Verification: V-001, V-002, V-003, V-004, V-005, V-006, V-007_
  - _Depends: T002, T004, T005_
  - _Boundary: read-only validation commands, formatting limited to F084 touched Python files, new F084 `verification.md` and task status only; no real MinIO/OpenFGA/DB calls_

- [ ] **T007**: 在隔离环境执行原文件链接人工验收
  - Done when: 经环境负责人授权后，使用受控 Developer Token 和“有 `view_file`、无 `download_file`”用户调用 `/retrieve`，确认绝对 URL 可直接 GET、相对 URL 拼接正确 Origin 后可 GET、两者访问同一原对象且签名为 7 天；使用无 `view_file` 用户确认无 Chunk/无签名；验证对象缺失为空、存储异常不返回部分结果、日志不含完整 URL；记录脱敏环境、步骤、结果、回滚检查和已签发 URL 的过期处置说明。
  - _Requirements: REQ-001, REQ-003, REQ-004, REQ-006, REQ-007, REQ-008, REQ-009_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-08, AC-09, AC-10, AC-11_
  - _Verification: V-008_
  - _Depends: T006_
  - _Boundary: authorized isolated environment only; never production, never expose full signed URLs in evidence, and do not create/modify real Token, permission tuple, file or MinIO object without separate explicit approval_

---

## Verification Checkpoints

| Checkpoint | 触发点 | 最低证据 | 禁止事项 |
|------------|--------|----------|----------|
| CP-01 | T002 完成 | T001 从红转绿，证明对象解析、7 天单次签名、去重、缺失和异常契约。 | 不修改 Repository/Storage 实现、权限或全局 MinIO 默认值。 |
| CP-02 | T004 完成 | T003 从红转绿，既有 Filelib/Knowledge 定向测试通过，证明只对最终可见结果签发且响应兼容。 | 不扩展到其他端点或门户下载链路。 |
| CP-03 | T006 完成 | V-001 至 V-007 实际证据写入 `verification.md`，每个 AC 有状态。 | 不重复运行同一代码状态和范围的成功命令，不伪报 V-008。 |
| CP-04 | T007 完成 | V-008 隔离环境证据完整且全部敏感 URL 脱敏。 | 未授权环境、生产环境或把完整签名写入证据时必须立即停止。 |

### T006 最终命令范围

后端命令从 `src/backend/` 执行；如实现期间发现受影响测试文件变化，可做最小调整，但必须在 `verification.md` 记录最终范围：

```bash
uv run pytest \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py

uv run ruff format --check \
  bisheng/open_endpoints/domain/services/filelib_retrieve_source_service.py \
  bisheng/open_endpoints/api/dependencies.py \
  bisheng/open_endpoints/api/endpoints/filelib.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py

uv run ruff check \
  bisheng/open_endpoints/domain/services/filelib_retrieve_source_service.py \
  bisheng/open_endpoints/api/dependencies.py \
  bisheng/open_endpoints/api/endpoints/filelib.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py
```

仓库根目录执行：

```bash
bash scripts/arch-guard.sh src/backend/bisheng/open_endpoints/domain/services/filelib_retrieve_source_service.py
bash scripts/arch-guard.sh src/backend/bisheng/open_endpoints/api/dependencies.py
bash scripts/arch-guard.sh src/backend/bisheng/open_endpoints/api/endpoints/filelib.py
rg -n "X-Amz-Signature=[A-Fa-f0-9]{16,}|bst_[A-Za-z0-9]{16,}" \
  features/v2.6.0/084-filelib-retrieve-original-links \
  docs/api/filelib-openapi-interfaces.md \
  docs/api/filelib-retrieve.md \
  src/backend/bisheng/open_endpoints \
  src/backend/test/open_endpoints
git diff --check
```

`filelib.py` 是大型遗留文件；若全文件 Ruff 暴露与 F084 无关的既有问题，必须记录并改用对新增/修改区域的最小充分检查，不得大范围机械格式化。

---

## Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|-------------|---------------------|-------|--------------|
| REQ-001 | AC-01, AC-04 | T003, T004, T006, T007 | V-003, V-004, V-007, V-008 |
| REQ-002 | AC-05, AC-06 | T001, T002, T006 | V-001, V-007 |
| REQ-003 | AC-01, AC-02 | T001, T002, T004, T005, T006, T007 | V-001, V-003, V-008 |
| REQ-004 | AC-03, AC-04 | T003, T004, T005, T006, T007 | V-004, V-005, V-008 |
| REQ-005 | AC-07 | T001, T002, T003, T004, T006 | V-002, V-003, V-007 |
| REQ-006 | AC-08 | T001, T002, T003, T004, T005, T006, T007 | V-001, V-003, V-008 |
| REQ-007 | AC-09 | T001, T002, T004, T005, T006, T007 | V-002, V-008 |
| REQ-008 | AC-10 | T003, T004, T005, T006, T007 | V-003, V-007, V-008 |
| REQ-009 | AC-11 | T001, T002, T003, T004, T005, T006, T007 | V-006, V-007, V-008 |
| REQ-010 | AC-12 | T001, T002, T003, T004, T006 | V-005, V-007 |

---

## 执行顺序

```text
T001 -> T002 -> T003 -> T004 -> T005 -> T006 -> T007
```

T001/T003 是失败测试批次，分别在 T002/T004 转绿。T001-T006 共享 Endpoint 契约和测试夹具，按顺序串行实施；不使用并行 Agent 修改共享代码。T007 只在获得隔离环境授权后执行，不阻塞本地代码交付，但必须在 `verification.md` 标记为 `MANUAL_REQUIRED`，不能伪报完成。

---

## 任务质量门

- [x] 每个任务引用至少一个 `REQ-*`。
- [x] 每个行为任务引用至少一个 `AC-*`。
- [x] AC-01 至 AC-12 均有实现任务或验证任务覆盖。
- [x] 每个任务具有可观察的 Done when、依赖和明确边界。
- [x] 链接 Service 与 Endpoint 两个独立风险批次均测试先行。
- [x] 最终可见性、7 天单次签名、仅 `view_file`、缺失对象和非缺失异常均有正反向测试。
- [x] 完整 URL/签名日志泄漏和无法提前撤销风险已进入文档与验证任务。
- [x] 最终验证复用同一代码状态的证据，不为每个微任务重复跑全套。
- [x] 没有新增 DAO、数据库、migration、错误码、依赖、配置、前端或其他 Filelib 路由任务。
- [x] V-008 明确为需授权的隔离环境人工验证，不混入自动化完成声明。
- [x] 用户已于 2026-08-21 授权按 T001-T006 实施；T007 仍需独立环境授权。

---

## 实际偏差记录

> 实施时只记录真实偏差；没有偏差则写“无”。范围或行为变化必须先更新 `spec.md` 并重新确认。

- T001-T006 已完成；T007 未执行并标记为 `MANUAL_REQUIRED`。
- 测试基础设施会预置精简版 `KnowledgeUtils`；Service 测试通过局部 fixture 恢复 `resolve_source_object_name()` 的既有持久化优先/规范路径回退语义，不修改共享 fixture。
- `filelib.py` 是未统一 Ruff 格式的遗留大文件，`dependencies.py` 也存在既有导入排序债务；为保持最小 diff，未执行全文件机械格式化，新增文件通过完整 Ruff，既有文件的语法、未定义名和新增导入通过定向检查。
- `features/` 被 `.gitignore` 忽略；F084 SDD 文档不会出现在普通 `git status` 中，是否强制纳入版本控制由用户另行决定，本任务不自行暂存。
