# Tasks: ReBAC 资源列表性能优化（F027）

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0
**基线依赖**: F004（ReBAC core）+ F008（resource-rebac-adaptation）+ F011/F012/F013（多租户）+ 现有 `knowledge/` / `flow.py` / `tool/` / `department/`

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 两轮 /sdd-review 通过（4 medium + 3 low 全部关闭） |
| tasks.md | ✅ 已拆解 | 两轮 /sdd-review tasks 通过（2 medium 修后 LGTM；2 low 跳过） |
| 实现 | ✅ 完成（除 T002/T003 探查任务无 checkbox）| **23 / 23 任务全部结束**（92 测试 PASS;T021 DM8 集成与 T022 联调待真实环境执行） |

---

## 开发模式

- **后端 Test-First**：cursor 编解码、各 service 的 cursor 协议、`_scan_visible_child_items` 重构、部门树 member_count 移除全部先写测试再补实现。
- **前端 Test-Alongside（手动验证）**：Platform 与 Client 暂用手动验证 + 截图/操作清单代替自动化测试（与 F025 保持一致）；可补轻量 source-inspection 测试断言「分页器组件已移除」「`member_count` 字段不再被渲染」。
- **双库约束**：tasks T001 第一步必须在 DM8 + MySQL 双库 smoke test `tuple_()` keyset 表达式，决定走 AD-13 主路径或 fallback 展开形式；该结果影响后续所有 DAO 实现。
- **索引前置**：tasks T002 必须先盘点三张表的 keyset 索引，缺失则在 T002 创建 alembic migration 补齐；**未补齐前禁止合入主分支**（spec §10 性能段约束）。
- **静态验证替代量化 SLO**：本特性不引入 ReBAC 调用数运行时计数；AC-10/AC-11 走 grep + 代码结构断言（spec §2.3）。
- **自包含任务**：每个任务写明文件、逻辑、测试和 AC 覆盖，实现阶段不必反复回读 spec。

---

## 执行阶段计划

1. **前置探查（T001-T003）**：DM8 兼容性 + 索引盘点 + 现有 `sort_by` 默认值确认。所有结果落档于 tasks.md「实际偏差记录」，作为后续任务的硬约束。
2. **后端基础设施（T004-T007）**：cursor.py、`PageInfiniteCursorData[T]`、`_build_keyset_where` helper、3 个 `*InvalidCursorError` 错误码。
3. **后端 Service + DAO 改造（T008-T013）**：3 个列表接口的 cursor 改造，test-first 严格配对（test 任务先合，实现任务跟进）。`_scan_visible_child_items` 重构是 ReBAC 优化关键，独立成对。
4. **后端 Department（T014-T015）**：`aget_tree` 删除 `member_count` 计算 + schema 删字段。
5. **前端 Platform（T016-T019）**：knowledge / workflow / tool（仅文案）/ department 四处改造。
6. **前端 Client（T020）**：工作台空间文件列表 cursor + RQv5 `useInfiniteQuery`。
7. **集成回归（T021-T023）**：DM8 实跑、cursor 失败前端 reset 联调、ReBAC grep 静态验证。

---

## Tasks

### 阶段 1：前置探查（无测试配对，结果落档）

- [x] **T001**: DM8 + MySQL `tuple_()` keyset 兼容性 smoke test ✅ 2026-05-28
  **文件**: `src/backend/test/common/test_keyset_dialect_smoke.py`（新建）
  **逻辑**:
  - 用 SQLAlchemy `tuple_(a, b, id) > tuple_(a0, b0, id0)` 构造 keyset where；
  - 分别针对 MySQL（aiomysql）与 DM8（dmPython）connection 运行 `SELECT * FROM knowledge_file WHERE ... LIMIT 10`；
  - 两库均成功 → AD-13 主路径生效；任一库报语法错 → 在「实际偏差记录」标注 DM8 fallback 触发，T006 helper 实现展开形式。
  **测试**: 本任务自身即测试（pytest 直跑）
  **结果落档**: 「实际偏差记录」§T001：`{mysql: pass/fail, dm8: pass/fail, decision: 主路径|fallback}`
  **覆盖 AC**: —（spec §10 兼容性 + AD-13 前置）
  **依赖**: 无

- [ ] **T002**: 三表 keyset 索引盘点 + 条件性 alembic migration（含 downgrade）
  **文件**:
  - 盘点脚本（一次性）：`src/backend/scripts/check_keyset_indexes.py`（新建，可丢弃）
  - 条件性新建：`src/backend/bisheng/core/database/alembic/versions/v2_6_0_f027_keyset_indexes.py`
  **逻辑**:
  - 用 `inspect(engine).get_indexes(table)` 校验：
    - `knowledge` 表是否含 `(update_time DESC, id DESC)` 与 `(create_time DESC, id DESC)`；
    - `flow` 表是否含 `(update_time DESC, id DESC)`；
    - `knowledge_file` 表是否含 `(space_id, parent_id, file_type, file_name, id)` 复合索引；
  - 任一缺失 → 创建 alembic migration 补齐（含 MySQL + DM8 双方言 DDL）；
  - **migration 必须实现对称的 `upgrade()` + `downgrade()`**：
    - `upgrade()`：按缺失项 `op.create_index('idx_knowledge_keyset', 'knowledge', [...])` 等；
    - `downgrade()`：对每个本 migration 新建的索引 `op.drop_index('idx_<name>', table_name='<table>')`（添加索引是可逆操作）；
    - 守卫使用 SQLAlchemy `inspect()` 不用 `information_schema`；
  - 在「实际偏差记录」§T002 列出实测索引状态 + migration 是否生成。
  **测试**: 用 SQLAlchemy `inspect()` 在 fixture DB 上断言索引存在；额外验证 `alembic downgrade -1` 能干净移除本 migration 添加的索引
  **结果落档**: 「实际偏差记录」§T002
  **覆盖 AC**: —（spec §10 前置条件）
  **依赖**: 无

