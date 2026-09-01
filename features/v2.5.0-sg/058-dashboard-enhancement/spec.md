# Feature: F058 数据看板筛选与统计口径增强

> **前置步骤**：Spec Discovery 已完成并确认，见 [spec-discovery.md](./spec-discovery.md)。

**关联需求**: 无独立 PRD 文件；需求来源为用户在会话中口头提出的 8 项看板改进点，逐项讨论、澄清边界并确认，
详见 [spec-discovery.md](./spec-discovery.md)。
**优先级**: P1
**所属版本**: v2.5.0-sg
**版本契约**: [release-contract.md](../release-contract.md)

---

## 0. 范围界定

### IN

- 组织架构（公司/部门/科室/班组）筛选选项改为直接查 `Department` 全量表，不再依据数据集内是否有数据反查。
- 组织架构筛选下拉支持"全选"；所有带公司/部门/科室/班组的下拉，选项统一排序为该四级顺序。
- 部门名称统一显示"组织简称"（下拉框 + 表格/图表内容），匹配不到降级显示全称。
- 修复横向朝向图表（含非分组横向条形图）数值标签位置，统一显示在条形末端。
- 知识空间内容统计数据集补齐"原始上传库"四级维度（`uploader_company/office/squad_name`，`uploader_
  department_name` 已存在）。
- 用户相关数据集精简：下线"用户反馈统计"；"用户规模统计/活跃用户规模统计/全员每日参与度"在看板 UI 层
  合并为一个入口，去掉"活跃用户"独立概念。
- 图表钻取导出（点击某维度分类导出明细）与整图导出（多 sheet）。
- 人名类维度（所属XX、上传人、原始上传库）展示时同行带出所属部门。
- 交叉表按筛选中实际选中值的最细组织层级分组，渲染分组 + 子表格（子表格展示下一级明细）。

### OUT

- 不做组织架构筛选的树形 UI，保持平铺多选、各级独立不级联。
- 不为没有数据的组织单元在结果集中补 0 值行。
- 不新建统一用户数据 ES 索引/同步链路；三个用户数据源合并**只做 UI 层**，底层查询仍是三个独立数据源。
- 用户数据集部门维度不升级四级，维持现状单级"主部门"。
- 不修复部门名称历史快照字段（`belonging_department_name` 等）因改名/重名/删除导致的简称匹配失配问题——
  匹配不到时降级展示全称原文，不做额外消歧。
- 不改造 ES 聚合响应契约（`parse_to_2d_array` 仍返回平铺多维行），分组+子表格在前端基于既有平铺行重建。

### 兼容原则

- `dataset/field/enums` 接口签名不变；只有当 `field` 属于组织架构四级时内部数据源切换为 `Department`
  全量表，其余字段（知识库大类、知识分类、业务域等）保持现状 ES distinct 行为不变。
- 现有依赖平铺 2D 行数组格式的图表类型（非组织架构多级维度的图表）渲染逻辑不变。

---

## 1. 概述与用户故事

### US-01：管理员按真实组织架构筛选

作为 **平台管理员**，
我希望 **组织架构筛选下拉展示全量公司/部门/科室/班组（不管有没有数据）**，
以便 **确认某个部门确实没有数据，而不是误以为筛选组件漏选了它**。

### US-02：管理员看简称、不看长部门全名

作为 **平台管理员**，
我希望 **看板所有部门名称（下拉框、表格、图表）统一显示组织简称**，
以便 **在有限的图表/表格空间里快速识别部门，不被长全称挤占布局**。

### US-03：管理员按组织层级下钻查看交叉表

作为 **平台管理员**，
我希望 **交叉表按我筛选的最细组织层级自动分组、组内展开下一级子表格**，
以便 **不用自己在一堆平铺行里手动归并，就能看清"部门→科室"或"科室→班组"的层级关系**。

### US-04：管理员导出图表明细做进一步分析

