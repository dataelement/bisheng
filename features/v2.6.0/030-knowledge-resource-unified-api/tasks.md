# Tasks: F030-knowledge-resource-unified-api（知识资源统一对外 API · v2 filelib 改造）

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-06-02 /sdd-review 通过；INV-6 cursor 冲突已解决、PRD 同步 |
| tasks.md | ✅ 已拆解 | 2026-06-02 /sdd-review tasks 通过（21 项检查，AC 追溯完整） |
| 实现 | ✅ 完成 | 9 / 9（T01-T09）；单测 16 passed + e2e 12 passed（真实后端，含空间上传/keyword 搜索） |

---

## 开发模式

**后端 Test-First（务实版）**：先写 API 端到端测试（pytest + httpx）覆盖 AC，再写实现。
本特性**纯后端 v2 RPC 改造，无前端、无新表、无 Worker**。核心是 facade 分派 + cursor 适配 + 代用户身份，
业务逻辑全部复用既有 `KnowledgeService` / `KnowledgeSpaceService`，**不新增 DAO 入口、不在 endpoint 写业务**。

**测试基线**：测试落 `src/backend/test/knowledge/`；若 `aretrieve_chunks` / Milvus / ES 难以 mock，
对应检索类 AC 标 `**测试降级**: 手动验证 + TODO`，并在「实际偏差记录」说明。

**自包含任务**：每个任务内联文件、逻辑、测试上下文，实现阶段不需要回读 spec.md。

---

## Tasks

### 基础设施（无测试配对）

- [x] **T01**: 错误码定义
  **文件**: `src/backend/bisheng/common/errcode/knowledge.py`
  **逻辑**: 新增 `KnowledgeTypeNotSupportedError`（`Code = 10962`，继承 `BaseErrorCode`，msg="不支持的知识资源类型"）。
  复用现有：`KnowledgeExistError`(10900)、`KnowledgeNoEmbeddingError`(10901)、`KnowledgeInvalidCursorError`(10991)；
  空间侧复用 `SpaceLimitError`(18001)、`SpaceFolderNotFoundError`(18010)、`SpacePermissionDeniedError`(18040)。
  release-contract.md 模块编码 109 行已登记（无需再改）。
  **覆盖 AC**: AC-04, AC-05
  **依赖**: 无

- [x] **T02**: 代用户身份解析封装（user_id → 权限上下文）
  **文件**: `src/backend/bisheng/open_endpoints/domain/utils.py`（与 `get_default_operator_async` 同处）
  **逻辑**: 新增 `async def resolve_operator(user_id: Optional[int]) -> UserPayload`：
  - `user_id` 为空 → 返回 `get_default_operator_async()`（默认操作人，维持现状）；
  - `user_id` 有值 → 按该 user_id 构造 `UserPayload`（查 `UserDao` + 角色/租户），用于后续 `rebac_list_accessible` / `PermissionService` 与 `permission_ids` 计算。
  user_id 不存在用户 → 抛 `NotFoundError`。**这是 AD-02 的统一入口，列表/检索/文件列表共用。**
  **约束**: 不得手写 `WHERE tenant_id`（多租户自动注入）；权限判断走 `PermissionService`。
  **覆盖 AC**: AC-03, AC-18, AC-28
  **依赖**: 无

### 后端 Service 适配（Test-First 配对）

