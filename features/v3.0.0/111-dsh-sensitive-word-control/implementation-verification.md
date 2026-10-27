# F111 实施验证与任务审查

- 首次记录：2026-10-23；更新至：2026-10-24
- 执行范围：用户于2026-10-24新增授权合入最新work120并推送，经Drone构建后仅部署109 DSH13001并启动当前客户端联调；历史“不提交/推送/部署”描述仅指当时阶段。
- 基线：B 2e6b5ae0；G 2995df6f；D 01e09d0，工作树及完整提交见 tasks §2。
- 当前阶段：核心实现及work120兼容候选源码审查完成，任务179/196；T119/T120的MySQL子项已独立通过，Linux DM8、完整授权E2E、容量与演练尚待验收。下文按实施顺序保留历史证据，早期“尚未执行/尚未实现”描述仅指当时阶段，最新结果见末尾记录。

## 1. 执行记录

| 任务 | 已执行验证 | 任务自审 | 状态 |
|---|---|---|---|
| T007 | 修改前扫描后端全部 Python AST，26170–26175 无占用；错误唯一性测试 1 passed；六个注册项 HTTP/ClientCode/消息检查通过；Ruff 与 arch-guard 通过 | 基础设施：分层、模块 261 五位码、静态安全消息、无敏感值、design §6.2 同步均 PASS；文件范围 1，依赖无 | 完成 |

