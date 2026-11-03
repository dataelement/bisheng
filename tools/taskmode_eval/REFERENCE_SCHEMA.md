# 参考答案格式（reference.json）

每条正式用例在 `cases/<用例编号>/reference.json` 放一份参考答案。判分脚本 `grade.py` 只读这个文件判分。

## 字段

```json
{
  "case_id": "C04",
  "annotator": "claude-agent",
  "annotated_at": "2026-11-03",
  "inputs_exclude": [],
  "query_override": null,
  "expected_status": "completed",
  "checks": [],
  "rubric": [],
  "judge_notes": "",
  "pass_threshold": 0.7
}
```

- `inputs_exclude`：执行时不上传的输入文件名。用于去掉泄露答案的文件，例如上一轮产物被当作输入上传。
- `query_override`：需要改写 query 时填新 query，否则填 null。只在原 query 依赖多轮上下文、单轮无法理解时使用，并在 `judge_notes` 写明原因。
- `expected_status`：期望终态，通常是 `completed`。
- `checks`：确定性检查，由脚本直接判定，不调用模型。
- `rubric`：评分要点，由评审模型（LLM judge）逐条判定通过或不通过。
- `judge_notes`：给评审模型的背景，写参考事实、正确数值、常见错误。评审模型看得到这段，被测系统看不到。
- `pass_threshold`：加权得分达到这个比例且所有 `critical` 项都通过，用例才算通过。默认 0.7。

## checks：确定性检查

每项都有 `id`（c1、c2…）、`type`、`desc`，可选 `weight`（默认 1）和 `critical`（默认 false）。

`target` 指检查对象：`answer` 是最终回答正文，`files` 是全部产物文件抽出的文本，`all` 是两者合并。产物文本由判分脚本抽取：docx 取段落和表格，pptx 取每页文字，xlsx 取每个 sheet 的单元格，html 去标签后的文字加 `<script>` 里的数据，md、txt、json、csv 取原文。

| type | 参数 | 判定 |
|---|---|---|
| `file_exists` | `ext`（如 `["docx"]`）、`min`（默认 1） | 产物里至少有 `min` 个指定扩展名的文件 |
| `no_files` | — | 没有产物文件 |
| `regex` | `target`、`pattern`、`flags`（可选 `"i"`、`"s"`） | 正则能匹配 |
| `not_regex` | `target`、`pattern` | 正则不能匹配 |
| `contains_all` | `target`、`values` | 每个字符串都出现 |
| `contains_any` | `target`、`values`、`min`（默认 1） | 至少 `min` 个字符串出现 |
| `numbers` | `target`、`values: [{"label","value","tol"}]`、`min`（默认全部）、`unit_flex`（可选） | 文本里能找到与 `value` 相差不超过 `tol` 的数（去掉千分位逗号后比较）；至少命中 `min` 个。`unit_flex: true` 时也接受换算成万、亿后的写法（`value` 按元写） |
| `json_valid` | `target`（`answer`、`files` 或 `any`）、`required_keys`（可选，顶层键） | 能解析出 JSON 对象且含这些键。`answer` 允许被代码围栏包住 |
| `paragraphs` | `target`、`count` | 非空段落数（按空行分段）等于 `count` |
| `pptx_slides` | `min`、`max` | 某个 pptx 的页数落在区间内 |
| `xlsx_rows` | `min`、`headers`（可选） | 某个 xlsx 的某个 sheet 数据行数 ≥ `min`，且表头含这些列名 |

能用确定性检查判定的，不要放进 rubric。

## rubric：评分要点

```json
{"id": "r1", "desc": "指出 2024 版把合同审批权限从……改为……", "weight": 2, "critical": true}
```

每条只写一个可判定的事实或行为，评审模型只回答通过或不通过。写法要求：

- 写具体事实，不写"内容完整""质量高"这类笼统判断。
- 数值、条款号、名称写在 `desc` 或 `judge_notes` 里，让评审模型能对照。
- `critical: true` 只给"错了这条结果就不能用"的要点，例如核心结论、关键数值、主体识别。
- 扣分项也写成要点，例如"没有编造输入中不存在的数据"。
- 一条用例一般 4–10 条 rubric。

## 标注原则

- 参考答案来自输入文件和知识空间原文，不来自历史产出 `baseline/`。历史产出只能用来了解常见错误。
- 开放 API 执行期间不会向用户提问。信息不足的用例，期望行为是按合理假设完成并在回答里写明假设。
- 客户数据只放在 106、116、114 三处，不拷到本机，不进代码仓库。
