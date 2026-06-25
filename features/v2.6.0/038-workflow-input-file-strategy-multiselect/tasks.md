# Tasks: 工作流输入节点文件处理策略多选

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | |
| design.md | ✅ 已评审 | 含升级脚本 §4.4 |
| tasks.md | ✅ 已拆解 | |
| 实现 | 🟢 基本完成 | 后端+前端三块+升级脚本+后端单测完成；剩 T009 端到端手动验证（需起环境） |

---

## 交接（下个 session 从这里接）

**已完成（已写代码，未提交、未跑测试）**：
- ✅ **后端 `input.py`**（T001-T003）：新增 `_modes_for_file` / `_active_modes` 归一化；`_parse_upload_file_variables` 改按模式集合并集暴露变量；`parse_upload_file` 按文件扩展名分文档/图片、各取模式、多模式累加产出。**已 review + 修一个回归**：旧 v2 表单无 `file_parse_mode` 时兜底必须是 `ingest_to_temp_kb`（不是 extract），否则老流程不再入库。v≤2 早返回路径未动。
- ✅ **对话框 `GroupInputFile.tsx`**（T005）：单值→按文档/图片分组单选，`file_parse_mode` 存 map `{doc,image}`，`toModeMap`/`persistModeMap` 归一+只存可见组；变量按 `anyExtract`/`anyKeepRaw`/`imageKeepRaw` 并集联动。
- ✅ **`flowUtils.ts` `filterParamByinputCheck`**（T007 对话框部分）：改 map/并集判断。
- ✅ **i18n**：flow.json 三语言加 `docFileProcessingStrategy` / `imageFileProcessingStrategy`。

**本 session 已完成**：
- ✅ **T004 升级脚本** `flowCompatible.ts` `comptibleInput`：写活 v2→v3，把 v2 扁平单组结构重组为 v3 的 4 组（接收文本/inputfile/custom推荐问题/表单），表单 file 项 `file_parse_mode` 字符串→单元素数组；dialog `file_parse_mode` 用字符串 `"extract_text"` 默认(读取端归一化为 map)，recommended_llm/prompt 留空避免环境耦合。**确认是 2→3 不是 3→4**：后端 `_current_v=2`、`node.v>2` 才进多选分支，模板即 v3。
- ✅ **T006 `InputFormItem.tsx`**：`processingStrategy`(单)→`processingStrategies`(数组)；策略选择器改多选(keep_raw 互斥、解析+入库可共存、至少选一)；`shouldShowField`/校验/提交序列化/摘要全改并集；提交按并集清字段；`file_parse_mode` 存数组。
- ✅ **T007** `SelectVar.tsx`：`getSpecialVar` form 分支单值 switch→数组 includes 累加；另把 dialog `inputfile` 组的变量过滤(原 `=== 'extract_text'`)改成 map 并集(anyExtract/anyKeepRaw/imageKeepRaw)。
- ✅ **后端单测** `test/workflow/test_input_parse_mode.py`：16 用例覆盖 `_modes_for_file`/`_active_modes`/`_parse_upload_file_variables`(map/数组/字符串三态 + v≤2 旧路径回归),全绿。

**待续**：
- ⬜ **T003 的单测**：`parse_upload_file` 逐文件分流是重 IO(下载/解析 minio),未写 mock 单测;其纯逻辑(`_modes_for_file` 每文件取模式)已覆盖,分流行为留 T009 端到端验。
- ⬜ **T009 端到端手动验证**(需起前后端+中间件):①新建工作流对话框分组+表单多选互斥 ②打开旧 v2 工作流升级不报错回填正确 ③混合类型分流+多选一次解析双产出 ④旧单值回归。
- 前端 `tsc` 残留类型报错(FileTypeSelect 联合类型/InputItem 缺 i18nPrefix/const enum)均为**既有**,非本次引入(同样出现在未改的 `InputFormItemOld.tsx`)。

**数据结构契约**（已定）：对话框 `{doc,image}` map、表单 `[mode,...]` 数组、旧单字符串兼容；后端归一化在 `_modes_for_file`/`_active_modes`。
**设计走查 HTML**：http://192.168.106.120:3000/share/C-_i9sjF0D_ELaDI19GRoTxl

---

## 开发模式

- 后端 Test-First：归一化 + 执行分支写单测；前端手动验证。
- **升级脚本是硬要求**：旧 v2 输入节点必须能在新前端正常打开（见 design §4.4 / §5 坑5）。
- 仓库均在 `src/frontend/platform`（前端）与 `src/backend`（后端）。

