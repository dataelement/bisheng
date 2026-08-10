# Spec Discovery — F079 标签管理控制台

**状态**: ✅ 已确认（★ SDD 暂停点 1 已通过，2026-08-07）
**目标页面**: `/standalone/knowledge-tag-library`（F078 新增的独立可嵌入页面）
**需求来源**: 客户手绘原型（Excel），2026-08-07
**所属版本**: v2.6.0

---

## 0. 一句话目标

把现在「工作台 → 知识空间 → 标签库管理」那一段（列表 + 查看标签弹窗），
在**独立页面**上重做成左右布局：左边标签库树/列表，右边标签明细表，
并补齐审核、批量操作、相似标签处理能力。

**工作台配置页里的旧组件完全不动。**

---

## 1. 现状盘点

### 1.1 现有数据模型

| 表 | 含义 | 关键字段 |
|----|------|---------|
| `knowledge_space_tag_library` | 标签库 | id, name, description, is_builtin |
| `tag` | **已入库**标签 | name, business_type(`tag_library`), business_id(=库id), resource_type, user_id(创建者), create_time |
| `tag_link` | 标签 ↔ 知识文件 | tag_id, resource_id(文件id), resource_type |
| `review_tag` | **待审核**标签 | name, business_type, business_id, user_id(提报者), resource_type, review_status(0待审/1通过/2驳回), reject_reason, review_time, create_time |
| `review_tag_link` | 待审核标签 ↔ 知识文件 | tag_id, resource_id |
| `knowledge_tag_library_link` | 标签库 ↔ 知识空间 | tag_library_id, knowledge_id |

审核通过时：`review_tag` → `tag`、`review_tag_link` → `tag_link`（`approve_tag_to_move`）。

### 1.2 原型各列 / 各功能的可行性

| 原型元素 | 现状 | 结论 |
|---------|------|------|
| 标签库列表（搜索/新增/改/删） | `GET /knowledge/space/tag-libraries` 已有 | ✅ 复用 |
| 标签库多选、悬停显示已关联知识空间 | `bound_space_names` 已返回 | ✅ 纯前端 |
| 标签名称 | `tag.name` | ✅ |
| 标签库名（标签属于哪个库） | `tag.business_id` | ✅ |
| 已标识知识数 | `tag_link` 计数 | ✅ |
| 标签来源库 | **= 现有「标签来源」列**（系统标签/人工标签/AI标签），`resource_type`。用户已确认沿用现有逻辑 | ✅ 无需新字段 |
| 标签来源知识 | `tag_link` → 知识文件；待审核走 `review_tag_link` | ✅ 可派生 |
| 提报者 | `tag.user_id` / `review_tag.user_id`，接口未返回用户名 | ⚠️ 接口补字段 |
| 创建日期 | `create_time` | ✅ |
| 审核时间 | `review_tag.review_time`，但**通过后搬到 `tag` 表时丢失** | ⚠️ `tag` 表加列 |
| **审核者** | **两张表都没有记录谁审的** | ❌ 两张表都要加列 |
| 已启用 / 待审核 同表展示 + 统一分页 | 两套接口两套数据，前端拼不出统一分页 | ❌ 需新接口 |
| 跨多个标签库分页查标签 | 只能"查单个库的全部标签"，不分页 | ❌ 需新接口 |
| 批量删除 / 入库 / 驳回 / 移动 | 全是单条接口 | ❌ 需新接口 |
| 处理相似标签 | 底层相似匹配已有（服务于 AI 打标），缺管理端合并去重动作 | 🚫 本期不做（D7） |

---

## 2. 待确认决策

### D1 — 新旧组件关系

新页面**新建**一套组件（`pages/BuildPage/bench/standalone/tagConsole/`），
工作台 tab 内的 `KnowledgeSpaceTagLibrarySection.tsx` 一行不改，两套并存。

> **建议**：确认。共用组件会把旧页面拖下水，违背"原配置页不动"。
> 代价：标签库增删改的表单逻辑会有一份重复。

---

### D2 — 筛选项去重

原型右侧同时有「标签类型」和「标签来源库」两个筛选/列，
按 D 用户确认，两者都是同一个字段 `resource_type`。

> **建议**：合并成一个，叫「标签来源」（系统标签 / 人工标签 / AI标签）。
> 原型说明第 4 条"用图标区分标签类型"也按这个字段画图标。

---

### D3 — 「标签状态」有几档

`review_status`：0 待审核 / 1 已通过 / 2 已驳回。

> **建议**：筛选四档 = 全部 / 已启用 / 待审核 / 已驳回。
> 「已驳回」保留在列表里可见（带驳回原因 tooltip），否则驳回后直接消失、无法复查。
> 状态用颜色区分（原型说明第 3 条）。

---

### D4 — 审核者字段怎么加

两张表都没有 reviewer。

> **建议**：
> - `review_tag` 加 `reviewer_id`（int, nullable）
> - `tag` 加 `reviewer_id`(int, nullable) + `review_time`(datetime, nullable)
> - 审核通过搬运时一并写入
> - 存量数据为空，前端显示 `-`
>
> 走 Alembic 迁移，遵守 MySQL + DM8 双库规则。

