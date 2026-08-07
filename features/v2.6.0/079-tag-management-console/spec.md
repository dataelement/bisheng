# Feature: F079 标签管理控制台

> **前置步骤**：Spec Discovery 已完成并确认，见 [spec-discovery.md](./spec-discovery.md)。

**关联需求**: 无独立 PRD 文件；需求来源为客户手绘原型（Excel，2026-08-07 由用户在会话中提供），
以及 2026-08-07 产品对左右栏交互的补充确认。原型逐项拆解与可行性盘点见 [spec-discovery.md §1.2](./spec-discovery.md)。
**优先级**: P1
**所属版本**: v2.6.0
**版本契约**: [release-contract.md](../release-contract.md)

---

## 1. 概述与用户故事

作为 **平台管理员 / 部门管理员**，
我希望 **在一个独立页面上，左边选标签库或切到「待审核标签」，右边看对应的标签清单，并能筛选、批量处理**，
以便 **不用一个库一个库点开弹窗，就能把成千上万条 AI 生成标签管起来**。

**页面**：`/standalone/knowledge-tag-library`（F078 引入的无外壳可嵌入页面）。
**范围红线**：工作台「知识空间」Tab 内的 `KnowledgeSpaceTagLibrarySection.tsx`、
`KnowledgeSpaceReviewTagSection.tsx` 及其子组件**一行不改**。

### 页面骨架

```
┌───────────────────┬────────────────────────────────────────────────┐
│ [搜索标签库]   [+] │  右栏随左栏选择切换视图                          │
├───────────────────┤                                                │
│ ▸ 待审核标签 (100) │  ← 模式 B：待审核 / 已驳回标签，行内「处理」      │
├───────────────────┤                                                │
│   T1 工序 (4)      │  ← 模式 A：已入库标签，可多选标签库              │
│   T2 缺陷类型 (4)  │                                                │
│   T3 知识级别 (9)  │                                                │
└───────────────────┴────────────────────────────────────────────────┘
```

- **模式 A「标签管理」**（默认）：右栏列出**已入库**标签（`tag` 表）。左栏可多选标签库缩小范围，一个都不选 = 全部可见标签。
- **模式 B「待审核标签」**：点左栏顶部固定入口后进入，右栏列出**待审核 / 已驳回**标签（`review_tag` 表），行内操作为「处理」。

两个模式**数据源互斥**，各自独立分页，右栏工具栏按钮也随模式切换。

---

## 2. 验收标准

### 2.1 左栏

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 管理员 | 打开 `/standalone/knowledge-tag-library` | 页面为左右两栏，无平台侧边栏/顶栏；默认进入模式 A，左栏无标签库被选中 |
| AC-02 | 管理员 | 查看左栏顶部 | 固定项「待审核标签」显示当前可见范围内**待审核**标签数；该项与下方标签库列表视觉上分隔 |
| AC-03 | 管理员 | 单击左栏某个标签库 | 该库高亮选中，右栏进入模式 A 并只展示该库下的标签；若此前在模式 B，自动切回模式 A |
| AC-04 | 管理员 | 继续单击其他标签库 | 支持多选（再次单击取消选中）；右栏展示所选库标签的并集 |
| AC-05 | 管理员 | 左栏一个标签库都不选 | 右栏展示当前用户可见范围内的全部已入库标签 |
| AC-06 | 管理员 | 单击左栏顶部「待审核标签」 | 右栏切换到模式 B；标签库的选中状态全部清空 |
| AC-07 | 管理员 | 鼠标悬停在标签库名上 | 浮层显示该库已关联的知识空间名称列表；无关联时显示「暂无关联知识空间」 |
| AC-08 | 管理员 | 在左栏新增 / 编辑 / 删除标签库 | 沿用现有规则：名称必填且 ≤20 字符、同名冲突报错；库内有标签或已被知识空间绑定时删除被拒并提示原因 |
| AC-09 | 管理员 | 在左栏搜索框输入标签库名 | 左栏标签库列表按名称模糊过滤；「待审核标签」固定项不参与过滤，始终可见 |

