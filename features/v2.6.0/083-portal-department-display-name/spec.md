# Feature: 门户部门简称统一展示

**Feature ID**: F083-portal-department-display-name

**状态**: ✅ 已实现，自动化验证完成（人工 E2E 待执行）

**优先级**: P0

**所属版本**: v2.6.0

**模式**: spec-then-implement

**创建日期**: 2026-08-10

**关联 Feature**: F082-department-short-name、F025-approval-center-unification、F060-department-multiple-spaces、F064-portal-watermarked-pdf-download、F065-qa-expert-schema-sync

---

## 0. 阅读摘要

本特性把首钢门户范围内所有动态部门展示统一为“优先简称、无简称回退部门原名”。简称只影响展示、展示排序和面向用户的搜索；部门正式名称、部门 ID、权限关系、组织同步和历史快照继续保持原契约。

统一规则为：

```text
display_name = trim(short_name) if trim(short_name) 非空 else name
```

后端响应保留现有 `name` / `department_name` 正式名称字段，并增量提供 `short_name` / `display_name` 或对应的标量字段。前端只消费展示字段，不自行改变权限、绑定或审批语义。部门路径的每一级都独立应用同一回退规则。

本特性覆盖独立首钢门户、其嵌入的 BiSheng Client 知识门户、知识空间成员管理、专家问答与专家管理、门户后台部门绑定、审批中心、用户信息及预览/PDF 水印。首页积分榜当前只有无部门 ID 的硬编码演示数据，本期不改；Platform 组织架构页面及非门户业务链路不在范围内。

本特性不取得 `Department.short_name` 的写入所有权，不新增数据库字段或迁移；F082 必须先发布并完成数据库迁移。

---

## 1. 背景与检索结论

### 1.1 当前问题

- F082 已允许管理员维护 `Department.short_name`，但原规格明确不改变组织树、搜索和 Client 展示。
- 门户的部门信息来自多个后端聚合链路，字段形态不一致：部门对象使用 `name`，用户/知识库使用 `department_name`，专家使用 `depart_ment`，成员管理还保存部门路径数组。
- 独立门户的“门户知识库”页面通过 iframe 嵌入 BiSheng Client，不能只修改独立门户仓库。
- 审批记录同时包含实时部门关联和历史名称快照；若直接覆盖旧字段，会破坏审计语义与旧客户端兼容性。
- 预览水印和服务端 PDF 水印分别在前后端生成，必须使用同一展示规则。

### 1.2 已检索的用户可见链路

| 场景 | 当前主要落点 | 当前部门来源 | 本期处理 |
|------|--------------|--------------|----------|
| 门户首页积分榜 | `shougang-group-knowledge-portal/frontend/src/pages/HomePage.tsx` | 硬编码 `dept` 文本，无部门 ID | 排除，等待真实接口 |
| 门户知识库 | `KnowledgeSpacesPage.tsx` → BiSheng Client iframe | BiSheng knowledge / permission API | 纳入 |
| 知识空间创建、详情与来源部门 | Client `CreateKnowledgeSpaceDrawer.tsx`、`PortalInfoDrawer.tsx` | `department_name`、部门选项 | 纳入 |
| 成员管理 | Client `KnowledgeSpaceShareDialog.tsx`、`PermissionListTab.tsx`、`SubjectSearchDepartment.tsx` | 部门树、成员部门路径 | 纳入 |
| 审批中心 | Client `ApprovalCenterDialog.tsx` | 实时申请人部门与历史快照 | 纳入 |
| 专家问答与专家管理 | 独立门户 `ExpertQAPage.tsx`、`ExpertQADetailPage.tsx`、`ExpertManagePage.tsx`、`ExpertInvitePicker.tsx` | qa_expert API | 纳入 |
| 门户后台部门绑定 | 独立门户 `AdminPage.tsx`、`adminConfig.ts`、`deptKnowledgeBinding.ts` | 部门知识库 API/BFF | 纳入 |
| 用户信息与水印 | 独立门户 `auth.ts`、`previewWatermark.ts`；Client `KnowledgePreviewWatermark.tsx`；后端 `portal_pdf_download_service.py` | 用户主部门 | 纳入 |

### 1.3 后端关键投影点

