# F083 专家问答 · 最终验收测试用例

| 项 | 内容 |
|---|---|
| 主模块 | `qa_expert`（毕昇写模型）+ 门户 ExpertQA 页 |
| 预言机 | `prd.md` + `spec.md` AC + `design.md` |
| 目标分支 | `feat/v2.6.0/083-expert-qa-enhancement`（HEAD `6876c6e5c`） |
| 基线 | 需求/技术方案已确认；本文件用于交付测试工程师前的开发侧验收执行 |
| 环境 | 171 MySQL（`config.yaml`）；门户 `:5173` + BFF `:8010` + 毕昇 `:7860`。**DM8 本机 macOS 不跑** |
| 数据前缀 | API 流转 `df-flow-`；UI `uitest-f083-` |
| 本轮动作 | **只输出用例，未执行回归**。不得把下列自动化路径当成已通过 |

**涉及数据表**（无本验收 DDL）：`qa_question` `qa_question_invite` `qa_answer` `qa_answer_adopt` `qa_answer_eligibility` `qa_comment` `qa_expert` `qa_anonymous_alias` `qa_publish_request` `qa_publish_approver` 读写；`inbox_message` 通知写；`knowledgefile` / 知识空间权限旁路读；积分表仅 F070 挂钩旁路（本 Feature 不写账本）。

---

## 1. 需求追踪（摘要）

- **新增**：定向/公开、三态、首答锁、资格快照、匿名别名、转公开审批、专家软停用、inbox 通知、关联文档 ID 对齐。
- **必须兼容**：存量题默认 `public`；列表 `status=3/4` 仍是「我的/邀请我的」；F070 采纳只调用不夺写。
- **明确不做**：已关闭态、硬删匿名化、改投票/专家分、门户自建问答表、把门户管理员写成 `is_global_super`。
- AC-01～AC-48（含反向 AC-37～40）均需有对应用例；描述不清处按 spec 执行，不按旧 Portal 习惯推断。

---

## 2. 跨模块影响

| 改动点 | 受影响模块 | 依赖方式 | 风险 | 优先级 | 现有覆盖 | 本验收 |
|---|---|---|---|---|---|---|
| 可见性/资格 | 门户列表/详情、搜索、类似问题、通知深链 | 同一套服务端规则 | 定向标题泄露 | P0 | DF-03、API 18301 | AT-V* |
| `related_docs` | knowledge 权限、门户选择树/详情 | 消费 F059 entry id | 「文档不存在」误报 | P0 | DF-04、related_docs 测 | AT-D* |
| 采纳 | F070 积分挂钩 | 只调用 | 本域误写账本 | P0 | adopt 测 mock hook | AT-A16 断言不写 `user_point_log` |
| 转公开 | 审批展示、inbox、Celery 过期 | 业务表为准 | 漏通知、匿名露真名 | P0 | DF-13/21/22、inbox 部分 | AT-P* / AT-N* |
| 专家停用 | 回答资格、审批默认同意 | 软停用 | 硬删、恢复误入旧申请 | P0 | DF-11 | AT-E* |
| 时间 | 门户解析、过期任务 | 东八墙钟 | 截止时间错一天 | P1 | beijing_time / DF 墙钟 | AT-T* |
| 身份表面 | 列表/详情/审批/通知 | `mask_identity` | 只做详情 | P0 | DF-16/17/22/26 | AT-I* 按表面 |

判断无影响须有表/接口证据。积分账本、投票公式：spec 排除，回归抽查「未改」。

---

## 3. 测试设计清单（适用性）

| 类 | 结论 |
|---|---|
| 业务与状态 | **适用**：三态、锁、转公开状态机、非法迁移 |
| 输入与契约 | **适用**：邀请人数、duration 1/3/7、图片上限、183xx |
| 身份权限租户 | **适用**：未登录、路人、受邀、管理员、超管；跨租户本版默认单租户，标未验证若未开 multi_tenant |
| 数据一致性 | **适用**：计数、锁、快照、级联删评、失败无脏行 |
| 跨模块异步 | **适用**：inbox、Beat 过期、F070 hook |
| 文件/搜索 | **适用**：关联文档；MinIO 资源持久化走 054 旁路，本验收不替代 054 |
| 数据库兼容 | **适用 MySQL**；**DM8 未验证**（darwin 无驱动） |
| 安全 | **适用**：脱敏、越权、禁止「文档不存在」冒充无权限 |
| 性能 | **不适用门槛**；仅并发锁 P0，不发明 P99 |