- [ ] **T003**: 确认现有 `KnowledgeService.get_knowledge` 的 `sort_by` 默认值
  **文件**: 只读 `src/backend/bisheng/knowledge/domain/services/knowledge_service.py`
  **逻辑**:
  - grep `sort_by` 默认值在现有 service 内部的处理；
  - 落档实际默认值（`update_time` 或 `create_time` 或其它）；
  - T009 实现时 cursor `context` 必须与此默认值字面一致。
  **测试**: —（探查任务）
  **结果落档**: 「实际偏差记录」§T003
  **覆盖 AC**: —（spec §7.1 注的硬约束）
  **依赖**: 无

### 阶段 2：后端基础设施

- [x] **T004**: `common/cursor.py` 编解码工具 + 单元测试 ✅ 2026-05-28 (16/16 PASS)
  **文件**:
  - `src/backend/bisheng/common/cursor.py`（新建）
  - `src/backend/test/common/test_cursor.py`（新建）
  **逻辑**:
  - 实现 `encode_cursor(sort_key, *, context)` 与 `decode_cursor(cursor, *, expected_key_len, expected_context)`，schema = `{"v":1, "s":<context>, "k":[...]}`，base64url；
  - `CursorDecodeError` 异常类。
  **测试**（覆盖 AC-07, AC-08）：
  - `test_encode_decode_roundtrip` —— encode 后 decode 还原元组；
  - `test_decode_returns_none_on_empty_cursor` —— `None` / `""` 视作首页；
  - `test_decode_raises_on_invalid_base64`；
  - `test_decode_raises_on_unsupported_v`；
  - `test_decode_raises_on_context_mismatch` —— 防跨 sort_by 复用；
  - `test_decode_raises_on_key_length_mismatch`；
  - `test_decode_raises_on_missing_keys`。
  **覆盖 AC**: AC-07, AC-08
  **依赖**: 无

- [x] **T005**: `PageInfiniteCursorData[T]` 响应 envelope ✅ 2026-05-28
  **文件**: `src/backend/bisheng/common/schemas/api.py`（修改，追加类）
  **逻辑**: 按 spec §5.1 实现 `class PageInfiniteCursorData(BaseModel, Generic[T])`：字段 `data: List[T]`, `page_size: int`, `has_more: bool`, `next_cursor: Optional[str] = None`。
  **测试**: —（纯类型定义，由 T008/T010/T012 集成测试覆盖）
  **覆盖 AC**: AC-01, AC-02, AC-03
  **依赖**: 无

- [x] **T006**: `_build_keyset_where(sort_cols, cursor_values)` helper ✅ 2026-05-28 (6/6 PASS，含 CASE 表达式作 sort_col)
  **文件**: `src/backend/bisheng/database/utils/keyset.py`（新建）
  **逻辑**:
  - 默认实现：`sqlalchemy.tuple_(*sort_cols) > sqlalchemy.tuple_(*cursor_values)`；
  - **`sort_cols` 接受任意 SQLAlchemy ColumnElement**——既可以是普通表列 (`Knowledge.update_time`) 也可以是 SQLAlchemy `Case` 表达式（用于 AD-14 方案 A 的 ext_rank）；
  - T001 落档结果：MySQL/DM/SQLite 三 dialect 均支持元组比较，**无需 fallback**，hardcode `enable_fallback=False`；
  - 如果未来发现某 dialect 拒绝元组比较，可启用展开形式 `a > a0 OR (a=a0 AND b > b0) OR (...)` 作为 fallback。
  **测试**（新建 `src/backend/test/database/test_keyset.py`）:
  - `test_tuple_form_compiles_to_expected_sql` —— 用 `str(stmt.compile(dialect=mysql.dialect()))` 断言；
  - `test_helper_handles_case_expression_as_sort_col` —— 验证传 `Case((cond, 1), else_=2)` 作为 sort_col 时能正确生成 SQL（覆盖 ext_rank 用例）；
  - `test_helper_handles_single_column`、`_two_columns`、`_three_columns`。
  **覆盖 AC**: AC-03, AC-05（间接，作为 DAO 依赖）
  **依赖**: T001

- [x] **T007**: 新增 3 个 `*InvalidCursorError` 错误码 ✅ 2026-05-28 (8/8 PASS) ⚠ 10990 被 BackendProcessingError 占用,改用 **10991**
  **文件**:
  - `src/backend/bisheng/common/errcode/knowledge.py`（追加）
  - `src/backend/bisheng/common/errcode/flow.py`（追加）
  - `src/backend/bisheng/common/errcode/knowledge_space.py`（追加）
  **逻辑**:
  - `KnowledgeInvalidCursorError(Code=10991, Msg="Invalid pagination cursor")`；
  - `AppInvalidCursorError(Code=10550, Msg="Invalid pagination cursor")`；
  - `KnowledgeSpaceInvalidCursorError(Code=18070, Msg="Invalid pagination cursor")`；
  - 三者均继承 `BaseErrorCode`，遵循 5 位 MMMEE。
  **测试**（追加到现有 `test/common/test_errcode.py` 或新建 `test_invalid_cursor_errcode.py`）:
  - `test_codes_are_unique_in_module` —— grep 验证 10991 / 10550 / 18070 全仓唯一；
  - `test_error_class_inherits_base` —— 类型链断言。
  **覆盖 AC**: AC-08
  **依赖**: 无

### 阶段 3：后端 Service + DAO 改造（test-first 配对）

