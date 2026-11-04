# F112 L1 任务审查

日期：2026-10-27。主 agent 自审，不是独立 agent 审查。按 task-review 的 7 项检查和各任务类型适用子集执行；逐项文件范围取 tasks.md 对应声明，机械生成物仍归原任务。

PASS=P，N/A=—。列顺序：架构、命名、序列化、数据库、前端、信息泄漏、设计同步。未新增 Worker；原 tenant headers 与 ContextVar 合同不变。Client 规则以根 AGENTS 的 Recoil/原 API 封装为准，未引入状态库。

| 任务 | 架构 | 命名 | 序列化 | 数据库 | 前端 | 信息泄漏 | 设计同步 | 文件/配对/依赖 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| T001 | P | P | — | P | — | P | P | PASS / N/A / PASS | LargeText nullable；保留原模型和 DAO |
| T002 | P | P | — | — | — | P | P | PASS / N/A / PASS | 16233 无冲突；不回显正文 |
| T003 | P | P | — | P | — | P | P | PASS / N/A / PASS | 幂等 DDL/旧 NULL/单 head |
| T004 | — | P | — | — | — | — | — | PASS / N/A / PASS | test_release_notes.py |
| T005 | P | P | — | P | — | P | P | PASS / PASS / PASS | T004 先完成；校验在副作用前 |
| T006 | — | P | — | — | — | — | — | PASS / N/A / PASS | test_release_notes_api.py + 旧 limits case |
| T007 | P | P | P | — | — | P | P | PASS / PASS / PASS | T006 先完成；仅 form/能力响应 |
| T008 | — | P | — | — | — | — | — | PASS / N/A / PASS | test_release_notes_snapshots.py |
| T009 | P | P | P | P | — | P | P | PASS / PASS / PASS | T008 先完成；只在原 INSERT 和映射复制 |
| T010 | P | P | P | — | — | P | P | PASS / PASS / PASS | T008 先完成；两个原快照复制 |
| T011 | — | P | — | — | — | — | — | PASS / N/A / PASS | CLI 测试文件：33 passed |
| T012 | P | P | — | — | — | P | P | PASS / PASS / PASS | T011 先完成；互斥/文件/三语言 |
| T013 | P | P | — | — | — | P | P | PASS / PASS / PASS | T011 先完成；严格能力与冻结重传 |
| T014 | P | P | — | — | — | P | P | PASS / PASS / PASS | 16233→exit 6；T011 错误路径 |
| T015 | P | P | — | — | — | P | P | PASS / N/A / PASS | 三语言 key parity |
| T016 | P | P | — | — | — | P | P | PASS / N/A / PASS | 生成器 --check |
| T017 | — | P | P | — | P | P | P | PASS / PASS / PASS | 可选字段；兼容旧 backend |
| T018 | — | P | — | — | P | — | — | PASS / N/A / PASS | 两个组件 4 passed |
| T019 | — | P | — | — | P | P | P | PASS / PASS / PASS | T018 先完成；1440/500px 组件预览 |
| T020 | — | P | — | — | P | P | P | PASS / PASS / PASS | 三语言 key parity |
| T021 | — | P | — | — | P | P | P | PASS / PASS / PASS | 三语言 key parity |
| T022 | — | P | — | — | P | — | — | PASS / N/A / PASS | 审批组件 12 passed |
| T023 | — | P | — | — | P | P | P | PASS / PASS / PASS | T022 先完成；仅 detail_snapshot |
| T024 | — | P | — | — | P | P | P | PASS / PASS / PASS | 三语言 key parity |
| T025 | — | P | — | — | P | P | P | PASS / PASS / PASS | 三语言 key parity |
| T026 | P | P | — | — | — | P | P | PASS / N/A / PASS | 源码/元数据 3.0.0.post1，无依赖升级 |
| T030 | P | P | — | — | — | P | P | PASS / N/A / PASS | post 默认兼容基线；显式/默认两项测试 |
| T027 | — | P | — | — | — | — | — | PASS / N/A / PASS | wheel 真实下载/独立安装/源码摘要一致 |

所有已勾选任务均 PASS。检查结果为适用范围判断，不代表不适用列执行了检查。T028 真实 E2E 未完成；T029 等待其证据后正式 L2。

## 实施中处理的事项

- 打包脚本 post 发行默认兼容基线必须在 CI 无参数重建时仍为 3.0.0；新增默认和显式参数测试，已回写 design §5、§7.3。
- 实际 500px 浏览器预览发现表格 min-width 导致说明长行需要横向滚动，已只限制新增正文的窄屏宽度，复查全文可读；未更改组件库。
- T006 同步修改旧 limits 断言；T026 的 uv.lock 项目版本及 T027 wheel/manifest 属于机械派生物。
- 生成产物由既有生成器/打包脚本输出；未修改原 SDK 安装件。