---

## 4. 角色

| 代码 | 含义 |
|---|---|
| guest | 未登录 |
| asker | 提问者 |
| stranger | 已登录路人 |
| expertInvited | 有效且被邀 |
| expertOther | 有效未邀 |
| expertDisabled | 已停用专家 |
| expertAdmin | 门户专家库管理员 |
| superAdmin | 平台超管 |

一条用例必须：**调接口（身份明确）→ 断言 HTTP/183xx → SELECT 落库（写库时）→ 再打一枪**。UI 条另加页面断言。失败：拒绝且目标表无脏行。

---

## 5. 用例矩阵

层级：`flow` = 171 真库流转；`api` = TestClient；`unit` = 规则/mock；`ui` = Playwright 或手工；`task` = Celery。

### 5.1 登录、三态、筛选（AC-01/02/03/37/41）

| ID | AC | 层 | P | 角色 | 步骤 | HTTP/UI | 落库 | 再打一枪 | 已有自动化 |
|---|---|---|---|---|---|---|---|---|---|
| AT-S01 | AC-41 | api/ui | P0 | guest | 打开列表/提问或调写接口 | 登录墙或 401 | 无新行 | 再写仍拒绝 | pytest 部分；UI-01 未跑绿 |
| AT-S02 | AC-01 | flow/ui | P0 | asker | 无答→首答→采纳 | 三态文案：未回答/待采纳/已解决 | `answer_count`/`adopt_count` | 无「已关闭」 | DF 派生；UI-02 |
| AT-S03 | AC-02 | api/ui | P0 | asker | 筛「未解决」 | 仅未回答∪待采纳 | — | 已解决不在结果 | T004/T006；UI-03 |
| AT-S04 | AC-03 | api | P0 | asker | `status=3/4` | 我的/邀请我的，不是待采纳 | — | 与 display_status 不混 | T006；UI-04 |
| AT-S05 | AC-37 | api/ui | P1 | 任意 | 寻找关闭/下架主状态 | 无此能力 | 无 closed 写入 | 超管违规删除仍可用 | T022 |

### 5.2 定向/公开可见性（AC-04/05/06/07/42）

| ID | AC | 层 | P | 角色 | 步骤 | HTTP | 落库 | 再打一枪 | 已有 |
|---|---|---|---|---|---|---|---|---|---|
| AT-V01 | AC-04 | flow | P0 | asker | POST 定向邀 1 有效专家 | 200；`directed` | `qa_question` 1 行；`qa_question_invite` 正好 1 且非提问者 | asker GET 详情可见 | DF-01 |
| AT-V02 | AC-04 | flow | P0 | stranger | 列表/搜索/similar | 不含该题；无标题 | 无脏行 | 深链 18301 | DF-03 |
| AT-V03 | AC-04 | flow | P0 | expertInvited / expertAdmin | 列表+详情 | 200 可见 | — | 管理员可见定向 | DF-01 扩；需确认 admin 列表 |
| AT-V04 | AC-05 | flow | P0 | asker+stranger | POST 公开邀 0 | 200；`public` | invite 0 行 | stranger GET 可见 | DF-02 |
| AT-V05 | AC-06 | flow | P0 | stranger | GET 定向详情 | **18301**；body **无标题/正文** | 问题行仍在 | 列表不含 | DF-03 |
| AT-V06 | AC-07 | 迁移 | P1 | — | upgrade 后读旧题 | — | `question_type=public`；`tenant_id` 默认 | 不可当定向藏 | DF-19 占位；查库抽检 |
| AT-V07 | AC-42 | api/ui | P1 | asker | similar 命中后仍发布 | 200 新题 | 新行；旧题不关 | 不自动合并 | T006；UI-09 |

### 5.3 关联文档（AC-08/47/48）

