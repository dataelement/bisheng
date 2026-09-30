# Tasks: 工作台日常模式引用改用短句柄

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.0.0-beta1（发版线 `feat/3.0.0-beta2`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-09-30 用户确认（直接迁移、无开关无过渡期） |
| design.md | ✅ 已评审 | 2026-09-30 用户确认 |
| tasks.md | ✅ 已拆解 | |
| 实现 | 🟡 进行中 | 17 / 18 完成（T018 的 test 环境验收待合并部署） |

---

## Tasks

### Wave 1：citation 共用件（Test-First）

- [x] **T001**: 流式转换器测试
  **文件**: `src/backend/test/citation/test_handle_stream_converter.py`
  **测试**: 文法表（单组、多组、逗号 / 顿号、链接标签、围栏与行内代码、定义行、未知编号保留）；模型自写私有区标记（含 `\\ue200` 转义形态）丢弃并计数；任意切块结果 == 整段 `convert_handles_to_markers`（去旧标记后）；尾巴超过 64 字符按字面下发；`flush` 吐出剩余
  **覆盖 AC**: AC-05, AC-07, AC-08, AC-09, AC-10
  **依赖**: 无

- [x] **T002**: `HandleStreamConverter` 实现
  **文件**: `src/backend/bisheng/citation/domain/services/citation_handle_service.py`
  **逻辑**: design §3 决策 2
  **测试**: T001 通过
  **依赖**: T001

- [x] **T003**: 日常规则与旧段替换测试
  **文件**: `src/backend/test/citation/test_daily_handle_rules.py`
  **测试**: 三语默认模板（取自 platform locale 的 `systemPrompt2`）替换后无 `<chunk_id>` / 私有区字符 / 旧小节，`{cur_date}` 与"其他信息"小节保留，其余段落不变；无标题但含旧格式 → 追加；什么都没有 → 追加；幂等
  **覆盖 AC**: AC-02, AC-03
  **依赖**: 无

- [x] **T004**: `daily_handle_rules` + `replace_legacy_citation_rules` + `ensure_daily_handle_rules`
  **文件**: `core/prompts/yaml/citation_handles.yaml`、`citation_handle_service.py`
  **逻辑**: design §3 决策 4
  **依赖**: T003

- [x] **T005**: 历史反向映射测试 + 实现 `markers_to_handles`
  **文件**: `test/citation/test_markers_to_handles.py`、`citation_handle_service.py`
  **逻辑**: 标记内每个 key 按 `key → handle` 写回 `[Sn]`（多来源写成 `[S3][S7]`）；映射不到的 key 丢弃，整组都映射不到则整段标记去掉
  **覆盖 AC**: AC-11
  **依赖**: 无

- [x] **T006**: 编号共用件上移 + `pins_contract`
  **文件**: `citation_handle_service.py`（`swap_chunk_id_for_handle`、`rewrite_web_results_with_handles`、`assign_handles` 读 `pins_contract`）、`linsight_citation_scope.py`（`pins_contract = True`）、`tool/domain/langchain/linsight_knowledge.py`、`linsight/domain/services/agent_factory.py`（改调上移后的函数）
  **测试**: 新增 `pins_contract=False` 建表不写 `meta:enabled`；`test/linsight` 全部通过
  **覆盖 AC**: AC-01
  **依赖**: 无

### Wave 2：日常模式接线

- [x] **T007**: `DailyCitationScope`
  **文件**: `src/backend/bisheng/citation/domain/services/daily_citation_scope.py`
  **逻辑**: 鸭子类型满足 `assign_handles`；`load()` 水化；本轮统计 seen / unknown / legacy；`pins_contract = False`
  **依赖**: T006

- [x] **T008**: 工具换编号 + 失败剥 key
  **文件**: `workstation/domain/services/chat_service.py`（知识库工具 `_format_chunk` 路径、`DailyChatCitationToolWrapper` 知识库与联网分支）
  **逻辑**: design §3 决策 1、决策 6
  **覆盖 AC**: AC-01, AC-17
  **依赖**: T006, T007