### 2.2 右栏 — 模式 A（标签管理）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-10 | 管理员 | 查看表格 | 列依次为：选择框、序号、标签库名、标签名称、已标识知识数、提报者、审核者、标签来源、标签来源知识、创建日期、审核时间、操作。**表内全部为已入库标签，不出现待审核/已驳回条目**。「提报者」取 `tag.user_id`：AI/人工提报后审核入库的标签为原提报人（`approve_tag_to_move` 保留了 `review_tag.user_id`），管理员直接「添加」的标签为创建人 |
| AC-11 | 管理员 | 按「标签名」模糊搜索 | 只返回名称包含关键词的标签 |
| AC-12 | 管理员 | 按「标签来源」筛选（系统标签 / 人工标签 / AI标签） | 按 `resource_type` 过滤 |
| AC-13 | 管理员 | 按「提报者」「审核者」筛选 | 按用户过滤；审核者为空的记录在筛选审核者时不返回 |
| AC-14 | 管理员 | 按「创建日期」「审核日期」区间筛选 | 闭区间过滤；只填起始或只填截止时按单边过滤 |
| AC-15 | 管理员 | 点击「重置」 | 清空右栏所有筛选条件并回到第 1 页；左栏标签库选中状态不变 |
| AC-16 | 管理员 | 翻页 | 支持首页 / 上一页 / 下一页 / 末页、当前页/总页数、每页条数、总条数 |
| AC-17 | 管理员 | 查看标签名称 | 名称前按「标签来源」显示区分图标（系统 / 人工 / AI 各一种） |
| AC-18 | 管理员 | 点击「标签来源知识」中的文件名 | 在**新标签页**打开知识门户预览，URL 按现有 `buildReviewTagFileDetailUrl()` 规则携带 `spaceId` / `fileId` / `fileName` / `folderId`；缺少任一必要参数时该文件名降级为纯文本不可点 |
| AC-19 | 管理员 | 查看历史存量标签的「审核者」「审核时间」 | 迁移前的数据这两列为空，显示 `-`，不报错 |
| AC-20 | 管理员 | 点击工具栏「添加」 | 弹窗输入标签名并选择目标标签库，创建为「已启用」的系统标签；未选标签库时报错 |
| AC-21 | 管理员 | 「添加」时输入的标签名已存在于其他标签库 | 创建被拒，提示「标签「X」已存在于其他标签库」（复用 `_ensure_global_tag_names_available`） |
| AC-22 | 管理员 | 点击单行「删除」 | 二次确认后删除该标签及其与知识文件的关联 |
| AC-23 | 管理员 | 勾选多行后点「批量删除」 | 二次确认后逐条删除，返回成功数与失败清单 |
| AC-24 | 管理员 | 勾选多行后点「批量移动」 | 弹窗选择目标标签库后逐条移动；目标库已存在同名标签的条目跳过并计入失败清单 |

### 2.3 右栏 — 模式 B（待审核标签）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-25 | 管理员 | 查看表格 | 列依次为：选择框、序号、标签名称、标签来源、标签来源知识、提报者、审核者、驳回原因、创建日期、审核时间、操作。数据源为 `review_tag`，**一行 = 一个「标签名 + 标签来源」组合**（同名标签在多个知识空间产生的多条 `review_tag` 记录聚合为一行，来源知识列出全部文件），与工作台旧页面口径一致 |
| AC-41 | 管理员 | 对比模式 B 列表与工作台旧「待审核标签」区块 | 同一筛选条件下两处条目集合完全一致：都排除「名字已存在于正式标签库」的标签，都排除「没有有效关联文件」的孤儿标签 |
| AC-26 | 管理员 | 查看工具栏标题 | 显示「待审核标签（待审核 N / 已驳回 M）」；N/M 受除「状态」外的其他筛选条件影响，**不受「状态」筛选影响** |
| AC-27 | 管理员 | 按「状态」筛选（全部 / 待审核 / 已驳回） | 默认「待审核」。已驳回条目在此可复查，驳回原因整列可见 |
| AC-28 | 管理员 | 按标签名 / 标签来源 / 提报者 / 审核者 / 创建日期区间 / 审核日期区间筛选 | 同模式 A 的对应行为 |
| AC-29 | 管理员 | 点击某行「处理」 | 打开审核弹窗；原「确认」「驳回」两个按钮合并为这一个入口 |
| AC-30 | 管理员 | 查看审核弹窗 | 只读展示：标签名称、标签来源（系统/人工/AI）、标签创建者、所属标签库、标签来源知识（**全部**来源文件名，可点击外链打开预览） |
| AC-31 | 管理员 | 在审核弹窗点击「同意」 | 必须先选择目标标签库，未选时报错；通过后写入 `tag` + `tag_link`，记录 `reviewer_id` / `review_time`；弹窗关闭且列表刷新 |
| AC-32 | 管理员 | 在审核弹窗点击「驳回」 | 驳回原因**必填**，未填时报错；驳回后写入 `reject_reason` / `reviewer_id` / `review_time`，该条状态变为「已驳回」 |
| AC-33 | 管理员 | 对**已驳回**的条目 | **只读**：行内「处理」入口不可用，也不参与「批量入库」「批量驳回」；仅供在此复查驳回原因。改判需求延后到后续版本 |
| AC-34 | 管理员 | 勾选多行后点「批量入库」 | 弹窗选择目标标签库后逐条审核通过；每条使用其自身来源知识 |
| AC-35 | 管理员 | 勾选多行后点「批量驳回」 | 弹窗填写驳回原因（必填）后逐条驳回 |

