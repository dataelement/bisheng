# Tasks: 全问答入口统一溯源角标（F054）

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md) · **调研**: [discovery.md](./discovery.md)
**版本**: v3.0.0-beta1
**分支**: `feat/3.0.0-beta1-054-unified-citation-entries`

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| discovery.md | ✅ 已裁定 | 三个口径 + 临时文件两条裁定，用户 2026-09-07 确认 |
| spec.md | ✅ 已评审 | 用户 2026-09-07 确认；导出改为「维持现状」后 AC 重编号 |
| design.md | ✅ 已评审 | 用户 2026-09-07 确认；六个决策，接手时的第一入口 |
| tasks.md | ✅ 已拆解 | 14 个任务 / 5 个 Wave；22 条 AC 全部有测试或手动验证覆盖 |
| 实现 | 🔲 未开始 | 0 / 14 完成。偏差处理见 `docs/SDD-Guide.md` §3-§4 |

---

## 开发模式

- **后端 Test-First**：测试任务在实现任务之前，实现任务的「测试」字段写明要转绿的测试。
- **前端手动验证**：每个前端任务附可操作的验证步骤（design §7 有完整的七步手动验证清单）。
- **中间件 / DM8 / e2e 在 CI 跑**，不依赖本地。
- **前端只涉及 Client 分区**（`src/frontend/client/`）；**Platform 分区本期一行不改**（discovery §4.3 裁定），无 Platform 任务。
- **非侵入回归测试前置**：T002 必须在任何实现任务之前写完并转绿——它捕获的是**改造前**的行为基线；改完再写就只是把改后的行为抄一遍，证明不了「没回归」。
- **自包含**：任务内联文件与逻辑；**为什么这么做指向 design §3 的决策编号，不复制论证**。

---

## Tasks

### Wave 1 — 无依赖，可并行（含基础设施与基线）

- [ ] **T001**: 新增 `article` 来源类型与载荷 schema
  **文件**: `src/backend/bisheng/citation/domain/schemas/citation_schema.py`
  **逻辑**: `CitationType` 增加 `ARTICLE = "article"`；新增 `ArticleCitationItemSchema` 与 `ArticleCitationPayloadSchema`（字段形状见 design §4.2）；`CitationSourcePayload` 联合类型扩为三种。**不改** `message_citation` 表结构（`citation_type` 已是 `varchar(32)`）——**无 DDL、无 Alembic，因而无需回滚方案**。
  **设计依据**: design §3 决策 2
  **依赖**: 无

- [ ] **T002**: 非侵入回归**基线**测试（先写、先绿）
  **文件**: `src/backend/test/citation/test_f054_non_regression.py`
  **逻辑**: 在**改造前**的代码上写并跑绿，锁死四条不变量：①**导出维持现状**——含角标的会话导出后，导出件里搜不到角标、编号、参考资料段与隐藏字符（本期 AC-07 的守护点，防止被顺手改成烘焙）；②已上线四个入口（工作流 / 日常模式 / 助手 / 知识空间）的溯源行为逐项不变；③内部引用键与协议标记在复制、导出、分享等状态下均不可见；④重新生成的答案产生自己的溯源、不沿用旧绑定（入口存在时）。**实现全部完成后必须再跑一次，仍须全绿**（T014 负责重跑）。
  **覆盖 AC**: AC-07, AC-12, AC-18, AC-21, AC-22
  **依赖**: 无

- [ ] **T003**: 解析服务单测 —— 匿名收紧 + 未解析原因
  **文件**: `src/backend/test/citation/test_resolve_anonymous_and_reason.py`
  **逻辑**: 覆盖 design §3 决策 5 的四条判定顺序各一例；**匿名回归**：`per_user` 与 `shared` 两档知识库来源都不得返回、文章来源不得返回、**网页来源仍返回**；**INV-7 不回归**：已登录用户的两档语义与改造前逐字段一致。
  **覆盖 AC**: AC-08, AC-09, AC-10, AC-13, AC-14
  **依赖**: 无

- [ ] **T004**: 工作流临时文件关断单测
  **文件**: `src/backend/test/workflow/test_temp_file_no_citation.py`
  **逻辑**: 构造临时文件检索工具 → 断言不产生任何来源登记；同一轮里真实知识库来源仍正常登记；护栏用例：喂一个「文档标识非整数」的文档给来源登记环节，断言被跳过。
  **覆盖 AC**: AC-16, AC-17
  **依赖**: 无

