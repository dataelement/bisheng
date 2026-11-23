# F118 升级统一流程七维代码审查

**Feature**：F118 AC-158～166，统一迁移入口、监控、阶段恢复与完整引用收尾。
**审查快照**：独立工作树 `codex/f118-upgrade-flow-20261120`，基准 `1a2f59a7273d` 加本轮差异；验证时这些差异尚未提交。报告随交付提交后，该句仍只描述验证时点，不描述分支后续状态。审查未执行 165 环境验收。
**审查范围**：统一 CLI/application/materials/executor/Run 绑定、引用批次/原证明/语义目录/Coverage 消费、最终报告合同及对应 spec/design/tasks/升级指南。H/P 的深层实现依赖其 Owner 回归，本文不宣称逐行审查全仓。
**方法**：按仓库 `sdd-code-review` 七维框架，对照已确认 spec AC-158～166、design §16 与 constitution C1～C8。引用代码含审查人负责实现的部分；额外检查真实统一入口及跨 Owner 接缝，不把自有 helper 通过等同端到端通过。

## 最终结论：PASS（本轮本地增量代码审查）

普通 frozen/new-run 两命令主链、preparing 共享恢复与完整 Coverage 已取得原生离线证据；完整证明、旧材料保留、坏材料零写拒绝及失败报告路径已接通。R1～R11 的实质问题均已修复或按明确的真实容量合同收敛，并取得对应代码及定向验证证据；当前审查范围无未解决 HIGH/MEDIUM。

本结论覆盖根入口/引用/证明/报告的本轮本地增量。主 Agent 已完成失败选择与 HEAD 的精确首因对照，147/147 一致；这不表示全目录通过，分类及限制见下。真实 MySQL/DM8、真实中间件和生产规模维护窗口仍按实施/QA 记录待验证，不以离线结果代填。

| Dimension | High | Medium | Low | 当前状态 |
| --- | ---: | ---: | ---: | --- |
| Boundary Conditions | 0 | 0 | 0 | PASS：R7/R8/R10/R11 修复及回归已收 |
| Permission & Auth | 0 | 0 | 0 | PASS：已审原生路径与 legacy guard |
| Concurrency Safety | 0 | 0 | 0 | PASS：本地协议/共享恢复；真实双库另待验证 |
| Information Leakage | 0 | 0 | 0 | PASS：R4 已修复 |
| Test Coverage | 0 | 0 | 0 | PASS：定向原生证据见下；未冒用全目录结果 |
| Code Style | 0 | 0 | 0 | 已审 Owner 路径 Ruff/架构检查通过 |
| Docs Sync | 0 | 0 | 0 | PASS：R1/R2 当前合同/操作步骤已同步 |

下文保留发现时严重度和关闭证据，均不计入表中的未解决缺陷数。共享工作树仍有其他 Owner 的综合验证；后续若改变本报告范围内的合同或效果，需复查对应项。

## 实质 Findings

### R1 — HIGH Docs Sync：超大单来源原设计“流式”描述须改为已明确的实际边界

- 合同：`features/v3.1.0-beta1/118-knowledge-space-unification/design.md:1516` 明确超大单来源单独流式处理；增加明细/字节预算，且不能提交半个 source。
- 实现：`src/backend/bisheng/knowledge/application/unification_references.py:359` `_records` 先累计一个来源的完整 records；`_batches` 在来源完整物化后才计算预算，超上限时只把该来源单独成批。原生 source DTO 的 JSON 配置/children 与索引 snapshot 也会完整载入单个来源。
- 初次审查的尾检字节成本只包含业务 snapshot，未包括完整 raw index payload；该实现问题已修复，当前成本包含实际业务与完整 index 的 canonical 字节，辅助成本不进入证明 fold。
- 现有预算用例证明了超预算来源不会和其他来源拼批、不会半个来源提交，没有证明超大来源以流式、有界内存完成。13/25 来源规模结果也不能证明这一点。
- 要求：实现与批准合同闭合，或明确约定并同步真实容量边界；不能保留“超大来源流式”的交付声称。若采用超限拒绝，应在读取/物化前检测并报告 `not_evaluated`，不能先耗尽内存再报告。该项已通知主 Agent，审查阶段未擅自弱化设计或新增容量策略。