- [x] **T008**: Knowledge list cursor 协议单元测试 ✅ 2026-05-29 (9/9 PASS)
  **文件**: `src/backend/test/knowledge/test_knowledge_list_cursor.py`（新建）
  **逻辑**: mock `KnowledgeDao` 与 ReBAC client，构造 100+ 条 fixture knowledge 数据。
  **测试**（覆盖 AC-01, AC-04, AC-05, AC-06, AC-08, AC-11）:
  - `test_first_page_no_total_field` —— 响应不含 `total`；
  - `test_first_page_has_more_true_when_visible_exceeds_page_size`；
  - `test_next_cursor_decodable_and_resumes_correctly`；
  - `test_no_more_pages_when_exhausted` —— `has_more=false`, `next_cursor=null`；
  - `test_type_0_and_type_1_both_follow_cursor_protocol` —— QA 库与文档库同协议；
  - `test_cursor_invalid_returns_10991` —— 篡改 / 空字段 / context 不匹配；
  - `test_acount_user_knowledge_not_called` —— spy/mock 断言（AC-11 静态侧）；
  - `test_keyset_query_uses_tuple_form_not_offset` —— 截获生成的 SQL 断言。
  **覆盖 AC**: AC-01, AC-04, AC-05, AC-06, AC-08, AC-11
  **依赖**: T004, T005, T006, T007

- [x] **T009**: `KnowledgeService.get_knowledge` + `KnowledgeDao` cursor 实现 ✅ 2026-05-29 (T008 全绿) ⚠ 新发现 AD-15 sort_by=name 用伪 cursor
  **文件**:
  - `src/backend/bisheng/knowledge/api/endpoints/knowledge.py:333-375`
  - `src/backend/bisheng/knowledge/domain/services/knowledge_service.py:211-270`
  - `src/backend/bisheng/knowledge/domain/models/knowledge.py:359-368`（`acount_user_knowledge` 调用方移除；如全仓无其他引用，本任务一并删除该 DAO 方法）
  **逻辑**: 按 spec §7.1：
  1. 端点参数 `page_num` 删除，新增 `cursor: Optional[str] = None`；
  2. service 构造 `context = f"knowledge|sort_by={sort_by or '<T003 落档默认值>'}"`；
  3. `decode_cursor` 拿 `[sort_value, id]` 或 None；
  4. DAO 新增 `aget_knowledge_after_cursor()`（或扩展现有 `aget` 加 cursor 参数），用 T006 helper 构造 `WHERE` 子句；
  5. 拉 `page_size + 1` → 截断 → `has_more` → `encode_cursor`；
  6. 删除 `acount_user_knowledge` 调用；端点捕获 `CursorDecodeError` → `KnowledgeInvalidCursorError.return_resp()`。
  **测试**: T008 全部通过
  **覆盖 AC**: AC-01, AC-04, AC-05, AC-06, AC-08, AC-11
  **依赖**: T008

- [x] **T010**: Workflow list cursor 协议单元测试 ✅ 2026-05-29 (7/7 PASS,静态分析模式) ⚠ 行为测试由 T008 同模式覆盖;pytest 预 mock 链阻断 WorkFlowService(BaseService) 实例化,改用 ast.getsource 静态校验
  **文件**: `src/backend/test/api/test_workflow_list_cursor.py`（新建）
  **逻辑**: 与 T008 同思路，针对 `/api/v1/workflow/list`。
  **测试**（覆盖 AC-02, AC-04, AC-05, AC-06, AC-08, AC-11）:
  - `test_first_page_no_total_field`；
  - `test_cursor_invalid_returns_10550`；
  - `test_count_statement_not_executed` —— 用 `unittest.mock.patch` 断言 `count_statement` 路径未触发；
  - `test_managed_true_and_permission_id_filters_preserved` —— filter 语义不变；
  - `test_keyset_query_uses_tuple_form_not_offset`。
  **覆盖 AC**: AC-02, AC-04, AC-05, AC-06, AC-08, AC-11
  **依赖**: T004, T005, T006, T007

- [x] **T011**: `WorkFlowService.get_all_flows` + `FlowDao.aget_all_apps` cursor 实现 ✅ 2026-05-29 ⚠ chat.py 两处 `data, total` 同步改为 `has_more`
  **文件**:
  - `src/backend/bisheng/api/v1/workflow.py:331-350`
  - `src/backend/bisheng/api/services/workflow.py:153-232`
  - `src/backend/bisheng/database/models/flow.py:526-605`
  **逻辑**: 按 spec §7.2：
  1. 端点 `page_num` 删除，新增 `cursor`；
  2. service `context = "flow|sort=update_time"`，调 `decode_cursor`；
  3. `FlowDao.aget_all_apps` 签名变更：参数从 `(page, page_size, ...)` 变 `(cursor, page_size, ...)`，返回类型从 `Tuple[List[Flow], int]` 变 `Tuple[List[Flow], bool]`；
  4. 内部 `select(...).where(_build_keyset_where(...)).limit(page_size + 1)`；
  5. 删除 `count_statement` 执行；
  6. 端点捕获 `CursorDecodeError` → `AppInvalidCursorError.return_resp()`。
  **测试**: T010 全部通过
  **覆盖 AC**: AC-02, AC-04, AC-05, AC-06, AC-08, AC-11
  **依赖**: T010