作为 **平台管理员**，
我希望 **点击图表某一分类能导出该分类的明细 Excel，或者整图一次性导出多 sheet**，
以便 **拿着明细数据在 Excel 里做我在看板上做不到的二次分析**。

### US-05：管理员在重名场景下区分具体是谁

作为 **平台管理员**，
我希望 **"所属XX"/"上传人"/"原始上传库"这类人名字段，展示时同行带出部门**，
以便 **在不同部门有同名员工时，能准确区分数据对应的是谁**。

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 管理员 | 打开任一带组织架构筛选的图表配置面板 | 公司/部门/科室/班组下拉展示 `Department` 全量数据，包含当前数据集里没有任何数据的组织单元 |
| AC-02 | 管理员 | 点开组织架构筛选下拉 | 下拉顶部/内部提供"全选"选项，点击后勾选该级全部选项 |
| AC-03 | 管理员 | 打开任一带公司/部门/科室/班组维度的下拉 | 选项统一按"公司→部门→科室→班组"顺序排列（同级内部排序不受影响） |
| AC-04 | 管理员 | 查看筛选下拉框、图表、交叉表里的部门名称 | 已维护 `short_name` 的部门显示简称；未维护简称或匹配不到当前部门记录的，降级显示原文/全称，不报错、不显示为空 |
| AC-05 | 管理员 | 查看任意横向朝向的柱状图/条形图（含非分组的普通横向条形图） | 数值标签显示在条形末端，不再挤在条形中部 |
| AC-06 | 管理员 | 打开看板数据集/图表选择列表 | "用户反馈统计"数据集不再出现在可选列表中 |
| AC-07 | 管理员 | 打开"用户"相关看板分组入口 | 原"用户规模统计/活跃用户规模统计/全员每日参与度"三个入口合并为一个分组展示，共享同一套筛选组件；界面上不再出现"活跃用户"这个指标标签 |
| AC-08 | 管理员 | 打开知识空间内容统计的维度筛选/分组配置 | 除已有"所属公司/部门/科室/班组"，新增可选"原始上传库公司/科室/班组"（部门已存在），结构与"所属"四级对称 |
| AC-09 | 管理员 | 在柱状图/条形图上点击某一分类（维度值） | 触发导出，生成仅包含该分类明细数据的 Excel |
| AC-10 | 管理员 | 对整张图表执行"导出" | 生成多 sheet 的 Excel，每个 sheet 对应该图表最外层分组维度的一个取值 |
| AC-11 | 管理员 | 查看包含"所属XX"、"上传人"或"原始上传库"人名维度的表格/明细行 | 同一行同时展示人名与对应部门名称（简称） |
| AC-12 | 管理员 | 对多级组织维度的图表配置交叉表，筛选中给某一级组织（如部门）配置了具体选中值，下一级（科室）未配置具体值 | 交叉表按该级（部门）分组，组内渲染下一级（科室）子表格 |
| AC-13 | 管理员 | 同上，但筛选中最细已经配置到"班组"这一级具体值 | 不生成子表格，明细摊平展示（等同当前行为） |

---

## 3. 边界情况

- 部门 `short_name` 未维护或为空 → 展示全称，不留空白。
- 图表/表格内历史快照字段（如 `belonging_department_name`）按名称文本匹配当前 `Department.name` 取
  `short_name`；因部门改名/已删除/重名导致匹配不到或匹配歧义时 → 降级展示快照原文全称，不报错、不阻断渲染。
  **已知限制**：本期不解决快照字段的部门重名/改名消歧，见 spec-discovery §3。
- 组织架构筛选各级（公司/部门/科室/班组）不做父子一致性校验；用户选择了不构成同一分支的组合（如公司 A
  + 不属于 A 的部门 B），按各级独立取交集处理，结果为空是预期行为，不是 bug。