### 2.4 通用

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-36 | 管理员 | 任一批量操作部分失败 | 不整批回滚；返回 `succeeded` / `skipped` 数量与 `failed` 明细（标签名 + 失败原因），前端以弹窗列出 |
| AC-37 | 管理员 | 任一写操作（增/删/移动/审核）成功后 | 后端失效当前租户的 Link B 标签目录缓存，使后续 AI 打标不再命中已删除/已移动/已审结的旧目录 |
| AC-38 | 部门管理员 | 打开页面 | 两个模式都只能看到其管理范围内知识空间产生的标签；范围外标签不出现在列表和计数中 |
| AC-39 | 无标签管理权限的用户 | 调用任一新接口 | 返回权限错误（沿用 `resolve_reviewable_space_ids` 的拒绝行为） |
| AC-40 | 管理员 | 打开「工作台 → 知识空间」Tab | 「标签库管理」与「待审核标签」两个区块的外观与行为与本次改造前完全一致（回归） |

---

## 3. 边界情况

- 左栏选中的标签库被其他人删除后再查询：后端忽略不存在的 `library_ids`，不报错；前端刷新左栏时自动去掉失效选中。
- 同名标签同时存在于 `tag`（已入库）和 `review_tag`（待审核）：模式 B 会按 `_library_tag_name_subquery`
  把该名字从待审核列表中排除（沿用现有口径），因此只在模式 A 出现，不会两边都看到。
- 批量操作中某条标签在执行前已被他人删除：计入 `failed`，原因为「标签不存在」。
- 「批量入库」时某条待审核标签没有来源知识（`review_tag_link` 为空）：计入 `failed`，原因为「缺少来源知识」。
- 一条待审核标签的来源知识**跨多个知识空间**：审核通过时按现有 `approve_or_reject_review_tag` 语义，
  取该标签在当前可见范围内的**第一个**知识空间作为 `knowledge_id`，其余来源文件的 link 一并搬运。
  审核弹窗（AC-30）必须列出全部来源文件，让审核人看到影响范围。
- 每页条数上限 200，超出按 200 处理；`page_size` ≤ 0 报参数错误。
- 单次批量操作的条目数上限 500，超出报参数错误。
- 左栏「待审核标签」的计数与模式 B 的 `pending_count` 使用同一口径，避免两处数字不一致。

**不支持（延后到后续版本）**：
- 原型说明第 5 条：标签在文件正文中的高亮定位、就地审核入库按钮、上一条/下一条切换
- 处理相似标签
- 审核弹窗中的「推荐标签」栏（其底层依赖相似标签能力，一并延后）
- 「AI标签」开关
- 标签库的层级树结构
- 已驳回标签改判为同意（AD-11）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 新接口放哪个模块 | A: knowledge / B: workstation | **B** | 待审核标签（`review_tag`）与可见空间范围解析 `resolve_reviewable_space_ids()` 都在 workstation；workstation 已单向依赖 knowledge 的 `KnowledgeSpaceTagLibraryService`，反向依赖会形成循环。 |
| AD-02 | 已入库与待审核如何组织 | A: 合并成一张表 UNION 统一分页 / B: 左栏切换的两个独立视图 | **B** | 产品确认交互为「左栏顶部『待审核标签』入口切换右栏视图」。两个数据源不再需要 `UNION ALL`，也就不存在跨表排序键无法构成全序导致翻页漏行的风险；后端工作量显著下降。**本条于 2026-08-07 推翻原 A 方案。** |
| AD-03 | 已入库标签是否展示审核留痕 | A: 展示审核者/审核时间 / B: 不展示 | **A** | 管理员需要能追溯"这个标签是谁批准进库的"。代价仅为 `tag` 表两个可空列，不引入 UNION。 |
| AD-04 | 分页方式 vs INV-6 | A: 传统 page/total / B: cursor | **A** | 见下方 AD-04 说明。 |
| AD-05 | 审核者字段落库位置 | A: 只加在 `review_tag` / B: 两张表都加 | **B** | 审核通过时记录从 `review_tag` 搬到 `tag`，只加在前者则已入库标签查不到审核者（AD-03 要求）。 |
| AD-06 | 新旧组件是否复用 | A: 抽公共组件 / B: 新页面独立实现 | **B** | 需求明确「原工作台配置页不动」（AC-40）；抽公共组件会把旧页面卷入回归风险。代价是标签库表单与来源文件外链逻辑各有一份重复，可接受。 |
| AD-07 | 「标签来源库」列语义 | A: 新增部门/来源库字段 / B: 沿用现有「标签来源」`resource_type` | **B** | 用户已确认沿用现有逻辑，不新增字段。 |
| AD-08 | 批量操作失败策略 | A: 整批事务回滚 / B: 逐条执行 + 失败清单 | **B** | 批量审核天然会遇到"部分标签已被他人处理"，整批回滚会让管理员反复重试整批。 |
| AD-09 | 模式 B 的数据接口 | A: 复用现有 `list_review` / B: 新建接口 | **B** | 现有 `list_review` 只支持 `keyword` + 分页，不支持状态（已驳回）、提报者、审核者、日期区间筛选。新建接口以免改动旧接口影响工作台旧页面（AC-40）；但**必须照抄它的分组口径与两个隐含过滤条件**（见 §7）。 |
| AD-10 | 模式 B 的行标识 | A: `review_tag.id` / B: `(name, resource_type)` | **B** | 同名标签在多个知识空间会产生多条 `review_tag` 记录；现有 `get_review_tag_group_list_by_page` 按 `(name, resource_type)` 分组，`approve_or_reject_review_tag` 也按此一次处理该组合下全部记录。用 id 键会让列表出现同名重复行，或让审核实际影响范围超出用户勾选。 |
| AD-11 | 已驳回条目能否改判为同意 | A: 支持改判 / B: 只读 | **B** | 现有 `get_review_tag_list_by_tag_name` 硬过滤 `review_status == 0`，已驳回取不到会抛 `ReviewTagNotFoundError`。放开需改这个方法，而工作台旧页面走同一条路径，与 AC-40 回归要求冲突。本期已驳回仅供复查驳回原因，改判延后。 |