- [ ] **T005**: 溯源文案 i18n
  **文件**: `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`
  **逻辑**: 在既有 `com_citation.*` 命名空间下新增 `no_permission`（「暂无权限查看该来源」，对齐 AC-09 的完整文案）与 `source_expired`（「来源已失效」）。三语同 PR 交付；组件接线在 T013。
  **落点变更**（实现期发现）：`packages/locales` 目前只承载 `api_errors` 域，且其 README 明确「错误码文案才放这里」；角标文案是 UI 文案、且只有 Client 消费，故放 client 应用自身的语言文件。迁移新域需要改 `scripts/build.mjs` 的 TARGETS，超出本任务范围。
  **覆盖 AC**: AC-11
  **依赖**: 无

### Wave 2 — 依赖 Wave 1

- [ ] **T006**: 解析服务实现 —— 匿名收紧 + 未解析原因判定
  **文件**: `src/backend/bisheng/citation/domain/services/citation_resolve_service.py`
  **逻辑**: 在 `_permitted_file_ids` / `_apply_tier_filter` **之前**加匿名分支：无登录用户时知识库与文章来源一律不返回（含 `shared` 档），网页来源放行；按决策 5 的安全序产出每条未解析来源的原因。**已登录用户的两档语义一个字不改。**
  **跨 Feature 影响**: 该文件是 F029 拥有的 citation 链路（release-contract 表 1 已登记 F054 的扩展权）；改动只加匿名分支，不触碰 F041 的 `accessScope` 两档语义。
  **设计依据**: design §3 决策 5 · §5 坑 4（本 Feature 最容易漏的地方）
  **同步改写既有用例**（用户 2026-09-07 选 A）：`test/citation/test_citation_resolve_visibility.py` 的 `test_filter_visible_rag_items_anonymous_caller_preserves_all` 与 `test_resolve_citation_anonymous_caller_passthrough`、`test/citation/test_access_scope_tiering.py` 中断言匿名保留全部的那条，全部改写为新预期，并在用例 docstring 注明「F054 覆盖 F029 AC-20」。
  **测试**: T003 全绿，改写后的三个既有用例全绿，且 T002 仍全绿
  **覆盖 AC**: AC-08, AC-09, AC-10, AC-13, AC-14
  **依赖**: T002, T003

- [ ] **T007**: 注册服务支持文章来源 + 非整数标识护栏
  **文件**: `src/backend/bisheng/citation/domain/services/citation_registry_service.py`, `citation_prompt_helper.py`
  **逻辑**: 新增文章来源标识生成（前缀 `articlesearch_`）、载荷构建与序列化；新增「给文章内容打标 + 收集 registry item」的 helper，形态对齐现有的知识库 / 网页两条。**护栏**：`_is_citable_rag_document` 增加「文档标识非整数则不视为可引用」的判断（决策 6 的 B 层）。
  **跨 Feature 影响**: 同 T006，属 F029 链路的扩展；不改既有两类来源的构建逻辑。
  **设计依据**: design §3 决策 2 / 决策 6
  **依赖**: T001

- [ ] **T008**: 工作流临时文件关断实现
  **文件**: `src/backend/bisheng/tool/domain/services/executor.py`（临时工具打标）, `src/backend/bisheng/workflow/nodes/agent/agent.py`（`WorkflowCitationToolWrapper.wrap` 分派处跳过）
  **逻辑**: 临时文件检索工具创建时带一个「临时来源」标记；Agent 节点包装工具时遇到该标记直接不包装 → 不登记来源。**不改临时文件的召回与答案内容。**
  **跨 Feature 影响**: `executor.py` 是所有工具的共享创建入口——只给临时文件那条分支加标记位，其余工具的创建路径不变。
  **设计依据**: design §3 决策 6 · §5 坑 5
  **测试**: T004 全绿
  **覆盖 AC**: AC-16, AC-17
  **依赖**: T004, T007

### Wave 3 — 依赖 Wave 2

- [ ] **T009**: 频道文章问答溯源编排单测
  **文件**: `src/backend/test/channel/test_article_chat_citation.py`
  **逻辑**: mock 文章与模型输出 → 断言：登记一条文章来源、载荷带**真实稳定的文章标识与原文链接**且**不含伪造的知识库片段标识**；系统提示词**被追加**引用规则且重复调用不重复追加；**答案无标记时一条来源都不写**（决策 4 的回归点）；重复处理同一条回答不产生重复行；**登记异常时回退为不带溯源并继续作答**。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-06, AC-19
  **依赖**: T007

