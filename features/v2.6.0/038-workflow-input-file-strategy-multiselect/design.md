# Design: 工作流输入节点文件处理策略（单选 + 输出变量联动）

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v2.6.0
**最后更新**: 2026-06-26（按 06.24 评审更新版 PRD 重写；上一版"真·多选"已作废）

---

## 1. 目标与非目标

- **目标**：选定单个「文件处理策略」后，按上传文件类型联动暴露该场景下全部有用的输出变量（解析文本 / 原图 / 文件路径 / 临时知识库），并把「解析 + 入库」做成命名好的单选项。
- **非目标**：不做真·多选 UI（自由勾选）；不新增底层处理模式；不迁移历史数据（运行时兼容）。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C7。本功能特有约束：
  - **三种底层原子模式不变**：`extract_text`（解析文本）/ `keep_raw`（保留原始）/ `ingest_to_temp_kb`（入临时知识库）。UI 选项是它们的组合命名。
  - **统一变量规则**（见 §4.3）：path 恒有、image 按上传类型、content 按是否解析、key 按是否入库——对话框与表单同一套。
  - **向后兼容**：读取侧必须兼容「字符串 / 数组 / 上一版 map」三种形态。
  - **解析只做一次**：多产出复用同一份解析结果，避免重复解析 / 重复入库。

---

## 3. 方案对比与选定

### 决策 1（本次变更）：多选 → 单选 + 命名组合项

- **背景**：上一版做了真·多选（对话框分组单选存 map、表单 checkbox 存数组）。06.24 评审更新 PRD 改为**保持单选**，用「输出变量联动」达到多产出效果。
- **选定**：
  - 对话框：单选 2 项（解析 / 不解析）。
  - 表单：单选 3 项，把唯一有意义的组合「解析 + 入库」做成独立命名项「解析文件内容(存入临时知识库)」。
- **原因**：用户真正想要的组合只有「解析 + 入库」，做成命名选项比让用户理解 checkbox 互斥规则更直观；其余多产出（原图 / 路径）改为「选了解析也一并给」，无需用户操心。
- **代价**：UI 要从上一版回退；后端变量暴露规则改为「按统一规则产并集」。
- **何时重新考虑**：若产品后续又要「文档解析、图片不解析」这类按类型分别处理，则需回到按类型分组方案。

### 决策 2：表单「解析 + 入库」怎么存

- **选定**：复用数组形态 `[extract_text, ingest_to_temp_kb]`。三个单选项分别映射 `[extract_text]` / `[extract_text, ingest_to_temp_kb]` / `[keep_raw]`。
- **原因**：后端已有数组归一化（`_active_modes`），复用即可；UI 层把「3 个单选项 ↔ 3 个固定数组」做成确定映射，不暴露自由勾选。

### 决策 3：对话框怎么存

- **选定**：回到**单字符串** `extract_text` / `keep_raw`（不再用 `{doc,image}` map）。
- **原因**：对话框对所有文件用同一策略，无需按类型分流；单字符串最简、且与节点模板默认值一致。

---

## 4. 系统现状与改动点

### 4.1 执行入口

`bisheng/workflow/nodes/input/input.py`
- `_run`：对话框分支组装 `key_info`（`file_parse_mode` = 单字符串、`file_type` = `dialog_file_accept`）；表单分支按每个文件表单项（`file_parse_mode` = 数组）。
- `parse_upload_file`：逐文件**始终**记录 path + image；按需解析文本（含 extract 或 ingest 时）；含 ingest 时写临时库。**注意：该函数本就总记录 path+image、总按需解析**，真正决定"暴露哪些变量"的是下一个函数。
- `_parse_upload_file_variables`：**本次核心改动**——由「按所选模式精确暴露」改为「按统一规则产并集」。

### 4.2 数据结构契约

| 输入形态 | `file_parse_mode` 结构 | 示例 |
|---|---|---|
| 对话框 | **单字符串** | `"extract_text"` / `"keep_raw"` |
| 表单 | **数组**（3 个固定组合之一） | `["extract_text"]` / `["extract_text","ingest_to_temp_kb"]` / `["keep_raw"]` |
| 历史值 | 单字符串（旧）/ map（上一版对话框）/ 数组（上一版表单） | 兼容读取 |

归一化函数 `_active_modes(file_parse_mode)` 把上述形态统一成「激活的原子模式集合」。

### 4.3 统一变量暴露规则（`_parse_upload_file_variables` 新逻辑）

```
active = _active_modes(file_parse_mode)        # {extract_text?, keep_raw?, ingest_to_temp_kb?}
ret = {}
ret[file_path] = <路径>                          # path 恒暴露
if file_type in ("image", "all"):
    ret[image_file] = <图片>                     # image 按上传类型
if "extract_text" in active:
    ret[file_content] = <解析文本>               # content 按是否解析
if "ingest_to_temp_kb" in active:
    ret[key] = <临时库 key>                       # key 按是否入库
```

> 关键差异：① path、image 不再受 `keep_raw` 门控；② image 只看 `file_type`，不看模式；③ extract 也产出 path/image。`keep_raw` 此时不再单独决定任何变量（它只是「没有 extract / ingest」的那种单选项，其产出就是 path[+image]）。

### 4.4 节点升级脚本 / 兼容（`flowCompatible.ts comptibleInput` v2→v3）