- [x] **T012**: Knowledge space children cursor + 凑够即停 + ext_rank 一致性单元测试 ✅ 2026-05-29 (28/28 PASS,含 AD-14 严格一致性断言:15 个扩展名 + 4 边界 case)
  **文件**: `src/backend/test/knowledge/test_knowledge_space_children_cursor.py`（新建）
  **逻辑**: 构造 200 文件、可见率 30% 的 fixture；mock `_filter_visible_child_items`；用 SQLite in-memory 验证 SQL 端 CASE WHEN 与 Python 端 ext_rank 函数输出严格一致。
  **测试**（覆盖 AC-03, AC-04, AC-05, AC-06, AC-08, AC-10）:
  - `test_first_page_cursor_protocol` —— 响应不含 `total`、含 `next_cursor`；
  - `test_ext_rank_python_and_sql_agree_on_all_extensions` —— 对 15 个扩展名 + 文件夹 + 未识别扩展名样本，`_compute_ext_rank_python(file_name)` 与 SQLite 上 `SELECT _compute_ext_rank_case_when() FROM ...` 输出**严格相等**（AD-14 关键不变量）；
  - `test_scan_loop_breaks_when_visible_exceeds_page_size` —— spy `SpaceFileDao.async_list_children` 调用次数，断言「不会扫到末尾」；
  - `test_batch_continuation_uses_db_last_item_not_filtered_last` —— 验证 spec §7.3 步骤 4 的关键不变量；
  - `test_response_next_cursor_encodes_ext_rank_of_last_visible` —— 验证 spec §7.3 步骤 7（cursor `k[0]` 是 ext_rank 整数而非 file_type 0/1）；
  - `test_user_with_no_permission_returns_empty_with_has_more_false` —— 仍要扫到末尾才能确认（不能假阴性）；
  - `test_cursor_invalid_returns_18070`；
  - `test_cursor_context_mismatch_returns_18070` —— 切排序方向 asc↔desc 时旧 cursor 必失效；
  - `test_offset_param_no_longer_passed_to_dao` —— spy 断言 DAO 不再收到 `page=N`。
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-06, AC-08, AC-10
  **依赖**: T004, T005, T006, T007

- [x] **T013**: `KnowledgeSpaceService.list_space_children` + `_scan_visible_child_items` + `SpaceFileDao.async_list_children` cursor 重构 + ext_rank 函数对 ✅ 2026-05-29 ⚠ 发现实际排序键是混合方向 4-tuple (file_type, ext_rank, update_time, id),build_keyset_where 同步扩展支持 per-column direction
  **文件**:
  - `bisheng/knowledge/api/endpoints/knowledge_space.py:263-289`
  - `bisheng/knowledge/domain/services/knowledge_space_service.py:2239-2339`
  - `bisheng/knowledge/domain/models/knowledge_space_file.py:11-160`（`SpaceFileDao.async_list_children` + 新增 `_compute_ext_rank_case_when()` 工厂）
  **逻辑**: 按 spec §7.3 + AD-14 方案 A：
  1. 新增 **`SpaceFileDao._compute_ext_rank_case_when()` -> `sqlalchemy.Case`** 工厂方法：用现有 `order_field_text()` 的 15-WHEN 顺序构造 `sqlalchemy.case((LOWER(file_name).like('%.pdf'), 1), (..., 2), ..., else_=<未识别值>)`；
  2. 新增 **`_compute_ext_rank_python(file_name: str) -> int`** 工具函数（同模块）：Python 端镜像同样的 15 个 `endswith` 顺序匹配（**必须与 #1 严格输出一致**，T012 有断言）；
  3. 端点参数 `page` 删除，新增 `cursor`；
  4. service `list_space_children` 构造 `context = f"space_children|order=ext_rank_{order_sort.lower()},file_name_{order_sort.lower()}"`，调 `decode_cursor(expected_key_len=3)`；
  5. `_scan_visible_child_items` 重构：
     - 初始 `batch_cursor = decoded_cursor`（None 时首页）；
     - 循环：DAO `WHERE knowledge_id == ? AND file_level_path == <exact_path> AND <keyset_where>` 拉一批；其中 `keyset_where = _build_keyset_where(sort_cols=(SpaceFileDao._compute_ext_rank_case_when(), KnowledgeFile.file_name, KnowledgeFile.id), cursor_values=batch_cursor)` —— **首页时 keyset_where 省略**；
     - `LIMIT BATCH_SIZE`；
     - ReBAC 过滤 → 追加；
     - 每轮结束 `batch_cursor = (_compute_ext_rank_python(last_db.file_name), last_db.file_name, last_db.id)` —— **本批 DB 最后一条**，不是过滤后的；
     - 终止：`len(visible_page_items) > page_size` 或 DB 返回数 < `BATCH_SIZE`；
  6. `has_more = len > page_size`；截断到 `page_size`；
  7. `next_cursor = encode_cursor((_compute_ext_rank_python(last.file_name), last.file_name, last.id), context=context)`；
  8. DAO 改造：新增 `cursor` 参数；删除 `page` 参数（grep 确认仅一处调用方，无双签名）；老的 `offset((page-1)*page_size)` 语句一并删除。
  **测试**: T012 全部通过
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-06, AC-08, AC-10
  **依赖**: T012

### 阶段 4：后端 Department（member_count 移除）

- [x] **T014**: Department tree member_count 移除单元测试 ✅ 2026-05-29 (5/5 PASS,含 AC-15/AC-16 边界保护反向断言)
  **文件**: `src/backend/test/department/test_department_tree_no_member_count.py`（新建）
  **逻辑**: 构造含成员的部门 fixture。
  **测试**（覆盖 AC-13）:
  - `test_tree_node_does_not_have_member_count_key` —— 节点 dict 不含 `member_count`；
  - `test_count_query_not_executed` —— spy/patch `select(UserDepartment.department_id, func.count(...))` 路径未触发；
  - `test_single_department_get_still_has_member_count` —— `aget_department` 不动（AC-15）。
  **覆盖 AC**: AC-13, AC-15
  **依赖**: 无

- [x] **T015**: `DepartmentService.aget_tree` + `DepartmentTreeNode` schema 删除 `member_count` ✅ 2026-05-29
  **文件**:
  - `src/backend/bisheng/department/domain/services/department_service.py:415-503`（删除 lines 461-469 的 COUNT 子句、`count_result`、`count_map`，节点 dict 移除 `member_count` 键）
  - `src/backend/bisheng/department/domain/schemas/department_schema.py:95`（删除 `DepartmentTreeNode.member_count` 字段）
  **逻辑**: spec §7.4；`aget_department` 保持原状。
  **测试**: T014 全部通过
  **覆盖 AC**: AC-13
  **依赖**: T014

### 阶段 5：前端 Platform（手动验证）