---

## Tasks

### Wave 1 — 后端基础（无依赖）

- [ ] **T001**: file_parse_mode 归一化 + 单测
  **文件**: `src/backend/bisheng/workflow/nodes/input/input.py` + `src/backend/test/workflow/test_input_parse_mode.py`
  **逻辑**: 新增归一化：字符串→单元素集合；表单数组→集合；对话框 map→按文件类型取对应组单值。统一产出「某类文件要套哪些模式」。
  **测试**: 三态各自归一正确；非法/空值兜底默认 extract_text。
  **覆盖 AC**: AC-10
  **依赖**: 无

### Wave 2 — 后端执行（依赖 T001）

- [ ] **T002**: `_parse_upload_file_variables` 改集合累加 + 单测
  **文件**: `input.py`（L150-171 区域）+ 测试
  **逻辑**: 从 if-elif-else 单分支 → 按所选模式集合累加暴露变量：含 extract→content；含 keep_raw→path（含图片→image）；含 ingest→key。多模式可同时暴露。
  **覆盖 AC**: AC-11, AC-13
  **依赖**: T001

- [ ] **T003**: `parse_upload_file` 对话框按类型分流 + 单测
  **文件**: `input.py`（L275-366 区域）+ 测试
  **逻辑**: 对话框混合类型时，按 `_image_ext` 把文件分文档/图片，文档套 doc 组模式、图片套 image 组模式；解析只做一次、产物按集合分发，避免重复解析/重复入库。
  **覆盖 AC**: AC-11, AC-12
  **依赖**: T001

### Wave 3 — 前端

- [ ] **T004**: 节点升级脚本写活
  **文件**: `src/frontend/platform/src/util/flowCompatible.ts`（`comptibleInput`）
  **逻辑**: 写活升级档：旧节点（无 `file_parse_mode` 或单字符串）→ 对话框转 `{doc,image}` map（按 `dialog_file_accept` 推断初值）、表单文件项 `file_parse_mode` 转单元素数组。与注释的 v3 草案对齐合并，避免两套并存。递进 `node.v`。
  **覆盖 AC**: AC-09, AC-10
  **依赖**: 无（可与后端并行）

- [ ] **T005**: 对话框分组单选 + 变量联动
  **文件**: `GroupInputFile.tsx`
  **逻辑**: 按 `dialog_file_accept`（文档/图片/全部）渲染 1~2 个分组、每组单选；状态从单值改按类型 map；变量徽标按并集联动（任一组解析→content；任一组不解析→path；图片组不解析且含图片→image）。
  **覆盖 AC**: AC-01~AC-05
  **依赖**: T004

- [ ] **T006**: 表单多选 + 配置项融合
  **文件**: `InputFormItem.tsx`
  **逻辑**: 策略选择器单选→多选（解析/存临时库 可多选，不解析 互斥单选），「至少选一」校验（默认 extract_text）；`shouldShowField` 等值→`includes`；按并集融合展示配置项。
  **覆盖 AC**: AC-06, AC-07, AC-08
  **依赖**: T004

- [ ] **T007**: 变量过滤/选择改 includes
  **文件**: `src/util/flowUtils.ts`（`filterParamByinputCheck`）+ `SelectVar.tsx`（`getSpecialVar`）
  **逻辑**: 所有 `=== 某模式` 单值判断改为对 map/数组的 `includes` 判断，保证下游变量选择器只列实际产出变量。
  **覆盖 AC**: AC-13
  **依赖**: T005, T006

### Wave 4 — 端到端验证

- [ ] **T008**: i18n 文案
  **文件**: `public/locales/{en-US,zh-Hans,ja}/flow.json`
  **逻辑**: 新增/调整分组标题、多选相关提示文案，三语言齐全。
  **覆盖 AC**: —
  **依赖**: T005, T006

- [ ] **T009**: 端到端手动验证
  **逻辑**: ① 新建工作流：对话框三种上传类型分组渲染 + 变量联动；表单多选互斥 + 配置融合。② **打开旧 v2 工作流**：升级脚本生效、不报错、策略正确回填。③ 执行：混合类型按扩展名分流（文档解析、图片不解析）；多选「解析+入库」一次解析双产出。④ 旧单值流程回归不变。
  **覆盖 AC**: AC-01~AC-13
  **依赖**: T001~T008

---

## 实际偏差记录

（待填）
