# 验证报告 Verification: 门户智能问答与知识库工作台查看范围对齐

## 元信息 Metadata
- Feature ID: `050-portal-qa-workbench-scope-alignment`
- Status: `verified-with-known-test-infrastructure-gaps`
- Verified: `2026-07-30`
- Verification level: `V3 权限/端到端链路回归`

## 结论 Summary

登录用户的智能问答知识库列表、树节点、目录统计、文件名搜索、分类选择和最终 RAG 文件范围现已统一使用
知识库工作台的标准读取权限。智能问答仅展示并检索 `SUCCESS` 文件；非主版本和回收站文件也被排除。
树选择器继续使用现有游标分页和按需展开机制。

未登录用户的公共知识库问答保持原行为。门户首页搜索、通用浏览、发布、分享等广域发现接口未被全局收紧。

## 红测证据 Regression Reproduction

门户 BFF 修改前执行 `tests/test_qa_knowledge_scope_api.py`：
- 结果：`9 failed, 4 passed`。
- 失败证明登录用户仍调用 `/shougang-portal/qa/...` 广域接口，空间列表仍包含工作台不可读部门库，
  目录统计仍使用广域部门授权模型。

BiSheng 修改前执行四个最终范围解析回归：
- 结果：`4 failed`。
- 失败证明最终解析器仍调用 `_get_shougang_portal_qa_space(public_and_department)`，
  未执行标准 `_require_read_permission`、`view_folder` 和 `view_file` 校验。

## 修复后证据 Verification Evidence

| Command / Scope | Result | Coverage |
|---|---|---|
| 门户 `pytest -q tests/test_qa_knowledge_scope_api.py` | `13 passed` | 工作台空间集合、不可读部门库拒绝、通用 children/folder-stats、SUCCESS 参数、游标分页、匿名公共范围 |
| 门户 ChatProxy 8 个定向测试 | `8 passed` | 默认整库范围、显式范围、无权限空间拒绝、模型/模板兼容 |
| BiSheng 知识与工作站 12 个节点/文件 + 工作站文件 | `28 passed` | 空间/目录/文件权限、持久引用、整库过滤、文件搜索、部门匿名兼容、RAG 文件过滤 |
| `node --test .test-dist/tests/qaKnowledgeTreeSelection.test.js` | `11 passed` | 分类浏览限定工作台空间、选择器双模式、20 文件上限、游标懒加载 |
| `npm run build` | passed | TypeScript 生产类型检查及 Vite 构建 |
| `npx eslint`（3 个变更文件） | `0 errors, 2 existing warnings` | 前端静态检查 |
| 门户 Python `compileall` | passed | 变更模块及测试语法 |
| 门户借用 BiSheng ruff `--isolated --select E4,E7,E9,F` | passed | Python 严重静态错误检查 |
| BiSheng 变更测试 ruff `--isolated --select E4,E7,E9,F` | passed | 测试静态检查 |
| BiSheng Python `compileall` | passed | 服务与测试语法 |
| 两仓库 `git diff --check` | passed | diff 空白和格式 |

## 验收映射 Acceptance Traceability

| Acceptance | Status | Evidence |
|---|---|---|
| AC-REQ-001-* | passed | QA spaces 使用 grouped/readable spaces；匿名公共范围回归 |
| AC-REQ-002-01..04 | passed | 通用 children/folder-stats、legacy 搜索和资源权限测试 |
| AC-REQ-002-05 | passed | 首页和 QAPage 分类浏览显式传入工作台可见空间 ID |
| AC-REQ-003-* | passed | 现有选择器不变；游标、继续加载、目录深层统计测试 |
| AC-REQ-004-* | passed | BFF 构造空间拒绝、BiSheng 空间/目录/文件/持久引用和整库过滤测试 |
| AC-REQ-005-* | passed | API schema 未变；通用 browse 默认语义未改；无迁移和依赖变更 |

## 安全审查 Security Review

- 授权源：登录用户使用工作台 grouped spaces 和标准 OpenFGA 资源权限。
- 服务端强制：BFF 校验空间集合，BiSheng 再校验 `view_space`、`view_folder`、`view_file`。
- 状态与生命周期：固定 `SUCCESS`，排除非主版本、回收站和未就绪分发入口。
- 输入信任：前端 `space_ids` 只能缩小分类候选；最终检索不信任客户端 ID。
- 失败模式：空间不存在或无权时过滤/拒绝；授权服务异常不降级为放行。
- 权限写入：无权限关系、成员关系或审批数据写入。