- [x] **T03**: 知识库文件列表 cursor 适配方法（伪游标，底层维持现状）
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_service.py`
  **逻辑**: 新增 `aget_knowledge_files_cursor(...)`（**不改动现有 `aget_knowledge_files`，避免破坏 v1 调用方**）。
  按 F027 AD-15 伪游标模式实现：
  1. `decode_cursor(cursor, expected_key_len=1, context="filelib_file|kb")` → `page_num`（首页默认 1）；失败抛 `KnowledgeInvalidCursorError`(10991)，**不静默 fallback 首页**。
  2. 复用现有 `KnowledgeFileDao.aget_file_by_filters(page=page_num, page_size=page_size+1)`——**多取 1 行探测 has_more**。
  3. **不调用 `acount_file_by_filters`**（不算 total，满足 INV-6"不得为算 total 扫描全部 batch"）。
  4. `has_more = len(rows) > page_size` → 截断到 page_size；`next_cursor = encode_cursor((page_num+1,), context=...)`（无更多则 None）。
  5. 复用现有权限校验（`ensure_knowledge_read_async`）、tag 搜索、title/tags 装饰、`writeable` 计算（按传入身份）。
  6. 返回 `(PageInfiniteCursorData[KnowledgeFileResp], writeable)`。
  **测试**: `test/knowledge/test_v2_filelib_unified.py::test_kb_file_list_cursor`（首页 has_more/next_cursor、翻页、非法 cursor→10991、无 total 字段）
  **覆盖 AC**: AC-26, AC-29, AC-06b（cursor 错误码）
  **依赖**: T01

- [x] **T04**: 知识空间列表口径（我创建的 + 我加入的）+ 文件列表 user_id 适配
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`
  **逻辑**:
  - 列表：复用 v1 `/mine` + `/joined` 既有路径（`_format_member_spaces` / `async_get_spaces_by_ids` / `async_count_spaces_by_user`），
    合并去重为单一"我创建的 + 我加入的"口径，返回 `PageInfiniteCursorData`（对齐 v1 knowledge 列表的 cursor 形状）。"我"= 传入身份（user_id 或默认操作人）。**不含部门/广场**。
  - 文件列表：`SpaceFileDao.async_list_children`（已 cursor）接 `user_id` 过滤——以传入身份解析可见文件集（对齐 F029 INV-7：检索/列表可见性一致），`parent_id` 不存在抛 `SpaceFolderNotFoundError`(18010)。
  **测试**: `test_space_list_mine_joined`、`test_space_file_list_cursor_parent_id`
  **覆盖 AC**: AC-02, AC-27, AC-28, AC-29b
  **依赖**: T02

### 后端 Facade + API 层（Test-First 配对）

- [x] **T05**: v2 filelib facade 集成测试（覆盖所有 AC）
  **文件**: `src/backend/test/knowledge/test_v2_filelib_unified.py`
  **逻辑**: httpx + ASGI TestClient 测试 6 个改动端点 + 回归端点。建/补 `test/knowledge/conftest.py`（默认操作人、临时 KB/QA/Space fixture）。
  用例映射：
  - 列表：AC-01(KB cursor 无 total)、AC-02(空间口径)、AC-03(user_id)、AC-04/05(type 拒绝 10962)、AC-06(翻页)、AC-06b(非法 cursor 10991)
  - 创建：AC-07(KB 建索引)、AC-08(QA 不建索引)、AC-09(空间忽略 model)、AC-10(缺 model 10901)、AC-11(重名 10900)、AC-12(忽略 auth_type)、AC-13(空间上限 18001)
  - 更新：AC-14/15/16
  - 检索：AC-17(混合 id)、AC-18(user_id)、AC-19(filters)、AC-20(top_k 上限) ← 检索类如难 mock 走**测试降级**
  - 上传：AC-21~25（parent_id 分派；不存在目录 18010）
  - 文件列表：AC-26~29b
  - 回归：AC-30(删空间级联)、AC-31(清空)、AC-32(元数据仅知识库)
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-06b, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-29b, AC-30, AC-31, AC-32
  **依赖**: T03, T04

