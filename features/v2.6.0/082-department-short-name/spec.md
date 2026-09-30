# Feature: 部门简称

**Feature ID**: F082-department-short-name

**状态**: ⚠️ 主体及历史简称回填脚本已实现；真实数据库、HTTP E2E 与浏览器多语言门禁仍待完成

**优先级**: P1（暂定，不影响已确认范围）

**所属版本**: v2.6.0

**模式**: spec-then-implement

**创建日期**: 2026-08-10

**更新日期**: 2026-08-21

**关联 Feature**: F002-department-tree、F009-org-sync、F014-sso-org-realtime-sync、F015-ldap-reconcile-celery

---

## 0. 阅读摘要

本特性为组织与成员模块的部门增加可选字段 `short_name`（部门简称）。管理员可以在创建部门时填写简称，也可以在部门设置中修改或清空简称。简称只作为独立的基础信息保存，不替代部门名称，不参与组织树展示、搜索、唯一性判断、权限或同步匹配。

字段采用 `VARCHAR(64) NULL`。创建时省略、传 `null` 或仅输入空白均存为 `NULL`；更新时使用三态语义：省略字段表示保持不变，字符串表示去除首尾空格后保存，显式 `null` 表示清空。第三方同步部门的完整名称继续只读，但简称允许管理员本地维护，后续同步不得覆盖简称。

为已有活动部门提供一次性、人工触发的简称回填脚本。脚本扫描所有租户和所有来源，只处理尚无有效简称的活动部门；当部门全称以其直接父部门全称为完整前缀时，截掉此前缀并将去除首尾空白后的结果作为简称。脚本默认只读预览，只有显式传入 `--apply` 才写库；根部门、归档部门、已有简称、无法匹配或结果不合法的数据均跳过并分类报告。Alembic migration、应用启动和组织同步仍不自动执行回填。

本规格只扩展 `Department.short_name` 的字段写入契约，不取得 F002 对 `Department` 其他 CRUD 行为的所有权，也不改变 F009/F014/F015 的组织同步事实源。

---

## 1. 背景与已确认需求

### 1.1 当前状态

- Platform 前端的部门设置基础信息目前只有“部门名称”和“上级部门”。
- 创建部门表单目前只提交 `name`、`parent_id` 和可选管理员。
- `department` 表和 `Department` ORM 当前没有简称字段。
- 部门详情接口直接序列化 `Department` ORM；创建和更新请求通过 `DepartmentCreate` / `DepartmentUpdate` 显式定义字段。
- 第三方同步部门的 `name` 由上游维护，当前禁止在部门设置中手工修改。

### 1.2 用户故事

作为 **组织管理员或部门管理员**，

我希望 **在创建部门和维护部门设置时记录部门简称**，

以便 **在不改变正式部门名称及现有组织逻辑的前提下保存更精简的部门标识**。

### 1.3 澄清记录

| 日期 | 问题 | 用户确认 |
|------|------|----------|
| 2026-08-10 | 简称录入范围 | 创建部门和部门设置都提供简称字段；左侧组织树继续显示完整名称 |
| 2026-08-10 | 字段规则 | 字段名 `short_name`；选填；填写时 1～64 个字符；去除首尾空格；允许清空；不唯一；历史数据为 `NULL` |
| 2026-08-10 | 第三方同步部门 | 完整名称继续只读，简称允许管理员手工维护，组织同步不得覆盖简称 |
| 2026-08-21 | 历史数据回填范围 | 使用独立脚本扫描所有租户、所有来源，仅处理 `active` 且无有效简称的部门；不处理归档部门 |
| 2026-08-21 | 回填解析规则 | 只使用直接父部门；仅当子部门全称以父部门全称为完整前缀时截取；未匹配、根部门、空结果或超过 64 字符时跳过 |
| 2026-08-21 | 已有简称保护 | `NULL`、空字符串和纯空白视为未填写；任何非空白简称均不得覆盖 |

---

## 2. 范围

### 2.1 包含

