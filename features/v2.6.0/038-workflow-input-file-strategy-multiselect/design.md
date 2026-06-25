# Design: 工作流输入节点文件处理策略多选

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v2.6.0
**最后更新**: 2026-06-25（初版）

---

## 1. 目标与非目标

- **目标**：把输入节点「文件处理策略」从单选升级为「按文档/图片分组配置」——对话框组内单选、表单可多选；并同时展示/保存/执行各策略对应的配置与输出变量。
- **非目标**：不新增处理模式；不迁移历史数据（运行时兼容旧字符串）；对话框不支持同类型组内多选。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C7。本功能特有约束：
  - **三种模式语义不变**：`extract_text`（解析文本）/ `keep_raw`（保留原始）/ `ingest_to_temp_kb`（入临时知识库）。
  - **向后兼容**：存量工作流 `file_parse_mode` 是单字符串，读取侧必须兼容「字符串 / map / 数组」三种形态，旧流程行为不变。
  - **解析只做一次**：多策略下文本解析复用同一份产物，避免重复解析与重复入库。

---

## 3. 方案对比与选定

### 决策 1：对话框「按文件类型分组」怎么存

- **备选**：
  - A. 扁平数组 `["extract_text","keep_raw"]`（不区分类型）——最简单；缺点：丢失「文档/图片各选了啥」，后端无法做到「文档解析、图片不解析」分别处理。
  - B.（选定）按文件类型 map `{"doc":"extract_text","image":"keep_raw"}`，只含当前上传类型涉及的组。
- **选定**：B
- **原因**：PRD 要求「全部类型」时文档与图片可选不同策略并分别执行；只有按类型存才能在后端按扩展名分流套用各组策略。代价是前后端读取逻辑略复杂，但语义正确。
- **何时该重新考虑**：若产品后续放弃「文档/图片分别处理」、退回「一刀切」，可简化为扁平数组。

### 决策 2：表单「可多选」的数据形态

- **选定**：数组 `["extract_text","ingest_to_temp_kb"]`。`keep_raw` 与其它互斥（前端约束，数组里要么只含 keep_raw、要么是 extract/ingest 的子集）。
- **原因**：表单是「同一文件项多策略」，数组天然表达多选；至少一个、不允许全空（默认 extract_text）。

### 决策 3：兼容旧值

- **选定**：读取侧统一**归一化**为「模式集合」：字符串→单元素集合；数组→集合；map→按文件类型取对应组的单值。执行逻辑只面对集合形态。不批量迁移历史数据。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（今天）

`前端配置(file_parse_mode 单值) → 存入节点 params → 执行 input.py：parse_upload_file 逐文件处理 → _parse_upload_file_variables 按单一 mode 选择对外变量 → 下游节点引用`

- **执行入口**：`bisheng/workflow/nodes/input/input.py`
  - `_run`：对话框分支（~L174-194）组装 `key_info`（含 `file_parse_mode`、`file_type=dialog_file_accept`），调 `parse_upload_file` 再 `_parse_upload_file_variables`；表单分支（~L196-215）按每个文件表单项同理。
  - `parse_upload_file`（L275-366）：逐文件记录 metadata/path/image；`KEEP_RAW`→只留 path/image（`continue`）；否则解析文本累加（受 `file_content_size` 上限）；`EXTRACT_TEXT`→不入库（`continue`）；否则 `INGEST`→写 Milvus+ES（临时知识库）。**注意：该函数本就总是记录 path+image、总是按需解析**，真正决定「对外暴露哪些变量」的是下一个函数。
  - `_parse_upload_file_variables`（L150-171）：**当前按单一 `file_parse_mode` 的 if-elif-else** 决定暴露哪组变量（keep_raw→image+path；extract→content；ingest→key）。**这是本次核心改动点**。

### 4.2 关键数据结构 / 字段约定

**`file_parse_mode`（升级后，对外契约）**：

| 输入形态 | 结构 | 示例 |
|---|---|---|
| 对话框 | 按文件类型 map（仅含当前涉及组） | `{"doc":"extract_text","image":"keep_raw"}` |
| 表单 | 模式数组（多选；keep_raw 互斥） | `["extract_text","ingest_to_temp_kb"]` |
| 历史值 | 单字符串（兼容） | `"extract_text"` |

**归一化函数（新增）**：把上述三态统一成「这类文件要套哪些模式」的集合，供执行逻辑消费。

