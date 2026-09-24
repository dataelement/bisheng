# Tasks: F059 解除知识空间创建数量上限

**Feature ID**: `059-unlimited-knowledge-space-creation`
**Status**: Confirmed — 用户已于 2026-07-16 确认任务清单
**Mode**: Test First
**Created**: 2026-07-16
**Updated**: 2026-07-16
**Related requirements**: [requirements.md](./requirements.md)
**Related design**: [design.md](./design.md)
**Related combined spec**: [spec.md](./spec.md)

---

## 1. 状态

| 阶段 | 状态 | 备注 |
|------|------|------|
| `spec.md` | ✅ 已确认 | 用户于 2026-07-16 确认。 |
| `tasks.md` | ✅ 已确认 | 用户于 2026-07-16 确认任务清单。 |
| 实现 | 🔲 未开始 | 0 / 7 完成。 |
| 验证 | 🔲 未开始 | 尚无实现证据。 |

---

## 2. 开发与范围规则

- 后端采用 Test-First：先增加能够证明现有实现仍受数量限制的失败测试，再修改生产代码。
- 只实现本文件列出的 T001-T007，不顺手清理旧 DAO、错误码、翻译或前端提示。
- 不修改 `shougang-group-knowledge-portal/**`、`src/frontend/client/**`、数据库 migration、配置文件或生产数据。
- 保留 `skip_user_limit`、`SpaceLimitError(18001)` 和 `KnowledgeDao.async_count_spaces_by_user` 的兼容定义，但创建链路不再使用数量限制。
- 旧角色或租户 `quota_config.knowledge_space` 键继续通过校验和读写；运行时统一忽略其有限值。
- `knowledge_space_file`、`storage_gb`、知识空间订阅数量和其他资源配额必须保持原行为。
- `knowledge_space_service.py` 已含用户未提交的 F057 修改，只允许在 import、常量和两个创建校验位置使用精确小补丁，不得整文件格式化。
- `test_knowledge_space_service.py` 已含用户未提交修改，本特性不得编辑该文件。
- 不得执行 `git reset`、`git checkout --`、stash、批量替换或其他覆盖用户改动的操作。
- 发现实现必须超出上述边界时，立即停止并先更新 `spec.md` 和 `tasks.md`。

---

## 3. Tasks

### Phase A：工作区保护与测试基线

- [x] T001 建立 F059 工作区基线
  - Done when: 记录当前分支、脏文件、F057 在 `knowledge_space_service.py` 中的具体 diff 区域；证明 F059 目标修改区域与现有 diff 不重叠，或在重叠时停止实施。
  - _Requirements: REQ-006_
  - _Acceptance: AC-11_
  - _Verification: V-007_
  - _Depends: none_
  - _Boundary: read-only investigation; no checkout, reset, stash, format, or file mutation_

- [x] T002 增加知识空间 Service 与审批链路失败测试
  - Done when: 新增独立测试文件，测试在生产实现修改前因仍调用 `async_count_spaces_by_user` 或抛出 `SpaceLimitError(18001)` 而失败，失败原因与 F059 一致。
  - _Requirements: REQ-001, REQ-002, REQ-005, REQ-006_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-10, AC-11_
  - _Verification: V-001, V-002, V-005, V-007_
  - _Depends: T001_
  - _Boundary: tests only; create `src/backend/test/knowledge/test_unlimited_knowledge_space_creation.py`; do not edit dirty `test_knowledge_space_service.py`_
  - 测试至少覆盖：
    - `validate_knowledge_space_create` 不应读取用户空间数量，并继续进入工作台模型等后续校验。
    - `create_knowledge_space` 不应读取用户空间数量，并继续进入后续创建校验。
    - 首钢审批 validate/submit 调用共享 Service 时不出现数量错误。
    - 审批通过 handler 重校验和落库时不出现数量错误。
    - 权限、模型、名称或标签库错误仍可按既有顺序返回，证明只移除数量限制。

### Phase B：移除固定 200 限制