- 被选中但数据集里没有匹配数据的组织单元 → 该次查询结果为空/该组织单元不出现在结果行里，**不**补 0 值行。
- 交叉表分组：筛选中实际配置了具体值的组织层级只到"班组"（已是最细一级） → 不做分组+子表格，摊平明细展示
  （AC-13）。
- 筛选中若组织架构多级都未配置任何具体值（即不限定任何组织层级） → 不触发分组+子表格逻辑，维持当前
  无分组的平铺展示。
- 用户数据集 UI 层合并：三个底层数据源（`mid_user_increment` / `mid_active_user` /
  `mid_user_daily_participation_fact`）字段粒度不完全一致（均为单级"主部门"，无公司/科室/班组）；某张图表
  引用了某个筛选维度而其底层数据源没有该字段时，按现有"图表未声明该维度，该维度对它不生效"规则处理，不报错。
- **不支持**：组织架构筛选树形 UI（延后，如后续确有大量部门导致平铺列表不可用，再评估）。
- **不支持**：把三个用户数据源合并为单一 ES 索引/统一交叉表（延后，见 AD-04）。

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 组织架构筛选选项数据源 | A: 维持现状 ES distinct（数据集内已有值）／B: 改查 `Department` 全量表 | 选 B | 只有 B 能满足"没数据的组织单元也要展示"，A 在原理上做不到（ES `terms` 聚合只会返回索引里实际存在的桶） |
| AD-02 | 交叉表分组+子表格的实现层 | A: 后端改造 ES 响应解析，保留嵌套桶结构下发树形 response／B: 前端对既有平铺多维行做 client-side group-by | 选 B | ES 聚合层（`search_engine_service.py`）本就已产出嵌套桶，是 Python 解析层（`_traverse_buckets`）主动拍平成组合 key 的平铺行；平铺行本身同时带有父子两级维度值，前端按目标层级做一次 reduce/group-by 即可安全还原分组结构。A 需要改动响应契约，牵动所有现存依赖平铺 2D array 格式的图表类型，回归面明显更大 |
| AD-03 | 部门名称→简称的替换层 | A: 下拉框与图表/表格统一处理／B: 分别处理（下拉框走 `department_id` 精确关联，图表/表格走名称文本运行时匹配） | 选 B | 下拉框数据源已切换为 `Department` 全量表（AD-01），天然带 `department_id`，可精确取 `short_name`；图表/表格里的部门字段是历史快照文本，没有 FK，只能运行时按名称字符串匹配当前 `Department.name`，匹配不到时兜底展示原文全称。用户已确认接受这个已知的匹配风险 |
| AD-04 | 用户三数据集合并的实现方式 | A: 新建统一 ES 索引 + 同步任务／B: 保持三个独立数据源，仅在看板 UI 层合并为一个分组入口 | 选 B（用户已确认） | A 需要新增 ETL/同步链路，工作量和引入的新故障面明显更大；B 改动成本低，且天然复用各数据源现状的实时性。代价是做不成单一数据集意义上的统一交叉表——该代价已向用户说明并被接受 |
| AD-05 | 明细导出的技术实现 | A: 新引入流式下载/新导出库／B: 复用仓库既有 `pandas.to_excel()` → `BytesIO` → `save_uploaded_file` 上传 MinIO 返回 URL 的模式（`knowledge.py` QA 导出同款） | 选 B | 仓库已有成熟可复用模式，B 不引入新依赖、不新增维护成本 |

---

## 5. 数据库 & Domain 模型

本特性**不新增数据库表**。涉及的模型改动均为对现有模型的字段透出/配置扩展：

### 5.1 `DepartmentTreeNode`（`department/domain/schemas/department_schema.py`）

追加 `short_name: str | None` 字段，`DepartmentService.aget_tree`（`department/domain/services/
department_service.py:424`）构建节点时一并透出该部门记录已有的 `short_name`（字段本身已由 F082 迁移
建好，本特性只是在树节点响应里补上，不需要新迁移）。