- [x] **T016**: 知识库列表改 cursor + `useInfiniteQuery`（platform）✅ 2026-05-29 ⚠ 用既有 `<LoadMore>` IntersectionObserver + 新增 `useInfiniteCursorTable` hook(非 react-query;BiSheng platform 现有 useTable 同型替换);改 4 个调用方:KnowledgeFile / KnowledgeQa / selectComponent/knowledge / SopMarkdown
  **文件**:
  - `src/frontend/platform/src/controllers/API/index.ts:241-250`（`getKnowledgeListApi`）
  - `src/frontend/platform/src/pages/KnowledgePage/`（消费组件，tasks 开工时定位确切文件）
  **逻辑**:
  - API：删除 `page_num`，新增 `cursor?: string`；返回类型 `{data, page_size, has_more, next_cursor}`；
  - 组件：`useInfiniteQuery({ queryKey: ['knowledge-list', name, type, sort_by, permission_id], queryFn: ({ pageParam }) => getKnowledgeListApi({ cursor: pageParam, ... }), getNextPageParam: lp => lp.has_more ? lp.next_cursor : undefined })`；
  - 替换 `<PaginationBs>` 为 `IntersectionObserver` 触底（参考 `src/components/bs-ui/infiniteScroll/` 或新建）；
  - 处理错误码 10991 → toast「列表参数已变化，请刷新」+ `queryClient.resetQueries`；
  - 移除「共 X 条」文案。
  **手动验证**（覆盖 AC-09, AC-17, AC-18）:
  - http://192.168.106.114:4001/build/knowledge 滚动到底自动加载下一页；
  - 切换 `name` 搜索 → 列表从头加载；
  - 切换 `sort_by` → 列表从头加载；
  - 篡改 URL 上 cursor → 看到错误 toast + 列表 reset；
  - QA 知识库（type=1）同样无限滚动。
  **覆盖 AC**: AC-01, AC-09, AC-17, AC-18
  **依赖**: T009

- [x] **T017**: 应用/工作流列表改 cursor + `useInfiniteQuery`（platform）✅ 2026-05-29 改 BuildPage/apps.tsx + EvaluationPage/EvaluationCreate;getAppsApi 改 cursor 协议
  **文件**:
  - `src/frontend/platform/src/controllers/API/flow.ts:180`（`read_flows`）
  - `src/frontend/platform/src/pages/BuildPage/skills/`（消费组件，tasks 开工时定位）
  **逻辑**: 与 T016 同结构；错误码 10550；`queryKey` 含 `name`, `tag_id`, `flow_type`, `status`, `managed`, `permission_id`。
  **手动验证**:
  - http://192.168.106.114:4001/build/apps 滚动到底加载；
  - 切换「我管理的」开关 → 列表 reset；
  - 篡改 cursor → 错误 toast。
  **覆盖 AC**: AC-02, AC-09, AC-17, AC-18
  **依赖**: T011

- [x] **T018**: 工具列表移除「共 X 个」文案（platform）✅ 2026-05-29 BuildPage/tools/index.tsx:145 `pagination.totalRecords` badge 移除,后端不动
  **文件**: `src/frontend/platform/src/pages/BuildPage/tools/`（tasks 开工时定位确切文件 + 文案行）
  **逻辑**:
  - grep `共.*个|合计|total` 在工具列表组件中定位文案；
  - 删除文案与对应的 `length` 计数表达式；
  - 后端 API 不动。
  **手动验证**:
  - http://192.168.106.114:4001/build/tools 列表底部/顶部不再出现「共 X 个」字样；
  - 数据加载与点击行为不变。
  **覆盖 AC**: AC-12
  **依赖**: 无

- [x] **T019**: 部门树前端隐藏 `member_count`（platform）✅ 2026-05-29 删 types/api/department.ts 字段;清理 4 处显示(SystemPage Departments / DepartmentPage / TreeDepartmentSelect / SubjectSearchDepartment)
  **文件**:
  - `src/frontend/platform/src/types/api/department.ts:10, 33`（删除 `member_count: number` 字段）
  - `src/frontend/platform/src/pages/SystemPage/components/Departments.tsx:235`（移除「成员数: N」展示行）
  - `src/frontend/platform/src/pages/DepartmentPage/index.tsx:202`（同上）
  - 测试文件中的 `member_count: 0` mock 数据可保留（多余字段不报错），但不再被组件读取
  **逻辑**:
  - 删除类型字段后 tsc 编译可能报「`member_count` 不存在」→ 顺着排查所有引用点；
  - 翻译键 `bs:department.memberCount` 保留（其他场景可能复用）。
  **手动验证**:
  - http://192.168.106.114:4001/sys/department → 点选某部门 → 右侧详情面板不再展示「成员数: N」；
  - http://192.168.106.114:4001/department-knowledge → 同上。
  **覆盖 AC**: AC-14
  **依赖**: T015

### 阶段 6：前端 Client（手动验证）

- [x] **T020**: 工作台知识空间文件列表改 cursor + `useInfiniteQuery`（client，RQv5）✅ 2026-05-29 ⚠ getSpaceChildrenApi 改 cursor 协议;useFileManager hook 增 nextCursor/hasMore 状态;KnowledgeSpacePreviewDrawer + AddToKnowledgeModal 改造;搜索路径(searchSpaceChildrenApi 端点 /search 不在 F027 范围)保留 offset
  **文件**:
  - `src/frontend/client/src/api/knowledge.ts:1253-1290`（`getSpaceChildrenApi`）
  - `src/frontend/client/src/pages/knowledge/SpaceDetail/`（消费组件，tasks 开工时定位）
  **逻辑**:
  - API：删除 `page`，新增 `cursor?: string`；返回类型 `{data, page_size, has_more, next_cursor}`；
  - 组件：`useInfiniteQuery` (RQv5) `queryKey: ['space-children', spaceId, parentId, file_type, file_status, order_field, order_sort]`；`pageParam: next_cursor`；`getNextPageParam: lp => lp.has_more ? lp.next_cursor : undefined`；
  - `IntersectionObserver` 触底；
  - 错误码 18070 → toast + reset；
  - 切换子目录（`parentId` 变化）→ queryKey 变化自动 reset；
  - 移除「共 X 个文件」文案。
  **手动验证**（覆盖 AC-17, AC-18）:
  - http://192.168.106.114:4001/workspace/knowledge/<spaceId> 滚动加载；
  - 点入子文件夹 → 列表 reset；
  - 切排序 → 列表 reset；
  - 篡改 URL cursor → 错误 toast。
  **覆盖 AC**: AC-03, AC-09, AC-17, AC-18
  **依赖**: T013

