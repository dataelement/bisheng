# Spec Discovery — F058 数据看板筛选与统计口径增强

**状态**: ✅ 已确认（对话逐项确认，2026-08-31）
**目标模块**: 后台数据看板（`src/backend/bisheng/telemetry_search/`，前端 `src/frontend/platform/src/pages/Dashboard/`）
**需求来源**: 用户在会话中口头提出的 8 项看板改进需求，逐项讨论并确认
**所属版本**: v2.5.0-sg

---

## 0. 一句话目标

看板的组织架构筛选从"数据集里出现过什么就能选什么"改成"组织架构表里有什么就能选什么"；
把交叉表的多级组织维度渲染成分组+子表格；精简合并用户相关数据集；修一个图表标签位置的 bug；
知识空间内容统计补齐"原始上传库"四级维度；支持钻取明细导出。

---

## 1. 现状盘点

### 1.1 筛选组件

- 下拉选项来源：`GET /dataset/field/enums`（`telemetry_search/api/endpoints/dashboard.py:119-153` →
  `DashboardService.get_dataset_field_enums`，`domain/services/dashboard.py:607-772`）对 `dataset.es_index_name`
  做 ES `terms` 聚合，取该数据集索引里**实际出现过**的字段值。
- 结论：筛选选项不是按具体图表/交叉表绑定的（数据集级别独立于图表），但**是按数据集里已有数据反查**的——
  组织架构表里存在但数据集里没有数据的组织单元，不会出现在下拉框里。这是需要改的点，不是"解绑"问题。
- 前端渲染：`DimensionFilter.tsx`（`pages/Dashboard/components/charts/DimensionFilter.tsx:40-160`），平铺
  `MultiSelect`，非树形，各维度筛选相互独立、不级联，多选间取交集。
- `Department.short_name` 字段已存在（F082 迁移，`database/models/department.py:66-73`，`VARCHAR(64)` 可空），
  但组织全量树读取接口 `DepartmentService.aget_tree`（`department/domain/services/department_service.py:424`）
  返回的 `DepartmentTreeNode` **目前没有透出 `short_name`**。

### 1.2 用户相关数据集

现有三个独立 ES 索引，无字面对应"用户规模统计/活跃用户规模统计"的数据集名：

| 概念 | 实际数据集 | ES 索引 |
|------|-----------|---------|
| 用户规模统计 | 用户行为指标表 | `mid_user_increment` |
| 活跃用户规模统计 | 活跃用户表 | `mid_active_user` |
| 全员每日参与度 | 全员每日参与度（字面存在） | `mid_user_daily_participation_fact` |
| 用户反馈统计 | 用户反馈指标表 | `mid_user_interact_dtl` |

四个数据集部门维度都只有单级"主部门"（`primary_department_id/name`），没有公司/部门/科室/班组四级。

### 1.3 知识空间内容统计

`mid_knowledge_space_content_stat`（`telemetry_search/domain/init_dataset.py:738-968`）已有完整四级
"所属"维度（`belonging_company/department/office/squad_name`），ETL 模型（`telemetry/domain/mid_table/
knowledge_space_content.py:65-74`）里对称的 `uploader_company/department/office/squad_name` 字段**已经存在**，
但目前只有 `uploader_department_name`、`uploader_user_name` 两个注册成了看板可选维度
（`init_dataset.py:944, 956-958`），`uploader_company_name`/`uploader_office_name`/`uploader_squad_name`
三个字段还没注册为 `DimensionConfig`。

### 1.4 横向条形图数值标签

`BaseChart.tsx:472-483`：`position: chartType === ChartType.GroupedHorizontalBar ? 'right' : 'top'`——
只对"分组横向条形图"这一种类型特判为末端，普通横向条形图（非分组）落入默认 `'top'` 分支，方向不对，
数字挤在条形中部靠上。

### 1.5 交叉表多级聚合

ES 聚合层（`search_engine_service.py:368-461`）已支持真正的嵌套桶（parent bucket → child bucket），
但响应解析阶段 `_traverse_buckets`（`search_engine_service.py:182-246`）把嵌套桶递归拍平成
`[dim1, dim2, metric1, metric2]` 的平铺行，`DataQueryService.query_all_metrics`
（`component.py:127-160`）再按 `tuple(one_dimension)` 拼 key 合并多指标——最终返回给前端的是**平铺的多维行**，
不是父子分组结构。每一行本身同时带有部门值和科室值，只是没有按父级分组。

### 1.6 导出

`telemetry_search` 模块目前**没有任何导出接口**。仓库里已有的 Excel 导出模式（如
`knowledge/api/endpoints/knowledge.py:713-788` 的 QA 导出）是 `pandas.to_excel()` 写入内存
`BytesIO`，走 `save_uploaded_file` 上传到 MinIO，返回 URL，不是流式下载。

---

## 2. 逐项确认结论

### 2.1 筛选组件重构

- 组织架构筛选（公司/部门/科室/班组）改为直接查 `Department` 全量表，不管有无数据都展示；不做树形，
  保持平铺多选，各级独立、不级联、取交集。