- [x] **T06**: 创建 / 更新 / 列表 endpoint facade 分派
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`
  **逻辑**:
  - **创建** `POST /`：请求体 `type` 判别——type 0/1 → `KnowledgeService.acreate_knowledge`（QA 跳过建索引为现有行为）；type=3 → `KnowledgeSpaceService.create_knowledge_space`（忽略 model、忽略 type 0/1 的 auth_type/is_released 入参对 KB 不生效）；type=2 或非法 → `KnowledgeTypeNotSupportedError`(10962)。统一出参 `KnowledgeRead`。
  - **更新** `PUT /`：按 `knowledge_id` 查 row.type 分派——KB → `update_knowledge`；空间 → `update_knowledge_space`；仅 name/description（AD-06、AD-09 不传 description 置空按 doc 语义）。
  - **列表** `GET /`：入参对齐 v1（`type/name/sort_by/page_size/cursor/user_id`）；type 0/1 → 现成 cursor 的 `KnowledgeService.get_knowledge`；type=3 → T04 空间口径；type=2/非法 → 10962。身份用 T02 `resolve_operator`。出参 `PageInfiniteCursorData`。
  **约束**: endpoint **仅分派、不写业务**；用 `resp_200`/`UnifiedResponseModel` 包装；arch-guard 不得 import `database/models`。
  **测试**: T05 中列表/创建/更新相关用例通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-06b, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16
  **依赖**: T02, T03, T04, T05

- [x] **T07**: 检索 endpoint —— 新增 user_id（filters 不变）
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`,
           `src/backend/bisheng/open_endpoints/domain/schemas/filelib.py`
  **逻辑**: `RetrieveReq` **仅新增 `user_id: Optional[int]`**；`filters.knowledge_base_filters`（每库各自标签）保持不变，**不引入扁平 tags**。
  endpoint 用 T02 `resolve_operator(user_id)` 解析身份后调 `KnowledgeSpaceChatService.aretrieve_chunks`（已多态、已 per-kb 标签过滤）；
  代用户身份下只在可见资源/文件范围检索（对齐 INV-7），无权资源静默跳过。混合知识库/知识空间 id 直接透传（各 id 即各自 collection）。
  **测试**: T05 中 AC-17~20（检索难 mock 时降级手动验证）
  **覆盖 AC**: AC-17, AC-18, AC-19, AC-20
  **依赖**: T02, T05

- [x] **T08**: 上传 + 文件列表 endpoint facade 分派
  **文件**: `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py`
  **逻辑**:
  - **上传** `POST /file/{knowledge_id}`：`parent_id` 作为 Form 入参；按 row.type 分派——KB(0/1) → `KnowledgeService.aprocess_knowledge_file`（**不涉及 parent_id，链路维持现状**）；空间(3) → `KnowledgeSpaceService.add_file(knowledge_id, file_path, parent_id)`（原生校验目录、构造 file_level_path；目录不存在 → 18010）。**不改 `KnowledgeFileProcess`**。
  - **文件列表** `GET /file/list`：入参对齐 v1（`knowledge_id/parent_id/keyword/status/page_size/cursor/user_id`）；身份用 T02。KB(0/1) → **T03 `aget_knowledge_files_cursor`（伪游标，底层 offset 维持现状）**；空间(3) → T04 空间文件列表（`SpaceFileDao.async_list_children` cursor + parent_id 校验）。统一出参 `PageInfiniteCursorData` + `writeable`。
  **约束**: endpoint 仅分派；`parent_id` 仅传给空间 `add_file`，不污染 KB 链路。
  **测试**: T05 中 AC-21~29b 通过
  **覆盖 AC**: AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-29b
  **依赖**: T03, T04, T05

### 回归验证（已有接口多态正确性）

- [x] **T09**: 已有接口回归 + 文档登记
  **文件**: `src/backend/test/knowledge/test_v2_filelib_unified.py`（回归用例），
           `features/v2.6.0/release-contract.md`（已登记，仅复核）
  **逻辑**: 验证删除/清空/删除文件/批量删除按 row.type 正确分派（空间走 `delete_space` 级联 + ReBAC tuple 清理）；
  元数据 8 接口行为不变、仅作用于知识库；复核 release-contract F030 登记（表1/表3/模块编码 109/变更历史）完整。
  **测试**: AC-30, AC-31, AC-32 通过
  **覆盖 AC**: AC-30, AC-31, AC-32
  **依赖**: T06, T07, T08

---

## 任务依赖图

```
T01(errcode) ─┐
T02(identity) ─┼─→ T03(kb file cursor) ─┐
              └─→ T04(space list/file) ─┤
                                        ├─→ T05(tests) ─→ T06(create/update/list)
                                        │                 T07(retrieve)
                                        │                 T08(upload/file-list)
                                        └────────────────→ T09(regression)
```

---

## 实际偏差记录