**本轮取舍及实际验证**：AC-163 不承诺单 source 常量内存；六类原生配置/索引按完整 source DTO/JSON 闭合，不能为流式改原 checksum/原子协议。本轮保留单 source 完整加载、超预算单 source 独立原子事务，不新增低上限拒绝已有支持数据；原 16 MiB 单制品上限保留。初始 4 MiB 是冻结 header/引用记录预算，header 不含原业务 JSON，不能据此声称初始批 native JSON 的总字节硬上限。尾检则使用前遍实际业务与完整 index 字节。5 MiB 配置、5,120 条引用的真实原生完整成功/中断原子恢复 **2 passed / 67.85s**；强断言逐字节核对尾检快照成本 **8,282,110 bytes**，原制品全部仍在 16 MiB 协议内。完整成功 25.44s / Python 分配峰 49.85 MB；中断后恢复 37.10s / 63.72 MB；对应进程生命周期 RSS 高水位 950.6/983.1 MB，包含 pytest 导入及 fixture，不能当阶段增量。R1 保留为已修复的设计描述偏差追溯，不把这项例外描述成全流式。

大来源量测包含测试中额外的真实快照读取/逐字节断言；不是隔离的生产 CLI 进程资源指标。16 MiB 是单制品协议上限，并非 source 原生 JSON 总大小上限。

**设计已同步**：当前 design §16.9 明确完整单 source DTO、超预算独立原子事务、初始序列化计划记录预算及非恒定内存，保留早先“超大来源流式”措辞调整的追溯；本项不再是未解决 HIGH。

### R2 — HIGH：正常升级指南仍要求两个历史脚本阶段

- 发现时 `docs/upgrades/v3.1.0-beta1.md` 旧第五阶段（当时第 218 行）仍将 `prepare_f118_history.py` 的 preview/apply 放在正常升级流程，之后才运行统一入口；与 AC-158/166 的统一 dry-run/apply 合同冲突。
- 当时 design §16 仍包含“拟实施合同/开发中”状态及旧修订说明，tasks 实施表仍写全体待完成。历史检查点可以保留，但最终实现状态、真实文件名、尾检成本与未验证边界需要当前快照。
- 要求：正常流程只展示统一预检、同计划显式执行、相同 apply 恢复；旧阶段/旧计划脚本移到兼容说明。仍独立执行结构升级、其他功能迁移及业务验收，不能把所有产品升级步骤合并为一个脚本。

**已修复**：当前升级指南第五/六阶段与 scripts README 正常流程采用同一 dry-run/apply，旧历史脚本明确为已有计划的兼容恢复。design §16 已记录实际实现及容量边界，tasks 已覆盖旧历史检查点并列本地完成态/实际文件路径，八列 QA 区分本地通过与真实平台/现场待验证；未将此前 165 旧脚本记录当本轮验收。

### R3 — HIGH：损坏的 flow 本体仍能先取得维护锁种子

P Owner 原生 review 回归 `test_upgrade_review_regressions.py::test_first_bootstrap_rejects_unusable_material_without_lock_seed[corrupt-...]` 曾复现：`objects/<flow-sha>.json` 损坏时，候选目录 manifest 副本先通过准入，直到上传图再拒绝，导致首次 bootstrap 锁种子已写入。与 AC-159/设计 §16.7 的材料拒绝前零写合同不符。

**已修复**：当前材料树有只读 `validate_tree`，实际 flow 本体及后代均在 seed 前验证，不从候选 manifest 副本冒充 object 本体。P Owner 最终 review 组 **10 passed / 4.46s** 覆盖此项。

### R4 — HIGH：CLI 取消错误未进入脱敏结果合同

P Owner `test_upgrade_review_regressions.py::test_cli_failure_or_cancel_report_omits_provider_text` 的 `CancelledError` case 曾复现：当时 `main` 仅捕获 Exception，取消作为 BaseException 裸抛，可输出 provider 错误文本。

**已修复**：当前 main 对取消专门输出脱敏非零结果，不裸抛 provider 文本；上述 10 项回归已通过。

### R5 — HIGH：dry-run 报告写入失败前已发布可执行候选

初次审查发现 `UnificationUpgradeApplication.preview` 先写 flow 并 `activate`，再调用 `write_report`。后者 OSError 会让预检失败，但 `reconciliation/<sha>/manifest.json` 已能被下一次 apply 的候选枚举读取；这与 design §16.8“dry-run 材料/报告未原子写成时不生成可执行计划”不符。故障注入路线为预检 `write_report` 失败后恢复 I/O，再 apply 必须无可用候选且零写。

**已修复**：当前 `preview` 先完成报告再 activate；P Owner 原生写失败用例验证没有 reconciliation/ACTIVE，I/O 恢复后 apply 缺候选拒绝且零 DML/FGA；上述 10 项回归已通过。