### AD-04 说明：INV-6 豁免理由

版本不变量 **INV-6** 要求「走 ReBAC 过滤的高频列表接口采用 cursor 分页，不返 `total` / `page_num`」。
本特性的两个列表接口申请豁免，理由：

1. **不是 ReBAC 逐行过滤**。可见范围由 `resolve_reviewable_space_ids()` **一次性**算出空间 ID 集合，
   再作为 SQL `IN` 条件下推；不存在"取一批 → 逐行判权 → 不够再取"的循环，也就没有 INV-6 要防的全表扫描问题。
2. **不是高频列表**。标签管理是低频后台运维页面，非终端用户高频访问路径。
3. **产品要求页码与总数**（AC-16），cursor 分页无法满足。

**豁免范围（写死，不可扩大解释）**：仅限 `/api/v1/workstation/tags/console/search`
与 `/api/v1/workstation/tags/console/review/search` 两个端点。
本特性不得以此为由让任何**走逐行 ReBAC 判定**的列表接口回退到 page/total 分页；
后续若这两个接口演化为需要逐行判权（例如按单个知识文件的查看权过滤标签），本豁免自动失效，
必须回到 INV-6 的 cursor 契约。

本豁免已在 release-contract.md 变更历史中登记，评审通过即生效。

---

## 5. 数据库 & Domain 模型

### 数据库变更

沿用现有 `tag` / `review_tag` 表，只加列，无新表。
Alembic 版本：`v2_6_0_f079_tag_review_audit_fields.py`，`down_revision` 取生成时的实际 head（当前为 `f078_knowledge_parse_priority`）。

| 表 | 新增列 | 类型 | 说明 |
|----|-------|------|------|
| `review_tag` | `reviewer_id` | `Integer`, nullable | 审核人用户 ID；同意与驳回都写入 |
| `tag` | `reviewer_id` | `Integer`, nullable | 审核通过搬运时从 `review_tag` 带过来 |
| `tag` | `review_time` | `DateTime`, nullable | 同上 |

**双库兼容**：三列均为可空标量列，不涉及 JSON / LONGTEXT / `ON UPDATE`，MySQL 与 DM8 语法一致。
存量数据为 `NULL`，前端显示 `-`（AC-19）。

### Domain Schema（新建 `workstation/domain/schemas/tag_console_schema.py`）

