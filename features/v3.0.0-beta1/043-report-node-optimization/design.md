# Design: 报告节点优化（手动保存 + 变量显示节点名称）

> **本文档定位 — 现状快照（Why this How）**
> `spec.md` 回答做什么；本文回答**为什么这么实现**；`tasks.md` 是流水账。
> 实现变化 → 覆盖更新本文，只留"今天的状态"，但保留每条决策的"为什么 + 被否方案"与 §5 的坑。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v3.0.0-beta1
**最后更新**: 2026-07-24

---

## 1. 目标与非目标

- **目标**：给工作流「报告」节点的模板编辑补两块能力——① 用户可主动落盘（不再只依赖易失效的自动保存）；② 模板里的变量占位符人眼可读（显示节点名称而非节点 ID），同时**不改变执行期以节点 ID 取数的事实**。
- **非目标**：不修自动保存 bug 的根因（hotfix 轨道）；不迁移存量模板；不改 OnlyOffice 服务端插件；不做显示名与节点改名的实时同步；**不覆盖旧「技能」体系的独立报告页**（入口已关闭、后续计划删除残留代码）。

---

## 2. 关键约束

- 遵循 `docs/constitution.md` C1–C7。本特性不新增表、不新增 DAO 入口、不新增错误码。
- **INV-8（本版本契约新增）**：报告模板变量解析必须以**节点 ID** 为取数键；解析端必须永久兼容旧格式 `{{nodeId.field}}`。
- **文档编辑器是外部服务**：模板编辑用的是独立部署的 OnlyOffice Document Server（前端加载 `office_url` 下的 `api.js`，后端持有 `office_jwt_secret` 用于签名）。BiSheng 只提供模板文件的取/存与回调端点，**编辑器本身不在本仓库**，能做的动作受 OnlyOffice 的 API 边界限制。
- 变量占位符是**存量文档里的既有内容**，格式变更等同于一次数据格式演进：只能"新写新格式 + 老格式永久可读"，不能一刀切。

---

## 3. 方案对比与选定

### 决策 1：手动保存怎么触发

- **备选**：
  - A. 前端调后端新端点 → 后端向 OnlyOffice **Command Service** 发 `forcesave` 指令 → OnlyOffice 主动回调既有 `/report/callback` → 落 MinIO。
  - B. 前端直接调 OnlyOffice Command Service。缺点：需把 `office_jwt_secret` 暴露到浏览器，违反 C6 精神；且 OnlyOffice 常只允许内网访问。
  - C. 前端模拟 Ctrl+S / 走 OnlyOffice 插件。缺点：插件在服务端、不在本仓库，改不动；模拟按键不可靠。
- **选定**：A
- **原因**：落盘路径完全复用既有 callback（`workflow.py` 的 `/report/callback`，只认 status ∈ {2,6}，forcesave 正好是 6），**不新增第二条写 MinIO 的路径**；密钥留在后端；前端只需知道 version_key。
- **何时该重新考虑**：若将来 OnlyOffice 换成内置编辑器（不再是外部服务），整个 forcesave 机制随之作废。

### 决策 2：保存成功以什么为准（同步等落盘 vs 指令下发即成功）

- **备选**：
  - A. 指令下发成功即返回成功（落盘由 OnlyOffice 异步回调完成）。
  - B. 后端下发指令后轮询 MinIO 对象 mtime，确认落盘再返回。
- **选定**：A
- **原因**：OnlyOffice 的 forcesave 是"命令 → 异步回调"模型，回调通常在 1~2 秒内到达；为强一致而轮询会把一次点击变成秒级阻塞请求，收益不抵成本。Command Service 的返回码本身能区分"key 不存在 / 无正在编辑的会话 / 指令已受理"，足以覆盖 AC-02 的失败提示。
- **何时该重新考虑**：若线上出现"提示已保存但内容确实没落盘"的投诉，改为 B 或在前端加一次落盘确认查询。