### R6 — HIGH：新增 history_summary 未闭合校验，可能在真实迁移完成后才失败

新增摘要初次实现时 `_FIELDS` 包含 `history_summary`，但 `_flow` 未校验该值的 dict/字段集/计数，`_admit_flow` 重算比较也未包含它。将原本合法 flow 的此字段改为 `False`、重新写为内容寻址的唯一候选并保持其他引用不变，当时准入允许继续；真实迁移结束后 `result.update(flow['history_summary'])` 才 TypeError。任意 dict 也可覆盖不应由历史摘要提供的结果字段。该项为新报告合同的实际坏材料前拒绝/结果真实性缺口，不描述为权限扩大。

**已修复**：当前 `_flow` 严格校验四字段、action 白名单、整数非负和总数；fresh/preparing 重算对比包含摘要，frozen 候选继承原绑定摘要，旧 frozen 只接受明确的本命令空计数。最终结果仅复制四个允许字段。新增原生 E2E 三类合法重新寻址的唯一候选（非 dict、额外 ready 字段、结构合法但伪造原计划计数）均在写前 10998 拒绝，**3 passed / 1.46s**，零 SQL DML/FGA/远端制品写入。

### R7 — MEDIUM：恢复前缀被当成本次处理量，首段速率/ETA 不可信

`ProgressRecorder.update` 在 phase/tenant 切换时先加入 `(now, 0)`，随后才加入当前累计 committed。恢复从 50,000 开始、10 秒后实际新增 100 时，窗口会算作 50,100/10=5,010/s，直到初始 0 样本被挤出；本次实际为 10/s。应以第一条观测的 committed（否则 processed）为窗口起点，再计算本次新增速度；可用固定 monotonic 时钟验证，不需真实等待。已通知主 Agent；此项不影响业务，但涉及 AC-162 的可靠实测速率。

当前代码已以首条观测作为起点，并新增 `test_resume_rate_counts_only_new_acknowledgements`。

**已修复并验证**：主 Agent 的 CLI/executor/progress 组 **28 passed / 16.06s** 包含假时钟回归，50,000→50,100 / 10 秒实际速率为 10/s。

### R8 — MEDIUM：退休检查点在失败位置摘要中拼写不一致

`UpgradeRunRepository.aload_state` 的 positions 白名单初次写为 `reference_retirements`，R 实际永久 key 为 `references_retired`。退休批次中断时因此漏报最后已确认的位置。已通知主 Agent 修正报告读取白名单并验证真实 checkpoint，不改 R 原历史 key/fold。

当前读取白名单已改为真实 `references_retired`。

**已修复并验证**：上述 28 项组包含 `test_failure_positions_include_the_native_retirement_checkpoint`，真实 Run/checkpoint 回读保留退休 count/complete/cursor 摘要；不输出原 cursor 载荷。

### R9 — HIGH（已修复）：frozen 当前集合前检会隐藏错误租户的助手子行

真实原生负例已复现：冻结后新增 AssistantLink，指向 tenant 101 的助手、却归属已注册 tenant 202 或不存在的 tenant 999999；原 strict-tenant source 页隐藏了这两行，来源 key census 也未校验孤儿，统一 dry-run 错误返回 can_apply=true（两个 case 先红）。修复复用原生不变量：当前差异观察前调用一次 global_orphans/registered_source_tenants，并在每个实际租户检查 tenant_orphans；完整 census/尾检也检查 tenant_orphans。正常最终签证原有全局 gate 在同事务执行，不重复扫描；completed strict verify 不调用签证器，已补其全局 live gate。

前检两个负例 **2 passed / 2.05s**：dry-run 明确不可执行，apply 在 SQL DML/FGA/远端制品写入前拒绝。写入后的最终尾检及 completed 严格复核矩阵 **4 passed / 5.01s**，覆盖上述两种 owner，不能签发新 Coverage/改写已完成 epoch。原规则/在线策略、旧提交 ordinal/hash/checkpoint 均不变。该必要完整性扫描成本纳入最终 N/2N，不能只保留修复前的较少查询数。

### R10 — HIGH：未完成 Run 的 --verify 仍进入可写执行路径

P Owner 最后只读复查曾发现 CLI help 声明 verify 对已完成 Run 做严格复核，但未完成 Run 加 `--verify --apply` 时仍可进入写迁移；legacy stage 组合还可能忽略该标志。completed 正常 strict verify 已通过不能代替这个负例。