- 为 `department` 表和 `Department` ORM 增加可空 `short_name` 字段。
- 部门创建、详情、更新接口支持 `short_name`。
- 创建部门表单在“部门名称”下方增加“部门简称”输入框。
- 部门设置的“基础信息”在“部门名称”下方增加“部门简称”输入框。
- 前后端统一执行空值、去空格和 64 字符上限规则。
- 允许清空已保存的简称，并区分“更新时未提交字段”和“显式清空字段”。
- 第三方同步部门允许手工维护简称；同步更新不得覆盖已保存简称。
- 已归档部门保持只读，简称不可编辑。
- 补充 Platform 现有生产语言的 i18n 文案。
- 提供 Alembic 升级和降级迁移，并验证 MySQL / DM8 兼容性约束。
- 提供独立的历史简称回填脚本，默认 dry-run，显式 `--apply` 后才更新符合规则的数据。
- 回填脚本覆盖所有租户和所有来源，但仅处理 `active` 部门，并输出扫描、拟更新/实际更新及各类跳过统计。

### 2.2 不包含

- 不用简称替换左侧组织树、部门选择器或成员路径中的完整部门名称。
- 不按简称搜索部门，也不改变现有部门名称搜索规则。
- 不要求简称全局唯一或同级唯一，不新增索引和唯一约束。
- 不从飞书、企业微信、钉钉、LDAP、Gateway 或首钢组织同步载荷读取简称；回填脚本只消费已落库的名称和父子关系。
- 不在 Alembic、应用启动、定时任务或组织同步过程中自动执行历史简称回填。
- 不为归档部门、根部门、父名称非前缀部门或解析结果不合法的部门生成简称。
- 不覆盖任何已有非空白简称，也不提供自动反向清空或覆盖人工值的能力。
- 不改变第三方同步部门 `name` 的只读规则。
- 不改变部门权限、多租户过滤、物化路径、归档、移动、成员、默认角色或管理员逻辑。
- 不改动 Client 前端 `src/frontend/client/`。
- 不新增依赖、错误码、接口端点或数据库表。

---

## 3. 需求 Requirements

### REQ-001：部门简称持久化

系统必须为每个部门保存一个独立、可选、最大 64 个字符的简称，并兼容所有历史部门。

### REQ-002：创建与维护

有现有部门管理权限的管理员必须能够在创建部门时填写简称，并在部门设置中读取、修改或清空简称。

### REQ-003：输入规范化与更新语义

系统必须去除简称首尾空格，将空字符串规范化为 `NULL`，并在更新接口中区分“字段未提交”和“显式清空”。

### REQ-004：同步来源边界

第三方同步部门的名称继续由上游控制，但其简称属于本地维护字段，任何现有组织同步创建、更新、重放或校对流程都不得覆盖已保存的简称。

### REQ-005：现有行为兼容

新增简称不得改变组织树展示、部门搜索、名称唯一性、权限、多租户隔离和归档只读行为。

### REQ-006：历史部门简称安全回填

系统必须提供一个人工运行的一次性脚本，扫描所有租户、所有来源中状态为 `active` 且简称为空的部门。当且仅当部门全称以直接父部门全称为完整前缀，且截取并去除首尾空白后的结果为 1～64 个字符时，脚本才能填入简称。脚本必须默认只读预览，显式确认后才写入，并对不可处理数据分类报告；不得覆盖已有有效简称。

---

## 4. 验收标准 Acceptance Criteria