---

### D5 — 「批量移动」移到哪

> **建议**：移动到另一个标签库（选中多条 → 选目标库 → 确认）。
> 冲突处理：目标库已存在同名标签则跳过并在结果里列出。

---

### D6 — 「批量入库」怎么给参数

现有单条审核通过强制要求 `tag_library_id` + `knowledge_id`。

> **建议**：批量时弹窗统一选**一个**目标标签库；`knowledge_id` 用每条标签自己的来源知识（后端逐条解析）。
> 部分失败时返回失败清单，不整批回滚。

---

### D7 — 「处理相似标签」

**更正**（spec 评审发现）：底层相似度能力**已经存在**，不是"完全没有"。
`TagLibraryTagService.find_similar_tag_name` / `find_similar_tenant_pending_review_tag_sync`
提供 L1 精确 + L2 子串 + L3 ratio 三级匹配，服务于 AI 打标（Link B）时复用已有待审核标签，
设计见 `docs/architecture/13-knowledge-space-link-b-tag-similarity-matching.md`。

缺的是**管理端动作**：把重复/近似标签挑出来给管理员合并、去重、批量归一。

> **已确认**（用户在知悉上述更正后重申）：本期不做，工具栏不出这个按钮。
> 连带：审核详情面板中的「推荐标签」栏也一并不做（它是相似度能力的界面入口）。

---

### D8 — 原型说明第 5 条是否本期做

> "点击知识文件高亮显示标签，并提供审核入库按钮，且支持上下切换"

这要接文件预览器 + 在正文里定位并高亮标签命中位置 + 上一条/下一条切换。
是这次需求里最重的一块，且和 PDF/Word 预览链路强耦合。

> **已确认**：本期不做，拆到二期。本期点击来源知识只做"跳转到文件预览"，不做高亮和上下切换。

---

### D9 — AI标签开关

原型右上角两个开关：标签库 / AI标签。

> **已确认**：AI库标签开关先不做。本期只保留现有的「标签库」开关（`auto_tag_visible`）。

---

### D10 — 分页方式与版本不变量 INV-6

release-contract v2.6.0 的 **INV-6** 规定：走 ReBAC 过滤的高频列表接口必须用 cursor 分页，
**不返 `total` / `page_num`**。

但原型明确要「首页 / 上一页 / **1/82** / 下一页 / 末页 / 共 **108**」——需要总数和总页数。

标签查询确实带空间可见性过滤（`resolve_reviewable_space_ids`）。

| 选项 | 说明 |
|------|------|
| A 传统 page/total 分页 + 在 spec 记豁免理由 | 满足原型。理由：标签管理是低频管理后台页面，非高频 ReBAC 列表；且可见空间集合先算好再作为 IN 条件，不需要逐行 ReBAC 判定 |
| B 改用 cursor 分页 | 符合 INV-6，但原型的页码和总数做不了，只能"上一页/下一页" |

> **已确认**：选 A，并在 spec.md §架构决策里显式记录豁免理由，评审时对照 INV-6 确认。

---

---

### D11 — 已入库与待审核如何组织（2026-08-07 产品补充确认）

原型右侧那张表同时画了「标签状态」筛选和「已启用 8 / 待审核 100」计数，
最初被理解为**一张合并表**，导致 spec 初版设计了 `tag` + `review_tag` 的 `UNION ALL` 统一分页。

产品澄清后的真实交互：

- 左栏**最上面**加一个固定入口「待审核标签」（不是标签库，是模式开关）
- 点它 → 右栏整体切换为「待审核标签」视图，内容等同工作台旧页面的 `KnowledgeSpaceReviewTagSection`
- 该视图里原来的「确认」「驳回」两个按钮合并为一个**「处理」**
- 点「处理」→ 弹出原型底部那个审核弹窗

> **已确认**：采用方案 C —
> 「标签管理」视图**只列已入库标签**，不出现待审核/已驳回条目；
> 但**保留「审核者」「审核时间」两列**，让管理员能追溯标签是谁批准进库的；
> 「标签状态」筛选与「已启用 N / 待审核 M」计数移到待审核视图，改为「待审核 / 已驳回」。
>
> **影响**：推翻 spec 初版的 AD-02。不再需要 `UNION ALL` 统一分页，
> 连带消除了"跨表排序键无法构成全序、翻页会漏行"的风险；后端工作量下降约三到四成。
> `tag.reviewer_id` / `tag.review_time` / `review_tag.reviewer_id` 三个字段仍然需要。

---

## 3. 本期明确不做

- 标签高亮定位与上下切换（D8）
- 处理相似标签（D7）
- AI标签开关（D9）
- 工作台配置页内旧组件的任何改动
- 标签库的层级/树形结构（现有 tree 接口只服务搜索联想，不改成真树）

---

## 4. 确认后的下一步

1. 用户确认本文档 ★
2. 写 `spec.md` → `/sdd-review 079-tag-management-console spec` → 用户确认 ★
3. 写 `tasks.md` → `/sdd-review 079-tag-management-console tasks`
4. 建分支 `feat/v2.6.0/079-tag-management-console`
5. 逐任务实现