> **归属提示**：`short_name` 列的迁移文件标注归属 F082（v2.6.0），但当前 v2.5.0 与 v2.5.0-sg 两份
> release-contract 的领域对象归属表均未登记该字段及其 Owner Feature（本地也没有 F082 的 feature 目录）。
> 字段本身已确实存在于代码库，本特性只读取、不改写该字段的写入行为，不构成对 F082 范围的越界；
> 实现前建议再确认一次 F082 的实际状态（已合并未登记 / 分支未同步），避免后续两边对同一字段的展示口径
> 产生分歧。

### 5.2 `DashboardDataset` / `DimensionConfig`（`telemetry_search/domain/init_dataset.py`）

- 知识空间内容统计（`mid_knowledge_space_content_stat`）新增三个 `DimensionConfig`：
  `uploader_company_name`（原始上传库所属公司）、`uploader_office_name`（原始上传库所属科室）、
  `uploader_squad_name`（原始上传库所属班组）。字段本身已在 ETL 模型
  （`telemetry/domain/mid_table/knowledge_space_content.py:65-70`）中存在，只是尚未注册为看板维度。
- "用户反馈统计"（`mid_user_interact_dtl` 对应数据集）下线看板可见性。**确定行为**：复用
  `DashboardDataset` 现有可见性/启用开关字段（如 `is_enabled`/`status`）；实现阶段先读该模型确认字段名，
  若确无可复用字段则新增一个布尔列（不算领域对象所有权变更，只是既有模型加一个展示开关字段）——无论
  哪种情况，AC-06（"用户反馈统计"不再出现在可选列表）都以此开关字段驱动，技术覆盖不因具体字段名未定而缺失。
- "用户规模统计/活跃用户规模统计/全员每日参与度"三个数据集在**看板配置层**新增一个"分组"归属标记，
  用于前端把三者渲染成一个入口下的多个子面板。**确定行为**：复用看板页面布局/组件配置的现有分组字段；
  实现阶段先确认是否已有 `dashboard_page`/`component` 级别的分组字段可复用，若无则新增——AC-07（三入口
  合并为一个分组展示）同样以此字段驱动，具体字段名待实现阶段确定不影响该 AC 的技术覆盖判断。

无需 Alembic 迁移（若 5.2 的开关/分组字段最终判定需要新列，按 §3.2 Dual-DB Compatibility 规则走迁移，
使用 `dialect_helpers` 保证 MySQL/DM8 双兼容）。

---

## 6. API 契约

### 端点列表

| 改动类型 | Method | Path | 描述 | 认证 |
|---------|--------|------|------|------|
| 修改 | GET | `/api/v1/department/tree` | 节点响应追加 `short_name` 字段 | 是 |
| 修改（内部实现） | GET | `.../dashboard/dataset/field/enums` | `field` 属于组织架构四级时，内部改为查 `Department` 全量表；签名/响应结构不变 | 是 |
| 新增 | POST | `.../dashboard/component/{component_id}/export` | 图表钻取导出：按点击的维度分类，导出对应明细 Excel | 是 |
| 新增 | POST | `.../dashboard/component/{component_id}/export-all` | 整图导出：按最外层分组维度值拆分为多 sheet 的 Excel | 是 |

> Path 前缀沿用 `telemetry_search/api/endpoints/dashboard.py` 现有路由挂载前缀，与既有
> `/component/query`、`/dataset/list`、`/dataset/field/enums` 一致。

### 请求/响应示例

**钻取导出请求**:
```json
POST .../dashboard/component/123/export
{
  "dimension_field": "belonging_department_name",
  "dimension_value": "生产部",
  "filters": { "...": "当前面板已生效的筛选条件，透传" }
}
```