| ID | 关联需求 | 场景 | 预期结果 |
|----|----------|------|----------|
| AC-01 | REQ-001 | 对包含历史部门数据的数据库执行升级迁移 | `department.short_name` 创建为可空 `VARCHAR(64)`；历史行值为 `NULL`；无数据回填和唯一索引 |
| AC-02 | REQ-001 | 执行迁移降级 | 仅移除 `department.short_name`；其他部门字段和数据不受影响 |
| AC-03 | REQ-002, REQ-003 | `POST /api/v1/departments/` 提交 `short_name: "  研发  "` | 创建成功，数据库和响应中的 `short_name` 为 `"研发"` |
| AC-04 | REQ-002, REQ-003 | 创建部门时省略 `short_name`、传 `null`、传空字符串或仅空白 | 均创建成功，数据库和响应中的 `short_name` 为 `null` |
| AC-05 | REQ-002 | `GET /api/v1/departments/{dept_id}` 查询有简称或无简称的部门 | 详情响应包含 `short_name`，值分别为已保存字符串或 `null` |
| AC-06 | REQ-002, REQ-003 | `PUT /api/v1/departments/{dept_id}` 提交非空 `short_name` | 去除首尾空格后保存并返回规范化值；重新查询结果一致 |
| AC-07 | REQ-003 | 更新接口省略 `short_name` | 保持数据库中原简称不变 |
| AC-08 | REQ-002, REQ-003 | 更新接口显式提交 `short_name: null`、空字符串或仅空白 | 原简称被清空为 `NULL`，响应和重新查询均返回 `null` |
| AC-09 | REQ-003 | 创建或更新接口提交去除首尾空格后超过 64 个字符的简称 | 请求被参数校验拒绝，不写入或修改部门数据 |
| AC-10 | REQ-002 | 管理员打开创建部门表单 | “部门名称”下方显示可选“部门简称”输入框；有效输入随创建请求提交 |
| AC-11 | REQ-002, REQ-003 | 管理员打开部门设置并修改、清空、取消或保存简称 | 正确回显服务端值；未保存变更可恢复；保存只提交发生变化的字段；刷新后结果一致 |
| AC-12 | REQ-004, REQ-005 | 管理员打开第三方同步部门设置 | 部门名称保持禁用，部门简称可编辑并可保存 |
| AC-13 | REQ-004 | 已有简称的第三方同步部门发生重命名、重放或校对更新 | `name` 按既有规则更新，`short_name` 保持不变 |
| AC-14 | REQ-005 | 打开已归档部门设置 | 部门名称和部门简称均为只读，不能提交简称修改 |
| AC-15 | REQ-005 | 查看组织树、使用现有部门搜索或创建同简称部门 | 组织树和搜索继续使用完整 `name`；相同简称允许存在；现有同级名称重复校验不变 |
| AC-16 | REQ-002, REQ-005 | 切换 `zh-Hans`、`en-US`、`ja` | 部门简称的标签、占位符和校验提示无 raw key，且不影响现有文案 |
| AC-17 | REQ-006 | 默认运行回填脚本，数据包含多个租户和不同 `source` 的符合条件活动部门 | 脚本扫描全部目标数据并报告 `would_update`，数据库中所有 `short_name` 保持不变 |
| AC-18 | REQ-006 | 使用 `--apply` 处理“父部门：北京首钢股份有限公司；子部门：北京首钢股份有限公司炼铁作业部” | 子部门简称写为“炼铁作业部”；再次运行 dry-run 时该行不再进入 `would_update` |
| AC-19 | REQ-006 | 候选数据包含归档部门、根部门、已有非空白简称、父记录缺失/跨租户、父名称不是前缀、截取后为空或超过 64 字符 | 这些行均不修改，并按明确原因计入跳过统计；其他合法部门仍可处理 |
| AC-20 | REQ-004, REQ-006 | 回填后发生第三方组织同步，或同一脚本重复执行 | 已回填简称不被同步或脚本覆盖；重复执行不会产生额外更新 |

### 4.1 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---------------|-----------------|--------|-----------------|
| AC-01, AC-02 | V-DB-01 | Alembic + schema inspection | 迁移定向测试；`uv run alembic heads`；MySQL 本地/CI 升降级；DM8 CI 升级 |
| AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09 | V-BE-01 | Backend automated tests | `uv run pytest test/department/ -k short_name` |
| AC-10, AC-11, AC-12, AC-14 | V-FE-01 | Vitest component/payload tests | `npm test -- src/test/departmentSettingsPayload.test.tsx src/test/createDepartmentShortName.test.tsx` |
| AC-13 | V-SYNC-01 | Backend sync regression test | `uv run pytest test/sso_sync/ -k short_name` |
| AC-15 | V-REG-01 | Existing targeted regression | 部门 API/Service 定向回归与 Platform 部门相关 Vitest |
| AC-16 | V-I18N-01 | Static key parity + manual smoke | JSON 解析/键集合检查；三种语言手动切换 |
| AC-03, AC-05, AC-06, AC-08 | V-E2E-01 | Project E2E gate | `uv run pytest test/e2e/test_e2e_department_tree.py -k short_name` |
| AC-17, AC-18, AC-19, AC-20 | V-SCRIPT-01 | Script contract/integration tests | `uv run pytest test/scripts/test_backfill_department_short_names.py`；覆盖 dry-run、apply、跨租户/来源、保护规则、跳过原因和幂等性 |

---