| ID | AC | 层 | P | 步骤 | HTTP/UI | 落库 | 再打一枪 | 已有 |
|---|---|---|---|---|---|---|---|---|
| AT-D01 | AC-47 | flow | P0 | 选择器 id=`{spaceId}-{fileId}` 发布 | 200 | `related_docs` 含同一串 | GET 详情可 preview，标题对，**不是**「文档不存在」 | DF-04 |
| AT-D02 | AC-08 | flow | P0 | 路人有 knowledge 读权 | 链接可点 | — | 不因「不是提问者」forbidden | DF-04b |
| AT-D03 | AC-08 | flow | P0 | 提问者无 knowledge 读权 | 正文在；链接不可用 | — | 不因作者放行 | DF-04b |
| AT-D04 | AC-48 | flow/ui | P0 | 无权看文档 | `unavailable_reason=forbidden`；testid `eqa-related-doc-blocked` | — | 文案无权限，禁用「文档不存在」 | T020；UI-10 |
| AT-D05 | AC-47 | ui | P0 | 选择后打开 | 标题+预览 | 与写入 id 同一空间 | — | UI-41；依赖 `E2E_RELATED_DOC_ID` |
| AT-D06 | — | flow | P1 | 「我的收藏」引用 | 写入前解析为源 space/file | 非空指针 | 详情打得开 | 事后修复；回归收藏路径 |

### 5.4 首答锁与资格（AC-09～15、43～45）

| ID | AC | 层 | P | 步骤 | HTTP | 落库 | 再打一枪 | 已有 |
|---|---|---|---|---|---|---|---|---|
| AT-L01 | AC-09 | flow | P0 | 受邀专家首答 | 200 | `qa_answer`+1；`content_locked=1`；`answer_count=1` | asker 改邀请失败 | DF-05 |
| AT-L02 | AC-10 | flow | P0 | 两专家并发首答 | 两路 200 | 两行回答；锁仅 0→1 | 锁不可逆 | DF-14 |
| AT-L03 | AC-11 | flow | P0 | 删光未采纳答 | 200 | 答 `status=3`；`answer_count=0`；**锁仍 1** | 改正文失败 | DF-07 |
| AT-L04 | AC-12 | flow | P0 | 未邀专家答定向 | 183xx | `qa_answer` 行数不变 | — | DF-06 |
| AT-L05 | AC-13 | api | P0 | 公开采纳前 expertOther 答 | 200 | 新回答行 | — | T004 |
| AT-L06 | AC-14/16 | flow | P0 | 公开：A 邀未答、B 答后删、C 答；采纳 C | 已解决 | adopt+1；eligibility 含 A/B/C | D 再答拒绝无新行 | DF-08 |
| AT-L07 | AC-15 | flow | P0 | 停用后再答 | 拒绝 | 无新回答；`qa_expert.status=0` 行还在 | — | DF-11 |
| AT-L08 | AC-43 | flow | P0 | 定向未答就评 | 183xx | `qa_comment` 无新行 | 先答后再评可写 | DF-10 |
| AT-L09 | AC-44 | api | P1 | 已答后评；转公开后评论仍在 | 200 | 评论随题公开 | — | T010 |
| AT-L10 | AC-45 | api | P1 | 公开题登录用户评 | 200 | 有评论行 | — | T010 |
| AT-L11 | — | flow | P0 | 作者删未采纳答（无进行中转公开） | 200 | 答删、评论级联 | 已采纳不可删 | DF-24 |
| AT-L12 | — | flow | P0 | 审批中删答 | 拒绝 | 行仍在 | 过期后未采纳可删 | DF-21/25 |

### 5.5 采纳与积分（AC-16/17/18）

| ID | AC | 层 | P | 步骤 | HTTP | 落库 | 再打一枪 | 已有 |
|---|---|---|---|---|---|---|---|---|
| AT-A01 | AC-16 | flow | P0 | 首次采纳 | 200；已解决 | `qa_answer_adopt`+1；`adopt_count=1`；`resolved_at` 有值 | **本域不写 `user_point_log`**；hook 被调 | DF-08；T012 mock |
| AT-A02 | AC-17 | flow | P0 | 第 4 次采纳 | 业务错误 | adopt 仍 3；`adopt_count=3` | — | DF-09 |
| AT-A03 | AC-17 | flow | P0 | 两路并发采纳不同答 | 成功次数=槽位 | 无超 3、无资格脏行 | — | DF-15 |
| AT-A04 | AC-18 | api | P1 | 同专家两答都采纳 | 两槽占用 | 两行 adopt | 积分只激励一次由 F070，本域不改幂等键 | T012；UI-22 |

### 5.6 匿名与表面（AC-19～22）

每条都要核：**列表、详情、审批、通知** 是否同一套脱敏。只测详情不算过。