## 已知验证限制 Known Gaps

1. 前端全量 `npm test` 在运行测试前被既有 TypeScript 测试夹具错误阻断，涉及缺失
   `home_icon`、`description`、旧配置字段、`.ts` 导入和已删除 `fetchHomeContent` 等，与本次改动无关。
   生产构建及本次 QA 定向测试均通过。
2. Vite 报告当前 Node.js `20.13.1` 低于建议的 `20.19+`，但本次生产构建成功。
3. BiSheng 全文件 ruff 仍包含既有导入排序、中文标点、未定义
   `KnowledgeSpaceTagLibraryNotBoundError`、未使用变量和 SQLAlchemy 比较等问题；
   本次变更测试通过严重错误规则，生产文件也通过 `compileall` 和行为测试。
4. 未启动完整门户与 BiSheng 服务执行浏览器端到端点击；当前以两层服务契约、最终 RAG 解析和前端构建/接线测试覆盖。

## 数据与回滚

- 无数据库迁移、数据回写、依赖或运行时配置变更。
- 回滚仅需恢复门户 QA 路由/服务、前端分类范围参数和 BiSheng 门户 QA 范围解析器。

## 2026-07-30 Bug 修复增量：同名个人知识库

### 调查与红测

`get_grouped_spaces()` 修复前会将两个不同 ID、规范化名称同为“gzx001的知识库”的本人个人空间同时追加到
`personal_spaces`。新增回归测试后首次执行：

| Evidence | Code State | Command / Step | Result | Scope |
|---|---|---|---|---|
| E-006-RED | `947a6fa22 + test-only worktree` | `pytest -q test/knowledge/test_knowledge_space_level_team_ks.py::TestKnowledgeSpaceServiceGrouping::test_get_grouped_spaces_deduplicates_current_user_personal_spaces_by_name` | `FAIL (exit 1)`；实际 `[11, 12, 13]`，期望 `[11, 13]` | AC-REQ-006-01, AC-REQ-006-02 |

### 修复后证据

| Evidence | Code State | Command / Step | Result | Scope |
|---|---|---|---|---|
| E-006-01 | `947a6fa22 + current worktree` | 同一条新增定向回归 | `PASS (exit 0), 1 passed` | AC-REQ-006-01, AC-REQ-006-02 |
| E-006-02 | `947a6fa22 + current worktree` | `pytest -q test/knowledge/test_knowledge_space_level_team_ks.py test/test_knowledge_space_service.py -k 'get_grouped_spaces'` | `PASS (exit 0), 4 passed, 215 deselected` | AC-REQ-006-01..03 |
| E-006-03 | `947a6fa22 + current worktree` | `pytest -q test/knowledge/test_knowledge_space_level_team_ks.py` | `PASS (exit 0), 6 passed` | AC-REQ-006-01..03 |
| E-006-04 | `947a6fa22 + current worktree` | 变更测试文件 `ruff check`、`ruff format --check`，生产与测试文件 `compileall`，仓库 `git diff --check` | `PASS (exit 0)` | 静态质量与语法 |

### 验收覆盖

| Acceptance | Status | Evidence |
|---|---|---|
| AC-REQ-006-01 | PASS | E-006-RED, E-006-01, E-006-02 |
| AC-REQ-006-02 | PASS | E-006-01, E-006-02 |
| AC-REQ-006-03 | PASS | E-006-02, E-006-03 |

### 增量验证缺口

1. 组合运行 `test/test_personal_default_space.py` 时，既有
   `test_ensure_personal_default_creates_when_missing` 未模拟 `_resolve_default_tag_library_id()` 的数据库访问，
   因测试环境数据库 URL 为 `MagicMock` 而失败；同批其余 `9` 项通过。该失败不经过本次分组名称防重代码。
2. 对整个 `knowledge_space_service.py` 执行严格 `ruff` 仍报告 6 个既有问题，包括未定义
   `ReviewTagFeatureDisabledError`、`section`、`KnowledgeSpaceTagLibraryNotBoundError` 和未使用变量等；
   本次变更测试文件 lint、两文件语法编译及相关行为回归均通过。
3. 本次不清理数据库里的重复空间，也不建立数据库唯一约束。接口会隐藏同名后续记录，但并发创建的数据库级根因仍需单独迁移方案。