```python
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TagConsoleReviewStatus(str, Enum):
    PENDING = "pending"
    REJECTED = "rejected"


class TagConsoleSourceFile(BaseModel):
    file_id: int
    file_name: str
    knowledge_id: int
    parent_id: int | None = None


class TagConsoleFilter(BaseModel):
    """模式 A / 模式 B 共用的筛选条件。"""
    tag_name: str | None = None
    resource_type: str | None = None
    submitter_id: int | None = None
    reviewer_id: int | None = None
    create_time_start: datetime | None = None
    create_time_end: datetime | None = None
    review_time_start: datetime | None = None
    review_time_end: datetime | None = None
    page: int = 1
    page_size: int = 20


class TagConsoleSearchReq(TagConsoleFilter):
    """模式 A：已入库标签。"""
    library_ids: list[int] = Field(default_factory=list)  # 空 = 全部可见


class TagConsoleItem(BaseModel):
    """模式 A 的行。"""
    id: int
    name: str
    resource_type: str
    library_id: int | None = None
    library_name: str | None = None
    marked_knowledge_count: int = 0
    submitter_id: int | None = None
    submitter_name: str | None = None
    reviewer_id: int | None = None
    reviewer_name: str | None = None
    source_files: list[TagConsoleSourceFile] = Field(default_factory=list)
    create_time: datetime | None = None
    review_time: datetime | None = None


class TagConsoleSearchResp(BaseModel):
    data: list[TagConsoleItem]
    total: int


class TagConsoleReviewSearchReq(TagConsoleFilter):
    """模式 B：待审核 / 已驳回标签。"""
    status: TagConsoleReviewStatus | None = None  # 空 = 全部


class TagConsoleReviewRef(BaseModel):
    """模式 B 的行标识。

    待审核标签的身份是 ``(name, resource_type)`` 而**不是** ``review_tag.id``：
    同一个标签名在多个知识空间产生时会有多条 ``review_tag`` 记录，现有
    ``get_review_tag_group_list_by_page`` 按 ``GROUP BY name, resource_type`` 聚合，
    ``approve_or_reject_review_tag`` 也按 ``tag_name + resource_type`` 一次处理该名下全部记录。
    新接口沿用同一身份口径，避免列表出现同名重复行、或审核影响范围超出用户勾选。
    """
    name: str
    resource_type: str


class TagConsoleReviewItem(TagConsoleReviewRef):
    """模式 B 的行（一行 = 一个 name + resource_type 组合）。"""
    status: TagConsoleReviewStatus
    review_tag_count: int = 0   # 该组合下聚合了多少条 review_tag 记录
    library_id: int | None = None
    library_name: str | None = None
    submitter_id: int | None = None
    submitter_name: str | None = None
    reviewer_id: int | None = None
    reviewer_name: str | None = None
    source_files: list[TagConsoleSourceFile] = Field(default_factory=list)
    create_time: datetime | None = None
    review_time: datetime | None = None
    reject_reason: str | None = None


class TagConsoleReviewSearchResp(BaseModel):
    data: list[TagConsoleReviewItem]
    total: int
    pending_count: int    # AC-26，不受 status 筛选影响
    rejected_count: int   # AC-26，同上


class TagConsoleBatchResult(BaseModel):
    succeeded: int
    skipped: int
    failed: list[dict]   # [{"name": str, "reason": str}]


class TagConsoleBatchDeleteReq(BaseModel):
    """模式 A 批量删除：已入库标签按 tag.id 键（同表主键唯一，可直接用）。"""
    ids: list[int]


class TagConsoleBatchMoveReq(BaseModel):
    ids: list[int]
    target_library_id: int


class TagConsoleBatchApproveReq(BaseModel):
    """模式 B 批量入库：按 (name, resource_type) 键，见 TagConsoleReviewRef。"""
    items: list[TagConsoleReviewRef]
    target_library_id: int


class TagConsoleBatchRejectReq(BaseModel):
    items: list[TagConsoleReviewRef]
    reject_reason: str
```

---

## 6. API 契约

> 认证：`UserPayload = Depends(UserPayload.get_login_user)`
> 响应包装：`UnifiedResponseModel[T]`
> 前缀：`/api/v1/workstation/tags/console`

| Method | Path | 描述 | 关联 AC |
|--------|------|------|---------|
| POST | `/search` | 模式 A：已入库标签分页查询 | AC-10 ~ AC-19 |
| POST | `/create` | 添加标签到指定标签库 | AC-20, AC-21 |
| POST | `/batch-delete` | 批量删除已入库标签 | AC-22, AC-23 |
| POST | `/batch-move` | 批量移动到其他标签库 | AC-24 |
| POST | `/review/search` | 模式 B：待审核 / 已驳回标签分页查询 + 两个计数 | AC-25 ~ AC-28 |
| POST | `/review/detail` | 审核弹窗的单条只读上下文（入参为 `TagConsoleReviewRef`） | AC-29, AC-30 |
| POST | `/review/batch-approve` | 批量入库（单条「同意」复用此端点，items 长度为 1） | AC-31, AC-34 |
| POST | `/review/batch-reject` | 批量驳回（单条「驳回」复用此端点，items 长度为 1） | AC-32, AC-35 |
| GET | `/review/pending-count` | 左栏「待审核标签」入口的角标计数 | AC-02 |

### 请求示例

```json
POST /api/v1/workstation/tags/console/search
{
  "library_ids": [5, 8],
  "tag_name": "结垢",
  "resource_type": "ai_auto_tag",
  "create_time_start": "2026-08-01T00:00:00",
  "page": 1,
  "page_size": 20
}
```

```json
POST /api/v1/workstation/tags/console/review/batch-approve
{
  "items": [
    {"name": "结垢", "resource_type": "ai_auto_tag"},
    {"name": "表面裂纹", "resource_type": "ai_auto_tag"}
  ],
  "target_library_id": 5
}
```

### 成功响应