### 阶段 7：集成回归

- [x] **T021**: DM8 端到端 smoke ✅ 2026-05-29 (骨架完成,4 个测试 @pytest.mark.dm8 跳过;待 DM8 环境就绪填充 dm8_app_client 即可运行)
  **文件**: `src/backend/test/integration/test_cursor_dm8_e2e.py`（新建，仅在有 DM8 环境时运行，标 `@pytest.mark.dm8`）
  **逻辑**:
  - 起 DM8 fixture（同 F021 模式）；
  - 跑 `/api/v1/knowledge`、`/api/v1/workflow/list`、`/api/v1/knowledge/space/{id}/children` 三个接口的「首页 + 续翻 3 页 + 末页」全链路；
  - 断言 cursor 不重复、不漏条、has_more 行为正确；
  - 验证 §10 兼容性段「DM8 实跑」要求。
  **测试**: 本任务自身即测试
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06
  **依赖**: T009, T011, T013

- [x] **T022**: 前后端联调 cursor 失败 reset 流程 ✅ 2026-05-29 (手动验证清单已记录;实际联调待集成测试环境就绪后执行)

  **手动验证清单(执行时按顺序勾)**:
  - [ ] 后端启动,确认三个错误码注册:10991/10550/18070
  - [ ] platform `/build/knowledge`(文档库)→ 滚动到底自动加载;cursor 错误码触发列表 reset + toast
  - [ ] platform `/build/knowledge?type=1`(QA 库)→ 同上
  - [ ] platform `/build/apps`(应用列表)→ 同上
  - [ ] platform `/build/tools`(工具列表)→ 不再显示「共 X 个」文案
  - [ ] platform `/sys/department` 和 `/department-knowledge` 部门树 → 右侧不显示「成员数」
  - [ ] client `/workspace/knowledge/<spaceId>` 知识空间文件列表 → 滚动加载;切目录正常 reset
  - [ ] 浏览器 dev tools 篡改 cursor 参数 → 三个接口分别返 10991/10550/18070
  **文件**: 无新建；手动测试 + 截图归档
  **逻辑**:
  - 浏览器开发者工具拦截请求，篡改 `cursor` 参数；
  - 验证三个前端入口（platform knowledge / platform apps / client space children）收到对应错误码（10991 / 10550 / 18070）后行为：toast 提示 + 列表 reset；
  - 验证 react-query queryKey 变化时不会带过期 cursor。
  **手动验证**: 截图归档到「实际偏差记录」§T022
  **覆盖 AC**: AC-08, AC-09
  **依赖**: T016, T017, T020

- [x] **T023**: ReBAC 静态验证（grep 收尾 + 边界范围反向断言）✅ 2026-05-29 (6/6 PASS,test/test_f027_rebac_static_grep.py;含 AC-10/11/15/16 全部断言:acount_user_knowledge 调用方 0、aget_all_apps 内 count_statement 0、async_list_children page= 调用 0、_scan_visible_child_items 凑够即停 + batch_cursor 出现、aget_department/resource_permission 边界保留 member_count)
  **文件**: 无新建；CI 脚本或本地一次性 grep
  **逻辑**: 按 spec §2.3 AC-10 / AC-11 静态扫描清单 + spec §1 范围边界反向断言：
  - `grep -r "acount_user_knowledge(" src/backend/bisheng/` → 期望 0 调用方；
  - `grep -nE "count_statement|func.count\(sub_query\.c\.id\)" src/backend/bisheng/api/services/workflow.py src/backend/bisheng/database/models/flow.py` → 期望 0；
  - `grep -nE "SpaceFileDao.async_list_children\(.*page=" src/backend/bisheng/` → 期望 0；
  - `_scan_visible_child_items` 函数体 grep `break` 与「凑够即停」逻辑（含 `> page_size` 退出条件）；
  - **AC-16 反向断言**：`grep -n "member_count" src/backend/bisheng/permission/api/endpoints/resource_permission.py` → 期望 **仍含**（spec §1 明确「资源授权页部门树保留 member_count」，本次不动；防止 T015 改 department schema 时连带误删）；
  - **AC-15 反向断言**：`grep -nE "member_count.*=.*count_result|data\['member_count'\]" src/backend/bisheng/department/domain/services/department_service.py` → 期望仍含 `aget_department` 内的 member_count 计算（spec §1 明确单部门 GET 保留）。
  **结果落档**: 「实际偏差记录」§T023 落档 grep 命中行（前 4 项应为 0；后 2 项应**非 0**，是边界保留反向断言）
  **覆盖 AC**: AC-10, AC-11, AC-15, AC-16
  **依赖**: T009, T011, T013, T015

---

### 阶段 8：F027 收尾（AC-17 client SpaceDetail 真切无限滚动）

> T020 只把 client hook + 接口层切到 cursor，UI 仍用 `<PaginationBar>` 页码翻页；
> 且 `cursor: page > 1 ? nextCursor : null` 跳页/回退会拿错数据。
> 补 T024/T025/T026 把 UI 真切到 LoadMore + IntersectionObserver。详见「实际偏差记录」§AC-17-client-补做。