**导出响应**（沿用仓库既有导出模式，返回 MinIO URL，非流式下载）:
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "file_url": "https://.../export/xxx.xlsx"
  }
}
```

### 错误码表

模块编码沿用已分配的 `170`（telemetry，见 v2.5.0 release-contract「已分配模块编码」），文件
`common/errcode/telemetry.py`。该文件当前已用到 `17015`，本特性顺号追加：

| HTTP Status | MMMEE Code | Error Class | 场景 | 关联 AC |
|-------------|------------|-------------|------|---------|
| 200 (body) | 17016 | DashboardExportEmptyError | 导出目标数据为空 | AC-09, AC-10 |
| 200 (body) | 17017 | DashboardExportLimitExceededError | 明细行数超出导出上限 | AC-09, AC-10 |

---

## 7. Service 层逻辑

### 核心方法

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `DashboardService.get_dataset_field_enums`（改造） | `index_name`, `field`, ... | 枚举值列表 | `field` 属于组织架构四级时，委托部门模块查询全量组织单元并映射 `{value, label}`；其余字段保持现状 ES `terms` 聚合不变 |
| `DepartmentService.aget_tree`（改造） | `login_user` | `DepartmentTreeNode[]` | 节点构建时追加 `short_name` |
| （新增）组织简称展示映射 | 部门名称文本 / `department_id` | 简称字符串 | 有 `department_id` 走精确查表；只有名称文本时按 `Department.name` 运行时匹配，匹配不到兜底原文 |
| （新增）`DashboardExportService.export_component_detail` | `component_id`, 维度/维度值, 当前筛选 | Excel 文件 URL | 复用 `DataQueryService` 查询明细行（非聚合），走 `pandas.to_excel` + `save_uploaded_file` 落 MinIO，返回 URL |
| （新增）`DashboardExportService.export_component_all` | `component_id`, 当前筛选 | 多 sheet Excel 文件 URL | 按最外层分组维度值分别查询，每个取值写一个 sheet |

### 权限检查

`dashboard` 是 v2.5.0 INV-15 明确列入的、有 OpenFGA type 的资源模块，变更操作前必须完成权限检查。
**已核实实际实现**：该模块目前不是直接调用 `PermissionService.check()`，而是在
`DashboardService.query_component_data`（`domain/services/dashboard.py:541-589`）里用
`login_user.async_access_check(dashboard.user_id, target_id=str(dashboard.id),
access_type=AccessType.DASHBOARD)` 结合 `dashboard.status`/`_is_department_admin()`/`_can_operate_
dashboards()` 等规则做访问判定，再校验 `component_id` 归属的 `dashboard_id` 是否一致——这是本模块对
INV-15 策略的具体落地方式。两个新增导出端点在查询明细前，必须复用与 `query_component_data`
（`dashboard.py:90-106` 路由 + 上述 service 方法）完全一致的这套访问判定 + 组件归属校验逻辑，不得绕开
直接调用 `DataQueryService`。组织架构全量树查询进一步复用 `DepartmentService.aget_tree` 已有的权限范围
收敛逻辑（超管看全量，部门管理员/租户管理员看有权范围），不额外放大可见组织范围。本特性不创建任何新的
OpenFGA 归属对象，因此不涉及 `PermissionService.authorize()`。

### 前端交叉表分组（不涉及后端契约变更，列在此处便于对照 AD-02）

新增一个纯前端工具函数，对 `DataQueryService` 返回的既有平铺多维行数组，按"筛选中实际选中值的最细组织
层级"对应的维度列做 `group by`，输出 `{ groupKey, groupLabel, childRows }[]` 结构，供表格组件渲染
分组 + 子表格；不修改任何后端接口响应结构。

---

## 8. 前端设计

### 8.1 Platform 前端（`src/frontend/platform/src/`）

**涉及页面**: `pages/Dashboard/`（已有页面，本特性均为增量修改，不新增路由）

**组件改动**:
```
pages/Dashboard/components/
├── charts/
│   ├── DimensionFilter.tsx      # 组织架构四级改为查 Department 全量接口；加"全选"；统一排序；简称展示
│   ├── BaseChart.tsx            # 横向图表 label.position 判断范围扩大到所有横向朝向类型
│   └── CrossTabTable.tsx (新增或在既有交叉表组件内扩展) # 分组 + 子表格渲染，消费前端 group-by 工具函数的输出
├── export/
│   └── useComponentExport.ts (新增 hook)  # 封装钻取导出 / 整图导出的调用与下载态
└── config/
    └── DatasetSelector.tsx      # "用户反馈统计"入口移除；三个用户数据集入口合并展示分组