| ID | AC | 层 | P | 步骤 | HTTP | 落库 | 再打一枪 | 已有 |
|---|---|---|---|---|---|---|---|---|
| AT-I01 | AC-19 | flow | P0 | 非管理员看匿名提问 | 列表/详情仅别名 | `qa_anonymous_alias` 有行；响应无真名部门 | 接口字段不靠前端藏 | DF-16/17 |
| AT-I02 | AC-21 | flow | P0 | expertAdmin 列表/详情 | 真名+匿名展示 | — | 路人仍是别名 | DF-26/25 |
| AT-I03 | AC-20 | unit/flow | P1 | 同用户多条匿名；删一条 | 别名不变 | 不重排 | — | T014；DF-16 弱 |
| AT-I04 | AC-22 | flow | P0 | 定向转公开后 | 按预存 reveal，不再询问 | `question_type=public` | 身份与预选项一致 | DF-13+17 |
| AT-I05 | AC-19 | flow | P0 | 转公开审批实例 | 匿名者不露真名/部门 | — | 非匿名申请人展示主部门 | DF-22/24 |

### 5.7 转公开（AC-23～28、46、34）

| ID | AC | 层 | P | 步骤 | HTTP | 落库 | 再打一枪 | 已有 |
|---|---|---|---|---|---|---|---|---|
| AT-P01 | AC-23 | flow | P0 | 已解决定向发起；duration∈{1,3,7} | 200；发起者已同意 | request pending；approver 含提问者+有效答专家 | 同题再发起拒绝 | DF-13 |
| AT-P02 | AC-23 | api | P0 | duration 非法 | 18310 类 | 无新申请行 | — | T016 |
| AT-P03 | AC-24 | flow | P0 | 任一人拒绝 | 已拒绝 | 保持 directed | 可重新发起；旧申请不可改口 | DF-13 reject |
| AT-P04 | AC-24/28 | flow | P0 | 全体同意 | approved；不可逆 public | invite 行数不变 | 非原受邀答拒绝 | DF-13 |
| AT-P05 | AC-25 | unit | P0 | 审批中停用专家 | 移出+默认同意；可静默通过 | 审计 | 恢复不加入已结束申请 | T016 |
| AT-P06 | AC-26 | task | P0 | 到期未通过 | expired（≤1 分钟延迟） | status=expired | 可重新发起 | T031；DF-17 原 P1 |
| AT-P07 | AC-27/34 | unit | P0 | 提问者账号停用 | 申请 ended；保持定向 | — | 不可新发起 | T016 |
| AT-P08 | AC-46 | flow | P0 | 审批中新专家作答 | 加入审批人；截止 +1 天；同人不再延 | 累计延期 ≤3 天 | 通知相关人 | DF-21 |
| AT-P09 | AC-28 | ui | P0 | 转公开后 expertOther | 无回答框 | 答拒绝无新行 | 可见范围为已登录 | UI-30 |

### 5.8 专家库与超管（AC-29～33、35）

| ID | AC | 层 | P | 步骤 | HTTP | 落库 | 再打一枪 | 已有 |
|---|---|---|---|---|---|---|---|---|
| AT-E01 | AC-29/31 | flow | P0 | admin 停用 | 200 | `status=0` 行在（非硬删） | 不可邀/不可新答/不在榜 | DF-11 |
| AT-E02 | AC-30 | flow | P0 | 非管理员 disable | 权限错误 | status 仍 1 | — | DF-12 |
| AT-E03 | AC-31 | api | P1 | 恢复专家 | 200 status=1 | 不加入历史已结束申请 | — | T018 |
| AT-E04 | AC-32 | api | P0 | 超管 moderate-delete ±R* | 删除成功；扣分走 F070 | 内容行按策略 | 非超管不可见入口 | T029；UI-34 |
| AT-E05 | AC-33 | api/ui | P0 | expertAdmin 调违规删除 | 拒绝 | 无删行 | — | T022；DF-21 占位 |
| AT-E06 | AC-35 | unit | P1 | 回答专家账号停用 | 同停用对答/审批 | — | — | T016 |

### 5.9 通知（AC-36）— 必须查 `inbox_message`

mock `assert_awaited` **不算**本验收。