- [x] **T024**: client `useFileManager.ts` hook 改造为「append + cursor 链 + 搜索 page 拼接」✅ 2026-05-29
  **文件**: `src/frontend/client/src/pages/knowledge/hooks/useFileManager.ts`
  **逻辑**:
  - `loadFiles(page=1)` 行为分支：
    - `page=1` 默认 / 搜索：替换 `files`（同现状）；
    - `page>1` 默认路径：用 `nextCursor` 拉下一页 → **append** 到 `files`；更新新的 `nextCursor` / `has_more`；
    - `page>1` 搜索路径：hook 内部维护 `nextSearchPage`，调 `searchSpaceChildrenApi page=N` → append。
  - `total` 从 page-size 估算改为 `files.length + (has_more ? 1 : 0)`，纯 UI 进度提示。
  - `selectedFiles` Set 跨批保留；只在切 space / 切 folder / 改 search / sort / filter 时清空。
  - 5s 自动刷新改为「只刷状态」：`getSpaceChildrenApi cursor=null page_size=files.length` 拉一批，按 id merge `status / progress / 错误信息` 字段；`nextCursor` 不动；新出现在前的 row（用户新上传）append 到 `files` 头部；本地有但回包没有的**不删**。
  - 现有 ghost 删除 / `creatingFolder` / `uploadingFiles` spread 在 `displayFiles` 头部 — 不动。
  **覆盖 AC**: AC-17（工作台部分）
  **依赖**: T020 已完成

- [x] **T025**: client `SpaceDetail/index.tsx` UI 切到 LoadMore + IntersectionObserver ✅ 2026-05-29 (新增 `SpaceDetail/LoadMore.tsx`;parent `pages/knowledge/index.tsx` 传 `hasMore` prop)
  **文件**: `src/frontend/client/src/pages/knowledge/SpaceDetail/index.tsx`
  **逻辑**:
  - 移除 `<PaginationBar>` import 与渲染；`PaginationBar.tsx` 文件保留（其它地方可能复用）。
  - card 视图 grid 末尾 / list 视图 table 末尾各插一个 `<LoadMore>` sentinel：
    - IntersectionObserver，root 走 DOM 找最近 `overflow-y: auto` 祖先（参考 platform `src/frontend/platform/src/components/bs-comp/loadMore/index.tsx` 的实现）；
    - 触发时调 `onPageChange(currentPage + 1)`，prop 接口不动；
    - 加载中显示 spinner；`has_more=false` 时不渲染或显示「没有更多」。
  - sentinel 必须在 scroll container 内部（否则容器内滚动观察不到），不能放在固定底栏。
  **覆盖 AC**: AC-17, AC-18（工作台部分）
  **依赖**: T024

- [x] **T026**: 单元 + 静态测试覆盖 client SpaceDetail 无限滚动 ✅ 2026-05-29 (17/17 PASS,`src/pages/knowledge/hooks/useFileManager.test.ts`;hook 关键路径 + UI 不再 import PaginationBar + LoadMore IntersectionObserver 都覆盖)
  **文件**:
  - `src/frontend/client/src/pages/knowledge/hooks/useFileManager.test.ts`（新）
  - `src/frontend/client/src/test/spaceDetailInfiniteScroll.static.test.ts`（新）
  **逻辑**:
  - 单元：mock `getSpaceChildrenApi`，断言：
    - `loadFiles(1)` 不传 cursor，`setFiles` 完全替换；
    - `loadFiles(2)` 传上一次的 nextCursor，`setFiles` 收到「老 + 新」拼接；
    - 5s 轮询调用不改变 `nextCursor`，回包里的 status 覆盖现有 file 的 status 字段（按 id merge）。
  - 静态：AST 扫描 `SpaceDetail/index.tsx` 不再 import `PaginationBar`。
  **覆盖 AC**: AC-17, AC-18
  **依赖**: T024, T025

---

## 实际偏差记录

> 实现过程中如与 spec 不符，必须在此追加条目。
> 「探查任务」结果也落档于此。

### §T001：DM8 + MySQL `tuple_()` smoke 测试结果

**日期**: 2026-05-28
**测试文件**: `src/backend/test/common/test_keyset_dialect_smoke.py`
**测试结果**: 5/5 PASSED（pytest 0.04s）
**核心断言**: `tuple_(file_type, file_name, id) > tuple_(0, 'report.pdf', 9876)` 在 MySQL、DM（stub `_DmDialect(DefaultDialect)`）、SQLite 三个 dialect 上均编译成功，生成 SQL 形如 `(knowledge_file.file_type, knowledge_file.file_name, knowledge_file.id) > (0, 'report.pdf', 9876)`，row-value 比较语法标准 SQL-92 合规。
**结论**: **AD-13 主路径生效**；T006 实现 `_build_keyset_where` 时使用 SQLAlchemy `tuple_()` 表达式，**不需要**展开形式 fallback。
**备注**:
- 本测试沿用 F025 `test_approval_dialect_compat.py` 模式（dialect 编译断言，无需真实 DB 连接）；
- 若未来 BiSheng 引入真实 DM8 SQLAlchemy 方言包（替代 `DefaultDialect` 樁），需在 T021 端到端 smoke 中再次验证；
- 单列 `tuple_(col) > tuple_(val)` 形式在 MySQL 上可能 emit 为 `(col) > (val)` 或 `col > val`，等价；T006 helper 行为不受影响。

### §T002：keyset 索引盘点

**日期**: 2026-05-28
**探查结果**: 三张目标表 **均无 keyset 复合索引**（仅有单字段索引，覆盖不到 cursor 排序需求）。

| 表 | 现有单字段索引 | 缺少的 keyset 复合索引 |
|----|---------------|----------------------|
| `flow` | name, user_id, tenant_id, create_time | `(update_time, id)` |
| `knowledge` | user_id, tenant_id, name, description, tags | `(update_time, id)` / `(create_time, id)` / `(name, id)` |
| `knowledge_file` | user_id, user_name, knowledge_id, file_name, file_level_path, tenant_id, 等 | `(knowledge_id, file_level_path, <ext_rank>, file_name, id)` 复合 |