**已修复并复查**：preview/apply 在真实 state 读取后拒绝非 completed verify，公开 legacy stage 与 verify 组合直接拒绝。P 原生四负例（fresh/frozen × dry/apply）先红、completed strict 只读正例先绿，修复后全部通过；coordinator 另覆盖两个 legacy 组合冲突。P 最终 database helper/singlehead/coordinator/review/legacy 组合 **38 passed / 16.03s**，无未完成 verify 写入或忽略参数。已核对当前生产 guard 位置及 reason。

### R11 — HIGH：旧 completed Run 首次统一严格复核仍写远端对象并进入控制锁

旧原生完整引用应用已完成、尚无统一 flow 绑定的 Run，首次统一 dry-run 后执行 `--verify --apply`，原路径虽无 SQL/FGA 写入，仍上传 verification 与 upgrade_flow 两个对象并进入执行控制锁。P 原生两个参数节点分别记录真实 `put_object` 与在控制锁调用即抛错的 sentinel，先复现两红；仅断言业务数据或 Coverage epoch 不变不能满足已完成复核的完整只读合同。

**已修复并复查**：`src/backend/bisheng/knowledge/application/unification_upgrade.py:820` 在 completed strict 分支只调用只读 `_admit_flow`，通过本地材料叠层读取首次候选，再调用原生完整 `arun_references(reuse_completed=True)`；分支在 `UpgradeExecutor.acquire` 之前返回，不 seed/start/upload/bind。结果与正常流程共用 `_reference_result`，只追加私有本地报告。已核对 `_admit_flow` 的实际材料树校验为 `publish=False`，完整引用复核与现有 Coverage 消费未被快路替代。

`test_upgrade_review_regressions.py::test_legacy_completed_first_unified_verify_is_readonly_including_remote_store` 的两个真实节点均通过：远端 put 为零、控制锁未调用、SQL/FGA 为零、原对象全集与 Coverage epoch 不变。首次定向 **7 passed / 6.91s** 包括既有新统一 completed 正例及未完成四负例；最终 review/coordinator/CLI/public legacy/registration/E2E 加 R9 最终尾检精确四节点组合 **87 passed / 58.72s**。共用结果 helper 的 fresh happy 与 before_history/after_history 丢本地材料三个独立消费者另 **3 passed / 5.01s**，不机械累加为唯一用例总数。R11 关闭。

## 已复查的实质问题及修复证据

1. **original new_run flow 冻结后恢复漏引用前检**：原 `reconciliation_ref=None` 分支只检查 SQL/权限，业务配置变化可在若干 Run/FGA 写入后才被引用拒绝。现 `_admit_flow` 对所有 frozen 分支执行完整引用观察，并在首次维护锁 bootstrap 前及锁内进行适用的只读准入。新增原生 E2E 在 history→freeze 后中断、修改无 SQL conversion 的 FlowVersion 配置且保持时间/引用 revision 不变，验证继续执行在任何 Run/业务/FGA 写入前拒绝。主 Agent 最新联合组报告 **30 passed / 24.02s**，包含此新用例。
2. **完整引用核验可能拼接不同批次时点**：现 `ReferenceMigration._verify_tail` 在签证同一原生事务中，按 tenant/root 稳定序取得业务 root/index guard，批量复读实际业务/source/version 与完整 index，对比先前完整验证的实际快照，复核 additions/retired/来源与版本全集。四个原生故障用例证明业务/索引无时钟变更、真实新增来源变更、空根生命周期变化均不能签 Coverage。仍要求停写；不宣称任意在线并发的线性一致。
3. **身份断言被完成快路忽略**：环境及显式 backup/schema 断言现位于 completed 返回前；真实正整数且有效存在的 User 才能执行。不存在的正数 actor、0/负值、环境与材料冲突均有拒绝路径；旧 DBA descriptor 的内容不作为必须重新读取的备份证明。

## 七维审查要点

### 1. 边界条件

`ready` 与 `can_apply/preflight_complete` 分开；dry-run 通过不会伪造 Coverage ready。空来源、零引用及空租户有明确证明，缺页/缺来源不作为空集。语义 DAG 严格校验 Run/kind/SHA/schema、递归目录数量/范围、重复 SourceKey、叶与目录计数，不只校验首叶。R1 是当前实际剩余容量边界。

### 2. 权限与认证