- **偏差 9（创建出参缺 permission_ids/user_name —— 已修复，post-merge）**：create 端点原样返回 `acreate_knowledge`/`create_knowledge_space` 的 raw `Knowledge`，缺 `permission_ids`、`user_name`（与 list/update 出参不一致）。**修复**：KB(0/1) 走 `KnowledgeService.aconvert_knowledge_read`（创建者=owner→全量 KB 权限点 + user_name）；空间(3) 用 `KnowledgeRead(**space.model_dump(), user_name=login_user.user_name, permission_ids=sorted(_get_effective_permission_ids("knowledge_space", id)))`（空间权限模型不同，取创建者有效权限点）。e2e 在 test_kb_lifecycle / test_space_create_upload_list 增断言。**注**：知识空间 LIST(type=3, `_format_member_spaces`) 同样未填 permission_ids/user_name，存在相同 gap，待确认是否一并补。


> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

- **偏差 1（错误码编号）**：spec/tasks 原定 `KnowledgeTypeNotSupportedError = 10970`，实现时发现 **10970 已被 `KnowledgeNotExistError` 占用**，改用 **10962**（109 模块空闲段）。spec/tasks/release-contract 三处已同步为 10962。

- **偏差 2（T05 测试策略）**：原计划 httpx ASGI TestClient + 真实 DB fixture 覆盖全部 AC。实际本地环境无 DB/Milvus/ES/OpenFGA，改为**直接调用 endpoint 协程 + monkeypatch service 层**验证 facade 分派与类型拒绝（12 用例全过）。覆盖：创建/更新/列表/文件列表的 type 分派、type=2/非法拒绝(10962)、KB 忽略 auth_type/is_released、空间忽略 model、空间更新保留 is_released、列表/文件列表无 total(INV-6)。**测试降级（需 infra 的 e2e）**：检索真实召回(AC-17~20)、cursor 真库翻页(AC-06/06b)、创建真实建索引(AC-07/08)、空间上限(AC-13)、parent_id 真实落目录(AC-23/24)、删除级联(AC-30) —— 留待 `/e2e-test` 在带 infra 环境跑。

- **偏差 3（空间文件列表 keyword —— 已支持）**：~~原以为空间不支持 keyword~~。用户指出空间有关键词搜索接口 `GET /api/v1/knowledge/space/{id}/search`（service `search_space_children`，offset+total）。已接入：v2 文件列表空间分支按 keyword 是否存在二选一——**有 keyword → `asearch_space_children_cursor`**（新增，把 offset 搜索用 F027 AD-15 伪游标适配为 cursor 形状，复用 search 已算的 total 推 has_more、不外露 total、不膨胀 page_size 以保 offset 对齐）；**无 keyword → `list_space_children`**（原生 cursor 目录导航）。两路统一 `PageInfiniteCursorData` + writeable。

- **偏差 8（clear 后索引被删不重建 → 资源不可查 —— 已修复，post-merge）**：用户发现清空后检索报 `index_not_found`。根因:`delete_knowledge_file_in_vector` 对 clear 和 delete 都**直接 drop Milvus collection + delete ES index**,clear 不重建 → 资源"存在但无索引",再上传前不可查。**修复(选项 A)**:抽 `KnowledgeService._init_knowledge_indices_sync(invoke_user_id, knowledge)`(从 create 块提取,**QA 跳过——QA 字段/schema 与文档库不同,索引按 QA 自身 schema 懒建**),在 `delete_knowledge`(only_clear)与 `KnowledgeSpaceService.clear_space` 删除后重建空索引。create 路径同步复用该方法。e2e `test_clear_kb_keeps_index_queryable`:create→clear→retrieve 返回 200 空结果(非 500)。**注**:full delete 不重建(资源已删)。