**输出变量（不变）**：`dialog_files_content` / `dialog_file_paths` / `dialog_image_files`（对话框）；表单项的 file_content / file_path / image_file / key（临时库）。

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 本次改动 |
|---|---|---|
| `GroupInputFile.tsx`（对话框配置） | 渲染上传类型 + 策略 + 变量徽标 | 单值 → 按类型分组单选；变量按并集联动 |
| `InputFormItem.tsx`（表单项配置） | 文件表单项策略 + 配置项 | 单选 → 多选（keep_raw 互斥）；`shouldShowField` 等值 → includes |
| `flowUtils.ts` / `SelectVar.tsx`（变量过滤/选择） | 决定下游可选变量 | 等值判断 → map/数组 includes 判断 |
| `input.py` `_parse_upload_file_variables` | 决定暴露哪些变量 | 单分支 → 按模式集合累加 |
| `input.py` `parse_upload_file` / 归一化 | 逐文件处理 | 读取兼容三态；对话框按扩展名分流套各组模式 |
| `flowUtils.ts` `flowCompatible.ts` `comptibleInput` | **节点升级脚本**（按 `node.v` 版本递进，工作流加载时跑） | 新增版本档：把旧 `file_parse_mode`（单字符串）升级为对话框 map / 表单数组结构 |

### 4.4 节点升级脚本（comptibleInput）

`flowCompatible.ts` 的 `comptibleInput(node)` 在工作流加载到画布时，按 `node.v` 逐档升级旧节点结构（已有 0→1、1→2）。现状：**2→3 一档被注释掉**（草拟了引入 `file_parse_mode` 的 v3 分组结构但未启用）；而当前组件 `GroupInputFile.tsx` 已直接读单值 `file_parse_mode`，所以**未升级的旧 v2 节点打开会因缺 `file_parse_mode` 出错**。

F038 要做：**写活升级档**，把旧节点（无 `file_parse_mode` 或单字符串值）升级为本期新结构——对话框转 `{doc, image}` map（按当时 `dialog_file_accept` 推断初值）、表单文件项的 `file_parse_mode` 转单元素数组。与那段注释的 v3 草案对齐/合并，不要并存两套。

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `parse_upload_file` 本就总记录 path+image、总按需解析；决定「暴露哪些变量」的是 `_parse_upload_file_variables` 而非它 | 改错地方，多选不生效 | 核心改 `_parse_upload_file_variables` 为集合累加 |
| 2 | 对话框「全部类型」下文档/图片可选不同策略，需按**扩展名**把文件分到 doc/image 再套对应模式 | 图片被当文档解析、或文档没解析 | `parse_upload_file` 按 `_image_ext` 分类 + 按类型取模式 |
| 3 | `file_parse_mode` 升级后有三种形态，任何读取处只认字符串都会炸 | 历史流程/新流程二选一坏掉 | 统一归一化函数，所有读取走它 |
| 4 | 表单 `keep_raw` 与 extract/ingest 互斥，但 extract 与 ingest 可共存 | 前端允许非法组合，后端产出错乱 | 前端选择器约束 + 后端按集合稳健处理 |
| 5 | 旧 v2 输入节点的 2→3 升级在 `flowCompatible.ts` 里**被注释**，而组件已读 `file_parse_mode`；不写活升级脚本，旧工作流打开即报错（缺字段） | 存量工作流在新前端打不开/配置错乱 | F038 写活 `comptibleInput` 升级档，旧值迁新结构 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `file_parse_mode`（map/数组/字符串三态） | 节点 params 数据契约 | 工作流存储、执行引擎、前端配置/变量选择 |
| 输出变量（content/path/image/临时库） | 节点输出变量 | 下游大模型/多模态/代码/知识库问答节点 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| `get_upload_file_path_content` 解析文本 | 内部方法 | 解析失败时多策略产出需稳健兜底 |
| 临时知识库 Milvus/ES 写入 | 向量库 | 入库仅在含 ingest 时触发 |

---

## 7. 测试与可观测

- **后端单测**：归一化函数（字符串/map/数组三态）；`_parse_upload_file_variables` 各模式组合产出正确变量；对话框混合类型按扩展名分流；历史单值流程回归不变。
- **前端手动验证**：对话框三种上传类型下分组渲染 + 变量联动；表单多选互斥 + 配置项融合展示；下游变量选择器只列实际产出变量。
- **可观测**：保留 `file_parse_mode` 的 debug 日志，多策略下记录实际触发的处理路径。

---

## 8. 后续改进 / 不打算做的事

- 不迁移历史数据；不做对话框组内多选；不新增处理模式。
- 若后续要支持更多文件类型分组（如音视频），归一化与分流逻辑可扩展。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-06-25 | 初版 | 设计定稿（数据结构按类型存，用户确认） |
