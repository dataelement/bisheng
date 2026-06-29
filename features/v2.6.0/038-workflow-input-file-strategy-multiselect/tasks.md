# Tasks: 工作流输入节点文件处理策略（单选 + 输出变量联动）

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | 🔁 已按新 PRD 重写 | 2026-06-26 单选 + 变量联动 |
| design.md | 🔁 已按新 PRD 重写 | 含统一变量规则 §4.3、迁移 §4.4 |
| tasks.md | 🔁 重新拆解（返工） | 见下 |
| 实现 | 🟢 返工完成（R1–R8） | 后端统一规则 + 前端单选回退 + 升级脚本 + i18n + 后端单测 24 passed；剩 R9 端到端、R10 重部 120 |

---

## 需求变更说明（2026-06-26）

按 06.24 评审更新版 PRD，需求由「策略多选」改为「策略**单选** + 按上传文件类型**联动输出变量**」。上一版（对话框 `{doc,image}` map 分组单选、表单 checkbox 多选）**已作废**。变更分析与新规则见 spec §3/§5、design §3/§4.3。

**上一版已落地物（需回退/改写）**：
- 提交 `b956085de`（feat/2.6.0，已并入分支历史）。
- 已部署 120 信保环境（前端整包 + 后端 input.py）——回退实现后需**重新部署 120**。

---

## 返工任务

### Wave 1 — 后端变量暴露规则（核心）

- [x] **R1**: `_parse_upload_file_variables` 改为「统一规则产并集」
  **文件**: `input.py` + `test/workflow/test_input_parse_mode.py`
  **逻辑**: path 恒暴露；image 当 `file_type ∈ {all,image}`；content 当 active 含 extract；key 当 active 含 ingest。去掉 keep_raw / image_keep_raw 门控（见 design §4.3）。
  **测试**: 按 spec §2.1/§2.2 全矩阵（策略 × file_type）逐格断言；历史字符串 / 上一版 map/数组 回归。
  **覆盖 AC**: AC-01~AC-14, AC-17

- [ ] **R2**: `parse_upload_file` 简化（可选）
  **文件**: `input.py`
  **逻辑**: 对话框单字符串对所有文件同一模式，按扩展名分流套不同模式的逻辑不再必要；保留 image/path 始终记录、按 active 解析/入库即可。归一化 `_active_modes`/`_modes_for_file` 保留（兼容上一版 map）。
  **覆盖 AC**: AC-16, AC-17

### Wave 2 — 前端回退/改写

- [x] **R3**: `GroupInputFile.tsx` 对话框 → 单选下拉
  **逻辑**: 去掉 doc/image 分组与 `{doc,image}` map；单选下拉 2 项（解析 / 不解析），存单字符串。变量徽标按 design §4.3 联动：解析→长度上限+content；image 当类型∈{全部,图片}；path 恒显。
  **覆盖 AC**: AC-01~AC-06, AC-15

- [x] **R4**: `InputFormItem.tsx` 表单 → 单选下拉 3 项（重命名）
  **逻辑**: 去掉 checkbox 多选；单选下拉 3 项——解析(不入库)/解析(入库)/不解析；存固定数组（`[extract]` / `[extract,ingest]` / `[keep_raw]`）。`shouldShowField`/校验/提交/摘要按 design §4.3 联动（长度上限+解析结果名 当解析；图片名 当类型∈{全部,图片}；文件路径名 恒显；临时库名 当入库）。
  **覆盖 AC**: AC-07~AC-14, AC-15

- [x] **R5**: `SelectVar.tsx` + `flowUtils.ts` 变量过滤改统一规则
  **逻辑**: 对话框分支与表单 `getSpecialVar` 改为按 design §4.3 判断（path 恒有、image 看 file_type、content 看 extract、key 看 ingest）。
  **覆盖 AC**: AC-18

- [x] **R6**: `flowCompatible.ts comptibleInput` 升级脚本调整
  **逻辑**: 对话框单字符串默认 `extract_text`（保持）；表单单字符串→数组映射：extract→`[extract]`、keep_raw→`[keep_raw]`、ingest→`[extract,ingest]`（见 design §4.4）。
  **覆盖 AC**: AC-16

- [x] **R7**: i18n 文案
  **文件**: `public/locales/{en-US,zh-Hans,ja}/flow.json`
  **逻辑**: 表单 3 选项重命名（解析(不存入临时知识库)/解析(存入临时知识库)/不解析）；对话框去掉 docFileProcessingStrategy/imageFileProcessingStrategy 分组标题、回到单一「文件处理策略」。
  **覆盖 AC**: —

### Wave 3 — 验证与部署

- [x] **R8**: 后端单测全绿（R1）。
- [ ] **R9**: 端到端手动验证：对话框 2×3 矩阵、表单 3×3 矩阵变量联动；打开旧 v2 / 上一版 120 节点不报错、回填最接近单选项；执行产出符合 §4.3。
- [ ] **R10**: 重新部署 120（前端整包 + 后端 input.py），见 [[project_120_sinosure_deploy]]。

---

## 数据结构契约（新）

- 对话框 `file_parse_mode` = 单字符串 `extract_text` / `keep_raw`。
- 表单 `file_parse_mode` = 数组：`[extract_text]` / `[extract_text, ingest_to_temp_kb]` / `[keep_raw]`。
- 兼容历史：旧单字符串、上一版对话框 map、上一版表单自由数组 —— 读取侧 `_active_modes` 归一。

**设计走查 HTML**: http://192.168.106.120:3000/share/C-_i9sjF0D_ELaDI19GRoTxl

---

## 历史（上一版"真·多选"，已作废）

上一版任务 T001–T009 及交接记录见 git 历史（提交 b956085de 及本文件先前版本）。核心差异：对话框分组 map、表单 checkbox 多选、变量按所选模式精确暴露——均被本次「单选 + 统一变量规则」取代。

---

## 实际偏差记录

- 2026-06-26：PRD 由「多选」更新为「单选 + 变量联动」，上一版实现作废，全面返工（本 tasks 为返工版）。
