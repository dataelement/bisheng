# Tasks: DSH 模型转发敏感词控制

- **特性**：F111 / v3.0.0
- **关联**：[spec.md](./spec.md) · [design.md](./design.md) · [任务评审](./tasks-review.md)
- **日期**：2026-10-23
- **工作分支**：feat/bisheng-work-dsh-guardrails
- **当前范围**：用户已授权持续按依赖实施至 T132，逐项测试、自审后更新状态；允许多 agent 并行。核心实现与配对自审已推进至 Wave 32，T119/T120的MySQL子项已独立通过；完整E2E、容量与演练仍待环境/前驱，DM8实测按用户决定保留待验收，用户已追加授权合入最新 feat/bisheng-work-120-main 并推送，经 Drone 构建后仅部署 109 DSH13001，再启动客户端联调；其他环境禁止变更。

## 1. 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 用户已确认，后续取舍已同步 |
| design.md | ✅ 已评审 | 用户于本轮明确“设计可以”，包含现有共享 HMAC、可信身份变化和既有分页取舍 |
| tasks.md | ✅ 已拆解 | 经 sdd-review tasks 静态评审 LGTM；不代表任务已执行 |
| 实现 | 🔄 进行中 | 177 / 195；核心实现及配对自审至Wave32，T119/T120 MySQL子项通过，DM8及完整E2E/容量/演练待验 |

## 2. 执行约定与仓库范围

| 标识 | 执行工作树 | 当前执行基线 |
|---|---|---|
| B | /Users/zhangguoqing/.codex/worktrees/bisheng-work-dsh-guardrails/bisheng | 2e6b5ae0fb1dcd2e32d480545e1d1ea57e77cd24 |
| G | /Users/zhangguoqing/works/bisheng-gateway.worktrees/dsh-guardrails | origin/main / 2995df6fdf9c51b70617a86a803aec9c6633b69e |
| D | /Users/zhangguoqing/works/bisheng-work.worktrees/dsh-guardrails | origin/main / 01e09d027ba729f6021ec37c33937f5745cee992 |

每项文件路径相对该项执行工作树，目标文件逐一列出；不存在的路径是拟新增文件，不声称已实现。三个仓库的功能分支均为 feat/bisheng-work-dsh-guardrails；G/D 于 2026-10-23 获取 main 后创建并核对远端 SHA，未复用原业务分支。原工作区和已有 worktree 均保留，禁止仓库级 stash/reset/restore/clean。

原设计评审核查基线保留在 design §4.1，作为历史依据。Gateway 新 main 与原核查提交文件树一致；Desktop 新 main 有变化，Chat 的 content_filter 分支与 Responses 的 UPSTREAM_ERROR 分支仍存在，但这不替代完整兼容性复核。各实现任务开始前须对新基线重读所涉及模块、目录规则和测试；该基线调整没有完成或勾选任何实现任务。

任务目标为一次会话约 30 分钟的人工编写/操作、最多 2 个人工维护文件；真实数据库造数和负载运行可使用可恢复的长运行会话，单列运行耗时与证据，不把目标工时当运行SLA。只修改该任务内声明的方法/区域；共享文件后续任务均为增量接入，不覆盖前驱逻辑。后端及Gateway、Desktop核心协议采用前置测试；Platform界面采用本项手工验证和后续组件测试。红测允许缺少拟新增类型/方法，不能把待实现函数写入测试充当生产实现。基础设施声明/DDL/错误码/fixture 不要求配对，全部先于业务任务。

类别为基础设施、后端 Domain、后端 API、前端 Platform、Worker，另将外部 Gateway/Desktop 明确标出。**前端 Client（src/frontend/client）本期无业务实现任务**，共享错误文案生成物按构建同步验证；Desktop 不是这个 SPA。Platform 按当前用户根 AGENTS 采用 @tanstack/react-query v4，仅补直接依赖和本特性局部Provider，不全站迁移；不沿旧模板新建 DAO、用 Zustand 替代 Client Recoil 或引入 react-query v3。

已确认边界：复用现有 HMAC 密钥和签名头配置，不新增独立密钥/key_id；profile 是 backend 校验 DSH Token、当前用户/租户和会话后的 user/tenant 返回，缓存最长 30 秒；接受毕昇可信身份变化，不增加跨事件身份冻结表；分页沿既有方式，默认 7 天/最多 31 天，不冻结默认相对窗口。backend 模型鉴权、额度和计量不感知 Gateway。

环境验收按方言和链路分别记账：T119 的 MySQL 子闸门经独立实际验证通过后，可推进 T120 的 MySQL SQL 验证与不依赖 DM8 的准备；缺少 Linux DM8 不视为产品测试失败，也不视为通过，T119/T120 整体仍保持未完成。实际失败仍阻断依赖，完整 E2E、容量和交付验收不得以组件或单方言结果代替。此约定落实用户“DM8 实测保留待验收”和“环境阻断保留未完成、继续独立工作”，不改变功能或验收标准。

测试仅使用合成账号、Token、密钥和可控上游。普通单元与 API 测试可本地执行，中间件/真实双库在隔离集成或中央回归环境运行；DM8 按 constitution 的 Linux 中央回归要求，不伪称每 PR 已有自动门禁。UI 手工步骤是常规界面验收，不是高成本测试降级；本计划没有测试降级项。构建生成物与运行报告须按真实产出列入交付差异，禁止手改生成资源或将未运行检查标通过。

## 3. Wave 总览

Wave 由依赖图最长路径计算；实施中发现的必要兼容补齐按已执行状态插入安全的后续 Wave，不倒退已完成任务。Wave 用于展示依赖层级；T016基础一致性闸门之后，独立链路可在前驱全部完成时提前解锁，不必等待其他无依赖链的环境验收。并行任务不得共享目标文件；文件相交即使无数据依赖也串行。当前采用主 agent 加 3 个子 agent；每个文件仅一名写入负责人，共享文档和任务状态由主 agent 统一更新。

| Wave | 任务 | 本 Wave 完成条件 |
|---|---|---|
| 1 | T001、T002、T003、T004、T005、T006、T007、T008、T009、T010、T011、T012、T013、T014、T015、T133、T134 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 2 | T016 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 3 | T017、T019、T055、T061、T065、T077、T083、T099、T100、T101、T111 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 4 | T018、T020、T056、T062、T066、T078、T084、T112 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 5 | T021、T057、T063 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 6 | T022、T058、T064 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 7 | T023、T059、T067、T069、T135 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 8 | T024、T060、T068、T070 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 9 | T025、T071、T073、T075 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 10 | T026、T072、T074、T076 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 11 | T027、T041、T085、T113、T115 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 12 | T028、T042、T086、T114、T116 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 13 | T029、T037、T043、T087、T136 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 14 | T030、T038、T044、T088、T137 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 15 | T031、T089、T117 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 16 | T032、T090 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 17 | T033、T091、T118、T140、T141 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 18 | T034、T092、T142、T143 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 19 | T035、T093 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 20 | T036、T094、T144 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 21 | T039、T079、T095、T145、T146 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 22 | T148、T149、T150、T151、T040、T080、T096、T147 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 23 | T045、T081、T102 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 24 | T046、T152、T153、T156、T082、T154、T155、T103、T105、T106 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 25 | T047、T097、T165、T104、T107 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 26 | T166、T167、T048、T098、T157、T158、T159、T160、T161、T162、T163、T164 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 27 | T049、T138 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 28 | T050、T139 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 29 | T051、T108 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 30 | T052、T109、T170 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 31 | T053、T110、T168、T171、T172、T174 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 32 | T054、T169、T173、T175 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 33 | T119 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 34 | T120 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 35 | T121 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 36 | T122 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 37 | T123 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 38 | T124 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 39 | T125 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 40 | T126、T127、T128、T130 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 41 | T129 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 42 | T131 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |
| 43 | T132 | 所列任务的验证完成并做 /task-review；失败不越过依赖 |

## 4. 任务清单

### Wave 1

- [x] **T001 安全事件 ORM 与租户发现**

  **类型**：基础设施 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/models/content_safety_event.py`（拟新增）；`src/backend/bisheng/core/database/tenant_filter.py`（既有，显式登记事件模型）。

  **逻辑与上下文**：新增 dsh_content_safety_event，采用现有租户基类、BigInteger、JsonType；唯一 source_id/event_id 和 source_id/gateway_request_id/event_version，包含两个请求编号、审计关联、阶段快照、有限命中摘要、原始与接收时间。增加详情、未关联、请求事件及清理索引；不建身份冻结表，不保存正文或凭据。

  **验证**：检查 SQLModel 模型发现和 MySQL/DM8 编译；回退应用时保留事件表及已有事实，删除需另获数据清理授权。

  **承接 AC**: AC-35、AC-37、AC-39、AC-42、AC-53。

  **依赖**：无。

- [x] **T002 主审计的外部来源和安全摘要列**

  **类型**：基础设施 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/models/model_audit_request.py`（既有）。

  **逻辑与上下文**：新增 MODEL/EXTERNAL_SAFETY 来源、可空 model_entered/model_started_at、source/Gateway 请求关联、输入/输出状态及版本、三个单调命中标志、六态汇总、安全投影版本和已投影命中标志。外部条目的 mode/session/模型结果/交付/结算可空；来源条件约束替换旧 mode CHECK。旧行默认 MODEL、UNREPORTED、无已知命中。

  **验证**：新旧模型声明可发现；不得把旧 UNKNOWN 变为零。回退保留新增列及事实；旧应用读取前先关闭检查并做 DTO 兼容验证。

  **承接 AC**: AC-34、AC-36、AC-38、AC-44、AC-52、AC-53。

  **依赖**：无。

- [x] **T003 会话与目录命中计数模型**

  **类型**：基础设施 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/models/model_audit_conversation.py`（既有）；`src/backend/bisheng/dsh/domain/models/model_audit_tree.py`（既有）。

  **逻辑与上下文**：会话增加 sensitive_hit_count/has_sensitive_hit；目录节点增加 own/branch 命中请求计数及安全汇总水位。沿用现有 dirty、租约与代际发布字段，不新增第二套树。

  **验证**：列默认不宣称历史已通过；检查双库类型。回滚应用不删除新增计数，需重建时由后续运维任务操作。

  **承接 AC**: AC-47、AC-48、AC-52、AC-53。

  **依赖**：无。

- [x] **T004 持久删除水位声明**

  **类型**：基础设施 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/models/model_audit_setting.py`（既有）。

  **逻辑与上下文**：在既有审计 setting 增加每租户 audit_deleted_before 和有限清理进度，默认空；与 mode/version 字段分离。只声明字段，不实施自动清理、不默认设置 30 天保留。

  **验证**：旧设置读取默认兼容；回退保留水位，不把删除水位清空后允许旧记录复活。

  **承接 AC**: AC-51、AC-52、AC-53。

  **依赖**：无。

- [x] **T005 接收与请求 DTO 声明**

  **类型**：基础设施 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/schemas/content_safety.py`（拟新增）；`src/backend/bisheng/dsh/domain/schemas/model_audit.py`（既有）。

  **逻辑与上下文**：声明 ContentSafetyEnvelope(sent_at,event)、严格 v1 Event 和 Receipt；stage_results 为 input/output 状态映射，stage_versions 为对应非负版本（未观测为 0，状态改变取当前 event_version，未改变保持原值）；ID 正十进制 int64 字符串/UUID、64 KiB、深度 16、摘要最多 20 项、合法枚举及清理后的四个会话字段。AuditRequestMetadata 增加外部来源、可空模型字段、六态安全结果及详情状态；不增加 key_id。

  **验证**：DTO 能导入；未知字段拒绝，错误不回显值；保持旧请求 DTO 的已有效字段。

  **承接 AC**: AC-25、AC-26、AC-34、AC-35、AC-36、AC-46。

  **依赖**：无。

- [x] **T006 会话目录查询与返回类型**

  **类型**：基础设施 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/schemas/model_audit_group.py`（既有）。

  **逻辑与上下文**：扩展既有组/树查询类型，并在同文件新增当前缺失的响应 DTO，包含 has_sensitive_hit、INPUT/OUTPUT/BOTH、六态结果、去重命中计数、安全 readiness、水位及 scan_limited；BOTH 是交集。保持原模型异常数语义。

  **验证**：旧无安全过滤请求可解析；默认时间不引入固定窗口或新游标协议。

  **承接 AC**: AC-45、AC-47、AC-48、AC-49、AC-50。

  **依赖**：无。

- [x] **T007 沿用 DSH 模块登记事件错误**

  **类型**：基础设施 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/common/errcode/dsh.py`（既有）。

  **逻辑与上下文**：实施前扫描全仓 Code 字面量，确认候选 26170–26175 未占用后登记接收鉴权、事件非法、事件冲突、事件过期、接收不可用及超限。只扩展既有 261 模块；ClientCode content_blocked/check_unavailable 不借用账号或额度错误。

  **验证**：错误码唯一且符合 MMMEE；不修改已有错误码或发布契约含义。

  **承接 AC**: AC-30、AC-31、AC-42、AC-43。

  **依赖**：无。

- [x] **T008 既有表 DDL 与安全回退说明**

  **类型**：基础设施 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/core/database/alembic/versions/v3_0_0_f111_dsh_content_safety.py`（拟新增）；`src/backend/bisheng/core/database/alembic_helpers/online.py`（既有，复用大小写兼容的约束检查）。

  **逻辑与上下文**：实时运行 alembic heads 确认单 head，再生成 f111_dsh_content_safety revision；只对既有审计主表、setting、会话/树增列、索引及来源 CHECK 做幂等 DDL。新事件整表由模型发现 create_all 创建；禁止 revision 内回填、清理或 SELECT 后写。使用 online helpers 和 DM8 适配。

  **验证**：uv run alembic heads 与 test/database/test_alembic_single_head.py；fresh/upgrade 结构相同。downgrade 默认拒绝破坏性收缩，不在 revision 内按业务数据判空；应用回退保留扩展 schema。空数据结构回退由独立运维步骤先停止写入和判空，再在双库演练验证。

  **承接 AC**: AC-51、AC-52、AC-53。

  **依赖**：无。

- [x] **T009 后端独立测试 fixture**

  **类型**：基础设施 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/content_safety_fixtures.py`（拟新增）；`src/backend/test/dsh/conftest.py`（既有）。

  **逻辑与上下文**：新增合成租户、身份、事件、时钟、原生审计、故障注入和事务工厂；SQLite 只验证无方言逻辑，保留真实 MySQL/DM8 会话适配接口。接收测试不启动完整模型 runtime、不使用真实 Token 或密钥。

  **验证**：fixture smoke 可导入且不改变其他 dsh 测试默认行为；不做 Milvus/ES 测试降级。

  **承接 AC**: AC-39、AC-42、AC-53。

  **依赖**：无。

- [x] **T010 Gateway 策略与 Outbox 实体**

  **类型**：基础设施 · 基础设施；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/entity/DshSensitivePolicy.java`（拟新增）；`src/main/java/com/dataelem/gateway/entity/DshSafetyOutbox.java`（拟新增）。

  **逻辑与上下文**：策略实体 tenant_id 唯一、version/开关/方向/词源/词/回复/摘要；Outbox 不可变 payload/hash 与独立投递字段分开，PENDING/INFLIGHT/ACKED/QUARANTINED、租约、退避及时间齐全。没有原始凭据或命中原文列。

  **验证**：实体编译；两种 DDL 列型对齐。应用回退保留词库配置、未确认事实及 ACK 状态。

  **承接 AC**: AC-06、AC-10、AC-35、AC-58。

  **依赖**：无。

- [x] **T011 有界预算与不可变请求上下文类型**

  **类型**：基础设施 · 基础设施；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/config/DshSafetyProperties.java`（拟新增）；`src/main/java/com/dataelem/gateway/dto/DshSafetyContext.java`（拟新增）。

  **逻辑与上下文**：定义默认关闭、固定 backend namespace/source-id、32 MiB 请求/累计响应、Responses 8 MiB 单事件、64 MiB 编码额度、16 检查/8 续读、30 秒续读、词表/编译/队列预算；上下文携带验证身份与策略快照。HMAC 只引用既有 BishengConfig 配置，不增加独立密钥。

  **验证**：参数绑定有合法范围；不通过扩大 200 MB 全局 codec 绕过额度；明示实际堆放大仍需压测。

  **承接 AC**: AC-02、AC-09、AC-14、AC-18、AC-26、AC-57。

  **依赖**：无。

- [x] **T012 Gateway MySQL 增量 DDL**

  **类型**：基础设施 · 基础设施；仓库 G；目标约 30 分钟。

  **文件**：`docker/db/f111_dsh_content_safety_mysql.sql`（拟新增）；`docker/db/f111_dsh_content_safety_mysql_rollback.sql`（拟新增）。

  **逻辑与上下文**：创建 gt_dsh_sensitive_policy、gt_dsh_safety_outbox 及 tenant/version/领取索引，提供重复执行前检查与空表结构回退 SQL；不改旧应用表。回退脚本对有数据表拒绝删除，转应用关闭功能并保留事实。

  **验证**：后续真实 MySQL fresh/upgrade/空表回退验证；不在本轮执行 SQL。

  **承接 AC**: AC-06、AC-10、AC-53、AC-58。

  **依赖**：无。

- [x] **T013 Gateway DM8 增量 DDL**

  **类型**：基础设施 · 基础设施；仓库 G；目标约 30 分钟。

  **文件**：`docker/db/f111_dsh_content_safety_dm.sql`（拟新增）；`docker/db/f111_dsh_content_safety_dm_rollback.sql`（拟新增）。

  **逻辑与上下文**：提供与 MySQL 同义的 DM8 类型、约束及索引，无 JSON 查询、MySQL upsert 或 SKIP LOCKED 假设；空表回退与有数据保护规则相同。

  **验证**：后续 Linux DM8 fresh/upgrade/空表回退验证，不能用 SQLite/MySQL 结果代替；不在本轮执行 SQL。

  **承接 AC**: AC-06、AC-10、AC-53、AC-58。

  **依赖**：无。

- [x] **T014 Platform 的策略及审计类型**

  **类型**：基础设施 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/src/types/dshContentSafety.ts`（拟新增）；`src/frontend/platform/src/types/dshModelAudit.ts`（既有）。

  **逻辑与上下文**：声明策略版本/词库限制、capabilities、六态检查结果、外部条目、有限命中事件、未关联分页及会话树命中计数。effective_mode 等未知值可空，BOTH 为输入输出均命中；与 backend DTO 和 Gateway ResultData 对齐。

  **验证**：仅新增/扩展类型，不引入 HTTP 或新状态库；Web Client 无新增类型或改动。

  **承接 AC**: AC-34、AC-44、AC-45、AC-46、AC-48。

  **依赖**：无。

- [x] **T015 Platform v4 取数依赖兼容**

  **类型**：基础设施 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/package.json`（既有）；`src/frontend/pnpm-lock.yaml`（既有）。

  **逻辑与上下文**：当前 platform 只直接声明 react-query v3，而已确认设计要求新增取数用 @tanstack/react-query v4。仅为 platform 补充 workspace 已锁定的 4.44.0 直接依赖，保留其他模块 v3 和现有锁定版本；不做全站迁移、不引入新状态库。Provider 在后续安全设置组件内局部接入。

  **验证**：从 src/frontend 定向更新 platform 依赖与锁；检查其他包版本不被批量升级，后续组件/构建验证新hook可解析v4。

  **承接 AC**: AC-03、AC-06。

  **依赖**：无。

- [x] **T133 DTO 消费端审计元数据兼容修复**

  **类型**：基础设施 · 既有 DTO 消费端兼容修复；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/model_audit_queries.py`（仅 metadata 序列化）；`src/backend/test/dsh/test_model_audit_groups.py`（专项兼容回归）。

  **逻辑与上下文**：Wave 1 回归发现既有 metadata 对 DTO 全字段直接 getattr ORM，新增别名/阶段映射字段导致 AttributeError。先保留红测证据并添加旧 MODEL 默认/UNKNOWN、EXTERNAL_SAFETY 可空状态回归，再显式映射新增字段；明细未实际查询时不声称 AVAILABLE，不逐行查询事件，不实施后续完整筛选功能。

  **验证**：新增回归红转绿及既有审计组/请求测试；Ruff、架构、文件范围和 DTO 同步检查。

  **覆盖 AC**: AC-34、AC-36、AC-44、AC-52。

  **依赖**：无；同 Wave 内等待 T005 的字段定义冻结后增量适配，复用已复现红测的轻量兼容修复流程。

