# Feature: F059 解除知识空间创建数量上限

**Feature ID**: `059-unlimited-knowledge-space-creation`
**Status**: Confirmed — 用户已于 2026-07-16 确认
**Mode**: Spec First
**Created**: 2026-07-16
**Updated**: 2026-07-16
**Priority**: P0
**Version**: v2.6.0
**关联需求**: 首钢门户知识空间创建超过 200 个时解除限制（2026-07-16）

---

## 1. 概述

当前知识空间创建服务使用硬编码 `_MAX_SPACE_PER_USER = 200` 限制单个创建人可创建的知识空间数量。首钢门户提交知识空间创建申请时，审批预校验、审批提交、审批通过落库和直接创建都可能经过该限制；达到上限后返回 `SpaceLimitError(18001)`，门户展示 “You can create a maximum of 200 Knowledge Spaces”。

系统同时存在角色级、租户级 `knowledge_space` 数量配额。仅删除硬编码判断不能保证所有用户、所有入口真正不限量，因为旧角色或租户配置仍可能再次阻断创建。

本特性统一解除知识空间创建数量限制：固定上限、角色上限和租户上限均不再对知识空间创建生效。旧 `knowledge_space` 配额键保留兼容，但按无限量语义处理。文件上传容量、租户存储、订阅数量、创建权限、审批和其他业务校验保持不变。

### 用户故事

作为 **具备知识空间创建权限的用户**，我希望 **在已有 200 个或更多知识空间时仍能继续创建**，以便 **门户上线后不会因历史固定上限阻断知识空间扩展**。

---

## 2. 已确认业务规则

| ID | 规则 |
|----|------|
| BR-001 | 知识空间创建数量完全不限量，不设置新的固定替代值。 |
| BR-002 | 所有具备相应创建权限的用户均不受数量限制，包括普通用户、管理员和不同角色用户。 |
| BR-003 | 所有合法知识空间类型统一生效，包括公共、部门、团队及其他现有合法类型。 |
| BR-004 | 所有创建入口统一生效，包括首钢门户审批校验、审批提交、审批通过落库、BiSheng 直接创建接口及原生入口。 |
| BR-005 | 角色或租户历史 `knowledge_space` 有限配额不得阻断创建，运行时有效配额统一视为 `-1`。 |
| BR-006 | `knowledge_space_file` 文件上传容量、`storage_gb` 租户存储、知识空间订阅数量及其他资源配额继续生效。 |
| BR-007 | 创建权限、审批策略、名称唯一性、标签库、模型配置和空间层级规则保持不变。 |
| BR-008 | 不迁移、不删除现有知识空间数据，也不要求清理历史配额配置。 |

---

## 3. 范围

### 3.1 包含

- 移除知识空间创建服务中的固定 `200` 数量判断。
- 使 `validate_knowledge_space_create` 不再统计或校验创建人已有空间数量。
- 使 `create_knowledge_space` 不再统计或校验创建人已有空间数量。
- 使 `QuotaService.check_quota(..., resource_type='knowledge_space')` 始终允许创建。
- 使单项和批量有效配额查询对 `knowledge_space` 统一返回无限量语义。
- 忽略角色、租户历史配置中的有限 `knowledge_space` 数值，但继续兼容该键的读取和保存。
- 覆盖直接创建、审批预校验、审批提交和审批通过落库的回归验证。

### 3.2 不包含

- 修改知识空间文件上传容量限制 `knowledge_space_file`。
- 修改租户存储限制 `storage_gb`。
- 修改知识空间订阅上限 `_MAX_SUBSCRIBE_PER_USER`。
- 修改频道、工作流、助手、工具、看板等其他资源配额。
- 修改知识空间创建权限、审批路由、审批人或审批条件。
- 修改空间名称唯一性、层级、归属、自动标签、标签库或模型配置规则。
- 修改 `shougang-group-knowledge-portal` 独立仓库或 BiSheng Client 页面交互。
- 数据库迁移、配置批量更新、历史数据清理或生产数据操作。
- 删除 `SpaceLimitError(18001)` 或既有多语言文案；保留其兼容定义，但知识空间创建链路不再触发。

---

## 4. 需求 Requirements

### REQ-001：移除固定创建数量限制

系统不得根据创建人已有知识空间数量拒绝新的知识空间创建或创建预校验。

### REQ-002：统一所有创建入口行为

直接创建、首钢审批预校验、审批提交和审批通过落库必须共享不限量行为，不得出现某个节点通过、后续节点再次因数量失败。

### REQ-003：角色与租户数量配额失效

`knowledge_space` 数量配额必须被视为无限量；任何角色或租户中保存的 `0`、正整数或其他合法历史有限值均不得阻断创建。