- [x] **T009**: 流式转换接线
  **文件**: `chat_service.py`（agent 分支 `astream_events` 与无工具分支 `astream`）
  **逻辑**: 文本先经转换器再进 `final_msg` / `events` / SSE / scanner；`on_tool_start`、流结束、中断时 `flush`
  **覆盖 AC**: AC-05, AC-06, AC-18
  **依赖**: T002, T007

- [x] **T010**: 完成与中断落库 + 审计日志
  **文件**: `chat_service.py`
  **逻辑**: design §3 决策 3；日志 `[daily-citation-audit]`
  **覆盖 AC**: AC-12, AC-13, AC-14
  **依赖**: T009

- [x] **T011**: 系统提示词接线
  **文件**: `chat_service.py`
  **逻辑**: 去掉 `ensure_citation_rules`，改 `replace_legacy_citation_rules` + `ensure_daily_handle_rules`
  **覆盖 AC**: AC-02, AC-03
  **依赖**: T004

- [x] **T012**: 历史回放接线
  **文件**: `workstation/domain/services/workstation_service.py`（历史构造）、`chat_service.py`（scope 先 load 再构造历史）
  **覆盖 AC**: AC-11
  **依赖**: T005, T007

- [x] **T013**: 识图路径剥编号
  **文件**: `common/image_view/react_loop.py`
  **覆盖 AC**: AC-19
  **依赖**: 无

- [x] **T014**: 会话导出剥未识别编号
  **文件**: `workstation/domain/services/conversation_export_service.py`
  **覆盖 AC**: AC-15
  **依赖**: 无

- [x] **T015**: 日常模式链路测试（新增 + 改写既有）
  **文件**: `test/workstation/test_daily_chat_citation_handles.py`（新）；改写 `test_daily_chat_citation_backstop.py`、`test_stream_interrupt_persist.py` 等受影响用例
  **覆盖 AC**: AC-01, AC-05, AC-06, AC-11, AC-12, AC-13, AC-14, AC-17
  **依赖**: T008～T014

### Wave 3：前端

- [x] **T016**: 三语默认模板
  **文件**: `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json` 的 `chatConfig.systemPrompt2`
  **覆盖 AC**: AC-04
  **依赖**: T004

- [x] **T017**: 日常模式复制剥未识别编号
  **文件**: client `AiMessageBubble.tsx`、`AiChatMessages.tsx`、`ChatView.tsx`、`ShareView.tsx`
  **验证**: jest 覆盖复制文本；知识空间 / 频道不传 prop 行为不变
  **覆盖 AC**: AC-15, AC-20
  **依赖**: 无

### Wave 4：回归与验收

- [ ] **T018**: 回归 + test 环境验收
  **逻辑**: `test/citation`、`test/linsight`、`test/workstation`、`test/knowledge` 引用相关、`test/channel` 全跑（F054 非回归用例不变）；client lint / typecheck / jest；部署 test 按 design §7 手动验证与 116 对比
  **覆盖 AC**: AC-16, AC-20
  **依赖**: 全部

---

## 实际偏差记录

- T002 / T004 / T005 → 日常专用件放新模块 `daily_citation_handles.py`，编排放 `workstation/.../daily_citation.py`（design §4.3）
- T016 → en / ja 模板用本语言标题，运行时判重识别三种标题（design §3 决策 4）
- T015 → `test_stream_interrupt_persist.py`、`test_daily_chat_citation_backstop.py` 在本 Feature 之前就因 `image_view_configured` 查库而失败（fixture 未 mock），本次在 fixture 里补 mock 后恢复为真实运行；`test_citation_prompt_rules.py` 的默认模板用例收窄到 `aiPrompt`
- T017 → 复制按钮从 `AiMessageBubble.tsx`（837 行）抽成 `MessageCopyButton.tsx`
- 代码审查（5 路）修复：末尾 flush 移入 try（design §5 #11）、识图剥编号改落日常专用出口（#8）、导出只剥回答、编号指向最新 key（#12）、规则加载失败记日志、`load()` 容错、三处注释订正
- T018 回归：`test/citation`、`test/linsight`、`test/workstation`、`test/channel`、`test/common`、`test/tool`、知识空间对话引用用例共 2190 通过；剩余 15 个失败在基线提交 9ca1e6ea3 上同样失败（本地 config 开了多租户 / 需真实 MySQL），与本 Feature 无关