```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [
      {
        "name": "结垢", "resource_type": "ai_auto_tag", "status": "pending", "review_tag_count": 3,
        "library_id": 5, "library_name": "缺陷类型",
        "submitter_id": 7, "submitter_name": "AI",
        "reviewer_id": null, "reviewer_name": null,
        "source_files": [{"file_id": 88, "file_name": "热轧水处理…", "knowledge_id": 12, "parent_id": 3}],
        "create_time": "2026-08-05T10:00:00",
        "review_time": null, "reject_reason": null
      }
    ],
    "total": 100,
    "pending_count": 100,
    "rejected_count": 8
  }
}
```

### 错误码表

> 本特性的端点与 Service 位于 **workstation 模块**（AD-01），新增错误码取
> **模块编码 120**（`12000–12099`，见 `docs/architecture/02-backend-modules.md`），
> 写入 `common/errcode/workstation.py`。该文件现已用到 `12045`，本特性顺延 `12046–12049`。
> 复用的标签库错误仍由 knowledge 模块的 Service 抛出，保持 109 段不变。

| HTTP | Code | Error Class | 场景 | 关联 AC |
|------|------|-------------|------|---------|
| 200 (body) | 10989 | `KnowledgeSpaceTagLibraryInvalidError` | 目标标签库未选 / 名称非法 / 标签名已存在于其他标签库（复用现有） | AC-08, AC-20, AC-21 |
| 200 (body) | 10988 | `KnowledgeSpaceTagLibraryNotExistError` | 目标标签库不存在（复用现有） | AC-24, AC-31, AC-34 |
| 200 (body) | 12046 | `TagConsoleBatchTooLargeError` | 单次批量条目 > 500 | §3 边界 |
| 200 (body) | 12047 | `TagConsolePageParamsError` | `page` / `page_size` 非法 | §3 边界 |
| 200 (body) | 12048 | `TagConsoleActionNotApplicableError` | 对已驳回条目调用 `/review/batch-approve` 或 `/review/batch-reject`（AD-11 已驳回只读） | AC-33 |
| 200 (body) | 12049 | `TagConsoleRejectReasonRequiredError` | 驳回未填原因（单条与批量共用） | AC-32, AC-35 |

---

## 7. Service 层逻辑

新建 `workstation/domain/services/tag_console_service.py`。

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `search` | `TagConsoleSearchReq` | `TagConsoleSearchResp` | 模式 A：解析可见空间 → 过滤 `tag` → 分页 → 批量补齐库名/用户名/来源知识/已标识知识数 |
| `create_tag` | name + library_id | `TagConsoleItem` | 校验重名（全局唯一）→ 写 `tag` |
| `batch_delete` | `list[int]`（tag.id） | `TagConsoleBatchResult` | 删除 `tag` 及其 `tag_link` |
| `batch_move` | ids + target_library_id | `TagConsoleBatchResult` | 改写 `tag.business_id`（**必须走 `TagLibraryTagService._business_id(library_id)` 编码，不是裸 id**，见 `_resolve_approved_tag_business_id`）；目标库同名则跳过 |
| `review_search` | `TagConsoleReviewSearchReq` | `TagConsoleReviewSearchResp` | 模式 B：按 `GROUP BY name, resource_type` 聚合 `review_tag` → 分页 → 补齐 + 两个计数 |
| `review_detail` | `TagConsoleReviewRef` | `TagConsoleReviewItem` | 审核弹窗只读上下文，含该 (name, resource_type) 下**全部**来源文件 |
| `batch_approve` | `list[TagConsoleReviewRef]` + target_library_id | `TagConsoleBatchResult` | 逐项复用 `WorkstationTagsService.approve_or_reject_review_tag`（APPROVE），`knowledge_id` 取该标签自身来源知识；写入 `reviewer_id` |
| `batch_reject` | `list[TagConsoleReviewRef]` + reject_reason | `TagConsoleBatchResult` | 逐项复用同一入口（REJECT），写入 `reviewer_id` / `review_time` |
| `pending_count` | — | int | 左栏角标 |

### 查询实现要点

- **可见范围**：`resolve_reviewable_space_ids()` 返回 `None` 表示全租户；返回 `set` 时作为 `IN` 条件下推到 link 查询。
- **单表分页**：两个模式各查一张表，`ORDER BY create_time DESC, id DESC` 即为全序（同表内 `id` 唯一），
  直接 `LIMIT/OFFSET`。**不再需要 `UNION ALL` 与跨表排序键**（AD-02）。
- **批量补齐**：「已标识知识数」「来源知识」「库名」「用户名」在拿到当页 ID 后批量查询，禁止 N+1。
- **模式 B 必须照抄现有的两个隐含过滤**（AC-41），否则本页列表与工作台旧页面条目对不上：
  1. `ReviewTag.name.not_in(_library_tag_name_subquery(tenant_id))` — 排除名字已存在于正式标签库的待审核标签
  2. `_active_review_tag_link_exists(tenant_id)` — 排除没有有效 `review_tag_link` 的孤儿标签

  两者定义见 `workstation/domain/repositories/review_tags_repository.py:374-388`。
  左栏角标（`pending-count`）也必须走同一套条件。