- 下拉框增加"全选"。
- 所有带公司/部门/科室/班组的下拉选项，统一按"公司→部门→科室→班组"顺序排列。
- 没数据的组织单元被选中后，图表/交叉表结果维持现状——**不**反查全量组织表插 0 值行，只是查出来是空结果。
  理由：插 0 值需要"全量组织 × 已有维度组合"补全，多维度交叉会组合爆炸，成本明显更高；现状聚合本来就是
  "有数据才出现"，只换筛选下拉框的数据源，不改聚合输出逻辑，是成本最低的路径。
- 筛选维度整体范围：知识库大类、知识分类、组织架构、时间、业务域；图表未声明的维度对它不生效
  （复用现有 `schema_config.dimensions` / `allowed_fields` 机制）。

### 2.2 部门名称显示（组织简称）

- **决定**：统一用组织简称，匹配不到就降级显示全称；下拉框和表格/图表内容都要用简称。
- 下拉框：本身就是从 `Department` 表查全量（有 `department_id`），可以干净地换成简称，无匹配风险。
- 表格/图表内的"所属部门"等字段：ES 里存的是**当时的部门名称文本快照**（不是部门 ID 外键，部门改名/
  重名/删除都不会同步更新这些历史快照）。用户已确认接受这个风险——**运行时按名称文本匹配当前
  `Department.name` → `short_name`**，匹配不到（改名/已删除/重名歧义）就展示快照里的全称原文兜底。

### 2.3 横向条形图数值标签位置

把"横向"判断从"仅 `GroupedHorizontalBar`"扩大到所有横向朝向的图表类型，统一末端展示。纯前端 echarts
配置改动，不涉及数据逻辑。

### 2.4 知识空间内容统计新增"原始上传库"四级维度

补齐 `uploader_company_name` / `uploader_office_name` / `uploader_squad_name` 三个 `DimensionConfig`
注册（ETL 字段已存在，只是没注册成看板维度），与已有 `uploader_department_name` / `uploader_user_name`
凑齐对称的四级 + 姓名。

### 2.5 用户数据集精简合并

- 下线"用户反馈统计"（`mid_user_interact_dtl`）看板入口。
- "用户规模统计" + "活跃用户规模统计" + "全员每日参与度" 合并为一个看板分组/数据集入口。
- **实现方式（已确认）**：UI 层合并，后端仍是三个独立数据源——看板配置上把三个入口收成一个分组展示，
  共享同一套筛选组件，但底层分别查询三个现有 ES 索引拼接结果；不新建统一 ES 索引/同步链路。
  理由：改动成本低、复用现状各自的实时性（各自本来多实时就多实时），代价是做不成单一数据集意义上的
  统一交叉表/统一维度——这个代价已向用户说明并被接受。
- 去掉"活跃用户"这个独立概念（不再区分活跃/非活跃）。
- 部门维度**不**升级四级，维持现状单级"主部门"——本期不做。

### 2.6 图表钻取 + 导出

- 点击图表某一列（维度值）→ 导出该维度对应明细数据的 Excel。
- 整图导出 → 多 sheet（按最外层分组维度值拆分 sheet）。

### 2.7 人名类字段消歧

"所属XX"、"上传人"、"原始上传库"这几个维度展示人名时，同一行要带出其部门，避免同名混淆。
`uploader_user_name` 与 `uploader_department_name` 已经是同一条 ETL 记录里的独立字段
（`KnowledgeSpaceContentRecord.build_file_record`，`knowledge_space_content.py:947-995`），
不需要新的反规范化——只要图表/表格配置在选中"上传人姓名"类维度时，同时把对应部门维度并入同一行展示。

### 2.8 交叉表分组子表格

- 维度包含公司/部门/科室/班组多级时，交叉表按"用户在筛选里实际选了具体值的最细一级"分组，
  子表格展示该级的下一级明细。
- 例：部门多选了具体值（科室未配置具体值）→ 按部门分组，组内子表格展科室；
  科室也配置了具体值 → 按科室分组，组内子表格展班组。
- **边界**：若最细已经选到"班组"（没有下一级），不生成子表格，摊平展示明细。
- 实现层面：ES 聚合层本身已产出嵌套桶，但当前解析层拍平成"每行同时带父子维度值"的平铺行——分组+
  子表格结构不需要改后端聚合/响应契约，前端对已有的平铺多维行按需要分组的那一级做一次 group-by 即可
  还原（见 spec.md §4 AD-02）。

---

## 3. 明确排除 / 延后

- 不做组织架构的树形筛选 UI（平铺即可）。
- 不为"没数据的组织单元"在结果里插 0 值行。
- 不新建统一用户数据 ES 索引/同步链路，三个用户数据源保持独立，只做 UI 层合并。
- 用户数据集部门维度不升级四级。
- 部门名称快照字段的简称匹配歧义（重名/改名/已删除）已知会有失配风险，本期不做消歧修复，匹配不到即降级全称。