配置与环境由真实 CURRENT/ACTIVE 或原 frozen pin 约束；操作者通过真实 User 行的 active 检查。新批仓储逐类保持 tenant 验证；历史 AFTER 精确查询先应用受控投影，再验证 owner，不把被原 tenant 条件隐藏的 dirty 行当缺失。原始 BRR AFTER port 只允许 `target_tenant_id` 纠正，禁止增删、重排或改其他原字段。未改在线来源/引用业务门禁、删除授权或租户创建策略。

公开 legacy writer 已接同一控制互斥/原生事务 guard、有效 actor/环境和只读前检。P Owner CLI/registration/公开 mutex 组 **45 passed / 32.33s**，另有异常/取消后 pending 保留与锁释放负例通过；R9 补齐 strict tenant 页外的非法子行闭口。

### 3. 并发安全

引用 Prepared 批绑定 TransactionIdentity、Run/原 hash、期望 checkpoint；批内回滚、未知 COMMIT 回读及批末原子 checkpoint 均有实际仓储测试。原 ordinal/fold/旧 checkpoint 不改。原生 root/version 锁按稳定键取得，不能凭 IN 行序宣称稳定锁序。executor 的 durable 外部意图未闭合时拒绝新 attempt，旧 token 被 SQL 事务 fence 拒绝；不以 TTL/一次 AFTER 观察证明未知 FGA 请求结束。真实 MySQL/DM8 的 NOWAIT/连接丢失仍需集成环境验证。

### 4. 信息泄漏

私有目录/文件权限、canonical/SHA/大小限制、不可变发布与真实远端回读分开。日志字段白名单、结构化 cursor 哈希及 projection metric 聚合不输出配置载荷或凭据；原始历史行另存私有运维备份，不把全库原值作为 replay 共享材料。报告位置面向维护操作者，不作为在线 API 的用户输出。

P Owner 另以真实 planner/SQL before、仅替代外部 `F118Publisher.ascan` 的边界注入 provider 错误，在含 exception/diagnose/backtrace 的 Loguru sink 下验证不泄漏外部文本或 SQL bind。迁移专有 warning 改固定 reason/type，原异常/账本传播不变；stage/input/artifacts/minio 组 **75 passed / 26.68s**，不是只验证 main 的一层输出。

### 5. 测试覆盖

统一 CLI 原生测试穿过实际 planner、SQL/Run/CAS、权限发布、引用批次、材料读取及 Coverage；只替代外部协议传输及 SQLite 不支持的维护控制连接锁，不模拟最终 ready。候选测试覆盖同事实重复 dry-run 同 SHA、一个匹配加旧不匹配仍唯一选择、两个同时匹配零写阻断、已绑定后本地材料全丢的共享恢复。AC-165 的 SQL 精确 AFTER 边界仍保留：R receipt 不能扩大 Knowledge/default SQL scope；没有完整原生变更证据时明确 BLOCK/维护复核，不虚构 ledger。

### 6. 代码风格

已审入口依赖应用协议/Owner repositories，未新增 HTTP/Celery/前端流程；common 指标 sink 不反向 import knowledge。R 所有 15 个明确路径 Ruff 与按仓库相对路径调用 arch-guard 通过。用绝对工作树路径运行 guard 会把既有测试 fixture 的 FGA 导入误识别为业务模块；原测试 import 与 HEAD 一致，未为绕过守卫修改规则或生产代码。

### 7. 文档同步

R1/R2 当前已收敛。正常操作、实现快照、证明范围、尾检开销、超大单来源行为及未验证平台已按真实实现记录；旧脚本 165 执行记录保持独立。历史任务/设计调查记录保留其时点，当前实施段明确覆盖此前待确认/未实施状态。

## 验证证据与实际边界

本报告列出的本轮实现验证均使用离线 `config=/private/tmp/f118-reference-offline.yaml`（内容 `{}`）、私有 tmp materials；审查验证阶段未连接 165、未写生产、R 未执行 Git 提交。