```

**状态管理**: 沿用现有 Zustand dashboard store，新增导出中/导出结果的临时 UI 状态（本地组件状态即可，
无需进全局 store）。

**API 调用**: `controllers/API/dashboard.ts` 新增 `exportComponentDetail`、`exportComponentAll`；
`getFieldEnums` 调用方不变（组织架构四级的数据源切换发生在后端，前端调用签名不变）。

**i18n**: 沿用现有 `dashboard` 命名空间，新增键如 `dashboard.filter.select_all`、
`dashboard.export.detail`、`dashboard.export.all_sheets`、`dashboard.user_dataset.merged_title` 等。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/telemetry_search/domain/services/dashboard_export_service.py` | 钻取导出 + 整图导出服务 |
| `src/backend/bisheng/telemetry_search/api/endpoints/dashboard.py`（追加端点，非新文件） | `export` / `export-all` 端点 |
| `src/frontend/platform/src/pages/Dashboard/components/export/useComponentExport.ts` | 导出交互 hook |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/department/domain/schemas/department_schema.py` | `DepartmentTreeNode` 追加 `short_name` |
| `src/backend/bisheng/department/domain/services/department_service.py` | `aget_tree` 节点构建透出 `short_name` |
| `src/backend/bisheng/telemetry_search/domain/services/dashboard.py` | `get_dataset_field_enums` 组织架构四级分支改数据源 |
| `src/backend/bisheng/telemetry_search/domain/init_dataset.py` | 新增 3 个 `uploader_*` `DimensionConfig`；用户数据集下线/分组标记 |
| `src/frontend/platform/src/pages/Dashboard/components/charts/DimensionFilter.tsx` | 全量组织单元、全选、排序、简称展示 |
| `src/frontend/platform/src/pages/Dashboard/components/charts/BaseChart.tsx` | 横向图表 label 位置判断范围扩大 |
| `src/frontend/platform/src/pages/Dashboard/components/config/DatasetSelector.tsx` | 用户数据集入口合并、反馈统计下线 |
| `src/frontend/platform/src/controllers/API/dashboard.ts` | 新增导出相关 API 封装 |
| `public/locales/{zh-Hans,en,ja}/dashboard.json`（如该命名空间独立文件） | 新增文案 key |

---

## 10. 非功能要求

- **性能**: 组织架构全量查询走 `DepartmentService.aget_tree` 现有实现，不引入新的未缓存高频查询路径；
  导出接口的明细行数上限、是否分页/分批参考仓库现有 QA 导出（`knowledge.py:728-788`）的既有处理方式，
  本期不强制设定新的量级门槛。
- **安全**: 导出与组织架构全量查询均复用现有 `PermissionService` 检查链路和 `DepartmentService` 的权限
  范围收敛逻辑，不放大可见数据范围；导出产物落 MinIO 沿用现有对象存储权限模型，不新增公网直链。
- **兼容性**: 非组织架构维度的筛选行为、依赖平铺 2D 行数组格式的既有图表渲染逻辑均不变；`用户反馈统计`
  数据下线仅影响看板展示入口，不删除底层 ES 数据。

---

## 相关文档

- Spec Discovery: [spec-discovery.md](./spec-discovery.md)
- 版本契约: [features/v2.5.0-sg/release-contract.md](../release-contract.md)