- **对话框**：升级脚本把 `file_parse_mode` 置为单字符串默认 `"extract_text"`（已与新方案一致，无需 map）。
- **表单**：旧单字符串 → 数组映射：
  - `"extract_text"` → `["extract_text"]`（解析不入库）
  - `"keep_raw"` → `["keep_raw"]`（不解析）
  - `"ingest_to_temp_kb"` → **`["extract_text","ingest_to_temp_kb"]`**（PRD 把「存入临时知识库」原地重命名为「解析(存入临时知识库)」，新选项同时解析+入库）
- **上一版形态兼容**：若线上已有上一版的对话框 `{doc,image}` map / 表单自由多选数组（如已部署 120 的节点），读取侧 `_active_modes` 仍能归一执行；前端打开时按"取代表值/最接近单选项"回填（map 取任一组值；数组若含 ingest→解析(入库)，否则含 extract→解析(不入库)，否则不解析）。
- **运行时兜底**：旧表单纯 `["ingest_to_temp_kb"]`（仅入库、无 extract）在后端仍按 active 集合暴露 key（不报错）；UI 回填到「解析(入库)」。

> 迁移注记：旧"仅入库"与新"解析(入库)"语义不同（新增 content 产出），属 PRD 重命名带来的**预期行为变化**，对下游是「多一个可用变量」，加性、不破坏。

### 4.5 关键模块职责

| 模块 / 文件 | 职责 | 本次改动 |
|---|---|---|
| `GroupInputFile.tsx`（对话框） | 渲染上传类型 + 策略 + 变量徽标 | map/分组 → **单选下拉(2 项)**；变量按 §4.3 规则联动 |
| `InputFormItem.tsx`（表单项） | 文件表单项策略 + 配置项 | checkbox 多选 → **单选下拉(3 项重命名)**；配置项按 §4.3 联动；存固定数组 |
| `SelectVar.tsx` / `flowUtils.ts`（变量过滤/选择） | 决定下游可选变量 | 改为按 §4.3 统一规则判断（path 恒有、image 看类型、content 看解析、key 看入库） |
| `input.py _parse_upload_file_variables` | 决定暴露哪些变量 | **核心**：改为统一规则产并集（去掉 keep_raw / image_keep_raw 门控） |
| `input.py parse_upload_file` | 逐文件处理 | 对话框单字符串对所有文件同一模式，**按类型分流逻辑可简化**（不再需要 per-kind 不同模式） |
| `flowCompatible.ts comptibleInput` | 节点升级脚本 | 对话框单字符串、表单 3-组合数组映射（见 §4.4） |
| i18n `flow.json` | 文案 | 表单 3 个选项重命名；对话框去掉 doc/image 分组标题 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | PRD 标题写「多选」，正文实为「单选 + 变量联动」 | 又做成 checkbox 多选（上一版错） | 见 spec §5；本设计已纠正 |
| 2 | 「解析」也要暴露 path + image，不只 content | 下游拿不到原图/路径 | `_parse_upload_file_variables` 统一规则 |
| 3 | image 只看上传类型、不看是否 keep_raw | 解析图片时图片变量丢失 | §4.3 `file_type in (image,all)` |
| 4 | 表单「解析(入库)」= extract+ingest，存数组 `[extract,ingest]` | 当成单 ingest，content 不产出 | §4.2 + 升级脚本 §4.4 |
| 5 | 旧「仅入库」与新「解析(入库)」语义不同（多了 content） | 误判迁移破坏 | §4.4 迁移注记：加性、不破坏 |
| 6 | 已部署 120 的上一版节点是 map/自由数组 | 直接报错/配置错乱 | `_active_modes` 兼容 + 前端回填最接近单选项 |

---

## 6. 对外契约与依赖

### 6.1 提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `file_parse_mode`（对话框字符串 / 表单 3-组合数组 / 历史值兼容） | 节点 params 数据契约 | 工作流存储、执行引擎、前端配置/变量选择 |
| 输出变量（content/path/image/临时库 key） | 节点输出变量 | 下游大模型/多模态/代码/知识库问答节点 |

### 6.2 依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `get_upload_file_path_content` 解析文本 | 内部方法 | 解析失败时仍要稳健产出 path/image |
| 临时知识库 Milvus/ES 写入 | 向量库 | 仅在含 ingest 时触发 |

---

## 7. 测试与可观测

- **后端单测**：`_active_modes` 三态归一；`_parse_upload_file_variables` 按「策略 × file_type」产出正确变量（覆盖 spec §2.1/§2.2 全矩阵）；历史单字符串 / 上一版 map/数组 回归不报错。
- **前端手动验证**：对话框单选 2 项 × 3 上传类型变量联动；表单单选 3 项 × 3 上传类型变量/配置联动；下游变量选择器只列实际产出。
- **可观测**：保留 `file_parse_mode` debug 日志，记录实际触发的处理路径。

---

## 8. 后续改进 / 不打算做的事

- 不迁移历史数据；不做真·多选；不新增处理模式。
- 若后续要「文档与图片分别处理」，需回到按类型分组方案（上一版思路可参考）。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-06-25 | 初版（真·多选：对话框 map + 表单 checkbox） | 旧 PRD |
| 2026-06-26 | **重写为「单选 + 变量联动」** | 06.24 评审更新版 PRD（保持单选） |