- [x] **T134 Platform 可空状态消费兼容修复**

  **类型**：基础设施 · 既有 DTO 消费端兼容修复；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditCard.tsx`（既有）。

  **逻辑与上下文**：T014 类型扩展触发三个真实 TypeScript 错误；仅允许既有状态标签函数接受 null 并显示已有本地化 UNKNOWN，空值不形成模型失败说明。最终外部条目的不适用/未观测展示与三语仍由既定后续 UI 和文案任务交付，不新增缺翻译键或样式。

  **验证**：完整 Platform typecheck、定向 ESLint 和 Card/Panel/Group/Tree 组件回归；不减弱 DTO 类型。

  **承接 AC**: AC-36、AC-44、AC-52。

  **依赖**：无；同 Wave 内 T014 字段定义冻结后增量适配。

### Wave 2

- [x] **T016 基础设施一致性检查**

  **类型**：验收 · 基础设施；仓库 B；目标约 30 分钟。

  **文件**：`features/v3.0.0/111-dsh-sensitive-word-control/implementation-verification.md`（拟新增）；`src/backend/test/database/test_alembic_dsh_main_upgrade.py`（既有，保留原 main 字节校验，扩展 F111 链路、模型/DDL 一致性与迁移保护验证）。

  **逻辑与上下文**：未来执行时记录模型/双库 DDL 对照、单 head、候选错误码唯一、测试 fixture 可用和旧行默认值；结果写入该报告的基础设施节。此任务不调用模型、不部署、不清理业务数据。

  **验证**：运行静态模型导入与单 head 测试；真实 DDL 结果由后续双库任务补充，未做的不写通过。

  **覆盖 AC**: AC-52、AC-53。

  **依赖**：T001、T002、T003、T004、T005、T006、T007、T008、T009、T010、T011、T012、T013、T014、T015、T133、T134。

### Wave 3

- [x] **T017 提取共享 HMAC primitive 并保留 SSO 适配先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_hmac.py`（拟新增）。

  **逻辑与上下文**：只编写测试：固定 METHOD/LF/PATH/LF/raw bytes 的跨语言向量、大小写十六进制、正文空字节/Unicode/篡改、相同密钥兼容；旧 SSO 错误码、默认 X-Signature 及正文回放仍保持。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_hmac.py -q。

  **覆盖 AC**: AC-03、AC-35、AC-42。

  **依赖**：T016。

- [x] **T019 六态归并与单调命中归约先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_states.py`（拟新增）。

  **逻辑与上下文**：只编写测试：输入输出 36 种状态组合、缺结果、旧版本命中先后到、重复及 DRAIN 不能重开已结束检查；输入关闭输出不适用为 NOT_APPLICABLE。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_states.py -q。

  **覆盖 AC**: AC-33、AC-34、AC-41。

  **依赖**：T016。

- [x] **T055 DSH profile 专用 HTTP 客户端先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/client/DshProfileClientTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：/api/v1/dsh/profile 原始 Token、user.id/tenant.id 合法校验、业务失败/超时/结构异常、固定目标且不记录 Authorization、同 Token 当前资料变化可用。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshProfileClientTest test。

  **覆盖 AC**: AC-13、AC-16、AC-18、AC-19、AC-38。

  **依赖**：T016。

- [x] **T061 租户策略 CAS 存储先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshSensitivePolicyStoreTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：缺失策略关闭/version0、首次 expected_version0、并发 CAS 一个成功、读取异常不当关闭、SQL 不依赖 MySQL 特有写法。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshSensitivePolicyStoreTest test。

  **覆盖 AC**: AC-02、AC-06、AC-09、AC-10、AC-12、AC-53。

  **依赖**：T016。

- [x] **T065 策略管理实时授权客户端先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/client/DshSafetyAdminClientTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：普通用户拒绝；Child Admin 仅 leaf且active；超管目标有效范围；HTTP200业务失败拒绝；OFF/密钥不可用的审计设置仍允许有权管理者。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshSafetyAdminClientTest test。

  **覆盖 AC**: AC-07、AC-08、AC-18。

  **依赖**：T016。

- [x] **T077 Gateway 不可变事件与持久 Outbox先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshSafetyOutboxServiceTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：命中立即DECISION、正常FINAL、续读DRAIN完整快照；event_id/version固定重试不变；SQL写失败仍阻断且报缺口；无命中仅审计失败保留业务结果。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshSafetyOutboxServiceTest test。

  **覆盖 AC**: AC-33、AC-34、AC-35、AC-40、AC-41、AC-43、AC-55、AC-58。

  **依赖**：T016。

- [x] **T083 DSH 单次上游 HTTP 所有权先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/client/DshModelProxyClientTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：一次请求一次响应订阅、无自动重试/重定向、原Bearer/正文/正常X-Request-ID、用户取消关闭上游、固定backend目标、资源释放。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshModelProxyClientTest test。

  **覆盖 AC**: AC-03、AC-05、AC-16、AC-17、AC-29、AC-31、AC-32。

  **依赖**：T016。

- [x] **T099 Platform 与 API 错误文案 zh-Hans**

  **类型**：实现 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/public/locales/zh-Hans/bs.json`（既有）；`src/frontend/packages/locales/src/api_errors/zh-Hans.json`（既有）。

  **逻辑与上下文**：为 dsh.contentSafety.* 增加策略、命中方向、六态、未调用/未观测/已清理/未关联/积压等固定文案；为最终登记26170–26175补api_errors文案。三语言同一交付，不手改api_errors生成物，不翻译租户自定义阻断提示。

  **验证**：三个locale任务全部完成后再生成并执行三语键对齐；新增键集合完全一致。

  **承接 AC**: AC-56。

  **依赖**：T016、T007。

- [x] **T100 Platform 与 API 错误文案 en**

  **类型**：实现 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/public/locales/en-US/bs.json`（既有）；`src/frontend/packages/locales/src/api_errors/en.json`（既有）。

  **逻辑与上下文**：为 dsh.contentSafety.* 增加策略、命中方向、六态、未调用/未观测/已清理/未关联/积压等固定文案；为最终登记26170–26175补api_errors文案。三语言同一交付，不手改api_errors生成物，不翻译租户自定义阻断提示。

  **验证**：三个locale任务全部完成后再生成并执行三语键对齐；新增键集合完全一致。

  **承接 AC**: AC-56。

  **依赖**：T016、T007。

- [x] **T101 Platform 与 API 错误文案 ja**

  **类型**：实现 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/public/locales/ja/bs.json`（既有）；`src/frontend/packages/locales/src/api_errors/ja.json`（既有）。

  **逻辑与上下文**：为 dsh.contentSafety.* 增加策略、命中方向、六态、未调用/未观测/已清理/未关联/积压等固定文案；为最终登记26170–26175补api_errors文案。三语言同一交付，不手改api_errors生成物，不翻译租户自定义阻断提示。

  **验证**：三个locale任务全部完成后再生成并执行三语键对齐；新增键集合完全一致。

  **承接 AC**: AC-56。

  **依赖**：T016、T007。

- [x] **T111 Desktop 安全错误文案与声明先行测试**

  **类型**：测试 · 外部 Desktop；仓库 D；目标约 30 分钟。

  **文件**：`test/enterprise-content-safety-copy.test.mjs`（拟新增）。

  **逻辑与上下文**：只编写测试：CONTENT_FILTERED/CONTENT_CHECK_UNAVAILABLE 的zh/en/ja固定键完整，安全消息清理，不把content_blocked识别为登录失败，不翻译租户自定义提示。测试上下文：D 仓库 Vitest，沿用 EnterpriseLlmAdapter 与 BlockAssembler fixture；可控 SSE 和记录调用次数的假工具，不读取真实 Profile；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：D: npm test -- test/enterprise-content-safety-copy.test.mjs。

  **覆盖 AC**: AC-30、AC-31、AC-35、AC-56。

  **依赖**：T016。

### Wave 4

- [x] **T018 提取共享 HMAC primitive 并保留 SSO 适配**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/common/utils/hmac_signature.py`（拟新增）；`src/backend/bisheng/sso_sync/domain/services/hmac_auth.py`（既有）。

  **逻辑与上下文**：公开 compute_hmac_signature(method,path,raw,secret) 与常量时间比较的无业务副作用 helper；旧 SSO compute_signature 委托该 helper，保留原依赖行为。共享文件影响限签名计算，不接入 DSH 模型认证，不更换密钥或全局 tenant bypass。

  **验证**：通过配对任务 T017 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-03、AC-35、AC-42。

  **依赖**：T017。

- [x] **T020 六态归并与单调命中归约**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/services/content_safety_states.py`（拟新增）。

  **逻辑与上下文**：实现 reduce_safety(existing,event) 纯函数：任一已知命中→BLOCKED；否则 ERROR→UNREPORTED→两方向 DISABLED→至少一个 PASSED→NOT_APPLICABLE。阶段版本只更新可确认事实，旧命中仍累积；同版本异事实诊断，不加身份冻结。

  **验证**：通过配对任务 T019 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-33、AC-34、AC-41。

  **依赖**：T019。

- [x] **T056 DSH profile 专用 HTTP 客户端**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/client/DshProfileClient.java`（拟新增）；`src/main/java/com/dataelem/gateway/dto/DshSafetyContext.java`（既有，允许可信身份的 Token 到期未知并禁止缓存）。

  **逻辑与上下文**：实现 fetchIdentity(authorization,deadline)；只信任 backend 成功校验 Token/用户/租户/会话后返回的 user/tenant，不把 JWT payload 当已验证身份。目标复用固定 bisheng-api-url，客户端不启用通用 DEBUG 头日志，无重定向/自动重试。

  **验证**：通过配对任务 T055 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-13、AC-16、AC-18、AC-19、AC-38。

  **依赖**：T055。

- [x] **T062 租户策略 CAS 存储**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/mapper/DshSensitivePolicyMapper.java`（拟新增）；`src/main/java/com/dataelem/gateway/service/DshSensitivePolicyStore.java`（拟新增）。

  **逻辑与上下文**：提供 read(tenantId) 与 save(tenantId,expectedVersion,policy)；租户条件显式，策略字段一次事务保存，成功版本递增。使用可移植条件 INSERT/UPDATE，不复用旧应用资源策略表。

  **验证**：通过配对任务 T061 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-02、AC-06、AC-09、AC-10、AC-12、AC-53。

  **依赖**：T061。

- [x] **T066 策略管理实时授权客户端**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/client/DshSafetyAdminClient.java`（拟新增）。

  **逻辑与上下文**：每次带浏览器凭据调 user/info；所有操作者调 /api/v1/dsh/admin/model-audit/settings?tenant_id=target 验证管理权。普通管理员另核 user/tenants active 列表，超管再读 tenants/{target}；不以 profile 缓存/显示角色独立授权，不缓存管理授权。

  **验证**：通过配对任务 T065 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-07、AC-08、AC-18。

  **依赖**：T065。

- [x] **T078 Gateway 不可变事件与持久 Outbox**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/mapper/DshSafetyOutboxMapper.java`（拟新增）；`src/main/java/com/dataelem/gateway/service/DshSafetyOutboxService.java`（拟新增）。

  **逻辑与上下文**：提供 recordDecision/recordFinal/recordDrain 与可移植租约领取/确认，事件最多64KiB/depth16/20摘要，禁止正文与凭据。只有SQL成功称已记录；保存payload_hash，不用内存队列冒充持久化；命中记录不等待续读或结算。

  **验证**：通过配对任务 T077 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-33、AC-34、AC-35、AC-40、AC-41、AC-43、AC-55、AC-58。

  **依赖**：T077。

- [x] **T084 DSH 单次上游 HTTP 所有权**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/client/DshModelProxyClient.java`（拟新增）。

  **逻辑与上下文**：使用独立客户端持有上游连接，沿用部署模型超时；过滤hop-by-hop与失效Content-Length。不给 CLIENT_RESPONSE_CONN_ATTR，让默认代理清理接管；将读完/交付完/用户取消拆成独立信号，不二次subscribe。

  **验证**：通过配对任务 T083 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-03、AC-05、AC-16、AC-17、AC-29、AC-31、AC-32。

  **依赖**：T083。

- [x] **T112 Desktop 安全错误文案与声明**

  **类型**：实现 · 外部 Desktop；仓库 D；目标约 30 分钟。

  **文件**：`packages/dsh-desktop-enterprise/error-copy.js`（既有）；`packages/dsh-desktop-enterprise/error-copy.d.ts`（既有）。

  **逻辑与上下文**：新增安全错误归一化与三语copy导出并同步声明；只为新错误补语言，不重构所有旧账号文案，不引入i18n库或改Token存储。提供后续adapter和locale消费的稳定接口。

  **验证**：通过配对任务 T111 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-30、AC-31、AC-35、AC-56。

  **依赖**：T111。

### Wave 5

- [x] **T021 事件幂等保存与保留检查先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_repository.py`（拟新增）。

  **逻辑与上下文**：只编写测试：重复同载荷、同编号异载荷、同请求同版本异事实、并发唯一键重读、跨租户隔离、已删除主行补报 410、真实身份变化接收。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_repository.py -q。

  **覆盖 AC**: AC-38、AC-39、AC-41、AC-42、AC-51、AC-53。

  **依赖**：T016、T020。

- [x] **T057 身份 L1 与 Redis 绝对寿命先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshIdentityCacheTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：L1 2 秒/Redis 30 秒、Token 到期减 5 秒、原子 value+PTTL、读取耗时不得续期、namespace/完整 Token 隔离、Redis 故障和无效结果不缓存。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshIdentityCacheTest test。

  **覆盖 AC**: AC-13、AC-14、AC-15、AC-17、AC-18、AC-19。

  **依赖**：T016、T056。

- [x] **T063 词表编译与五秒策略快照先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshSensitivePolicyServiceTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：内置+自定义、字面大小写、空词拒绝、超过 1MiB/30000词/256码点拒绝、摘要不一致不可用、更新和失效丢失最多 5 秒收敛。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshSensitivePolicyServiceTest test。

  **覆盖 AC**: AC-06、AC-09、AC-10、AC-11、AC-12、AC-18、AC-21、AC-26、AC-55。

  **依赖**：T016、T062。

### Wave 6

- [x] **T022 事件幂等保存与保留检查**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/content_safety.py`（拟新增）。

  **逻辑与上下文**：提供 append_event(session,event,payload_hash)、lookup_receipt 和 retention_guard；SELECT 使用严格租户上下文，UPDATE/DELETE 显式 tenant/id/version。相同来源事件去重；Repository 不提交调用者事务，唯一键竞争向外传播 IntegrityError，由 T030 的事务所有者退出失败事务后新事务重读，不建立全局身份绑定表。

  **验证**：通过配对任务 T021 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-38、AC-39、AC-41、AC-42、AC-51、AC-53。

  **依赖**：T021、T020。

- [x] **T058 身份 L1 与 Redis 绝对寿命**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/service/DshIdentityCache.java`（拟新增）。

  **逻辑与上下文**：key=backend namespace+SHA256完整原始 Token；值仅验证身份/时间/截止时间。单调时钟截止和 Redis 剩余 TTL，不滑动续期；成功 profile 后只读 exp 缩短有效期。明确凭据错误仅本机负缓存 1 秒，基础设施错误不负缓存；校时异常副本不接检查。

  **验证**：通过配对任务 T057 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-13、AC-14、AC-15、AC-17、AC-18、AC-19。

  **依赖**：T057、T056。

- [x] **T064 词表编译与五秒策略快照**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/service/DshSensitivePolicyService.java`（拟新增）；`src/main/java/com/dataelem/gateway/service/DshSensitiveMatcherCache.java`（拟新增）。

  **逻辑与上下文**：复用 FileUtil、CustomerConfig 内置加载和 ACPlus；快照键 tenant/version/builtin_digest。L1 1秒/Redis 5秒、500ms 读预算；旧读不能覆盖新版本。编译池2任务、最多200000节点、缓存权重128MiB，失败不发布空词库；已取得的在途引用固定到本次结束。

  **验证**：通过配对任务 T063 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-06、AC-09、AC-10、AC-11、AC-12、AC-18、AC-21、AC-26、AC-55。

  **依赖**：T063、T062。

### Wave 7

- [x] **T023 外部条目与主摘要事务合并先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_merge.py`（拟新增）。

  **逻辑与上下文**：只编写测试：输入命中未转发、输出编号已知/未知、事件/原审计两种顺序及竞争、用户身份变化保留事实、不可确认归属留未关联、摘要和事件同事务回滚。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_merge.py -q。

  **覆盖 AC**: AC-27、AC-32、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-44、AC-48。

  **依赖**：T016、T022、T020。

- [x] **T059 冷验证合并与取消预算先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshProfileVerifierTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：同副本相同键首次/过期并发只调用一次；单等待者取消不取消共享请求；队满/超时；Redis owner 租约失效旧结果不能覆盖新结果。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshProfileVerifierTest test。

  **覆盖 AC**: AC-14、AC-15、AC-18、AC-19、AC-59。

  **依赖**：T016、T058。

- [x] **T067 策略保存与能力 API先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/controller/DshSensitivePolicyControllerTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：GET默认关闭/公开限制、PUT版本冲突409/格式400/超限413/依赖503、Origin校验、用户凭据或旧DSH登录不能管理、租户回复校验。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshSensitivePolicyControllerTest test。

  **覆盖 AC**: AC-02、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-18。

  **依赖**：T016、T066、T064。

- [x] **T069 Unicode 增量字面扫描先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshSensitiveScannerTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：跨 UTF8/UTF16补充平面/转义/最后尾部、同域连续文本块、不同消息/choices/工具不能拼词、命中摘要20项不存原词。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshSensitiveScannerTest test。

  **覆盖 AC**: AC-20、AC-21、AC-22、AC-25、AC-26、AC-35。

  **依赖**：T016、T064。

- [x] **T135 管理授权返回可信操作者**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/client/DshSafetyAdminClientTest.java`（既有）；`src/main/java/com/dataelem/gateway/client/DshSafetyAdminClient.java`（既有）。

  **逻辑与上下文**：T066 已完成管理授权但返回 Void，策略持久化的 updated_by 需要可信当前用户。追加 authorizeIdentity(headers,target) 返回嵌套不可变 AdminIdentity(tenantId,userId)，只从既有 /user/info 响应取合法正 int64 用户编号，完整实时授权链不变；既有 authorize 委托后 then() 保持兼容。不取浏览器自报操作者，不新增 backend RPC 或 profile 缓存。此项是已确认管理能力的必要返回类型补齐，不扩展权限规则。

  **验证**：原 T065 文件新增可信编号/非法缺失编号/旧 Void 兼容断言先 RED 后 GREEN，重跑原八项真实本地 HTTP 回归及任务自审；本项最多两文件，T068 保留两个目标文件。

  **承接 AC**: AC-02、AC-08、AC-09、AC-35。

  **依赖**：T065、T066。


### Wave 8

- [x] **T024 外部条目与主摘要事务合并**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/content_safety_projection.py`（拟新增）。

  **逻辑与上下文**：提供 merge_audit(session,event) 与标记 dirty：输入以 Gateway UUID 创建外部行，输出用模型响应 UUID；外部 NULL/NOT_CAPTURED/NOT_APPLICABLE，缺用量为 null。started_at 首次固定，真实模型起点另存；已有主行按自身归属关联。安全命中不写 dsh_model_call 或额度。

  **验证**：通过配对任务 T023 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-27、AC-32、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-44、AC-48。

  **依赖**：T023、T022、T020。