### 决策 3：变量占位符格式（本特性的核心决策）

- **备选**：
  - A. **名称+ID 双写**：`{{显示名|nodeId.field}}`，解析时取最后一个 `|` 之后的部分作为取数键。
  - B. **纯名称寻址**：`{{节点名称.field}}`，执行期按名称反查节点。
  - C. 显示层映射：文档里仍存 ID，靠编辑器插件把 ID 渲染成名称。
- **选定**：A（★ 已与用户确认）
- **原因**：
  - B 把"节点名唯一且不改名"变成运行时的硬依赖——用户改个节点名，所有历史模板静默断链；重名则静默取错数据。PRD 写"唯一性由编排者保证"，但代价实际由用户承担，且失败形态是**静默错值**而非报错，最难排查。
  - C 需要改 OnlyOffice 服务端插件（不在本仓库、无源码），不可行。
  - A 的显示名是**插入时快照**：改名后模板显示的还是旧名（可接受的信息陈旧），但执行永远正确。
- **何时该重新考虑**：若将来引入"节点稳定别名"（用户可见、系统保证唯一且改名自动同步引用），可用别名替代 ID 出现在占位符里。

### 决策 4：兼容旧格式在哪一层做

- **备选**：
  - A. 在**取数前**做一次 key 规范化：提取仍返回原始占位符全文（替换要用它当 key），只在调 `get_other_node_variable` 前把显示名前缀剥掉。
  - B. 改 `extract_variables` 直接返回规范化 key。缺点：`replace_and_save` 用的 variables 字典 key 必须和文档里的原文一致，改了就替换不上。
  - C. 改正则 `placeholder_pattern` 分组捕获。缺点：牵动提取/替换两处正则语义，回归面大。
- **选定**：A
- **原因**：现有实现里 `workflow_variables[原始占位符] = 值`，替换阶段严格按原文匹配——**原文必须原样保留**。A 只在"拿 key 去查数"这一点插入一个纯函数，旧格式走同一函数原样返回，改动面最小、回归风险最低。
- **何时该重新考虑**：若未来占位符要支持更多元信息（如格式化指令），再考虑把解析升级成结构化 parse。

---

## 4. 系统现状（接手必读）

### 4.1 模板编辑与保存数据流

`报告节点参数项 → 打开模板编辑弹窗 → 前端挂载 OnlyOffice 编辑器 → 用户编辑 → 保存触发 → OnlyOffice 回调后端 → 落 MinIO`

- **节点参数项**：`platform/src/pages/BuildPage/flow/FlowNode/component/ReportItem.tsx` —— 存 `{ file_name, version_key }`，点「编辑报告模板」开弹窗。
- **模板编辑容器**：`.../component/ReportWordEdit.tsx` —— 新建/导入 docx、拉模板、挂 `SelectVar` 变量选择器与「插入变量」按钮。**手动保存按钮加在这里**。
- **编辑器组件**：`platform/src/pages/Report/components/Word.tsx` —— 挂 `window.DocsAPI.DocEditor`；`forcesave: true`；`callbackUrl` 工作流场景指向 `/api/v1/workflow/report/callback`；编辑器 JWT 走 `getOfficeTokenApi`。
- **取模板**：`GET /api/v1/workflow/report/file`（`api/v1/workflow.py`）——无 key 则新生成 `version_key`，有则返回 MinIO 预签名地址。
- **存模板**：`POST /api/v1/workflow/report/callback` —— 只处理 `status ∈ {2,6}`，下载 OnlyOffice 给的 URL 写入 MinIO `workflow/report/{version_key}.docx`。
- **本特性新增**：一个"触发保存"端点，入参 `version_key`，后端用 `office_jwt_secret` 签名后向 `office_url` 的 Command Service 发 `c=forcesave`；落盘仍由上面的 callback 完成。

### 4.2 变量插入与执行期解析数据流