- **模式 B 的行标识**：`GROUP BY name, resource_type`，一行代表该组合下的全部 `review_tag` 记录（见 `TagConsoleReviewRef` 文档串）。
  排序用 `ORDER BY MAX(create_time) DESC, name ASC, resource_type ASC` 构成全序。
- **模式 B 计数**：`total` 使用全部筛选条件；`pending_count` / `rejected_count` 使用**剔除 `status` 后**的同一套筛选条件分别 `COUNT(DISTINCT name, resource_type)`（AC-26）。
- **左栏角标**：`pending-count` 与模式 B 的 `pending_count` 走同一个查询函数，保证口径一致（§3 边界）。
- **双库兼容**：不使用 `JSON_EXTRACT` / `information_schema` / 方言专有分页语法。

### 缓存一致性（AC-37）

现有 `WorkstationTagsService.approve_or_reject_review_tag` 在 approve / reject 成功后都会调用
`TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_async(tenant_id)`
（`workstation_tags_service.py:180, 193`），用于让 Link B 的 AI 打标不再命中过期的标签目录。

**本特性所有写操作都必须遵守同一约定**：`create_tag`、`batch_delete`、`batch_move`、
`batch_approve`、`batch_reject` 在提交事务后各失效一次租户目录缓存（批量场景合并为一次调用，
不要每条调一次）。遗漏会导致 AI 继续把新文件挂到已删除或已移走的标签上。

### 权限检查

标签属于租户级配置资源，不走 OpenFGA 资源元组，沿用 workstation 现有的
`resolve_reviewable_space_ids()` 判定链（全局超管 / RBAC admin / 子租户管理员 / 部门管理员范围 / 拒绝）。
该方法通过 `DepartmentDao` + `DepartmentKnowledgeSpaceDao` 解析范围，**不查 `role_access`**，
符合架构守卫 RULE-8。本特性不新增 OpenFGA 资源类型，因此不调用 `PermissionService.authorize()`。

---

## 8. 前端设计

> 路径：`src/frontend/platform/src/`
> 页面路由：`/standalone/knowledge-tag-library`（F078 已建）

**组件树**（全部新建，不复用工作台旧组件 — AD-06）：

```
pages/BuildPage/bench/standalone/
├── KnowledgeTagLibraryPage.tsx        # 改造：换成左右布局容器 + 模式状态
└── tagConsole/
    ├── TagLibraryPanel.tsx            # 左栏：待审核入口 + 搜索 + 新增 + 库列表多选 + 悬停关联空间
    ├── TagLibraryFormDialog.tsx       # 左栏：新增·编辑标签库弹窗
    ├── TagTablePanel.tsx              # 右栏模式 A：筛选栏 + 工具栏 + 表格 + 分页
    ├── ReviewTablePanel.tsx           # 右栏模式 B：同上，行内「处理」
    ├── TagFilterBar.tsx               # 两个模式共用的筛选栏（模式 B 多一个状态项）
    ├── TagReviewDialog.tsx            # 「处理」弹窗：只读上下文 + 选择标签库 + 驳回原因 + 同意/驳回
    ├── TagBatchDialogs.tsx            # 批量移动/入库/驳回 + 结果清单弹窗
    ├── AddTagDialog.tsx               # 工具栏「添加」
    ├── buildTagFileDetailUrl.ts       # 来源文件外链，与旧 Section 同规则（AC-18）
    └── tagConsoleTypes.ts             # 本地类型与状态·来源的展示映射
```

**模式状态**：页面顶层维护 `mode: 'library' | 'review'` 与 `selectedLibraryIds: number[]`。
选中任一标签库 → `mode='library'`；点「待审核标签」→ `mode='review'` 且清空选中（AC-03 / AC-06）。

**状态管理**：页面内 `useState` + `useTagConsoleQuery` / `useReviewConsoleQuery` 两个自定义 hook。
不引入 Zustand store（单页局部状态，跨页无共享需求）。

**API 调用**：`src/controllers/API/knowledgeSpaceTagLibrary.ts` 追加 9 个 console 函数。

**来源文件外链**（AC-18）：沿用 `KnowledgeSpaceReviewTagSection.tsx` 中
`buildReviewTagFileDetailUrl()` 的既有规则 —
`getWorkspaceClientUrl('/knowledge-portal?spaceId=..&fileId=..&fileName=..&folderId=..')`，`target="_blank"`。
新标签页打开同时保证本页被 iframe 嵌入门户时，预览不会挤在 iframe 内。
按 AD-06 不改旧文件，在新目录下按同规则实现一份。