### REQ-004：配额读取语义一致

系统对外返回知识空间有效配额时必须表达为 `-1`（无限量），避免后台或调用方继续认为历史有限配额有效。

### REQ-005：保留其他限制和兼容性

系统必须保持文件容量、租户存储、订阅数量、其他资源配额及知识空间其他业务校验不变；旧 `knowledge_space` 配额键继续兼容，避免角色或租户配置读写失败。

### REQ-006：保护现有工作区与改动边界

实现必须以最小补丁修改当前已有未提交变更的文件，不得重置、覆盖、stash、批量格式化或改写无关代码。

---

## 5. 验收标准 Acceptance Criteria

| ID | 关联需求 | 场景 | 预期结果 | 验证方式 |
|----|----------|------|----------|----------|
| AC-01 | REQ-001 | 创建人已有数量达到或超过 200，执行创建预校验 | 不查询或比较用户空间数量，不返回 `18001`；继续执行后续既有校验。 | Backend service 单元测试，断言计数 DAO 未调用，并观察后续校验行为。 |
| AC-02 | REQ-001 | 创建人已有数量达到或超过 200，执行实际创建 | 不查询或比较用户空间数量，不返回 `18001`；继续执行后续既有创建流程。 | Backend service 单元测试，断言计数 DAO 未调用，并观察后续创建阶段。 |
| AC-03 | REQ-002 | 门户调用审批创建预校验和提交 | 两个节点均不因知识空间数量失败；需要审批时正常提交申请，直通时正常进入创建。 | Approval service 定向测试。 |
| AC-04 | REQ-002 | 已提交申请审批通过并执行落库 handler | 审批通过后不因申请人已有空间数量失败。 | Approval handler 定向测试。 |
| AC-05 | REQ-003 | 普通用户具有角色 `knowledge_space=0/200`，或租户配置有限 `knowledge_space` 值 | `QuotaService.check_quota` 允许创建，不读取资源使用量来阻断。 | QuotaService 参数化单元测试。 |
| AC-06 | REQ-004 | 查询单项有效配额 | `knowledge_space` 返回 `-1`，不受角色或租户历史值影响。 | `get_effective_quota` 单元测试。 |
| AC-07 | REQ-004 | 查询全部有效配额 | `knowledge_space` 项的 `role_quota`、`tenant_quota` 和 `effective` 均表达无限量语义；其他资源项保持原计算。 | `get_all_effective_quotas` 单元测试。 |
| AC-08 | REQ-005 | 角色或租户配置仍包含 `knowledge_space` 键并执行配置校验/保存 | 旧键不会导致未知配置错误，保存其他配额时不会因历史键失败。 | 配额配置兼容单元测试。 |
| AC-09 | REQ-005 | 用户达到文件上传容量、租户存储或订阅上限 | 现有对应错误和阻断行为保持不变。 | 现有 quota、storage、subscription 定向回归。 |
| AC-10 | REQ-005 | 创建请求违反权限、审批、名称唯一性、标签库或模型配置规则 | 仍按现有规则拒绝，不因本特性放宽。 | KnowledgeSpaceService 与审批既有定向回归。 |
| AC-11 | REQ-006 | 检查最终差异 | 用户已有未提交修改完整保留；只出现 F059 规格、测试和目标代码差异。 | `git status`、目标文件分段 diff、`git diff --check`。 |

---

## 6. 现有架构与问题链路

### 6.1 门户入口

`shougang-group-knowledge-portal/frontend/src/pages/KnowledgeSpacesPage.tsx` 通过 iframe 嵌入 BiSheng Client。门户自身不实现知识空间数量校验。

BiSheng Client 的 `submitKnowledgeSpaceCreate` 对非个人空间调用：

```text
POST /api/v1/approval/shougang/knowledge-space-create/submit
```

### 6.2 审批链路

```text
门户确认创建
  → ShougangApprovalService.submit_knowledge_space_create
  → KnowledgeSpaceService.validate_knowledge_space_create
  ├─ 无需审批 → KnowledgeSpaceService.create_knowledge_space
  └─ 需要审批 → 创建审批实例
                    → KnowledgeSpaceCreateApprovalHandler.on_approved
                    → validate_knowledge_space_create
                    → create_knowledge_space
```

当前 `validate_knowledge_space_create` 和 `create_knowledge_space` 各自执行一次硬编码数量判断，因此不能只修改单一入口或单一审批节点。

### 6.3 配额链路

直接创建端点标注 `@require_quota(QuotaResourceType.KNOWLEDGE_SPACE)`。`QuotaService` 当前同时支持角色配额和租户配额；默认 `knowledge_space=200`，已有角色或租户也可能保存有限值。

因此不限量行为必须同时覆盖：