- Owner 组合：`test_reference_upgrade_batches.py`、`test_reference_reconciliation_materials.py`、`test_reference_batch_repository.py`、原引用 application/registration、E2E、旧 CLI、原 M2 默认热点断言：**97 passed / 99.26s**。此组发生于最后一项 original flow 前检修复前；不能将后来新增用例并入该命令的通过数。
- 后续主 Agent 联合组：fresh new-run + E2E 9 + 旧 CLI 20：**30 passed / 24.02s**（主 Agent 提供）；覆盖新增 original-flow 漂移零写拒绝。
- 额外 plan/backfill/QA/知识在线仓储组：**69 passed、3 failed / 56.16s**。三个失败均在未修改的 `test_kn_reference_repository.py`，fixture 仅建 Knowledge 表，而既有 SQL 查询 ResourceReferenceTombstone。该 test 文件与 owning `model_reference_repository.py` 已验证与 HEAD 字节一致；不修改无关 fixture、不把该组写成全绿，未另建干净 HEAD 重跑整个选择。
- 最终 N/2N 真仓储规模组 **8 passed / 16.80s**，已计入 R9 必需完整性扫描；先完成 SQL/权限，统计包含语义采集及本次引用动作，排除 history 与初始权限耗时。并非生产耗时承诺。
- 尾检 full-index 字节/预算辅助值不进入证明 fold 的 Owner 小组 **35 passed / 32.60s**（排除两个大来源）；两个真实大来源测试另 **2 passed / 67.85s**，细节见 R1。最后的 C3 闭口另见 R9，最终规模/组合记录须包含此变更。
- C3 闭口后的原引用/证明/批仓储/旧 application/registration 定向组 **65 passed / 72.56s**（排除两个大来源与八个规模用例）；无后续 R 生产/测试改动，稳定时点 **2026-11-20 15:05:32 UTC**。
- 主 Agent 最终统一静态门禁：**91 个 Python 文件 Ruff check/format、arch-guard 与 diff-check 全绿**（主 Agent 提供；本报告未另行篡改其检查范围）。
- R11 后的主相关最终组合 **87 passed / 58.72s**、共用结果 helper 的新建流程消费者另 **3 passed / 5.01s**（P Owner 提供），选择和去重边界见 R11；原生两红转绿覆盖旧 completed 首次统一严格复核的远端存储与控制锁只读。
- 主 Agent 失败选择的 HEAD 精确对照 **147/147 首因一致**；当前选择复跑 **109 failed、38 errors、7,721 deselected / 12.33s**。分类为 44 项上下文/F048 未配置、38 项 sandbox 本地服务 PermissionError、12 项 SQLite 缺表、16 项旧 test-double 契约不足、37 项旧就绪/业务断言/错误映射，不能统称环境问题或写成全目录全绿。全目录最终汇总由主 Agent 实施报告记录。

| 来源数 | 实际根数 | 路径 | 语义采集 SQL | 总 SQL | 事务 | 耗时(s) | tracemalloc 峰值(MB，十进制) |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 13 | 2 | 仅登记 | 4 | 197 | 31 | 0.378 | 1.43 |
| 25 | 2 | 仅登记 | 4 | 221 | 31 | 0.450 | 1.47 |
| 13 | 14 | 仅登记 | 4 | 230 | 31 | 0.393 | 1.37 |
| 25 | 26 | 仅登记 | 4 | 290 | 31 | 0.509 | 1.87 |
| 13 | 2 | 完整引用含尾检 | 4 | 601 | 96 | 1.775 | 8.00 |
| 25 | 2 | 完整引用含尾检 | 4 | 637 | 96 | 2.244 | 7.86 |
| 13 | 14 | 完整引用含尾检 | 4 | 671 | 96 | 2.274 | 7.85 |
| 25 | 26 | 完整引用含尾检 | 4 | 779 | 96 | 2.063 | 7.86 |

尾检包含一次 O(root) 稳定标量锁及有界精确批复读；不声称所有 SQL 都是批查询、所有 I/O 都减少或恒定内存。tracemalloc 不等于进程 RSS。真实 MySQL/DM8 行锁/未知提交、真实 OpenFGA/MinIO 及约 5.5 万来源的同等级克隆演练尚未在本报告中验证。

## 独立验证边界

- preparing 的 before_history/before_freeze 两个中断点、全部本地材料丢失、只读 dry-run 和同 apply 共享恢复已列入原生用例与当前 QA；不重新生成原历史计划。
- 结果合同区分 can_apply 与 ready、历史动作统计范围、原生完成状态与报告/清理失败；R3～R8 已有对应负例，私有报告不替代原生账本。
- 全目录最终汇总与后续统一静态门禁由主 Agent 记录到实施报告；本文只记录已取得的失败选择 HEAD 首因对照，不推算其余通过总数。
- R10 最终拒绝/组合冲突及 R11 旧 completed 首次统一严格复核只读原生回归均已关闭；本轮本地增量七维审查 PASS。
- MySQL/DM8 NOWAIT/真实连接失锁、真实 OpenFGA/MinIO、生产规模克隆和开服业务验收仍未在本报告中执行。该后续范围不由本地 PASS 代替，也不包含 165 操作、发布或合入授权。
