# Design: 文档知识库外层列表展示文件解析异常

> **本文档定位 — 现状快照（Why this How）**

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v3.0.0-beta1
**最后更新**: 2026-09-10

---

## 1. 目标与非目标

- **目标**：管理后台文档知识库外层列表直接标出「库内是否有解析异常文件」，并支持只看异常库，减少逐库排查。
- **非目标**：不改 QA / 知识空间 / 工作台；不展示计数或分状态；不反范式写回 `knowledge` 表；不改解析写状态。

---

## 2. 关键约束

遵循 `docs/constitution.md` C1–C7。本功能特有：

- 中信保客户文档库数量多，外层列表是 F027 游标分页（约 20 条/页），筛选必须下推 SQL，不能在内存滤完再分页。
- `knowledgefile.status` 原先无可用复合索引；筛「仅异常」时，无异常的大库会沿 `knowledge_id` 扫完全部 SUCCESS 行才能证明不存在。
- 文档库无文件级 ReBAC（库级可见即可），与知识空间文件夹 rollup 的 `view_file` 过滤不同。
- Platform 尚未接入 `@bisheng/ui`；异常标签复用内层文件列表的红点+红字。

---

## 3. 方案对比与选定

### 决策 1：库级异常如何计算

- **备选**：
  - A. 实时 `EXISTS` / 本页批量 DISTINCT — 始终与文件表一致；列表页 20 条成本低
  - B. 在 `knowledge` 表加 `has_abnormal` 并在解析成功/失败/删除时双写 — 筛很快，但双库下易漂
- **选定**：A
- **原因**：避免解析管线双写；C2 下维护成本高于列表读放大
- **何时该重新考虑**：单页需要判断的库数远超当前 page size，或「仅异常」全表 EXISTS 成为热点

### 决策 2：筛选落在哪一层

- **备选**：
  - A. SQL `EXISTS` 进入 `generate_all_knowledge_filter`，与名称、`id_in`、keyset 同时生效
  - B. Service 拉一页再内存丢掉非异常行
- **选定**：A
- **原因**：B 会抽空 F027 游标页（一页 20 条可能全被丢掉，`has_more` 失真）
- **何时该重新考虑**：无

### 决策 3：Platform 标签组件

- **备选**：
  - A. 复用 `Files.tsx` 红点+红字
  - B. 首次把 `@bisheng/ui` Tag 引进 Platform
- **选定**：A
- **原因**：Platform 尚无该依赖；本次不应借一个标签完成组件库接入
- **何时该重新考虑**：Platform 已统一接入 `@bisheng/ui`

---

## 4. 系统现状（接手必读）

### 4.1 数据流

`KnowledgeFile.tsx` → `GET /api/v1/knowledge?type=0` → `KnowledgeService.get_knowledge` → `KnowledgeDao.aget_all_knowledge`（可选 EXISTS）→ `aconvert_knowledge_read` 对本页 NORMAL id 批量 `async_exists_abnormal_files_batch` → 行字段 `has_abnormal_files` → 外层【文件状态】列。

筛「仅异常」时 `has_abnormal=true` 进入 DAO WHERE，不在 Service 内存滤。

点异常行 → `/filelib/:id?fileStatus=abnormal` → `Files.tsx` 预筛选 status `3/6/7`。

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| `has_abnormal` | query bool, 可选 | 仅 `true` 时筛异常库；省略 / false = 不筛 | Platform 文档库列表 |
| `has_abnormal_files` | response bool, 默认 false | 本库是否存在异常有效文件 | Platform 列表行 |
| 有效文件 | `file_type=1` | 硬删即不存在；不含文件夹 | DAO |
| 异常状态 | `{3,6,7}` | FAILED / TIMEOUT / VIOLATION | DAO；与空间 rollup 语义对齐 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `knowledge_file.py` | 异常状态常量、批量 EXISTS、复合索引声明 | 不组装列表行 |
| `knowledge.py` DAO | 列表 WHERE 下推 EXISTS | 不计算展示文案 |
| `knowledge_service.py` | 传筛选参数；QA+仅异常直接空页；异步组装布尔字段 | 不改权限裁决 |
| `KnowledgeFile.tsx` | 列、红标签、表头筛选 | 不引入 `@bisheng/ui` |
| `Files.tsx` | 读 `fileStatus=abnormal` 预筛内层 | 不改外层列表 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 文档库按库级可见，空间文件夹 rollup 还要按文件 ReBAC 过滤 | 错把空间逻辑搬过来会漏标管理者可见的失败文件 | 只查 `knowledgefile`，不做 `view_file` |
| 2 | TIMEOUT(6) 主路径很少写入，但历史数据与枚举仍在 | 筛异常时漏 6，现场对不上「超时」 | 状态集合含 6 |
| 3 | Radix `SelectItem` 不能用空字符串 value | 表头筛选会整页崩溃 | 选项用 `all` / `abnormal` |
| 4 | F027 游标页在内存过滤会丢行 | 「仅异常」看起来丢页或永不相等 | EXISTS 下推 DAO |
| 5 | QA 与文档库共用 `GET /knowledge` | QA 带 `has_abnormal=true` 会去扫文档文件表 | QA 直接空页，组装时只查 `type=0` |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /api/v1/knowledge` 增加可选 `has_abnormal` | HTTP query | Platform 文档库列表 |
| `KnowledgeRead.has_abnormal_files` | 响应字段，默认 false | Platform；v2 列表因共用组装会自然带上 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F027 cursor envelope `{data, page_size, has_more, next_cursor}` | 列表契约 | 不得重新引入 `total` |
| F048 visible-first / admin bypass | `id_in` + 权限短路 | 异常筛选不得绕过可见集 |
| `knowledgefile.status` / `file_type` | 文件表 | 解析状态语义变更会改「异常」定义 |

---

## 7. 测试与可观测

- DAO：批量 EXISTS、仅文件夹 / 仅 PROCESSING 不标异常、`has_abnormal=true` 的 SQL 含 EXISTS。
- Service：文档库行打标；QA 恒 false；QA+仅异常空页且不扫文件表。
- 前端：有/无标签；筛仅异常走 `filterData`；异常行带 `fileStatus=abnormal`。
- 回归：F027 游标、F048 visible-first、F051 行操作懒加载。
- 手动：`/filelib` 文档库 Tab，确认异常列、筛选与进入详情后的内层预筛。

---

## 8. 后续改进 / 不打算做的事

- 异常文件数、分状态标签：产品只要布尔「异常」。
- Platform 接入 `@bisheng/ui` Tag：等平台级接入，不在本 Feature 做。
- v2 筛选参数：本期无开放面需求。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-09-10 | 初版 | 实现方案确认后落地 |