1. 知识空间 Service 的旧硬编码校验。
2. `QuotaService` 的创建校验。
3. 有效配额查询结果。

---

## 7. 设计方案

### 7.1 知识空间 Service

- 删除 `_MAX_SPACE_PER_USER = 200`。
- 删除 `KnowledgeSpaceService` 中不再使用的 `SpaceLimitError` import。
- 删除 `validate_knowledge_space_create` 中调用 `KnowledgeDao.async_count_spaces_by_user` 的数量判断。
- 删除 `create_knowledge_space` 中相同数量判断。
- 更新仍声称 “max 200 per user” 的注释或 docstring。
- 保留 `skip_user_limit` 参数的兼容签名，避免内部调用方或外部扩展因参数删除产生签名不兼容；参数标记为兼容保留且不再改变行为。
- 保留 `KnowledgeDao.async_count_spaces_by_user` 和 `SpaceLimitError` 定义，不做范围外清理。

### 7.2 QuotaService

定义明确的无限量资源集合，例如：

```python
UNLIMITED_RESOURCE_TYPES = {QuotaResourceType.KNOWLEDGE_SPACE}
```

具体语义：

- `DEFAULT_ROLE_QUOTA['knowledge_space']` 改为 `-1`。
- `check_quota` 对 `knowledge_space` 在角色、租户和资源用量查询前直接返回 `True`。
- `get_effective_quota` 对 `knowledge_space` 直接返回 `-1`。
- `_compute_role_quotas` 对 `knowledge_space` 固定生成 `-1`，忽略角色历史有限值。
- `get_all_effective_quotas` 对 `knowledge_space` 固定返回无限量语义，不使用租户历史有限值计算 effective。
- `VALID_QUOTA_KEYS` 继续接受 `knowledge_space`，保证旧配置和混合配置更新兼容。
- 其他资源沿用现有三层配额计算，不改变管理员、角色和租户规则。

### 7.3 API 与前端

- 不新增、不删除、不修改 API 路径、请求体或成功响应结构。
- `18001` 兼容定义继续存在，但目标创建链路不再产生该错误。
- 不修改门户或 BiSheng Client UI；后端不再返回限制错误后，现有错误提示自然不再出现。
- 有效配额 API 中 `knowledge_space` 统一显示无限量，防止调用方读取到误导性有限值。

### 7.4 数据与配置

- 不新增或修改数据库字段。
- 不创建 Alembic migration。
- 不批量更新角色或租户 `quota_config`。
- 历史 `knowledge_space` 配额数据保留但运行时忽略。
- 回滚代码后，历史配置仍可恢复原有限配额行为，数据层可逆。

---

## 8. 架构决策

| ID | 决策 | 备选方案 | 结论与理由 |
|----|------|----------|------------|
| AD-01 | 不限量范围 | 只删硬编码 / 全部数量配额不限量 | 全部不限量。用户已确认 1A、2A、3A；只删硬编码不能覆盖角色和租户配置。 |
| AD-02 | 历史配置处理 | 数据迁移删除键 / 校验拒绝旧键 / 保留并忽略 | 保留并忽略。无需数据操作，兼容现有角色和租户配置，回滚也更安全。 |
| AD-03 | 旧错误码 | 删除 `18001` / 保留未触发 | 保留未触发。减少 API 与多语言兼容风险，不做无关清理。 |
| AD-04 | `skip_user_limit` | 删除参数 / 保留兼容参数 | 保留。多个系统管理和部门空间内部调用显式传参，删除会扩大改动面。 |
| AD-05 | 配额校验入口 | 删除直接端点 decorator / QuotaService 统一短路 | QuotaService 统一短路。保留端点结构，并保证所有复用配额服务的调用方语义一致。 |
| AD-06 | 前端改动 | 删除提示文案 / 不改前端 | 不改前端。问题根因在共享后端，删除提示不能解除限制且会扩大范围。 |

---

## 9. 文件结构计划

### 9.1 新建

| 文件 | 职责 | 关联需求 |
|------|------|----------|
| `features/v2.6.0/059-unlimited-knowledge-space-creation/tasks.md` | 规格确认后的可执行任务、边界和验证追踪。 | REQ-001..REQ-006 |
| `src/backend/test/knowledge/test_unlimited_knowledge_space_creation.py` | 独立覆盖 Service 和审批链路不限量行为，避开当前脏测试文件。 | REQ-001, REQ-002, REQ-006 |
| `features/v2.6.0/059-unlimited-knowledge-space-creation/verification.md` | 记录实际命令、退出码和 AC 覆盖结果。 | REQ-001..REQ-006 |

### 9.2 修改