- `user/domain/services/user.py` 与 `user_repository_impl.py`：用户主部门名称。
- `knowledge_space_service.py` 与 `department_knowledge_space_service.py`：部门选项、树、路径、知识空间绑定、来源部门和默认空间名称。
- `resource_permission.py` 与 `grant_subject_user_service.py`：成员管理部门树、成员部门路径。
- `approval_center_service.py` 与 `department_file_view_approval_service.py`：实时部门投影和历史审批快照。
- `qa_expert/domain/services.py`：专家列表、详情和部门筛选项。
- `portal_pdf_download_service.py`：服务端 PDF 水印部门文案。

### 1.4 已确认决策

| ID | 决策 |
|----|------|
| D-001 | “部门展示”统一使用简称，简称缺失或空白时回退正式名称。 |
| D-002 | 搜索同时匹配正式名称和简称；列表按展示名称排序。 |
| D-003 | 部门路径每一级分别应用回退规则，不把整条路径当成一个简称。 |
| D-004 | 现有 `name` / `department_name` 字段继续表达正式名称；新增展示字段，避免破坏旧调用方。 |
| D-005 | 历史知识空间名称和历史审批名称快照不批量改写。 |
| D-006 | 审批展示优先按有效部门 ID 读取当前展示名称；无法解析时回退已保存的历史名称。 |
| D-007 | 新自动创建的部门知识空间使用当时的部门展示名称生成默认名称；以后简称变化不自动重命名空间。 |
| D-008 | 首页积分榜硬编码部门文本本期不改，待接入包含部门 ID 的真实数据接口后再纳入。 |

---

## 2. 范围

### 2.1 包含

- 建立后端统一、可复用的部门展示名称派生函数。
- 增量扩展门户相关 API 的部门对象、标量名称和部门路径响应字段。
- 部门选择器、树、列表、卡片、详情、成员行、水印等动态界面使用展示名称。
- 部门搜索同时匹配正式名称和简称，展示列表按展示名称稳定排序。
- 知识空间成员管理中的部门节点和成员部门路径使用简称回退展示。
- 审批中心保留快照原值，同时提供实时展示名称和失效部门回退。
- 新建部门知识空间的默认名称使用创建时展示名称。
- 独立门户 BFF 透传/映射新增字段，前端兼容后端分阶段发布。
- 为后端、BiSheng Client、独立门户 BFF/前端补充定向回归和最小集成验证。

### 2.2 不包含

- 不修改 F082 的字段、迁移、录入、清空、同步保护和写权限。
- 不修改 Platform `src/frontend/platform/` 的组织树、部门设置、成员页或搜索行为。
- 不修改首页积分榜硬编码的 `dept` 文本，不为其虚构部门映射。
- 不修改组织同步、LDAP、SSO、Gateway、飞书、企微、钉钉等正式名称事实源。
- 不修改 Filelib 同步匹配、外部部门编码、遥测字段、worker 中间表或报表事实字段。
- 不批量重命名历史知识空间，不回填或覆盖历史审批快照。
- 不用简称替代部门 ID，不改变权限判断、多租户隔离、审批状态、知识空间绑定或成员关系。
- 不要求简称唯一；重复简称通过完整路径、正式名称和稳定 ID 区分。
- 不新增数据库表、字段、迁移、依赖、端点或错误码。

---

## 3. 术语与统一契约

### 3.1 名称语义

| 字段 | 语义 | 是否兼容保留 |
|------|------|--------------|
| `name` / `department_name` / 既有 `depart_ment` | 部门正式名称 | 是，不改语义 |
| `short_name` / `department_short_name` | 部门简称，可空 | 新增透传 |
| `display_name` / `department_display_name` | `short_name` 非空时取简称，否则取正式名称 | 新增，门户默认展示 |
| `department_paths` | 既有正式名称路径 | 是，不改语义 |
| `department_display_paths` | 逐级应用回退规则后的展示路径 | 新增，门户默认展示 |

模块已有字段前缀不强制改名，按以下映射增量扩展：