- [x] **T060 冷验证合并与取消预算**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/service/DshProfileVerifier.java`（拟新增）；`src/main/java/com/dataelem/gateway/service/DshIdentityCache.java`（拟新增）。

  **逻辑与上下文**：实现 resolveIdentity：本机 singleflight、32 在途/64 等待、1 秒含排队总预算；跨副本短租约只允许 owner 发布/释放。Redis 故障退本机合并及容量限制，不无限等待；原始 Token 仅在本次验证/转发必要内存存在。仅增量接入缓存 miss 分支。

  **验证**：通过配对任务 T059 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-14、AC-15、AC-18、AC-19、AC-59。

  **依赖**：T059、T058。

- [x] **T068 策略保存与能力 API**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/controller/DshSensitivePolicyController.java`（拟新增）；`src/main/java/com/dataelem/gateway/params/DshSensitivePolicyRequest.java`（拟新增）。

  **逻辑与上下文**：实现 GET/PUT /api/sensitive/dsh/settings?tenant_id= 与 GET /capabilities；委托实时授权、策略 Store/Service，沿用 ResultData 并正确报告 status_code。浏览器写操作校验允许 Origin，实时授权成功后才聚合最多8MiB原始正文，严格UTF8/JSON深度16，解码词库仍限1MiB；不扩展 saveWords/wordsDetail/testWords 为 DSH 入口。

  **验证**：通过配对任务 T067 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-02、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-18。

  **依赖**：T067、T066、T064、T135。

- [x] **T070 Unicode 增量字面扫描**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/service/DshSensitiveScanner.java`（拟新增）。

  **逻辑与上下文**：提供新建逻辑域、feedDecodedText、completeDomain 接口；按 Unicode 码点保留 L−1 尾部，适配 ACPlus 的 char 索引。保留每个域的已检查水位，输出有限 rule_ref/hit_count；不调用旧 filterNormal 或写 BlockRecord。

  **验证**：通过配对任务 T069 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-20、AC-21、AC-22、AC-25、AC-26、AC-35。

  **依赖**：T069、T064。

### Wave 9

- [x] **T025 原生 writer 接受安全先到条目先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_native_writer.py`（拟新增）。

  **逻辑与上下文**：只编写测试：外部条目提升 MODEL 后原文、mode、会话及模型字段正确补齐；原生事件后到不重置命中、不重复条目、不改安全 started_at；回滚不留下半提升。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_native_writer.py -q。

  **覆盖 AC**: AC-03、AC-32、AC-38、AC-41、AC-47、AC-49、AC-52。

  **依赖**：T016、T024。

- [x] **T071 Chat 与 Responses 输入文本域先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/protocol/DshInputSafetyAdapterTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：两协议完整历史/可读reasoning/工具描述与结果、工具JSON字符串和值、同消息连续块、图像/加密reasoning/凭据/audit_context排除、非法结构400。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshInputSafetyAdapterTest test。

  **覆盖 AC**: AC-01、AC-05、AC-20、AC-21、AC-22、AC-25、AC-26、AC-27。

  **依赖**：T016、T070。

- [x] **T073 Chat SSE 检查与 content_filter 终态先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/protocol/DshChatSafetyAdapterTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：UTF8跨片/CRLF/多行data、完整原事件按序、跨event词、工具参数完整屏障、错误/取消未完成检查ERROR、正常文本字节与usage不改。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshChatSafetyAdapterTest test。

  **覆盖 AC**: AC-01、AC-05、AC-20、AC-21、AC-22、AC-24、AC-25、AC-28、AC-29、AC-30、AC-31、AC-33、AC-34。

  **依赖**：T016、T070。

- [x] **T075 Responses 有序增量与最终快照屏障先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/protocol/DshResponsesSafetyAdapterTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：增量/arguments.done/item.done/最终快照新增文本、reasoning/refusal、多个域交错、sequence_number不重写、8MiB事件与32MiB累计上限。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshResponsesSafetyAdapterTest test。

  **覆盖 AC**: AC-01、AC-05、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-28、AC-29、AC-30、AC-31、AC-33。

  **依赖**：T016、T070。

### Wave 10

- [x] **T026 原生 writer 接受安全先到条目**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/model_audit_write.py`（既有）；`src/backend/bisheng/dsh/domain/services/model_audit_writer.py`（既有）。

  **逻辑与上下文**：在 upsert_request 的既有身份校验边界支持外部来源的已确认事实补齐，原 writer 同事务补 mode 并提升来源；保存模型实际起点，不写安全列。仅调整审计写入，不修改模型执行、凭证或用量真相。

  **验证**：通过配对任务 T025 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-03、AC-32、AC-38、AC-41、AC-47、AC-49、AC-52。

  **依赖**：T025、T024。

- [x] **T072 Chat 与 Responses 输入文本域**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/protocol/DshInputSafetyAdapter.java`（拟新增）。

  **逻辑与上下文**：解析有界 UTF8 JSON，提取已支持 schema 的文本域；工具参数完整 JSON 解码后分别查键和值；保留原始正文转发，不改写或只查最新问题。可选四个审计提示独立清洗，非法提示只影响关联。

  **验证**：通过配对任务 T071 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-01、AC-05、AC-20、AC-21、AC-22、AC-25、AC-26、AC-27。

  **依赖**：T071、T070。

- [x] **T074 Chat SSE 检查与 content_filter 终态**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/protocol/DshChatSafetyAdapter.java`（拟新增）。

  **逻辑与上下文**：适配 Chat 流式和非流式输出；整原事件只有所有依赖文本过水位才可交付。命中发 content_filter chunk 再 [DONE]，不发 stop/tool_calls 成功终态或伪造usage；检查失败 event:error/check_unavailable。工具按choice/call绑定并完整解码。

  **验证**：通过配对任务 T073 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-01、AC-05、AC-20、AC-21、AC-22、AC-24、AC-25、AC-28、AC-29、AC-30、AC-31、AC-33、AC-34。

  **依赖**：T073、T070。

- [x] **T076 Responses 有序增量与最终快照屏障**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/protocol/DshResponsesSafetyAdapter.java`（拟新增）。

  **逻辑与上下文**：按 item/call/content_index 维护域和有序原事件队列，所有工具参数依赖检查完成后才交付；完成快照独立校验而不重复当增量。命中或不可用发明确 type=error 且无 completed；未知可交付结构报错，不跳过检查。

  **验证**：通过配对任务 T075 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-01、AC-05、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-28、AC-29、AC-30、AC-31、AC-33。

  **依赖**：T075、T070。

### Wave 11

- [x] **T027 外部条目的模型状态与停滞排除先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_external_status.py`（拟新增）。

  **逻辑与上下文**：只编写测试：外部缺 mode/manifest/model_result 时为不适用或未观测，不能进入 RUNNING 停滞或全租户 INVALID_STATE；来源升级恢复模型状态；实际 UNKNOWN 不变零。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_external_status.py -q。

  **覆盖 AC**: AC-32、AC-34、AC-36、AC-38、AC-44、AC-48、AC-52。

  **依赖**：T016、T026。

- [x] **T041 请求到会话的命中差量投影先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_groups.py`（拟新增）。

  **逻辑与上下文**：只编写测试：命中变化且 audit_status 不变仍 dirty；重复事件/外部升级只计一次；无 conversation 条目不永久 dirty，后补关联再次处理；回滚/重试不负计数。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_groups.py -q。

  **覆盖 AC**: AC-38、AC-41、AC-47、AC-48、AC-52。

  **依赖**：T016、T024、T026。

- [x] **T085 缓冲额度与命中后有界续读先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshSafetyRequestManagerTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：64MiB编码预算、16检查/8续读、客户端阻断闭流不提前取消上游、从命中计时30秒/字节/异常/无容量先到即止、普通取消不续读。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshSafetyRequestManagerTest test。

  **覆盖 AC**: AC-18、AC-19、AC-26、AC-29、AC-32、AC-40、AC-43、AC-57。

  **依赖**：T016、T084、T074、T076、T078。

- [x] **T113 Desktop Chat 阻断及工具完成屏障先行测试**

  **类型**：测试 · 外部 Desktop；仓库 D；目标约 30 分钟。

  **文件**：`test/enterprise-content-safety-chat.test.mjs`（拟新增）。

  **逻辑与上下文**：只编写测试：HTTP403/503、content_filter+[DONE]、event:error、租户提示、工具参数已完整但最后blocked时无可执行block-end、正常工具及usage不变、调用次数为1。测试上下文：D 仓库 Vitest，沿用 EnterpriseLlmAdapter 与 BlockAssembler fixture；可控 SSE 和记录调用次数的假工具，不读取真实 Profile；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：D: npm test -- test/enterprise-content-safety-chat.test.mjs。

  **覆盖 AC**: AC-05、AC-24、AC-29、AC-30、AC-31、AC-32、AC-56。

  **依赖**：T016、T112、T074。

- [x] **T115 Desktop Responses 错误优先识别先行测试**

  **类型**：测试 · 外部 Desktop；仓库 D；目标约 30 分钟。

  **文件**：`test/enterprise-content-safety-responses.test.mjs`（拟新增）。

  **逻辑与上下文**：只编写测试：无sequence_number的合法error在序列检查前处理；最终快照/工具完成后再blocked不执行工具；错误非UPSTREAM_ERROR；正常序列/推理回放不变。测试上下文：D 仓库 Vitest，沿用 EnterpriseLlmAdapter 与 BlockAssembler fixture；可控 SSE 和记录调用次数的假工具，不读取真实 Profile；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：D: npm test -- test/enterprise-content-safety-responses.test.mjs。

  **覆盖 AC**: AC-05、AC-23、AC-24、AC-29、AC-30、AC-31、AC-32、AC-56。

  **依赖**：T016、T112、T076。

### Wave 12

- [x] **T028 外部条目的模型状态与停滞排除**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/schemas/model_audit_status.py`（既有）；`src/backend/bisheng/dsh/domain/services/model_audit_states.py`（既有）。

  **逻辑与上下文**：状态派生先区分 MODEL/EXTERNAL_SAFETY；外部不要求原文密钥与模型终态，停滞扫描只处理真实模型条目。安全 dirty 独立于 audit_status 变化，不能用原模型异常数表达安全命中。

  **验证**：通过配对任务 T027 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-32、AC-34、AC-36、AC-38、AC-44、AC-48、AC-52。

  **依赖**：T027、T026。

- [x] **T042 请求到会话的命中差量投影**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/model_audit_conversations.py`（既有）；`src/backend/bisheng/dsh/domain/services/model_audit_projection.py`（既有）。

  **逻辑与上下文**：按 group_indexed_sensitive_hit 与当前请求状态计算 delta，维护 sensitive_hit_count/has_sensitive_hit 和树 dirty。领取/完成显式 tenant/id/lease，条目计数与模型调用次数分开；批次最多 200，返回持久进度。

  **验证**：通过配对任务 T041 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-38、AC-41、AC-47、AC-48、AC-52。

  **依赖**：T041、T024、T026。

- [x] **T086 缓冲额度与命中后有界续读**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/service/DshSafetyRequestManager.java`（拟新增）。

  **逻辑与上下文**：管理单一上游订阅和独立有界客户端通道；原始请求32MiB完整限长再转发，检查和排队预算有界。命中立即停内容交付且生成DECISION，独立最多30秒续读、剩余响应字节预算，结束释放DataBuffer/订阅/额度并生成DRAIN；只上报观察状态不写用量。

  **验证**：通过配对任务 T085 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-18、AC-19、AC-26、AC-29、AC-32、AC-40、AC-43、AC-57。

  **依赖**：T085、T084、T074、T076、T078。

- [x] **T114 Desktop Chat 阻断及工具完成屏障**

  **类型**：实现 · 外部 Desktop；仓库 D；目标约 30 分钟。

  **文件**：`packages/dsh-desktop-enterprise/openai.js`（既有）。

  **逻辑与上下文**：把阻断映射不可重试CONTENT_FILTERED，检查失败映射CONTENT_CHECK_UNAVAILABLE；保留安全提示和编号。工具完成块延迟到该轮正常终态确认后发布，错误轮次清掉待工具；保留普通文字安全前缀和原providerRetryPolicy。

  **验证**：通过配对任务 T113 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-05、AC-24、AC-29、AC-30、AC-31、AC-32、AC-56。

  **依赖**：T113、T112、T074。

- [x] **T116 Desktop Responses 错误优先识别**

  **类型**：实现 · 外部 Desktop；仓库 D；目标约 30 分钟。

  **文件**：`packages/dsh-desktop-enterprise/responses.js`（既有）。

  **逻辑与上下文**：在普通sequence校验前归一化content_blocked/check_unavailable；延迟可执行工具完成块到正常整轮确认，错误轮次清理pending，保留租户提示/编号；无自动重试或伪造completed。

  **验证**：通过配对任务 T115 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-05、AC-23、AC-24、AC-29、AC-30、AC-31、AC-32、AC-56。

  **依赖**：T115、T112、T076。

### Wave 13

- [x] **T029 安全事件接收编排与持久 ACK先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_ingest.py`（拟新增）。

  **逻辑与上下文**：只编写测试：提交成功才 COMMITTED、SQL 失败/超时不 ACK、响应丢失重试、唯一键竞争后完整事务回滚并用新 Session 重读/重归并、不在失效事务继续查询、未关联也只确认事实、可信身份变化可接受、旧命中不清除。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_ingest.py -q。

  **覆盖 AC**: AC-03、AC-35、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-58。

  **依赖**：T016、T024、T026、T028。

- [x] **T037 主列表摘要过滤与事件分页先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_queries.py`（拟新增）。

  **逻辑与上下文**：只编写测试：真假命中、INPUT/OUTPUT/BOTH、六态和用户/模型/时间组合；外部 nullable DTO；7/31 天、显式换条件/跨租户旧游标拒绝；PURGED 与 UNREPORTED 区别。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_queries.py -q。

  **覆盖 AC**: AC-32、AC-34、AC-36、AC-44、AC-45、AC-46、AC-49、AC-50、AC-51、AC-52。

  **依赖**：T016、T028、T024。

- [x] **T043 目录 own/branch 命中与代际发布先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_tree.py`（拟新增）。

  **逻辑与上下文**：只编写测试：父子会话命中传播、重复代际构建、仅外部条目可就绪、worker 停止时 PREPARING、租户停用后补报仍 dirty。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_tree.py -q。

  **覆盖 AC**: AC-41、AC-47、AC-48、AC-52。

  **依赖**：T016、T042。

- [x] **T087 两个模型入口的检查编排先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/filter/DshContentSafetyFilterTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：仅两条精确POST、部署关闭透传/租户关闭无阻断、profile/策略不可用503、输入命中403且backend模型调用0、过期身份清缓存不重试模型。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshContentSafetyFilterTest test。

  **覆盖 AC**: AC-01、AC-02、AC-03、AC-04、AC-05、AC-11、AC-12、AC-13、AC-16、AC-17、AC-18、AC-19、AC-27、AC-30、AC-31、AC-55。

  **依赖**：T016、T060、T064、T072、T086。

- [x] **T136 Desktop 当前语言回调贯通先行测试**

  **类型**：测试 · 外部 Desktop；仓库 D。

  **文件**：`test/enterprise-content-safety-chat.test.mjs`（既有）；`test/enterprise-content-safety-responses.test.mjs`（既有）。

  **逻辑与上下文**：只增补当前真实adapter的可选localizeContentSafety(code,defaultMessage)消费测试；未提供回调兼容、三语固定fallback、Gateway两种check_unavailable固定提示、租户自定义提示不覆盖、普通账户额度错误不受影响、无效回调结果安全回退；安全错误body的Gateway编号优先，普通错误保留header优先。不能用字典存在代替接线。

  **验证**：新增断言先RED，原31及相邻74保持；不写生产桩。

  **覆盖 AC**: AC-30、AC-31、AC-56。

  **依赖**：T114、T116。

### Wave 14

- [x] **T030 安全事件接收编排与持久 ACK**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/services/content_safety_ingest.py`（拟新增）。

  **逻辑与上下文**：实现 ingest(event,verified_source)：规范事件摘要、调用事件与主投影 Repository 的同一事务，唯一键竞争时退出失败事务并以新 Session 开完整短事务重读去重/重归并，提交后生成 Receipt。区分事实追加与主行唯一冲突；新事务严格租户重读仍不可见的跨租户主键/关联占用，保存事实为UNASSOCIATED而不无限重试或开启bypass。线程执行前后建立/恢复严格 profile_scope；不按当前用户退出或调租拒绝历史事件，不主动调用 Gateway。

  **验证**：通过配对任务 T029 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-03、AC-35、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-58。

  **依赖**：T029、T024、T026、T028。

- [x] **T038 主列表摘要过滤与事件分页**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/model_audit_queries.py`（既有）；`src/backend/bisheng/dsh/domain/repositories/content_safety_queries.py`（拟新增）。

  **逻辑与上下文**：主列表只读主摘要并 bulk 查用量/姓名；输出模型执行成功与内容 BLOCKED 可并存。提供请求事件和未关联事件的 limit+1/keyset 查询，不逐行读事件、不全历史 COUNT。默认窗口沿既有分页，不新增冻结要求；模型调用与实际用量仍取 dsh_model_call。

  **验证**：通过配对任务 T037 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-32、AC-34、AC-36、AC-44、AC-45、AC-46、AC-49、AC-50、AC-51、AC-52。

  **依赖**：T037、T028、T024。

- [x] **T044 目录 own/branch 命中与代际发布**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/model_audit_tree_build.py`（既有）；`src/backend/bisheng/dsh/domain/repositories/model_audit_hierarchy.py`（既有）。

  **逻辑与上下文**：扩展现有树构建摘要和安全 readiness，不为安全检查建立新树；持久租约与批次重建、一次发布完整代际。历史租户枚举只返回 pending tenant IDs，具体构建回到严格租户范围。

  **验证**：通过配对任务 T043 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-41、AC-47、AC-48、AC-52。

  **依赖**：T043、T042。

- [x] **T088 两个模型入口的检查编排**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/filter/DshContentSafetyFilter.java`（拟新增）。

  **逻辑与上下文**：早于旧CustomResponseFilter设置DSH路由标志，取得profile成功结果和租户策略快照；按方向组织输入检查与请求管理器。缺失策略为关闭而读取失败为不可用；商业检查能力失效不能静默透传已开启策略。保留backend自己的身份、模型权限、额度错误。

  **验证**：通过配对任务 T087 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-01、AC-02、AC-03、AC-04、AC-05、AC-11、AC-12、AC-13、AC-16、AC-17、AC-18、AC-19、AC-27、AC-30、AC-31、AC-55。

  **依赖**：T087、T060、T064、T072、T086。