`插入变量 → 占位符文本进文档 → 执行报告节点 → 提取占位符 → 按节点 ID 取数 → 替换 → 生成 docx`

- **插入**：`ReportWordEdit.tsx` 通过 `SelectVar` 选中变量后，把文本经 `postMessage` 交给 OnlyOffice 插件写进文档。当前传的是 `nodeId.field`；**本特性改为 `显示名|nodeId.field`**。
- **提取**：`backend/bisheng/workflow/nodes/report/docx_replace.py` —— 正则 `\{\{([^}]+)\}\}` 扫段落/表格/页眉页脚，返回**占位符原文**列表。
- **取数**：`workflow/nodes/report/report.py` 的 `_run()` 逐个调 `get_other_node_variable(占位符)` → 最终落到 `graph_state.py` 的 `get_variable_by_str()`，按 `node_id.var_key#index` 解析。**本特性在此之前插入 key 规范化**。
- **替换**：`replace_and_save(variables, ...)`，字典 key 必须是占位符原文。

### 4.3 关键数据结构 / 字段约定

| 契约 | 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| 变量占位符（新） | `{{显示名\|nodeId.field}}` | 显示名为插入时快照，仅供人读；`\|` 后为取数键，可带 `#index` | 报告节点执行期解析、用户肉眼 |
| 变量占位符（旧，永久兼容） | `{{nodeId.field}}` | 存量模板；解析行为不变 | 同上 |
| 规范化规则 | 取**最后一个** `\|` 之后的内容作为取数键；无 `\|` 则整串即键 | 用 rsplit 使得显示名中含 `\|` 也不误伤 | 后端解析 |
| 插入时的显示名清洗 | 剔除 `{`、`}`、`\|` 三类字符 | 防止用户给节点起名带这些字符导致占位符结构被破坏 | 前端插入逻辑 |
| 保存端点成功响应 | `{"saved": true}` | 前端据此判定成功；避免"空响应"与"失败被吞掉"两种情况无法区分 | platform 模板编辑弹窗 |
| 文档服务「无变更」的处理 | Command Service 返回 error=4（自上次保存后无改动）**按成功处理** | 此时存储上的模板与用户所见已一致，报错会让用户以为没保存上 | 保存端点 |