| 场景 | 既有正式字段 | 新增展示字段 |
|------|--------------|--------------|
| 用户、知识空间、通用部门标量 | `department_name` | `department_short_name`、`department_display_name` |
| Permission 成员路径 | `subject_department_paths` | `subject_department_display_paths` |
| Approval 申请人列表 | `applicant_department_name` | `applicant_department_display_name` |
| Approval 部门文件快照 | `department_name` | `department_display_name` |
| QA Expert | `depart_ment` | `department_short_name`、`department_display_name` |

### 3.2 规范化规则

- 后端派生时对 `short_name` 执行 `strip()`；空字符串或纯空白视为无简称。
- 正式名称沿用现有数据，不在本特性中裁剪、修正或写回。
- 若异常数据的正式名称也不可用，沿用当前场景的空值/占位策略；不得使用部门 ID 伪装成名称。
- 前端优先级为 `display_name` → `short_name` → `name`，仅用于兼容分阶段发布；新后端必须返回与统一派生函数一致的 `display_name`。

### 3.3 搜索与排序规则

- 有服务端关键字过滤的部门接口同时匹配正式名称和简称。
- 已加载到前端的部门树/列表，本地搜索同时匹配 `name`、`short_name` 和 `display_name`。
- 沿用当前大小写和模糊匹配方式，不引入分词或拼音搜索。
- 用户可见部门列表按 `display_name` 排序；展示名称相同时依次按正式名称、部门 ID 稳定排序。
- 过滤和排序只影响选项呈现，不改变提交的部门 ID。

---

## 4. 需求 Requirements

### REQ-001：统一展示名称派生

系统必须在后端部门领域提供唯一的展示名称派生规则，所有本期后端投影复用该规则，禁止各业务模块自行形成不同的空值和回退逻辑。

### REQ-002：兼容的 API 展示契约

门户相关 API 必须保留现有正式名称字段，并增量返回简称和展示名称；部门路径必须同时保留正式路径和展示路径。

### REQ-003：部门选项、树、搜索与排序

门户知识库、成员管理、专家管理和门户后台中的部门选项/树必须展示简称回退名称，搜索正式名称与简称，并按展示名称稳定排序。

### REQ-004：知识门户与成员管理展示

BiSheng Client 的知识空间创建、来源部门、门户知识工作台和成员管理必须使用展示名称；知识空间与权限提交仍只使用稳定 ID。

### REQ-005：专家与门户后台展示

独立门户的专家问答、专家详情、专家邀请、专家管理及部门知识库绑定必须使用展示名称，并保留既有筛选和绑定行为。

### REQ-006：用户部门与水印一致性

用户信息、浏览器预览水印、Client 预览水印和服务端 PDF 下载水印必须使用同一个主部门展示名称；无简称时行为与当前正式名称一致。

### REQ-007：审批实时展示与历史兼容

审批中心必须优先展示当前有效部门的展示名称；部门已删除、跨租户不可见或无法解析时，回退审批记录中已保存的正式名称快照。历史快照不得被批量改写。

### REQ-008：知识空间名称历史兼容

新自动创建的部门知识空间默认名称必须使用创建时的展示名称；已有空间名称和简称变更前创建的名称保持不变，不做自动重命名。

### REQ-009：权限、多租户与正式名称不变

所有改动必须保持部门 ID、正式名称、权限关系、多租户过滤、组织同步和审批事实源不变；简称不得参与身份、授权或同步匹配。

### REQ-010：分阶段发布兼容

后端、BiSheng Client 与独立门户必须支持后端先行的分阶段发布；旧客户端忽略新增字段，新客户端在暂时缺少新增字段时回退正式名称，不得出现空部门文案。

---

## 5. 验收标准 Acceptance Criteria