- [x] T003 移除 KnowledgeSpaceService 固定数量校验
  - Done when: `_MAX_SPACE_PER_USER`、两处数量查询与判断以及不再使用的 import 被移除；`skip_user_limit` 签名保留；T002 测试由红转绿。
  - _Requirements: REQ-001, REQ-002, REQ-005, REQ-006_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-10, AC-11_
  - _Verification: V-001, V-002, V-005, V-006, V-007_
  - _Depends: T002_
  - _Boundary: implementation only in `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`; exact local patches around import, constants, `validate_knowledge_space_create`, and `create_knowledge_space`_

### Phase C：统一角色与租户配额语义

- [x] T004 增加知识空间无限配额失败测试
  - Done when: 测试在 QuotaService 实现修改前证明默认、角色有限值、租户有限值和零配额仍会返回有限结果或阻断创建；同时记录其他资源当前行为基线。
  - _Requirements: REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-05, AC-06, AC-07, AC-08, AC-09_
  - _Verification: V-003, V-004_
  - _Depends: T001_
  - _Boundary: tests only in `src/backend/test/test_quota_service.py`；若既有租户链测试把 `knowledge_space` 当作有限资源，可在 `src/backend/test/test_quota_service_check_chain.py` 中将对应通用用例改用仍受限资源；do not modify production code_
  - 测试至少覆盖：
    - `DEFAULT_ROLE_QUOTA['knowledge_space'] == -1`。
    - `get_effective_quota` 忽略角色和租户有限 `knowledge_space` 值并返回 `-1`。
    - `check_quota` 对 `knowledge_space` 直接允许，且不读取角色、租户或资源使用量。
    - `_compute_role_quotas` 忽略角色历史有限值。
    - `get_all_effective_quotas` 的 `knowledge_space` 项统一表达无限量，其他资源仍按原逻辑计算。
    - `validate_quota_config` 继续接受历史 `knowledge_space` 键。

- [x] T005 实现 QuotaService 知识空间无限量语义
  - Done when: `knowledge_space` 默认、创建校验、单项查询、角色聚合和批量有效配额均按无限量处理；历史键继续合法；T004 测试由红转绿。
  - _Requirements: REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-05, AC-06, AC-07, AC-08, AC-09_
  - _Verification: V-003, V-004, V-006_
  - _Depends: T004_
  - _Boundary: implementation only in `src/backend/bisheng/role/domain/services/quota_service.py`; no changes to role/tenant schemas, endpoints, UI, database, or configuration data_
  - 实现约束：
    - 无限量短路条件必须严格限定为 `resource_type == 'knowledge_space'`。
    - `knowledge_space_file` 和 `storage_gb` 不得进入该短路。
    - 保留 `knowledge_space` 在 `VALID_QUOTA_KEYS` 中。
    - 批量配额返回中 `knowledge_space` 的 `role_quota`、`tenant_quota` 和 `effective` 使用一致的 `-1` 语义。

### Phase D：回归验证与交付

- [ ] T006 执行定向回归和静态检查
  - Done when: F059 聚焦测试、审批创建测试、配额测试、存储/上传/订阅回归、静态检查和编译均有新鲜结果；失败项如实分类为本次回归或既有问题。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11_
  - _Verification: V-001, V-002, V-003, V-004, V-005, V-006, V-007_
  - _Depends: T003, T005_
  - _Boundary: verification only; no production data, external services, dependency changes, or broad repository formatting_
  - 验证命令候选：
    - `cd src/backend && uv run pytest test/knowledge/test_unlimited_knowledge_space_creation.py -q`
    - `cd src/backend && uv run pytest test/test_quota_service.py test/test_quota_service_check_chain.py test/test_require_quota_decorator.py -q`
    - `cd src/backend && uv run pytest test/approval/test_shougang_approval_service.py -q -k 'knowledge_space_create or create_approval_handler'`
    - `cd src/backend && uv run pytest test/integration/test_storage_quota_e2e.py test/test_knowledge_service_rebac_bridge.py -q`
    - `cd src/backend && uv run ruff check <F059-backend-files>`
    - `cd src/backend && uv run ruff format --check <F059-backend-files>`
    - `cd src/backend && uv run python -m compileall -q <F059-production-files> <F059-test-files>`
    - `git diff --check` 及目标文件分段 diff。