| 文件 | 变更内容 | 关联需求 |
|------|----------|----------|
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | 移除固定数量校验并保留兼容参数。 | REQ-001, REQ-002, REQ-006 |
| `src/backend/bisheng/role/domain/services/quota_service.py` | 将 `knowledge_space` 创建校验及有效配额统一为无限量。 | REQ-003, REQ-004, REQ-005 |
| `src/backend/test/test_quota_service.py` | 更新旧的 200 配额预期，覆盖角色、租户历史值忽略及批量有效配额。 | REQ-003, REQ-004, REQ-005 |
| `src/backend/test/test_quota_service_check_chain.py` | 将两条通用租户链阻断用例改用仍受限的 `channel`，避免与知识空间不限量规则冲突。 | REQ-003, REQ-005 |

### 9.3 明确不修改

- `shougang-group-knowledge-portal/**`
- `src/frontend/client/**`
- 数据库 migration 与配置文件
- `src/backend/bisheng/common/errcode/knowledge_space.py`
- 多语言 JSON
- 当前 F057 的 `shougang_portal.py`、schema 和业务域测试改动

---

## 10. 测试策略与验证矩阵

| Verification ID | 方法 | 覆盖 AC |
|-----------------|------|---------|
| V-001 | 新增 `test_unlimited_knowledge_space_creation.py`，证明预校验与创建不再调用用户空间计数。 | AC-01, AC-02 |
| V-002 | 审批 service/handler 定向测试，覆盖预校验、提交、直通和审批通过。 | AC-03, AC-04, AC-10 |
| V-003 | `test_quota_service.py` 参数化测试有限角色/租户值、单项配额和批量配额。 | AC-05, AC-06, AC-07, AC-08 |
| V-004 | 现有 storage、knowledge-space upload、subscription 定向回归。 | AC-09 |
| V-005 | 现有 KnowledgeSpaceService 权限、名称、标签库、模型配置定向回归。 | AC-10 |
| V-006 | `ruff check`、`ruff format --check`、`python -m compileall`，仅覆盖 F059 修改文件。 | 代码质量 |
| V-007 | `git status --short --branch`、分段 diff、`git diff --check`。 | AC-11 |

建议命令在 `tasks.md` 中按实际测试收集进一步收窄，避免以全量仓库既有失败掩盖本功能结果。

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| `knowledge_space_service.py` 已有 F057 未提交修改 | 不当编辑可能覆盖用户工作 | 只对常量区和两处创建校验做精确小补丁；修改前后保存分段 diff；不批量格式化该文件。 |
| `test_knowledge_space_service.py` 已有未提交修改 | 新测试可能产生写冲突 | 新建独立 `test/knowledge/test_unlimited_knowledge_space_creation.py`，不修改该脏测试文件。 |
| 无限创建增加资源数量 | 列表、权限和搜索范围可能随空间数增长 | 本特性保留存储/文件容量限制；性能优化不在本范围，出现可观察瓶颈后单独立项。 |
| 旧配置仍保存有限值 | 管理或运维人员可能误解其含义 | 有效配额 API 固定返回 `-1`；规格明确该键仅为兼容历史数据。 |
| 配额短路误伤其他资源 | 文件容量或租户存储可能被意外放宽 | 短路条件必须严格等于 `knowledge_space`，并执行 `knowledge_space_file`、`storage_gb` 及其他资源回归。 |

---

## 12. 回滚方案

- 回滚 F059 对 `knowledge_space_service.py` 和 `quota_service.py` 的局部代码变更。
- 无数据库 migration，无数据恢复步骤。
- 历史角色和租户 `knowledge_space` 配额值未删除，代码回滚后会恢复原配额行为。
- 回滚不会影响现有知识空间、文件、审批实例或权限关系。

---

## 13. 澄清记录 Clarifications

### Session 2026-07-16

- Q: 数量策略是否完全不限量？ -> A: `1A`，固定、角色和租户知识空间数量配额全部解除。
- Q: 是否覆盖所有创建入口？ -> A: `2A`，门户审批、审批通过、直接创建和 BiSheng 原生入口全部覆盖。
- Q: 是否覆盖所有用户和空间类型？ -> A: `3A`，所有具备权限的用户和所有合法空间类型统一覆盖。

---

## 14. 需求与设计质量门

- [x] 每个 requirement 具有稳定 `REQ-*` ID。
- [x] 每个 acceptance criterion 具有稳定 ID 和验证方式。
- [x] 所有 requirement 均映射到设计和文件边界。
- [x] Includes 与 Excludes 明确。
- [x] API、数据、配置和回滚影响明确。
- [x] 不存在阻塞规划的关键歧义。
- [x] 当前工作区脏文件和冲突规避策略已记录。
- [x] 用户已确认本规格，可以创建 `tasks.md` 并进入任务评审。