- [ ] **T010**: 频道文章问答溯源实现 + 端点瘦身
  **文件**: `src/backend/bisheng/channel/domain/services/channel_chat_service.py`（新增编排）, `src/backend/bisheng/channel/api/endpoints/channel_chat.py`（下沉，不新增编排）
  **逻辑**: 敏感内容准入校验**之后**登记文章来源并写运行时缓存；系统提示词尾部幂等追加引用规则（首次真正调用 `prompt_has_citation_rules`）；「参考资料」块携带来源标识；答案落库前**严格过滤**（只留答案里出现的，不用「无标记则全存」的兜底）+ 清除未注册标记；把来源绑到答案消息。
  **设计依据**: design §3 决策 1 / 3 / 4 · §4.3（编排必须落 Service）· §5 坑 1、坑 3
  **测试**: T009 全绿
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-06, AC-19
  **依赖**: T007, T009

- [ ] **T011**: 解析端点响应追加未解析清单
  **文件**: `src/backend/bisheng/citation/api/endpoints/citation.py`, `citation_schema.py`
  **逻辑**: `ResolveCitationResponse` 追加 `unresolved` 字段（形状见 design §4.2），`items` 语义与顺序不变；单条详情端点的 404 响应体携带同一个 `reason`。**不新增对外 API、不新增错误码段。**
  **测试**: T003 断言响应形状
  **覆盖 AC**: AC-08, AC-09, AC-10
  **依赖**: T006

### Wave 4 — 前端 Client（Platform 不涉及）

- [ ] **T012**: Client 识别文章来源并落地点击行为
  **文件**: `src/frontend/client/src/components/Chat/Messages/Content/citationUtils.ts`（`normalizeCitationType` 扩展第三种类型）, `CitationSourceIcon.tsx`, `Markdown.tsx`
  **逻辑**: 新前缀映射为文章类型（**不扩展就会被当成知识库来源，点开空白页**）；文章角标显示来源类型 / 标题 / 摘录；点击**打开原文链接（新标签）**。角标形态复用公共组件库的「文档」色，**不新增来源色**（视觉归设计师）。
  **设计依据**: design §5 坑 2、坑 6、坑 7 · §2 组件所有权约束
  **覆盖 AC**: AC-04, AC-05
  **手动验证**: 按 design §7 步骤 1-3 起前后端 → 文章页侧边问答提一个能命中文章内容的问题 → 角标出现 → 悬浮看标题 / 摘录 → 点击开原文新标签。
  **依赖**: T010, T011

- [ ] **T013**: Client 区分「来源已失效」与「暂无权限」
  **文件**: `src/frontend/client/src/components/Chat/Messages/Content/Markdown.tsx`, `citationUtils.ts`, `chatApi.ts`
  **逻辑**: 消费 `unresolved` 的原因字段，渲染两种**不可点**状态且文案可区分；历史消息缺结构化溯源数据时原样保留答案、不补造角标；分享页解析不到时降级为不可点，**不报错、不使页面渲染失败**。文案取自 T005 的 key。
  **覆盖 AC**: AC-08, AC-09, AC-11, AC-15, AC-20
  **手动验证**: 无痕窗口打开含角标的分享页 → 知识库与文章角标全为「暂无权限」、网页角标仍可点、页面不报错。
  **依赖**: T005, T011

### Wave 5 — 验收与落档

- [ ] **T014**: 回归重跑 + 端到端手动验证 + 落档
  **文件**: 本文件「实际偏差记录」段
  **逻辑**: ①**重跑 T002 基线测试，必须仍全绿**（这才是「没回归」的证明）；②按 design §7 的七步清单走一遍（含工作流临时文件不出角标、匿名分享页全灰两项）；③把实现期发现的、**改变了系统认知**的偏差回写 design（决策或坑），此处只留一行指针。
  **依赖**: T012, T013, T008

---

## 实际偏差记录

> **只留一行指针**，论证写进 design.md（决策 / 坑），这里不重复。
> 推翻已 ★ 确认的决策时，先停下与用户重新确认，再记录。

- T005 落点由 `packages/locales` 改为 client 应用语言文件 → 该包只承载错误码域，角标属 UI 文案（详见 T005 内说明）。
- T006 推翻 F029 AC-20（匿名放行为分享链接有意保留）→ 用户 2026-09-07 选 A：直接覆盖，已登记 release-contract 表 4 + design §6.1，三个既有用例随 T006 改写。