### 4.4 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `ReportWordEdit.tsx` | 模板弹窗编排：取模板、插入变量（拼显示名）、手动保存按钮 | 不直接与 OnlyOffice 通信细节耦合（走 Word.tsx / postMessage） |
| `Word.tsx` | 挂载 OnlyOffice 编辑器、配置 callbackUrl 与 JWT | 不管业务语义（工作流 vs 独立报告页由调用方传参） |
| 后端「触发保存」端点 | 校验权限 + 向 Command Service 发 forcesave | **不写 MinIO**（落盘统一走 callback） |
| `/report/callback` | 唯一的模板落盘入口 | 不区分保存是自动还是手动触发 |
| `docx_replace.py` | 占位符提取与按原文替换 | 不理解占位符语义（不做规范化） |
| `report.py` `_run()` | 编排：提取 → 规范化 key → 取数 → 替换 | 不直接查 graph_state |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `replace_and_save` 的 variables **字典 key 必须与文档中占位符原文逐字一致**——它是按原文做字符串替换的 | 一旦在提取阶段就把 key 规范化（去掉显示名），替换阶段匹配不上，报告里会残留 `{{...}}` 原文 | `report.py` 中只在"取数前"规范化，字典 key 仍用原文（决策 4） |
| 2 | 执行期取数强依赖节点 ID（`get_variable_by_str` 按 `node_id.var_key` 查 graph_state），**节点名称在运行时根本不可靠**（可重复、可被改） | 采用纯名称寻址会在用户改名后静默取空/取错，且不报错 | 格式设计（决策 3）+ INV-8 |
| 3 | 保存不是前端"提交内容"，而是**OnlyOffice 反向回调后端**；前端点保存只是"请求 OnlyOffice 去存" | 会误以为要在前端把文档内容 POST 给后端，白写一条上传链路，还和 callback 打架 | 决策 1 / 决策 2 |
| 4 | `/report/callback` 只认 `status ∈ {2,6}`，其余状态直接忽略 | 调试时看到回调进来了却没落盘，误判为存储故障 | `api/v1/workflow.py` 既有逻辑，本特性不改 |
| 5 | **旧「技能」体系的独立报告页不共用变量解析链路**：它的变量来自技能标签、格式是 `{id}_{name}`，替换走的是另一套旧实现；只有 OnlyOffice 编辑器组件（`Word.tsx`）是共用的。该入口现已关闭，属待清理的残留代码 | 会误以为改了 `docx_replace.py` 就能让它的变量也显示名称（实际毫无影响）；**反过来更危险——改 `Word.tsx` 会同时影响两边**，改动时需确认不把已关闭入口的页面改崩（虽不做新功能，但不应留下报错） | 本特性只改工作流侧包装层，`Word.tsx` 的改动保持向后兼容；见 §8 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| 「触发模板保存」端点（工作流报告模板） | HTTP API | platform 前端模板编辑弹窗 |
| 变量占位符格式 `{{显示名\|nodeId.field}}` + 旧格式兼容 | 隐式数据契约（写在 docx 里） | 报告节点执行期；受 INV-8 约束 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| OnlyOffice Document Server（`office_url` + `office_jwt_secret`） | 外部服务 + 系统配置 | 未配置/不可达时手动保存必然失败（AC-02 的失败提示即为此设计）；Command Service 需从后端网络可达 |
| OnlyOffice 编辑器插件（服务端，非本仓库） | 隐式契约：`postMessage` 的 `insetMarker` 动作把文本原样插入文档 | 若插件对插入文本做转义/截断，显示名方案会受影响，需实机验证 |
| `graph_state.get_variable_by_str` 的 `node_id.var_key#index` 解析规则 | 内部数据契约 | 该规则若变更，规范化函数需同步 |

---

## 7. 测试与可观测

- **后端单测**：key 规范化函数——新格式、旧格式、显示名含 `|`、含 `#index`、空显示名，各一例。
- **手动验证**（需 OnlyOffice 环境）：
  1. 工作流建报告节点 → 打开模板 → 插入 2 个不同节点的变量 → 肉眼确认显示节点名 → 点保存 → 关闭重开确认内容在。
  2. 运行工作流，确认生成的 docx 里变量被正确替换。
  3. 改掉其中一个节点名 → 直接运行 → 确认仍取到正确值（AC-05）。
  4. 找一个升级前建的存量模板 → 直接运行 → 确认行为不变（AC-06）。
  5. 断开/停掉 OnlyOffice → 点保存 → 确认有明确失败提示（AC-02）。
- **回归点**：`Word.tsx` 为两处报告页共用，改动后需确认旧技能报告页（入口虽已关闭，代码仍在）不因此报错。
- **日志**：触发保存端点记录 version_key 与 Command Service 返回码；callback 已有 `logger.debug(f'callback={data}')` 可对照。

---

## 8. 后续改进 / 不打算做的事

- **自动保存 bug 根因**：本特性只提供兜底手段，未修根因。根因待独立排查（怀疑与 OnlyOffice 会话/`forcesave` 配置或 callback 失败静默有关）。
- **旧「技能」体系的独立报告页**：入口已关闭，其变量机制是另一套遗留实现（`{id}_{name}` 标签）。本特性**不为其新增任何能力**，也不统一两套机制——该页面属于待删除的残留代码，正确的后续动作是**连同技能报告链路一起清理**（另立清理任务），而不是为它做兼容投入。
- **显示名与改名同步**：需要引入引用登记或稳定别名，成本远超本次收益，暂不做。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-07-24 | 初版 | 特性设计 |