## 5. 架构与设计

### 5.1 现有链路

```text
CreateDepartmentDialog / DepartmentSettings
  → controllers/API/department.ts
  → /api/v1/departments/
  → department/api/endpoints/department.py
  → DepartmentService
  → Department ORM
  → department 表
```

本特性沿用现有链路，不新增层、端点、Store 或状态管理方案。

### 5.2 架构边界

| Boundary | 允许变更 | 禁止变更 | 重新评审触发条件 |
|----------|----------|----------|------------------|
| Department 数据模型 | 仅新增 `short_name` 可空字段 | 修改 `name`、路径、租户、同步键或唯一约束 | 简称需要唯一、必填、回填或参与查询 |
| Department API | 扩展现有创建/详情/更新请求响应 | 新增端点或改变现有字段语义 | 简称需要树接口、批量接口或外部 API |
| Platform 前端 | 创建和设置表单录入/回显/保存 | 改组织树、搜索或 Client 前端 | 简称需要展示在其他页面 |
| 组织同步 | 保留本地简称 | 从上游读取、映射或覆盖简称 | 上游提供正式简称字段 |
| 权限与多租户 | 完全复用现有部门权限与自动租户过滤 | 新增授权关系或手写 `tenant_id` 条件 | 简称被用作新的资源标识 |

### 5.3 数据模型与迁移

`Department` 增加：

```python
short_name: str | None = Field(
    default=None,
    sa_column=Column(
        String(64),
        nullable=True,
        comment="Optional department short name maintained locally",
    ),
)
```

迁移契约：

- 文件：`v2_6_0_f082_department_short_name.py`。
- Revision：`f082_department_short_name`。
- Down revision：实现时以当时唯一 Alembic head 为准；当前规划基线为 `f081_knowledge_file_original_origin`。
- Upgrade：使用 SQLAlchemy `inspect()` 判断字段是否存在后添加 `VARCHAR(64) NULL`。
- 不设置 server default，不回填，不增加索引。
- Downgrade：字段存在时删除。
- 迁移必须使用通用 SQLAlchemy 类型和 introspection，不使用 MySQL 专属 SQL、`information_schema` 或 `DATABASE()`。

### 5.4 API 契约

#### 创建请求

```json
{
  "name": "研发中心",
  "short_name": "研发",
  "parent_id": 1
}
```

- `short_name` 可省略或传 `null`。
- 字符串先去除首尾空格；规范化后为空则转为 `null`。
- 规范化后长度范围为 1～64。

#### 更新请求

```json
{
  "short_name": null
}
```

更新采用三态语义：

| 请求状态 | 行为 |
|----------|------|
| 不包含 `short_name` | 保持现有值 |
| `short_name` 为字符串 | 规范化后保存 |
| `short_name` 为 `null`、空字符串或仅空白 | 清空为 `NULL` |

后端不得使用单纯的 `if data.short_name is not None` 判断是否更新；必须依据 Pydantic 的显式字段集合区分“省略”和“显式清空”。

#### 响应

- 创建、更新和部门详情响应均包含 `short_name: string | null`。
- `GET /api/v1/departments/tree` 不新增简称展示契约；部门设置继续通过详情接口加载简称。

### 5.5 Service 行为

- `acreate_department` 将规范化后的 `data.short_name` 写入 `Department`。
- `aupdate_department` 仅在请求显式包含 `short_name` 时更新字段，允许写入 `None` 完成清空。
- source-readonly 校验继续只限制 `data.name`；不得因 `short_name` 更新抛出 `DepartmentSourceReadonlyError`。
- 归档只读校验保持在所有字段更新之前，归档部门不得修改简称。
- 简称不进入同级名称重复查询。
- `aget_department`、创建和更新端点沿用 ORM `model_dump()` 返回简称，无需新增查询。

### 5.6 组织同步保护

- 现有同步创建部门时不传 `short_name`，新部门简称自然为 `NULL`。
- 现有同步更新必须保持字段级更新，只更新 `name`、父级、路径、排序、状态和同步时间戳等既有同步字段。
- 禁止把同步 DTO 扩展为 `short_name`，也禁止在同步 update `.values(...)` 中将简称写为 `NULL`。
- 增加回归测试证明已有本地简称在同步重命名和 upsert 后仍保留。