T007 命令（cwd=src/backend）：

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest --confcutdir=test/dsh -p no:cacheprovider test/dsh/test_error_code_uniqueness.py::test_dsh_error_codes_are_unique -q
PYTHONDONTWRITEBYTECODE=1 /Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m ruff check --no-cache bisheng/common/errcode/dsh.py
bash ../../scripts/arch-guard.sh "$PWD/bisheng/common/errcode/dsh.py"
```

新代码的三语 api_errors 覆盖由既定 T130 生成验证，当前不声称该项全量检查通过。初次 Ruff 因功能工作树写缓存受沙箱限制失败，改用 --no-cache 后通过，不修改工具规则。

## 2. Wave 1 初始环境与当时未执行验证

新工作树没有预装依赖。现有主仓 Python 3.11 环境仅只读调用，禁止改动其依赖；独立 Java/Maven 与前端环境准备情况将在任务结果记录。真实 MySQL、Linux DM8 的 fresh/upgrade/回退、E2E、负载以及部署均未执行，不能由离线编译或 SQLite 结果代替。

## 3. Wave 1 与 T016 基础设施验收

Wave 1 的 17 项（原 T001–T015，及回归补充 T133/T134）与 T016 已完成；这是基础设施交付，不代表模型拦截、回传 API、策略界面或 Desktop 行为已实现。

| 任务 | 实际验证及交叉自审 | 结果 |
|---|---|---|
| T001–T004 | 7 表/32 索引分别经 MySQL 方言及 Linux 原生 dmPython 2.5.32 / dmSQLAlchemy 2.0.12 编译；默认值、UNKNOWN、来源 CHECK、显式租户登记及持久水位检查；主 agent 对照模型与 DDL | PASS |
| T005–T006 | 30 项合成 DTO 断言；既有审计上下文 21 tests；严格字段/版本/ID/UTC/64KiB/深度/摘要/提示清洗；Java 纳秒字符串原样保留；返回 DTO 与可空默认检查 | PASS |
| T008 | 29 个增量列 DDL、4 个索引及 mode CHECK 与模型一致；单 head；独立 agent 38 项结构与重复升级检查；持久化数据库回归 24 passed；DDL-only、两目标文件和拒绝破坏性 downgrade 审查 | PASS |
| T009 | fixture smoke 覆盖 JSON 持久化、唯一约束、可信身份变化、严格租户读写、提交失败回滚、监听器/上下文恢复；未启动模型 runtime；既有审计等 114 tests 通过 | PASS |
| T010–T011 | Maven 编译 99 源文件；Spring 配置边界、MyBatis 映射、不可变快照 31 断言；无新增密钥/凭据；实体与 DDL 列对齐 | PASS |
| T012–T013 | Java/MySQL/DM 静态列对齐（策略 11、Outbox 15）；整体判空先于所有 DROP，默认拒绝缺少停写确认；MEDIUMTEXT/CLOB 与 UTC 微秒同义；真实库 fresh/upgrade/回退留 T120 | PASS_WITH_NOTES |
| T014–T015 | 新类型严格编译、定向 ESLint；Platform 551 strict files 通过；冻结离线安装和 v4=4.44.0/v3=3.39.3 共存；锁仅新增既有包直接引用 | PASS |
| T133 | 两项专项测试先复现 source_id AttributeError，再修复显式别名/阶段映射；旧 UNKNOWN 保留、外部可空/N_A 合法；未查询明细不声称 AVAILABLE；114 tests 通过 | PASS |
| T134 | 既有本地化 UNKNOWN 接受空值，不产生虚构失败；无样式或翻译变化；Platform typecheck 和相关 Card/Panel/Group/Tree 30 tests 通过 | PASS |
| T016 | 上述一致性验收；保留原 main 83 个迁移字节哈希校验，允许后续合法链路并锁定 work110→F111；增补结构一致性、重复升级、大小写约束反射及安全回退测试；17 个变更 Python 文件 Ruff/lint/format 与 arch-guard 通过 | PASS_WITH_NOTES |

基础设施逐项按 task-review 的适用清单检查：分层、数据库约定、信息泄漏、设计同步及目标文件范围通过；声明任务无前置业务测试要求。T133 采用既有回归确证缺陷的红转绿轻量兼容修复，未扩展到后续完整查询；T134 是既有类型消费者的最小修复。所有实体/DTO/字段细节已同步 design §9，任务粒度不超过两个人工目标文件。

补充命令（cwd=src/backend，Python 为前述只读 3.11 环境）：

```bash
python -m pytest --confcutdir=test/database -p no:cacheprovider test/database/test_alembic_single_head.py test/database/test_alembic_dsh_main_upgrade.py test/database/test_dsh_audit_work110_migrations.py test/database/test_alembic_online_helper.py -q
config=/private/tmp/f111-synthetic-config.yaml python -m pytest -p no:cacheprovider test/dsh/test_model_audit_setting.py test/dsh/test_model_audit_groups.py test/dsh/test_model_audit_tree.py test/dsh/test_foundation.py test/dsh/test_model_audit_contract.py test/dsh/test_model_audit_contract_api.py test/dsh/test_model_audit_flow.py test/dsh/test_model_audit_tree_http.py test/dsh/test_model_audit_user_names.py test/dsh/test_audit_response_diagnostics.py -q
```

临时合成配置仅含 `{}`，没有复制真实凭据。独立 JDK/Maven 位于 /private/tmp/f111-gateway-tools，编译/68 项既有 Gateway 回归/31 项 smoke 日志在同目录；backend fixture 与原生 Linux 方言编译脚本位于 /private/tmp/f111-wave1-smoke，DTO 断言脚本为 /private/tmp/f111_dto_smoke.py。这些 smoke 不等于真实双库执行；DM JsonType 的实际编译输出是 TEXT，真实存储行为仍待 T119 验证。

## 4. 完整前端质量门禁的既有基线问题

完整 workspace `pnpm lint` 和 `pnpm typecheck` 均已实际执行，**当前失败，不能标绿**。环境最初缺失 Client 的 tsc，补齐全 workspace 冻结离线依赖后已排除这一环境问题。

- Platform lint：93 errors，6 个未修改文件。
- Client lint：21 errors，2 个未修改文件，另有过期抑制提示。
- Client typecheck：useAiChat.test.ts:294 缺少既有 ChatMessage 必填字段，1 个既有错误；Platform 551 strict files 与独立 file-viewers typecheck 通过。
- UI 与 file-viewers lint 通过；本次变更类型/Card 的定向 ESLint 通过。

逐个报错源文件、相关 ESLint/TS 配置及抑制文件均与 HEAD 字节一致；关联 ChatMessage 定义与 manifest 同样未变。证据在 /private/tmp/f111-{platform,client}-eslint-baseline.json 及对应原始报告。未修改抑制清单或开展无关代码修复；全特性 T132 仍须如实报告这些未通过门禁。T016 的 PASS_WITH_NOTES 仅表示已完成它声明的基础设施一致性验收，不把完整 workspace 门禁视为通过。

## 5. Wave 3 前置测试与三语文案

| 任务 | 已执行证据 | 自审与状态 |
|---|---|---|
| T017、T019 | 82 项预期 RED、7 项旧 SSO 检查 PASS；失败仅来自待实现 HMAC 29 项和 reducer 53 项；36 阶段组合、旧命中、重复/终态/纯函数均有行为断言 | 测试任务命名、AC 全编号、文件范围 PASS；未写实现桩，测试任务完成，行为仍待 Wave 4 |
| T055、T061、T065、T077、T083 | 五份 Java 测试语法/空白检查通过；Maven 在 testCompile 因配对生产类缺失而预期 RED；T083 单独编译仅两处缺失被测类，真实 HTTP/Mockito SQL 边界 | 测试自审 PASS，尚未执行生产行为断言；日志 /private/tmp/f111-gateway-tools/wave3-red-final.log |
| T099、T100、T101 | 每语言新增 119 个 contentSafety 叶键、6 个错误码；三语键/插值/唯一 JSON/原文不变检查 PASS；后端错误与三语覆盖 4 tests PASS；locales check 与 check-i18n PASS | 实现任务 i18n/文件范围/设计同步 PASS；生成器更新 6 个 api_errors 产物，未手改；不替代 T130 |
| T111 | 标准 npm test 完整执行 Office 准备和 PPT build 后进入 Vitest，18 项预期 RED；直接 Vitest 定向执行也为同样 18 RED（缺少归一化、文案导出与声明）；node --check PASS | 测试任务 AC/命名/文件范围 PASS；只新增指定 test；日志 /private/tmp/f111-desktop-copy-red.log |

Desktop 独立 worktree 的 npm ci 离线模式缺包后，使用正常 npm ci --prefer-offline 成功；postinstall 补丁与品牌资源准备成功，没有修改真实 Profile 或启动桌面应用。标准 npm test 的 Office/PPT 前置准备是构建产物，不能替代安全适配器实际 UI 验收。

接口补充：profile 成功后 Token 的 exp 只能缩短缓存寿命；opaque/无法解码 Token 的可信 profile 可用于本请求但不可缓存。T056 因此补充上下文的 nullable expiresAt 表达未知，禁止伪造截止时间。可选会话提示异常只能清洗/丢弃关联提示，仍记录核心安全事实，不能因为提示无效丢失命中事件。

## 6. Wave 4 配对实现与交叉审查

| 任务 | 实际验证 | 任务自审 |
|---|---|---|
| T018、T020 | HMAC/reducer 配对与旧 SSO 94 passed；相邻扩展回归共 152 passed；Ruff、架构检查通过；旧 verify_hmac AST 行为保持 | 分层、命名、纯函数/序列化、信息泄漏、设计同步 PASS；配对测试和依赖已完成；数据库/前端项 N/A |
| T056、T084 | Profile 24 + Proxy 9 = 33 passed，真实本地 HTTP 覆盖身份解析、超时、无重试/重定向、原始流/取消生命周期；未知 exp 用 null 表示 | 文件范围、依赖、配对测试、无业务凭据日志、设计同步 PASS；不在模型后端接入网关 |
| T062、T066、T078 | Policy 8 + Admin 8 + Outbox 9 = 25 passed；条件 CAS/租约 SQL、显示租户条件、不可变快照、提示清洗、64KiB/深度和失败保守行为审查 | PASS；SQL 端口使用 Mockito，真实数据库并发与事务未执行，不能由本项代替 T119/T120 |
| T112 | 文案配对及既有 enterprise-package 28 passed；node --check 与 npm run typecheck PASS；独立 agent 复审无 HIGH/MEDIUM 发现 | 命名、三语固定文案与租户提示分离、白名单代码、无关账号行为保持、两目标文件、设计同步 PASS |

主 agent 在全部 Wave 4 文件完成后使用准确测试类名重新执行 Gateway 11 个测试类，Surefire 合计 **126 tests / 0 failures / 0 errors / 0 skipped**；日志 /private/tmp/f111-gateway-tools/wave4-parent-exact.log。其中 58 项新行为 + 68 项既有回归。

Backend 与 Desktop 日志见 /private/tmp/f111-desktop-copy-green.log、/private/tmp/f111-desktop-typecheck.log；Gateway 子集日志为 wave4-b-tests.log 与 wave4-final.log。任务 review 按七项清单逐项适用检查，依赖和目标文件检查 PASS，详情同步 design §9。本 Wave 尚未接线模型拦截入口、审计回传 API 或管理页面。

用户于 2026-10-23 明确目前没有 DM8 测试环境，DM8 实测保留待验收。继续不依赖它的实现和当前环境测试，后续真实双库检查保持未完成。

隔离 MySQL 环境准备：新建仅监听 127.0.0.1 随机端口的 f111-dsh-mysql-isolated 容器，镜像 mysql:8.0，实测版本 8.0.46，SELECT VERSION() 连接检查通过。凭据为临时生成的合成测试值，未复用真实账号。当前仅完成环境准备，没有执行 F111 DDL、业务迁移或 T119/T120，不能勾选真实库验收。

主 agent 补跑 HMAC/reducer/旧 SSO 精确三个测试文件：94 passed（/private/tmp/f111-wave4-parent-backend-exact.log）。首次命令的旧 SSO 路径误写为不存在目录而未收集，已定位实际 test/sso/test_sso_hmac_auth.py 并纠正重跑，未把首次执行视为通过。

## 7. Wave 5 先行测试

- T021：19 项预期 RED，全部因为待新增 content_safety Repository 不存在。主 agent 逐行读取 327 行测试，检查哈希原始值/缺失-null、严格租户、默认保留、有效旧主行豁免、已提交重试及真实 SQLite 唯一键异常控制流；不把 SQLite 当双库证明。Ruff、文件范围、AC/命名、依赖与测试子集 review PASS；日志 /private/tmp/f111-wave5-repository-red.log。
- T057：414 行，26 测试方法/38 预定用例。Maven 和定向 javac 预期 RED；后者恰有 3 处缺少 DshIdentityCache，无其他编译错误。主 agent 读取测试，覆盖原子 value+PTTL、非滑动寿命、读取耗时、Token skew、负缓存、坏缓存和完整 Token 键；review 的 AC/命名、文件范围、依赖 PASS。日志 /private/tmp/f111-gateway-tools/t057-red.log 与 t057-focused-javac.log。断言尚未在生产实现上执行。

复用匹配器的实际缺陷：现有 ACPlus 对 words=[acbcc,bcx,cca]、text=acbcca 仅返回 acbcc@0，漏掉 cca@3。主 agent 在当前真实编译类上执行最小 Java 脚本 /private/tmp/f111-ac-minimal.java 复现；不是 mock 推断。T063 加入回归，T064 仅在 DSH 匹配器构建环节修正完整 failure-chain，继续复用 ACPlus，不扩大为旧应用过滤器重构。

T063：349 行、20 项前置测试；主 agent 完整阅读目标文件，命名/AC/信息安全、单文件范围及依赖复核 PASS。Java 17 语法和 git diff --check PASS；Maven 预期 RED 仅缺配对生产类及其类型，日志 /private/tmp/f111-gateway-tools/wave5-red-final.log。包含词、多层失配、150 固定 seed 独立 substring oracle、1MiB/30k/256码点、2编译/200k节点/权重、缓存5秒及旧读版本覆盖均有断言。生产断言尚未执行。独立临时 Java 探针 AcRepairProbe.java 验证局部 BFS 失配链修正可使真实 ACPlus 对这150组与oracle一致，不以临时探针冒充 T064 实现。

补充真实 Java 有界性复现：/private/tmp/f111-ac-bounded-repro.java 在 -Xmx64m 下，256 个长度 1–256 的合法 a 前缀词与 10000 个 a 字符触发旧 ACPlus.indexOf 的 OutOfMemoryError，探针捕获并明确输出。该结果只证明无界命中列表的放大，不是完整网关堆容量测量；T064 收集阶段有界修复及 T070 扫描契约需验证。

## 8. Wave 6 配对实现

T022：前置 19 项全绿，扩展仓储/状态/HMAC/设置/分组/树/基础回归 166 passed；主 agent 独立运行仓储/HMAC/状态/旧SSO/分组 138 passed，日志 /private/tmp/f111-wave6-parent-backend.log。额外合成检查覆盖错租户/bypass在SQL前拒绝、错归属不能豁免保留、UUID统一小写存储且原始wirehash保持。Repository不提交事务；唯一竞争的IntegrityError传播由T030统一恢复。主 agent 逐行读唯一目标文件，task-review：#1分层PASS、#2既定命名PASS、#3内部返回N/A、#4数据库/UTC/严格租户PASS、#5前端N/A、#6信息泄漏PASS、#7设计同步PASS；范围/前置测试/依赖PASS。Ruff格式/检查/F821、arch-guard、空白检查通过。没有真实库并发证明。

保留闸门为设置行 FOR UPDATE，与清理水位互斥；可能串行化同租户回传事务，真实库并发/负载阶段须观察，当前不移除互斥以追求单元吞吐。原始 UUID 大小写会导致不同wirehash，存储编号统一小写；Receipt后续应保持请求event_id响应契约。

T058：真实 JUnit 定向运行全部 38 用例，38 successful / 0 skipped / 0 aborted / 0 failed；日志 /private/tmp/f111-gateway-tools/t058-private-compile.log 与 t058-private-tests.log。当时同 Wave 词库类型尚未写完，Maven 全 testCompile 被其缺类阻断，因此使用私有 classdir 编译实际 Profile/配置/上下文/Cache 依赖并运行原 JUnit 测试（无 stub、无改断言）；Wave 6 结束前仍需常规 Maven 合并回归。主 agent 逐行读取唯一 305 行目标文件，严格JSON/4KiB/时间和PTTL边界、完整Token散列、4096本机容量、boundedElastic Redis I/O、安全日志与绝对TTL复核 PASS。测试/依赖/文件范围及task-review适用项 PASS；T060分布式 owner fencing 和请求合并尚未实现，本任务不声称已有。

Wave 6 补充复核：T058 最终取样修正后 38/38 再次通过；独立 agent 以SHA-256 1485bbe169cd0c6bd5639aced960e2985f1569bc2a79646c17a8a3156466900a 版本只读复审，没有新 HIGH/MEDIUM 问题。T009 fixture 及 T133 新增测试 docstring 的两处中文 AC 注释改为 English Coverage AC，业务 literal 未改；Ruff及关联 groups/repository 44 passed。

独立 Redis 环境准备：新建 f111-dsh-redis-isolated，仅监听127.0.0.1随机端口、合成凭据，实际Redis7.2.16/Linux aarch64，INFO/PING通过。未使用已有Redis，无FLUSHALL。真实cache/Lua小验证正在准备，当前不能据此宣称端口行为或多副本预算已验收。

T064/T063 收尾：前置测试增补至31项（原20项，加实际漏检/重叠摘要/非终端链/绝对发布时间/停用上限/Unicode/已提交保存/元数据计权等回归）。修改前故障注入确认RED，修复后31/31 PASS；日志 wave6-policy-review-final.log，RED为wave6-save-review-red.log与wave6-save-status-red.log。既有GenericJackson Redis模板参数加引号、迟到SET PX延寿、CAS后编译忙导致已提交误报失败、停用元数据漏计、原始超限/Unicode绕过和413错误码均已修复。

主 agent 逐行读取两目标生产文件，独立agent用真实service/matcher探针复现两项P2后修复；任务review #1分层PASS、#2命名PASS、#3内部不可变record序列化PASS、#4显式租户/CAS边界PASS（无新增SQL/DDL）、#5前端N/A、#6无原文/凭据诊断PASS、#7设计同步PASS；配对/依赖/范围PASS。git diff --check PASS。T064生产2文件，增补测试归原T063单文件，未改全局AC、Redis模板或其他业务文件。

最终主 agent 常规 Maven 重跑13个准确测试类：**195 passed / 0 failures / 0 errors / 0 skipped**，日志 /private/tmp/f111-gateway-tools/wave6-parent-final.log；其中本轮Policy31+Identity38，其余126既有选择。同版本真实隔离Redis策略验证PASS（wave6-live-redis.log）：默认GenericJackson模板隔离为专用String模板、PTTL原子读取、int64版本CAS、同版本不续期、刻意迟到PUT被拒绝、Pub/Sub真实回调。身份缓存真实Redis补充27断言PASS，/private/tmp/f111-redis-test/cache-smoke.log，仅创建并清除6个明确临时key，无FLUSHALL。它们不等于T060多进程owner fencing、MySQL/DM8或部署验证。

Wave7必要补齐T135：实际AdminClient返回Void但Store要求updated_by>0，禁止从客户端伪造。新增两文件兼容任务，先红后绿追加可信管理身份返回，原授权行为保持；T068仍两文件。总任务135项，当前完成43项。capabilities的目标授权和homeUrl Origin约定同步design，未新增配置、backend网关感知或放宽管理范围。

## 9. Wave 7 前置测试与必要身份补齐

T069：仅新增 DshSensitiveScannerTest.java，262行、17普通测试+4参数用例（21预定执行用例，另含逐切分循环）；覆盖 AC-20、AC-21、AC-22、AC-25、AC-26、AC-35。UTF16绝对水位、Unicode码点尾部、跨UTF8字节/高低代理项、JSON解码、同域连续/异域隔离、末尾完成、单调水位、阻断终态与有限摘要均有断言。Java17语法PASS；定向javac预期RED，仅1处缺少待实现Scanner类，无其他诊断，日志t069-focused-javac.log。独立标准库fixture小验证PASS：所有UTF8切分重组、真实JSON转义和代理项字面量正确，t069-fixtures.log；未添加生产桩。task-review测试子集：命名/英文完整AC/单文件/依赖PASS，前端N/A；配对生产行为尚未执行，不以语法检查冒充通过。

T023：484行23用例，主agent完整读取测试；覆盖保存事实→摘要同事务、输入外部/输出编号未知、不猜关联、原生优先、可信身份变化、会话dirty、幂等和计量守恒。主agent组合运行结果 **23预期RED+72PASS**，23项均缺投影Repository；/private/tmp/f111-wave7-parent-backend-red.log。唯一键故障注入仅验证回滚，不声称SQLite复现双库写锁竞争。Ruff格式/检查、十类合成事件及真实存储fixture smoke PASS。

T059：428行17方法/18预定用例；真实Cache/Profile回复及Redis原子存储边界double，未实现测试coordinator。32在途/64等待、取消/队列/总deadline、Redis故障、完整Token/namespace、旧owner迟到成功与401均有公开结果断言。私有javac仅4处缺Verifier，t059-focused-javac.log。T067：327行17前置测试，HTTP standalone使用真实AdminClient+本地backend响应；TS扁平DTO、8限额、实时授权、Origin、可信操作人、409/400/413/503和失败信息不泄漏覆盖；私有javac仅1处缺Controller，wave7-controller-red.log。主agent逐行读取两文件，测试subset review命名/英文完整AC/单文件/依赖PASS。

三份Gateway新测试集中Maven预期RED：/private/tmp/f111-gateway-tools/wave7-parent-red.log；编译先在Verifier/Scanner缺类处停止，Controller独立RED另有证据。生产行为尚未执行，未添加stub或把测试double当实现。

T135：原8+新增3实际本地HTTP测试 **11/11 PASS**（wave7-admin-final.log），读取backend UserRead.user_id正int64，缺失/非法或header自报不能替代；旧authorize.then()兼容。主agent逐行审查生产客户端及新增测试，分层/序列化/身份信任/安全诊断/范围/依赖/设计同步PASS。最初全新JVM首HTTP受Netty类冷加载导致1秒超时，已将无网络的HttpClient.warmup置于test setup，未放宽生产预算；冷JVM重跑11/11通过。该观察保留供后续启动/冷验证测试，不把warmup当真实延迟指标。T135只两文件，T067另一个文件，原全局权限逻辑不变。

## 10. Wave 8 配对实现（2026-10-24）

主agent集中backend回归：165 passed，日志 /private/tmp/f111-wave8-parent-backend.log。主agent集中Gateway常规Maven16类：261 tests / 0 failures / 0 errors / 0 skipped，日志 /private/tmp/f111-gateway-tools/wave8-parent-final.log，逐份Surefire XML核对。首次集中testCompile在新增取消释放测试的Flux泛型处失败，负责人修正并完成私有23项，再执行本次集中回归；未把首次失败算通过。

T024：190行唯一目标Repository；23项配对测试全绿，连同相邻回归160通过、主agent组合165通过。已保存事实语义对齐、严格租户、可信身份变化、未知编号不关联、同事务摘要/事实CAS、固定started_at和模型计量守恒均有断言；Ruff/arch-guard通过。主agent逐行审查：#1分层PASS、#2既定Repository命名PASS、#3内部返回N/A、#4严格租户/UTC/显式写条件PASS、#5前端N/A、#6信息保护PASS、#7设计同步PASS；单文件/配对/依赖PASS。SQLite仅合成事务测试，真实唯一竞争仍由T029/T030及双库任务覆盖。

T060：Verifier199行、Cache403行；私有fresh javac/JUnit38+18=56全绿并纳入集中261。实际Redis缓存兼容27断言PASS，/private/tmp/f111-redis-test/t060-cache-smoke.log，精确键清理；该smoke未证明多进程租约。主agent读取两个完整文件，复核固定deadline、32/64预算、原子排队取消、过期任务不复用、先取消源再释放槽位，以及发布/删除/释放owner fencing；旧401不污染新身份。范围/前置测试/依赖PASS，适用task-review分层/命名/不可变身份/安全/设计PASS，数据库及前端N/A，无原始Token日志。

T068：Controller+Request两个生产文件；原T067测试增加rawbody与真实池化缓冲回归至23项，私有和集中均全绿。先Origin/实时身份授权再订阅聚合；8MiB原始JSON/1MiB解码词库、严格UTF8/深度16/重复键/尾随值、未授权不订阅、最坏六倍转义合法词库、成功/解析错误/超限/取消refCnt归零均已验证。私有日志wave8-body-final.log。主agent读取完整生产文件和新增测试，task-review范围/配对/依赖及适用命名/序列化/信息保护/设计同步PASS；无前端/SQL改动。缺失可选Service的HTTP行为已测，完整Spring条件装配仍由T098验证。

T070：唯一Scanner生产文件，22项JUnit全绿并纳入集中。错误状态重开回归先RED后GREEN，t070-error-state-red.log、t070-tests.log；主agent逐行自审、AgentA独立读取Scanner/全部测试/CompiledPolicy.scan，未发现确证HIGH/MEDIUM。UTF16水位与码点尾部、跨片surrogate、独立域、完成/阻断/错误终态和有限无原文摘要一致。task-review范围/配对/依赖、适用命名/安全/设计同步PASS；后端/前端/数据库N/A。

四项完成后更新52/135，进入Wave9。MySQL只完成隔离环境准备，DM8用户确认暂无环境，真实双库、跨进程、部署和性能结果仍未执行，不以当前测试替代。

## 11. Wave 9 前置测试（2026-10-24）

T025：唯一423行测试，21项中13预期RED/8PASS；红测由真实upsert_request不能提升EXTERNAL_SAFETY触发。真实Capture、Writer、Repository、EncryptedStorage配合成SQL/对象端口，未写业务桩。回滚测试的故障标记仍pending明确证明尚未到达事务提交点，不将当前红测误称回滚通过。相邻52PASS；主agent集中新增与既有165项，结果13预期RED+173PASS（/private/tmp/f111-wave9-parent-backend-red.log）。主agent逐行读取；Ruff和task-review测试subset/English完整AC/单文件/依赖PASS。

T071：唯一输入测试266行，23普通+3组参数化16例，共39预定调用。javac及集中Maven预期RED仅缺DshInputSafetyAdapter类型，日志t071-red-javac.log、wave9-parent-red.log。覆盖全历史/连续块与独立域、JSON解码键值、两协议根类型、可读reasoning/refusal/citation、opaque图像和密文/审计提示、Unicode、原始bytes与错误400/invalid_request。外部事件深度16不误套模型工具参数，支持20层合法嵌套。

AgentA独立审查发现三项MEDIUM测试问题：原图像fixture非现有inline协议、缺Chat根string/array与Responses object差异、Unicode坏hint未明确断言核心blocked。已修正并由主agent使用真实B schema现场验证2图像+4根类型行为；补断言后重新javac，仍仅缺配对生产类型。输入超限按design§6.3为400/invalid_request，不把管理词库413口径套入模型请求。主agent测试subset命名/AC/依赖/范围PASS，无生产桩。

T073：唯一387行，27普通+参数化5例=32预定调用；私有javac仅缺Chat adapter的5处类型引用，t073-javac-red.log。主agent完整读取，原bytes/完整事件水位/usage队头/独立choice和reasoning/完整工具JSON/阻断及取消错误/非流字节均有断言。backend原有错误保留原语义，未完成检查state仍ERROR；已BLOCKED优先。测试subset范围/完整AC/命名/依赖PASS。

T075：唯一417行26项；私有javac仅缺Responses adapter，wave9-responses-red.log。主agent逐行读取，覆盖sequence不重编号、跨域有序屏障、done/item/final变化快照独立扫描、工具JSON、reasoning/refusal、引用title、event/累计/非流byte预算和取消。失败/未完成最终快照仍检查其可读output，命中优先；普通error.message不作为模型文本。合法Citation依据现有backend schema，URL独立opaque，title可读。测试subset范围/完整AC/命名/依赖PASS。

三个Gateway类常规Maven集中预期RED，仅缺三个配对adapter类型，wave9-parent-red.log；未生成stub、未执行尚不存在的生产断言。适配器采用(CompiledPolicy,Properties)构造，accept/complete/cancel返回有序完整原事件byte[]，非流正常返回原bytes，state与有界Outcome供后续manager接线；可信request_id注入留T086/T098，不在单元自造编号。四项测试自审完成后更新56/135、进入Wave10。

## 12. Wave 10 配对实现（2026-10-24）

主agent最终Gateway常规Maven19个准确测试类：371 tests / 0 failures / 0 errors / 0 skipped，逐份Surefire XML核对，/private/tmp/f111-gateway-tools/wave10-parent-final.log。三个协议分别Input42/Chat36/Responses32；其余261为既有范围。首次370项全绿后，独立复审发现缺失item结束断言，补真实RED并修后重新跑本次371；不以首次绿测代表覆盖充分。

T026：仅既有model_audit_write.py和model_audit_writer.py，T025的21项全绿；agent12文件组合219PASS（f111-t026-adjacent.log），主agent独立8文件186PASS（f111-wave10-parent-backend.log）。原生首次事实补齐EXTERNAL未知NULL，严格tenant/user/model与已确认非空关联，MODEL原身份校验不放宽。来源与mode同事务flush，安全started_at、阶段/命中/投影版本保持，model_started_at首次固定；不写model_call/额度。主agent读取两份实际完整源及diff，Ruff/format/arch-guard、范围/配对/依赖及task-review适用分层/序列化/租户/安全/设计同步PASS，前端N/A。真实数据库并发仍未验证。

T072：唯一305行输入Adapter。初始39GREEN后，AgentA实际production探针+B schema确认两类MEDIUM：schema业务属性名properties引起误拦，default内业务type值漏检；同reasoning列表连续块漏扫。原T071补3回归，实际39PASS+3FAIL（t072-review-red.log），修后42/42全绿（t072-tests.log）并纳入集中371。独立fresh探针重跑确认normal/reserved schema均不误拦、default命中、content/summary连续块命中且彼此独立，无新增HIGH/MEDIUM。test现301行，未改旧断言。主agent完整自审，内部Inspection保持原bytes与清洗提示，不记录原文；范围/配对/依赖及task-review适用命名/安全/设计同步PASS，数据库/前端N/A。

T074：唯一408行Chat Adapter，原T073追加usage nullable/detail与20层参数兼容2项，再加混载error正文2项，共36。混载错误实际先RED（t074-mixed-red.log），白名单纯DSH error修复后，Chat36/Scanner22/Cache38/Verifier18私有114/114全绿；实际边界smoke12/12（低字节限额、duplicate/trailing、UTF8、bareCR、合法100位JSON数字和纯真实backend错误）。日志t074-{compile,test,boundary-smoke}.log。主agent逐行读生产与新增测试，原事件FIFO/水位/工具完整参数、固定终态、安全prefix和原usage一致；纯error原bytes保留，混载拒绝；name仅非空观察不保留大段文本。范围/配对/依赖和适用task-review命名/不可变结果/信息保护/设计同步PASS，SQL/前端N/A。

T076：唯一502行Responses Adapter，原T075授权增补至32项，旧断言保持。纯flat/nested真实backend错误与mixed error+output先实际RED后修；日志wave10-responses-mixed-red.log、wave10-responses-backend-error-red.log。31项绿后AgentA只读501行源/469行测试，用真实target类复现added工具仅arguments.done、或空message added，最终output=[]竟PASSED。补循环回归两种均先RED（wave10-item-close-red.log），ensureClosed要求item.done后32/32GREEN（wave10-item-close-green.log）；final-only合法message/tool正例保持。主agent在fresh集中target直接重跑原Probe，两场景均ERROR且completed=false（/private/tmp/f111-impl-a-t076/fixed-probe.log）。相邻独立阅读未发现其他确证HIGH/MEDIUM。

主agent读取T076最终完整源和新增测试，核对progress快照前缀SHA256、完整快照独立检查、工具增量与snapshot各自检查、summary/refusal/citation域、未知结构、失败快照、8MiB事件/32MiB累计/编码缓冲及结束释放。范围/配对/依赖和适用task-review命名/序列化/信息保护/设计同步PASS，数据库/前端N/A。内存放大/延迟、全局配额、上游订阅所有权、request_id注入仍待后续真实接线及性能任务。

四项满足当前任务完成条件后更新60/135，进入Wave11。未提交、推送或部署；MySQL/DM8、部署、跨进程与容量验收不由本轮单元/合成事务结果替代。


## 13. Wave 11 前置测试（2026-10-24）

T027：唯一329行测试22项，12预期RED/10PASS；相邻84PASS，f111-t027-red.log、f111-t027-adjacent.log。真实状态派生、查询就绪、停滞worker与原生writer路径；无密钥/无原文表的外部条目可用、外部先排除再读activity/facts、满100页仍推进cursor、提升后恢复原生派生、UNKNOWN用量保持未知。主agent完整读取，Ruff/format/arch-guard和测试subset命名/完整AC/依赖/范围PASS。

T041：唯一会话投影测试16项，13预期RED/3PASS，f111-t041-red.log。覆盖晚到命中独立dirty、外部N_A仅计条目/命中、真实writer提升后去重、无关联清pending后可再关联、双阶段及后续事件去重、事务回滚、租户隔离、模型异常与安全计数独立、实际UPDATE WHERE含tenant与源版本、批次上限200及205行跨批恢复。MODEL的N_A仍拒绝。状态刷新安全dirty断言由T028实现，其余T042；没有跨文件隐含职责。独立agent完整只读复审未发现确证fixture/事务错误。主agent集中六个真实存在的测试文件：25预期RED、112PASS、3SKIP（既有环境用例），f111-wave11-parent-backend-red.log；首次命令引用不存在文件退出4，修正路径后才得到本结果，不计为执行通过。全部红测为待实现断言，不将尚未到达的回滚断言宣称已通过。

T085：唯一544行JUnit测试24项，私有javac预期RED仅14处缺DshSafetyRequestManager及ManagedResponse，无其他编译错误；/private/tmp/f111-gateway-tools/t085-javac-red.log。主agent完整读取，真实Netty上下游、实际Outbox+SQL端口mock、纯定时端口ManualScheduler，未写manager业务桩。覆盖唯一订阅、16检查/8续读独立额度及24线程竞争、64MiB累计入站预算和取消回收、32MiB原始上传与总时限、命中起算30秒/剩余响应字节/断连/关闭、观察订阅取消不持有上游、阶段快照/版本及无原文无用量事实。未运行尚不存在的生产类型，不把编译RED当运行通过。范围/配对前置依赖/命名/完整AC及task-review适用项PASS。

T113/T115：仅Desktop两个新测试文件，共25项，Chat9RED/3PASS、Responses10RED/3PASS；/private/tmp/f111-desktop-wave11-final-red.log。既有adapter/responses/copy共74PASS，f111-desktop-wave11-adjacent.log。真实adapter+BlockAssembler覆盖HTTP/SSE错误、租户提示/编号、正常usage/reasoning/工具标识、Responses无sequence错误优先识别、错误轮次无可执行tool block-end、单调用无重试。读取AgentLoop现有消费入口确认错误finish先于executeToolCalls；这些测试不冒充实际runner执行证据，后者留T118。主agent完整读取并交叉核对，测试subset/完整AC/范围/依赖PASS。

五项满足前置测试任务条件，更新65/135、进入Wave12。原有完整前端基线门禁失败、真实双库/跨进程/部署/性能未执行状态保持，DM8按用户确认留待验收。无提交、推送或部署。


## 14. Wave 12 配对实现（2026-10-24，进行中）

T028：仅status/states两个既有文件；T027+共享T041安全dirty断言23PASS，相邻11文件139PASS（f111-t028-adjacent.log）。EXTERNAL先返回N_A、无pending，状态纯函数不写入，worker在activity/facts前排除且锁读后再确认来源；原100行及annotations保留用于cursor，MODEL/legacy原派生未放宽。主agent完整读取两源，Ruff/format/arch-guard，范围/配对/依赖及task-review #1–4/#6–7 PASS，#5 N/A，design实施细节已同步。

T042：仅conversations/projection两个既有文件；T04116项通过，主agent初次集中6文件137PASS/3SKIP，所有7个内容安全文件190PASS，树/会话/标题/生命周期8文件66PASS。独立agent发现C3 SELECT手工tenant谓词偏差，改用strict_tenant_filter包完整查询并再次只读复核PASS；修后配对及旧groups41PASS（f111-t042-final.log）。写语句保留显式tenant及请求双版本/pending、会话旧三计数条件，set_committed_value避免额外PK-only ORM写；无关联清pending不伪造已计入水位，NA来源提升不重复条目，安全变化与tree revision同事务。批次默认100/最大200，单项失败隔离，持久pending可重试。主agent完整自审，独立agent计数/原子性/隔离复核无确证HIGH/MEDIUM；Ruff/arch-guard/diff-check，范围/配对/依赖及task-review分层/命名/序列化/数据库/安全/设计PASS，前端N/A。

T042真实MySQL补充小验证：在已有专用MySQL8.0.46容器中新建唯一dsh_test_f111_t042_临时数据库，以真实生产ORM建表并调用真实Repository；实际caller rollback、202租户隔离、两线程同主行锁竞争仅一次投影、重复重试、外部NOT_APPLICABLE计数及NULL模型/用量均PASS。/private/tmp/f111-t042-mysql-smoke.py、f111-t042-mysql-smoke.log；finally只删除本次唯一临时库，清理确认PASS。该smoke没有执行Alembic升级/回退、全协议/Outbox竞争/性能或DM8，T119/T120仍未完成。

已验证两项更新67/135；本Wave其他三项仍未勾选，继续实现和独立审查。


Wave12交叉审查进行中记录（不勾选未完成任务）：Desktop主agent独立定向5文件105/105PASS（/private/tmp/f111-desktop-wave12-parent.log），仍等待独立复审。T086初版24项中23PASS，唯一失败是T085 Responses fixture使用标量input而实际backend要求list[InputItem]；主agent核对真实schema后授权只纠正fixture，不放宽生产解析或原断言。

T086在初次回归后发现三项需修复边界：主agent读源确认finishOwner归还预算却未清adapter引用，旧ManagedResponse可继续持有未完成正文；独立agent实际BufferProbe复现8×8MiB未结束Chat行manager计64MiB而raw+line实际128MiB（非解析树/字符串放大）；实际CancelProbe复现同chunk安全prefix后同步client cancel，已确认hit降ERROR且ownerDone后新领取drainPermit泄漏。探针 /private/tmp/f111-impl-a-t086/{BufferProbe,CancelProbe}.java，对应buffer-probe.log/cancel-probe.log。实现负责人正修复并在原T085补RED→GREEN；未经最终复跑不宣称解决，T086保持未完成。


T114/T116最终实现与task-review：仅openai.js/responses.js，原T113/T115授权追加边界回归后Chat14+Responses17共31，既有74，agent及主agent独立集中均105/105PASS（/private/tmp/f111-desktop-wave12-final.log、f111-desktop-wave12-parent.log）；npm run typecheck退出0（仅实际TS集成检查，不冒充插件JS全类型覆盖），限定四文件diff-check clean。初版确定content_filter后malformedtail/EOF覆盖错误已实际probe并先RED后修；Responses真实SDK parseStreamingJson可把截断工具补{}、非object可变成可执行true、缺status可释放工具，补真实RED后修；max-token截断保留文字兼容亦通过。正常完整tool ID、encrypted replay、nullable usage/cached语义、账号/额度原映射保持。

主agent读取完整改动源及实际BlockAssembler max-tokens assemble规则；独立agent只读两生产diff、31配对全量和插件实际pi-ai0.87.1源码，未发现本轮引入的确证HIGH/MEDIUM。既有max-token工具丢弃导致replay hash不匹配会降为可见文字，已比对HEAD同样行为，不扩本轮。范围/配对/依赖及task-review命名/i18n复用/信息保护/设计一致性PASS，backend与SQL检查N/A。现更新69/135，T086仍未完成，Wave13尚未开始；实际runner及界面locale验收不由105项adapter测试替代。


T086最终修复已复验：唯一499行生产manager；原T085仅修真实契约不合法的Responses fixture，增6调用至30。先保留旧版运行原24全绿+新6全红（/private/tmp/f111-gateway-tools/t086-owner-red.log），最终fresh私有30PASS；本轮主agent常规Maven20个准确类401/401PASS，逐份20个新Surefire XML验证0失败/错误/跳过，wave12-parent-final.log。独立A用原实际BufferProbe复跑：requests=4、managerRetained=67108864、adapterRawPlusLine=67108864；CancelProbe同步取消后仍BLOCKED+owner存活，hit后30s ownerDone=true/drainPermit=false/managerDraining=0（buffer-fixed.log、cancel-fixed.log）。两项HIGH关闭。主agent确认owner结束cancel/drop adapter实际引用、可信fallback root及header编号、记录幂等修复；新增6回归均已逐行读取。

SlowDeliveryProbe实际无demand客户端验证保留字节<=8192，上游停止，completion等待排队字节释放，cancel后retained=0（t086-slow-delivery.log）；它不是heap/GC或性能验收。私有相邻union260项中259PASS、1个原T055 ListAppender capture因Netty DEBUG日志并发修改ArrayList出现CME；主agent按实际AppenderBase monitor取得不可变快照，保留原凭据不泄漏断言，定向Profile24/24PASS（wave12-profile-capture-final.log），无业务修改、无削弱断言。401集中结果在此前生产完全相同版本完成，不把union初次失败隐去。

T086主agent完整读取生产及追加测试，task-review范围/配对/依赖、Service边界/命名/序列化/安全/设计一致性PASS，SQL与前端N/A；git diff --check clean。五项实现满足完成条件后更新70/135，进入Wave13。尚无完整Gateway路由接线、运行中端到端/多进程/双库/heap压测或部署验收；DM8继续待验收，未提交或推送。


## 15. Wave 13 前置测试与接线契约补齐（2026-10-24，进行中）

必要任务补齐：真实Desktop当前renderer直接显示failure.message，Host Node的navigator不能代表当前界面语言；仅注册copy或给未消费options传参无效。新增T136（Wave13两测试文件）/T137（Wave14两adapter）并将原T117（仍client/index两文件）移Wave15依赖T137，总任务137，未改变已确认需求或触碰第三方包。现有renderer locale active同步变更与Host配置异步保存存在时差；T117仍须验证真实入口、注册/卸载与默认值，不据字典存在勾选。

T086编号契约复核：原design§6.3明确Gateway生成错误用Gateway UUID，backend编号单独携带。先退回未完成，窄修manager/T085：安全body编号Gateway、正常backend X-Request-ID原样、X-Backend-Request-ID独立、未知编号不猜关联。保留旧真实t086-classes运行已纠正契约断言29PASS/1RED（t086-id-contract-red-tests.log）；fresh实际源30/30PASS（t086-id-contract-tests.log），单一源码/目标测试私有javac无stub。普通Maven本次被新T087尚缺filter类型的testCompile阻断（t086-id-contract-final.log），不误记为执行通过；生产compile已成功，待Wave14再常规集中。主agent完整读取修正，自审编号语义/原bytes/信息保护/范围PASS，恢复T086勾选至70/137。

主agent本Wave backend5文件集中：54预期RED/53PASS（f111-wave13-parent-backend-red.log）；29缺ingest模块、14查询缺能力、11树安全计数/代际行为，未把RED误称运行成功。详细任务审查结果随本Wave收尾追加。


Wave13五项任务自审收尾：

- T029：唯一569行新测试，29预期RED均缺配对ingest模块，相邻85PASS；f111-t029-final-red.log、f111-t029-red-adjacent.log。主agent逐行读全文件，真实Session/commit故障/失败关闭后真实winner事务验证编排，非业务桩；已确认raw Mapping+frozen VerifiedSource端口，原wirehash在清洗前、commit后ACK、异步线程严格租户恢复、丢确认重试、跨tenant主PK不可见时有界event-only、新可信身份变更及保留水位。Ruff/arch-guard、测试subset完整AC/范围/依赖PASS。
- T037：唯一约340行新测试，26项15预期RED/11PASS（最终主agent组合日志）；direction旧模型无字段、当前逐行查用量N+1及新事件Repository缺类型均为预期，未出现fixture误红。默认list仅主摘要/bulk用量和姓名、26例覆盖六态/命中组合/nullable外部DTO/keyset显式条件+tenant/真实request_started默认7至31天/PURGED区别。独立agent读实际ORM/fixture和全测试无确证错误，指出空后续页不能等同PURGED，追加真实保留竞态回归；事件排序按实际索引id，与design已对齐。Ruff/arch-guard及task-review测试subset/范围/依赖PASS。
- T043：唯一约366行15项，11预期行为RED/4PASS，相邻39PASS；f111-t043-red-adjacent.log。主agent完整读取，真实group→fold→tree_step持久事务，不另建安全树；own/branch不重计、外部N_A无原文读取、停用租户补报、summary及safety两版本变更不混代发布、过期owner不可publish均有断言。最终查询DTO属后续任务，未逼T044越界。Ruff/arch-guard及task-review测试subset/范围/依赖PASS。
- T087：唯一395行JUnit、45预定调用，私有javac11处全部缺配对DshContentSafetyFilter（t087-red-javac.log），无其他类型错误。主agent完整读取，真实manager/input scanner而filter orchestration未写stub；测试端routing仅转交真实manager，不冒充T090完成。精确两POST、先managed标记、可信tenant快照、关闭/依赖/license边界、原backend5类身份失效清缓存不重试、9类非身份错误原bytes保留与64KiB观察上限均覆盖。T086编号补正复验后依赖PASS；命名/完整AC/范围/测试subset PASS。
- T136：仅原两个Desktop测试文件，新回调+编号契约共59项，18预期RED/41PASS，相邻74PASS；f111-desktop-wave13-t136-red.log、f111-desktop-wave13-adjacent.log。主agent完整读取新增两节；14RED为回调未消费，4RED为安全body编号优先，原HTTP两项旧错误期望经确认改正，其余断言保持。三语、tenant文字不覆盖、未知账户/额度不走安全本地化、回调异常不泄漏且保留分类均覆盖。范围/前置/命名/完整AC与测试i18n subset PASS，无生产修改。

主agent最终backend5文件55预期RED/53PASS（108项），f111-wave13-parent-backend-red.log；初次54RED/53PASS后新增空后续页保留断言，已重新执行，不沿用旧计数。五项完成后更新75/137、进入Wave14。DM8、真实完整双库/GUI/端到端/性能仍按对应任务待验收，未提交、推送或部署。


## 16. Wave 14 配对实现与交叉验收（2026-10-24）

- T030：新content_safety_ingest唯一生产文件，原T029新增实际全局关联键占用回归；新增case先1FAIL/29PASS，修后30PASS，相邻178PASS。实际独立probe先503且fact丢失，修后COMMITTED/UNASSOCIATED；日志f111-t030-binding-{regression-red,regression-green,probe-green}.log。最多三个完整新事务；仅连续merge Integrity触发第三次event-only，append/commit失败仍不ACK。默认expire_on_commit=True及提交暂停超过2s的probe验证超时不ACK、实际后提交、重试duplicate；不是数据库超时取消证明。原事件hash、两租户MODEL身份/执行/计量及source绑定不变。主agent完整读取源码和追加回归，C独立审阅并实际4项定向PASS（f111-impl-c-wave14-review.log），无新增HIGH/MEDIUM。Ruff/arch-guard及任务分层/命名/序列化/SQL租户/信息保护/设计一致性PASS，前端N/A；范围/配对/依赖PASS。
- T038：仅model_audit_queries/content_safety_queries两生产文件。配对30项、相邻五文件组合78PASS，f111-t038-final-green.log。主列表bulk Call/Evidence/User，无事件查询或N+1；六态、INPUT/OUTPUT/BOTH交集、外部NULL及已知安全摘要PENDING；事件request授权+严格tenant、limit+1/time/id keyset、有限白名单详情、默认7/max31天及空续页AVAILABLE。自审新增4个非str游标ID回归先3FAIL/1PASS，UUID(list/dict/int)的AttributeError被严格类型检查修复（f111-t038-cursor-red.log）。SQLite限长SQL会自动生成OFFSET 0，原observer误报；只剔除末尾真实参数0的该方言产物，不放宽正offset，生产未使用offset()。首次写入用了错误相对路径导致未修复，第一次组合仍3FAIL/75PASS，修正路径后才得到78PASS，未隐去失败。Ruff无cache format/check、arch-guard/diff-check及主agent任务自审PASS，独立C全文复审+实际定向回归无新增HIGH/MEDIUM。
- T044：仅tree_build/hierarchy两个既有文件；T04315PASS，六文件75PASS，f111-t044-adjacent.log。三水位锁内capture/restart/publish，own/branch安全计数沿既有Path累加，dirty仅投影一次；pending包括停用租户，旧租约/清理保持。具体执行经profile_scope，verified ORM对象承接原严格租户/tenant编码主键，未新增bulk写或bypass。主agent读取完整源及diff，配对/范围/依赖及task-review分层/命名/数据库/安全/设计PASS，DTO/UI N/A；Ruff/arch-guard PASS。
- T088：唯一249行preflight filter，原T087维护至52项。实现出现后暴露测试中6处AssertJ类型编译错误：五处明确Boolean泛型、一处AtomicReference.get().isNull，保留业务断言；Wave13缺新类型的红编译不能证明这些断言已可编译，现纠正记录。真实PathPattern probe证实编码字符和matrix路径匹配专用路由，编码斜杠不匹配；新增7例先46PASS/6FAIL，修后52PASS（t088-path-{red,green}.log）。私有9项实际observer probe覆盖逐字节UTF8、坏编码、重复键/尾随/mixed JSON、同步/异步/永不结束invalidate及原flush边界，9PASS；t088-observer-probe.log。主agent全文审查，预检查无body订阅、上下文无凭据、错误日志固定；范围/配对/依赖与适用task-review PASS。T090实际所有权/T098条件组装仍未完成。
- T137：仅openai.js/responses.js，T13659+既有74共133PASS；主agent独立五文件同样133PASS（f111-desktop-wave14-parent.log）。npm typecheck退出0，仅TS集成不冒充JS完整类型检查。安全body编号优先、普通header优先，tenant提示不覆盖；仅固定不可用和缺提示走同步locale回调，异常/非字符串/HTML不能泄露或变换分类。B交叉读所有新增回调点/测试/helper，实际Node边界probe通过，无新增HIGH/MEDIUM；范围/依赖/配对和命名/i18n/安全/设计PASS，数据库N/A。真实locale消费和GUI验收仍属T117。

主agent最终集中：backend所有test_content_safety*.py **265PASS**（f111-wave14-parent-backend.log）；Gateway准确19类 **409PASS/0SKIP**，逐份新Surefire XML复核（wave14-parent-final.log），包含原路由/转发/许可/旧词扫描相邻用例；之前Dsh*子集385PASS不代替此409结果。Desktop **133PASS**。五项勾选后80/137，进入Wave15。所有结果仅各自执行边界；完整前端基线门禁、真实全链双库/DM8、GUI、跨进程/性能仍保留相应待验收，无提交/推送/部署。


Wave15开始前完整性核对：发现T098元数据只有telemetry/Dispatcher，历史design备注把Spring组装留在T098不成立。补T138/T139在Wave27/28，后续双库Gateway验收依赖T139；总数139，已完成80不变。组装尚未实现，不将纯类/手动构造证明真实接线。接收部署租户范围按现有multi_tenant配置和共享服务身份明确，未新增source白名单/密钥配置。


## 17. Wave 15 接收认证/专用路由前置测试（2026-10-24，进行中）

T031：唯一399行测试，44项预期RED均缺content_safety_runtime，旧共享签名/SSO及T030组合71PASS（f111-t031-red-adjacent.log）。真实SSOSyncConf没有enabled字段，测试使用实际SystemLoginMethod.bisheng_pro=false/省略登录配置对照；相同key与自定义签名头、原始字节、精确方法path、±300秒边界、UTF8/重复JSON/NaN/depth/64KiB、单租户403、多租户历史不查active、真实T030原mapping hash/missing-null冲突均有配对断言。cold import时拦模型/audit/tool runtime，不将已缓存模块避过导入当独立组装证明。主agent全文读取，Ruff/arch-guard及task-review测试subset、完整AC/范围/依赖PASS；缺生产模块的RED不能宣称全部断言已实际到达。

T089：唯一约340行JUnit测试20展开调用，私有javac使用FLOW诊断后仅4处缺DshModelRoutingFilter类型（t089-red-javac.log）；实际相邻T08852+T08630+proxy9共91PASS（t089-neighbor-green.log）。四模式用真实FilteringWebHandler、PathRate和默认Netty过滤器，CountedFilter仅委托计数；真实manager/proxy及两个独立loopback端口验证固定目标/原body/原Authorization/默认trap零请求，另测原错误、双编号、命中续读/取消/pooled refCnt与无demand预算。主agent全文读取，A交叉核对实际类和javap签名，未发现确证fixture错误；范围/前置/命名/完整AC与测试subset PASS。仍缺实现类，不以红编译代替实际路由验收。

两项前置测试满足任务条件，更新82/139；T117仍在同Wave实施与真实语言入口验证，未勾选、尚未进入Wave16。无提交/推送/部署。


T117最终实现：仅client.js/index.js，独立namespace与公共LocaleRuntime/addLanguage、authenticated connection/request→请求ALS→实际注册adapter。首次真实入口为中文却返回英文，entry-red.log；首版probe手动加ja掩正式catalog只有zh/en，移除后no-ja-red.log，再按公共接口缺失时登记ja/fallback en转GREEN，不宣称整个Desktop日文化。Host只接两码三语SSOT固定copy，非法值降级不改分类，不含tenant/Auth、不进入broker/model请求。

B交叉审真实Cordis+独立LocaleRuntime共享CookieJar实际复现同值两renderer：旧fiber卸载误删新窗口cookie，before=true/after=false。修为{owner,messages}随机owner所有权及按copy去重，Host只把messages投影入ALS；主agent独立执行同原probe得到before=true/afterFirstUnload=true、secondStillActive=2/locale=zh，parent-owner-green.log。原探针 /private/tmp/f111-impl-b-locale/renderer-ownership.mjs，未写业务桩。entry扩展覆盖双协议三语两类copy/tenant、6请求并发、无偏好、Host设置落盘延迟、坏cookie/重复/跨authority及重载；final-entry-green.log。主agent独立执行同真实入口probe退出0（parent-entry-green.log）；不是完整Session/Agent执行证据。

GUI：独立Electron43.0.0/Chromium150.0.7871.46，临时bootstrap且独立userData，未跑正式main（其源码会强制使用bisheng-dev/bisheng）。旧electron-leiWN8/zh-blocked图经主agent实际查看为空，仅日志PASS不足；改为预期DOM文本+可见height+双requestAnimationFrame后捕获。最终有效paint-electron-gui.log及electron-zLug2C/六图，C逐六图、主agent抽三图查看确认新增安全正文实际可见；使用已发布LocaleRuntime/client、认证Host/adapter及原TurnErrorItem消费组件。该有限裸组件显示不代表全应用布局/全部旧文案翻译、正式main启动、Session.prompt/Agent队列或打包验收；这些保持后续任务范围。

相邻六文件143PASS（final-regression.log），npm typecheck退出0（TS集成边界）、node --check与diff-check PASS；没有新增依赖或第三方分发包改动。主agent完整diff审查，B实际生命周期交叉审查；任务范围/依赖、命名/注释/现有i18n与安全/设计同步PASS，backend/SQL N/A。T117满足当前接线及有限实际显示验收后勾选，新增T140在Wave17固化入口回归（临时probe不代替长期CI）。

Wave15完成83/140，进入Wave16。全应用Session/真实模型全链、双库及容量等仍未验收；DM8依用户要求保留待验收，无提交/推送/部署。


## 18. Wave 16 接收认证与专用转发实现（2026-10-24，进行中）

T032：仅content_safety_runtime.py及既有common/errcode/dsh.py。配对44项加旧HMAC/SSO/真实ingest初次115PASS（f111-t032-first.log）。扩大旧错误码唯一性回归实际1FAIL/335PASS：运行时遍历包括继承Code，同码403子类违反现有约束（f111-t032-final.log）；删除新子类，不修改唯一性测试，改唯一AuthError的显式tenant_forbidden实例工厂，原类/新默认实例/ClientCode注册仍401，仅范围拒绝实例403。最终相同组合 **336PASS**（f111-t032-final-green.log），含所有内容安全、错误码及三语覆盖、模型错误、原配置与旧SSO。

主agent源码全文/原共享HMAC工具复核：签名先于JSON及SQL，唯一header/原bytes/固定METHOD/path，无独立密钥或modelruntime；严格JSON保留原mapping、时间窗和单租户部署范围；惰性默认Session仅在接收worker作用域触发。C独立12项边界probe PASS（f111-impl-c-t032/final-review.log）：重复签名头两顺序401、可清洗hint浮点/NaN/Infinity仍400、17/1000层安全拒绝、原mapping不注默认、default factory按需及worker tenant202严格visible/bypass恢复；实际DshRoute.error 403与registry401隔离。该default factory探针在首次严格scope contextmanager截断，未连接真实DB，不误称数据库验收。

Ruff format/check、arch-guard/diff-check及任务分层/命名/序列化/配置租户/信息保护/设计同步PASS；API composition不含SQL或FastAPI Request对象。范围/配对T031/依赖T018/T030 PASS，frontend N/A。T032满足条件勾选84/140，T090仍实施与资源边界审查中，尚未进入Wave17。无提交、推送或部署。


T090审查进行中（不勾选）：初版20例19PASS，slow源4而原断言≤3。独立直接MockServerHttpResponse probe证实Spring首帧屏障request(1)，不是可据此放宽的字符串/heap放大。A真实32MiB非流/零需求probe旧版springCachedBytes=33554432、managerRetained=0、writeDone=false（f111-impl-a-t090/budget-red.log）；0字节prelude后cached=0、managerRetained=33554432（budget-green.log、budget-final-prelude.log）。原ordinary-cancel fixture需跳过0字节prelude后再取首真实模型prefix，保留源订阅1/唯一HTTP/refCnt断言；新增prelude-only取消及header writer失败回归即时回收，原slow≤3保持。私有22配对及113相邻通过不能覆盖下一项真实Netty发现。

A真实慢TCP第二层HIGH：ReactorHttpHandlerAdapter+实际Filter/Manager、上游合成单个32MiB合法Chat JSON，rawSocket POST后不读；Netty pendingOutbound=33554626、可读ByteBuf=33507330/refCnt1/writablefalse，但managerRetained=0/checking0/writeDonefalse。证据f111-impl-a-t090/{NettyBudgetProbe.java,netty-budget.log}。这证明0字节prelude仅修Spring前取，实际Netty持有期仍绕过总预算；不能延期到T128才处理或放宽测试。T090扩为两个生产文件接HTTP writer持有租约，T089前置测试单文件补RED→GREEN；尚未完成，保持未勾选。


T090写租约首版继续审查：新增两种完成/取消顺序先RED（原22PASS、新2FAIL，t090-http-lease-red.log），原因writer已读取4096bytes但manager计费0。租约版原慢TCP探针writer未完成期间retained=33554432，断开socket后retained0、writeDonetrue、大PooledUnsafeDirectByteBuf refCnt0（netty-lease-green.log），只对这次普通断开成立。

A进一步复用500ms既有I/O超时，证实guard超时虽然终止reactive write，真实channel仍active/writablefalse/pendingOutbound33554722、32MiB buffer refCnt1，而预算已归零；必须等实际下游连接关闭才能退款（netty-timeout-confirmed-red.log；另早期netty-timeout-green.log虽名字含green实际未通过，不作为GREEN证据）。因此首版租约也不能验收；改用公开Spring/Reactor下游连接生命周期与usingWhen异步error/cancel清理，成功写结束直接结束租约，失败/取消先close实际下游再归还，不关闭独立模型drain。

另实际MEDIUM：已取得ManagedResponse但尚未开始writer时manager.close，旧beginHttpWrite仍接受、等500ms才超时（late-lease-red.log）；开始writer应拒绝clientGone，并处理begin→shutdown→guard间隙，不能拒绝ownerDone（正常完整模型响应可先于HTTP完成）。两问题待最终修复/原探针复验，T090保持未勾选。


T090最终验收：原T089追加真实native timeout、manager.close及late lease先RED，28项25PASS/3FAIL（t090-native-close-red.log）；修后28PASS，私有四类联合119PASS（t090-native-close-{final,union}.log）。主agent常规离线Maven准确20类 **443PASS/0FAIL/0ERROR/0SKIP**，逐份Surefire XML复核，wave16-parent-final.log。未放宽原slow≤3或业务断言；测试维护属于T089原单文件，T090仅Filter+Manager两生产源。

A用相同实际慢TCP与合成上游独立复验：未结束写入retained33554432，timeout/socket-close/manager.close后native active=false、pendingOutbound=-1、32MiB pooled buffer refCnt0、retained0；late lease立即拒绝。f111-impl-a-t090/final-{timeout,socket,shutdown,late}.log。静态尾部UnreleasableByteBuf的refCnt1不当作大缓冲泄漏；真实下游不是完整模型E2E或heap/性能证明。两项HIGH及late lease MEDIUM关闭。

主agent完整读取Filter165行、Manager560行及新增T089实际连接/回收回归；独立A最终只读复核无新增HIGH/MEDIUM。task-review：#1/#3/#4/#5 Python/前端/SQL N/A，#2命名/#6固定错误及凭据保护/#7设计同步PASS；文件范围、已勾配对T089及依赖T088 PASS，diff-check clean。T090勾选后 **85/140**，Wave16完成，进入Wave17。T139真实Bean组装、双库/DM8、T128容量/吞吐等保持未验收，无提交/推送/部署。


## 19. Wave17 HTTP/配置前置与Desktop运行边界（2026-10-24，进行中）

T140：唯一约320行维护测试，真实Cordis renderer fiber/LocaleRuntime/client.apply、公开Connection authenticatedUrl/admission/request waterfall与实际注册adapter。10/10 PASS（f111-t140-first.log）；主agent全文读取及独立首次四文件87PASS。第二次准确七文件包含原需环境protocol-integration，实际六文件143PASS/1SKIP（f111-wave17-desktop-locale-parent-final.log），不将skip称完整协议E2E；后续补准确原enterprise-adapter邻近集。无偏好、Host持久化未完成、三语双协议/tenant、自定义非法及重复/跨authority cookie、六并发ALS隔离、同值双renderer所有权、真实fiber卸载重载及既有ja语言包保留均有行为断言。合成broker/目录存储/webServer注册端口替身不替代Session/Agent或GUI，未运行正式main或真实profile。主agent与C的task-review测试subset命名/英文注释/完整AC/范围/已勾依赖T117 PASS，diff-check clean。T140勾选 **86/140**，其余Wave17仍进行，无提交/推送/部署。


T033：唯一440行前置测试，A实际79PASS/36预期RED，主agent独立三个文件 **74PASS/36预期RED**（f111-wave17-backend-api-parent-red.log）；36setup error逐项为缺配对content_safety_events模块，不把尚未到达断言记GREEN。真实composition+DshRoute/ASGI、原verify+ingest+SQLite事务，时钟/config/Session端口可控；64KiB假长度chunk早停、原bytes单次读取/不改_receive/hashmissing-null、提交等待/回滚后ACK、错误状态与安全输出、query不覆盖签名scope、历史202租户无Token及断连无ACK均覆盖。主agent完整读取全部440行，A的Ruff/format/F821/arch-guard clean；task-review测试subset命名/完整AC/范围/依赖T016/T032 PASS。T033勾选 **87/141**，T034仍未开始。


T091：唯一242行先行测试，真实YAML Binder/placeholder→RouteDefinitionRouteLocator(Path/Method/CacheRequestBody工厂)→CachingRouteLocator/RoutePredicateHandlerMapping→FilteringWebHandler。私有编译成功；当前24项4PASS/20预期FAIL，16专用路由实际选中bisheng-http、4未显式默认关闭；相邻原路由3PASS。主agent完整读取文件、普通Maven独立同样 **7PASS/20预期FAIL/0ERROR/0SKIP**，逐两份XML确认（wave17-parent-config-red.log），不把在首个route断言前尚未执行的真实Netty/Profile/Proxy场景记通过。actual默认Path factory matchTrailingSlash=true，与T088 parser默认不接受尾slash不同，T092须显式false保持两入口一致。task-review测试subset命名/完整AC/唯一定义范围/已勾T016/T090依赖PASS；无生产或YAML改动。

T141：唯一既有enterprise-adapter.test.ts，仅公共on disposer夹具和两处函数export提取终点，新增AC/边界英文注释，原业务断言完整保持。先 **5FAIL/147PASS**（f111-wave17-desktop-locale-adjacent-final.log），修后准确七文件 **152PASS/0SKIP**（f111-wave17-desktop-locale-adjacent-fixed.log）。主agent读全旧测试及实际diff，A只读交叉审T140+T141并对照真实Connection/LocaleRuntime/Host无新增HIGH/MEDIUM；A未重复执行，不冒领独立运行。task-review命名/完整AC/测试范围/依赖T117/T137 PASS，diff-check clean。T091/T141勾选 **89/141**，T118仍在本Wave最终验收。


T118：唯一197行真实公开AgentRegistry/AgentLoop/ToolRuntime测试，五安全终态0次body/preexecute/result，两个正常协议1次；真实assistant-stream完整args帧放行transport后段，随后文字到达再安全错误，tool block-end0/assistant attempt/turn-end安全error与request1无fallback均断言。7定向PASS；主agent8文件 **159PASS/0SKIP**（f111-wave17-desktop-parent-final.log），C九文件169PASS及typecheck0（f111-wave17-desktop-combined.log、f111-wave17-typecheck-final.log）。首次类型检查合成capabilities缺reasoning_content，测试fixture补false后通过，无生产或断言修改。

主agent全文读取，A独立全文及实际AgentLoop错误finish先于message/executeToolCalls消费点复核，无新增HIGH/MEDIUM。内存SessionStore+mkdtemp cwd是隔离边界，未安装Loader/持久化插件，不称完整Host Profile/正式应用或Gateway E2E。task-review命名/英文注释/TS严格/完整AC/文件范围及依赖T117/T090 PASS，diffcheck clean。T118勾选 **90/141**，Wave17完成进入Wave18。

附加线索：C实际公开AgentLoop排队probe发现首轮zh-display ALS运行中收到ja-display followup，第二transport仍继承首轮scope（f111-queued-context-probe.log）。该探针未启用生产cookie桥/真实Sessioncontroller，证明runtime继承事实，尚未证明日常生产语言显示缺陷；不凭推断修改业务或否定已通过工具屏障，继续独立核查真实入口。


Wave18扩大相邻检查发现维护夹具失配：Desktop6文件实际24FAIL/12PASS/1SKIP（f111-wave18-desktop-plugin-adjacent.log），3为旧Host on夹具缺新公共connection/request/错误只认session/event，21为旧UI locale缺getSnapshot等公共接口。跳过的real-backend审计测试没有执行，不声称其通过。按原两文件上限补T142/T143，仅修夹具、保持原断言；T141增加第二审计测试目标并暂退勾。Gateway两YAML合法URI placeholder后，旧配置测试手工Binder缺resolver，1PASS/2FAIL（t092-neighbor-green.log名字含green实际RED）；T091扩第二旧测试目标后暂退勾，原断言不放宽。尚未重新勾选这些任务，不把不完整test stub当生产API需optional兼容的理由。


T034：唯一43行endpoint与28行composition，原T03336PASS；A完整内容安全+旧HMAC/错误唯一性/identity/编号 **359PASS/0SKIP**（f111-t034-adjacent.log），主agent实际HTTP/verify/ingest/identity/编号组合 **115PASS**（f111-wave18-backend-parent-final.log）。主完整读两源，原raw只读且无SQL/SSO回放/modelruntime，query前拒/64KiB/断连无ACK/安全错误映射合design。Ruff/format/F821/archguard/diff clean；task-review #1分层/#2命名/#3既定directReceipt及DshRoute/#6信息保护/#7设计同步PASS，SQL/frontend N/A；范围/已勾T033/T032依赖PASS。

T092：仅两YAML各新增29行，旧codec/应用WS路径/凭据原bytes不改，专用Path显式false/POST/-10/同backend placeholder与默认关闭；source-id注释去除不存在的registered含义。原T09124全部GREEN含真实默认Netty四模式透传bytes/status/编号、manager0，实际Profile/Chat/Responses同loopbackbackend。T091旧第二fixture只补Spring placeholder resolver，原3断言GREEN，RED2原日志保留。主读两YAML差异/旧test全部改动，集中Maven **21类467PASS/0FAIL/0ERROR/0SKIP**，逐21份XML核对（wave18-parent-final.log）。task-review配置subset架构/SQL N/A、信息泄漏/设计同步PASS；两生产源范围、已勾配对T091及T090依赖PASS，diffcheck clean。原测试第二目标兼容复验通过，恢复T091。

T141第二audit-integration夹具：真实未到业务的三项RED已保留，新公共connection/request由夹具提供无事件disposer，其余事件仍委托原services.on并保留原name/global/title断言。主读完整275行及实际差异，原两文件 **12PASS**（f111-wave18-desktop-audit-fixture-fixed.log），无生产改动/业务断言修改。命名/英文注释/完整AC/两文件范围及依赖PASS，恢复勾选。T034/T092/T091/T141验收后 **92/143**，T142/T143仍在收尾，不冒称全Desktop/端到端/双库或DM8通过，无提交/推送/部署。


T142/T143最终：两账户UI测试文件/一市场UI文件只将不完整locale桩替换为同JSDOM realm发布包真实LocaleRuntime+Cordis Context，Context/disposers/DOM均清理，原产品断言逐字不变。原5FAIL/16FAIL分别保留f111-t142-before.log、f111-t143-before.log；修后5PASS/16PASS，对应after日志。C所选13文件193PASS、typecheck0（f111-t142-t143-{combined,typecheck}.log），主agent准确另13文件 **191PASS/0SKIP**（f111-wave18-desktop-parent-final.log），文件组合不同不混报。主全文读取三目标和全部diff，真实UI渲染继续原断言，不用生产optional chaining掩测试stub；无新库/生产改动。JS syntax及diffcheck PASS，task-review测试subset命名/完整AC/2+1文件范围/依赖T117 PASS，真实locale注册/卸载与cookie入口由T140独立验证。

两项勾选 **94/143**，Wave18全部完成，进入Wave19。无提交/推送/部署。queued语言生产组合探针当前停在正式SessionController所需typert.lookups配置，未执行排队，不据此声称生产缺陷或修复；后续特性验收仍记录未证实线索。


全量扫描直接client.js消费者后仅剩旧enterprise-market-client夹具缺公共locale接口；实际定向RED见f111-market-client-locale-fixture-red.log。T143扩第二文件维护（仍两文件）并暂退勾；不把之前13文件通过宣称全仓通过。

排队语言线索升级为实际MEDIUM复现：C补真实TypertRegistry后，真实renderer LocaleRuntime/client cookie第二请求已ja，真实认证Connection/生产startEnterpriseLlm ALS/实际SessionController.prompt(mode:queue)/AttachmentStore/FileUploads/AgentLoop/实际注册adapter，第二安全错误仍zh。f111-production-queued-locale-typert.log。入口carrier为fixture，未挂generated Remote RPC或整Desktop，但生产回调与实际队列错误scope已达到，不能再仅标猜测。分类/编号/工具0保持；需要宿主公开扩展点的窄修，不改第三方包/模型鉴权或传locale到上游。原T117接线能力已验证不撤销其他行为，修复与回归另立明确任务，正在评估最小端口。


T143第二目标复验：主读enterprise-market-client完整文件及diff，仅旧夹具换实际JSDOM/LocaleRuntime/Context/React，原4业务断言全部保持，await Context清理后只关本DOM。C与市场UI20PASS（f111-t143-second-after.log），主准确两市场+真实locale三文件 **30PASS/0SKIP**（f111-t143-second-parent-final.log）；原4FAIL保留。两测试文件范围、命名/完整AC/依赖与L1测试subset PASS，恢复T143。

T035：唯一254行真实CustomMiddleware(实际类名，不存在HTTPLoggingMiddleware)+原T034/verify/ingest测试，21项 **10预期RED/11既有GREEN**，A另45相邻GREEN；主实际组合 **10预期RED/51PASS**（f111-wave19-backend-parent-red.log）。新入口缺精确tuple导致旧Cookie/Bearer 19103提前拒或残留6scope未清，原无Cookie实际commit及8邻近/非POST保留浏览器准入均GREEN；外部JWTdecode/DAO读端口可控，实际tokenversion判定不stub，Redis禁止实际调用。成功/401/SQL失败/断连后原scope恢复、真实严格租户落库均有断言。主全文读取，Ruff/format/F821/archguard/diff clean，L1测试subset命名/完整AC/唯一定义范围及T016/T034依赖PASS，勾选。当前 **95/143**，T093主回归正在执行，尚未写T036/T094。


T093：唯一232行先行JUnit，私有编译成功，主普通Maven独立 **14PASS/8预期FAIL/0ERROR/0SKIP**（wave19-parent-red.log），A/B相邻4类107PASS（t093-neighbor-green.log）。8普通DSH(2协议×流/非流×开关)与6真实旧应用input/JSON/SSE命中+BlockRecord均现有GREEN；8RED为真实T088设置可信MANAGED后内部request decorator改旧path的显式防御契约，不宣称当前部署真实泄漏。真实filterNormal/ACPlus未stub，仅词库/持久端口/身份策略外部I/O mock，client Header无法设置server attr；并发logger capture恢复level/additive且仅清本case UUID缓存。主全文读目标，完整AC/命名/唯一文件范围/T016/T092依赖及L1测试subset PASS，diff-check clean。T093勾选 **96/143**，Wave19完成进入Wave20。


## 20. Wave20最小入口实现与排队文案前置（2026-10-24，进行中）

T036：仅http_middleware.py精确POST tuple **1行**，原exempt/6scope/浏览器Token/其他DSH行为字节不改。T03521GREEN；A内容安全+原DSH/SSO/错误/identity/编号 **384PASS**，另tenant/admin/tokenversion **58PASS**（f111-t036-{content,context}-adjacent.log）。主实际HTTP/middleware/tenant/admin/tokenversion组合 **106PASS/0SKIP**（f111-wave20-backend-parent-final.log），主补读并完整覆盖目标534行、实际diff唯一tuple。Ruff format/check/F821/archguard/diff clean；L1分层/命名/原序列化/严格tenant机制/安全/设计一致PASS，frontend N/A；范围/已勾T035/T034依赖PASS。

T094：仅两旧filter各新增 **3行** Boolean.TRUE MANAGED guard，主全文读189+343行和diff。原T09322PASS、相邻107PASS（t094-{green,neighbor-green}.log）；主常规Maven准确 **22类489PASS/0FAIL/0ERROR/0SKIP**（wave20-parent-final.log）。旧filterNormal/ACPlus/URL/资源分类/BlockRecord/日志字节不改，正常DSH天然避开旧分类与模拟内部改写防御分别记录，不混称线上泄漏。用户header不生成server标记。L1职责/命名/信息保护/设计同步PASS，序列化/SQL/frontend N/A；恰两源范围、已勾T093/T092依赖及diffcheck PASS。

两项勾选 **98/147**；新增T144正在当前Wave测试，后续T145/T146/T147分开配对完整门禁，暂不宣称排队语言已修。无提交/推送/部署。


T144：仅原Chat/Responses两维护测试，新增27cases，合 **19预期FAIL/67PASS**（f111-t144-final-red.log），原59断言全保留；新增8个非法factory兼容边界当前自然PASS，不造RED。factory在实际stream开始一次捕获session/purpose、并发相反完成/在途不随未来scope变、原callbackfallback/非法factory不影响普通模型/不改tenant/不进modelbody；Chat content_filter/error及Responses flat/nested streaming终态均覆盖。主读全新增两节及fixture端口，独立六文件 **19预期FAIL/148PASS**（f111-wave20-desktop-factory-parent-red.log），相邻C七文件110PASS（f111-t144-adjacent.log）。19RED确为未接factory行为，不是缺模块/fixture。JS syntax/diffcheck clean，task-review命名/完整AC/两目标范围/T137/T117依赖PASS。勾选 **99/147**，Wave20全部完成，进入Wave21。无提交/推送/部署。


Wave21 T145审查中（未勾选）：首版两adapter配对86PASS、C14文件224PASS/typecheck0（f111-t145-{first,combined,typecheck}.log），但主实际独立Node调用新共享resolver，factory返回Promise.reject时fallback已返回、unhandledRejections=1（f111-t145-rejected-factory-probe.log），可能干扰普通模型进程。初轮GREEN不足以覆盖非法异步factory拒绝，需要原T144测试范围补RED→GREEN，并对非法异步显示返回仅观察拒绝不await/执行；生产仍仅T145两源，不新增异常业务fallback。T145保持未完成，不把即将执行的T146 helper/queue测试误称语言修复已生效。


## 21. Wave21查询/回传/限流前置及Desktop按流文案（2026-10-24，进行中）

T039：唯一468行HTTP查询测试，37cases **32预期RED/5既有GREEN**，A加旧仓储/admin组装/审计流48PASS，组合53PASS/32RED（f111-t039-red-adjacent.log）。主全文读取并独立实际 **32预期FAIL/35PASS**（f111-wave21-backend-query-parent-red.log），失败具体为filters被忽略/7至31天窗口未限/detail仍PENDING/事件route404/readiness缺字段，无fixture异常。真实authorize_admin/is_tenant_admin/Service/SQL Repository，登录actor交付与外部身份/关系读取为端口替身，不冒称浏览器JWT或真实双库；普通/越tenant/superactive scope、历史actor退出、keyset绑定、白名单无tenant/hash、外部NULL和N_A、已发布0水位/pendingfalse及真实published_at等有断言。测试不绑定新service方法、不强改repo；readiness可经已有tree_state端口组合。Ruff/F821/format/archguard/diff及L1命名/完整AC/单文件范围/T016/T038/T036依赖PASS，勾选。

T079：唯一203行JUnit，52参数化/普通测试定义，B普通私有javac仅5处缺待实现Client/nested type；主独立FLOW诊断 **17错误全为同缺失Client/Disposition**（f111-root-t079-red/compile.log），未补生产桩，尚未到真实HTTP/receipt断言，不能称这些通过。既有共享SSO primitive对backend4固定向量×methodcase **12PASS**（t079-existing-primitive-green.log）。主全文读source，固定目标/原字节包装/Clock重签event不改/不直接ACK row、200 COMMITTED同ID才ACK、permanent6码隔离/其余状态retry、假receipt/重定向/自动retry/总deadline及日志保护配对完整；实际执行及隐藏类型检查待T080补类后再次验证。L1测试subset命名/完整AC/单文件范围/T016/T018/T036/T078依赖PASS，勾选。当前 **101/147**，其他Wave21任务继续，无提交/推送/部署。


T145最终：两source实际协议stream开始一次捕获formatter，Chat在Responses委托后才捕获，Responses内部一次；公开scope固定sessionId/purpose，非函数/同步异常沿旧callback，tenant/分类/编号/工具结束逻辑不变。主额外两处实际Node RED分别factory非法Promise、被调用formatter非法Promise（CONTENT_FILTERED仍未处理1拒绝）；原T144维护新增隔离Node子进程回归同时覆盖本机/cross-realm Promise、rejecting thenable、throwing then getter及真正四参requestFailure消费，不污染Vitest全局。仅对非法异步显示结果observe reject，不await/执行/采用。修后主原两probe均 **unhandledRejections=0**（f111-t145-rejected-{factory,formatter}-parent-green.log），对应RED均保留；C child RED4→GREEN及两源87配对PASS。

主读新共享resolver、全部HTTP/SSE/content_filter接入与新增child回归，六文件 **159PASS/0SKIP**（f111-wave21-desktop-factory-parent-fixed.log），此前包含原locale10的七文件169PASS；C十四文件 **225PASS/显式SKIP4**（仅新T146 queue预期RED，旧locale10均执行），f111-t145-rejected-callback-combined.log。不是把17个新helper/queue RED算通过，整队列仍待T147。最终typecheck0（仅TS集成）、两JSsyntax及diffcheckPASS。L1完整适用子集命名/既有包与i18n/信息保护/设计同步PASS，架构/SQL/序列化N/A；两生产文件范围/已勾T144依赖PASS，勾选 **102/147**。


T095：唯一202行先行测试，45项 **13PASS/32预期FAIL**；主agent独立私有javac与实际执行同数（f111-root-t095-red/compile.log、tests.log），B同JVM邻近129项全部PASS，联合174项142PASS/32RED（t095-canonical-red-neighbor-union.log）。真实PathRate与真实LimitRuleLoader/Guava permit，未配置DSH不强增限流、旧应用资源规则与HTTP200/body429合同、邻近方法/尾slash仍保留旧分支均GREEN；RED为无缓存NPE、正文/Query日志、编码与matrix别名未规范化。LimitRuleLoader自身记录flowID，因此T096须在精确DSH入口统一为completions/responses后继续既有configured tryAcquire，不将敏感matrix传入日志。私有规则只逐key恢复，两个logger恢复level/additive，不clear全局map。主全文读取，L1测试subset命名/完整AC/单文件范围及已勾T016/T094依赖PASS，勾选 **103/147**。T146缺少合法语言提示的排队边界仍补测，不越过Wave21门禁。


T146：仅两个测试文件，新增missing/invalid hint边界5例后 **22预期FAIL/原10PASS**；C f111-t146-missing-hint-red.log，主独立相同两文件复验同数（f111-wave21-desktop-scope-parent-final-red.log）。14项缺helper；实际SessionController.queue/Agent/生产cookie桥的双协议后续ja及缺失/非法hint8项均在真实双insert/claim、首轮completed、两模型请求和无copy入模型断言后因旧zh显示FAIL。insert时undefined必须作为已知缺失保存，不能claim时回用旧driver ALS；新factory接入后index不再同时交旧callback，防止undefined沿legacy fallback复活旧语言。主全文读取helper测试及真实queue新增段，L1测试subset命名/完整AC/两文件范围/已勾T145/T118/T140依赖PASS。勾选，Wave21完成 **104/149**；新增T148/T149是实际默认窗口游标问题的窄适配，尚未完成，不声称已修复。进入Wave22，无提交推送部署。


## 22. Wave22回传、查询与排队作用域实现（2026-10-24，进行中）

T147：恰两source helper/index，T146 **32PASS**（f111-t147-first-green.log）。主全文读新91行helper及index新增接线，实际Cordis dispatch/公开agentEvents与SessionController事件类型对照；pending按session+稳定messageID，claim含明确missing，匹配turn/end才清active，agent/session dispose及幂等unload清理，formatter保存冻结白名单copy。index移除旧localize回调，direct/auxiliary仍由factory捕获发起请求ALS，未转模型或消息数据。初次15文件245PASS/2FAIL仅T141旧audit stub把所有新events错送onTitle。主按T141既定第二测试文件改事件端口：只有session/event且global:true送原标题监听，原name/global/title/重试断言不改；其余真实locale生命周期另由T146。原RED f111-t147-combined.log保留。修后C准确15文件 **247PASS/0SKIP**（f111-t147-final.log），主独立五文件 **51PASS/0SKIP**（f111-wave22-desktop-parent-first.log），含原审计两文件、完整locale32及真实Agent工具7。typecheck0（仅TS集成）、JSsyntax/diffcheckPASS。L1命名/固定SSOT i18n/安全/设计一致PASS，DB/API N/A；两生产源、已勾T146/T145/T117依赖PASS。T141恢复，T147勾选 **105/149**，实际公开queue入口与工具屏障已验证，不冒称完整Remote RPC、正式Desktop启动或Gateway E2E。


T148：恰两个既有test增量，3Repo窗口能力RED+1实际API移动窗口RED+1旧无now控制GREEN。A组合 **36预期RED/54PASS**（f111-t148-red-adjacent.log），包含原T03932RED；主实际Repo文件 **3预期FAIL/31PASS**（f111-t148-parent-red.log）和单API **1预期FAIL**（f111-t148-api-parent-red.log）。Repo缺now端口将其当ORM列导致AttributeError，API仍包括未来0.5秒记录；新增分页在clock+1s必须纳入新进入记录，不能靠冻结首轮窗口通过。显式start/end、安全筛选及tenant绑定原断言保留并补充，旧无now40天内部查询控制GREEN。主读两新增段及全部修改，Ruff/F821/format/archguard/diff与L1测试subset命名/完整AC/两文件范围/T038/T039依赖PASS，勾选 **106/149**。T149仅仓储文件，T040后接Service时再验API；不将仍RED的API记通过。


T149：仅主请求Repository文件增量增加可选now端口；复用既有naive_utc时间校验/UTC规范化，7天默认及31天上限在仓储内部应用，fingerprint只用户显式filters，未传now旧内部查询不变。主实际T148仓储全部转GREEN及原groups **59PASS**（f111-t149-parent-first-green.log），新API仍等待T040接线不记通过。主完整读取目标所有实际方法与修改段，SQL只在Repo、SELECT严格tenant与原keyset/批量用量及姓名查询保持，无事件列表JOIN或全历史COUNT。Ruff check/format/F821、archguard及diffcheck PASS。L1分层/命名/元数据序列化/双库可移植谓词及tenant/无信息泄漏/设计§4.9同步PASS，frontend N/A；唯一目标及已勾T148/T038依赖PASS，勾选 **107/149**。C独立交叉审查仍进行，若发现确证问题修复并重验；T040可沿已通过配对端口实施。


T149独立交叉补证：C实际仓储34PASS（f111-impl-c-t149-review.log），四个独立行为探针4PASS（f111-impl-c-t149-independent.log）：默认下界推进移出未消费旧行、显式UTC/+08同一时刻续页、只显式start时隐式end继续推进、visible含101/202仍严格返回101。无确证HIGH/MEDIUM；SQLite仅证明Repository行为，实际双库计划仍待验收。


T080：唯一180行新Client，原T07952项补类后完整编译并 **52PASS**（t080-absolute-deadline.log），无测试类型补丁/断言修改；B五类105PASS及四个真实loopback边界smoke PASS（oversize receipt重试、坏Unicode/oversize event隔离且HTTP0、Clock错HTTP0重试）。原payload字节保持，不修改row/mapper；固定origin/path、共享sign、签名头及每次sent_at、严格UTF8/JSON/depth与<=64KiB完整receipt、全流程绝对deadline/无redirect/retry及取消连接所有权均全文审查。T096唯一120行旧filter增量、T095原单test追加16个完整canonical配置别名case；先61项13PASS/48预期FAIL（t095-full-canonical-red.log）后61GREEN（t096-first.log），原45断言不弱化，实际Guava许可及旧拒绝合同保持。

主常规离线Maven **27类641PASS/0FAIL/0ERROR/0SKIP**，包含两配对、完整已实现DSH和原路由/WebSocket/许可/词库对照（wave22-parent-final.log），逐27份Surefire XML核对总数。B私有七类242PASS，wave22-impl-b-union-green.log。主全文读取两生产源和新增T095段；Ruff/SQL/frontend N/A，L1职责/命名/严格序列化事实与信息保护/设计同步、范围/配对/依赖及diffcheckPASS。两任务勾选 **109/151**。不以loopback代生产回传、真实双库/性能或Spring Bean组装；后者仍T139。

T014窄维护：未关联事件Query类型补tenant_id/user_id/model_id、association_status仅UNASSOCIATED，与实际新端点一致；旧共享主请求/组/树audit_status仍保留NORMAL|ABNORMAL合法子集，记录DTO的NOT_APPLICABLE既有支持不变。仅原类型文件，ESLint及完整Platform tsc-strict **551文件通过**（f111-t014-query-type-maintenance.log），无新库/HTTP或状态改变；不是全前端门禁结论。


T040两source配对T039/T148 **72PASS**（f111-t040-paired.log），A扩大回归 **617PASS/3SKIP/13FAIL**（f111-t040-adjacent.log）。主实际读Service251/Endpoint330行，失败11为旧audit_database未建事件表、2为手工NOW=10/14数据在wallclock10/24的默认窗口外；不修改生产来绕缺表，也不全局改Harness clock（其模型调用仍用实时，单改query会反向排除新模型数据）。补T150唯一fixtures模型tuple登记事件，T151仅两手工固定数据测试注入query.now=NOW+1秒；原所有assert/SQL/tenant/游标检查保留，原Harness/NOW未改。

主独立全匹配test_content_safety*.py+test_model_audit*.py **611PASS/3SKIP/0FAIL**（f111-wave22-backend-parent-final.log），覆盖所有13个原RED。与A先前组合文件范围不同不混算；3SKIP为旧显式隔离HTTP、owned-store及本地MySQL opt-in未开启，不宣称全链或双库通过。Ruff/format/F821、guard/diffcheckPASS；主逐完整fixture、两旧测试和diff审查，T150/T151测试subset命名/全AC/各1和2文件范围/已勾依赖PASS。T040 L1分层/命名/原平台响应/SELECT严格租户且Service无SQL/信息保护/设计同步PASS，frontend N/A；两生产源及已勾配对T039/T038/T036/T149 PASS。T150/T151/T040勾选 **112/151**，Wave22全部完成，进入Wave23；全程无提交、推送或部署。


## 23. Wave23目录过滤/投递前置与Platform API（2026-10-24，进行中）

T045：唯一506行前置测试，18新case **15预期FAIL/3既有PASS**；A另36相邻GREEN（f111-t045-red-adjacent-corrected.log），主全文读取并独立原组合 **15FAIL/33PASS**，纠正六态夹具后准确新18项 **15FAIL/3PASS**（f111-wave23-backend-parent-corrected-red.log）。原初版误把CHECKING列为六态，主审发现后仅改为已确认DISABLED，未让实现接受新非法状态。真实请求投影/fold/tree_step先建代，同请求time/model/user/direction/state交集、BOTH、分层own/branch计数、默认7/max31、显式fingerprint/tenant及scan_budget续页覆盖；预算断言不强迫合法前置优化产生空页，只对确有未耗尽cursor的不足结果要求scan_limited。SQL EXISTS不被误判成必须内层LIMIT，外层候选和tenant约束有断言。没有fixture收集错，RED对应未实现direction/tree filters/now端口/安全summary。Ruff/format/guard/diff与L1测试subset命名/完整AC/单文件范围/已勾T016/T044/T040依赖PASS，勾选 **113/151**；未开始T046。


T102：恰两API源308/514行，主全文读全部source与临时actual wrapped request+Axios synthetic adapter探针；独立 **25PASS**（f111-t102-parent-contracts.log），四原API/request文件 **25PASS**（f111-t102-parent-regressions.log）。C六文件40PASS、最终契约25PASS，目标ESLint0及完整Platform tsc-strict **552严格文件PASS**（f111-t102-{api-regressions,final-contracts,final-lint,final-typecheck}.log）。原拦截器真实解包及200业务拒绝/409证据保留/取消/无retry、404/503/network不假disabled、nullable/int64、200emoji合法码点与协议数组拒绝、legacyunknown及外部N_A/null、false过滤传递均有行为证据。临时探针不代长期T110组件回归、全frontend门禁或E2E。主L1 API边界/C7、命名/TS与旧optional兼容、无敏感日志/新403/新库、设计同步及两源范围/已勾依赖PASS，diffcheck clean。勾选 **114/151**；T081仍同Wave前置复核中。


T081：唯一488行先行JUnit，28方法计划35调用，B私有javac仅4处缺待实现Dispatcher，主独立FLOW诊断 **6错误全为缺同一Dispatcher类型**（f111-root-t081-red/compile.log）；不能把尚未执行的新35项记通过。既有OutboxService9+真实EventClient52 **61PASS**（t081-neighbor-green.log），原test辅助CAS/ManualScheduler独立编译及端口smoke通过，无生产Dispatcher桩。主全文读原source与修改后owner结束观察；原要求SQL outcome计数作为结束证据会强迫合法实现一定发过期CAS，改以真实dispatchOnce终止观测后再断言旧owner不改新owner/不假ACK。实际shared Service+行级Mapper CAS双实例、同实例ABA/超时/满批lease、可恢复丢ACK/真正断socket、jitter、close/阻塞claim、ACKED-only有界无COUNT清理均配对；真实双库和进程重启保留后续。L1测试subset命名/完整AC/单源范围/已勾T016/T080依赖及diffcheckPASS，勾选 **115/153**，Wave23完成进入Wave24；T152/T153仅分离组树真实Service时钟接线测试与实现，不偷占T046第三源。


## 24. Wave24目录查询、持久调度与Platform配置（2026-10-24，进行中）

T046：恰两Repo源407/275行，主全文读取及新增租户回归。T045当前19配对GREEN；主独立内容安全/全部旧model_audit及admin/middleware组合 **640PASS/3环境SKIP**（f111-wave24-backend-parent.log），与A完整组合一致。旧稀疏目录SQL预算断言保持原<35，通过合并就绪查询实际33条；T045单源维护新增C3案例：202待hierarchy不能让101已发布安全汇总unready，已记录实际RED→GREEN。所有筛选落同一Request，不用不同请求分别证time/model/hit；有界元数据查询，不读事件正文/模型body。Ruff及archguard/diffcheckPASS；L1分层/命名/原DTO/严格SELECT和显式写租户守卫/信息保护/设计同步PASS，frontend N/A；恰两源、已勾T045/T044/T040依赖PASS。MySQL CASE/EXISTS编译证据不代真实双库；DM8缺dmPython未编译。勾选T046。

T082：唯一213行Dispatcher，主完整读取；原T081 **35/35GREEN**，主常规离线Maven准确 **28类676PASS/0FAIL/0ERROR/0SKIP**（f111-gateway-tools/wave24-parent.log），无改动测试断言。16并发/批次100/3秒单回调预算、UUID owner及原lease、只COMMITTED ACK、SQL失败可恢复、关闭/时钟/抖动/ACKED有界清理均覆盖。B另真实阻塞Mapper探针关闭前后各100轮仅1个claim、HTTP0（t082-blocking-sql-bounded.log）；不强加外层超时后释放gate使不可中断SQL堆积。实际数据库statement timeout仍T120待验收。L1职责/命名/既有数据契约/数据库方言与CAS边界/安全日志/设计同步及单源范围、已勾T081/T080依赖PASS；无@Component自启动接线混入。勾选后 **117/155**，其余Wave24仍实施中；无提交、推送或部署。


T152：唯一257行真实HTTP/Service/Repo先行测试，主全文读取并独立 **9预期FAIL/16PASS**（f111-t152-parent-red.log）；A与T04519+T03938相邻组合 **9预期FAIL/73PASS**（f111-t152-red-adjacent.log）。三个公开组/树/组内请求入口分别复现默认7天未生效、超31天未拒、未来0.5秒观察提前入选，精准对应Service缺now。显式31天/显式时间与安全条件及tenant游标绑定/默认移动不固化/实际同请求核验/原管理员权限/元数据不预取/历史location独立语义均有对照；不以Repo直调代API接线。Ruff/format/F821/archguard/diff和L1测试subset命名/完整AC/单文件范围/已勾T039/T046依赖PASS，勾选 **118/155**，允许配对T153。


T153/T156：T153恰原Service三处增now=self.now()，主已全文读251行及实际三处差异；无Service SQL/隐式bounds/游标实现混入，location/parent保持独立历史定位。A配对82GREEN后原两手工历史记录HTTP断言RED，主独立 **2FAIL**（f111-t156-parent-before.log），不是生产算法问题。T156各唯一旧case加NOW+1秒查询时钟（tree文件只另补必要import），原断言保持，未改全局Harness或模型记录。主新API25+原组/树 **52PASS**（f111-t153-t156-parent-green.log），最终全内容安全/全部model_audit及admin/middleware **665PASS/3环境SKIP**（f111-wave24-backend-final-parent.log）；全部原窗口9RED与旧2RED已闭合。Ruff/format/archguard/diffcheckPASS。T153 L1分层/命名/既有响应/严格tenant边界/安全/设计同步及单源范围、T152/T046配对依赖PASS；T156测试subset命名/完整AC/仅两文件与已勾T152依赖PASS。勾选两项 **120/156**，真实DM8和全链E2E仍待验收。


T154/T155：Platform正式@bisheng/ui workspace:^本地链接；pnpm生成曾带无关peer图重解析，已拒绝该变更，仅保留生成的本地link，程序比对旧lock全部importers/packages/snapshots/元数据逐项不变。离线frozen-lockfile install成功（f111-t154-frozen.log），无其他manifest或嵌套lock残留。T155唯一Vite配置+physical CSS入口，从公开token/preset真实编译90,843bytes；主执行实际production plugin **613普通selector全部有scope**、dark/green顺序、touch及keyframe隔离PASS（f111-t155-probe-final.log）。新配置类型问题已修，主TS compiler API原HEAD与现源码对比均仅既有http-proxy类型缺失，无新增诊断（f111-t155-ts-compare.log）；不声称整个Vite config历史全绿。主全文读取两源/实际包与lock差异、零新依赖闭包、L1基础设施边界/无设计值复制/信息保护/设计同步/两任务各≤2文件及依赖PASS。

T103/T105/T106：主完整读取五源（设置+hook、Filters、Card+Details），使用landed共享组件、局部v4 Provider、原wrapped request，无store HTTP/403分支/新库/HTML渲染。主独立正式包组件 **17PASS**、筛选 **6PASS**、详情最终 **10PASS**（f111-{t103-parent-official,t105-parent-private,t106-parent-final}.log）；原DSH/API相邻 **24文件204PASS**（f111-wave24-parent-frontend-regressions.log），完整Platform strict **602文件PASS**（f111-wave24-parent-frontend-typecheck.log），五源目标ESLint PASS。C各旧50回归及原18Card/Body断言保留。主审发现刷新失败后retry误用旧分页cursor，新增实际 **1RED/9GREEN→10GREEN** 后用attemptCursor记录确切重试请求；新区域详情按钮使用共享Button，旧Card按钮不变。三locale validation新增checks_required/reply_too_long/range_too_large并修旧默认窗口提示，主递归内容安全key parity PASS，无改generated api_errors。

C隔离Electron43/Chromium150、临时独立profile、真实production样式插件和组件、合成loopbackGateway浏览器验证：保存/101→202切租户/zh-en-ja/390宽scroll379=client379/console错误0，外root radius .58rem与内0.5rem独立；暗色过渡完成后Textarea父背景18/18/18（f111-wave24-gui/result-settled-final.log）。主实际查看en截图，布局与组件可读；最终图run-Hd6zRf/{zh,en,ja,ja-narrow,ja-dark}.png。暗色初始浅色为transition捕获时序，等待350ms复核，不为此改共享样式。临时Vite/Electron均停止。此为真实组件集成预览，**不代T104真实导航入口/真实账号权限/端到端或信创浏览器验收**。L1前端边界/命名/可空语义/i18n/安全/设计同步及各2/1/2文件范围、已勾依赖PASS。五项统一勾选 **125/156**，Wave24完成，按依赖进入Wave25；无提交、推送或部署。


## 25. Wave25注册/遥测前置与实际页面入口（2026-10-24，进行中）

T097：唯一307行前置JUnit，28方法、按固定Counter16/Gauge13预计60调用，尚未执行，不记通过。主已全文读，独立私有javac **114诊断均为缺Telemetry及其Counter/Gauge/Alert/Snapshot类型**（f111-root-t097-red/compile.log：4缺package/110缺symbol），未见其它业务类型/fixture错误。B四相邻类 **157PASS/0SKIP**（t097-neighbor-green.log），helper独立编译/Wrapper端口smoke通过，但不代待实现telemetry。主审删除未传被测对象的无关联mock verifyNoInteractions空证明；真实Dispatcher自己的Mapper交互断言保留。实际持久ACK/RETRY/QUARANTINE、CAS0/SQL失败、后台固定4状态聚合且不读payload、不在模型投递新增statsSQL、unknown样本非健康0及日志无rawThrowable均配对。缓存/profile等枚举观察端口测试**不冒称实际调用已接线**，新增T157–T164四组有限文件配对补齐，T138/T139在其后用同实例。L1测试subset命名/完整AC/单源范围与已勾T016/T082/T096依赖PASS，勾选 **126/165**，允许T098。


T165：主唯一既有导航测试维护，独立原 **1FAIL/1PASS**（f111-t165-parent-before.log）仅固定5tab计数；改为6并追加真实新tab点击→content-safety URL→Settings heading断言，原audit/access/plugins/隐藏operations回退断言保持。实际 **2PASS**（f111-t165-parent-after.log），不mock新设置业务准入或QueryProvider。L1测试subset命名/i18n/单文件及已勾T103依赖PASS，勾选 **127/165**。主同时补齐新增测试任务的59AC表正向追溯，原AC编号与章节未改；T104仍等真实入口补验后验收，未越过后端实时权限链。


T107：恰hook+Panel两源，主完整读取并跟踪所有hook调用点（父useMemo/组state均稳定query引用）。主独立真实Panel/Hook **7PASS**（f111-t107-parent-final.log），与实际DSH入口/旧列表组合 **23文件186PASS**（f111-wave25-parent-frontend-regressions.log），C四旧35PASS及完整Platform602strictPASS。覆盖false/BOTH/六态组合、apply清cursor、refresh沿applied但保留dirty draft、新补命中入Card、租户key重建/旧transport不认abort也不能落迟到数据、旧缺字段unknown、明细按需、不适用null。hook新scope首render也不暴露旧page；原group查询引用/有界API/数据权限链保持。L1前端分层/C7、命名/TS、nullable兼容/i18n、无raw HTML/log/403、设计同步与2源范围、已勾T105/T106依赖PASS，diffcheck clean。勾选 **128/165**；T104仍处理Tabs既定规范的未保存草稿保护，不将入口未收尾提前记完成。


T098：Telemetry125+Dispatcher331两源，主逐段完整读取及最终冻结复核。T097原60GREEN后，主审发现并发ACK较旧now后完成会倒退lastSuccess；原单测试源授权补2例（ACK-A等待SQL、ACK-B/新数据库样本先写）真实 **60PASS/2FAIL→62PASS**（t098-ack-order-{red,green}.log），只历史lastSuccess取max，occupancy正常可下降。B五类 **219PASS**；主集中常规离线Maven **29类738PASS/0FAIL/0ERROR/0SKIP**（wave26-telemetry-parent.log），逐29XML汇总一致，原35Dispatcher和前驱全部保留。实际不可中断SQL及阻塞exporter探针分别queryCalls1/maxSQL1，取消后100+close后100轮无新SQL，原投递继续2轮（t098-sampling-{sql,sink}-green.log）。后台采样/导出独立loop、实际slot finally释放；unknown样本清当前健康值，历史成功保留，不读payload或新加请求I/O。L1职责/命名/固定枚举/安全code+type不带message/stack/设计同步及两生产源、已勾T097/T082/T096依赖PASS，diffcheck clean。SQL聚合4返回行界不冒充扫描成本界、远端卷压力未实测；留T120等如实验收。按已满足依赖先完成T098，勾选 **129/165**；Wave25 T047/T104仍收尾，未假称整Wave26完成。


T047：主全文读取最终516行（原456+真实迟到native回归），独立 **16预期FAIL/1真实signalsPASS**（f111-t047-parent-final-red.log）；A相邻原Worker/tenant共 **16预期FAIL/20PASS**（f111-t047-late-native-red-adjacent.log），失败均为待实现Worker模块不存在。真实Celery eager apply_async/prerun/postrun/异步桥/SQL有界executor和投影Service不stub；父pytest旧mock以独立解释器隔离。publisher仅捕获投递边界再执行原Task；两正常进程退出共享SQLite证明丢内存续页后可扫持久状态，不代真实broker/kill9/双库锁。缺/错/string/bool/zero header、SQL失败恢复、100批/租户续页、disabled/archived、旧owner、幂等及跨租户scope清理均配对。主审增加MODEL先UNREPORTED发布、首FINAL/BLOCKED后到仍groupPending而旧水位不变的实际场景，真实Repo夹具探针确认成立（f111-t047-native-first-fixture-probe.log）。发现现有树扫描仅看hierarchy/state dirty会漏此case，旧pending_tenants却含无关运行模型，因此T166/T167补窄Repo端口，禁止048内藏SQL/第三文件。Ruff/checkformat/F821/guard/diff与L1测试subset命名/fullAC/单文件/已勾T016/T046依赖PASS，勾选 **130/167**。


T104：主全文读取最终159行入口及33行sections，真实backend admin_runtime/UserPayload与GatewayAdminClient授权链复核后修正最初误沿旧审计mode的child只读假设；child只能自身leaf，global才目录选择。主独立最终入口 **13PASS**（f111-t104-parent-verified13.log），包含实际Settings+mutation提交target202、global切租户、未知target不请求、旧身份fallback、普通用户原403、Gateway离线旧tab可用、身份/部署变更卸载。Tabs规范复核发现未保存输入会丢：新临时case **1RED→GREEN**，仅原index保持首次访问后panel hidden、切回草稿/目标不变且不自动保存；首次未进入不挂业务取数。主最终导航/DSH **23文件186PASS**（f111-wave25-parent-frontend-final.log），完整Platform602strictPASS，4目标lint/diffcheckPASS。

C实际入口Electron43/Chromium150+BrowserRouter+真实TenantSelect/Settings/wrapped API（仅合成userContext/loopback transport）验证global101→202、草稿→Access隐藏→切回目标/草稿保留，三语已逐张view有效截图；主实际view最终窄图。新tab溢出真实对照旧5doc402/client379、新6doc496/client379，原index窄滚动修后390doc=client390、内scrollWidth488/client350、scrollLeft138末tab可达，原生Right切换和Tab焦点可见（f111-t104-gui/result-final-focused.log；run-5P8dI3/ja.png,narrow-six.png）。newErrors0；访问既有Access Settings的Input style-jsx non-boolean React warning1单列保留，**不再笼统声称console0**。截图paint竞态不完整图不采用，未为截图改业务。私有服务/窗口均停止，非真实账号/部署E2E。L1前端C7/命名/原路由兼容/权限边界/i18n/安全/设计同步及2源范围、已勾T103依赖PASS，勾选 **131/167**，Wave25完成进入Wave26。原T099/100/101各单locale维护补own_hits/branch_hits两明确安全计数label，三语同步，未动generated文件。


## 26. Wave26安全扫描与诊断实际接线（2026-10-24，进行中）

T166：既有test_content_safety_tree.py单源增4case（总480行），主读完整新增场景及复用夹具，独立最终 **4预期FAIL/15PASS**（f111-t166-parent-final-red.log）；A加旧tree/worker/T045 **4预期FAIL/48PASS**（f111-t166-red-adjacent.log）。缺include_group_pending参数为唯一RED；disabled/archived实际native发布→首FINAL迟到只groupPending、旧default/显式False无改变、新True应发现并处理后清，真实RUNNING无dirty对照、101脏租户100keyset两页及只ID无COUNT/DISTINCT/GROUP BY均有断言。主审移除恰两个EXISTS的实现形状过约束，保留相关查询/有限SQL/语义，不要求合法等价实现固定子查询数量；原业务断言未放宽。Ruff/checkformat/F821/guard/diff与L1测试subset命名/fullAC/单源/已勾T047/T046依赖PASS，勾选 **132/167**，允许T167。


T167：唯一既有Hierarchy仓储，主全文读取159行及实际新增signature+条件；旧默认/显式False谓词保持、True额外OR groupPending，沿原Tenant相关EXISTS/只ID/100keyset，未在Worker/API/Service放SQL。主独立新19+旧tree8/worker6/T04519 **52PASS**（f111-t167-parent-green.log），A同52PASS；Ruff/format/F821/guard/diffcheckPASS。L1分层/命名/编号序列/SQLAlchemy双库可移植与明确只ID跨租户枚举/无敏感数据/设计同步及单源、已勾T166/T046依赖PASS，勾选 **133/167**，允许T048调用新端口。


T157：唯一293行先行测试，主已全文读取并在独立私有javac目录编译、实际执行 **24预期FAIL/1既有PASS/0SKIP**（f111-root-t157/{compile,red}.log）。2项缺实际可注入构造器、22项真实Cache/Verifier行为无observer；不是生成stub或手工increment冒称接线。B相邻Cache38/Verifier18/Client24/Telemetry62合计 **142PASS**（t157-neighbor-green.log）。口径限定HIT为真实成功缓存返回、MISS及latency为一次物理profile订阅、MERGED为额外准入等待者；negative命中不充成功HIT、不重复计物理错误，取消不滑动TTL/伪释放在途槽，latency不含Redis发布。主L1测试subset命名/完整AC/单源范围/已勾T098依赖及信息保护PASS，勾选 **134/167**，允许T158两源实现；未进入下一测试配对。

T130只读预检（尚未验收）：实际workspace check-i18n PASS，Platform602 strict及共享UI lint、file-viewers lint/typecheck PASS。完整lint为Platform93项、Client21项加既有unused suppressions；Client1354 strict文件中1项useAiChat.test.ts:294缺parentMessageId/sender。C将完整HEAD源码/config/baseline放私有临时快照后运行相同命令，93/21的file/line/column/rule/message和该TS2345逐项一致；配置、相关源码及3份baseline哈希未改（f111-t130-preflight/head-comparison-summary.json及README.md）。早期stdin-only 137/23不是完整抑制计数，已由实际HEAD全量结果取代。无修无关源/基线/抑制文件，T130保留未完成，不将本次预检视为全前端门禁通过。


T048：主完整读取79行Worker、114行Registry和T047维护区域，注册仅import+call两行。主独立真实Celery/子进程配对 **17PASS**（f111-t048-parent-green.log），A其他内容安全 **456PASS**、旧Worker/context **39PASS/3Redis环境SKIP/2external未执行**。原fixture误以get_current_tenant_id有效admin202代表raw leaf；授权记录raw101并保留有效scope原值、SQL线程(101,None,{101},False)及全部恢复断言。ready/counts观测也改用真实profile_scope，前后scope恢复新增断言，未改通用fixture或生产signals。宽旧tenant15FAIL/10settingsERROR在原main同synthetic配置实际重现，nodeid一致（f111-t048-main-tenant-baseline.log）；另2外部DB缺连接未执行。Worker只调Domain/有界executor、无SQL、dirty-ID扫描包含停用/归档且不选无dirty运行模型，任务tenant参数/header严格正int64一致、异步桥前捕获header。L1架构/数据库线程租户/安全日志/设计§4.9及两源范围/已勾依赖PASS，Ruff/format/F821/guard/diffcheckPASS。勾选 **135/167**，允许T049先行测试；不冒充真实broker、强杀或双库锁验证。


T158：主完整读取Cache450行/Verifier222行，保留旧构造并新增尾部Telemetry；Cache唯一计物理profile MISS/ERROR/latency，真实成功L1/Redis计HIT，Verifier仅MERGED/有限队列拒绝与锁内实际active/queue。物理profile结果前置观察于Redis发布，错误/取消原子一次，TTL/lease/到期预算及所有真实IO顺序保持。主私有javac及独立真实loopback联合 **167PASS/0SKIP**（f111-root-t158/{compile,green}.log），B同167PASS；最初沙箱内loopback bind失败已用授权随机本机端口重跑，不当业务回归。L1命名/固定标量/安全类型无raw正文/设计§7.3及恰两源、已勾T157/T098依赖PASS；无新增profile/Redis/SQL。勾选 **136/167**；组件装配统一实例仍T139，不提前声称生产已启动。


T161：主单源先行JUnit234行，真实Manager/协议adapter/Outbox recorder，只替换transport/SQL。私有javac成功，最终 **24预期FAIL/0SKIP**（f111-root-t161/{compile,red}.log），2缺构造、22为真实counter0/gauge未知；主修正合成Responses数组/annotations及Chat必填metadata后复跑，不把样例错误算预期RED。相邻实际loopbackManager30+Outbox9 **39PASS**（同目录neighbors.log）。真实输入/双协议非流式输出/流式DECISION→DRAIN一次命中、有限check/全局bytes、普通取消/关闭释放、HTTP写未完成仍计费、缓存record结果重订阅一次、SQL throw/0/非法事件gap与safe log均覆盖。B独立只读fresh-eyes建议已采纳：普通取消/关闭CHECK_ERROR0，backend原401/200纯error及流式error不充检查故障；现有模型状态不改。L1测试subset命名/完整AC/单源范围/已勾T098依赖及信息保护PASS，勾选 **137/167**，允许T162两生产源。


T159：唯一367行测试，主全文读取、私有独立javac及实际 **15预期FAIL/0SKIP**（f111-root-t159/{compile,red}.log），构造/age/active缺失与真实mismatch/rejection为0；原四类 **124PASS**（t159-adjacent.log）。真实Policy/Matcher、只有SQL/Redis和调度Executor端口替身，普通hit不续age/5秒expiry、共享PTTL扣roundtrip、真实permit取消仍占用、executor/node/weight拒绝固定分类一次、输入413不混拒绝、CAS409不发布草稿/单CAS/权重eviction持有旧matcher/AC suffix语义均配对。无手工increment/新依赖；L1测试subset命名/完整AC/单源/已勾T098依赖PASS，勾选 **138/167**。为并行推进，T160两个生产源明确移交C，B只负责T162/后续T164，不交叉写同文件；前端T108仍等T050。


T049：唯一272行先行测试，主全文读取并独立实际 **3预期FAIL/4PASS**（f111-t049-parent-red.log）；三个均为真实Beat缺唯一扫描task，无收集或fixture错误。A新旧组合 **3RED/70PASS**（f111-t049-final-red-adjacent.log）。实际Celery Scheduler→scanner→headers/signals→严格SQL覆盖101及disabled202；API assembly在独立进程读取持久pending/已发布/追加dirty保留旧水位/再发布/重复不增代。原Service已有readiness接线如实GREEN，不强造接口；真实model/audit构造无Gateway/缺或空共享接收key均可用，禁止网络探针未被触发。SQL为隔离SQLite，非双库/真实broker证明。Ruff/format/F821/guard/diffcheck及L1测试subset命名/fullAC/单源/已勾T016/T048依赖PASS，勾选 **139/167**，依赖满足允许T050，不宣称整个Wave27完成。


T162：主完整读取Manager587/Outbox255行及原source窄diff，独立私有javac及真实loopback组合 **240PASS/0SKIP**（f111-root-t162/{compile,green}.log），B同240PASS，T16124及旧Manager30/Outbox9/Routing29/Telemetry62/Dispatcher35/Preflight51全部保留。原锁更新bytes/check/drain，从原DECISION幂等闸门一次命中，Request错误标志一次观察；普通取消/close、原backend纯error不混检查故障。流式复用既有synthetic判断、非流式原数组引用区分检查失败，不新增正文解析；Outbox原cached persist失败点计一次gap+固定alert，Manager不重计。L1有限标量/安全/既有响应与IO不变/设计§7.3及两源、已勾T161/T098依赖PASS，勾选T162。

T163仍自审中：初次12FAIL/11PASS里encoded-slash样例遭MockServerHttpRequest字符串重编码，实际status为null，不能归为诊断RED。已立即保留任务未完成，按原Filter测试采用URI入口校正后重跑；T162已独立通过并勾选，目前 **140/167**。



T163最终：主纠正MockServerHttpRequest使用URI原样入口后，实际 **12预期FAIL/11既有PASS/0SKIP**（f111-root-t163/{compile,red}.log）；1缺构造、11全为真实入口拒绝counter0，无fixture/收集错误。原Filter51已在主T162240组合GREEN。部署关闭/无关路由/两个成功路径/租户关闭与license优先级/普通取消/downstream原异常为GREEN；身份401/403/503、empty/sync/async、policy缺失/失败/错租户、license及encoded-slash拒绝保持原status、错误优先级和正文零订阅。B独立fresh-eyes全文读测试+Filter无新阻断。L1测试subset命名/fullAC/单源/依赖T098/T096 PASS，正式勾选，**141/167**，允许T164唯一Filter源；原不准确记录已撤回。


T160：主读取Policy350/Matcher264行，私有独立-Xlint:unchecked编译0诊断，六类实际loopback组合 **161PASS/0SKIP**（f111-root-t160/{compile,green}.log）；C连三协议110项九类 **271PASS**，未把不存在类的早期discovery试跑计通过。旧及生产Redis构造兼容，生产内部matcher也接同Telemetry。age只用既有tick/validUntil重建保守缓存年龄，hit不续期；compile原Semaphore转移+采样同锁，缓存命中不重置别的job，cancel不提前释放物理permit。busy/node/weight固定code各一次拒绝，输入限额/digest/closed不混容量，digest实际拒绝点一次alert/counter。L1架构/命名/信息保护/设计§7.3、恰两源及配对T159/T098依赖PASS，diffcheck clean，勾选。

T050：主完整读取39行config和仅4新增行，独立原7配对 **7PASS**（f111-t050-parent-green.log），A含旧scheduler/runtime/API/context组合 **85PASS**（f111-t050-green.log）。扫描沿既有DSH enabled区块/default queue/原audit_state_scan_interval_seconds，copy+setdefault不污染原schedule、显式override/reimport不重复。audit_admin_runtime真实readiness在前驱已接通，本任务无需改其源码；没有为凑两文件引入行为。Ruff/format/F821/guard/diff及L1职责/无新SQL或接收配置依赖/信息保护/设计§4.9、一源范围和已勾T049/T048依赖PASS，勾选。两项后 **143/167**，允许T051及T108按已满足依赖并行；GatewayT164/组装链仍继续，不冒称全部Wave已完成。


T164：主全文读取260行Filter和仅observer窄差异；原6参noop兼容、新7参尾部注入，唯一原reject点计CHECK_ERROR，未改模型body、响应或错误优先级，不重计依赖counter。主集中常规离线Maven **33类825PASS/0FAIL/0ERROR/0SKIP**（wave26-observers-parent.log），按日志33个类名逐XML汇总一致，含T16323/T15725/T15915/T16124及全部原738。B相邻10类229PASS，自审PASS。L1边界/命名/信息保护/设计§7.3及单源/已勾T163/T098依赖PASS，勾选，原 **144/167**，Wave26完整完成。随后新增已确认防复活需求的必要原生writer接线配对T168/T169，总数改为 **144/169**，未假勾新增任务；T139仅在2源范围内移交Outbox自动扫描所有权，Spring真实注册/唯一实例由T138验证。


T138组装前只读核查：现有PolicyStore构造仅持Mapper/Clock，Admin构造校既有backend URL并建惰性WebClient，无网络；无需为无新配置分支重写两类。Outbox@Service确会自动构造noop observer实例，因此T139第二源仅移交其Bean所有权。当前application.yml和其它生产配置没有model读取timeout，不能借connectTimeout或魔法数充既有预算；已把设计“沿用部署IO预算”落实为检测开启须显式配置现有spring.cloud.gateway.httpclient.response-timeout正有限值，同值注入Proxy/Manager；默认off无该值仍正常，完整回传配置off仍管理/投递。T138真实绑定/组件扫描覆盖这些条件，不新增配置键/第二套密钥。


T051：主完整读取511行及最后bulk观察修订，独立 **25预期FAIL/1真实竞争控制PASS**（f111-t051-parent-red.log），全部RED仅缺维护Repo/lock_retention/begin_cleanup，无fixture/schema错；A原repository/setting/groups/queries组合 **25RED/76PASS**（f111-t051-bulk-scope-final-red.log）。真实caller事务/独立提交watermark、rollback、三轴RUNNING/PENDING后续重访、旧主可补/删后410、会话delta/tree dirty、有限rebuild/已清不假回放、双租户和billing不变均配对。主审收窄engine SQL全UPDATE当bulk的过约束：Session.do_orm_execute只捕实际bulk，仍逐条tenant+目标守卫；原engine记录继续证明setting首锁/真实DELETE。首次缺setting竞争有实际第二connection唯一键控制，但SQLite不作双库锁证明。Repo不得commit/新Session，水位独立提交由T054编排，原生writer防复活另T168/T169。主清理仅主审计+关联安全facts，不销毁无FK的原生Manifest/Evidence/Occurrence/共享对象/密钥或模型用量；body读取先验主行/授权，不能声称原文空间已回收。Ruff/format/F821/guard/diff及L1测试subset命名/full7AC/单源/已勾T016/T038/T050依赖PASS，勾选 **145/169**，允许T052两源。


T138：主完整读取248行及最终禁Bean覆盖发现设置，独立私有javac/真实Spring feature注解扫描+loopback **18预期FAIL/5PASS/0SKIP**（f111-root-t138/{compile,red}.log）；18仅缺组装/启用校验/Outbox默认扫描，既有廉价Store/Admin/Controller实际启动无IO与默认capability认证链GREEN。B旧相邻206PASS；主同链前次825PASS为当前已通过基线，不把组件slice冒充完整部署。测试覆盖真实唯一实例/同Telemetry+Matcher/同HMAC固定backend/已存预算/filter顺序/关闭实际owned资源及关闭检查仍真实签名投递旧事件，未构造假配置或删Bean。主L1测试subset命名/fullAC/单源/全部已勾依赖PASS，勾选T138。

T108：主完整读取Group249/Tree286行，独立临时实际组件 **12PASS**、原目录/审计/navigation/API **24文件195PASS**（f111-t108-parent-{behavior,regressions}.log），C目标lint0/完整602strictPASS。旧缺progress/nullable不报0，真实全会话/筛选与own/branch独立Badge、collapsed已知命中、版本0/安全水位、子页progress与有限scan continuation不新增逐行GET。每对象最多2Tag，新区域CSS scope，原布局/逻辑保持。主实际view生产bundle日语窄图，C三语实际GUI counts[1234,0]/[0,2]/unknown、Badge10/Tag12px、390scroll=client390、console0/API0（gui-built.log），临时资源已关闭；非真实账号E2E。主locale两纯label三语同步、126key parity PASS。功能L1与两源范围/已勾依赖PASS，勾选T108。已确证正式Vite dev优化错选merge2.6丢字号，不能只当截图选择器问题；生产Rollup正确，另T170单构建源修复，未覆盖业务/shared样式。两项后 **147/169**，新增T170后 **147/170**，后续T110须该修复。


T139：主完整读取Configuration160行、Outbox唯一移交的2行删除，常规共享target离线Maven集中 **34类848PASS/0FAIL/0ERROR/0SKIP**（wave28-assembly-parent.log），按34类名逐XML汇总一致；含真实Spring条件扫描23配对及全部原825。B私有296PASS及off Redis listener故障1PASS。默认off不建模型资源/不需timeout；完整配置off仍管理/真实HMAC补报，on显式校既有response-timeout与Redis；同Telemetry/Matcher/Clock、有限owned scheduler、shutdown解除listener并dispose，无重复@Service或假Bean覆盖。主L1职责/配置边界/信息保护/依赖/两源范围及设计§7.3 PASS，勾选，未当完整网关部署证据。

T052：主完整读取最终Maintenance275/Setting105行，独立8文件 **164PASS**（f111-t052-parent-green.log），A配对+相邻 **172PASS**、5项实际SQL临时probe PASS，均隔离SQLite，非双库锁验收。首次setting唯一sentinel flush、单调水位caller先独立commit、每批≤100且facts共享预算、running/pending排除并下轮重访、明确tenant/状态CAS、group delta和first/last索引约束、tree dirty及剩余子会话可见、rebuild原hash/保留窗口/过期skipped均核对。Repo无commit/新Session；不回收原生正文元数据/共享对象/密钥/计量，不能声称原文存储已释放。Ruff/guard与L1两源/已勾依赖及AC一致性PASS，勾选。A扩大特殊runtime→ingest→API→middleware顺序36FAIL/101PASS，以HEAD原Setting独立内存overlay确证同36FAIL/101PASS且endpoint module与sys.modules分叉，Maintenance未加载；保留旧fixture隔离缺陷证据，不归T052回归、不越界修复。两项后 **149/170**，允许T053和T168各自唯一测试先行。


T170：主单构建源仅2新增行（对T155稳定preimage比对），optimizeDeps.include预编译@bisheng/ui自身依赖图，保留UI1.14/Platform2.6锁定merge；未加依赖/改组件/设计值。正式Vite5 dev真实helper DOM before丢text-caption-sm/12px → after保留/10px，Tag12px；同维护plugins/resolve的独立合成入口三语+390实际GUI PASS，console0/API0、根radius不变。新生产bundle独立重建4.05s（仅通用chunk-size提示）、三语+390 GUI再PASS，主view dev日语窄图。Platform原cname真实dev import 5合并语义PASS，613selectors/90,843bytes scope probe PASS，配置TS对HEAD基线仅同一http-proxy声明缺失/新增诊断0。证据f111-t170/{font-before,font-after,gui-after,legacy-after,production-build,gui-production,scoped-style,config-typecheck}.log。初次全GUI私有入口被HTML插件注入正式app而超时，仅调整私有harness剔除HTML入口注入后验证，未当业务失败或有效E2E。主L1基础设施架构/无DB/信息保护/设计同步/一源及已勾T155/T108依赖PASS，勾选 **150/170**；T110待T109主验后解锁。


T171：主唯一测试源把冷启动检查移真实独立Python进程，guard在首次import前安装，仍真实构造IngestService且session_factory零调用，并验证父进程module身份不变。原同5文件顺序 **36FAIL/101PASS → 137PASS**（f111-t171-five-parent-green.log），单独cold1PASS、4文件131PASS；Ruff/format/guard/diffcheck PASS。冷启动行为检查保留且隔离更严格，无API fixture或生产源改动，无HTTP断言放宽。L1测试subset命名/完整AC/单文件/已勾T032/T034依赖PASS，勾选 **151/171**。此前T052的HEAD Setting对照证明归因边界，本条修复本特性T031自身fixture污染，不把已知顺序错误留到交付。


T109：主完整读取最终List329/Panel565及字段a11y最后差异，独立 **16行为PASS+原24文件195PASS**（f111-t109/parent-{behavior,regressions}.log），C最终603strict/targetLint0/同回归全绿。独立局部v4 Provider/tenant+caller+权限scope key，旧页hidden保draft/cursor，首次进入才查events，6支持条件/显式UNASSOCIATED，未固定默认相对时间，有限20页，错误固定文案/失败页原cursor重试、旧scope abort/忽略。现有Group/Tree进度仅父页面传递，无逐行HTTP；实际metadata详情无原文/usage伪造。Input具体error状态先2RED/14PASS→16GREEN，日期两field，ID仅非法field。C实际wrappedAPI+strictDTO三语合成生产GUI PASS，390 scroll=client379、零renderererror、三exact HTTP query无隐式日期；主view日语窄图，非真实账号/后端筛选E2E。三语新增3key分别落原T099/T100/T101各自bs.json维护范围，contentSafety **129key parityPASS**，不碰generated api_errors。旧bs-ui Input style-jsx warning单列，不泛称全旧页console0。主L1命名/接口边界/前端约定/信息保护/设计一致/两源及已勾T108/T102依赖PASS，勾选 **152/171**，T110依赖均满足。C已关闭独立41786服务，主T170的41789/41790也均关闭。


T052/T053交叉修订门禁：主在已完成T051唯一测试源补已提交主清理水位后的details-only案例，真实RED缺include_audits；暂撤T052，修复仅原Maintenance增加默认True兼容参数，False只明细后返回，不修改主checkpoint/cursor。主读取全部差异并独立8文件 **165PASS**（f111-t052-parent-final-green.log），A27retention+相邻140PASS，重新通过L1并恢复勾选。T053最终456行33case主全文及参数化新场景读取，独立 **1缺脚本FAIL/31缺脚本ERROR/1真实fixturePASS**（f111-t053-parent-final-red.log），无其他setup错误。真实caller事务、dryrun零DML/DDL且全部rows不变、UTC/参数前置拒绝、bounded/cursor租户、disabled/archived、checkpoint跨connection先commit、后batch失败保水位/rollback、commit失败不输出成功、六scope恢复、安全固定错误及DB-only无其他middleware均承接。新CLI测试含真实已存在非空cleanup cursor时details-only保所有Setting字段。Ruff/F821/format/guard/diff及测试L1命名/完整AC/唯一文件和已勾T016/T052依赖PASS，勾选T053 **153/171**；允许T054只脚本+README，勿把CLI缺失RED当实现通过。


T110：主完整读取永久Settings254/Details582行（跨页补读所有片段），正式仓库Vitest独立 **2文件54PASS**（f111-t110/parent-final.log），C同54及26文件249PASS（原195+新54）、完整605strict/targetESLint0/diff0。真实v4/hook/CAS helper/Card/Filters/Details/Panel/Unassociated/原文组件保留，仅API外端口替身；HTTP409及HTTP200业务409保draft/显式刷新后新version保存、配置未知/关闭区分、空ID、六态/真实usage与unknown独立、三语BOTH交集copy、PURGED保主摘要、失败page/refresh cursor重试、六条件和field a11y、tenant及同tenant hidden caller取消/旧缓存移除、旧页保draft/cursor均保护。readAuditBody监测无触发，不用替换Body组件掩盖调用；合成transport logger与旧Inputjsx提示单列，非真实账号E2E。L1测试subset命名/完整11AC、两文件≤600、已勾T104/T109/T170依赖PASS，勾选 **154/171**。

真实MySQL准备（未勾T119）：主私有脚本通过实际DatabaseConnectionManager和未替换的完整Alembic online env/模型发现，在本次唯一临时dsh_test_f111库fresh upgrade head再重复upgrade，实际 **144表/f111_dsh_content_safety PASS**，finally仅删除本次库（f111-full-migration-preflight.log）。只替换连接配置入口，不替换migration/DDL；旧F029缺OpenFGA store/model回填跳过、F030空数据0行，不能当完整应用环境或真实DM8验收。首次私有probe误给只读engine property赋值，未运行迁移即异常并已清库；改为真实连接Manager构造后成功。T119永久真实并发/升级前后/schema回退仍待前驱齐备，未伪勾。


T054：主全文读取最终CLI155行及README53行新增，独立8文件 **184PASS**（f111-t054-parent-final-green.log，35 CLI+27 retention及相邻），A八相邻选择175PASS。真实shared settings/session端口，DB-only严格profile_scope六context恢复、默认dryrun仅tenant验证/不扫描也不伪造估数、显式apply每batch事务且commit后才JSONL、main checkpoint独立先commit、details-only保水位/cursor，固定非0类型错误，README明确存储/billing非GC和部署writer guard前置。自审实际坏YAML与真实空SQLite下层logger先泄露trace/SQL的RED已保留0600；仅独立__main__进程导入前关闭bisheng/std业务日志，库导入不改宿主logging，固定安全stderr。主补T053同一源2永久真实子进程回归，35全部GREEN，正常/坏配置--help均0；不改core第三源。Ruff/format/F821/guard/diff及L1架构/命名/DB caller事务/信息保护/设计、恰脚本+README/已勾T053/T052依赖PASS，勾选 **155/171**。执行主清理前所有writer部署防复活仍由T169与后续运维验收约束；未执行真实环境清理或部署。


T174：主唯一既有查询测试源新增18实际Repo断言，旧34保留；独立 **18预期RED/34PASS**（f111-t174-parent-red.log），4为upper查询丢记录/同规范cursor错误拒绝，14为非法UUID未前置安全拒绝，不把SQLite当DM8。大小写等价与显式cursor、不同实际ID仍拒绝、跨tenant隔离、不在SQL列调用LOWER以保索引、非法值SQL零调用均明确。Ruff/format/guard/diff及L1测试命名/full5AC/单源/已勾T109/T040依赖PASS，勾选 **156/175**，允许T175唯一查询Repo。新总数包含实际null序列化两任务T172/T173及本配对；不改已确认默认相对分页窗口。


T175：主完整读原查询Repo并只加UUID值规范化端口，校验36位canonical UUID并lower后供显式binding与原列等值比较，固定安全ValueError/SQL前拒绝，不在列调用LOWER、不变默认移动时间窗口。独立真实Repo+HTTP/group/retention/CLI **177PASS**（f111-t175-parent-green.log），T17418全绿。Ruff/format/F821/guard/diff及L1职责/严格tenant/信息保护/设计、单源/已勾T174/T109依赖PASS，勾选。

T168：主完整读取339行唯一测试，独立 **13预期RED/11PASS**（f111-t168-parent-red.log），B原六文件107PASS、组合13RED/118PASS，0skip。真实writer/ingest caller事务、首Setting锁→唯一sentinel flush→Request顺序、fresh session重试/故障rollback、strict微秒watermark边界、现存有效主可补、双tenant及mode/version不变、receipt/两冲突先于retention锁均配对。观测真实ORM statement/flush而非模拟锁算法；SQLite不作真实并发证据。Ruff/format/F821/guard/diff与L1测试subset命名/完整3AC、单源/已勾T052依赖PASS，勾选。原T021 test_retention_defaults_allow_historical_fact_without_setting_watermark要求setting仍空，与新明确sentinel契约冲突；待T169实际仅此断言RED后主精准维护原测试文件，不允许配对实现藏第三源。两项后 **158/175**，允许T169两生产源。


T172：主全文读取OutboxTest268/ControllerTest456及截断helper补读，真实生产SpringCustomConfig mapper与WebFlux codec，独立私有javac+实际loopback **35项32PASS/3预期FAIL**（f111-cross-review/t172-parent-red.log）；三红精准为事件nullable被写空串、absent-service和snapshot-failure cap digest非JSON null。其余原32行为保留，真实known IDs/子会话/strict数值bool、共享legacy mapper仍null→空串、event/hash原持久字节均保护；无假mapper或B/Platform容错。L1测试subset命名/fullAC/恰两源/已勾T139依赖PASS，勾选。T106在独立Card未知名称设计缺口回归时暂撤（T110同原测试源补2RED/32PASS），故当前净 **158/175**；允许T173只Outbox+Controller局部修复。


T106/T110复审：真实EXTERNAL_SAFETY条目model_name为空而model_id已知，原Card两处只显名称，违反设计§4.8。主在原T110 Details测试源补空串/空白名2真实RED/32PASS，暂撤T106；只原Card源复用现三语model_id label作为header/title/详情fallback，无新组件/样式/键。独立全部26文件 **251PASS**（原249+2），完整605strict/目标ESLint0/diff0，测试589行≤600；原文仍零调用。L1原T106两源范围中只Card及原T110唯一测试维护，设计一致、恢复T106勾选。

T169：主完整读取最终两个仓储及锁/边界差异，独立新旧7文件 **131PASS**（f111-t169-parent-green.log，原107+新24）；原生先Setting→Request，旧missing严小于水位拒绝，已有有效主仍可补；receiver统一锁行/retained Request FOR UPDATE populate_existing，receipt/冲突先行不改。B新24GREEN、Ruff/format/F821/guard/selfreview PASS。原合跑4旧fixtureRED保留：T0213处（默认Setting空断言/重复insert/SQLite first-sentinel写锁混进Fact竞争）+T0291重复insert；主精准维护原两个测试文件，历史允许/原fact唯一竞争/新事务重读/回滚断言不删，首次Setting竞争仍T168覆盖，未在169藏第三生产源。L1恰两源/事务归caller/无commit/tenant/设计与已勾T168/T052依赖PASS，勾选。

T030追加实际缺口待修：B真实Service probe显示已有未关联receipt在foreign主PK占用解除且租户水位推进后，重放仍会走merge而重建旧主。原append receipt优先正确，但不足以覆盖Service后续投影。已暂撤原T030；在原T029测试源补实际foreign冲突→保留COMMITTED事实→水位→重放不复活，原T030唯一Service源修复，保留已提交receipt的ACK/重复语义及窗口内修复关联。不扩169源/不新增任务，T119明确依赖修复。当前 159/175，未当整个防复活链已验收。


T173：主完整读取Outbox私有mapper差异及Controller196行，standard NullSerializer仅copy provider，nested Capabilities digest显式@JsonSerialize(nullsUsing)，全局legacy null→空串保留，事件/hash/HMAC不在投递时重写、B/Platform consumer不放宽。主正常共享target离线Maven **34类851PASS/0FAIL/0ERROR/0SKIP**（t173-parent-regressions.log），逐类XML汇总一致；C私有35及7类238PASS、最新私有实际Java payload→B Event/Envelope严格schema PASS，旧gap恢复正常JSON null。T138原唯一测试维护单独先4ClassCast RED/19PASS，再把4组Java Map过约束换真实生产codec字节/JsonNode断言，保留并增强布尔类型/digest null及所有Bean/投递/close行为；私有23+35=58PASS，主全文268行并集中再验，不在173藏第三生产源。L1局部JSON边界/命名/无全局serializer改动/安全/设计及两源、已勾T172/T139依赖PASS，勾选 **160/175**。G先前jar为此修复前的构建产物，不当当前运行物，后续打包须重算hash；未启动正式服务。


T029/T030复审恢复：主读取新3个真实Service参数场景与唯一Service新增分支，独立先 **1精确RED/32PASS**（f111-t029-replay-parent-red.log），修后10文件 **252PASS**（f111-t030-replay-parent-green.log）。duplicate已持久fact继续同短txn持Setting锁验证水位；仅Expired跳过归并并保留原COMMITTED/duplicate/原hash/未关联事实，within-window恢复关联及仍存合法旧主继续归并，非duplicate原410与冲突优先级不改；不无条件跳过所有duplicate。无新增Session/commit/SQL/Request预读，不改Projection或重排原锁；同tenant setting持有至caller结束。L1原T029单测试维护/原T030唯一Service及原全部依赖PASS，Ruff/F821/format/guard/diff PASS，恢复T030，**161/175**，所有核心实现/配对截至Wave32已完成，T119永久真实DB测试前驱齐备。

真实MySQL升级私有准备追加：A真实归档基线2e6b5ae0的work110源码online env重复迁移143表并种旧ORM记录，再当前源码升级+重复至f111 144表；current fresh+repeat与upgrade完整144表列型/NULL/default/PK/index/unique/CHECK反射 **0差异**。历史mode METADATA/version7、原生执行记录、未知NULL用量和monthly17/version2逐值保留，新安全语义UNREPORTED。内外进程socket guard非DB尝试 **0**，F029显式OpenFGA disabled，修正上次以不可达跳过的证据边界。finally仅删除本轮两UUID库，容器/其他库不变。证据f111-mysql-schema-probe.log、f111-real-schema-comparison.json与独立phase私有0600日志；只是准备，不替代T119永久并发/水位/双库验收。最新全frontend check-i18n再次PASS（f111-t130-preflight/check-i18n-current.log），既有全量lint/clientTS基线阻断仍保留。


T009 fixture 隔离维护：实际 DatabaseConnectionManager 将 DM8 path 规范化至 query.schema，原 fixture 仅认 URL.database 会拒绝合法隔离 schema。主仅维护原 content_safety_fixtures.py，支持规范化 schema 与旧 path，拒绝冲突两者、重复 query、系统 schema、不安全标识符及非 MySQL/DM 方言。私有纯 URL guard13项及原 repository/retention46项独立 **59PASS**（f111-fixture-url-guard-final.log）；不连接 DM8，不据此声称驱动/DDL/锁通过。首次 guard 暴露空 path 为字符串而非 None，已修正重跑；Ruff 与后续 T119 实际 MySQL仍单列。任务清单实际解析 **161/175**，依赖无缺项/循环、已勾任务无未勾前驱，修正页首滞后的115/155显示。


当前 Gateway 构建补验：主 agent 在 T173 修复之后离线执行 `mvn -o -DskipTests package`，实际 BUILD SUCCESS（f111-gateway-tools/t173-current-package.log），当前 gateway-0.0.1-SNAPSHOT.jar SHA256 为 `d115c09f3209f703b2bc0e354af9122166f2140e4be2af032955d4996b246d36`。该命令跳过测试，测试证据仍为前述独立851PASS，不混成新测试运行；没有启动正式应用、部署或制造 License。


T009 追加隔离复核：用真实 SQLAlchemy dialect.create_connect_args（不建立连接）确认 MySQL query `database`/`db` 可覆盖 URL path，原 fixture 只验 path 会漏掉这类目标变换。主在同一 fixture 源前置拒绝 database/db/schema query 覆盖，扩大私有 URL guard至16项；合并原46回归 **62PASS**（f111-fixture-url-guard-overrides.log），Ruff/guard通过。修改schema选择前的所有内容安全及原生retention组合回归已独立 **587PASS**（f111-fixture-maintenance-regressions.log，0失败；没有将真实数据库集成混入该组件组合）。此补充不修改业务代码或声称DM8通过。

/e2e-test 准备：主已完整读取 B 的只读矩阵 `/private/tmp/f111-e2e-ac-matrix.md`，实际59条AC完整连续/唯一并保留AC-34优先表，逐条映射真实路由、PKCE/helper、T121–T128及所需环境。59条真实E2E均NOT_RUN，不以既有组件/SQLite/GUI合成预览替代；三份拟新增HTTP E2E源仍待前驱及授权完整环境。现有cleanup helper分页与吞错不能直接证明清理，未来需按自建前缀/tenant/IDs GET核实；公开入口封闭还需部署侧证据。尚未提供可用完整授权测试环境，未绕过License/鉴权。T121–T128及T125仍未勾选。


T119 MySQL子闸门：主完整读取最终926行唯一永久测试（SHA256 `254e46203b8a16d55ef51e51ab02421cea09ca4455efe112c30fbb569c95c30c`），最终源码独立真实执行 **16PASS/16DM8明确SKIP**，58.31s（f111-t119-parent-final.log）；前版主16/16 68.35s与A16/16 49.29s分别保留。真实8.0.46/PyMySQL1.1.2/SQLAlchemy2.0.44，actual archive work110143表→F111144表与current fresh全表schema一致；重复升级、旧mode/version/未知usage/17token事实保留。实际双session去重fresh retry、两租户/foreign PK、original hash冲突、同txn rollback、提交后丢观察重放、Setting缺行两序列实际SQL阻塞/释放、RUNNING保留再terminal后重访删除、dirty owner fence/revision restart、details-only保命中/PURGED/既存cursor水位、空及有数据downgrade拒绝并保Fact/Request/Call/月用量均通过。此处丢观察是after_commit故障注入，不冒称真实TCP丢ACK。父子仅连接owned容器、唯一2UUID库finally清理，完整baseline树hash+路径、DB-only network guard、日志局部关闭恢复、URL覆盖前置拒绝均交叉自审；私有21负/3正guard探针PASS。Ruff/format/F821/arch-guard/diff与L1测试subset/完整AC/唯一源/全前驱PASS。DM8无真实Linux/schema环境，整体T119仍未完成 **161/175**；只解锁已明确的MySQL独立子闸门。

T120 MySQL子闸门：主全文读取最终430行唯一Java测试及所有后续差异，源码SHA256 `2b97c4862ec5a45012de3ede7d5b874ee8c7fcfd259cf80d5decc482db0e3e7e`，A119实证后为C及主各准备全新unique库/限定库权限专用用户，0600manifest未输出值。C真实10PASS/0SKIP 15.611s；主另一库正常离线Maven **10PASS/0FAIL/0ERROR/0SKIP** 18.614s，逐Surefire XML核实（f111-gateway-tools/t120-parent-mysql.log）；C相邻106PASS/新类默认10SKIP，默认不连接。actual MyBatis/Hikari/MySQL8.0.46/Connector8.2.0/JDK17.0.21/isolation4，DDL hash见G docs/dsh-content-safety-verification.md。真实first/create及same-version更新竞争一胜一409、唯一immutable事实、双pool领取owner fence、child JVM abrupt exit后10s实际lease恢复、真实HMAC client/SQL dispatcher丢首ACK相同fact重传、第三次HTTP409隔离重开保留、仅7天旧ACK清理、真实双表判空/停写保护与empty rollback/recreate通过。受控receiver不当backend摘要去重/完整E2E证明。主实际锁201ms observer超时物理active1，释放后version2，明确取消不保证JDBC中断/rollback；100/250领取385ms<4s测试lease，小表计划ALL/filesort不当性能通过。范围恰唯一测试+验证doc，实际前驱MySQL子项及L1命名/完整AC/信息保护PASS；没有修改生产求绿。DM8未执行，T120整体未勾，T121及后续完整链仍待环境/前驱。


后续待执行文档留档：主完整审阅59AC矩阵与197行运维草案，保存 `e2e-checklist.md`（59行均NOT_RUN、真实前置/入口/helper/记录要求）和 `rollout-runbook.md`（T131准备稿，未满足容量/质量前驱、未执行部署演练）。手册按实际代码核正PROFILE_LATENCY_NANOS，并把T120 MySQL SQL片段10PASS与现场演练NOT_RUN分开；Gateway source与Docker response-timeout配置差异、worker/default queue/readiness、共享HMAC/默认X-Signature、公开入口网络验证、关闭检查保在途/补报/用量、旧DTO无兼容证明不回退、B downgrade无条件拒绝及无现成Backend空schema收缩脚本均明确。没有为文档新增配置/改代码/执行部署，T121–T125/T131均不勾选。T120两轮owned目标经owner marker/两表为空/无连接/无routine逐一检查后，已仅删除本轮2库及专用用户，私有cleanup receipt保留于f111-gateway-sql-targets，未停止或更改容器/其他库。


未执行项最终区分：T119/T120仅待各自真实Linux DM8子项；T121–T125缺完整合法授权的隔离backend/Gateway/角色/受控provider及故障操作环境，不能用SQL片段代替；T126–T129容量依赖T125且真实双库/百万千万与堆负载尚未运行；T130的完整前端lint/client typecheck仍为已核HEAD一致的既有失败，不能标绿；T131手册仅草案、网络封闭和回退部署演练未做；T132尚未满足特性最终审查前驱。全部保持未勾，当前161/175。没有提交/推送/部署，三仓HEAD仍为tasks§2的原SHA。


独立负载准备（未入仓、未验收）：B在 `/private/tmp/f111-t127` 保存单源DshProfileLoadTest草案/资源契约/manifest，Java17私有编译及默认10SKIP/0执行；`/private/tmp/f111-t128` 保存单源DshSafetyCapacityTest草案（最终389行）/资源契约/manifest，编译及默认5SKIP/0执行，参数模板未展开。两者均未运行HTTP/Redis/负载或benchmark JVM，主未完整审阅源，不能称行为就绪或作为T127/T128通过；后续必须先满足T125、完整审阅和独立资源执行。没有复制到G或修改共享target/生产预算；相关任务保持未勾选。


## 2026-10-24 work120 集成任务复验

源提交：B 3420114d0、G 108eb5c8、Desktop 6c84d46。B 在独立 worktree 将源历史合入 target 858f766，尚未形成最终合并提交/推送。

- T176 PASS：已读两目标源码，唯一 head 为 f111_dsh_content_safety，接续 f062_credit_multiplier，已发布两积分 revision 哈希断言保留；配对12 PASS、普通入口相邻组合37 PASS（含T181），Ruff/架构/diff通过。
- T177 PASS：已读 router/middleware 全部冲突上下文；target 路由及 web-session 保留，F111 仅增加精确 POST 回传所有权。HMAC、回传中间件、web-session、SSO HMAC 组合82 PASS；Ruff通过。日志 /private/tmp/f111-t177-auth-regressions.log。
- T178 PASS_WITH_NOTES：主已核七页签定义及default规则，导航14项、相邻28文件273项PASS，Platform609严格文件及workspace类型检查PASS；定向eslint通过。全量lint target旧问题有独立字节基线；不当作全量PASS。
- T181 PASS：原特性源确证15表常量旧失败；维护为模型/实表集合精确相等，保留原数据/列/索引/幂等断言。正常入口7文件37 PASS；主读取实际diff复核，无生产源修改。

T182–T184 翻译检查正在复验，T179真实MySQL联合升级执行中。更广组合backend回归发现失败，正在区分既有冻结配置夹具与新增集成问题；尚未宣告最终版本回归通过。DM8继续按用户决定保留待验收。

T182/T183/T184 PASS：主已读实际翻译差异/自审记录，补12日语键及28001–28009 sandbox三语，规范generator更新6产物；全check-i18n/locales:check通过，真实i18next27项双namespace及插值通过，文案后78项PASS。未扩大baseline。

T187 PASS：原target Chat夹具直接修改frozen DshSettings，真实2FAIL+2teardown ERROR，遗留monkeypatch造成13个后续scope断言假失败。第一次替换Settings.dsh触发旧Settings赋值validator（celery_redis_url已规范化为list）同样中断，已改为测试局部monkeypatch.setitem(settings.__dict__, "dsh", immutable-copy)，不修改生产配置。原全部业务断言保留，Ruff规范重排；同进程受影响6文件162 PASS（/private/tmp/f111-t187-final.log）。独立其余组合901 PASS、15 SKIP（真实DB opt-in），日志 /private/tmp/f111-integration-safety-regressions.log；最终含Chat完整组合仍待重跑。

Gateway候选108eb5c8七维审查NEEDS_FIX：实际Java证明同message相邻output_text以及同reasoning的content/summary各自跨part漏检（dan+ger），流/非流原响应错误放行；AC-21/22/23要求同域连续检查。T185/T186配对修复中，未推送/部署候选。另T188仅开发模式react-query原始AxiosError可能记录草稿，局部修复中；不能以正式production不打印掩盖该信息泄漏。


### 最终组合候选验证（2026-10-24）

- 后端广组合最终：**910 PASS / 15 SKIP / 0 FAIL / 0 ERROR**，147.96s；skip均独立真实环境opt-in未提供，不算通过。/private/tmp/f111-integration-backend-final.log。
- T179主独立真实MySQL：**24 PASS / 24 DM8 SKIP**，270.13s；A独立303.53s同结果。fresh149、真实work110归档143→149、真实target858f766积分归档148→149全部反射等价；原始80/125倍率/计费100/UNKNOWN NULL及规则ledger快照保持。七项SQL计量与安全联合case通过（不冒充Gateway/Redis模型E2E）。/private/tmp/f111-t179-parent-independent.log。两源已读/交叉只读复核，隔离创建列表限定清理，无第三方schema删除。
- T185/T186主独立：**Gateway 34类882 PASS / 0 skip**，15.719s；Responses60/60（原32，新增28）。19初始RED、Unicode/空part/mixed后续RED均保留，1800语义对照通过。/private/tmp/f111-gateway-candidate-review/t186-parent-independent.log。主已读实际adapter及L1报告，同步design混合观察尾屏障与64候选预算；无改spec。
- T188–T191主交叉读实际diff：安全logger2RED→24PASS；Card新增5RED→10PASS，未知/未执行不伪造时间。DSH 28文件280PASS、Platform609strict、四目标lint、全i18n/locales通过。最终UI修复之后两个SPA再次正式pnpm build exit0（/private/tmp/f111-work120-frontend-final-build.log）。旧全量lint Platform95/Client23均字节等target，仍不称全绿。
- Desktop6c84d46正式build通过、临时Profile实际启动日志有Harness is ready，所有userData/session/log路径均在/private/tmp/f111-desktop-live.d65u13l2。原生CUA窗口检查异常耗时，只返回空窗口，未据此宣称完整UI验收。完整npmtest：2810PASS/5FAIL/3SKIP及3unhandled；typecheck通过。Python3.10 chdir环境问题用已有3.11独立7PASS，SSE readiness原用例单独1PASS但非全量通过。既有Undici private receiver真实故障登记T192修复。为依赖重放仅退出本轮5347，已确认5347/5368退出及43228/43230清空，不清用户profile。

当前候选B/G源码审查与聚焦门禁已收口，T192及真实部署/客户端登录/E2E/容量继续推进。未把LinuxDM8缺环境或全量legacy lint当作通过。


T194/T195 L1主完整读105/376/680行源，C独立复跑27合成边界+33真实loopback/SDK及额外15实际协议/资源检查均PASS，无HIGH；0600/Origin/真实PKCE/独立HTTP客户/CAS恢复与仅自有资源约束通过。Provider无外部网络client，32槽/128场景/128KiB及合成文本32KiB有界，不记录正文/Token。网络发布/故障和真实E2E仍非本地probe证明。发现scenario0不能排除未标记调用，登记T196增强物理全局计数与final独立版本fixture，T121不得以旧计数误证输入0。主真实账号只读核知识/评估/助手/工作台所需默认已配置（实际API为嵌套envelope，未写默认）。

交付：B正常merge并远端读回ecf43f79c8aa31bc645636e94b78fb1c9a74bcf9；G最终faa6463b14cc908e6e507241a9d280efb040e80e同名分支与唯一DSH tag原子推送并读回。Drone B5623/G403均SUCCESS，G stage只有clone/package/image/notify四步，115部署步骤被ref条件过滤。109使用原有cr入口拉取，digest逐一等CI日志；未修改共享Docker daemon的insecure registry配置。


T196 PASS：C独立读冻结404/767行helper/Provider，13新增+原27/33以及额外10真实loopback检查通过，含32混合并发/global32、饱和不回绕并由helper拒绝、独立delta/done/final观察。主逐项读最终合同与报告，通过私网部署gate。实际109仅临时f111-provider容器加入dsh-integration，控制面宿主127.0.0.1:18181经SSH，本轮随机0600测试key，不连接外部模型。现场协议仍未验。

T192 PASS_WITH_NOTES：主读最终补丁/10配对及完整报告；标准clean npm ci 34patch成功，原包reverse/replay与真实安装SHA一致，package/lock未变。既有Mac CI=1串行配置+临时已有Py3.11 PATH完整2820PASS/3SKIP、0FAIL/0unhandled，472.78s；此前默认并行2817PASS/2FAIL的两个原物理复制超时记录保留，不宣称已证明竞争机制。最终npm run build再次exit0，已实际启动最终补丁客户端；隔离Profile与Harness ready成立，完整UI/模型/工具验收另列。

109实际交付：B/G四目标容器镜像ID均等本次CI digest，B健康200、UI200；backend升级到f111_dsh_content_safety。实际ConfigService没有自动SSOSyncConf env覆盖，首次runtime hmac_configured=false（env已到达）；使用其既有YAML !env构造器引用0600env_file的共享key/header，真实load_settings_from_yaml内部值校验通过，仅重建backend/worker后实际hmac_configured=true。未把共享key明文写YAML/文档/Git。Gateway随后只重建指定gateway。部署前后所有非四目标容器ID/image/startedAt逐字节相等，额外仅本轮测试Provider。

真实联调阻塞：GET /api/license/status actual expired=true，两个/api/sensitive/dsh管理接口HTTP200但status_code11001；已请求适用有效License，不绕过。独立发现work120离线模型管理复用online调用快照阻止安全上线前私有配置，登记T197/T198最小修复后再创建测试模型；不先online制造公开窗口。DM8/完整E2E/容量仍未执行。


T197/T198 PASS：C持久16配对先11FAIL/5PASS→服务14PASS/管理2RED→全部16PASS；B独立五文件71PASS，主独立相关70PASS/5环境skip+新模型初始化1PASS。主完整读三源，Ruff/archguard/diff通过；管理只在既有admin authorize/profile_scope后读取独立治理快照，调用路径固定online_required=True，canonical Root共享和provider-owner核查不变，CAS409/倍率保持。新测试替换管理认证外端口，非admin真实现场拒绝另验，不夸称真实角色/双库证明。C扩大12旧文件用完整精确HEAD service源码和current各跑133PASS/同4FAIL/同1缺环境ERROR，属既有默认DB mock与DSH_TEST_DATABASE_URL条件；不改夹具求绿。109已创建本轮server5与model8/9，两个offline/status0，所有既有默认模型快照逐字节不变；安全收窄与上线等待包含该修复的新镜像。

Desktop最终两源补丁已提交3e8486c；本轮已启动进程含该补丁，真实公开state connected=true/phase=connected、目录0（尚未开测试模型），不冒模型执行证明。


2026-10-24现场进展：B最新治理修复3cc9de9298ad2c6346f17d180105d46d2d3e3324经Drone5624 SUCCESS；backend镜像8c001dcc8c921ebf32c8e5c468d5368216c56b698a3511e2421f860713ee4392实际运行，frontend与5623 digest相同无需重建。模型8/9在offline期间用真实管理GET/PUT CAS收窄为仅本轮普通user9，并读回确认后才online；普通user两端点真实HTTP200/status19801拒绝，既有默认模型和其它credit规则不变。

四协议正常真实HTTP烟测4/4通过：每请求global和scenario物理Provider delta1，确切文本/SSE终态和80usage，原生MODEL/SUCCEEDED/SETTLED与安全DISABLED分离。四请求事件各AVAILABLE/一个FINAL，证明真实HMAC发送/接收；列表PENDING为保守展示，详情可用，不误称丢事件。第一次只等待SETTLED时usage事实稍后到达，改测试有限等待完整30/50/80且保留严格最终断言，无生产改动。实际Electron两独立UI会话分别选Chat8/Responses9，均可见合成文本和80token；真实session-title另产生调用，不把物理模型次数当工具执行次数。

T122真实基础4PASS/3deselected（3.22s），PKCE/profile/models、两个完整凭据/refresh、logout后旧新access+refresh精确session_revoked，以及admin可读/普通GET-PUT19801且snapshot无变。A独立467源读及guard4/cleanup6合成异常安全检查通过；三策略例在此前License阻塞下未跑，不勾完整T122。T123最终633源已主全文与新增validator复读，B独立实际关闭嵌套/值/normal轴两个测试盲区；只读既有4normal manifest真实API 4PASS（5.30s），不触模型/策略，不冒SQL/ACK/Outbox或故障恢复。

用户追加授权“生成License”后，主使用现有gen_license/gateway_license.py官方sso兼容格式、匹配当前Gateway公钥生成30天trial，expire_day2026-11-23，仅存0600，不需DSH发行私钥。只更新109 DSH Gateway license配置并备份/重建该服务，真实expired=false；capabilities available/enabled/configuration_ready全true。平台聚合按既有一天采样仍旧过期，主经现有上报接口同步真实Gateway状态，读回expiring/30days。未改许可检查或其他部署。

T199/T200/T201 PASS：现场普通Gateway管理GET真实503错误映射，Client原20案例4RED→精确只加19801拒绝映射→Client20+Controller24全44PASS、34类891PASS；B独立私有javac44PASS+原三向Netty3PASS，未知19899/19803/500保持503。主读两源、追加独立验证文档并提交64f602bed9fc8593cb957fb1326c229f911aae1c，已原子推同名work120分支及唯一v1.8.0-dsh-f111-20261024-admin-denial-64f602be标签，远端解引用已核。Drone404 SUCCESS，实际只有四步、115部署被条件排除；运行109尚待当前协议套件结束再更新。

T121首轮真实8PASS后第9(Chat非流输出BLOCKED)因测试错误混用Gateway公开错误编号和Backend audit UUID而失败。实际API证据为MODEL/BLOCKED/模型SUCCEEDED/raw80且DECISION正确关联，生产合同无改。A在唯一测试源修为分别记录public/backend/audit IDs，先8编号反例RED→GREEN、原23解析反例保留；C独立门禁PASS_WITH_NOTES。原CAS恢复失败又logout失败会保留Python异常context，只有顶层展示风险，实际合成probe留档，不伪称清理成功。主重跑该实际单案1PASS（10.59s），随后全35运行中；旧首轮失败日志/XML保留。策略已确认首轮退出恢复disabled/version18。


## 2026-10-24 最终单实例现场验收（替代此前“全35运行中”的当前状态）

- T121真实完整已落地协议子集35/35 PASS，380.29s；输入403的四模式global/scenario0、无账本增加；输出四模式阻断后仍实际30/50/80结算。Responses delta/done/final独立文本、reasoning summary/content、邻接空part、工具参数、完整历史/内部用途及Unicode均有真实链路观察。保留首轮ID测试失配历史，不改业务满足测试。日志protocol-live-final.log/XML均私有0600。
- Gateway CI404 exact64f602be已仅重建109 dsh-gateway；实际镜像digest63d7d9eddd7b0b5c5633b8ab598f633c5ad6120d017de07221dc5fb93f75d908，imageID3bb8d64d1a3cd4f23a11b07826d5c7be8bdd673b0d906005528f76f0ddf50df4；capabilities正常且许可证保持有效。T122全部当前7例真实PASS/29.83s，普通Gateway策略管理精确403、admin允许、CAS旧版本冲突和非法配置不保存、撤销会话后原始准入拒绝均验证；不冒跨租户/多副本缓存验收。
- T123从最终JUnit实际UUID经GET复核生成12条manifest（四NORMAL PASSED、四INPUT_BLOCKED EXTERNAL_SAFETY、四OUTPUT_BLOCKED MODEL）。最终633行只读测试4参数PASS/12.47s，每参数遍历3类并对摘要/事件稳定两读。Gateway重启后仍可查询，不冒Backend进程重启、事务ACK、丢ACK或Outbox故障恢复。
- T202/T203主读902行Provider和335行持久测试、B独立全读及新48PASS/旧SDK33PASS/计数13PASS。默认lookup保持；工具名声明、same scenario+protocol+issued-call-ID+name+JSON对象语义参数+非空结果后final text，最多16标量tuple，不存请求/凭据。先保存旧global counters且active0才更新本轮Provider（SHA80782c04c0936c16aefeacbed35e7382b04d22901df8f97f8c567394289772fa），新进程计数从新基线开始，不能跨重启相减。
- 实际Desktop Chat与Responses各独立两会话：正例公开持久tool/call1+tool/result1、isError=false、确切参数/同callId且结果含真实文件新nonce；turn/end completed。负例公开持久tool/call0/result0、turn/end CONTENT_FILTERED，界面显示租户合成提示，无自动重试。每个正例两次chat模型请求各raw80，负例一次chat模型请求raw80且安全BLOCKED、模型SUCCEEDED、SETTLED；另有原生session-title辅助请求，所以Provider场景总数正3/负2，不能误报模型总1。私有desktop-tools-live-results.json与四events文件/真实截图留档。
- 工具验收结束实际CAS恢复租户原字段，version97，原enabled/input/output均false。该版本号只记录本轮快照，不作固定合同。
- 主沿用/e2e-test与/task-review核AC/错误码/隔离/真实GET/cleanup与设计；新文件测试/设施源不改业务鉴权/计量。A最终只读一致性复核无HIGH/MEDIUM代码项，指出旧摘要/计数/执行树及反向AC引用已由主集中修订。DM8/多租户/多副本/设施故障、无Gateway部署、真实容量与回退仍留未执行；最终T132不能标完成。


T204/T205最终主交叉验收PASS：完整单源420行/冻SHA749c8262247196cb869448ca90d3071cd4ac459452fd8ec3dace1d34bc0a1684；主发现能力字段与真实Wire不符，经3RED→9GREEN纠正，主最终actual56PASS（49local+7live）/78.03s。Chat/Responses各非法JSON/重复model/unknown INPUT，以及合法JSON确切33554433bytes上限+1均400 invalid_request、无Backend header、global/scenario0、无账本变化；两轮精确conversation/requestUUID/unassociatedGatewayUUID完整空页，发生在recorder前，故无安全ERROR事件。实际settings恢复原disabled/version111，capabilities可用；verify-scope再次NON_DSH_CONTAINER_IDENTITIES_UNCHANGED。

真实Platform English管理员UI：在审计高级筛选设置Conversation ID为本轮Responses blocked会话、Match recorded=Sensitive word match，点击Search后唯一会话，命中计数1；展开只显示匹配请求（辅助标题被过滤），Overall Matched/Input Passed/Output Matched。打开View check details可见独立DECISION v1与DRAIN v2、同Gateway/Backend各UUID/策略96/rule opaque ID，续读先waiting后fullyread，实际usage ledger80，页面说明不把客户端中断当模型停止。原词与凭据不出现在内容安全事件详情。只读GET未改变租户策略。Japanese因当前APP_CONFIG.disableJa隐藏，未更改客户开关冒三语UI验收。


## 最终镜像与重启后复验

B测试资料提交d5b026557b76bb57af223520c11aeecd4e83473e正常推work120并读回，Drone5625 SUCCESS；业务bisheng树与3cc9de9298无差异，backend COPY包含新测试故镜像更新为151d35b0436825c23dd9c5940300d801e8294bb1c0a75c5798250216991ef0cd，ImageID e5d1403c2e1a95323dffded3858cd088a76a8ac965df186cba799e0cea8587ce，仅109 backend/worker更新；frontend摘要未变。真实Backend进程重启后12条已存在审计四模式4PASS/13.14s，证明此批事实重启可读，不冒丢ACK/并发事务验收。

启动窗口业务读取失败及四模式烟测2PASS后策略teardown503保留原日志；主核最后版本114/自有合成词和提示后CAS恢复115，不覆盖外部编辑。Gateway私有日志确实包含对旧172.31.62.10和新172.31.62.9的连接拒绝，127.0.0.1:17860/health及真实管理APIready后仅同镜像重建指定Gateway刷新连接，受保护capabilities连续三读成功。最终同源四模式烟测4PASS/31deselected/40.27s（post5625-stable-protocol-four），策略正常恢复；不放宽测试/不加模型自动重试。13001/health可被SPA兜底，不能当Backend就绪证据，运维步骤已同步。

最终只读：官方trial许可证2026-11-23/expired=false；原默认模型四组和原审计设置完整值不变；租户原enabled/input/output/custom_words恢复关闭/空；verify-scope再次逐字节确认全部非四目标既有容器身份不变。190/205及完整AC0PASS/30PARTIAL/29NOT_RUN保持；DM8/双租户多副本/容量/设施故障/无Gateway/回退等待实际环境与验收。最后纯features文档提交不改构建上下文，不再次重建服务。


## 2026-10-27：关闭采集边界与审计说明（T206–T211）

用户明确要求：敏感词与审计采集均关闭时不再采集新请求；敏感词开启、审计关闭时仍保留安全摘要，并在审计界面常驻解释。新增 AC-60、AC-61，既有 AC 与编号不变。

- Gateway 单一生产改动：DshSafetyRequestManager 仅在冻结策略至少一个检查方向开启时创建 Recorder。策略关闭时不写新 Outbox，backend 仍独立按 OFF/METADATA/CONTENT 工作；不增加 Gateway 对审计开关的感知。旧事件补报、请求入站快照、模型鉴权、额度和真实计量不变。
- Platform：采集状态下方始终显示 collectionHint，管理员未展开设置或只读用户也可见；通过 aria-describedby 关联状态栏。三语同义，原 modeHint 不再声称关闭采集会停止全部请求摘要。复用相邻辅助文字布局，无新组件或设计样式。
- 未修改 backend 业务代码、SQL/DDL、凭据、客户端、其他工作区或部署环境；本轮不删除历史事件和记录，不暂停积压投递。

| 验证 | 实际结果 |
|---|---|
| Gateway 新契约 RED | 两协议 × 流式/非流式 4 项均因仍写 Outbox 失败；原正文透传和单次调用断言保留 |
| Gateway 定向 GREEN | RequestManager / RoutingFilter / OutboxService / Dispatcher：107 通过 |
| Gateway 全量 | Maven Java 17 离线执行，906 项：896 通过、10 跳过、0 失败/错误；跳过项均为 DshSafetyDatabaseIntegrationTest 的真实数据库验收 |
| 常驻说明 RED → GREEN | 新增三种模式 × 可配置/只读 6 项先失败；修复后审计模式及相邻 4 文件 59 通过 |
| DSH 全部前端回归 | 25 文件、258 项全部通过 |
| 类型检查 | src/frontend 下 pnpm typecheck 通过，包括两应用及 file-viewers |
| lint | 本次两个 UI 文件精确检查通过；workspace pnpm lint 被 Platform 原有 95 项错误阻断，均不在修改文件，未修改抑制清单，不标全量通过 |
| i18n | pnpm check-i18n、pnpm locales:check、三语 JSON 校验通过 |
| 生产构建 | pnpm build:platform 通过；构建仅给出原有体积提示 |
| 架构和差异 | 两个修改 UI 文件 arch-guard 无违规；两库 schema、接口和数据权限未改变；两仓 git diff --check 通过；AC 1–61 定义/任务追溯完整 |

任务自审：T206/T208 的旧断言更改来自上述用户新契约，不放宽模型交付、调用次数和安全命中测试。T207 的唯一采集闸门在每请求固定策略下，不影响已创建 Recorder 的收尾和补报；T209 说明不依赖额外请求，也不改变任何设置值或可配置权限。T210/T211 三语键完整。架构分层、文件归属、依赖配对、信息保护、设计同步均 PASS；全量 lint 的既有错误和未执行的真实数据库/部署验收单列保留。

本轮本地验证日志：/private/tmp/dsh-audit-disabled-{gateway-red,gateway-green,gateway-full,frontend-red,frontend-green,frontend-dsh,typecheck,target-lint,lint,i18n,locales,platform-build}.log。没有使用 SQLite 或 mock 代替真实 MySQL/DM8 验收；现有定向业务测试使用既有传输/SQL 端口夹具，结果仅表示本地回归。


本地组件显示核验：在仅监听127.0.0.1的临时预览中挂载实际 ModelAuditMode，使用本轮生产构建CSS及真实三语资源、固定OFF的API夹具。Chrome已确认中/英/日说明在未展开配置时可见；中文已保存组件截图。该证据只覆盖组件显示，不代表109环境已部署、真实接口端到端或窄屏验收。预览与应用登录相隔离，没有修改任何部署环境。

### T206–T211 任务自审结果

| 任务 | 架构分层 | 命名 | 序列化 | 数据库 | 前端约定 | 信息保护 | 设计同步 | 文件/配对/依赖 |
|---|---|---|---|---|---|---|---|---|
| T206 测试 | N/A | PASS | N/A | N/A | N/A | PASS | PASS | PASS：单测试文件，4项RED后GREEN |
| T207 实现 | PASS | PASS | PASS：事件格式未改 | N/A | N/A | PASS | PASS：design §4.7 | PASS：仅Manager；T206已通过 |
| T208 测试 | N/A | PASS | N/A | N/A | PASS | PASS | PASS | PASS：单测试文件，6项RED后GREEN |
| T209 实现 | PASS | PASS | N/A | N/A | PASS | PASS | PASS：design §4.10 | PASS：仅Mode；T208/T210/T211已通过 |
| T210 三语 | N/A | PASS | PASS：JSON | N/A | PASS | PASS | PASS | PASS：中/英两文件、键一致 |
| T211 三语 | N/A | PASS | PASS：JSON | N/A | PASS | PASS | PASS | PASS：日文单文件、键一致 |

结论：六项任务本身 PASS；workspace完整lint为既有问题记录，真实数据库与部署未执行，不计为本轮通过。


## 2026-10-27 Wave45：统一请求编号（T212–T218）

### 范围和存储边界

用户授权 Gateway/ backend 统一请求编号、补测试并同步设计，本轮明确不提交、不推送。B 在干净 e59b249a3、G 在干净 c999f9bf 上各创建 `codex/dsh-unified-request-id`；保留其他工作树，没有执行仓库级 stash/reset/restore/clean。没有修改前端、Desktop、数据库结构、真实数据或109部署。

Gateway 仍为每次请求生成独立 UUID，Proxy 用显式 UUID 参数在 hop-by-hop 过滤后覆盖客户端头；客户端重复 X-Request-ID 及 Connection 指定该头均不能控制实际编号。Manager 在发起转发前设定 backend_request_id/forwarded；连接失败或响应头前取消仍可投影外部摘要。backend DshRoute 只实现通用 UUID 复用，不读取 Gateway 配置、不新增网络调用，模型准入和计量代码不改。无 Gateway、缺失/非法/零 UUID/多值头仍生成自己的编号。旧 backend 明确返回不同有效编号时兼容实际模型编号，缺失/非法/零 UUID/多值响应不抹掉预分配编号。

事件明细仍存 `dsh_content_safety_event`；有安全摘要的请求仍存 `dsh_model_audit_request`。按会话字段进入会话记录或未关联请求；只有事件而无法安全关联请求的历史/冲突数据仍从未关联检查入口查看。分配 ID 或尝试发送不能证明模型执行，外部 `model_entered`/结果/用量保持未知，后到原生记录沿现有校验升级，不创建假 `dsh_model_call`。两开关都关闭时的零采集规则不变。

### 验证命令与结果

以下命令 B 从 src/backend 运行，使用已有 Python3.11 环境 `/Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python`，`config=/private/tmp/dsh-credit-limit-fix-20261027/test-config.yaml`、`PYTHONDONTWRITEBYTECODE=1`。G 使用现有 Java17 `/private/tmp/f111-gateway-tools/jdk-17.0.21+9/Contents/Home` 与 Maven3.9.9，不改锁定依赖。

| 检查 | 命令/方法 | 结果 |
|---|---|---|
| 新 backend HTTP/仓储测试 | `pytest -q -p no:cacheprovider test/dsh/test_unified_request_id.py`（并入下列组合） | 20项新增覆盖；最初7个有效反例确认旧实现不复用ID，另2个Responses夹具非法input先纠正为现有消息列表契约，再转GREEN |
| backend 相关回归 | `pytest -q -p no:cacheprovider test/dsh/test_unified_request_id.py test/dsh/test_content_safety_merge.py test/dsh/test_content_safety_native_writer.py test/dsh/test_model_audit_request_id.py test/dsh/test_models_api.py test/dsh/test_native_responses_middleware.py -k 'not usage_selected_model_cannot_borrow_another_allowance' --tb=short` | **81 PASS / 1 deselected**；1.42s |
| 既有失败对照 | 不排除上述case时，旧test_models_api中的policy SimpleNamespace缺monthly_token_limit，AttributeError；新进程读取`git show HEAD:src/backend/bisheng/dsh/api/responses.py`并加载原DshRoute后单独运行同一case | 同一 AttributeError；证明该失败在HEAD基线存在，本轮未修改用量业务或放宽原断言。排除仅用于清楚报告本轮通过集合，不宣称整个backend回归全绿 |
| Gateway 定向 | `mvn -o -q -Dtest=DshModelProxyClientTest,DshSafetyRequestManagerTest,DshModelRoutingFilterTest,DshContentSafetyFilterTest,DshRequestTelemetryTest,DshSafetyRoutingConfigurationTest test` | 初轮172 PASS；自审追加响应头前主动取消、多值/零UUID后纳入完整回归 |
| Gateway 完整 | `mvn -o -q test` | **902 PASS / 10 SKIP / 0 FAIL / 0 ERROR**，912 cases；Manager39项通过。SKIP为原真实双库集成，没有用mock替代 |
| 两仓实际回环HTTP | `/private/tmp/dsh-unified-request-id/run_probe.py`：真实Java DshModelProxyClient→随机127.0.0.1端口上的实际Python DshRoute/模型服务/原生协议adapter | **Chat流式1 PASS + Responses流式1 PASS**；供应商/鉴权/额度是合成fixture。backend准入及结算4条事件的request_id/trace_id与Gateway生成ID一致，2个SUCCEEDED；不冒充真实部署E2E |
| Ruff | `ruff format --check --no-cache .../responses.py .../test_unified_request_id.py`、`ruff check --no-cache`同两文件 | PASS |
| 架构和差异 | `bash scripts/arch-guard.sh`逐个修改Python文件；两仓`git diff --check`；设计引用核验 | PASS；无新增分层违规、无章节重编号 |

本地日志：`/private/tmp/dsh-unified-request-id-backend-pass.log`、`/private/tmp/dsh-unified-request-id-backend-baseline.log`、`/private/tmp/dsh-unified-request-id-gateway-full.log`；跨仓合成证据与临时运行器在 `/private/tmp/dsh-unified-request-id/`。运行器退出后已停止其自有backend进程；全部凭据、内容和ID为合成值，没有访问109或输出真实Token。

### Task Review（按仓库 /task-review，主agent自审）

| 任务 | 文件范围 | 配对/依赖 | 结果 |
|---|---|---|---|
| T212 | 新增单一test_unified_request_id.py，HTTP透传/真实Chat执行/仓储投影/拒绝准入边界 | 覆盖AC-62、AC-63；20项新增测试通过 | PASS |
| T213 | 仅responses.py请求ID解析与DshRoute赋值 | T212已通过；没有Gateway配置、身份或计量变更 | PASS |
| T214 | ProxyClientTest、RequestManagerTest；真实回环收到请求未发头即断开、头前主动取消、正常回显及旧ID兼容 | AC-62、AC-63；正常正文不重编码、一次调用/订阅断言保留 | PASS |
| T215 | ProxyClient、RequestManager；显式UUID、转发前固定编号、响应UUID安全选择 | T214通过；缺失/非法/多值/零UUID回退已覆盖；客户端取消释放物理连接 | PASS |
| T216 | 两过滤器test；只更新Proxy调用及verify的UUID参数 | T215通过；原鉴权、路由和正文断言保留 | PASS |
| T217 | RoutingConfigurationTest、RequestTelemetryTest；只更新调用UUID参数 | T215通过；原装配/遥测回归通过 | PASS |
| T218 | B本记录及G验证记录；spec/design/tasks同步 | T213、T215、T216、T217通过；本地证据与未执行项分开 | PASS_WITH_NOTES |

七项检查：架构分层PASS；命名及AC标注PASS；序列化PASS（保持既有OpenAI兼容DSH信封，不套通用平台响应）；数据库N/A（没有生产DDL或SQL写法变更，沿现有租户/身份校验）；前端N/A；信息泄漏PASS；设计同步PASS（spec新增AC-62、AC-63，design数据流、关联和对外编号契约均已更新）。T218注记为HEAD既有用量fixture失败与真实环境未验，并非本轮业务失败。

没有进行真实MySQL/DM8本轮验收、109镜像或客户端联调、完整跨租户/故障/容量测试及总体T132审查，不据本地HTTP或SQLite仓储测试勾选原15项待验任务。统一编号也不能修复已丢失的历史conversation_id，滚动升级中旧backend替换ID且响应丢失仍无法自动合并到其实际模型记录。当前 **203/218**，仅本轮T212–T218新增勾选。


## 2026-10-27 Wave46：移除未关联检查界面（T219–T224）

用户明确要求“界面上去掉未关联检查功能，仅保留数据库以供debug排查定位”。该变更由用户直接确认，覆盖前版AC-63中独立界面兜底的取舍；spec新增AC-64，design的数据归并、前端职责和查询消费者均已同步。继续在两仓既有未提交分支上工作，不提交、不推送、不部署。

### 改动与边界

- ModelAuditRequests 以原 tenant/caller scope key 直接挂载原请求页，删除 ModelAuditViews 入口按钮、隐藏检查页、访问状态和页面缓存。
- 删除 UnassociatedSafetyEvents.tsx（329行）、getUnassociatedSafetyEvents 前端封装及 ContentSafetyEventQuery 专用类型；生产前端没有这些名称或独立未关联事件取数调用残留。
- zh-Hans、en-US、ja 同步删除专属标题/说明/筛选提示和两个专属UUID/身份校验文案，共五个键；保留共用关联状态、31天范围校验及请求检查详情文案。
- 会话记录、未关联请求、请求明细以及请求内ContentSafetyDetails保留。未关联请求仍查询请求摘要的association_status=UNASSOCIATED，与被移除的未关联检查事件视图不同。
- 本轮业务改动仅8个Platform文件；没有修改backend事件接收、投影、数据库模型、迁移、保留策略或实际数据，dsh_content_safety_event继续保存debug事实。前轮统一请求编号的未提交改动完整保留；其他工作树不变。

### 实际验证

| 检查 | 命令/方法 | 结果 |
|---|---|---|
| 配对反例 | `pnpm --dir src/frontend/platform exec vitest run src/pages/SystemPage/dsh/ContentSafetyDetails.test.tsx`，实现前 | **3 RED / 25 PASS**；groups/unassociated/requests均仍出现旧入口，三项均在预期“不应存在按钮”的断言失败 |
| DSH组件回归 | `pnpm --dir src/frontend/platform exec vitest run src/pages/SystemPage/dsh` | **257 PASS / 25 files**，8.28s；覆盖三个入口移除、无独立查询、未关联请求条件保留、已有请求检查详情/会话/筛选/原文等 |
| workspace类型 | frontend根目录`pnpm typecheck` | PASS；Platform610 strict文件、Client1467 strict文件、共享file-viewers均通过 |
| 目标lint | Platform目录`pnpm exec eslint src/pages/SystemPage/dsh/ModelAuditPanel.tsx src/pages/SystemPage/dsh/ContentSafetyDetails.test.tsx src/controllers/API/dshContentSafety.ts src/types/dshContentSafety.ts --suppressions-location eslint-suppressions.json` | PASS；涉及文件无既有suppression条目，无新增豁免或strict-ignore |
| 完整lint | frontend根目录`pnpm lint` | **95项既有错误**；日志8个诊断文件逐一用`git diff --quiet HEAD -- <files>`核对均未修改，目标文件单独lint全过；未改无关文件、规则或suppression |
| 文案 | frontend根目录`pnpm check-i18n`、`pnpm locales:check` | PASS；三语键对齐，无新增drift，生成文案未改 |
| 生产构建 | frontend根目录`pnpm build:platform` | PASS，17.21s；既有大chunk warning保留。没有发布或部署产物 |
| 范围与结构 | 原组件已删除、生产导入/封装/类型无残留、三语专属key删除、原共享key保留；arch-guard、`git diff --check` | PASS；ModelAuditPanel525行、ContentSafetyDetails测试405行，均低于600行 |

日志：`/private/tmp/dsh-remove-unassociated-check-{red,tests,typecheck,lint,target-lint,i18n,locales,build}.log`。界面验证为实际组件DOM断言和生产构建；没有将其表述为109已更新或真实浏览器/客户端验收。数据库没有执行查询、删除或修改命令。

### Task Review

| 任务 | 类型/文件范围 | 配对/依赖与结果 |
|---|---|---|
| T219 | 测试；ContentSafetyDetails.test.tsx | AC-64三反例先RED后GREEN；删除废弃页面专属测试，保留请求内详情及过滤测试；PASS |
| T220 | 实现；ModelAuditPanel.tsx、明确删除的UnassociatedSafetyEvents.tsx | T219通过；原scope key隔离保留，未增加样式/组件/状态库；PASS，组件缺失是预期删除 |
| T221 | 实现；API/dshContentSafety.ts、types/dshContentSafety.ts | T220通过；独立查询/类型无使用点，保留请求内事件API和DTO；PASS |
| T222 | 实现；zh-Hans/bs.json、en-US/bs.json | T220通过；仅五个专属键删除；PASS |
| T223 | 实现；ja/bs.json | T222通过；与中英文同键删除，i18n检查通过；PASS |
| T224 | 文档/本地验收；本记录 | T221–T223通过；本轮spec/design/tasks同步，记录full lint既有失败和未部署范围；PASS_WITH_NOTES |

七维检查：架构PASS（组件取数仍通过封装，未新增store HTTP）；命名PASS；序列化N/A（保留现有响应及DTO）；数据库N/A（无本轮生产数据库改动）；前端PASS（无硬编码中文/新库/新样式，实际类型与目标lint通过）；信息泄漏PASS（只用合成测试，无凭据）；设计同步PASS（AC-64及前端职责/数据保留明确）。本轮新增6项完成，当前 **209/224**；既有15项双库/完整现场/容量/最终门禁不勾选。未提交、未推送、未部署。


## 2026-10-27 Wave47：移除请求明细视图并展示命中词（T225–T243）

用户明确要求“请求明细去掉，把相关的跳转也去掉”“命中后展示具体的敏感词”。spec新增AC-65、AC-66，design同步存储、协议、权限、旧数据与发布顺序。该记录覆盖Wave46中保留请求明细的旧取舍；继续保留此前统一请求编号和移除未关联检查界面的未提交改动。不提交、不推送、不部署。

### 实现边界

- 审计只保留会话记录、未关联请求两个主视图；移除请求明细标签、跨视图跳转/返回状态和深层树继续跳转。树达到既有限制时显示普通说明。单条请求展开、原文和检查详情保留，未删除请求审计数据。
- Gateway按本次请求冻结的CompiledPolicy将命中rule_refs映射为配置词快照；不读取命中后的新配置，不保存词周边正文。Observation深拷贝且toString不输出词值；既有客户端阻断消息和普通日志不增加词值。
- 既有schema_version=1事件增加可选matched_words对象，包含input/output两个必需数组；允许旧字段缺失/null。两阶段合计至多20词，每词非空白、合法UTF-8、至多256个Unicode码点、阶段内不重复；非空方向必须BLOCKED。前后端和Gateway均校验边界。
- backend的dsh_content_safety_event增加可空JsonType列，接收、投影事实一致性与已授权详情元数据均接入；不增加主列表JOIN或N+1查询，不改变用户/租户鉴权、模型准入和计量。迁移f111_matched_words基于实际唯一旧head f111_dsh_content_safety，仅幂等DDL，不回填旧数据，拒绝破坏性downgrade。
- 检查详情按输入/输出显示命中词，采用React文本渲染；三语文案同步。旧记录没有词快照时显示“该检查记录未保存命中词，无法还原。”，不拿当前词库反推。命中词仍受既有请求详情权限保护。
- 必须先完成迁移并升级**全部backend实例**再升级Gateway；旧严格DTO会拒绝未知字段。回退先回退Gateway，保留backend新增列及既有事实。Gateway继续使用既有MEDIUMTEXT/CLOB事件载荷，无新DDL。

### 实际验证

| 检查 | 命令/方法 | 结果 |
|---|---|---|
| backend配对反例 | 新test_content_safety_matched_words.py在实现前运行 | 5项预期RED / 11PASS；原DTO拒绝新字段、原模型缺属性；实现后16PASS |
| backend定向 | config为隔离test-config.yaml，Python3.11，pytest -q -p no:cacheprovider：新词值/仓储/合并/查询/API/native writer/新迁移/单head共9文件 | **170PASS**，4.95s；命令及日志见下 |
| backend扩大回归 | 当前test/dsh与相同命令/配置的只读git archive HEAD基线对照；共同排除此前已确证旧用量fixture case | 当前16FAIL /1466PASS /227SKIP /1 deselected /102ERROR；HEAD16FAIL /1428PASS /227SKIP /1 deselected /102ERROR。逐项Counter对照全部FAILED/ERROR case ID及次数完全相同；新增38PASS=统一编号20+词值16+迁移2。不宣称全量通过，不扩大修复旧失败 |
| Gateway完整 | Java17、Maven3.9.9，mvn -o -q test | **905PASS /10SKIP /0FAIL /0ERROR**，915 cases；10项原真实双库测试未执行 |
| Gateway生产mapper及跨语言 | 新DshMatchedWordsTest用SpringCustomConfig实际ObjectMapper；导出实际Java事件，再由真实Python ContentSafetyEvent.model_validate_json解析 | 3PASS；input合成词与output空数组一致，生产null序列化不会破坏协议；没有模拟拼接事件 |
| Platform组件 | pnpm --dir src/frontend/platform exec vitest run src/pages/SystemPage/dsh | **269PASS /25 files**，9.60s；覆盖仅两入口/无跳转/树限制、过滤保留、方向词值/文本转义/旧数据及严格API解析 |
| 类型、文案和目标lint | frontend根pnpm typecheck、pnpm check-i18n、pnpm locales:check；12个保留的修改TS文件单独ESLint | PASS；Platform610、Client1467 strict及共享文件通过，三语键一致，无新增豁免 |
| 完整前端lint | frontend根pnpm lint | 95项既有错误；8个诊断文件逐项git diff --quiet HEAD确认未修改。没有修改无关文件或规则 |
| Platform生产构建 | frontend根pnpm build:platform | PASS，16.67s；保留既有大chunk warning，构建产物未发布 |
| Ruff/架构 | 8个修改Python源和测试的ruff format --check与ruff check；修改业务源逐项arch-guard | PASS；没有新增分层违规 |
| 迁移结构 | alembic heads、离线重复upgrade/旧NULL/downgrade拒绝、既有JsonType双方言编译 | 单head f111_matched_words；迁移测试2PASS。静态方言检查不冒充DM8实测 |
| 实际隔离MySQL | 本机Docker socket已核对；新随机名称/127.0.0.1随机端口/随机合成凭据/带任务label的mysql:8.0独立容器，mysql_check.py调用真实迁移两次 | **MySQL8.0.46 PASS**：旧NULL保留、可空原生JSON、中英文/HTML样式/256emoji词往返、拒绝破坏性回退。退出后仅移除本次自有容器及匿名卷，label查询确认无残留；其他容器和109不变 |

完整定向backend命令：在src/backend目录，以既有Python3.11独立环境执行：

```sh
config=/private/tmp/dsh-credit-limit-fix-20261027/test-config.yaml PYTHONDONTWRITEBYTECODE=1 /Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest -q -p no:cacheprovider test/dsh/test_content_safety_matched_words.py test/dsh/test_content_safety_repository.py test/dsh/test_content_safety_merge.py test/dsh/test_content_safety_queries.py test/dsh/test_content_safety_api.py test/dsh/test_content_safety_native_writer.py test/dsh/test_matched_words_migration.py test/database/test_alembic_single_head.py --tb=short
```

证据：`/private/tmp/dsh-matched-words-backend-final.log`、`/private/tmp/dsh-matched-words-backend-full.log`、`/private/tmp/dsh-matched-words-backend-head-baseline.log`；Gateway完整和生产mapper日志`/private/tmp/dsh-matched-words-gateway-full.log`、`/private/tmp/dsh-matched-words-gateway-production-mapper.log`；实际事件和MySQL脚本/回执`/private/tmp/dsh-matched-words/`（全部合成值）；前端`/private/tmp/dsh-request-view-words-{ui-final,typecheck-final,target-lint-final,lint,i18n,locales,build-final}.log`。HEAD对照来自`git archive`到本次独立临时目录，没有checkout/reset已有工作树。

### Task Review（主agent逐文件自审）

| 任务 | 范围/依赖核对 | 结论 |
|---|---|---|
| T225 | ContentSafetyDetails/Tree测试；AC-65、AC-66入口/无跳转/词值/旧数据反例及最终组件回归 | PASS |
| T226 | Panel/Tree只保留两视图和深度提示，无相关跳转残留；T225通过 | PASS |
| T227 | Card/Group移除onNavigate透传，保留单请求展开；T226通过 | PASS |
| T228 | Panel/Filters测试改为真实未关联请求条件，断言association_status保留；T226通过 | PASS |
| T229 | Card测试删除废弃callback fixture，原显示/展开断言保留；T227通过 | PASS |
| T230 | 新词值与Manager测试；冻结版本、深拷贝、输入/输出决策和drain、隐私和边界；完整回归通过 | PASS |
| T231 | MatcherCache/Outbox只从冻结规则还原词并校验持久化，无新配置RPC；T230通过 | PASS |
| T232 | Manager构建方向快照，原请求编号/计量边界保留；T231通过 | PASS |
| T233 | 新backend词值测试16项，旧协议和不合法值拒绝覆盖 | PASS |
| T234 | DTO/ORM严格可选契约及可空字段；T233通过 | PASS |
| T235 | repo append/projection同步字段与JSON事实比较，原wire hash不变；T234通过 | PASS |
| T236 | 请求事件metadata白名单，原鉴权/租户过滤不变，主列表不变；T235通过 | PASS |
| T237 | 新迁移及测试，唯一head/幂等/旧NULL/拒绝降级；T234通过，真实MySQL补验通过 | PASS |
| T238 | API/types兼容缺失/null，新值数量/状态/字符/重复校验；T225、T236通过 | PASS |
| T239 | 仅显式打开检查详情后显示文本和历史缺失提示；T238通过 | PASS |
| T240 | 中英文同键增删，无硬编码中文；T226、T239通过 | PASS |
| T241 | 日文同键同义，i18n检查通过；T240通过 | PASS |
| T242 | 自有实际MySQL与真实Java→Python事件契约通过；DM8和部署E2E未冒充通过 | PASS_WITH_NOTES |
| T243 | 两仓验证记录及spec/design/tasks一致，失败与未执行项如实保留 | PASS_WITH_NOTES |

七维：架构PASS；命名及AC标注PASS；序列化PASS；数据库PASS（本轮新增迁移真实MySQL，DM8待验）；前端PASS（复用原组件，无新库/样式、无硬编码中文、无新strict-ignore，维护文件均≤600行）；信息泄漏PASS（只有配置命中词进入受权详情，无正文上下文/凭据/普通日志泄漏）；设计同步PASS。原完整现场/双库/容量/最终特性审查仍未完成，本轮不是全feature最终验收。

T225–T243共19项完成，当前**228/243**。原15项T119、T120、T121、T122、T123、T124、T125、T126、T127、T128、T129、T130、T131、T132、T180保持待验；Linux DM8按用户决定继续待验。未执行真实浏览器视觉验收、109部署或客户端联调；DOM测试和构建不替代这些验收。未提交、未推送、未部署。


## 2026-10-27 授权发布与验收脚本补齐（T244）

用户已明确授权本轮提交、合并最新feat/bisheng-work-120-main并推送、CI构建和仅109 DSH13001部署，覆盖前述仅本轮不提交的限制。合并最新dfadd7ab3后B190PASS、G905PASS/10真实DB SKIP、前端269PASS；完整frontend lint/typecheck/i18n/locales和Platform生产构建PASS（18.83s），最新目标分支已修复旧95项lint问题，历史证据保持不变。

发布前自审确证既有test_content_safety_recovery_e2e.validate_event_shape使用严格旧字段白名单；新详情会固定返回matched_words，即使旧数据NULL也会被旧验收脚本错误拒绝。T244仅在该脚本增加可选字段严格校验，保留旧缺失/null，拒绝词值越界、错误阶段、重复/Unicode及其他额外字段；新增test_content_safety_recovery_contract.py共11项。相关最终组合**201PASS**（3.61s），Ruff通过，业务文件未增加修改。文件范围、配对、边界、泄漏与设计自审PASS。原全特性15项待验不变，当前229/244。

本地本轮发布证据目录/private/tmp/dsh-id-audit-release-20261027。CI SHA/digest及实际部署、权限模型维护和现场验收结果继续单独记录，不以本条预告冒充部署完成。