- [x] **T137 Desktop 当前语言回调贯通**

  **类型**：实现 · 外部 Desktop；仓库 D。

  **文件**：`packages/dsh-desktop-enterprise/openai.js`（既有）；`packages/dsh-desktop-enterprise/responses.js`（既有）。

  **逻辑与上下文**：沿T136端口传递同步可选localizeContentSafety回调；仅固定fallback使用当前语言，租户提示始终保留。requestFailure/responseFailure末尾可选参数，Chat终态与Responses hooks用同一回调；不修改第三方分发包或另建语言体系。T117在既有两文件负责真实注册、构造与卸载。

  **验证**：T136新增断言与原31/相邻74全部通过，任务自审；UI运行验证仍归T117。

  **承接 AC**: AC-30、AC-31、AC-56。

  **依赖**：T136。

### Wave 15

- [x] **T117 Desktop locale 与错误消费接线**

  **类型**：实现 · 外部 Desktop；仓库 D；目标约 30 分钟。

  **文件**：`packages/dsh-desktop-enterprise/client.js`（既有）；`packages/dsh-desktop-enterprise/index.js`（既有）。

  **逻辑与上下文**：沿现有插件locale服务注册新错误zh/en/ja固定文案，并把已归一化安全错误接到当前显示入口/adapter构造上下文；保留租户自定义提示。只新增命名空间键与必要参数传递，不新建语言体系/运行时，不修改第三方分发包。

  **验证**：切换三语言实际显示阻断/不可用文案，账号状态不被误置失效；插件卸载重载无重复注册；不把只新增copy对象当已接通。

  **承接 AC**: AC-30、AC-31、AC-56。

  **依赖**：T114、T116、T137。

- [x] **T031 接收端共享密钥认证和独立组装先行测试**

  **类型**：测试 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_runtime.py`（拟新增）。

  **逻辑与上下文**：只编写测试：现有密钥和配置签名头可用；无密钥只使接收端不可用；无 SSO 登录仍可用；错误签名/时间窗/超限拒绝；未验签不访问业务表。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_runtime.py -q。

  **覆盖 AC**: AC-03、AC-26、AC-35、AC-42、AC-43。

  **依赖**：T016、T018、T030。

- [x] **T089 专用路由过滤器和有序交付先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/filter/DshModelRoutingFilterTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：在PathRate之后/default Netty之前取所有权、无默认二次HTTP、完整原事件顺序、两协议四种模式、原错误保留与Gateway/backend编号区分。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshModelRoutingFilterTest test。

  **覆盖 AC**: AC-01、AC-05、AC-16、AC-23、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-37、AC-57。

  **依赖**：T016、T088。

### Wave 16

- [x] **T032 接收端共享密钥认证和独立组装**

  **类型**：实现 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/content_safety_runtime.py`（拟新增）；`src/backend/bisheng/common/errcode/dsh.py`（既有，来源租户范围拒绝复用认证业务码并区分 HTTP 403）。

  **逻辑与上下文**：提供 get_content_safety_service 与 verify_source(raw,headers,method,path)：从 settings.sso_sync 取既有 gateway_hmac_secret/signature_header，默认 X-Signature，时间窗口 ±300 秒。无独立密钥变量/key_id，用户 Token 不能代替服务签名。独立按需组装，不初始化 model runtime。

  **验证**：通过配对任务 T031 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-03、AC-26、AC-35、AC-42、AC-43。

  **依赖**：T031、T018、T030。

- [x] **T090 专用路由过滤器和有序交付**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/filter/DshModelRoutingFilter.java`（拟新增）；`src/main/java/com/dataelem/gateway/service/DshSafetyRequestManager.java`（既有，增量接入实际HTTP写入生命周期额度）。

  **逻辑与上下文**：读取可信上下文，标already-routed并交给专用proxy/request manager，不继续默认模型路由。正常原始X-Request-ID保留；生成阻断错误用Gateway UUID，已知模型编号附X-Backend-Request-ID；不由forwarded推断执行。订阅HTTP正文前登记writer租约，编码字节从交付队列转为writer-held，实际write完成/失败/取消后才归还，避免Spring/Netty待发字节落到全局额度之外；原独立manager消费者语义保持。

  **验证**：通过配对任务 T089 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-01、AC-05、AC-16、AC-23、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-37、AC-57。

  **依赖**：T089、T088。

### Wave 17

- [x] **T033 安全事件路由与真实 HTTP 回执先行测试**

  **类型**：测试 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_api.py`（拟新增）。

  **逻辑与上下文**：只编写测试：真实路径方法、64 KiB/depth/ID 限制、原始字节只读一次、400/401/403/409/410/413/503 与 200 COMMITTED；字段错误不回显敏感内容。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_api.py -q。

  **覆盖 AC**: AC-25、AC-26、AC-35、AC-39、AC-42、AC-43。

  **依赖**：T016、T032。

- [x] **T091 源配置与部署配置精确路由先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/config/DshSafetyRoutingConfigurationTest.java`（拟新增）；`src/test/java/com/dataelem/gateway/config/GatewayRoutingConfigurationTest.java`（既有，仅Spring placeholder解析夹具对齐）。

  **逻辑与上下文**：只编写测试：两个DSH精确POST优先catch-all、无CacheRequestBody、profile及模型同固定目标、DM继承、登录/刷新/profile/目录不受内容检查、关闭仍透传。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshSafetyRoutingConfigurationTest test。

  **覆盖 AC**: AC-01、AC-02、AC-03、AC-04、AC-05、AC-26、AC-54。

  **依赖**：T016、T090。

- [x] **T118 真实 Harness 工具执行边界验证**

  **类型**：测试 · 外部 Desktop；仓库 D；目标约 30 分钟。

  **文件**：`test/enterprise-content-safety-runtime.test.ts`（拟新增）。

  **逻辑与上下文**：只写运行时行为测试，使用安装的Harness公开Agent/工具执行入口、Enterprise adapter与一个递增计数的合成工具：先出现完整工具参数，最后返回两种协议阻断/不可用，调用计数均为0；正常工具轮次计数为1。覆盖block-end/finish消费链及同轮后续文本命中。

  **验证**：D: npm test -- test/enterprise-content-safety-runtime.test.ts；通过后记录实际消费点，不以BlockAssembler单测代替工具runner证据，不直接编辑node_modules。若屏障不成立，该任务不能完成，按SDD偏差机制补齐宿主适配。

  **覆盖 AC**: AC-23、AC-24、AC-29、AC-30、AC-31。

  **依赖**：T117、T090。

- [x] **T140 Desktop 语言桥接入口与卸载回归固化**

  **类型**：测试 · 外部 Desktop；仓库 D。

  **文件**：`test/enterprise-content-safety-locale.test.mjs`（拟新增）。

  **逻辑与上下文**：将T117已执行的真实LocaleRuntime/client.apply/认证connection/request/注册adapter入口验证固化到仓库测试；覆盖无偏好、Host持久化延迟、三语言双协议固定copy、租户提示、并发ALS隔离、非法/重复/跨authority cookie、同值双renderer owner与卸载重载。使用临时专用profile和合成本地上游，无真实Cookie/Token；不得只mock locale或直接调用localize callback代替入口。不把该测试替代真实Agent/Session工具屏障或Electron GUI。

  **验证**：D: npm exec -- vitest run test/enterprise-content-safety-locale.test.mjs；与内容安全adapter现有测试组合执行，不依赖前一测试遗留Context或Cookie。

  **覆盖 AC**: AC-30、AC-31、AC-56。

  **依赖**：T117。

- [x] **T141 Desktop 既有插件夹具兼容回归**

  **类型**：测试 · 外部 Desktop；仓库 D。

  **文件**：`test/enterprise-adapter.test.ts`（既有）；`test/enterprise-audit-integration.test.ts`（既有，公共事件夹具对齐）。

  **逻辑与上下文**：维护既有插件上下文夹具的公共on订阅disposer，以及原private函数被公开导出后的源码提取边界；不修改原目录、图像、错误分类和文案断言，不将无事件stub作为语言桥接证明（实际入口由T140验证）。

  **验证**：保留先前5项夹具失败证据，修后运行该文件及内容安全、旧Chat/Responses适配器相邻集。

  **覆盖 AC**: AC-03、AC-30、AC-31、AC-56。

  **依赖**：T117、T137。

### Wave 18

- [x] **T034 安全事件路由与真实 HTTP 回执**

  **类型**：实现 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/api/endpoints/content_safety_events.py`（拟新增）；`src/backend/bisheng/dsh/api/router.py`（既有）。

  **逻辑与上下文**：注册 POST /api/v1/internal/dsh/content-safety-events；Endpoint 只限长读取、调用 verifier/DTO/Service，返回直接 receipt 对象及 DSH 错误 envelope，不包平台 resp_200，不使用 SSO request._receive 回放。

  **验证**：通过配对任务 T033 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-25、AC-26、AC-35、AC-39、AC-42、AC-43。

  **依赖**：T033、T032。

- [x] **T092 源配置与部署配置精确路由**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/resources/application.yml`（既有）；`docker/gateway/config/application.yml`（既有）。

  **逻辑与上下文**：增加独立DSH路由与默认关闭属性，精确Chat/Responses POST、URI对齐bisheng-api-url；不把新密钥值写入示例，不扩大200MB codec。保留原应用/WS路径和既有限流；部署入口封闭另由验收证明。

  **验证**：通过配对任务 T091 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-01、AC-02、AC-03、AC-04、AC-05、AC-26、AC-54。

  **依赖**：T091、T090。

- [x] **T142 Desktop 账户旧UI夹具兼容回归**

  **类型**：测试 · 外部 Desktop；仓库 D。

  **文件**：`test/enterprise-seat-error-view.test.mjs`；`test/enterprise-insecure-confirm-view.test.mjs`（既有）。

  **逻辑与上下文**：对齐T117新增使用的公共LocaleRuntime接口，保留全部原UI断言。只维护测试夹具，不以生产optional chaining兼容不完整桩，不将夹具通过冒充真实语言桥接（真实入口见T140）。

  **验证**：保留旧夹具缺getSnapshot等接口导致的RED证据；修后执行对应文件及T140/现有内容安全组合回归。

  **覆盖 AC**: AC-03、AC-30、AC-31、AC-56。

  **依赖**：T117。

- [x] **T143 Desktop 市场旧UI夹具兼容回归**

  **类型**：测试 · 外部 Desktop；仓库 D。

  **文件**：`test/enterprise-market-view.test.mjs`；`test/enterprise-market-client.test.mjs`（既有，仅公共locale夹具对齐）。

  **逻辑与上下文**：对齐T117新增使用的公共LocaleRuntime接口，保留全部原UI断言。只维护测试夹具，不以生产optional chaining兼容不完整桩，不将夹具通过冒充真实语言桥接（真实入口见T140）。

  **验证**：保留旧夹具缺getSnapshot等接口导致的RED证据；修后执行对应文件及T140/现有内容安全组合回归。

  **覆盖 AC**: AC-03、AC-30、AC-31、AC-56。

  **依赖**：T117。

### Wave 19

- [x] **T035 精确服务认证入口与租户恢复先行测试**

  **类型**：测试 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_middleware.py`（拟新增）。

  **逻辑与上下文**：只编写测试：合法服务签名在无浏览器 Cookie 时可达；无签名/用户 Token 不能上报；相邻 internal 路径不豁免；残留超管/bypass 清除，异常后上下文恢复。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_middleware.py -q。

  **覆盖 AC**: AC-03、AC-42、AC-45。

  **依赖**：T016、T034。

- [x] **T093 旧输入与响应敏感词路径跳过 DSH先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/filter/DshLegacySensitiveIsolationTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：DSH输入/输出不进filterNormal/BlockRecord/原文日志；旧assistant/workflow应用命中行为不变；关闭检查仍不会误用旧应用策略。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshLegacySensitiveIsolationTest test。

  **覆盖 AC**: AC-02、AC-03、AC-35、AC-54。

  **依赖**：T016、T092。

### Wave 20

- [x] **T036 精确服务认证入口与租户恢复**

  **类型**：实现 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/utils/http_middleware.py`（既有）。

  **逻辑与上下文**：仅对精确 POST 接收路径跳过浏览器 JWT 准入，转专用服务认证；不把 internal/dsh 前缀加入 TENANT_CHECK_EXEMPT_PATHS。签名验证后使用事件租户的严格上下文，保护其他 API/DSH 认证行为。

  **验证**：通过配对任务 T035 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-03、AC-42、AC-45。

  **依赖**：T035、T034。

- [x] **T094 旧输入与响应敏感词路径跳过 DSH**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/filter/SensitiveWordsFilter.java`（既有）；`src/main/java/com/dataelem/gateway/filter/CustomResponseFilter.java`（既有）。

  **逻辑与上下文**：在旧输入和响应包装入口识别精准DSH路由标志并跳过旧敏感词分支，普通应用不改。只复用ACPlus/FileUtil能力，不重连已移除DSH登录、License或席位代码。

  **验证**：通过配对任务 T093 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-02、AC-03、AC-35、AC-54。

  **依赖**：T093、T092。

- [x] **T144 Desktop 每次模型流冻结安全文案的先行测试**

  **类型**：测试 · 外部 Desktop；仓库 D。

  **文件**：`test/enterprise-content-safety-chat.test.mjs`；`test/enterprise-content-safety-responses.test.mjs`。

  **逻辑与上下文**：只测试可选同步contentSafetyFormatterFor({sessionId,purpose})在每次实际协议stream开始冻结formatter；旧localizeContentSafety兼容，异常/非法factory安全降级不影响普通模型，tenant提示不覆盖，未来上下文改变不改在途formatter，不转发文案。

  **验证**：双协议新factory契约先RED、原callback/普通工具/账户与错误回归GREEN；配对T145全部通过。

  **覆盖 AC**: AC-03、AC-30、AC-31、AC-56。

  **依赖**：T137、T117。

### Wave 21

- [x] **T039 审计查询服务与管理端点扩展先行测试**

  **类型**：测试 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_query_api.py`（拟新增）。

  **逻辑与上下文**：只编写测试：租户管理员/超管作用域/普通用户、历史用户退出后的查询、请求详情、事件详情及未关联列表；403 由既有权限链返回。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_query_api.py -q。

  **覆盖 AC**: AC-07、AC-08、AC-35、AC-44、AC-45、AC-46、AC-49、AC-50、AC-51。

  **依赖**：T016、T038、T036。

- [x] **T079 共享 HMAC 回传与提交回执校验先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/client/ContentSafetyEventClientTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：Java/Python同向量、默认/配置签名头、sent_at重试重签但event不变、COMMITTED与event_id匹配才ACK、2xx假成功/404/5xx/401等分类。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=ContentSafetyEventClientTest test。

  **覆盖 AC**: AC-35、AC-39、AC-41、AC-42、AC-43、AC-58。

  **依赖**：T016、T018、T036、T078。

- [x] **T095 PathRate 正文日志隔离与公共限流先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/filter/DshPathRateIsolationTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：DSH无旧CACHED_REQUEST_BODY时不空指针、不打印Token/正文，适用公共限流仍执行；旧应用流量规则不变。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshPathRateIsolationTest test。

  **覆盖 AC**: AC-05、AC-26、AC-35、AC-54。

  **依赖**：T016、T094。

- [x] **T145 Desktop 每次模型流冻结安全文案**

  **类型**：实现 · 外部 Desktop；仓库 D。

  **文件**：`packages/dsh-desktop-enterprise/openai.js`；`packages/dsh-desktop-enterprise/responses.js`。

  **逻辑与上下文**：两个适配器沿可选factory在stream开始取得冻结formatter，实际Responses委托不重复捕获；只改变默认安全文案回调归属，不改变分类/编号/租户提示/工具屏障。

  **验证**：通过T144全部配对断言和T118真实工具执行回归。

  **覆盖 AC**: AC-03、AC-30、AC-31、AC-56。

  **依赖**：T144。

- [x] **T146 Desktop 排队语言与公开事件作用域先行测试**

  **类型**：测试 · 外部 Desktop；仓库 D。

  **文件**：`test/enterprise-content-safety-locale-scope.test.mjs`（拟新增）；`test/enterprise-content-safety-locale.test.mjs`（既有）。

  **逻辑与上下文**：只编写helper状态和真实cookie→认证Connection→生产bridge→公开SessionController.queue→实际Agent/adapter双协议测试。insert只记录pending，claim按session/Message.id晋升当前turn；并发/未来入队/在途formatter不互相覆盖，discard/turn-end/dispose/unload回收，不在Message/source/model中写文案。

  **验证**：保留真实第二请求ja却返回zh的RED，helper缺能力先RED；配对T147后两测试全部GREEN。

  **覆盖 AC**: AC-03、AC-30、AC-31、AC-56。

  **依赖**：T145、T118、T140。

### Wave 22

- [x] **T148 默认相对窗口翻页先行回归**

  **类型**：测试 · 后端 Domain/API；仓库 B。

  **文件**：`src/backend/test/dsh/test_content_safety_queries.py`（既有）；`src/backend/test/dsh/test_content_safety_query_api.py`（既有）。

  **逻辑与上下文**：实际Repository及API验证默认7天、最多31天；第二页now推进仍沿相对窗口且不因隐式bounds改变拒绝cursor，显式时间/安全筛选/租户变更仍拒绝。只测试，不在Service解析或重签仓储游标。

  **验证**：仓储缺少窗口端口先RED；配对T149及T040后全部GREEN，保留原窗口与显式绑定断言。

  **覆盖 AC**: AC-45、AC-49、AC-50。

  **依赖**：T038、T039。

- [x] **T149 主审计请求仓储相对窗口适配**

  **类型**：实现 · 后端 Domain；仓库 B。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/model_audit_queries.py`（既有）。

  **逻辑与上下文**：page沿可选now端口在仓储内部计算默认窗口；fingerprint仅绑定用户显式筛选，隐式时间不写入游标，保留旧内部调用无now语义。复用已实现的未关联事件时间窗口约束，不增加Service SQL。

  **验证**：T148仓储配对断言及T037原回归GREEN，T040接线后API配对全部GREEN。

  **承接 AC**: AC-45、AC-49、AC-50。

  **依赖**：T148、T038。

- [x] **T150 旧审计数据库 fixture 事件表补齐**

  **类型**：测试基础设施；仓库 B。

  **文件**：`src/backend/test/dsh/model_audit_fixtures.py`（既有）。

  **逻辑与上下文**：把新增事件模型登记到原AUDIT_MODELS，结构发现及租户测试表集合使用同一tuple。仅补隔离测试schema，不改业务或旧断言。

  **验证**：原广回归缺事件表11项RED转GREEN；SQL回滚和租户fixture恢复保持。

  **覆盖 AC**: AC-03、AC-46。

  **依赖**：T001、T039。

- [x] **T151 旧手工审计记录测试时钟对齐**

  **类型**：测试；仓库 B。

  **文件**：`src/backend/test/dsh/test_model_audit_exact_models.py`（既有）；`src/backend/test/dsh/test_model_audit_user_names.py`（既有）。

  **逻辑与上下文**：仅两个手工插入固定NOW数据的既有测试，将查询clock注入NOW后一秒；保留所有原查询/名字/租户/游标断言，不改共享Harness的真实模型clock或全局NOW。

  **验证**：原过期固定数据导致2项RED转GREEN，广审计回归保持。

  **覆盖 AC**: AC-03、AC-45、AC-49。

  **依赖**：T039、T149。