**图标与颜色**：
- 标签来源图标：系统标签 / 人工标签 / AI标签 各一个 `lucide-react` 图标（AC-17）
- 模式 B 状态颜色：待审核=橙、已驳回=红；已驳回行的驳回原因整列可见（AC-27）

**i18n**：键前缀 `build.tagConsole.*`，写入 `public/locales/{zh-Hans,en-US,ja}/bs.json`。

**布局**：左栏固定宽 `280px` 可折叠，右栏 `flex-1` 并允许横向滚动（12 列表格）。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/core/database/alembic/versions/v2_6_0_f079_tag_review_audit_fields.py` | 三列迁移 |
| `src/backend/bisheng/workstation/domain/schemas/tag_console_schema.py` | 请求/响应 Schema |
| `src/backend/bisheng/workstation/domain/repositories/tag_console_repository.py` | 两个模式的查询与批量补齐 |
| `src/backend/bisheng/workstation/domain/services/tag_console_service.py` | 业务逻辑 |
| `src/backend/bisheng/workstation/api/endpoints/tag_console.py` | 9 个端点 |
| `src/backend/test/workstation/test_review_tag_audit_fields.py` | 审核留痕字段写入测试 |
| `src/backend/test/workstation/test_tag_console_search.py` | 模式 A 查询与筛选测试 |
| `src/backend/test/workstation/test_tag_console_review_search.py` | 模式 B 查询、分组、计数测试 |
| `src/backend/test/workstation/test_tag_console_write.py` | 模式 A 写操作（添加/删除/移动）测试 |
| `src/backend/test/workstation/test_tag_console_review_action.py` | 审核（同意/驳回/批量）测试 |
| `src/backend/test/workstation/test_tag_console_api.py` | 9 个端点集成测试 |
| `src/frontend/platform/src/test/tagConsoleLogic.test.ts` | 前端纯逻辑单测 |
| `src/frontend/platform/src/pages/BuildPage/bench/standalone/tagConsole/*` | 见 §8 组件树 |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/database/models/tag.py` | `Tag` 加 `reviewer_id` / `review_time` |
| `src/backend/bisheng/database/models/review_tags.py` | `ReviewTag` 加 `reviewer_id` |
| `src/backend/bisheng/workstation/domain/repositories/tags_repository.py` | `approve_tag_to_move()`（L17-39）搬运时补写 `tag.reviewer_id` / `tag.review_time`；现在只复制 name/business_id/user_id/tenant_id/resource_type/create_time/update_time |
| `src/backend/bisheng/workstation/domain/repositories/review_tags_repository.py` | `approve_review_tag()` / `reject_review_tag()` 写入 `review_tag.reviewer_id` |
| `src/backend/bisheng/workstation/domain/services/workstation_tags_service.py` | 把当前登录用户作为审核人传给上面两个 repository 方法 |
| `src/backend/bisheng/workstation/api/router.py` | 注册 `tag_console` 路由 |
| `src/backend/bisheng/common/errcode/workstation.py` | 新增 4 个错误码（12046–12049） |
| `src/frontend/platform/src/pages/BuildPage/bench/standalone/KnowledgeTagLibraryPage.tsx` | 换成左右布局容器 + 模式状态 |
| `src/frontend/platform/src/controllers/API/knowledgeSpaceTagLibrary.ts` | 追加 console 接口 |
| `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json` | 新增 i18n 键 |

### 明确不动

- `src/frontend/platform/src/pages/BuildPage/bench/KnowledgeSpaceTagLibrarySection.tsx`（AC-40）
- `src/frontend/platform/src/pages/BuildPage/bench/KnowledgeSpaceReviewTagSection.tsx`（AC-40）
- `src/frontend/platform/src/pages/BuildPage/bench/KnowledgeSpace.tsx`
- 现有 `/api/v1/workstation/tags/list_review` 等旧接口（工作台旧页面仍在用）

---

## 10. 非功能要求

- **性能**：两个 `search` 在 10 万条标签、50 个标签库规模下 P95 < 800ms；
  当页明细的补齐查询必须批量化（库名、用户名、来源知识、已标识知识数各一次查询），禁止 N+1。
- **安全**：可见范围由 `resolve_reviewable_space_ids()` 强制，租户隔离由现有 SQLAlchemy 事件自动注入。
- **兼容性**：三列均可空且默认 `NULL`；工作台旧页面继续使用原有接口，行为不变（AC-40）。
- **双库**：MySQL + DM8 双方言均须通过；迁移与查询不得使用方言专有语法。

---

## 相关文档

- Spec Discovery: [spec-discovery.md](./spec-discovery.md)
- 版本契约: [../release-contract.md](../release-contract.md)（INV-6 豁免见 AD-04）
- F078 独立页面路由: `src/frontend/platform/src/routes/standalone.ts`
- Link B 标签相似匹配（本期不做，但需保持缓存一致）: `docs/architecture/13-knowledge-space-link-b-tag-similarity-matching.md`