### 5.7 Platform 前端

#### 创建部门

- `CreateDepartmentDialog` 增加 `shortName` 本地状态。
- 在部门名称控件下方增加可选输入框，`maxLength={64}`。
- 提交前去除首尾空格；空值可省略或传 `null`，后端仍为最终规范化边界。

#### 部门设置

- `DepartmentSettings` 增加简称状态及 baseline 快照。
- 详情 `null` 映射为空输入框；保存时空输入映射为显式 `null`。
- 未修改简称时不提交该字段。
- 简称参与未保存变更检测、取消恢复和保存后 baseline 更新。
- `canEditShortName = !isArchived`；不受 `isSynced` 限制。
- 名称继续使用既有 `canEditName = !isArchived && !isSynced`。

#### 类型与 i18n

- `DepartmentDetail` 增加 `short_name: string | null`。
- `DepartmentCreateForm` 增加 `short_name?: string | null`。
- `DepartmentUpdateForm` 增加 `short_name?: string | null`。
- `DepartmentTreeNode` 不增加展示依赖。
- 在 `zh-Hans`、`en-US`、`ja` 的 `bs.json` 中增加一致的简称标签、占位符和长度提示键。

### 5.8 历史简称回填脚本

#### 运行入口与安全门

- 新增 `src/backend/scripts/backfill_department_short_names.py`，从 `src/backend/` 目录运行。
- 默认模式为 dry-run，只计算候选、解析结果和跳过原因，不执行 `UPDATE` 或 `COMMIT`。
- 只有显式传入 `--apply` 才允许写入；脚本不挂接 Alembic、应用启动、Celery、组织同步或任何定时入口。
- 脚本通过 `bypass_tenant_filter()` 扫描所有租户；不得伪造单一 `tenant_id` 上下文，也不得漏掉非 `sg` 来源。
- 使用按 `Department.id` 稳定排序的 keyset 批次，避免一次性加载整张部门表；允许配置批大小，但不改变业务范围。

#### 候选与解析

每行按以下顺序判定，任一条件不满足即跳过并记录唯一主原因：

1. 部门 `status` 必须为 `active`。
2. `short_name` 必须为 `NULL`、空字符串或纯空白；非空白值一律保护。
3. `parent_id` 必须存在，且能读取同租户的直接父部门；父子租户不一致按异常数据跳过，不遍历祖先链。
4. 子部门 `name` 必须以直接父部门 `name` 为区分大小写的完整前缀，使用精确字符串语义，不做模糊匹配或中间位置替换。
5. 截掉此前缀后执行 `strip()`；结果必须为 1～64 个字符。

例如父部门为“北京首钢股份有限公司”，子部门为“北京首钢股份有限公司炼铁作业部”，候选简称为“炼铁作业部”。

#### 写入与并发保护

- apply 只更新 dry-run 规则仍然成立、且写入瞬间简称仍为空白的行；禁止无条件覆盖整个 ORM 对象。
- 数据在扫描后发生变化时，该行按 `changed_before_update` 跳过，不使用旧快照覆盖新名称、父级、状态或简称。
- 同一合法输入重复运行是幂等的：首次写入后，后续运行会按“已有简称”跳过。
- 单行数据异常只影响该行；数据库连接、事务或提交失败属于基础设施错误，当前批次回滚并以非零退出码终止，不能继续声称成功。

#### 输出与审计

脚本输出机器可读 JSON，至少包含：

- `mode`：`dry_run` 或 `apply`。
- `scanned`、`eligible`、`would_update`、`updated`。
- `skipped` 总数及按原因聚合的 `reason_counts`。
- 有界的候选与跳过样例，包含稳定部门 ID、租户 ID、原名称、父名称、候选简称或跳过原因；不得输出无关用户数据。
- `next_start_after_id` 或等价批次游标信息，便于大数据量执行中断后审计；本期不承诺自动恢复写入。

脚本不提供自动回滚。正式执行前必须保存 dry-run 输出并完成数据库备份；需要撤销时依据备份或审核后的更新记录处理，不能通过再次运行脚本恢复原空值。

---