| ID | 验收标准 |
|----|----------|
| AC-01 | 对 `short_name="  研发  "` 的部门，统一派生结果为“研发”；`short_name=null`、空字符串或纯空白时结果为正式名称。 |
| AC-02 | 同一部门经过 user、knowledge、permission、approval、qa_expert 五类后端投影时，各模块对应的展示名称字段结果一致。 |
| AC-03 | 增强后的部门对象保留 `name` 并返回 `short_name`、`display_name`；标量响应保留 `department_name` 并返回 `department_short_name`、`department_display_name`。 |
| AC-04 | 成员的 `subject_department_paths` 正式路径保持不变；新增 `subject_department_display_paths` 的每一级独立使用简称回退规则。 |
| AC-05 | 部门搜索输入正式名称或简称都能命中同一部门；只匹配其他字段的无关文本不能命中。 |
| AC-06 | 部门选项按展示名称排序，展示名称相同时按正式名称和部门 ID 得到确定顺序。 |
| AC-07 | Client 创建知识空间、部门选择器和来源部门信息展示简称；提交 payload 仍为原部门 ID。 |
| AC-08 | Client 成员管理部门树、授权选择和成员列表路径展示简称；授权结果、角色和可见范围不变。 |
| AC-09 | 独立门户专家问答、详情、邀请与管理列表/筛选项展示简称；专家筛选仍按部门 ID 生效。 |
| AC-10 | 独立门户后台部门知识库绑定列表、选择器、树和确认文案展示简称；绑定读写仍使用部门 ID。 |
| AC-11 | 用户主部门有简称时，独立门户预览水印、Client 预览水印和服务端 PDF 水印均显示简称；无简称时均显示正式名称。 |
| AC-12 | 审批申请关联的部门仍有效时展示当前简称；简称后续变化在下一次数据刷新后可见，但历史 `department_name` 快照值不变。 |
| AC-13 | 审批部门无法解析时展示历史 `department_name` 快照，不显示空值且不跨租户查询。 |
| AC-14 | 新建部门知识空间在部门简称为“研发”时生成“研发的知识空间”；已有空间及简称变化后不自动重命名。 |
| AC-15 | 没有简称的历史部门在所有纳入场景中继续展示原名，原 API 字段和权限结果与改动前兼容。 |
| AC-16 | 两个部门简称相同时均可展示；树路径和提交 ID 可正确区分，不增加唯一性校验。 |
| AC-17 | 新 Client/门户连接未增强的后端时回退现有正式名称；旧 Client/门户连接增强后端时不受新增字段影响。 |
| AC-18 | 首页积分榜硬编码部门文本、Platform 组织架构、组织同步、Filelib 匹配、遥测和中间表无生产代码改动。 |
| AC-19 | 门户知识库、知识文件和文件夹的“新增授权 → 用户”组织树优先显示 `display_name`，缺失时按 `short_name → name` 回退；授权提交的用户 ID 和权限关系不变。 |

---

## 6. 架构与设计

### 6.1 总体数据流

```text
Department(name, short_name)
  → DepartmentDisplayService 统一派生
  → user / knowledge / permission / approval / qa_expert 响应投影
  → BiSheng Client 或独立门户 BFF
  → 前端 display_name 优先、正式名称兜底
  → 页面、选择器、路径和水印
```

### 6.2 后端共享能力

建议新增：

`src/backend/bisheng/department/domain/services/department_display_service.py`

提供纯函数/无状态能力：

- `get_department_display_name(name, short_name) -> str`
- `build_department_name_projection(department) -> DepartmentNameProjection`
- 批量场景先一次查询所需部门，再构造正式名、简称和展示名映射，禁止逐行查询。

共享能力只读取部门字段，不写 Department，不访问权限事实，不建立缓存或第二事实源。业务 Service 负责在现有租户作用域内取得 Department，再调用派生能力。

### 6.3 API 扩展模式

#### 部门对象

```json
{
  "id": 18,
  "name": "技术研发中心",
  "short_name": "研发",
  "display_name": "研发"
}
```

#### 标量部门字段

```json
{
  "department_id": 18,
  "department_name": "技术研发中心",
  "department_short_name": "研发",
  "department_display_name": "研发"
}
```

#### 部门路径

```json
{
  "subject_department_paths": ["首钢集团", "技术研发中心"],
  "subject_department_display_paths": ["首钢", "研发"]
}
```

具体 DTO 可按模块既有命名增量扩展，但不得把现有正式名称字段改成展示名称。专家 API 的历史字段 `depart_ment` 继续表达正式名称，同时新增明确的 `department_display_name`。

### 6.4 模块设计