- [x] **T040 审计查询服务与管理端点扩展**

  **类型**：实现 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/services/model_audit_queries.py`（既有）；`src/backend/bisheng/dsh/api/endpoints/model_audit_admin.py`（既有）。

  **逻辑与上下文**：沿用现有 audit 管理授权，传递安全过滤和 DTO；新增 GET /requests/{id}/content-safety-events、GET /content-safety-events，扩展 /requests、详情和 query-readiness。Service 只编排 Repository，Endpoint 不写 ORM，不增加 Gateway 查询 RPC。

  **验证**：通过配对任务 T039 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-07、AC-08、AC-35、AC-44、AC-45、AC-46、AC-49、AC-50、AC-51。

  **依赖**：T039、T038、T036、T149。

- [x] **T080 共享 HMAC 回传与提交回执校验**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/client/ContentSafetyEventClient.java`（拟新增）。

  **逻辑与上下文**：固定目标 POST /api/v1/internal/dsh/content-safety-events，复用 BishengConfig.gatewayHmacSecret 与 signatureHeader；包装 sent_at/event，METHOD/PATH/raw字节HMAC，小写hex；独立无凭据日志客户端，3秒超时。超时/5xx/429与未就绪继续退避，明确拒绝隔离且不ACK。

  **验证**：通过配对任务 T079 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-35、AC-39、AC-41、AC-42、AC-43、AC-58。

  **依赖**：T079、T018、T036、T078。

- [x] **T096 PathRate 正文日志隔离与公共限流**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/filter/PathRateGlobalFilter.java`（既有）。

  **逻辑与上下文**：仅跳过DSH旧应用正文解析与日志分支，保留普通应用和适用通用限流。DSH并发由请求管理器预算控制；不复制body制造未计入内存缓冲。

  **验证**：通过配对任务 T095 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-05、AC-26、AC-35、AC-54。

  **依赖**：T095、T094。

- [x] **T147 Desktop 按消息入队与实际轮次隔离安全文案**

  **类型**：实现 · 外部 Desktop；仓库 D。

  **文件**：`packages/dsh-desktop-enterprise/content-safety-locale.js`（拟新增）；`packages/dsh-desktop-enterprise/index.js`（既有）。

  **逻辑与上下文**：createContentSafetyLocaleScope(ctx,requestLocale)按现成公开inbox inserted/claimed/discarded及turn结束/agent dispose管理短生命周期旁路状态，formatterFor({sessionId,purpose})在流开始冻结copy；无session及内部title/compaction沿发起请求ALS，卸载幂等清理。无第三方patch/全局last-language/消息持久化字段或模型传参。

  **验证**：通过T146全部断言，原T140/T118与相邻UI/审计回归GREEN。

  **覆盖 AC**: AC-03、AC-30、AC-31、AC-56。

  **依赖**：T146、T145、T117。

### Wave 23

- [x] **T045 会话目录组合过滤同请求核验先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_tree_queries.py`（拟新增）。

  **逻辑与上下文**：只编写测试：同会话上月命中/昨天未命中时最近 7 天命中过滤不得入选；用户/模型/方向组合由同一请求满足；扫描上限不能伪装空结果。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_tree_queries.py -q。

  **覆盖 AC**: AC-45、AC-47、AC-48、AC-49、AC-50。

  **依赖**：T016、T044、T040。

- [x] **T081 多实例领取、重试和确认清理先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshSafetyOutboxDispatcherTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：多实例同事件竞争、租约超时恢复、进程重启/ACK丢失、错owner不能确认、关闭检查仍发送、未确认不被7天TTL清理。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshSafetyOutboxDispatcherTest test。

  **覆盖 AC**: AC-39、AC-41、AC-43、AC-51、AC-55、AC-58。

  **依赖**：T016、T080。

- [x] **T102 Platform 策略及事件 API wrapper**

  **类型**：实现 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/src/controllers/API/dshContentSafety.ts`（拟新增）；`src/frontend/platform/src/controllers/API/dshModelAudit.ts`（既有）。

  **逻辑与上下文**：使用封装request调用Gateway settings/capabilities与backend新增事件接口，补全groupQuery安全过滤；校验Gateway ResultData业务状态及DTO nullable字段。沿用403拦截器、AbortSignal和既有审计no-store，不在store或组件直接导入axios。

  **验证**：合成HTTP响应验证200业务失败、409版本冲突、Gateway不可达/未部署及旧后端响应兼容；不把无命中解释通过。

  **承接 AC**: AC-06、AC-07、AC-10、AC-44、AC-45、AC-46。

  **依赖**：T040、T068、T099、T100、T101。

### Wave 24

- [x] **T154 Platform 共享组件 workspace 依赖接入**

  **类型**：基础设施；仓库 B。

  **文件**：`src/frontend/platform/package.json`（既有）；`src/frontend/pnpm-lock.yaml`（既有，生成）。

  **逻辑与上下文**：按现行根AGENTS仅补本仓已有@bisheng/ui workspace:^本地直接依赖，保留全部第三方锁定版本与旧UI/state依赖。不引入新第三方UI库。

  **验证**：离线依赖解析成功、锁文件无无关升级、现有Platform类型/目标lint通过。

  **承接 AC**: AC-03、AC-56。

  **依赖**：T102。

- [x] **T155 Platform 敏感词界面共享样式隔离接入**

  **类型**：基础设施；仓库 B。

  **文件**：`src/frontend/platform/vite.config.mts`（既有）；`src/frontend/platform/src/style/dsh-content-safety.css`（拟新增）。

  **逻辑与上下文**：构建时从共享tokens/preset与真实组件源码生成本功能容器作用域CSS，沿原值与主题规则，不复制维护设计变量、不改全站Tailwind主题。组件仅在独立dsh-content-safety容器内使用，原页面root变量/旧utility不被覆盖。

  **验证**：实际Vite/CSS编译、主题/键帧与选择器隔离、原平台变量对照，以及真实组件预览后再验收UI任务；JSDOM不能代样式编译。

  **承接 AC**: AC-03、AC-56。

  **依赖**：T154。

- [x] **T046 会话目录组合过滤同请求核验**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/model_audit_conversations.py`（既有）；`src/backend/bisheng/dsh/domain/repositories/model_audit_tree_queries.py`（既有）。

  **逻辑与上下文**：会话/目录安全筛选以汇总索引产生候选，按有界请求核验完整条件；达到预算返回 scan_limited，区分全量计数与已实际计算的筛选计数。仅修改查询方法，保留前驱投影增量逻辑。

  **验证**：通过配对任务 T045 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-45、AC-47、AC-48、AC-49、AC-50。

  **依赖**：T045、T044、T040。

- [x] **T152 会话组与目录默认窗口 API 接线回归**

  **类型**：测试 · 后端 API；仓库 B。

  **文件**：`src/backend/test/dsh/test_content_safety_group_query_api.py`（拟新增）。

  **逻辑与上下文**：真实管理API/Service/Repository验证组、目录与组内请求默认7天/max31，查询clock可控，默认时钟推进不绑定成显式筛选；保留授权及同请求安全过滤。测试复用现有隔离fixture与真实投影，不填生产算法。

  **验证**：T046端口完成后先形成缺Service时钟接线RED，再T153转GREEN；不以Repository直调代API接线。

  **覆盖 AC**: AC-45、AC-49、AC-50。

  **依赖**：T039、T046。

- [x] **T153 会话查询服务传递窗口时钟**

  **类型**：实现 · 后端 API；仓库 B。

  **文件**：`src/backend/bisheng/dsh/domain/services/model_audit_queries.py`（既有）。

  **逻辑与上下文**：仅组/树/组内请求实际查询向既有Repo端口传self.now()；Service不注默认上下界、不解析或签发游标，不改原内部无now查询。location保持独立定位语义。

  **验证**：通过T152 API与T045原回归及旧审计回归。

  **承接 AC**: AC-45、AC-49、AC-50。

  **依赖**：T152、T046。

- [x] **T156 两条既有组树 API 固定日期夹具校时**

  **类型**：测试维护；仓库 B。

  **文件**：`src/backend/test/dsh/test_model_audit_groups.py`（既有）；`src/backend/test/dsh/test_model_audit_tree_http.py`（既有）。

  **逻辑与上下文**：各仅手工固定NOW建记录的一个HTTP测试注入查询now=NOW+1秒，原业务断言不变。不改全局Harness、模型调用时钟或生产默认窗口。

  **验证**：保留T153后原两项RED证据，修后原断言及新窗口/相邻审计回归通过。

  **覆盖 AC**: AC-45、AC-49、AC-50。

  **依赖**：T152。

- [x] **T082 多实例领取、重试和确认清理**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/service/DshSafetyOutboxDispatcher.java`（拟新增）。

  **逻辑与上下文**：按最多100条/30秒租约有限并发投递，保证单批耗时与续租/逐条领取匹配；退避1秒至5分钟带抖动。只正确回执标ACKED；ACKED初始保留7天，未确认/隔离磁盘高水位告警，不自动丢弃；Spring生命周期独立于模型请求及检查开关。

  **验证**：通过配对任务 T081 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-39、AC-41、AC-43、AC-51、AC-55、AC-58。

  **依赖**：T081、T080。

- [x] **T103 策略表单与取数 hook**

  **类型**：实现 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/src/pages/SystemPage/dsh/DshContentSafetySettings.tsx`（拟新增）；`src/frontend/platform/src/pages/SystemPage/dsh/useDshContentSafety.ts`（拟新增）。

  **逻辑与上下文**：新命名导出组件：词源/输入输出/提示以Checkbox和保存按钮原子提交，expected_version冲突保留草稿并提示刷新，显示5秒新请求生效说明。若独立Switch则即时提交/等待锁定/失败回弹。设置组件内提供局部v4 QueryClientProvider，由子组件消费hook，使用本特性QueryClient与tenant_id查询键；不更换全站v3 Provider。Gateway不可达明确不可用。

  **验证**：用租户A/B管理员和超管切换目标、保存空词/无提示/冲突版本、关闭再启用和Gateway离线；仅落地组件，无新样式/状态库，空id不传SelectItem；运行组件测试确认不存在No QueryClient或v3/v4上下文混用。

  **承接 AC**: AC-02、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-55、AC-56。

  **依赖**：T102、T015、T154、T155。

- [x] **T105 请求安全筛选控件**

  **类型**：实现 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditFilters.tsx`（既有）。

  **逻辑与上下文**：加入是否命中、INPUT/OUTPUT/BOTH和六态筛选，BOTH文案明确两方向均命中；与用户/模型/时间一起提交，显式条件变化清游标/缓存。不增加默认时间窗口冻结或查询会话。

  **验证**：组合选择、重置、翻页和超过31天提示；空id过滤后再渲染SelectItem，不写单独403处理。

  **承接 AC**: AC-34、AC-45、AC-49、AC-50、AC-56。

  **依赖**：T102、T154、T155。

- [x] **T106 请求标签及安全详情组件**

  **类型**：实现 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditCard.tsx`（既有）；`src/frontend/platform/src/pages/SystemPage/dsh/ContentSafetyDetails.tsx`（拟新增）。

  **逻辑与上下文**：状态用已落地Tag，显示输入/输出与汇总；模型成功和输出BLOCKED可并存。详情分页读取事件、策略/词库摘要和三种时间，显示PURGED/未观测/不适用；外部条目不展示不存在的原文入口，未知usage不渲染成0。

  **验证**：输入阻断、输出命中成功计量、无事件、缺结果、明细清理和只保存metadata六类记录逐一展示。

  **承接 AC**: AC-32、AC-34、AC-36、AC-44、AC-46、AC-51、AC-56。

  **依赖**：T102、T154、T155。

### Wave 25

- [x] **T047 安全投影任务与 Celery 注册先行测试**

  **类型**：测试 · Worker；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_worker.py`（拟新增）。

  **逻辑与上下文**：只编写测试：真实 Celery task dispatch 恢复租户、缺失或不匹配 header 拒绝、重试/租约回收、单进程退出可续做、停用租户历史补报。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；Worker fixture通过tenant_id参数和Celery headers→ContextVar调度真实任务，不以直接调用task正文替代信号恢复验证；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_worker.py -q。

  **覆盖 AC**: AC-39、AC-41、AC-47、AC-48、AC-53、AC-55。

  **依赖**：T016、T046。

- [x] **T097 检查与补报的有限诊断指标先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshSafetyTelemetryTest.java`（拟新增）。

  **逻辑与上下文**：只编写测试：缓存合并/错误、策略摘要不一致、缓冲/续读、Outbox最老年龄/隔离/丢失、密钥和正文不入日志、无用户/事件ID无限维度标签。测试上下文：G 仓库 JUnit 5、Mockito 和现有 Reactor Netty 测试服务器；使用合成 Bearer、可控时钟及内存端口，不访问真实账户；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：G: mvn -Dtest=DshSafetyTelemetryTest test。

  **覆盖 AC**: AC-14、AC-18、AC-19、AC-26、AC-35、AC-43、AC-48、AC-58。

  **依赖**：T016、T082、T096。

- [x] **T165 DSH 导航既有测试维护**

  **类型**：测试维护；仓库 B。

  **文件**：`src/frontend/platform/src/pages/DshPage/dshPageNavigation.test.tsx`（既有）。

  **逻辑与上下文**：原固定五个tab计数更新为含安全控制入口的六个，并增该入口URL/可见性断言。保留原审计、访问设置、插件、旧隐藏tab回退全部断言；不mock新业务判定。

  **验证**：保留旧计数RED证据，实际导航及原断言通过；新表单/权限边界由T104独立真实组件探针补验。

  **覆盖 AC**: AC-03、AC-06、AC-07、AC-56。

  **依赖**：T103。

- [x] **T104 DSH 管理入口接入安全配置**

  **类型**：实现 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/src/pages/DshPage/sections.ts`（既有）；`src/frontend/platform/src/pages/DshPage/index.tsx`（既有）。

  **逻辑与上下文**：沿既有租户管理和DSH导航接入敏感词控制，复用当前目标租户上下文；无Gateway配置区域不可用但模型/额度/原审计可访问。仅消费前驱新组件，保留既有路由出口契约与其他tab。首次进入后切tab保留挂载和未保存草稿；未首访不取数，身份/租户/部署禁用仍隔离卸载。窄宽仅外容器横滚，不改共享Tabs视觉。

  **验证**：平台现有/dsh入口打开/切租户/退回原tab；非管理员沿原准入拒绝，模块新文案三语可见。

  **承接 AC**: AC-03、AC-06、AC-07、AC-56。

  **依赖**：T103。

- [x] **T107 请求取数与页面状态接线**

  **类型**：实现 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/src/pages/SystemPage/dsh/useModelAudit.ts`（既有）；`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditPanel.tsx`（既有）。

  **逻辑与上下文**：把安全过滤/nullableDTO/详情传到现有列表与组件，显式条件变化清游标；刷新保持原有分页方式。页面单文件保持≤600行，新增安全展示由前驱组件承担，不扩大Panel职责。

  **验证**：检查loading/error/empty、上一页/下一页、租户切换取消旧请求、后到补报刷新及无Gateway旧列表。

  **承接 AC**: AC-03、AC-44、AC-45、AC-49、AC-50、AC-56。

  **依赖**：T105、T106。

### Wave 26

- [x] **T166 安全dirty租户扫描端口先行测试**

  **类型**：测试 · 后端 Domain；仓库 B。

  **文件**：`src/backend/test/dsh/test_content_safety_tree.py`（既有）。

  **逻辑与上下文**：仅GroupPending但hierarchy已索引/已发布的迟到命中租户必须被新扫描端口发现；模型RUNNING但无dirty不入选。验证Tenant目录驱动、相关EXISTS只枚举dirty ID、100条游标、停用/归档租户及原tree_pending_tenants默认兼容。

  **验证**：真实Repo/SQL缺可选group pending端口先RED，原目录测试保持GREEN；不在Worker内写SQL或使用全量运行请求租户替代dirty扫描。

  **覆盖 AC**: AC-39、AC-47、AC-48、AC-53、AC-55。

  **依赖**：T047、T046。

- [x] **T167 安全dirty租户扫描端口实现**

  **类型**：实现 · 后端 Domain；仓库 B。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/model_audit_hierarchy.py`（既有）。

  **逻辑与上下文**：tree_pending_tenants新增可选include_group_pending=False，原默认不变，True时同一有界元数据扫描包含Request.group_index_pending。仅跨租户读取待处理租户编号，处理仍由Worker回到严格作用域，无正文/事实全聚合。

  **验证**：通过T166及原目录/安全查询回归，100条keyset且未更改默认旧调用行为。

  **承接 AC**: AC-39、AC-47、AC-48、AC-53、AC-55。

  **依赖**：T166、T046。

- [x] **T048 安全投影任务与 Celery 注册**

  **类型**：实现 · Worker；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/worker/dsh/content_safety.py`（拟新增）；`src/backend/bisheng/worker/dsh/registry.py`（既有）。

  **逻辑与上下文**：注册 dsh.project_content_safety 与有界扫描任务，使用默认 celery 队列。投递 args 中 tenant_id 且 headers={tenant_id:同值}，task_prerun headers→ContextVar，任务核对参数并进入严格 profile_scope，finally 恢复；SQL 线程重新建作用域。跨租户枚举只取 dirty IDs，不能只取 active tenant。

  **验证**：通过配对任务 T047 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-39、AC-41、AC-47、AC-48、AC-53、AC-55。

  **依赖**：T047、T046、T167。

- [x] **T098 检查与补报的有限诊断指标**

  **类型**：实现 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/main/java/com/dataelem/gateway/service/DshSafetyTelemetry.java`（拟新增）；`src/main/java/com/dataelem/gateway/service/DshSafetyOutboxDispatcher.java`（拟新增）。

  **逻辑与上下文**：增加受控聚合计数和安全日志字段；指标接入已有监控方式，无现成Prometheus导出时使用现有日志/健康能力，不新增依赖。Dispatcher仅增量调用遥测，不改前驱投递语义。

  **验证**：通过配对任务 T097 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-14、AC-18、AC-19、AC-26、AC-35、AC-43、AC-48、AC-58。

  **依赖**：T097、T082、T096。

- [x] **T157 身份缓存与profile有界诊断先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshIdentityTelemetryTest.java`（拟新增）。

  **逻辑与上下文**：真实L1/共享命中与miss、Redis失败、同Token合并、有限队列拒绝与active/queued/latency观察；取消/超时不重复计数，不改变profile次数、租约、deadline或模型身份。执行原生产对象的实际端口后断言共享Telemetry，不能仅手工increment冒称已接线；观测不可影响原结果、异常或资源预算。

  **验证**：无实际observer接线先RED、原相邻行为GREEN；配对T158后转GREEN。

  **覆盖 AC**: AC-14、AC-18、AC-19。

  **依赖**：T098。

- [x] **T158 身份缓存与profile有界诊断接线**

  **类型**：实现 · 外部 Gateway；仓库 G。

  **文件**：`src/main/java/com/dataelem/gateway/service/DshIdentityCache.java`（既有）；`src/main/java/com/dataelem/gateway/service/DshProfileVerifier.java`（既有）。

  **逻辑与上下文**：真实L1/共享命中与miss、Redis失败、同Token合并、有限队列拒绝与active/queued/latency观察；取消/超时不重复计数，不改变profile次数、租约、deadline或模型身份。保留旧构造器兼容并补可注入Telemetry端口，Spring由T139注入同一实例。只做有限枚举/标量观测，不新增依赖或用户维度历史，不记录Throwable正文。

  **验证**：T157及原相邻测试通过，额外profile/SQL/上游调用为0；资源释放/取消行为保持。

  **承接 AC**: AC-14、AC-18、AC-19。

  **依赖**：T157、T098。