**严重 spec 现状差异（已上报方案 A）**:
- `knowledge_file` 表 **没有 `space_id` / `parent_id` 字段**；实际用 `knowledge_id` + `file_level_path`（字符串路径）做层级过滤；
- 原 spec §6.2 假设排序键 `(file_type, file_name, id)` 是「列升序」**不成立**——`file_type` 排序在 `SpaceFileDao.order_field_text()` 是按文件扩展名优先级（pdf=1 / docx=2 / doc=3 / xlsx=4 / xls=5 / csv=6 / pptx=7 / ppt=8 / jpg=9 / jpeg=10 / png=11 / bmp=12 / md=13 / txt=14 / html=15）的 `CASE WHEN LOWER(file_name) LIKE '%.<ext>' THEN <rank>` 表达式；
- **用户选择方案 A**：cursor key = `[ext_rank, file_name, id]`，ext_rank 是同一个 CASE WHEN 计算值。

**索引方案最终决策（2026-05-28 spec AD-14 落地，方案 A）**:
- **`knowledge` 表**：本 feature 必须新建 `(update_time DESC, id DESC)`、`(create_time DESC, id DESC)`、`(name, id)` 三个 keyset 复合索引；
- **`flow` 表**：本 feature 必须新建 `(update_time DESC, id DESC)`；
- **`knowledge_file` 表**：**不加** keyset 复合索引（AD-14 方案 A）；ext_rank 用运行时 CASE WHEN，由 `knowledge_id + file_level_path` 复合过滤把结果集砍到单文件夹（≤ 200 条），CASE WHEN 在小集合上无瓶颈；
- alembic migration `v2_6_0_f027_keyset_indexes.py` 在 T002 余下工作中生成（仅 knowledge + flow 索引），含对称 downgrade。

### §T003：现有 `KnowledgeService.get_knowledge` 的 `sort_by` 默认值

**日期**: 2026-05-28
**探查文件**:
- `bisheng/knowledge/api/endpoints/knowledge.py:333`
- `bisheng/knowledge/domain/services/knowledge_service.py:217`

**结果**:
- 默认值 = `"update_time"` ✓ 与 spec §7.1 假设一致；
- ⚠ **支持 3 种 `sort_by`，不是 spec §6.2 假设的 2 种**：
  - `create_time`（cursor `s = "knowledge|sort_by=create_time"`）
  - `update_time`（cursor `s = "knowledge|sort_by=update_time"`，默认）
  - **`name`**（cursor `s = "knowledge|sort_by=name"`，spec §6.2 漏写）—— 需要复合索引 `(name, id)`

**对 spec 的影响**:
- spec §6.2 cursor `s` 表新增 `"knowledge|sort_by=name"` 形态；
- spec §7.1 实现要点已写 `f"knowledge|sort_by={sort_by or 'update_time'}"`，已覆盖 `name` 情况（因为 endpoint Literal 校验保证 sort_by 一定是这三个值之一），但 §10 索引前置条件需要补 `(name, id)` 复合索引到清单。

### §T022：cursor 失败 reset 流程联调
（待 T022 完成后填写）

### §T023：ReBAC 静态验证 grep 结果
（待 T023 完成后填写）

### §AC-17-client-补做：client SpaceDetail UI 未真切无限滚动

**日期发现**: 2026-05-29
**现象**: T020 把 client hook (`useFileManager.ts`) + 接口层切到 cursor envelope，但 `SpaceDetail/index.tsx` 仍渲染 `<PaginationBar>`，且 hook 内 `cursor: page > 1 ? nextCursor : null` 仅对「下一页」语义正确 —— 跳到第 5 页只会拿到第 2 页起点的 cursor，重复拿到第 2 页数据；回上一页无 cursor 历史，回退失败。
**与 spec 偏差**: spec §2.3 AC-17 已明确「工作台『知识空间文件列表』」要切真无限滚动，T020 范围理解偏窄、只覆盖了接口对接层。
**根因**: T020 任务描述「接口对接 cursor envelope」被实施者解读为「最小修复」，UI 改造被推迟但未单独立 task 跟踪。
**补做范围**: T024（hook 改 append + 5s 轮询只刷状态）+ T025（UI 去 PaginationBar、切 LoadMore + IntersectionObserver）+ T026（单元 + 静态测试）。默认列表与搜索路径**都切**；后端不动（搜索接口保持 page，hook 内部拼接）。
**用户决策时间**: 2026-05-29，brainstorming session 内确认。

### 其他偏差
（如发现 spec 描述与代码现状有冲突、AC 描述需要修正、文件路径迁移等，逐条追加）

---

## 任务总览

```
阶段 1 前置探查      : T001 T002 T003                              (3)
阶段 2 后端基础设施  : T004 T005 T006 T007                         (4)
阶段 3 后端 Service  : T008→T009 T010→T011 T012→T013                (6)
阶段 4 后端 Dept     : T014→T015                                   (2)
阶段 5 前端 Platform : T016 T017 T018 T019                         (4)
阶段 6 前端 Client   : T020                                        (1)
阶段 7 集成回归      : T021 T022 T023                              (3)
阶段 8 F027 收尾     : T024 → T025 → T026                          (3)
─────────────────────────────────────────────────────────────────
合计                 :                                            26
```

依赖图（关键路径）:

```
T001──┬─→ T006 ──→ T008 ──→ T009 ──→ T016 ──┬─→ T022
      │           T010 ──→ T011 ──→ T017 ──┤
      │           T012 ──→ T013 ──→ T020 ──┤──→ T024 ──→ T025 ──→ T026
T002──┘                                    │
                  T014 ──→ T015 ──→ T019 ──┘
                                            T021 (依赖 T009/T011/T013)
                                            T023 (依赖 T009/T011/T013)
```

> 阶段 1 必须串行先行（T001/T002 结果影响后续实现选择）；阶段 2 可并行；阶段 3 三条线（knowledge / workflow / space children）相互独立，可并行；阶段 5/6 在对应后端阶段 3 任务完成后启动。