| 模块 | 设计要求 |
|------|----------|
| User | 主部门查询同时取得正式名称和简称；`/user/info` 增量返回展示字段。 |
| Knowledge | 部门选项、树、路径、绑定列表、来源元数据返回展示字段；关键字匹配正式名和简称；新默认空间名使用展示名。 |
| Permission | 授权部门树返回展示字段；成员聚合保留正式路径并增加展示路径；不得改变 ReBAC/RBAC 关系。 |
| Approval | 写入历史快照时继续保存正式名称；查询时按租户内有效部门 ID 批量解析当前展示名，失败回退快照。 |
| QA Expert | 部门筛选项和专家投影返回正式/简称/展示字段；部门排序使用展示名稳定排序。 |
| PDF | 服务端 PDF 水印通过主部门展示投影取值，与 `/user/info` 规则一致。 |

### 6.5 前端设计

- Client 与独立门户各自提供轻量读取函数，例如 `getDepartmentDisplayName`，只做响应兼容优先级，不复制后端业务推导。
- 组件渲染使用 `display_name`；搜索索引同时包含正式名称、简称和展示名称。
- 通用部门路径优先 `department_display_paths`，Permission 成员路径优先 `subject_department_display_paths`；缺失时分别回退对应的正式路径。
- 选择器的 value、请求 payload、React key 继续使用部门 ID。
- 独立门户 BFF 显式保留新增字段；不得把 BFF 的 `department_name` 改写为简称。

### 6.6 历史数据策略

#### 审批

- 创建审批时继续把正式名称写入既有 `department_name` 快照。
- 查询列表和详情时，若快照同时具有有效 `department_id`，在当前租户范围内批量解析最新展示名称。
- 无 ID、部门失效或不可见时，`department_display_name = snapshot.department_name`。
- 禁止回写审批快照；简称变化只影响后续查询结果。

#### 知识空间名称

- 只在自动创建空间的瞬间用展示名称拼接默认名称。
- 既有 `Knowledge.name` 不回填；简称新增、修改或清空都不触发空间重命名。
- 用户手工命名的空间不受影响。

### 6.7 性能与租户边界

- 列表、树、成员和审批场景必须批量加载部门字段，禁止产生 N+1 查询。
- 所有部门解析复用当前请求已有的租户作用域；不得通过无租户的全局 ID 查询补齐展示名。
- 前端不额外逐部门请求详情。
- 不新增长期缓存；简称变更在用户下一次刷新相关接口或重新获取用户信息后生效。

### 6.8 发布与回退

发布顺序：

1. 先完成 F082 migration 和后端部署，确认 `short_name` 可读。
2. 部署 F083 BiSheng 后端 API 扩展。
3. 部署 BiSheng Client。
4. 部署独立门户 BFF 与前端。

回退时可先回退两个前端，再回退 F083 后端；新增响应字段对旧客户端是可忽略的。不得在仍运行 F083 后端时回退/删除 F082 数据库列。F083 本身无数据迁移和不可逆写入。

---

## 7. 验证策略

| Verification ID | 层级 | 目标 | 最低证据 |
|-----------------|------|------|----------|
| V-UNIT-01 | V1 | 统一派生、空白回退、重复简称和稳定排序 | 后端参数化单元测试 |
| V-BE-USER-01 | V2 | 用户信息与 PDF 水印一致 | user / portal PDF 定向测试 |
| V-BE-KNOWLEDGE-01 | V2 | 知识部门选项、树、绑定、来源、搜索和默认名称 | knowledge 定向测试 |
| V-BE-PERM-01 | V2 | 成员部门树与正式/展示路径并存 | permission 定向测试 |
| V-BE-APPROVAL-01 | V2 | 实时展示、快照保留、失效回退、租户隔离 | approval 定向测试 |
| V-BE-EXPERT-01 | V2 | 专家字段、筛选项和展示排序 | qa_expert 定向测试 |
| V-CLIENT-01 | V2 | 知识门户、成员管理、审批和预览水印 | Client Vitest 定向测试 |
| V-PORTAL-01 | V2 | BFF 字段透传、专家/后台/水印展示 | portal pytest、Node test、build/typecheck |
| V-E2E-01 | V3 | 有简称与无简称两条门户主路径 | 真实 HTTP/浏览器最小 E2E；环境不可用时明确 `MANUAL_REQUIRED` |
| V-SCOPE-01 | V0 | 排除模块无改动、兼容字段未被替换 | diff/代码搜索/契约审查 |

验证按独立风险分组，不为每个页面重复同一回退用例。后端共享规则以单元测试为主，各 API 只验证字段映射；前端测试重点验证展示、搜索、路径和 ID 提交未变。