| ID | 事件 | P | 接收人 | 匿名 | 落库 | 再打一枪 | 已有 |
|---|---|---|---|---|---|---|---|
| AT-N01 | 邀请回答 | P0 | 受邀专家 | 别名 | `inbox_message` 有行 | 深链再鉴权 | T021 mock；**缺真库** |
| AT-N02 | 问题被回答 | P0 | 提问者 | 别名 | 有行 | — | mock |
| AT-N03 | 回答被评论 | P0 | 回答作者+提问者−评论者 | 别名 | 有行 | 自评只通知对方 | DF-23 |
| AT-N04 | 回答被采纳 | P0 | 回答作者 | 别名 | 有行 | — | mock |
| AT-N05 | 转公开申请/加人/通过/拒绝/过期/结束 | P0 | spec 事件表 | 审批面脱敏 | 有行 | 旧申请按钮失效 | DF-21 部分 |
| AT-N06 | 问题已转公开 | P0 | **提问者+回答专家** | — | 提问者有行 | 专家也有 | `test_df_publish_approved_inbox_includes_asker` |

### 5.10 契约与时间

| ID | 风险 | P | 步骤 | 期望 | 已有 |
|---|---|---|---|---|---|
| AT-C01 | 提问图上限 | P0 | 超 3 张 | 18313 非 500；无脏行 | `test_df_question_too_many_images_rejected_no_dirty_row` |
| AT-C02 | 东八墙钟 | P1 | 创建问题 | `created_at` 墙钟；门户无偏移按东八解析 | DF 墙钟；beijing_time |
| AT-C03 | 反向 AC-38～40 | P1 | 扫描接口 | 无关闭态、无把管理员写成超管、不改专家分公式 | T022 |

### 5.11 UI 黄金链路（手工或 Playwright）

自动化目标 35/41；**T041–T044 曾未跑绿，本验收不得记通过**。

P0 手工最小集（无 credentials 时测）：登录墙 → 发定向 → 受邀首答锁定 → 路人 看不见 → 采纳已解决 → 转公开同意 → 非受邀不能答 → 管理员破匿名 → 超管才有违规删除。

对应 UI-01～08、11～16、20、21、23、25～30、32～34、41。

---

## 6. 建议执行顺序

1. `cd src/backend && .venv/bin/pytest -q test/qa_expert/test_data_flow.py`（171）
2. `pytest -q test/qa_expert` 模块回归
3. AT-N01～N06：对 `inbox_message` 做 SELECT（不要只信 mock）
4. 门户 Playwright：`npx playwright test e2e/expert-qa --project=chromium`（需 7 角色 credentials + 联调栈）
5. AT-V06 存量迁移抽检；DM8 仅 Linux/CI

---

## 7. 本轮验收报告（用例输出，回归未跑）

## 结论

- 验收结论：**不通过（作为「已完成开发验收」）** — 本轮只交付用例，**未执行** MySQL 流转、模块回归、Playwright、DM8。
- 主模块：`qa_expert` + 门户 ExpertQA
- 目标分支：`feat/v2.6.0/083-expert-qa-enhancement`
- 测试环境：未在本轮探活
- 结论依据：skill 禁止把未运行写成通过；E2E 历史状态为 CLI 待账号；通知真库仍是缺口风险

用例本身：**可执行、可对照 AC**。自动化已覆盖大部分 flow P0（DF-01～15 及后续 DF-16+）；交付测试工程师前仍须跑第 6 节命令并补通知落库证据。

## 需求覆盖

见第 5 节矩阵「已有自动化」列。缺口：AT-N01/02/04 真库、AT-V06 迁移抽检、UI T041–T044 跑绿、DM8、跨租户（若未开则标明 N/A）。

## P0/P1

- P0：第 5 节标 P0 的 AT-*，最终验收必须有证据。
- P1：similar 不阻断、别名不重排、过期任务、账号停用、收藏解析。
- 原因不明的 skip：无（本轮是未运行，不是 skip）。

## 专项

- 权限：AT-V/E/I；跨租户未验证
- 一致性：AT-L/A 流转
- 并发：AT-L02、AT-A03
- 异步：AT-P06、AT-N*
- MySQL：以 test_data_flow 为准，**本轮未跑**
- DM8：**未验证**
- 性能：不做门槛

## 交付建议

**不建议**在本轮命令未跑绿前声称可交测试工程师「开发已验收通过」。

建议下一步（需你授权才会改测试代码/执行）：

1. 跑 `test_data_flow.py` + `test/qa_expert`，把结果填进本报告。
2. 为 AT-N01/02/04 补 `inbox_message` SELECT（若仍缺）。
3. 配齐 `e2e/.auth/credentials.json` 后跑 Playwright @p0。
4. 通过后再把结论改为「有条件通过」或「通过」。
