# Tasks: 报告节点优化（手动保存 + 变量显示节点名称）

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md)
**版本**: v3.0.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户已确认；design 阶段实测后删除 AC-07（技能报告页移出范围） |
| design.md | ✅ 已评审 | 用户已确认；接手时第一入口 |
| tasks.md | ✅ 已拆解 | — |
| 实现 | 🟡 代码完成待验证 | 7 / 7 完成（T007 待人工在有 OnlyOffice 的环境验证） |

---

## 开发模式

- 后端可测部分（key 规范化）走 Test-First；OnlyOffice 交互部分无法在无中间件环境自动化 → **测试降级：手动验证**。
- 前端手动验证（Playwright 🚧 未落地）。
- 自包含任务：文件、逻辑、AC 内联；设计论证指向 design §X，不复制。

---

## Tasks

### Wave 1 — 后端：变量解析兼容（可与 Wave 2 并行）

- [x] **T001**: 占位符 key 规范化函数 + 单元测试
  **文件**: `src/backend/bisheng/workflow/nodes/report/docx_replace.py`（新增模块级纯函数）
  `src/backend/test/workflow/test_report_placeholder.py`（新建，测试目录按模块分）
  **逻辑**: 纯函数 `normalize_placeholder_key(raw: str) -> str`——取**最后一个** `|` 之后的内容作为取数键；无 `|` 则整串返回（旧格式）。见 design §3 决策 4、§4.2。
  **测试**: 新格式 `报告生成\|node_a.output` → `node_a.output`；旧格式 `node_a.output` → 原样；显示名含 `|`（`a\|b\|node_a.output` → `node_a.output`）；带数组下标 `名称\|node_a.out#0` → `node_a.out#0`；空显示名 `\|node_a.out` → `node_a.out`
  **覆盖 AC**: AC-04, AC-05, AC-06
  **依赖**: 无

- [x] **T002**: 报告节点执行期接入规范化
  **文件**: `src/backend/bisheng/workflow/nodes/report/report.py`（`_run()` 内）
  **逻辑**: 调 `get_other_node_variable()` 前对占位符做一次 `normalize_placeholder_key`；**`workflow_variables` 字典 key 仍用占位符原文**（替换按原文匹配，改了会残留 `{{...}}`——design §5 坑 1）
  **测试**: T001 通过 + 手动跑一次含新旧两种占位符的工作流
  **覆盖 AC**: AC-04, AC-05, AC-06
  **依赖**: T001

### Wave 2 — 后端：手动保存端点

- [x] **T003**: 「触发模板保存」端点
  **文件**: `src/backend/bisheng/api/v1/workflow.py`（与 `/report/file`、`/report/callback` 同级新增）
  **逻辑**: 入参 `version_key`；校验用户对该 workflow 有编辑权限（复用同文件既有 `ApplicationPermissionService` 校验写法）；用 `office_jwt_secret` 签名后向 `office_url` 的 Command Service 发 `c=forcesave`、`key=version_key`；按其返回码判定「指令已受理 / key 无效 / 无编辑会话 / 服务不可达」并返回。**不写 MinIO**（落盘走既有 callback）——design §3 决策 1、决策 2
  **约束**: 不新增错误码，失败以既有响应包装返回可读信息
  **覆盖 AC**: AC-01, AC-02
  **测试降级**: 手动验证 —— 该端点的核心行为是"与外部 OnlyOffice Command Service 交互并等待其反向回调"，自动化需同时起 OnlyOffice + MinIO + 可回调的公网地址，成本远超收益；本地仅保证参数/签名构造正确
  **手动验证**: OnlyOffice 正常时调用 → 观察 callback 日志出现 status=6 且 MinIO 对象 mtime 更新；停掉 OnlyOffice 再调 → 返回明确失败
  **依赖**: 无

### Wave 3 — 前端：插入变量带显示名 + 保存按钮

- [x] **T004**: 插入变量拼显示名
  **文件**: `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/ReportWordEdit.tsx`
  **逻辑**: 插入时把当前拼装的 `节点ID.字段` 改为 `显示名|节点ID.字段`；显示名取自变量选择器给出的节点名，插入前**清洗掉 `{`、`}`、`|` 三类字符**（design §4.2）；节点名为空时退化为不带前缀的旧格式
  **覆盖 AC**: AC-03
  **手动验证**: 工作流报告节点 → 插入 2 个不同节点的变量 → 文档中肉眼可见节点名
  **依赖**: 无

- [x] **T005**: 手动保存按钮
  **文件**: `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/ReportWordEdit.tsx`
  `src/frontend/platform/src/controllers/API/workflow.ts`（新增请求方法）
  **逻辑**: 在「插入变量」右侧加保存按钮 → 调 T003 端点 → 成功 toast「保存成功」、失败 toast 明确原因；请求期间按钮 loading 且禁用重复点击。走 platform 的请求封装（禁止直接 import axios）
  **覆盖 AC**: AC-01, AC-02
  **手动验证**: 编辑模板 → 点保存 → 关闭重开确认内容还在；断开 OnlyOffice → 点保存 → 有失败提示
  **依赖**: T003

- [x] **T006**: i18n 文案
  **文件**: `src/frontend/platform/src/locales/{en,zh,ja}/*`（按 platform 现有 locale 结构）
  **逻辑**: 新增保存按钮文案、保存成功/失败提示，三语齐全
  **依赖**: T005

### Wave 4 — 回归

- [x] **T007**: 编辑器组件共用回归确认
  **文件**: 仅验证，不改代码（涉及 `src/frontend/platform/src/pages/Report/components/Word.tsx`）
  **逻辑**: `Word.tsx` 被工作流报告与旧技能报告页共用（design §5 坑 5）。确认本次改动未触及该组件的公共行为；若 T005 需改动它，则须验证旧技能报告页（入口虽已关闭，路由代码仍在）不报错
  **手动验证**: 直接访问旧报告页路由，确认页面不白屏、控制台无新增报错
  **依赖**: T005

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已 ★ 确认的决策时先停下重新确认。

- 分支名改用扁平形式 `feat/3.0.0-beta1-043-report-node`：SDD 约定的 `feat/<version>/{NNN}-{name}` 与已存在的 `feat/3.0.0-beta1` 分支产生 git ref 层级冲突；仓库历史（如 `feat/2.5.0-sg-048-portal-hot-search`）本就是扁平命名
- T003 新增「文档服务返回"无变更"视为保存成功」→ 见 design §4.2（纯实现细节，未推翻决策）
- T006 实际文案位置为 `public/locales/{zh-Hans,en-US,ja}/bs.json`（tasks 原写 `src/locales/{en,zh,ja}`，与仓库实际结构不符）
- T007 未改动共用的 `Word.tsx`，共用组件回归风险从结构上消除；旧技能报告页路由的人工点检仍建议在联调环境顺手做一次