---

## 8. 需求追踪矩阵

| Requirement | Acceptance Criteria | Verification |
|-------------|---------------------|--------------|
| REQ-001 | AC-01, AC-02 | V-UNIT-01 及各后端模块测试 |
| REQ-002 | AC-03, AC-04 | V-BE-KNOWLEDGE-01, V-BE-PERM-01, V-BE-EXPERT-01 |
| REQ-003 | AC-05, AC-06, AC-16 | V-UNIT-01, V-BE-KNOWLEDGE-01, V-BE-PERM-01, V-BE-EXPERT-01, V-CLIENT-01, V-PORTAL-01 |
| REQ-004 | AC-07, AC-08 | V-BE-KNOWLEDGE-01, V-BE-PERM-01, V-CLIENT-01 |
| REQ-005 | AC-09, AC-10 | V-BE-EXPERT-01, V-BE-KNOWLEDGE-01, V-PORTAL-01 |
| REQ-006 | AC-11, AC-15 | V-BE-USER-01, V-CLIENT-01, V-PORTAL-01, V-E2E-01 |
| REQ-007 | AC-12, AC-13 | V-BE-APPROVAL-01, V-CLIENT-01 |
| REQ-008 | AC-14 | V-BE-KNOWLEDGE-01 |
| REQ-009 | AC-15, AC-16, AC-18 | V-SCOPE-01 及相关后端回归 |
| REQ-010 | AC-17 | V-CLIENT-01, V-PORTAL-01 |

### 8.1 2026-08-11 授权用户组织树缺陷修订

- 当前错误行为：知识库、知识文件和文件夹新增授权时，“用户”页签的组织树展示部门正式名称；截图中的“北京首钢股份有限公司”未使用已有简称。
- 期望行为：组织节点遵循 `display_name → trimmed short_name → name`；无简称或旧后端响应继续展示正式名称。
- 影响范围：仅 BiSheng Client 的知识类资源授权用户组织树。知识空间、知识库、文件夹和知识文件共用同一组件与资源类型分支。
- 复现路径：打开任一知识类资源的权限管理，进入“新增授权 → 用户”，观察具有 `short_name` 的部门节点。
- 根因：后端授权部门树已经返回 `short_name` 和 `display_name`，但 `SubjectSearchUserTree` 渲染节点时仍直接读取 `node.name`；“部门”页签已使用兼容展示函数，不存在该遗漏。
- 修复策略：复用现有 `resolveDepartmentDisplayName`，仅替换用户组织树节点的可见文本和 `title`，不修改加载、筛选、展开、用户选择或授权 payload。
- 回归策略：在 `SubjectSearchUserTree.test.tsx` 使用同时包含正式名和简称的部门 fixture，断言显示简称、不显示正式名，并保留现有知识类资源共用入口测试。
- 回退方式：回退该组件和对应测试、规格记录即可；无 API、数据或权限状态变更。

---

## 9. 风险与重新评审触发条件

| 风险/触发条件 | 处理 |
|---------------|------|
| F082 migration 未在目标环境完成 | 阻止 F083 后端发布；不得用捕获 SQL 异常的方式静默降级。 |
| 实施中发现门户还有未登记的动态部门展示 | 先补充本规格影响清单和任务；若属于已确认门户范围且契约相同，可继续，跨到 Platform/同步/报表则重新评审。 |
| 需要改变现有 `name` / `department_name` 语义 | 停止实施并重新评审 API 兼容策略。 |
| 需要回写审批快照或批量重命名知识空间 | 属于数据迁移和历史语义变化，必须另立规格并单独确认。 |
| 简称被要求参与权限、同步匹配、唯一性或业务标识 | 超出 F083，必须重新评审 F082/F083 及 release contract。 |
| 首页积分榜接入包含部门 ID 的真实接口 | 另补任务或后续 Feature，不能继续维护硬编码简称。 |

---

## 10. 规格状态

- [x] 完成跨仓库代码检索与需求澄清。
- [x] 生成 `spec.md`。
- [x] 生成 `tasks.md`。
- [ ] 用户评审并确认规格。
- [ ] 进入实现。
- [ ] 完成自动化验证与人工环境门禁。