- **偏差 7（QA 库 clear/delete 不清问答对 —— 已修复，post-merge）**：用户追问"清空是否含 QA 库"时发现:clear/delete 对 QA 库(type=1)只清 `KnowledgeFile`+向量+minio,而 QA 问答对存于独立 `QAKnowledge` 表,**残留**。**修复**(在 `KnowledgeService.delete_knowledge` 源头,clear 与 full delete 共用,且惠及 v1 调用方):QA 类型额外 `QAKnoweldgeDao.get_qa_knowledge_by_knowledge_ids([kid])`→`delete_batch`。单测 2 条(QA 清、NORMAL 不误清)。**另修一个 pre-existing bug**:v2 QA 写/读端点未 seed 租户 ContextVar,多租户下 `20004 Missing tenant context`。已修 `add_qa`/`add_relative_qa`/`update_qa`/`delete_qa`(读在 seed 之前)/`detail_qa`/`query_qa`——统一在入口调 `get_default_operator()` seed 租户(与 create/list 一致),并清理无用 `settings` import。add_qa 修复后 QA clear 的真库 e2e 可跑(`test_qa_add_then_clear_removes_pairs`:add_qa→detail_qa present→clear→detail_qa gone)。

- **偏差 6（检索不支持知识库 —— 已修复，post-merge）**：用户验收 OpenAPI 时发现 `/api/v2/filelib/retrieve` 对知识库 id 返回 `18000 Knowledge Space does not exist`——底层 `aretrieve_chunks` 是 F029 为知识空间建的，`_require_read_permission` 硬校验 `type==SPACE`。**我的 spec AC-17 错误地宣称支持混合 KB+空间 id**（未实测，检索类是测试降级，漏过）。**修复**：`knowledge_space_chat_service` 新增 `_aretrieve_chunks_dispatch`（按 row.type 路由）+ `_aretrieve_chunks_for_knowledge_base`（KB 读权限 + KB 维度标签过滤 + 同套 milvus/es 检索，去掉文件夹/版本逻辑）+ `_resolve_kb_file_ids_by_tags`（`TagBusinessTypeEnum.KNOWLEDGE`/`KNOWLEDGE_FILE`）。e2e 实测：文档库检索 18000→200+chunks。**范围修正(option B)**：检索仅支持**文档知识库(type=0)+知识空间(type=3)**;**QA 库(type=1)暂不支持**——QA 存储 schema 不同(page_content=问题、答案在 metadata.extra、用 file_id),走文档路径会错位,故 dispatch 显式拒绝 `KnowledgeTypeNotSupportedError`(10962),QA 专用召回(参考 QA_RETRIEVER 节点)留作后续特性。空 KB index_not_found 已由偏差8(清空重建索引)缓解。

- **偏差 5（e2e 捕获的真实 bug —— 已修复）**：将 delete/clear/update endpoint 改为 `async def` 后，它们直接调用**同步** `KnowledgeService.delete_knowledge`/`update_knowledge`（内部 `run_async_safe` 做 FGA 权限/审计），在运行中的事件循环上触发 `RuntimeError: run_async_safe cannot be called from a running event loop`。原 endpoint 是同步 `def`（FastAPI 走线程池才正常）。**修复**：三处 KB 分支用 `await run_in_threadpool(KnowledgeService.xxx, ...)` 包装；空间分支保持 `await`（本就是 async）。e2e 回归全绿后确认。**纯 mock 单测发现不了此问题**（不触发真实事件循环/FGA 交互），靠 e2e 暴露。

- **偏差 4（delete/clear 扩展为空间分派 —— 已按用户决策实现）**：核查发现原 `KnowledgeService.delete_knowledge` 不识别 type=3（删空间会遗漏级联+ReBAC 清理），且空间无清空方法。**用户决策：delete + clear 都分派**。已实现：① `DELETE /{id}` 按 row.type 分派——空间→`delete_space`、库→`delete_knowledge`、type=2/非法→10962；② `DELETE /clear/{id}` 同理——空间→**新增 `KnowledgeSpaceService.clear_space`**（复用 delete_space 的内容清理：向量/ES/minio + 子文件行 `async_delete_knowledge(only_clear=True)` + 子资源 FGA tuple 清理，**保留空间行/成员/空间 tuple/标签库**）、库→`delete_knowledge(only_clear=True)`。回归单测覆盖 delete/clear 空间与库分派、type=2 拒绝。**真库级联/tuple 清理待 `/e2e-test` 验证**。