## 6. 设计决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 历史数据兼容 | A: nullable 且 migration 不回填 / B: 必填并由 migration 回填名称 / C: 空字符串默认值 | 选 A | 字段仍为选填；结构迁移保持零数据变更，历史回填只通过独立人工脚本执行 |
| AD-02 | 字段长度 | A: 20 / B: 50 / C: 64 | 选 C | 用户明确确认 1～64 个字符 |
| AD-03 | 更新清空语义 | A: `null` 清空、缺失不变 / B: 空字符串持久化 / C: 单独清空端点 | 选 A | 可复用现有 PUT，且能准确表达可选字段生命周期 |
| AD-04 | 同步部门简称 | A: 本地可编辑并保留 / B: 与名称一起只读 / C: 从上游同步 | 选 A | 用户确认，且当前上游 DTO 没有简称字段 |
| AD-05 | 组织树 | A: 继续只显示 `name` / B: 优先显示简称 / C: 同时显示 | 选 A | 用户确认；避免改变搜索、路径和既有认知 |
| AD-06 | 唯一性 | A: 不唯一 / B: 同级唯一 / C: 全租户唯一 | 选 A | 用户确认；简称不是业务键 |
| AD-07 | 参数错误处理 | A: 复用 Pydantic 校验 / B: 新增 210xx 业务错误码 | 选 A | 长度属于请求字段约束，无需扩大错误码范围 |
| AD-08 | 回填匹配规则 | A: 直接父名称精确前缀 / B: 任意位置删除 / C: 遍历全部祖先 | 选 A | 用户确认；避免误删名称中间的同名文本或扩大祖先推断范围 |
| AD-09 | 回填写入门禁 | A: dry-run 默认、`--apply` 写入 / B: 默认直接写入 | 选 A | 全租户批量更新需要先审计影响范围，并保护人工简称和并发变更 |

---

## 7. 文件结构计划

### 7.1 新建

| 文件 | 职责 | 关联需求 |
|------|------|----------|
| `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f082_department_short_name.py` | 添加/移除可空简称字段 | REQ-001 |
| `src/backend/test/core/database/test_department_short_name_migration.py` | 验证迁移升级、历史空值与降级边界 | REQ-001 |
| `src/backend/test/department/test_department_short_name.py` | 请求规范化、创建/详情/更新三态语义回归 | REQ-001～REQ-003 |
| `src/backend/test/sso_sync/test_department_short_name_preservation.py` | 同步重命名/upsert 不覆盖简称 | REQ-004 |
| `src/backend/scripts/backfill_department_short_names.py` | 全租户历史部门简称 dry-run/apply 回填与审计输出 | REQ-006 |
| `src/backend/test/scripts/test_backfill_department_short_names.py` | 回填规则、保护边界、跨租户/来源、dry-run/apply 与幂等回归 | REQ-006 |
| `src/frontend/platform/src/test/createDepartmentShortName.test.tsx` | 创建表单简称 payload 回归 | REQ-002, REQ-003 |
| `features/v2.6.0/082-department-short-name/verification.md` | 记录实现后的自动化、E2E、MySQL/DM8、回填脚本与人工证据 | REQ-001～REQ-006 |

### 7.2 修改

| 文件 | 职责 | 关联需求 |
|------|------|----------|
| `src/backend/bisheng/database/models/department.py` | 定义 ORM `short_name` 字段 | REQ-001 |
| `src/backend/bisheng/department/domain/schemas/department_schema.py` | 创建/更新 DTO 与规范化规则 | REQ-002, REQ-003 |
| `src/backend/bisheng/department/domain/services/department_service.py` | 创建写入与更新三态处理 | REQ-002～REQ-005 |
| `src/backend/test/test_department_api.py` | 现有 SQLite fixture 表结构与 API 契约适配 | REQ-001～REQ-003 |
| `src/backend/test/test_department_service.py` | 现有 SQLite fixture 表结构适配 | REQ-001～REQ-003 |
| `src/backend/test/e2e/test_e2e_department_tree.py` | 创建、查询、更新和清空的单条 E2E 契约场景 | REQ-001～REQ-003 |
| `src/frontend/platform/src/types/api/department.ts` | 前端详情、创建、更新类型 | REQ-002, REQ-003 |
| `src/frontend/platform/src/pages/DepartmentPage/components/CreateDepartmentDialog.tsx` | 创建时录入简称 | REQ-002, REQ-003 |
| `src/frontend/platform/src/pages/DepartmentPage/components/DepartmentSettings.tsx` | 回显、修改、清空、恢复和保存简称 | REQ-002～REQ-005 |
| `src/frontend/platform/src/pages/DepartmentPage/components/DepartmentBasicInfoSection.tsx` | 承载基础信息字段，保持 `DepartmentSettings.tsx` 不超过 600 行 | REQ-002, REQ-005 |
| `src/frontend/platform/src/test/departmentSettingsPayload.test.tsx` | 设置页更新、清空及同步部门可编辑回归 | REQ-002～REQ-005 |
| `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json` | 简称相关三语文案 | REQ-002, REQ-005 |
| `src/backend/scripts/README.md` | 记录脚本用途、dry-run/apply 命令、风险和执行后复核方式 | REQ-006 |