- [x] **T159 策略与匹配器有界诊断先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshPolicyTelemetryTest.java`（拟新增）。

  **逻辑与上下文**：真实缓存年龄/摘要不一致、编译容量拒绝和active观察；读写CAS、5秒生效、缓存权重和匹配语义不变，不因观测重编译或增加SQL。执行原生产对象的实际端口后断言共享Telemetry，不能仅手工increment冒称已接线；观测不可影响原结果、异常或资源预算。

  **验证**：无实际observer接线先RED、原相邻行为GREEN；配对T160后转GREEN。

  **覆盖 AC**: AC-18、AC-19、AC-26。

  **依赖**：T098。

- [x] **T160 策略与匹配器有界诊断接线**

  **类型**：实现 · 外部 Gateway；仓库 G。

  **文件**：`src/main/java/com/dataelem/gateway/service/DshSensitivePolicyService.java`（既有）；`src/main/java/com/dataelem/gateway/service/DshSensitiveMatcherCache.java`（既有）。

  **逻辑与上下文**：真实缓存年龄/摘要不一致、编译容量拒绝和active观察；读写CAS、5秒生效、缓存权重和匹配语义不变，不因观测重编译或增加SQL。保留旧构造器兼容并补可注入Telemetry端口，Spring由T139注入同一实例。只做有限枚举/标量观测，不新增依赖或用户维度历史，不记录Throwable正文。

  **验证**：T159及原相邻测试通过，额外profile/SQL/上游调用为0；资源释放/取消行为保持。

  **承接 AC**: AC-18、AC-19、AC-26。

  **依赖**：T159、T098。

- [x] **T161 请求与持久录制有界诊断先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshRequestTelemetryTest.java`（拟新增）。

  **逻辑与上下文**：实际检查命中/错误、全局编码缓冲及检查/续读额度、SQL录制缺口；只从原锁或原原子计数读取标量，所有退出释放后的gauge准确，不重订模型或读取/记录正文。执行原生产对象的实际端口后断言共享Telemetry，不能仅手工increment冒称已接线；观测不可影响原结果、异常或资源预算。

  **验证**：无实际observer接线先RED、原相邻行为GREEN；配对T162后转GREEN。

  **覆盖 AC**: AC-26、AC-35、AC-43、AC-58。

  **依赖**：T098。

- [x] **T162 请求与持久录制有界诊断接线**

  **类型**：实现 · 外部 Gateway；仓库 G。

  **文件**：`src/main/java/com/dataelem/gateway/service/DshSafetyRequestManager.java`（既有）；`src/main/java/com/dataelem/gateway/service/DshSafetyOutboxService.java`（既有）。

  **逻辑与上下文**：实际检查命中/错误、全局编码缓冲及检查/续读额度、SQL录制缺口；只从原锁或原原子计数读取标量，所有退出释放后的gauge准确，不重订模型或读取/记录正文。保留旧构造器兼容并补可注入Telemetry端口，Spring由T139注入同一实例。只做有限枚举/标量观测，不新增依赖或用户维度历史，不记录Throwable正文。

  **验证**：T161及原相邻测试通过，额外profile/SQL/上游调用为0；资源释放/取消行为保持。

  **承接 AC**: AC-26、AC-35、AC-43、AC-58。

  **依赖**：T161、T098。

- [x] **T163 检查入口失败有限诊断先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshPreflightTelemetryTest.java`（拟新增）。

  **逻辑与上下文**：身份/策略/license/capacity入口拒绝有限计数，不用tenant/user/request/event等高基数标签，不变部署关闭/租户关闭与原错误优先级。执行原生产对象的实际端口后断言共享Telemetry，不能仅手工increment冒称已接线；观测不可影响原结果、异常或资源预算。

  **验证**：无实际observer接线先RED、原相邻行为GREEN；配对T164后转GREEN。

  **覆盖 AC**: AC-14、AC-18、AC-19、AC-35。

  **依赖**：T098、T096。

- [x] **T164 检查入口失败有限诊断接线**

  **类型**：实现 · 外部 Gateway；仓库 G。

  **文件**：`src/main/java/com/dataelem/gateway/filter/DshContentSafetyFilter.java`（既有）。

  **逻辑与上下文**：身份/策略/license/capacity入口拒绝有限计数，不用tenant/user/request/event等高基数标签，不变部署关闭/租户关闭与原错误优先级。保留旧构造器兼容并补可注入Telemetry端口，Spring由T139注入同一实例。只做有限枚举/标量观测，不新增依赖或用户维度历史，不记录Throwable正文。

  **验证**：T163及原相邻测试通过，额外profile/SQL/上游调用为0；资源释放/取消行为保持。

  **承接 AC**: AC-14、AC-18、AC-19、AC-35。

  **依赖**：T163、T098。

### Wave 27

- [x] **T049 Beat 调度与查询安全水位接线先行测试**

  **类型**：测试 · Worker；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_schedule.py`（拟新增）。

  **逻辑与上下文**：只编写测试：Beat 注册一次并投递各 dirty 租户；API/worker 分进程可见安全水位；无 Gateway、无接收密钥仍可启动原模型及审计。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；Worker fixture通过tenant_id参数和Celery headers→ContextVar调度真实任务，不以直接调用task正文替代信号恢复验证；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_schedule.py -q。

  **覆盖 AC**: AC-03、AC-39、AC-48、AC-55。

  **依赖**：T016、T048。

- [x] **T138 Gateway Spring 组装与关闭兼容先行测试**

  **类型**：测试 · 外部 Gateway；仓库 G。

  **文件**：`src/test/java/com/dataelem/gateway/config/DshSafetyBeansConfigurationTest.java`（拟新增）。

  **逻辑与上下文**：以真实Spring Context验证profile/cache/policy/request manager/两个filter/事件client/dispatcher/telemetry实际组装、单例所有权和close生命周期；完整配置但检查关闭仍可管理策略及投递历史事实；无新配置不初始化新依赖、不影响旧模型/审计，capabilities明确不可用。配置沿现有Bisheng/Redis/IO预算，不另造密钥或回传目标。测试不得仅手工new对象代替容器接线。

  **验证**：G: mvn -Dtest=DshSafetyBeansConfigurationTest test；缺组装形成实际红测，相邻旧启动/路由对照保留。

  **覆盖 AC**: AC-01、AC-02、AC-03、AC-05、AC-26、AC-39、AC-41、AC-43、AC-54、AC-55。

  **依赖**：T098、T090、T092、T094、T096、T158、T160、T162、T164。

### Wave 28

- [x] **T050 Beat 调度与查询安全水位接线**

  **类型**：实现 · Worker；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/worker/config.py`（既有）；`src/backend/bisheng/dsh/audit_admin_runtime.py`（既有）。

  **逻辑与上下文**：把扫描任务加入既有 Beat 配置，审计 query-readiness 暴露安全进度。worker tenant_id 始终通过 Celery headers→ContextVar，实际处理再建严格作用域；新回传配置不成为原 DSH runtime 启动依赖。

  **验证**：通过配对任务 T049 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-03、AC-39、AC-48、AC-55。

  **依赖**：T049、T048。

- [x] **T139 Gateway Spring 条件组装与生命周期**

  **类型**：实现 · 外部 Gateway；仓库 G。

  **文件**：`src/main/java/com/dataelem/gateway/config/DshSafetyBeansConfiguration.java`（拟新增）；`src/main/java/com/dataelem/gateway/service/DshSafetyOutboxService.java`（既有，仅组装所有权标注）。

  **逻辑与上下文**：在单一配置入口接通已有生产构造端口，固定同backend目标、既有共享HMAC和UTC时钟，复用Redis及原IO预算；匹配器、cache监听、请求owner、补报器按Spring生命周期启动与关闭。缺配置不创建不必要的新依赖；检查关闭与补报生命周期独立，配置/管理可用性保持明确。禁止以@Configuration文件存在或手动构造测试替代真实Bean验证。移除Outbox既有@Service自动扫描，保持旧构造兼容，仅由配置创建唯一实际observer实例；不以@Primary或RegistryPostProcessor掩盖重复实例。

  **验证**：通过T138全部断言及原路由/关闭配置回归；复核两个filter实际顺序和每副本唯一manager。

  **承接 AC**: AC-01、AC-02、AC-03、AC-05、AC-26、AC-39、AC-41、AC-43、AC-54、AC-55。

  **依赖**：T138、T098。

### Wave 29

- [x] **T051 明细清理与防复活保留闸门先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_retention.py`（拟新增）。

  **逻辑与上下文**：只编写测试：默认不清明细、删明细保留摘要、先落删除水位再分批清主行、排除执行中记录、已存在旧主行可补事实、过期重建 410、mode/version 并发不覆盖水位。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_retention.py -q。

  **覆盖 AC**: AC-39、AC-41、AC-43、AC-48、AC-51、AC-52、AC-53。

  **依赖**：T016、T038、T050。

- [x] **T108 会话及目录安全摘要**

  **类型**：实现 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditGroup.tsx`（既有）；`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditTree.tsx`（既有）。

  **逻辑与上下文**：展示own/branch去重命中计数、安全更新时间和PREPARING/scan_limited。全量条目数与筛选命中数区分，未实际计算不显示虚假0；计数用Badge，状态用Tag，沿既有布局。

  **验证**：父子会话命中传播、worker停用、长会话扫描受限、时间内无命中而历史有命中的组合查询。

  **承接 AC**: AC-45、AC-47、AC-48、AC-56。

  **依赖**：T107、T046、T050。

### Wave 30

- [x] **T052 明细清理与防复活保留闸门**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/content_safety_maintenance.py`（拟新增）；`src/backend/bisheng/dsh/domain/repositories/model_audit_setting.py`（既有）。

  **逻辑与上下文**：提供 rebuild_batch 与 purge_batch 的有界 Repository 操作；明细窗口必须由已确认运维参数提供。按 tenant/id/版本更新；默认不开放离散裸删，需要时先 tombstone；事实不可回放后不承诺重建。

  **验证**：通过配对任务 T051 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-39、AC-41、AC-43、AC-48、AC-51、AC-52、AC-53。

  **依赖**：T051、T038、T050。

- [x] **T109 未关联安全事件入口**

  **类型**：实现 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/src/pages/SystemPage/dsh/UnassociatedSafetyEvents.tsx`（拟新增）；`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditPanel.tsx`（既有）。

  **逻辑与上下文**：增加命名导出的未关联事件列表，沿现有审计权限展示时间、Gateway/backend编号、阶段和策略摘要；限长分页。Panel仅增量接入口，并把父page.progress传入T108的Group/Tree可选进度prop（子树用已有子页progress），不增加逐行GET；不与主请求行混算模型调用或用量，不把真实身份变化当不可信错误。

  **验证**：未知模型编号、可信身份变化不可关联、历史补报和其他租户访问隔离；保持其他列表筛选。

  **承接 AC**: AC-37、AC-38、AC-42、AC-45、AC-46、AC-56。

  **依赖**：T108。

- [x] **T170 Shared UI开发依赖解析兼容**

  **类型**：基础设施 · 前端 Platform；仓库 B。

  **文件**：`src/frontend/platform/vite.config.mts`（既有）。

  **逻辑与上下文**：正式Vite dev预优化把UI目录的catalog tailwind-merge 1.14错解为Platform 2.6，导致Badge/Tag字号class被删除；生产Rollup不复现。仅限定shared UI的嵌套依赖预优化/解析，保留各包锁定版本，不加库/改共享组件或设计值，不全站升级或给业务组件覆盖样式。

  **验证**：先保留正式配置实际DOM 12px错误证据，修后同真实helper/Badge/Tag dev为设计10px/12px；生产三语/390预览、旧Platform自身merge语义和scope样式不变，配置新增类型诊断为0。

  **承接 AC**: AC-45、AC-56。

  **依赖**：T155、T108。

### Wave 31

- [x] **T053 审计回填清理运维入口先行测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_maintenance_cli.py`（拟新增）。

  **逻辑与上下文**：只编写测试：dry-run 无写入、apply 需显式参数、批次与续跑游标、环境/租户错误退出、保留规则不默认缩短。测试上下文：B 仓库 test/dsh 的租户 101/202、用户 11/22、模型 7/8 合成 fixture；数据库/时钟/对象存储按需要替换，真实双库另验收；被测边界为下个配对实现任务公开的方法或类，缺失能力先形成红测，不填入生产实现。

  **验证**：B: cd src/backend && uv run pytest test/dsh/test_content_safety_maintenance_cli.py -q。

  **覆盖 AC**: AC-43、AC-48、AC-51、AC-52、AC-53。

  **依赖**：T016、T052。

- [x] **T110 Platform 设置与审计行为验证**

  **类型**：测试 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`src/frontend/platform/src/pages/SystemPage/dsh/DshContentSafetySettings.test.tsx`（拟新增）；`src/frontend/platform/src/pages/SystemPage/dsh/ContentSafetyDetails.test.tsx`（拟新增）。

  **逻辑与上下文**：只增加组件行为测试：CAS冲突保草稿、Gateway不可达、非法空id不崩溃、六态与未知用量、BOTH交集文案、明细清理、显式筛选清游标；使用mock API与现有测试工具，不把mock当E2E。

  **验证**：B: cd src/frontend && pnpm --filter bisheng test -- src/pages/SystemPage/dsh/DshContentSafetySettings.test.tsx src/pages/SystemPage/dsh/ContentSafetyDetails.test.tsx。

  **覆盖 AC**: AC-02、AC-07、AC-09、AC-10、AC-34、AC-44、AC-45、AC-46、AC-49、AC-51、AC-56。

  **依赖**：T104、T109、T170。

- [x] **T168 原生审计与接收端删除水位接线先行测试**

  **类型**：测试 · 后端 Domain；仓库 B。

  **文件**：`src/backend/test/dsh/test_model_audit_retention_guard.py`（拟新增）。

  **逻辑与上下文**：真实原生writer与安全事实接收端统一租户setting→request锁序；缺setting先建立唯一默认锁行，不让首次cleanup与旧主创建交错越过水位。缺主旧事件拒绝、边界及仍存在合法旧主允许、租户隔离/事务回滚/默认mode/version不改；既有receipt优先语义保留。顺序与故障注入不代双库并发。

  **验证**：未接线先实际RED，相邻writer/ingest GREEN；配对T169后转绿，真实锁竞争留T119。

  **覆盖 AC**: AC-41、AC-52、AC-53。

  **依赖**：T052。

- [x] **T171 冷启动测试模块隔离维护**

  **类型**：测试维护 · 后端 Domain；仓库 B。

  **文件**：`src/backend/test/dsh/test_content_safety_runtime.py`（既有）。

  **逻辑与上下文**：T031在当前进程删除sys.modules后重导，pytest撤销只恢复模块表而不恢复父package属性/endpoint别名，组合顺序实际36FAIL，HEAD原Setting同样复现。仅把真实冷启动/禁止模型runtime导入检查隔离到子进程，保留惰性组装和session零调用断言；不改API fixture、生产源或放宽HTTP断言。

  **验证**：同runtime→ingest→API→middleware顺序先保留36FAIL证据，修后全绿；单独冷启动子进程检查与Ruff/架构守卫通过。

  **覆盖 AC**: AC-03、AC-26、AC-35、AC-42、AC-43。

  **依赖**：T032、T034。

- [x] **T172 Gateway 生产JSON配置契约先行测试**

  **类型**：测试 · Gateway；仓库 G。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshSafetyOutboxServiceTest.java`（既有）；`src/test/java/com/dataelem/gateway/controller/DshSensitivePolicyControllerTest.java`（既有）。

  **逻辑与上下文**：真实SpringCustomConfig.objectMapper的null→空串设置会使Outbox缺backend/session/conversation被B严格DTO拒绝，capabilities不可用时digest也被Platform拒绝。使用真实生产mapper/codec保留SQL/admin外端口替身，断事件JSON null、hash/标量类型/共享mapper不变及capabilities真实HTTP null；不放宽接收DTO。

  **验证**：先复现真实配置RED，配对修复转绿并验证Java真实payload可过B严格schema；保留既有应用JSON行为。

  **覆盖 AC**: AC-02、AC-35、AC-39、AC-41、AC-42、AC-58。

  **依赖**：T139。

- [x] **T174 未关联UUID筛选规范化先行测试**

  **类型**：测试 · 后端 Domain；仓库 B。

  **文件**：`src/backend/test/dsh/test_content_safety_queries.py`（既有）。

  **逻辑与上下文**：真实已存UUID为lower，UI明确支持大写，使用真实查询验证Gateway/backend UUID大小写等价、相同规范筛选跨页可续，非法UUID安全拒绝；不冻结默认时间范围或弱化租户隔离。

  **验证**：原实现大写精确匹配实际RED，配对修复全绿；SQLite只作比较语义，不当DM8结果。

  **覆盖 AC**: AC-37、AC-38、AC-42、AC-46、AC-49。

  **依赖**：T109、T040。

### Wave 32

- [x] **T054 审计回填清理运维入口**

  **类型**：实现 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/scripts/dsh_content_safety_maintenance.py`（拟新增）；`src/backend/scripts/README.md`（既有）。

  **逻辑与上下文**：提供 argparse 子命令 rebuild/purge-details/purge-audit，默认 dry-run，--apply 显式写入且携带 tenant-id/batch/cursor。复用服务 settings 和数据库，不在 Alembic 做数据操作；纯 DB 不初始化其他中间件。模块 docstring、自举 import 与 README 给出从 src/backend 的命令，处理进程有严格租户上下文。

  **验证**：通过配对任务 T053 的全部断言；保留相邻现有测试。

  **承接 AC**: AC-43、AC-48、AC-51、AC-52、AC-53。

  **依赖**：T053、T052。

- [x] **T169 原生审计与接收端删除水位接线**

  **类型**：实现 · 后端 Domain；仓库 B。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/model_audit_write.py`（既有）；`src/backend/bisheng/dsh/domain/repositories/content_safety.py`（既有）。

  **逻辑与上下文**：复用T052 SettingRepository.lock_retention()建立/锁定租户水位行，先setting再request；不存在主行且started_at早于水位禁止重建，已有有效主可继续接收事实。冲突由原caller新事务重试，不在Repo commit、旁路Session或扩大tenant scope；不改变原模型鉴权/额度/计量或原生审计身份规则。

  **验证**：T168及旧writer/接收回归通过；未配双库的并发结果如实留待T119。

  **承接 AC**: AC-41、AC-52、AC-53。

  **依赖**：T168、T052。

- [x] **T173 Gateway 局部JSON契约隔离**

  **类型**：实现 · Gateway；仓库 G。

  **文件**：`src/main/java/com/dataelem/gateway/service/DshSafetyOutboxService.java`（既有）；`src/main/java/com/dataelem/gateway/controller/DshSensitivePolicyController.java`（既有）。

  **逻辑与上下文**：Outbox私有mapper保持标准JSON null而不修改注入全局mapper，事件/hash/HMAC字节不在投递时重写。capabilities局部明确nullable digest序列化，保持全局旧应用serializer与管理/模型协议不变，不用B/Platform接受空串掩盖。

  **验证**：T172全绿及真实配置payload→B schema通过，全部定向Gateway回归。

  **承接 AC**: AC-02、AC-35、AC-39、AC-41、AC-42、AC-58。

  **依赖**：T172、T139。

- [x] **T175 未关联UUID查询规范化**

  **类型**：实现 · 后端 Domain；仓库 B。

  **文件**：`src/backend/bisheng/dsh/domain/repositories/content_safety_queries.py`（既有）。

  **逻辑与上下文**：仅两UUID显式filter校验完整UUID并lower，cursor绑定同一规范值；保留tenant/query/time语义、索引谓词不在列上调用lower，不改变已确认默认分页窗口取舍。

  **验证**：T174及旧查询/HTTP回归全绿，错误固定安全文案。

  **承接 AC**: AC-37、AC-38、AC-42、AC-46、AC-49。

  **依赖**：T174、T109。

### Wave 33

- [ ] **T119 MySQL/DM8 事务与迁移集成测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_database_integration.py`（拟新增）；`features/v3.0.0/111-dsh-sensitive-word-control/implementation-verification.md`（拟新增）。

  **逻辑与上下文**：只增加/执行真实数据库集成测试，分别在MySQL及Linux DM8验证模型发现、DDL fresh/upgrade、schema相等、并发去重/回滚、nullable约束、dirty租约及保留水位。空数据库演练结构回退，有数据回退保护不删除事实；结果追加双库节。

  **验证**：在隔离集成环境运行该pytest文件并记录方言/版本/迁移head与通过用例；缺DM8环境为未执行，不用SQLite替代。

  **当前证据**：最终永久测试主独立真实MySQL **16PASS**（58.31s），Linux DM8 **16SKIP/未执行**；fresh/真实归档work110升级/144表反射、实际锁/事务/回退/保留边界已验证MySQL子项，整体保留未勾选。

  **覆盖 AC**: AC-38、AC-39、AC-41、AC-48、AC-51、AC-52、AC-53。

  **依赖**：T054、T050、T082、T169、T030。