- [ ] T007 记录 verification、任务状态和实现偏差
  - Done when: 新建 `verification.md`，记录每条实际命令、退出码、关键证据和 AC 状态；更新任务勾选与实现偏差，未运行项标记 `NOT_RUN` 或 `MANUAL_REQUIRED`，不得伪报完成。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11_
  - _Verification: verification.md_
  - _Depends: T006_
  - _Boundary: docs/spec only in `features/v2.6.0/059-unlimited-knowledge-space-creation/`; no new implementation changes_

---

## 4. Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|-------------|---------------------|-------|--------------|
| REQ-001 | AC-01, AC-02 | T002, T003, T006, T007 | V-001, V-006, V-007 |
| REQ-002 | AC-03, AC-04 | T002, T003, T006, T007 | V-002, V-005, V-007 |
| REQ-003 | AC-05 | T004, T005, T006, T007 | V-003, V-004, V-006 |
| REQ-004 | AC-06, AC-07 | T004, T005, T006, T007 | V-003, V-006 |
| REQ-005 | AC-08, AC-09, AC-10 | T002, T003, T004, T005, T006, T007 | V-002, V-003, V-004, V-005, V-006 |
| REQ-006 | AC-11 | T001, T002, T003, T006, T007 | V-007 |

---

## 5. 执行顺序

```text
T001
 ├─ T002 → T003 ┐
 └─ T004 → T005 ├─ T006 → T007
                ┘
```

T002/T003 与 T004/T005 修改不同目标，可在 T001 后独立推进；当前会话默认串行执行以降低脏工作区协调风险。

---

## 6. Task Quality Gate

- [x] 每个任务引用至少一个 `REQ-*`。
- [x] 每个行为任务引用对应 `AC-*`。
- [x] 每个 `AC-*` 至少由一个任务和验证项覆盖。
- [x] 每个任务具有可观察的 Done when。
- [x] 任务依赖关系明确。
- [x] 文件和阶段边界可阻止无关修改。
- [x] 测试任务位于对应实现任务之前。
- [x] 脏工作区和用户改动保护已单列任务。
- [x] 用户确认任务清单后，方可进入 T001 实施。

---

## 7. 实现记录 Implementation Notes

- T001：基线分支为 `feat/2.6.0/057-domain-bindable-spaces-perf`；实施前共有 5 个用户脏文件。
- T001：`knowledge_space_service.py` 既有差异位于 import/schema、约 3777 行和约 9352 行；F059 目标位于 `SpaceLimitError` import、约 256 行、约 2289 行和约 2372 行。除 import 区需逐行精确处理外，业务逻辑区域不重叠。
- T001：`quota_service.py` 与 `test_quota_service.py` 实施前无未提交差异；本特性不编辑脏文件 `test_knowledge_space_service.py`。
- T002 RED：`.venv/bin/python -m pytest test/knowledge/test_unlimited_knowledge_space_creation.py -q` 返回 1，4 个测试均因调用 `async_count_spaces_by_user` 触发预期保护断言而失败。
- T003 GREEN：同一命令返回 0，4 个 Service、门户直通与审批 handler 用例通过。
- T004 RED：定向 quota 命令返回 1；8 个 F059 用例按预期失败，另有 20 个通用配额与配置兼容用例通过。
- T006 首轮 quota 回归：61 passed、2 failed；失败均来自租户链通用用例仍以 `knowledge_space` 断言有限配额阻断，属于已确认语义变化导致的测试预期过期，已先更新设计文件计划。
- T005 GREEN：更新两条过期的租户链用例后，quota、tenant-chain 与 decorator 组合回归为 63 passed。
- `features/` 目录被仓库 `.gitignore` 忽略，SDD 文件作为本地工作产物保存；不影响生产代码 diff 检查。