如实现检索发现现有测试 fixture 还有独立的手写 `department` DDL，只允许进行增加 `short_name` 列的最小适配，并记录到 `tasks.md §实际偏差记录`；不得顺手重构测试基础设施。

---

## 8. 测试策略

| Acceptance IDs | 风险 / 层级 | 独立结果 | 主要测试层 | Evidence Group | 停止条件 |
|----------------|-------------|----------|------------|----------------|----------|
| AC-01, AC-02 | 中 / V2 | 升级保留历史数据、降级只删目标列 | migration integration | EG-DB | 迁移结构断言通过且 Alembic 单 head |
| AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09 | 中 / V2 | 创建、查询、更新、清空、缺失不变、超长拒绝 | backend API/service integration | EG-BE | 三态与边界结果均有可执行证据 |
| AC-10, AC-11, AC-12, AC-14 | 中 / V2 | 创建 payload、设置回显/保存/清空、同步可编辑、归档只读 | Vitest component/payload | EG-FE | DOM 状态与请求 payload 行为通过 |
| AC-13 | 中 / V2 | 同步更新保留本地简称 | DAO/sync integration | EG-SYNC | 至少覆盖同步重命名和 upsert 更新 |
| AC-15 | 低 / V1 | 树、搜索、名称唯一性无变化 | targeted regression | EG-REG | 相关现有回归通过，无简称进入既有判断 |
| AC-16 | 低 / V0+manual | 三语键一致且页面无 raw key | static/manual | EG-I18N | JSON/键检查通过，三语烟测完成 |
| AC-03, AC-05, AC-06, AC-08 | 项目门禁 / V3 | 创建后查询、更新后查询、清空后查询 | backend E2E | EG-E2E | 一条完整契约场景通过，不复制边界用例 |
| AC-17, AC-18, AC-19, AC-20 | 高 / V2 | 跨租户 dry-run 无写入、apply 精确回填、保护/异常跳过、重复执行幂等 | script integration | EG-SCRIPT | 聚焦脚本测试通过；未连接真实库时明确保留人工 dry-run/apply 门禁 |

最终相关回归不要求运行整个 monorepo 测试集；只有定向验证失败、影响面扩大或 CI 门禁要求时才升级范围。DM8 驱动在 macOS 不可用，真实 DM8 迁移验证由 Linux CI 完成，并在最终验证记录中明确证据状态。

---

## 9. 发布、兼容与回滚

### 9.1 发布顺序

1. 先执行 additive Alembic upgrade，创建 nullable 列。
2. 再部署支持 `short_name` 的后端和 Platform 前端。
3. 观察部门创建/更新错误率和组织同步日志。
4. 部署稳定后单独运行回填脚本 dry-run，保存并审核 JSON；完成数据库备份和独立执行确认后才运行 `--apply`。
5. apply 后再次 dry-run，确认 `would_update=0` 或仅剩已知跳过项；抽样核对简称与直接父部门前缀规则一致。

旧版本应用会忽略新增数据库列；新版本应用在迁移完成后读写该列，因此向前兼容。禁止在未执行迁移的数据库上部署新后端。

### 9.2 回滚

1. 先回滚后端和前端到不读取 `short_name` 的版本。
2. 确认无新版本实例后，再执行 Alembic downgrade 删除列。
3. Downgrade 会永久删除已填写的简称数据；执行前必须确认接受该数据损失或先行备份。
4. 回填脚本本身不提供自动回滚；若误填，依据执行前数据库备份或审核后的更新记录恢复，禁止盲目批量清空简称。

---

## 10. 非功能要求