### Wave 34

- [ ] **T120 Gateway 双库 Outbox 恢复验证**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshSafetyDatabaseIntegrationTest.java`（拟新增）；`docs/dsh-content-safety-verification.md`（拟新增）。

  **逻辑与上下文**：只做真实MySQL/DM8集成测试：CAS首次创建/更新、多副本领取、租约owner、进程重启、未确认事件保留、明确拒绝隔离、ACK丢失不重复计数，核对两份DDL fresh/upgrade和回退保护；不调用有费用的真实模型。

  **验证**：G: mvn -Dtest=DshSafetyDatabaseIntegrationTest test；独立容器/数据集运行，两种方言分别记录，观察批量领取耗时不超过租约或正确续租。

  **当前证据**：T119 MySQL子闸门后，主在另一全新专用库通过正式Maven **10PASS/0SKIP**，agent独立库同10PASS；真实子JVM退出/租约、HTTP丢ACK及409隔离、双表回退保护通过。DM8未执行，整体保留未勾选；小表EXPLAIN不当容量验收。

  **覆盖 AC**: AC-10、AC-39、AC-41、AC-43、AC-51、AC-53、AC-55、AC-58。

  **依赖**：T098、T119、T139。

### Wave 35

- [ ] **T121 模型协议 API E2E**

  **类型**：测试 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_protocol_e2e.py`（拟新增）；`features/v3.0.0/111-dsh-sensitive-word-control/e2e-checklist.md`（拟新增）。

  **逻辑与上下文**：按/e2e-test skill启动本特性E2E，复用现有模型审计E2E的测试登录与受控上游。测试Chat/Responses×流式/非流式，输入/输出命中、安全回复、可读reasoning、完整历史/内部用途、跨片/最终快照/工具参数、非法输入、检查失败、部署关闭及本地无Gateway。清单只编写协议节，不改后续其他节。

  **验证**：以真实backend/Gateway响应和审计验证输入命中调用0、正常响应顺序不变、输出BLOCKED仍保留实际用量或UNKNOWN；Desktop真实工具屏障证据来自前驱运行时测试。测试环境地址、登录凭据从环境注入。

  **覆盖 AC**: AC-01、AC-02、AC-03、AC-05、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-57。

  **依赖**：T110、T118、T120、T096、T147、T173、T175。

### Wave 36

- [ ] **T122 策略与身份缓存 API E2E**

  **类型**：测试 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_identity_e2e.py`（拟新增）；`features/v3.0.0/111-dsh-sensitive-word-control/e2e-checklist.md`（拟新增）。

  **逻辑与上下文**：只追加身份策略E2E及清单节：A/B租户、管理员/普通用户/超管，读写越权与CAS冲突、空词和提示、词库摘要一致及5秒更新；profile冷/热/刷新/多副本/Redis故障、同凭据首次并发合并、单等待者取消、退出后backend准入拒绝。使用已有合成fixture与受控profile计数，身份变化接受，不增加冻结检查。

  **验证**：逐案记录请求次数、profile验证次数、最终策略版本和错误类型；关闭/失败/过期分开，原始凭据和正文不进日志。

  **覆盖 AC**: AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-35、AC-38、AC-59。

  **依赖**：T121。

### Wave 37

- [ ] **T123 审计事实及补报 API E2E**

  **类型**：测试 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_recovery_e2e.py`（拟新增）；`features/v3.0.0/111-dsh-sensitive-word-control/e2e-checklist.md`（拟新增）。

  **逻辑与上下文**：只追加审计事实/恢复E2E及清单节：OFF/METADATA仍有最小事实、输入外部条目、输出编号/无编号、事件和原审计竞争、同事件异载荷、乱序命中保持、断开接收/重启Gateway/丢ACK后恢复、关闭检查仍投递、明细清理及删除水位。事件同事务ACK且记录不重复计数。

  **验证**：操作均在隔离fixture中，核对SQL持久事件/主摘要/Outbox状态及真实用量；无效服务签名拒绝，历史凭据退出不阻断真实补报。

  **覆盖 AC**: AC-33、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-51、AC-52、AC-53、AC-55、AC-58。

  **依赖**：T122。

### Wave 38

- [ ] **T124 审计页面及目录手工验收**

  **类型**：验收 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`features/v3.0.0/111-dsh-sensitive-word-control/e2e-checklist.md`（拟新增）；`features/v3.0.0/111-dsh-sensitive-word-control/implementation-verification.md`（拟新增）。

  **逻辑与上下文**：只追加页面与隔离节：按测试用户实际打开/dsh，组合命中/方向/状态/用户/模型/7天及31天窗口，详情三个时间/未知/N/A/PURGED，未关联事件、父子目录own/branch、worker停止readiness与scan_limited；三语言设置及Desktop错误实际可见。验证公开入口均经Gateway及旧应用敏感词回归。

  **验证**：以真实API返回和页面操作验证，不以截图或mock替代；跨租户/普通用户拒绝、默认时间翻页沿原行为，清单逐项链接自动测试或手工结果，未执行项不能勾选。

  **覆盖 AC**: AC-04、AC-07、AC-08、AC-34、AC-37、AC-38、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-54、AC-56。

  **依赖**：T123。

### Wave 39

- [ ] **T125 E2E 覆盖与执行结果核对**

  **类型**：验收 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`features/v3.0.0/111-dsh-sensitive-word-control/e2e-checklist.md`（拟新增）；`features/v3.0.0/111-dsh-sensitive-word-control/implementation-verification.md`（拟新增）。

  **逻辑与上下文**：汇总前四项和Desktop运行时证据，逐条核对59条AC的自动/手工覆盖，按/e2e-test流程完成结束报告；仅补完整性与运行结果节，不重复编写前驱用例或修改实现。

  **验证**：执行新增三份HTTP E2E文件并核对页面清单、真实进程重启和双协议工具执行计数；全部结果需有环境/命令/时间证据，无环境为未执行。

  **覆盖 AC**: AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56、AC-57、AC-58、AC-59。

  **依赖**：T124。

### Wave 40

- [ ] **T126 双库审计查询容量测试**

  **类型**：测试 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`src/backend/test/dsh/test_content_safety_query_capacity.py`（拟新增）；`features/v3.0.0/111-dsh-sensitive-word-control/implementation-verification.md`（拟新增）。

  **逻辑与上下文**：只构造隔离容量数据与查询负载：百万/千万主请求、每请求1–3事件、租户倾斜/命中率、组合筛选/深游标/长会话；分别测MySQL/DM8执行计划、扫描行数、p95/p99、锁和索引体积。长时间造数/运行使用可恢复会话，结果只写查询容量节。

  **验证**：与同环境基线比较；默认列表不扫全事件或逐行查询、不做全历史COUNT。暂不编造SLO，实测不足时报告限制，不用SQLite性能代替。

  **覆盖 AC**: AC-26、AC-45、AC-48、AC-49、AC-50、AC-53。

  **依赖**：T125。

- [ ] **T127 profile 冷热和缓存故障负载测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshProfileLoadTest.java`（拟新增）；`docs/dsh-content-safety-verification.md`（拟新增）。

  **逻辑与上下文**：只测profile冷/热/Token刷新、多副本、同键首次并发、单等待者取消和Redis故障；记录额外profile调用量/SQL读取、等待和失败上限，复用现有可控服务器与时钟，不按SSE片段放大验证次数。只追加profile负载节。

  **验证**：G: mvn -Dtest=DshProfileLoadTest test；证明30秒绝对有效期、32/64容量和1秒总预算，记录QPS及未命中率，不把缓存收益误当模型鉴权开销消失。

  **覆盖 AC**: AC-13、AC-14、AC-15、AC-18、AC-19、AC-59。

  **依赖**：T125。

- [ ] **T128 Gateway 流式资源和续读负载测试**

  **类型**：测试 · 外部 Gateway；仓库 G；目标约 30 分钟。

  **文件**：`src/test/java/com/dataelem/gateway/service/DshSafetyCapacityTest.java`（拟新增）；`docs/dsh-content-safety-verification.md`（拟新增）。

  **逻辑与上下文**：只测Chat/Responses长流、交错域/工具HOL、首字延迟、64MiB编码预算和实际JVM堆/GC、16检查/8续读、普通取消及命中后30秒终止；记录上游只有一次请求/订阅和DataBuffer/配额回收。只追加流式资源节。

  **验证**：G: mvn -Dtest=DshSafetyCapacityTest test；实测后根据目标堆余量下调预算或按SDD评审调整，不为指标提前释放未检查文本，不声明供应商已停止计费。

  **覆盖 AC**: AC-11、AC-19、AC-26、AC-29、AC-32、AC-43、AC-57。

  **依赖**：T125。

- [ ] **T130 三语生成及前端质量门禁**

  **类型**：验收 · 前端 Platform；仓库 B；目标约 30 分钟。

  **文件**：`features/v3.0.0/111-dsh-sensitive-word-control/implementation-verification.md`（拟新增）。

  **逻辑与上下文**：在前端质量节记录三语言源键与backend错误码覆盖，按唯一生成流程更新api_errors生成物；手改文件仍限本任务声明范围，生成物由命令统一产生并在交付diff单列，不手改。对触及旧硬编码的实现执行提取，对已修复旧违规按规则prune。

  **验证**：B: cd src/frontend && pnpm locales:build；pnpm check-i18n；pnpm --filter @bisheng/locales check；pnpm lint；pnpm typecheck；必要时各app pnpm lint:prune。不得修改suppression扩大基线或新增ts-ignore。

  **覆盖 AC**: AC-03、AC-44、AC-56。

  **依赖**：T110、T125。

### Wave 41

- [ ] **T129 容量证据汇总与支持边界登记**

  **类型**：验收 · 后端 Domain；仓库 B；目标约 30 分钟。

  **文件**：`features/v3.0.0/111-dsh-sensitive-word-control/implementation-verification.md`（拟新增）。

  **逻辑与上下文**：只汇总双库查询、profile和流式三个前驱结果到容量节，记录支持负载、初始预算的实际堆放大、扫描限制和未解决的运行限制，不增加新的SLO或功能要求。

  **验证**：核对两个数据库均有真实计划、深分页/并发写入和续读压力证据；长运行的会话/日志路径可追溯，缺失的环境不写已验证。

  **覆盖 AC**: AC-11、AC-14、AC-15、AC-18、AC-19、AC-26、AC-43、AC-45、AC-48、AC-49、AC-50、AC-53、AC-57、AC-59。

  **依赖**：T126、T127、T128。

### Wave 42

- [ ] **T131 启用、入口封闭与回退演练手册**

  **类型**：验收 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`features/v3.0.0/111-dsh-sensitive-word-control/rollout-runbook.md`（拟新增）；`features/v3.0.0/111-dsh-sensitive-word-control/implementation-verification.md`（拟新增）。

  **逻辑与上下文**：只编写/在隔离环境演练backend schema/DTO→投影worker→平台/Desktop→Gateway默认关闭→测试租户启用的顺序。记录所有公开Chat/Responses入口经Gateway、backend模型端口受信网络、共享HMAC配置/签名头一致、NTP、词库摘要、观察指标。回退先关闭新请求，保留在途快照/未确认投递/模型用量和证据；旧DTO回退须有外部条目兼容证明。

  **验证**：演练账号/主机从环境注入，不在文档保存密钥。检查开启后的旁路访问被网络阻断、停用及恢复后补报继续；本任务不自行授权生产迁移或部署。

  **覆盖 AC**: AC-02、AC-03、AC-04、AC-11、AC-12、AC-16、AC-17、AC-32、AC-43、AC-51、AC-54、AC-55、AC-58。

  **依赖**：T129、T130。

### Wave 43

- [ ] **T132 特性代码审查与交付证据整理**

  **类型**：验收 · 后端 API；仓库 B；目标约 30 分钟。

  **文件**：`features/v3.0.0/111-dsh-sensitive-word-control/code-review.md`（拟新增）；`features/v3.0.0/111-dsh-sensitive-word-control/implementation-verification.md`（拟新增）。

  **逻辑与上下文**：未来实现完成后按/sdd-code-review对真实目标发布线执行特性审查；汇总本地静态/单元、MySQL/DM8、E2E、Desktop工具屏障、性能和回退证据，未执行项明确标记。跨仓库基线与共享文件影响逐项核验，不由features目录或测试计划推断交付。

  **验证**：使用用户届时指定的目标ref，运行任务级/task-review和适用仓库质量检查，记录实际SHA；不得在本轮创建PR、提交、推送或合并。

  **覆盖 AC**: AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-12、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-22、AC-23、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42、AC-43、AC-44、AC-45、AC-46、AC-47、AC-48、AC-49、AC-50、AC-51、AC-52、AC-53、AC-54、AC-55、AC-56、AC-57、AC-58、AC-59。

  **依赖**：T131。

### 交付整合补充（2026-10-24追加授权）

下列为合入最新work120所需的兼容维护，不改变已确认租户/HMAC/分页/可信身份语义。原Wave1–43证据按当时基线保留。新增交付顺序：T176/T177/T178并行、T181/T182/T183/T184、T179、T180；DM8与完整环境结果分别记账。用户本次授权测试环境部署后补真实客户端/E2E验收，不将候选版本部署等同T132最终通过。

- [x] **T176 接续最新积分迁移并保持唯一head**

  **类型**：基础设施 · 仓库B交付worktree。

  **文件**：`src/backend/bisheng/core/database/alembic/versions/v3_0_0_f111_dsh_content_safety.py`；`src/backend/test/database/test_alembic_dsh_main_upgrade.py`。

  **逻辑与验证**：真实组合图已RED为两个head；F111未对受支持环境发布、109当前work110，接到target真实f062_credit_multiplier；保留已发布revision哈希，实际head及迁移回归、双库静态可移植自审。

  **依赖**：T008、T016。

- [x] **T177 保留新版登录与安全回传入口**

  **类型**：实现 · 后端API；仓库B交付worktree。

  **文件**：`src/backend/bisheng/dsh/api/router.py`；`src/backend/bisheng/utils/http_middleware.py`。

  **逻辑与验证**：逐块合并，保留target全部capabilities/skills/work/credits/web-session路由和身份校验、F111精确HMAC回传路由；原登录/strict scope及接收中间件配对回归。

  **依赖**：T032、T034。

- [x] **T178 保留积分默认页和敏感词导航**

  **类型**：实现/测试 · 前端Platform；仓库B交付worktree。

  **文件**：`src/frontend/platform/src/pages/DshPage/sections.ts`；`src/frontend/platform/src/pages/DshPage/dshPageNavigation.test.tsx`。

  **逻辑与验证**：组合七页签，保持target credits默认/非法回退和F111 content-safety入口，原operations继续隐藏；真实导航Vitest、类型和三语检查，不改组件视觉。

  **依赖**：T104、T110。

- [x] **T179 最终组合的真实迁移与积分安全联合回归**

  **类型**：测试 · 后端Domain；仓库B交付worktree。

  **文件**：`src/backend/test/dsh/test_content_safety_database_integration.py`；`src/backend/test/dsh/test_content_safety_credit_integration.py`（拟新增）。

  **逻辑与验证**：保留真实work110归档升级，增加真实target归档已应用信用倍率/个人额度数据升级，与fresh组合schema比较；输出命中不改变倍率/原始用量/未知及迟到幂等，结合target计量原有回归。MySQL实际执行，DM8继续待环境；不得用当前模型伪造旧schema。

  **依赖**：T176、T177、T178。

- [ ] **T180 集成候选版本审查与定向交付记录**

  **类型**：验收/运维 · 三仓交付。

  **文件**：`features/v3.0.0/111-dsh-sensitive-word-control/code-review.md`；`features/v3.0.0/111-dsh-sensitive-word-control/deployment-execution.md`。

  **逻辑与验证**：以最新目标ref做七维候选审查，修复HIGH；记录源/合并/远端SHA、Drone构建和镜像digest、115步骤跳过、109 DSH专用备份与仅目标服务更新、真实客户端联调与剩余环境边界。原T132完整特性验收另按完整证据，不伪勾。

  **依赖**：T179。

- [x] **T181 修正 bootstrap 完整模型集合夹具**

  **类型**：测试。**文件**：`src/backend/test/database/test_dsh_audit_work110_migrations.py`。

  **逻辑与验证**：原源树实际复现15表常量失配；改验真实模型集合、无重复及反射集合精确相等，保留列/索引/存量/幂等断言；普通入口7文件37 PASS。**依赖**：T176。

- [x] **T182 补齐目标分支日语统一策略文案**

  **类型**：兼容维护。**文件**：`src/frontend/platform/public/locales/ja/bs.json`。

  **逻辑与验证**：按现有中英文及实际策略语义补12个缺键；不改旧值或baseline；三语检查和相邻测试。**依赖**：T178。

- [x] **T183 补齐 sandbox 错误中文和英文**

  **类型**：兼容维护。**文件**：`src/frontend/packages/locales/src/api_errors/zh-Hans.json`；`src/frontend/packages/locales/src/api_errors/en.json`。

  **逻辑与验证**：按既有28001–28009真实业务调用补齐错误文案，使用仓库生成器同步衍生产物，不手编辑产物或baseline。**依赖**：T178。

- [x] **T184 补齐 sandbox 错误日语并验收三语**

  **类型**：兼容维护。**文件**：`src/frontend/packages/locales/src/api_errors/ja.json`。

  **逻辑与验证**：与T183同义的九项日语；运行生成器、check-i18n及locale校验。**依赖**：T183。

- [x] **T185 Responses 同消息连续文本块漏检回归**

  **类型**：测试 · Gateway。**文件**：Gateway `src/test/java/com/dataelem/gateway/protocol/DshResponsesSafetyAdapterTest.java`。

  **逻辑与验证**：实际候选私有Java复现相邻output_text、reasoning.content、reasoning.summary拆分dan/ger流及非流均错误通过；按AC-21、AC-22、AC-23固化RED，同一通道连续块拼接、不同item/channel隔离，done/final前不泄漏。**依赖**：T073。

- [x] **T186 Responses 连续文本块按逻辑域检查**

  **类型**：实现 · Gateway。**文件**：Gateway `src/main/java/com/dataelem/gateway/protocol/DshResponsesSafetyAdapter.java`。

  **逻辑与验证**：修复T185确证HIGH，保持有界扫描、乱序/重复快照校验及协议边界；配对和Gateway全部定向回归，七维重审。**依赖**：T185。

- [x] **T187 冻结配置夹具恢复与联合回归**

  **类型**：测试。**文件**：`src/backend/test/dsh/test_chat_credits.py`。

  **逻辑与验证**：target原测试直接修改frozen DshSettings，异常导致monkeypatch撤销中断并污染后续租户断言。仅在fixture对settings.__dict__置换不可变配置副本并自动恢复，保留全部实际chat计量断言；组合162 PASS及全部相关回归。**依赖**：T177。

- [x] **T188 策略保存失败不记录完整草稿**

  **类型**：实现/测试。**文件**：`src/frontend/platform/src/pages/SystemPage/dsh/DshContentSafetySettings.tsx`；`src/frontend/platform/src/pages/SystemPage/dsh/DshContentSafetySettings.test.tsx`。

  **逻辑与验证**：开发模式react-query默认logger可能输出AxiosError.config.data里的自定义词/回复；局部安全query client禁用原始error logging并保留现有错误反馈，补网络/409回归。**依赖**：T110。

- [x] **T189 模型开始时间中文及英文标签**

  **类型**：兼容维护。**文件**：`src/frontend/platform/public/locales/zh-Hans/bs.json`；`src/frontend/platform/public/locales/en-US/bs.json`。

  **逻辑与验证**：增加独立模型执行开始时间的业务标签，不混用请求开始，复用既有未知/不适用文案。**依赖**：T178。

- [x] **T190 模型开始时间日语标签**

  **类型**：兼容维护。**文件**：`src/frontend/platform/public/locales/ja/bs.json`。

  **逻辑与验证**：补齐T189同义日语，全check-i18n通过。**依赖**：T189。

- [x] **T191 请求详情区分模型开始时间**

  **类型**：实现/测试。**文件**：`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditCard.tsx`；`src/frontend/platform/src/pages/SystemPage/dsh/ModelAuditCard.test.tsx`。

  **逻辑与验证**：AC-46要求稳定request_started与独立model_started可辨；已用真实组件复现字段存在却未显示。沿既有详情dl行显示模型开始/未知/未执行，保留请求排序与原时间，不新增视觉样式。配对RED/GREEN及相邻回归。**依赖**：T189、T190、T106。

- [ ] **T192 Desktop Undici 既有补丁接收者兼容修复**

  **类型**：基础设施/测试 · Desktop。**文件**：Desktop `patches/undici+8.11.2.patch`；`test/undici-legacy-headers.test.mjs`。

  **逻辑与验证**：完整现行客户端回归确证Object.create(handler/controller)使private-field方法接收者失配，三请求超时及unhandled errors；原patch/test/lock均等main，仍是当前联调阻断。仅修回调转发接收者并覆盖私有字段/abort/resume/trailers，标准patch重建重放，不手留node_modules补丁、不升级依赖；临时3.11 PATH运行完整回归。**依赖**：T118。

- [x] **T193 Gateway 最终修复验证文档同步**

  **类型**：文档维护 · Gateway。**文件**：Gateway `docs/dsh-content-safety-verification.md`。

  **逻辑与验证**：同步T185/T186最终60配对/主独立882回归、两次独立语义对照，明确旧108eb5c8不可部署及真实环境待验；与B design/code-review交叉一致，无凭据。**依赖**：T186。

- [ ] **T194 真实HTTP验收共享helper接入**

  **类型**：测试基础设施。**文件**：`src/backend/test/e2e/helpers/dsh.py`；`src/backend/test/e2e/helpers/dsh_content_safety.py`。

  **逻辑与验证**：复用真实RSA登录会话和原S256 PKCE，支持精确API/Origin且不破坏旧调用，live缺配置fail-loud；只读0600显式session，测试资源ID/前缀登记和GET确认/CAS恢复，无JWT伪造/生产SQL写。创建offline测试模型前核既有全局默认引用，避免set_default_model自动改变空默认。**依赖**：T179。

- [ ] **T195 无费用受控Provider测试设施**

  **类型**：测试基础设施。**文件**：`src/backend/test/e2e/helpers/dsh_content_safety_provider.py`。

  **逻辑与验证**：stdlib真实HTTP Chat/Responses流与非流，确定场景/有界调用计数，只有合成随机test key、opaque marker，无外部模型、原文/凭据日志。仅109 DSH私网临时容器，控制面只loopback经SSH隧道；不得接入其他部署。**依赖**：T194。

## 5. AC → 测试任务追溯

本表只列测试/验收任务；配对实现见各任务依赖。每条 AC 至少一个针对性测试或端到端场景，末端 E2E 和特性审查不能代替前置测试。

| AC | 测试 / 验收任务 |
|---|---|
| AC-01 | T071、T073、T075、T087、T089、T091、T121、T125、T132、T138 |
| AC-02 | T061、T067、T087、T091、T093、T110、T121、T125、T131、T132、T135、T138、T172 |
| AC-03 | T017、T025、T029、T031、T035、T049、T083、T087、T091、T093、T121、T125、T130、T131、T132、T138、T141、T142、T143、T144、T145、T146、T147、T150、T151、T165、T171 |
| AC-04 | T087、T091、T124、T125、T131、T132 |
| AC-05 | T071、T073、T075、T083、T087、T089、T091、T095、T113、T115、T121、T125、T132、T138 |
| AC-06 | T061、T063、T067、T122、T125、T132、T165 |
| AC-07 | T039、T065、T067、T110、T122、T124、T125、T132、T165 |
| AC-08 | T039、T065、T067、T122、T124、T125、T132、T135 |
| AC-09 | T061、T063、T067、T110、T122、T125、T132、T135 |
| AC-10 | T061、T063、T067、T110、T120、T122、T125、T132 |
| AC-11 | T063、T067、T087、T122、T125、T128、T129、T131、T132 |
| AC-12 | T061、T063、T067、T087、T122、T125、T131、T132 |
| AC-13 | T055、T057、T087、T122、T125、T127、T132 |
| AC-14 | T057、T059、T097、T122、T125、T127、T129、T132、T157、T163 |
| AC-15 | T057、T059、T122、T125、T127、T129、T132 |
| AC-16 | T055、T083、T087、T089、T122、T125、T131、T132 |
| AC-17 | T057、T083、T087、T122、T125、T131、T132 |
| AC-18 | T055、T057、T059、T063、T065、T067、T085、T087、T097、T122、T125、T127、T129、T132、T157、T159、T163 |
| AC-19 | T055、T057、T059、T085、T087、T097、T122、T125、T127、T128、T129、T132、T157、T159、T163 |
| AC-20 | T069、T071、T073、T075、T121、T125、T132 |
| AC-21 | T063、T069、T071、T073、T075、T121、T125、T132、T185、T186 |
| AC-22 | T069、T071、T073、T075、T121、T125、T132、T185、T186 |
| AC-23 | T075、T089、T115、T118、T121、T125、T132、T185、T186 |
| AC-24 | T073、T075、T113、T115、T118、T121、T125、T132 |
| AC-25 | T033、T069、T071、T073、T075、T121、T125、T132 |
| AC-26 | T031、T033、T063、T069、T071、T075、T085、T091、T095、T097、T121、T125、T126、T128、T129、T132、T138、T159、T161、T171 |
| AC-27 | T023、T071、T087、T089、T121、T125、T132 |
| AC-28 | T073、T075、T089、T121、T125、T132 |
| AC-29 | T073、T075、T083、T085、T089、T113、T115、T118、T121、T125、T128、T132 |
| AC-30 | T073、T075、T087、T089、T111、T113、T115、T118、T121、T125、T132、T136、T137、T140、T141、T142、T143、T144、T145、T146、T147 |
| AC-31 | T073、T075、T083、T087、T089、T111、T113、T115、T118、T121、T125、T132、T136、T137、T140、T141、T142、T143、T144、T145、T146、T147 |
| AC-32 | T023、T025、T027、T037、T083、T085、T089、T113、T115、T121、T125、T128、T131、T132 |
| AC-33 | T019、T073、T075、T077、T123、T125、T132 |
| AC-34 | T019、T027、T037、T073、T077、T110、T123、T124、T125、T132、T133 |
| AC-35 | T017、T023、T029、T031、T033、T039、T069、T077、T079、T093、T095、T097、T111、T122、T123、T125、T132、T135、T161、T163、T171、T172 |
| AC-36 | T023、T027、T037、T123、T125、T132、T133 |
| AC-37 | T023、T089、T123、T124、T125、T132、T174 |
| AC-38 | T021、T023、T025、T027、T029、T041、T055、T119、T122、T123、T124、T125、T132、T174 |
| AC-39 | T021、T023、T029、T033、T047、T049、T051、T079、T081、T119、T120、T123、T125、T132、T138、T166、T172 |
| AC-40 | T023、T029、T077、T085、T123、T125、T132 |
| AC-41 | T019、T021、T025、T029、T041、T043、T047、T051、T077、T079、T081、T119、T120、T123、T125、T132、T138、T168、T172 |
| AC-42 | T017、T021、T029、T031、T033、T035、T079、T123、T125、T132、T171、T172、T174 |
| AC-43 | T029、T031、T033、T051、T053、T077、T079、T081、T085、T097、T120、T123、T125、T128、T129、T131、T132、T138、T161、T171 |
| AC-44 | T023、T027、T037、T039、T110、T124、T125、T130、T132、T133 |
| AC-45 | T035、T037、T039、T045、T110、T124、T125、T126、T129、T132、T148、T151、T152、T156 |
| AC-46 | T037、T039、T110、T124、T125、T132、T150、T174、T191 |
| AC-47 | T025、T041、T043、T045、T047、T124、T125、T132、T166 |
| AC-48 | T023、T027、T041、T043、T045、T047、T049、T051、T053、T097、T119、T124、T125、T126、T129、T132、T166 |
| AC-49 | T025、T037、T039、T045、T110、T124、T125、T126、T129、T132、T148、T151、T152、T156、T174 |
| AC-50 | T037、T039、T045、T124、T125、T126、T129、T132、T148、T152、T156 |
| AC-51 | T021、T037、T039、T051、T053、T081、T110、T119、T120、T123、T124、T125、T131、T132 |
| AC-52 | T016、T025、T027、T037、T041、T043、T051、T053、T119、T123、T125、T132、T133、T168 |
| AC-53 | T016、T021、T047、T051、T053、T061、T119、T120、T123、T125、T126、T129、T132、T166、T168 |
| AC-54 | T091、T093、T095、T124、T125、T131、T132、T138 |
| AC-55 | T047、T049、T063、T077、T081、T087、T120、T123、T125、T131、T132、T138、T166 |
| AC-56 | T110、T111、T113、T115、T124、T125、T130、T132、T136、T137、T140、T141、T142、T143、T144、T145、T146、T147、T165 |
| AC-57 | T085、T089、T121、T125、T128、T129、T132 |
| AC-58 | T029、T077、T079、T081、T097、T120、T123、T125、T131、T132、T161、T172 |
| AC-59 | T059、T122、T125、T127、T129、T132 |

## 6. 共享文件与发布边界

共享 HMAC helper 只调整签名计算复用，旧 SSO 协议/错误码/正文回放原样回归；HTTP middleware 仅精确新接收路由，不改模型认证。model_audit_write/writer、会话查询及 ModelAuditPanel 分步只改本任务区域；状态、事件、投影和查询方法分工明确。Gateway 应用敏感词/PathRate/默认路由的改动必须跑旧应用与WS回归。Desktop 保持宿主插件边界，不改第三方 tgz 或直接修 node_modules。

所有数据库扩展采用保留事实的应用回退；包含外部记录时不盲目降级到旧 CHECK/NOT NULL，不以删除事实换回滚成功。正常列表走主摘要，事件表只服务详情/未关联查询。默认不自动清明细，30 天是容量评估而非保留期。生产迁移、部署、提交、推送和合并均须后续对应授权；本计划并非这些操作的授权。

## 7. 实际偏差记录

新增 T133、T134：Wave 1 既有 DTO 消费端兼容回归确证的问题，最小修复见 design §9。T001 增加显式租户登记；T008 增加 schema helper；T016 增加持久化迁移验证，均保持每任务最多两个目标文件。实现改变认知时按“任务 ID → design 的具体决策/坑”留一行指针，不复制论证；推翻已确认需求或设计先按 SDD 重新确认。

## 8. 文档与执行检查

初版132项/43个Wave静态评审见[tasks-review.md](./tasks-review.md)；实施中确证的兼容与接线补齐按§9留记录，原Wave1–43共175项；交付补充后当前195项。新增任务逐项/task-review与配对测试验收，不把初版静态LGTM当新增任务已执行。59条AC追溯表按当前测试任务覆盖补齐；保持依赖无环、每任务人工目标文件至多两个。

## 9. 执行记录

2026-10-23：完成 Wave 1 T001–T015、兼容补充 T133/T134 以及 T016，18 / 134。任务自审、具体测试与既有前端全量门禁失败见 [implementation-verification.md](./implementation-verification.md)。真实 MySQL/DM8 事务、模型、页面 E2E 和容量未执行；不提交、不推送、不部署。

2026-10-23：完成 Wave 3 的 T017/T019、T055/T061/T065/T077/T083、T099/T100/T101、T111，共 29 / 134。测试任务的完成表示已编写、自审并证实预期 RED，不代表未实现的行为已通过；进入 Wave 4 逐项转绿。

2026-10-23：Wave 4 八项配对实现通过测试和任务自审，累计 37 / 134。Gateway 合并定向回归 126 passed；backend 配对及相邻回归 152 passed；Desktop 文案及企业包 28 passed、typecheck passed。DM8 暂无可用测试环境，用户确认保留实测待验收；未勾选后续真实双库验收任务。

2026-10-23：Wave 5 三项前置测试全部审查完成，累计 40 / 134，进入 Wave 6 配对实现。T063 加入实际 AC 失配链漏检回归；DSH 局部 BFS 修正已在临时真实 Java 探针复现转绿，生产实现仍待 T064。

2026-10-23：Wave 6 三项实现全部完成，累计 43 / 135。主 agent 对最终代码重新运行13类195项Gateway回归全部通过；独立Redis缓存27断言及策略Lua/广播验证通过，仍不代表多进程预算、双库或E2E验收。进入Wave7前置测试。

2026-10-23：Wave7发现T066仅返回Void，无法为既定updated_by提供可信操作者；新增必要兼容补齐T135（2文件，原授权链不变），T068依赖它且仍只两文件。总任务135项；capabilities明确带目标tenant_id并实时管理授权，Origin复用既有bisheng.homeUrl，不新增配置或backend RPC。

2026-10-23：Wave7五项全部完成，累计48 / 135。Gateway三组新测试语法/定向预期RED通过自审；主agent集中MavenRED仅待实现Verifier/Scanner等缺类；backend主agent组合23预期RED+72既有PASS；T135真实本地HTTP11/11PASS。进入Wave8四项配对实现。

2026-10-24：Wave8四项配对实现完成；backend集中165 PASS，Gateway16类261 PASS，实际Redis缓存27断言PASS。逐文件自审和独立Scanner复审完成；修正管理请求在授权前聚合200MB正文、Profile过期任务复用与槽位取消时序。进入Wave9，真实DM8继续待验收；未提交、推送或部署。

2026-10-24：Wave9四个前置测试任务完成；backend集中13预期RED+173PASS，Gateway集中仅缺三个配对生产adapter类型。独立复审修正合法内联图像fixture，补齐Chat/Responses工具参数根类型差异、Unicode提示保留核心命中，以及失败Responses快照仍检查可读内容。进入Wave10配对实现。

2026-10-24：Wave10四项实现完成。backend配对21PASS、agent组合219PASS、主agent独立186PASS；Gateway19类371PASS。独立实测复审修复schema结构/业务值混淆、reasoning跨块、错误混载绕检、未结束Responses条目被遗漏后误判成功，均留RED→GREEN证据。进入Wave11，真实双库/部署/性能仍待验收；未提交推送部署。

2026-10-24：补T138/T139（Wave27/28）显式承接Gateway Spring条件组装；原T098仅遥测/Dispatcher两个文件，不能承担缺失的Configuration接线。真实配置容器与检查关闭仍补报列为配对验收，总数139；已完成仍80。

2026-10-24：补T140在Wave17固化T117实际入口/卸载回归；临时探针不能长期承担CI保护，仍单文件/独立临时profile，不替代T118真实工具runner或最终E2E，总数140。

2026-10-24：Wave17补T141维护既有enterprise-adapter夹具；本特性新增公共事件订阅/函数导出造成5项原测试未到达业务断言，修夹具且不放宽断言。总数141。

2026-10-24：Wave18相邻真实回归发现旧Gateway手工Binder不解析合法placeholder，T091扩第二测试文件；旧Desktop审计on接口夹具纳T141第二文件，另补T142/T143维护三份UI locale夹具（每任务至多两文件），原业务断言不改。T091/T141暂退勾等待复验，总数143。

2026-10-24：真实SessionController.queue生产locale桥复现后续请求沿旧driver ALS显示首轮语言；补T144/T145双adapter冻结formatter测试/实现及T146/T147公开消息事件作用域测试/实现，Wave20–22每项至多两文件、独立配对门禁，总147。只修既定当前语言显示，不改模型鉴权/安全分类/工具屏障或第三方包。

2026-10-24：T040只读准备实际复现Service注入移动默认bounds会导致主请求游标冲突。新增Wave22串行T148/T149后再接T040；既定默认相对窗口不冻结、显式筛选绑定不变，每任务至多两文件，总149。

2026-10-24：T040扩大回归实际13项旧fixture失败；新增T150补原隔离schema事件模型、T151只对两手工固定日期测试注入相干查询clock。保持最多两文件、原断言、共享Harness实时模型行为及固定NOW，总151。

2026-10-24：组/树Repo沿主请求一样的可选now端口保留旧内部语义，需独立API时钟接线；补Wave24串行T152/T153（T046后）避免把第三Service源隐藏进两源Repo实现。每任务单文件、真实API先RED后GREEN，总153；不改变默认窗口和显式绑定取舍。

2026-10-24：当前Platform缺共享组件依赖及语义样式，现行AGENTS强制复用landed组件；新增T154 workspace依赖与T155限定容器的构建接入，拒绝全站样式迁移或复制token值。两任务各至多两维护文件，不升级第三方闭包，总155。

2026-10-24：T153实际API默认窗口接线后两旧手工历史NOW测试失配，新增T156精准两个case查询时钟维护，保留原断言/全局Harness与生产语义，总156。

2026-10-24：T097边界审查确认T098两源只能落聚合器与Dispatcher，现有final Cache/Policy/Manager/Filter无observer端口，不能把手工increment当实际诊断已完成。新增T157–T164四组配对（每任务≤2源），位于Wave26/T138前，仅接既定有限诊断不新增产品需求；T139统一注同实例。另T165精准维护新增tab导致的既有导航计数。总165。

2026-10-24：T047补真实原生审计先发布/首命中后到，发现只tree_pending漏group-only dirty，而旧pending_tenants包含无关运行模型；新增T166/T167窄Repo端口配对，保持048仅Worker+registry两源，旧tree扫描默认兼容。总167。

2026-10-24：T051实际链路确认原生writer缺删除水位闸门、首次缺setting会有并发空隙；新增T168/T169配对，复用T052锁行端口，T119依赖其完成，保持每任务≤2源。T139增加第二源仅移交Outbox的Spring唯一Bean所有权，真实context测试先行，不用多实例掩盖。总169。

2026-10-24：T108生产构建GUI通过，但正式Vite dev实际DOM确认Shared UI的tailwind-merge被同名优化到Platform不同锁定版本，丢字号类；新增T170单构建源兼容，不在108两业务源藏覆盖样式或升级依赖，T110依赖修复。总170。

2026-10-24：T052扩大组合确证T031当前进程重导runtime造成package/module别名分叉，新增T171单测试冷启动隔离维护；同HEAD原Setting36FAIL为保留证据，修复不放宽API断言。总171。

2026-10-24：跨仓真实配置probe确证全局null→空串使事件/不可用capabilities被严格consumer拒绝，新增T172/T173配对局部修复；真实Repo确证大小写UUIDfilter与已存lower不等，新增T174/T175配对，保持每任务≤2源，不放宽DTO或更改默认分页取舍。总175。