- **兼容性**：MySQL 与 DM8 均可执行迁移和回填脚本；单租户和多租户模式行为不变。
- **安全与权限**：完全复用现有部门管理权限，不新增权限入口，不手写租户条件。
- **性能**：在线请求不新增查询、JOIN、索引或树节点负载；回填脚本使用稳定 keyset 批次，避免全表一次性加载。
- **可维护性**：规范化和三态语义在后端作为最终事实源，前端只做交互级预处理。
- **国际化**：生产语言键集合一致，不引入硬编码用户文案。

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 更新 DTO 无法区分缺失与 `null` | 清空简称失败或误清空旧值 | 使用显式字段集合判断，并覆盖三态回归测试 |
| 同步更新使用全模型覆盖 | 本地简称在重命名/校对时丢失 | 保持字段级 update，并增加同步保留测试 |
| 手写测试 DDL 未增加新列 | API 测试与真实模型不一致 | 最小更新相关 fixture DDL，运行部门定向回归 |
| Alembic head 在实现前变化 | 产生多 head，阻塞部署 | 创建迁移时重新执行 `alembic heads` 并绑定当时唯一 head |
| 前后端长度或空值规则不一致 | UI 可提交但 API 拒绝，或空字符串落库 | 后端统一规范化；前端相同限制；覆盖边界测试 |
| Downgrade 删除简称数据 | 回滚后无法恢复已填写简称 | 回滚顺序中明确先停新代码，并在删列前备份/确认 |
| 全租户回填范围过大 | 一次误判会批量写入错误简称 | 默认 dry-run、精确直接父前缀、已有值保护、批次写前复核和显式 `--apply` |
| 扫描期间部门名称或层级变化 | 旧快照可能写入过期简称 | apply 写入前复核名称、父级、状态和当前简称；变化行跳过 |
| 脚本执行后需要撤销 | 无法仅凭当前数据区分人工简称与脚本简称 | 执行前备份并保存 dry-run/apply 审计输出；不提供盲目反向脚本 |

---

## 12. 需求追踪矩阵

| Requirement | Acceptance Criteria | 设计元素 | Verification |
|-------------|---------------------|----------|--------------|
| REQ-001 | AC-01, AC-02, AC-05 | ORM、Alembic、详情序列化 | V-DB-01, V-BE-01, V-E2E-01 |
| REQ-002 | AC-03, AC-04, AC-05, AC-06, AC-10, AC-11 | Create/Update DTO、Service、Platform 表单 | V-BE-01, V-FE-01, V-E2E-01 |
| REQ-003 | AC-03, AC-04, AC-06, AC-07, AC-08, AC-09, AC-11 | 规范化、更新三态、baseline/payload | V-BE-01, V-FE-01, V-E2E-01 |
| REQ-004 | AC-12, AC-13, AC-20 | source-readonly 边界、同步字段保护、回填后同步保留 | V-FE-01, V-SYNC-01, V-SCRIPT-01 |
| REQ-005 | AC-12, AC-14, AC-15, AC-16 | 归档只读、树/搜索边界、i18n | V-FE-01, V-REG-01, V-I18N-01 |
| REQ-006 | AC-17, AC-18, AC-19, AC-20 | 回填脚本、精确父前缀解析、dry-run/apply 门禁、写前复核和审计输出 | V-SCRIPT-01 |

---

## 13. 规格质量门

- [x] 每个 Requirement 均有稳定 `REQ-*` ID。
- [x] 每个验收标准均有稳定 `AC-*` ID 和 Verification ID。
- [x] 范围包含项和排除项明确。
- [x] 创建、更新、清空、空值、超长、同步、归档和历史回填边界均可观察。
- [x] 数据迁移、兼容、发布和回滚策略明确。
- [x] 所有 Requirement 均进入追踪矩阵。
- [x] 验证采用最低充分层级，未机械要求全量测试。
- [x] 未引入新架构、依赖、端点、权限或错误码。
- [x] 无阻塞实现的关键歧义。

---

## 相关文档

- [v2.6.0 Release Contract](../release-contract.md)
- [F002 部门树规格](../../v2.5.0/002-department-tree/spec.md)
- [F009 组织同步规格](../../v2.5.0/009-org-sync/spec.md)
- `src/backend/AGENTS.md`
