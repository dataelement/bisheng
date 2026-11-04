# F118 实施验证记录

- **Status**: IN_PROGRESS / NOT_VERIFIED
- **Date**: 2026-11-03—2026-11-04
- **验证时的代码状态**为 `codex/118-kunlian-sso-user-sync` 上基于 `5a359d8e6` 的工作树快照。两仓库的本地提交见 [配对代码状态](./release-readiness.md#配对代码状态)。完成 T001—T077、T081、T083，共 79 / 83；T078—T080、T082 四项未完成。
- 用户已明确授权实施。此记录不表示新 SSO 已可使用，不允许解除外部条件或正式启用。

## 当前结论（2026-11-04）

对照规格的本轮审查已完成，五类运行问题和一处设计快照漂移已修复，见 [code-review.md](./code-review.md)。整体仍为 **NOT_READY / PARTIAL**。当前相关回归：后端 331 passed／5 skipped（E-032）、网关 75 passed（E-033）、Client 40 passed 及前端 lint／typecheck（E-034）；Platform 122 项及三语构建校验复用未变化的 E-029。后端使用 SQLite／受控传输，网关包含本机模拟 HTTP，均不能宣称真实 E2E 通过。五项真实用例仍待执行，不计通过。

剩余 T078（真实存储跨实例）、T079（真实 Worker／权限 API E2E）、T080（两 SPA／昆联／传播时效）未完成。T078／T079 的四个指定文件现已补齐，真实执行结果为 NOT_RUN；参数、操作侧协作和命令见 [live-test-runbook.md](./live-test-runbook.md)。T080 清单与 T082 发布说明已准备，但依赖和环境未闭合，T082 保持未完成。当前未取得可执行专属环境信息，没有连接外部环境。

当前 AC 矩阵中 PARTIAL 均表示本地证据通过、整体验收尚未通过。E-032 包含本特性后端及相关旧通道回归，E-033 为网关，E-029 为 Platform／三语，E-034 为当前 Client 和前端静态门禁；一条证据可覆盖多个 AC。

| AC | 当前本地证据 | 尚缺的独立边界 | 整体状态 |
| --- | --- | --- | --- |
| AC-01 | E-033、E-029、E-032：登录、绑定、入口／目标约束 | 真实 OP＋已授权目标页面 | PARTIAL |
| AC-02 | E-033、E-032：签名／绑定／消费／拒绝 | 真实浏览器跨节点重放 | PARTIAL |
| AC-03 | E-032：稳定身份与 Owner fence | 双 DB 并发及真实同名／更名 | PARTIAL |
| AC-04 | E-029、E-032：待目录拒绝与补同步 | 真实 Worker 补齐后重新登录 | PARTIAL |
| AC-05 | E-032：完整分页、归属及发布 | 真实全租户目录与 DB | PARTIAL |
| AC-06 | E-032：旧目录保留、恢复与 fence | 两实例锁／事务竞争 | PARTIAL |
| AC-07 | E-032：每次 HTTP／WS SQL＋内省 | 真实内省、到期与跨节点失效 | PARTIAL |
| AC-08 | E-029、E-032：逐动作与旧来源分流 | 真实浏览器复用连接／直连反例 | PARTIAL |
| AC-09 | E-032：状态、epoch 与旧会话拒绝 | 真实传播窗口及恢复流程 | PARTIAL |
| AC-10 | E-033、E-029、E-032：先撤销、票据、调用者 | Redis／SQL 跨实例及真实 OP | PARTIAL |
| AC-11 | E-033、E-029、E-032：到期／换码／落点 | 实际 AT 五分钟到期与重新授权 | PARTIAL |
| AC-12 | E-032：原 F048 调用／执行上下文 | 非管理员 A／B 真实对象动作与 OpenFGA | PARTIAL |
| AC-13 | E-033、E-029、E-032：凭据隔离／日志探针 | 真实反代／浏览器／外围日志 | PARTIAL |
| AC-14 | E-033、E-029、E-032：旧通道相关回归 | 真实旧身份全链路对照 | PARTIAL |
| AC-15 | E-032：角色／组织引用及 opaque version | 对照上游实际字段与状态语义 | PARTIAL |
| AC-16 | E-032：未知／冲突／失败不发布 | 真实目录数据及双 DB | PARTIAL |
| AC-17 | E-032：当前绑定、成员／租户／本地资格拒绝 | 真实 Owner／权限与跨节点 | PARTIAL |
| AC-18 | E-032：人工 Grant 保留、旧会话不恢复 | 真实停用恢复及人工撤权对照 | PARTIAL |
| AC-19 | E-032：凭据／范围／网络失败分类 | 真实只读 Key／出口／错误合同 | PARTIAL |
| AC-20 | E-032：外部事实隔离、不自动授管理权 | 多租户实际目录／非管理员权限 | PARTIAL |
| AC-21 | E-033、E-029、E-032：本地失效与远端结果区分 | OP 确认／取消／错回跳 | PARTIAL |
| AC-22 | E-029、E-032：无默认菜单或对象授权 | 两端真实未授权／人工授权对照 | PARTIAL |
| AC-23 | E-032：Owner 回执／来源／资产与 Grant 保留 | 双 DB 竞争、真实资产不变 | PARTIAL |
| AC-24 | E-032：未初始化／空／失败／诊断区分 | 真实 Worker 状态及恢复观测 | PARTIAL |
| AC-25 | E-033、E-029、E-032：关闭／依赖失败不降级 | SQL 禁用跨节点与旧通道实测 | PARTIAL |
| AC-26 | E-033、E-032：持久事实及受控实例替身 | MySQL／DM8／Redis 真实两实例 | PARTIAL |

外部执行步骤见 [e2e-browser-checklist.md](./e2e-browser-checklist.md)，配对状态、启停顺序及回退限制见 [release-readiness.md](./release-readiness.md)。本文后续各批次是历史快照，不以早期未实施描述覆盖当前结论。spec 中的初始验证表保留规格确认时快照，实际执行状态以本记录为准。

## 首批交付（历史快照）

八张控制面表、ROOT 范围字段／时间戳／唯一性及模型发现，严格 DTO 与 application Protocol，默认关闭的配置及配置就绪判定，十类昆联错误与安全公开响应、三语源文案，以及可控时钟／分页故障测试辅助。没有新增业务路由，没有执行数据库建表、真实同步、账号修改或授权变更。网关未改动。

## 实际证据

| ID | 命令／步骤 | 结果与范围 |
| --- | --- | --- |
| E-001 | uv venv --python 3.11 src/backend/.venv；在 backend 执行 uv sync --frozen --python .venv/bin/python | PASS，独立 Python 3.11.14 环境，不更改 pyproject／uv.lock；原工作树 3.10 环境不复用 |
| E-002 | Python 声明检查：枚举八张模型，使用 SQLAlchemy MySQL dialect 编译 CreateTable，检查 tenant_id／create_time／update_time；默认开关和严格未知字段检查 | PASS；为隔离数据库包启动而使用包加载替身。仅为声明证据，不代表真实模型启动／建表／事务／DM8 通过 |
| E-003 | Python 就绪断言：未登记陈旧上限、workspace、状态语义时拒绝；完整 HTTPS 测试配置可通过配置门禁；单租户及错 Origin 回调拒绝 | PASS；新方法缺失的预期失败后实现。只评估配置前置条件，不代表目录／投影／上游就绪 |
| E-004 | Python 断言：未知身份字段、空 AT／ID Token 拒绝，repr／JSON／ValidationError 隐藏测试敏感值；十类错误的真实 HTTP、JSON、SSE 及 str 不输出底层异常；时钟推进和分页异常；三语共 30 个键 | PASS；发现空 AT 校验与继承 JSON 异常输出问题后修复再通过 |
| E-005 | backend：临时空测试 YAML 注入 config 环境变量；.venv/bin/python -m pytest test/sso/test_sso_payload_schemas.py test/sso/test_sso_hmac_auth.py -q | PASS，21 passed；只证明旧 DTO／HMAC 相关回归，不是昆联业务验收 |
| E-006 | .venv/bin/ruff check／format 受影响 Python；逐文件 bash scripts/arch-guard.sh；git diff --check | PASS；架构守卫无违规输出；检查含新增模型、DTO、Protocol 与测试辅助 |

初次 pytest 因工作树无 bisheng/config.yaml 在加载 conftest 时失败，未产生测试结果。随后通过临时仅含空对象的测试 YAML 运行成功，未复制用户配置或使用真实服务凭据。运行中原有第三方弃用提示不作为新业务验证。

语言源文件只新增 19320—19329，保持原键值与顺序；生成物仍由 T077 统一构建，目前不声称前端文案发布完成。

## L1 任务级静态自审

按项目 task-review 的基础设施子集检查；由同一代理自审，不是独立复审。旧清单 DAO 示例以 constitution 的 Repository 规则为准。

| 任务 | 架构／序列化 | 数据／文件范围 | 泄漏边界 | 设计同步 | 依赖／结果 |
| --- | --- | --- | --- | --- | --- |
| T001 | PASS：纯 SQLModelSerializable 模型 | PASS：新表含租户／时间，JsonType／LargeText，core 只登记字符串 | PASS：无明文令牌字段 | PASS：design §4.1／§4.4 | NONE；PASS |
| T002 | PASS：模型不导入服务 | PASS：映射、身份、会话和回执，唯一约束及哈希／密文列 | PASS：不存原始会话引用 | PASS：design §4.4 | T001；PASS |
| T003 | PASS：窄 Protocol 不暴露 ORM | PASS：仅 DTO／application 与机械包标记 | PASS：secret 排除公开序列化及错误输入 | PASS：design §6.4 | NONE；PASS |
| T004 | PASS：仅配置声明／纯就绪判定 | PASS：已有 sso_sync 子命名空间，无运行配置修改 | PASS：秘密为受控引用且 repr 隐藏 | PASS：design §6.6；精确测试 Origin 显式配置，不允许默认 HTTP | NONE；PASS |
| T005 | PASS：不改变旧 BaseErrorCode／处理器 | PASS：19320—19329 当前本地无占用 | PASS：公开输出固定原因，不传播异常 | PASS：design §6.7 | NONE；PASS |
| T006 | N/A | PASS：英文／日文与中文同批源文案 | PASS：无秘密 | PASS：design §6.7 | T005；PASS |
| T008 | PASS：纯测试辅助，无业务实现 | PASS：仅既有 test/sso 下新增辅助 | PASS：只用虚构数据，不访问网络 | PASS：design §7 | T003；PASS |

## 第一批次时的限制（历史记录，当前状态见文首及后续批次）

- T007 未开始：系统 java 命令无默认 JRE，但 Maven 自带 Java 25 可启动。不能以此前系统命令失败认定整个 Java 环境不可用；还需核验 Java 17 编译目标与测试兼容性。
- T009 至 T082 未完成：同步租约／仓储／服务、Owner 投影、可信登录、HTTP／WS 准入、网关、退出和前端交互尚未实施。本批次不构成可用登录链路。
- V-01 至 V-07 的新业务验收均 NOT_RUN；真实 MySQL／Redis／OpenFGA、DM8、昆联凭据及 EXT-01 至 EXT-04 门禁未解除。
- 下一执行批次为 T009→T010 的租约与分页暂存测试先行，同时保留网关 T007 的独立依赖核验。不得跳过测试直接上线。

## 第二批次：目录仓储与全轮编排（T009—T016）

- T009 先运行得到 5 个预期失败（本特性仓储尚未实现）；T010 后 5 passed。T011 扩展后 9 个方法缺失失败、原 5 项仍通过；T012 后 14 passed。
- T013 先得到 11 个目录客户端缺失失败；T014 与仓储冲突案例扩充后 28 passed。T015 先得到 5 个目录服务缺失失败、原仓储 17 项通过；T016 后两文件共 33 passed。均使用 Python 3.11、临时空测试 YAML、真实 SQLite SQL 与 MockTransport／受控分页，不连接实际服务。
- 执行命令（cwd src/backend）：临时 config 环境变量指向仅含空 JSON 对象的 YAML；`.venv/bin/python -m pytest test/sso/test_kunlian_directory.py test/sso/test_kunlian_directory_client.py -q --disable-warnings`。
- 实现：连接行锁、租约 fencing、固定 Key 版本／page_size／游标续接、完整发布事务、不可回退 auth_epoch、稳定身份指纹与显式映射 CAS；独立目录 HTTP 客户端、有限重试、严格全部字段校验；全轮编排、密文游标、失败持久记录和独立投影状态。
- 目录服务只通过显式注入创建；application 提供窄委托，没有隐式全局客户端和启动网络。尚未接入 Worker 或管理 API，不能宣称调度已运行。
- L1 自审：测试任务 T009／T011／T013／T015 的覆盖及命名 PASS；实现任务 T010／T012／T014／T016 的分层、SQL 所在层、ROOT 作用域、字段／凭据隔离和依赖 PASS；按 constitution 使用 Repository，不采用旧清单 DAO 示例。目录版本、租户和人工授权策略未改变。
- 新 SQL 的锁竞争／跨实例并发、MySQL／DM8、正式凭据与网络，以及全特性 E2E 仍待 T078—T082；SQLite 测试不能替代这些证据。


## 第三批次：持久会话及用户 Owner 投影（T017—T020、T083）

- E-007：backend 定向组合 `test/sso/test_kunlian_session_store.py test/sso/test_kunlian_directory.py test/sso/test_kunlian_directory_client.py test/sso/test_sso_payload_schemas.py test/sso/test_sso_hmac_auth.py`，`pytest -q --disable-warnings`，67 passed、7 warnings。覆盖会话固定期限幂等交接、密文写入失败回滚、SQL 撤销持久化、单次退出票据和目录故障分类；不代表完整准入或真实并发通过。
- E-008：`pytest test/user/test_kunlian_external_identity.py -q --disable-warnings --tb=short`，6 passed、7 warnings。覆盖同名不合并、跨租户分号、改名不换号、来源隔离、人工授权记录保留、同操作重试、旧操作迟到及 User／应用回执同事务回滚。
- E-009：第九张 Owner 状态模型以 MySQL dialect 编译 CreateTable，检查 ROOT／时间／用户外键／fence 声明，PASS；新增 Owner 文件及 application 的 Ruff check／format、逐文件 arch-guard 和 git diff --check 均 PASS。未连接真实数据库，DM8 未运行。
- 用户明确批准补充设计后才新增独立状态表及 T083；不改 User／Tenant 列，无实际建表。F118 持有的源修订与 user Owner 本地 fence 分开，不复用 JWT／DSH 版本作投影栅栏。
- 测试先行偏差：T019 首轮失败来自旧 UserRole 复合自增主键不兼容 SQLite，尚不是有效行为红灯；在检查根因前已写 Owner 草稿。未将这次失败计为有效 TDD 证据。修复夹具后执行实际 Owner 事务测试，并补充同长度修订冲突、旧操作迟到及回执写入故障回滚验证。SQLite 的 UserRole 简化夹具只证明关联记录保留，不证明真实复合主键或权限运行时。
- L1 自审：T017／T019 测试业务结果与错误路径 PASS；T018 ROOT SQL 事务、密文和幂等边界 PASS；T020 user Owner 独立 UoW、不授默认角色、原文复核／操作栅栏 PASS；T083 模型／发现登记／MySQL 声明 PASS。T003 Protocol 改为真实目录命令，移除目录未提供的登录声明依赖。跨实例及双 DB 仍由 T078 验证。
- 当前未完成：T007、T021—T082。新 HTTP／WS、Worker、网关及前端尚未接线，不可用作登录功能；所有真实上游和环境门禁保持未解除。


## 第四批次：IDP 复核与内部信任协议（T031—T034）

- E-010：backend 在临时空 config 下运行 `pytest test/sso/test_kunlian_idp_client.py test/sso/test_kunlian_trust.py test/sso/test_kunlian_directory_client.py test/sso/test_sso_hmac_auth.py -q --disable-warnings --tb=short`，60 passed、7 warnings。新能力缺失时先产生明确失败；客户端完成后修正测试同步／异步上下文混用，所有案例实际执行通过。
- RS256 实签、必要声明／时间／nonce／aud 和 azp／固定租户／workspace 校验，拒绝 none／HS256／错误签名和令牌指定 jku；Discovery 不能重定向登记端点。公钥有限缓存，未知 kid 每个受复用客户端 30 秒内最多刷新一次。
- opaque AT 仅通过 Basic 表单内省，不按 JWT 解析；Basic 对 ID 与 secret 分别表单编码。每次调用均实际请求，不缓存允许决定；超时拒绝且不重试 POST；不携带同步 Key、Cookie 或 Origin。仍是 MockTransport 证据，未访问真实 IDP。
- 新 HMAC 协议使用确定性固定向量，绑定精确 raw body／method／path／key id／timestamp／nonce；先核验再通过 Redis SET NX EX 原子消费 nonce，TTL 121 秒覆盖完整 60 秒双向接受窗口。Redis 故障、重放、来源未通过与 Unicode 签名均拒绝；旧 F014 用例继续通过。
- L1 自审：T031／T033 覆盖和失败路径 PASS；T032 HTTP／秘密隔离、JOSE／端点约束与配置快照 PASS；T034 独立密钥／协议、无载荷日志、原子 nonce 适配器 PASS。四个受影响文件 Ruff check／format，两个实现文件 arch-guard 和 git diff --check 均 PASS。
- 本批次仅提供可注入协议服务。HTTP 对真实网关来源的判定、服务装配及生产客户端生命周期仍待 T040／T046；不以 `source_allowed` 参数或伪 Redis 测试代替真实网络门禁和跨实例证据。


## 第五批次：来源守卫、人工停用与租户 Owner（T021—T024）

- E-011：backend 运行 `pytest test/user/test_kunlian_source_guards.py test/sso/test_sso_cross_source_user.py test/user/test_kunlian_external_identity.py test/tenant/test_kunlian_external_membership.py test/user/test_user_update_tenant_admin_gate.py`，并加入 `test/dsh/test_user_profile_changes.py` 四个 `[sqlite]` 节点，参数 `-q --disable-warnings --tb=short`，43 passed、7 warnings。初次扩大到 DSH 全文件时 40 passed、4 个 external 参数因缺少隔离 DSH_TEST_DATABASE_URL 报环境错误；未配置外部库或执行这些外部参数。后续明确选择 SQLite 节点，不用模糊 `-k not external` 排除包含 external 的新 Owner 文件。
- 注册／普通管理创建不能使用保留 source 或命名空间；资料持久化在原 User 锁下检查真实库来源，并禁止自动 flush 先写入／清空变更历史；原 SSO 的非昆联迁移合同保持，昆联不能创建、认领或改写为其他来源。
- 人工启停保留原 API 权限闸门，在连接→身份锁下预留 user Owner fence，核对原 F118 事务再写 User 和回执。上游停用时清除人工 override 也不会把 User 强行启用；旧人工操作不能晚到覆盖新 Owner 状态。无效 delete 值拒绝，不能借此跳过已有“仅超管解除同步停用”判断。
- 租户 Owner 只关联已有有效本地租户，拒绝非专属账号、错误作用域和任何既有关联的跨租户搬迁；不创建部门、菜单、角色或资源 Grant。tenant#member 仍走权限 application 的持久投影，并强一致复核当前关系，不能把补偿排队当成完成。权限失败时成员 SQL 不提交。
- L1 自审：T021／T023 回归与拒绝路径 PASS；T022 Owner 边界、身份／用户锁顺序、原权限及普通来源兼容 PASS；T024 租户上下文和权限 application 边界 PASS。新增及修改的干净文件 Ruff PASS；User API 和旧 login-sync 共 61 条 Ruff 诊断逐条原文对照 HEAD 均属原有行，没有新增行诊断；不顺手整改旧问题。相关八个实现文件架构守卫及 git diff --check PASS。
- 人工协调测试将控制面和 User Owner 的 SQLite 存储分开，以验证独立事务和失败恢复；不声称 SQLite 已证明生产同库跨连接行锁。T078 仍需实际双 DB 和多实例证据。User Owner 提交而 F118 最终提交失败时仍须按当前修订恢复，不能宣称跨服务原子成功。


## 第六批次：租户解析和后台对账豁免（T025—T028）

- E-012：backend `pytest test/tenant/test_user_tenant_reconcile_service.py test/tenant/test_tenant_reconcile_task.py test/tenant/test_tenant_resolver.py test/user/test_user_tenant_sync_service.py test/tenant/test_kunlian_external_membership.py test/sso/test_kunlian_directory.py -q --disable-warnings --tb=short`，73 passed、7 warnings。Ruff 定向与六个实现文件架构守卫、git diff --check PASS。
- 先观察昆联无部门返回 Root、未知映射未拒绝，以及后台候选把昆联列入部门漂移的失败。现由 tenant application 先判来源；普通账号不查 F118 表，昆联只通过 F118 的当前、启用、物化完成映射，tenant Owner 再复核本地有效租户和唯一当前成员。缺失或停用时抛错，不降级 Root。
- UserTenantSyncService 对昆联返回显式权威，不走旧搬迁、凭据迁移、JWT 版本或资产转移分支。后台对账只对非昆联候选读取部门快照并修正；一次用户来源批查限定最多 500，与原 Worker 批量上限一致。
- 通用测试夹具预模拟整个 Celery 包，初版“注册入口”尝试落到 MagicMock，不能计为真实注册证据。现用独立 Python 进程预加载真实 Celery，再加载真实任务模块，在 memory broker／memory backend 下通过注册 task 的 apply 调用真实对账服务；修改前确实调用昆联与普通两个修正，修改后只调用普通账号一次。异步桥在测试进程内改为 asyncio.run，调度及部署、Broker 和真实 Worker 启动仍未验证。
- 修复原 Worker 单测对 UserDao 模块属性未通过 monkeypatch 恢复的夹具泄漏；没有改变生产 Worker 文件、调度周期或任务注册。
- L1 自审：T025／T027 的允许／拒绝和调用入口证据 PASS；T026 application 委托、ROOT 窄读与作用域恢复、普通身份兼容 PASS；T028 查询落 Owner Repository、候选范围及资产不搬迁 PASS。T030 明确列出已有 F118 Repository 作为自身投影 SQL 落点，无额外表或跨 Owner 写入。


## 第七批次：Owner 投影协调与恢复（T029—T030）

- E-013：backend `pytest test/sso/test_kunlian_projection.py test/sso/test_kunlian_directory.py test/sso/test_kunlian_session_store.py test/user/test_kunlian_external_identity.py test/user/test_kunlian_source_guards.py test/tenant/test_kunlian_external_membership.py -q --disable-warnings --tb=short`，70 passed、7 warnings。新协调器缺失时先有 5 个明确失败；实现后补齐停用／缺失恢复并全部通过。相关两个实现与新测试 Ruff，两个实现架构守卫、git diff --check PASS。
- 显式映射在首次账号写入前独立提交冻结；即便用户已提交而租户失败，也不能换绑目标。投影保留原控制面事务，预留 Owner fence 后核对原事务与当前源修订／auth_epoch／override／状态，再派发写入；失去原事务不能另开事务继续旧计划。
- User 和成员 Owner 各自提交后再验证当前操作回执，完成本身份 projected_revision；失败不回滚完整目录、已生效停用或其他已完成身份。失败标记也只允许对应源修订和 epoch，不能覆盖新发布或其他实例已完成结果。候选采用有界 keyset 读取，失败隔离，支持后续 Worker 分页恢复。
- 覆盖用户已提交／租户失败后同号恢复、冻结目标不可搬迁、预留后源修订变化或原事务 rollback 不派发 User 写入、手工停用交错拒绝旧回执、单个失败不阻塞其他身份，以及 DISABLED／全轮缺失 UNKNOWN 的停用和恢复。恢复保留原主键及人工角色，不降低 auth_epoch；本地 User、成员和人工授权只通过 Owner 路径处理。
- L1 自审：T029 覆盖／失败路径 PASS；T030 SQL 只在自身 Repository、Owner 只经 application、原事务探针与持久 fence 配对、源修订完成 CAS、超时拒绝和失败诊断 PASS。实际生产 SQL 锁竞争仍待 T078；本批次没有接线 Worker、业务登录或 HTTP／WS 准入。


## 第八批次：当前资格、在线准入与受限协议（T035—T036）

- E-014：backend `pytest test/sso/test_kunlian_admission.py test/user/test_kunlian_external_identity.py test/sso/test_kunlian_session_store.py test/sso/test_kunlian_idp_client.py test/sso/test_kunlian_projection.py -q --disable-warnings --tb=short`，74 passed、7 warnings。准入服务缺失及当前用户资格方法缺失先产生明确失败；补查“失效状态写入／协议查询发生 SQL 故障”时复现两个原始异常外泄的失败，再修复并通过。
- 当前 SQL 会话、连接、稳定身份、冻结映射、已发布目录及新鲜度、投影和人工状态都必须就绪。user Owner 强读本人当前 source／专属外部 ID／停用／token_version／人工角色，tenant Owner 复核有效租户与当前成员；不使用旧 token_version 允许缓存或外部角色代授。
- 每个新 HTTP／WS 动作均在线内省并校验冻结 sub／client／issuer／tenant／sid／workspace；网络往返后再复核当前控制面。IDP 临时故障保留 ACTIVE 记录但本次拒绝，确认无效、身份错配或本地版本变化持久失效，后续不能自动复活。用户主体为 frozen UserPayload 子类，实际工厂不触发旧构造器的角色回查；全局超管按当前 SQL 人工角色／权限 application 强一致关系判定，不使用旧允许缓存。
- 内省上下文只承载会话实际保存的绑定字段，不伪造未保存的 auth_time 或目录身份字段。AT 到期后只可读取绑定的本地协议上下文和 CSRF，不能取业务身份／外部令牌；Origin、会话摘要、浏览器绑定及 CSRF epoch 均参与校验；硬到期仍拒绝。未知引用和必需 SQL／权限依赖故障都不放行，不输出原始异常。
- L1 自审：T035 拒绝／终态／逐次内省及 SQL 故障证据 PASS；T036 各 Owner 窄协议、ROOT／业务租户作用域恢复、无外部令牌进入主体、原接口兼容和稳定失败 PASS。相关受影响九文件 Ruff、六个实现文件架构守卫、git diff --check PASS。
- HTTP／WS 实际接线、Cookie 签发与网关登录仍未交付；本批次是注入式服务证据，不能宣称浏览器或业务入口已受到新准入保护。


## 第九批次：固定 JWT 签发与密码通道保护（T037—T038）

- E-015：backend `pytest test/user/test_kunlian_auth.py test/permission/test_auth_jwt_token_version.py test/tenant/test_tenant_auth.py test/user/test_jwt_secret_resolution.py test/user/test_user_access_request_dedup.py test/dsh/test_web_session.py -q --disable-warnings --tb=short`，65 passed、23 warnings。新行为先复现 11 failed／1 passed：缺签发上下文仍可签普通令牌、部分标记未拒绝及专属来源进入密码解密。实现后固定期限重放、标记／命名空间／硬期限／外部凭据拒绝、普通 JWT 与 DSH 相关行为全部通过。
- 昆联专属账号只能通过带完整 auth_source／会话引用和原 SQL 绝对 iat／exp 的 Owner 签发路径；重复签发不延长期限，最多八小时，过期或缺时间拒绝，外部 AT／ID Token 不能进入本地 JWT。认证解析遇到任一昆联标记时校验完整主体，不因另一标记缺失回退普通分支。完全无标记但 SQL 绑定属于昆联的入口识别仍由 T046 接线验证。
- 密码入口在解密／密码检查前排除专属来源，因此管理员重设密码也不能建立普通会话；普通来源默认 JWT 不新增 iat、显式 expires_in 和原 token_version／tenant_id 合同保持。
- 相关扩大回归首次有 60 passed 及旧 tenant_auth 夹具的 5 个 setup、5 个 teardown 错误：它直接赋值真实 Pydantic Settings.jwt_secret，触发无关 Redis 字段重复校验。仅修正该夹具为替换 config_service／auth 模块 settings 测试绑定，保留原 JWT 断言，随后全部通过；未改生产配置加载器。Ruff 清理该测试未用 import，原预模拟后导入造成的 E402 仍属原有位置。
- L1 自审：T037 主路径／拒绝和普通通道证据 PASS；T038 签发分支、字段最小化、原默认值／解密隔离、无新 SQL 和 Owner 来源限制 PASS。两个实现及新测试 Ruff PASS，两个实现架构守卫和 git diff --check PASS。
- 当前未完成 T007、T039—T082。运行开关仍默认关闭；HTTP／WS 接线、Worker、新登录入口、网关和前端尚未完成，不能作为可用 SSO 发布。


## 第十批次：可信登录交接与控制策略（T039—T040，2026-11-04）

- E-016：backend `pytest test/sso/test_kunlian_login_contract.py test/sso/test_kunlian_admission.py test/sso/test_kunlian_directory.py test/sso/test_kunlian_session_store.py test/sso/test_kunlian_projection.py test/user/test_kunlian_external_identity.py test/user/test_kunlian_auth.py -q --disable-warnings --tb=short`，95 passed、7 warnings。交接协调器／策略方法缺失，以及旧策略仍可准入，均先产生失败；新登录夹具初次漏注入密文适配器时正确拒绝，修正夹具显式使用既有加密设施，没有给生产仓储增加明文或随机密钥兜底。
- raw-body 签名、严格 DTO、ID Token 复核和 opaque AT 内省之后，才查稳定绑定、当前目录／投影／映射／用户／成员及既有菜单入口。缺目录只登记受控需求并拒绝本次，不自动建账号、授权或等待后续再消费原交接。无菜单复用现有 user 错误语义，HTTP 映射由 T042 实现。
- SQL 创建或重放唯一 handoff 回执，user Owner 按回执的原用户名／iat／exp 签发本地 Cookie 描述；重试不延长期限，不创建新会话；同 ID 不同 raw body 和已撤销结果拒绝。内部结果只有本地 JWT／期限及当前主体标识，不返回外部令牌；OAuth nonce 也排除 DTO repr／序列化。总超时 15 秒，超时不伪造成功。
- 原 ConnectionState.policy_revision 落到显式版本配置。初始化只创建已登记连接；已有策略更高版本才能更新，旧版本／同版本相矛盾拒绝，更新同时 fence 旧同步并增加绑定 auth_epoch，登记重新同步需求，保留当前完整目录和人工授权。停止、恢复后旧 Cookie 仍不可用；准入、交接及签发事务都校验当前版本。
- L1 自审：T039 签名／身份／菜单／幂等和失败覆盖 PASS；T040 分层、Owner 固定签发、无默认权限、SQL 原子版本与租约／会话隔离、秘密输出及超时 PASS。相关十一文件 Ruff、六个实现架构守卫、git diff --check PASS；26 条 AC 原文 SHA256 与确认规格一致。
- 以上是 SQLite／受控 HTTP／Owner 测试，尚无真实 MySQL／DM8、外部 IDP 或完整浏览器证据。T041 起的新路由及其 HTTP／WS／Worker／网关接线仍未完成。当前仍不可部署启用。


## 第十一批次：内部 HTTP 交接（T041—T042）

- E-017：backend `pytest test/sso/test_kunlian_internal_api.py test/sso/test_sso_api_integration.py -q --disable-warnings --tb=short`，22 passed、7 warnings。先记录新端点模块不存在的导入失败，仅证明实施入口缺失，不当作业务红灯；实现后真实聚合 Router→Endpoint→application→登录服务→SQLite 回执通过。旧 F014 路由测试一并通过。
- 显式 trusted_gateway_networks 默认空，非法网段也拒绝。内部路径要求原始 raw_path 精确一致、无查询参数；从服务端连接 peer 核验来源，拒绝 Cookie／Authorization／Origin／浏览器 Fetch／Forwarded 和 X-Forwarded 头，防止代理头改写来源。流式读取上限 64KiB，验签使用原始字节，重复 nonce 拒绝，未知身份字段不得进入协议。
- 仅昆联 APIRoute 将领域错误转为真实 HTTP，菜单拒绝保留 10609／10611 并返回 403；成功及错误均 no-store。与模拟全局旧 HTTP 200 handler 共存时仍返回 400／403／503，秘密不进入响应。管理路径已声明薄委托，但管理应用和真实运行装配仍待 T044／T046；未装配固定 503，不以默认允许掩盖未接线。
- L1 自审：T041 覆盖／实际路由／原通道回归 PASS；T042 分层、原始字节和来源边界、无 ORM、局部错误合同、默认拒绝、秘密最小化 PASS。五文件 Ruff、三个实现架构守卫、git diff --check PASS。本批次未调用真实网关或 IDP。


## 第十二批次：全局超管控制面（T043—T044）

- E-018：backend `pytest test/sso/test_kunlian_management_api.py test/sso/test_kunlian_internal_api.py test/sso/test_kunlian_directory.py test/sso/test_kunlian_projection.py test/sso/test_sso_api_integration.py test/user/test_kunlian_external_identity.py test/tenant/test_kunlian_external_membership.py test/sso/test_kunlian_admission.py test/sso/test_kunlian_login_contract.py -q --disable-warnings --tb=short`，109 passed、7 warnings。先记录管理 application 缺失，再接通；初版夹具尝试用同一策略版本把 SQL 已关闭登录变为开启时得到 409，修正为真实目录预热场景（登录关闭），未放宽策略栅栏。
- 四种管理操作每次由 user Owner 强读当前账号状态和全部本人角色，再检查既有全局 AdminRole／权限 application HIGHER_CONSISTENCY super_admin。忽略请求或旧主体的 is_global_super 标记，租户管理员和停用账号拒绝；必要依赖失败返回稳定 503。控制面显式 ROOT 范围，调用 tenant Owner 核验既有有效 Root／一级 Child，退出后恢复原上下文。不自动建租户。
- 映射采用既有 CAS／物化冻结规则，变更与现有 AuditLog 追加在同一事务，审计写入失败时映射及修订回滚。人工同步只合并未处理的需求版本，返回 202 REQUESTED；审计与该需求同事务，重复受理不冒充同步完成。
- 状态展示已发布目录批次、age、最近运行／失败关联和投影待办／失败，凭据配置不可用有稳定原因，不输出凭据值／引用或成员摘要。无完整目录时计数为 null，已发布空目录为 0；身份投影失败不伪装目录失败。来源网段缺失／非法纳入配置就绪诊断。昆联局部路由保持认证依赖 401／403，旧全局异常处理不变。
- L1 自审：T043 覆盖／真实 HTTP／失败及回滚 PASS；T044 Owner 分工、无新 DAO、SQL 只在 Repository、审计持久化／操作人来自服务端、ROOT 恢复、安全输出和设计同步 PASS。新修改文件 Ruff、八个实现架构守卫、git diff --check PASS。未操作真实目录、运行配置、权限或部署。
- 当前未完成 T007、T045—T082。HTTP／WS 在线准入、Worker、商业网关和前端尚未接线；管理和内部登录目前是可注入的真实路由证据，生产运行装配仍待 T046。


## 第十三批次：HTTP／WS 逐动作接线与工作流因果边界（T045—T049、T053）

- E-019：backend `pytest test/sso/test_kunlian_*.py test/user/test_kunlian_*.py test/tenant/test_kunlian_external_membership.py test/sso/test_sso_api_integration.py test/open_api/test_websocket_tenant_revalidation.py test/open_api/test_websocket_auth.py test/open_api/test_execution_snapshot.py test/permission/test_auth_jwt_token_version.py test/tenant/test_tenant_auth.py test/dsh/test_web_session.py -q --disable-warnings --tb=short`，279 passed、23 warnings（10.83s，进程退出 0）。仅临时空 YAML、SQLite、ASGI、模拟 IDP 和内存 Celery，没有真实上游／中间件访问。
- HTTP 分支在旧 fail-open、租户豁免和 token_version 缓存之前识别 Cookie／Bearer 中的标记、引用、保留来源／命名空间和定点 SQL 绑定。未验签字段只用作拒绝／分流提示，不能生成身份；去掉全部标记、引号 Cookie、重复 Cookie、身份头及 Bearer 替代不能绕过。逐请求在线内省，middleware 与 UserPayload 仅共享同一请求内已验证结果，SQL 分类故障拒绝 503；外部失效或本地 JWT 到期 401。写请求需要精确 Origin 和绑定 CSRF。业务 scope 恢复原上下文，允许可见 Root 共享范围，不给普通身份增加昆联内省；v2／v3／DSH 专属通道保留原合同。
- 两个真实 FastAPI WebSocket Router→身份依赖→Endpoint 已接线，握手及每个业务消息分别内省；Origin、query t 和 Bearer 替代拒绝。消息准入先于原 F048 use，缺回调不得使用昆联握手旧身份。真实长连接循环的两次空闲超时不产生授权检查；第三个已失效业务动作不 dispatch。连接关闭保留已开始的昆联 debug 工作流，显式且通过准入的 stop 才停止。
- BaseClient 通过 ContextVar 读取当次 operator，finally 恢复；不替换共享连接中的身份或工作流状态。真实 WorkflowClient 的发送／继续／取消使用当次主体；并发消息可分别读取独立身份，原连接身份保留。既有 GPTS 的 copy 路径回归通过。Open API execution_snapshot 保持原格式，昆联 cause 在独立 Celery headers 中，只含 user／tenant／绑定摘要／会话摘要／请求因果编号，无浏览器引用、AT、ID Token 或授权标志。
- 独立进程先加载真实 Celery，再预模拟外部依赖并注册真实 workflow tasks，以内存 broker/backend 的 Task.apply 验证接收端。先复现非法 cause 仍执行的业务失败；实现后校验任务参数、显式本地 tenant header 和当前 worker tenant 一致，拒绝换人、换租户和额外 reference；不构造登录主体或 PermissionActor，不把 cause 当开放面授权快照，不增加在途逐节点内省。原 trace 保持执行 unique_id，因果 request_id 单独记脱敏日志，worker 结束恢复原 tenant。
- 运行装配采用明确的 env:NAME 引用；外部令牌／游标使用独立 encryption_secret_reference 的 Fernet 密钥，不使用通用函数中的旧固定密钥。配置／必需秘密缺失、非法密文密钥或秘密复用时不装配登录／业务准入；目录缺密文密钥也拒绝拉取。运行中复用网络客户端以保留 JWKS 刷新预算，不缓存允许；配置／秘密变化重建，shutdown 关闭。读取原 allow_multi_login 设置，并将其接入 SQL 签发服务；默认关闭不查询此设置、不外连。
- 夹具偏差：HTTP 首轮漏替换 AuthJwt 密钥解析，曾尝试读取未配置 DB；随后只在夹具注入虚构签名密钥。新增 WS 夹具首轮漏 receive/send，已补齐；扩大回归遇到旧 DSH SimpleNamespace 假 socket，保留其旧语义，仅真实 WebSocket 进入新适配。以上不计作有效行为红灯。有效失败包括 BaseClient 不接受 execution_context 的 TypeError、真实 route 缺逐消息回调、非法因果头仍到达实际注册任务；最终上述组合均通过。
- L1 自审：T045 覆盖／真实路由和工作流／失败及并发证据 PASS；T046 默认拒绝、独立加密及实时身份／请求级去重 PASS；T047 消息局部身份与保留工作流状态 PASS；T048 先准入再 use、无回调拒绝及拒绝后不 dispatch PASS；T049 两个实际入口与原身份回归 PASS；T053 真实任务消费／无凭据元数据及无新认证主体 PASS_WITH_NOTES。
- 静态检查：新／原干净修改文件 Ruff PASS。BaseClient 的 B027／RUF013 及 workflow tasks 的四个 RUF059 共六条诊断逐行与 HEAD 比较，全部在原有代码，无新行诊断。21 个实现文件运行守卫：15 文件无输出；四个 common/chat 旧文件的七条 RULE-1 与两个旧 Endpoint 的两条 RULE-3，共九条输出，与 git show HEAD 临时副本运行结果完全一致。未移动旧架构或增加豁免；保留为合入前特性级审查的既有债务，不能宣称全文件守卫零诊断。git diff --check PASS。
- 当前未完成 T007、T050—T052、T054—T082。同步 Worker、商业网关和前端尚未完成；真实 MySQL／DM8、共享 Redis／FGA、两实例、完整浏览器和 EXT 门禁未验收，不能启用或部署。


## 第十四批次：同步 Worker 与 Beat 恢复（T050—T052）

- E-020：backend `pytest test/sso/test_kunlian_worker.py test/sso/test_kunlian_http_admission.py test/sso/test_kunlian_directory.py test/sso/test_kunlian_directory_client.py test/sso/test_kunlian_projection.py test/sso/test_kunlian_session_store.py test/tenant/test_tenant_reconcile_task.py -q --disable-warnings --tb=short`，79 passed、7 warnings（11.28s，进程退出 0）。五个实现／测试文件 Ruff、五个实现守卫及 git diff --check PASS。
- 新增三种真实 Celery 任务 dispatch_sync／sync_directory／recover_projection，并由 worker 聚合入口注册；默认 celery 队列，目录关闭不建立运行服务、不发请求。Beat 仅目录开关允许时增加唯一条目，显式传本地 Root tenant_id=1。任务本体再次校验严格正整数 Root 头，拒绝 UUID、bool、其他租户和缺失值，不以 Celery 旧默认 Root 兜底。
- 当前配置只登记单个 connection_id，因此调度只处理这一已登记连接。先提交同步需求版本再投递；SQLite 中模拟 Broker 投递失败后需求仍保留，下一 tick 重新投递同步和投影恢复。目录全轮继续使用原 SQL lease／fence、旧指针和稳定失败处理，不把 FETCHING 或投影 FAILED 当成完整交付。投影每任务最多 25 个身份，keyset 续投；每轮从头恢复失败／丢队列待办，有界超时和 finally 关闭客户端、恢复 Root／原租户作用域。
- 独立进程加载真实 Celery，用内存 broker/backend 注册任务并 Task.apply，验证任务名、严格 headers、默认关闭和 Beat／队列配置；导入期间将 socket.connect 设为失败，未发生网络连接。pytest 通用预模拟会缓存旧 MagicMock 装饰的任务模块，首版真实注册夹具因此报 NotRegistered，已改为显式重新执行实际模块；该错误不计业务红灯。旧通用 tenant signal 在非法头时清空上下文，测试按独立任务重新设定环境，不修改该全局策略；本业务 Root 作用域和失败后恢复另外用实际驱动＋SQL 证明。
- L1 自审：T050 覆盖／实际注册／安全导入及失败路径 PASS；T051 仅经 application／领域服务、无秘密队列载荷、Root 头和上下文恢复、持久需求及分页恢复 PASS；T052 默认关闭、唯一 Beat 项、队列隔离和间隔不等于撤权 SLA PASS。未启动真实 Broker／Worker／Beat 服务，没有同步真实目录或修改运行配置。
- 当前未完成 T007、T054—T082，共 30 项。商业网关、退出完整链路、前端和最终外部验收仍未完成，不能部署启用。


## 第十五批次：网关依赖与独立属性（T007）

- 网关独立工作树 `/Users/wenruli/code/project/bisheng/bisheng-gateway-kunlian-sso`，分支 codex/118-kunlian-sso-user-sync，基线 948cce69。原 main 工作树未写入；两个仓库都未提交／推送。JDK 17.0.17 和 Maven 3.9.14 已实际核验，无 JDK 阻塞。
- E-021：网关工作树 `JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home mvn -B -DskipTests compile`，基线 BUILD SUCCESS；随后相同 Java 17 环境运行 `mvn -B -DskipTests compile dependency:tree '-Dincludes=org.springframework.security:*,com.nimbusds:*' -DoutputFile=/tmp/f118-gateway-oidc-dependency-tree.txt`，BUILD SUCCESS。新增属性后 `mvn -B -Dtest=KunlianSsoPropertiesTest test`：7 tests，0 failures／errors／skipped，BUILD SUCCESS；git diff --check PASS。
- 仅增加 Boot 管理的 spring-boot-starter-oauth2-client，不整体升级 BOM／JustAuth。实际解析 OAuth2 client／core／jose／config／web 6.2.4、Nimbus oauth2-oidc-sdk 9.43.3、nimbus-jose-jwt 9.24.4。查阅这些实际下载 POM 的 licenses 均为 Apache 2.0，同时核对 [Boot 3.2.6 管理版本](https://docs.spring.io/spring-boot/docs/3.2.6/reference/html/dependency-versions.html)、[Spring Security 许可证](https://github.com/spring-projects/spring-security)、[Nimbus JOSE 许可证](https://connect2id.com/products/nimbus-jose-jwt) 与 [Nimbus OIDC SDK 许可证](https://connect2id.com/products/nimbus-oauth-openid-connect-sdk)。这是版本及许可证证据，不是依赖漏洞扫描或生产安全验收。
- custom.kunlian 独立属性默认关闭，仅保存秘密引用；Binder 验证真实绑定前缀、精确 Origin／回调、HTTPS／显式测试或服务 Origin、资源预算和缺失诊断。旧 JustAuth 属性不参与新绑定。测试无 Redis／数据库／IDP。尚未启动网关；新增 Security 依赖的自动配置影响必须由 T060／T061 的真实 Reactive 上下文隔离验证，不能据属性测试声称全站行为未变或可以部署。
- L1 自审：T007 基础设施依赖范围、BOM／许可证、无秘密值、默认属性与配置诊断、独立工作树 PASS_WITH_NOTES（安全链隔离仍属后续明确任务）。当前未完成 T054—T082 共 29 项。


## 第十六批次：网关登录／退出事务（T054—T055）

- E-022：独立网关工作树，Java 17 环境 `mvn -B -Dtest=KunlianLoginTransactionStoreTest,KunlianSsoPropertiesTest test`，22 tests，0 failures／errors／skipped，BUILD SUCCESS（5.377s）。git diff --check PASS。先记录目标类缺失的编译失败，不能当成行为红灯；随后新增硬期限场景实际复现“过期绑定仍可消费尚未到五分钟的事务”，补服务器侧绑定期限复核后通过。
- 事务保存在明确注入的 Redis 原子端口，生产实现以单个 Lua GET／DEL 原子消费，无进程内生产状态兜底；错误回调也只暴露同一单次消费接口。state／nonce／verifier 分别安全随机，PKCE S256 以 RFC 7636 已知向量校验；不同标签页 state 独立，共享服务器已登记浏览器绑定。
- 事务材料用独立注入的 256 位密钥、AES-GCM／96 位随机 IV／认证标签保护，记录密钥版本，秘密不在键、日志／toString 或错误中。损坏密文和更换密钥拒绝，无明文或随机新密钥读取兜底。回跳仅限登记站内前缀，拒绝外链、编码斜线、路径穿越、控制字符与未登记 API 路径。
- 浏览器绑定单独保存硬期限，五分钟事务到期不会删除八小时上限的绑定。只有受信后端成功会话的期限能调整绑定；消费时重新查服务器硬期限，不能手工重放已过期 Cookie。事务期限取五分钟与当前绑定硬期限的更早值；登录／退出事务分 kind，跨浏览器和重放拒绝，Redis 故障 503。
- L1 自审：T054 随机／绑定／消费／期限／失败及无秘密证据 PASS；T055 默认关闭、独立受保护共享状态、严格回跳、原子消费和稳定错误 PASS。内存共享端口只证明应用状态机及两实例共同调用原子边界，不证明真实 Redis 的 Lua 并发、TTL 和网络故障；实际中间件留 T078。Controller 的 error 回调实际接线还需 T062／T063。尚未实现 OIDC 客户端、签名交接、安全链隔离或浏览器回调，不得部署。
- 当前未完成 T056—T082，共 27 项。


## 第十七批次：专用 OIDC 客户端（T056—T057）

- E-023：Java 17 网关工作树 `mvn -B -Dtest=KunlianOidcClientTest,KunlianLoginTransactionStoreTest,KunlianSsoPropertiesTest test`，43 tests，0 failures／errors／skipped，BUILD SUCCESS（7.460s）。包括 localhost 随机端口模拟 OP，使用生产构造器和实际 Reactor Netty 连接器；没有连接真实昆联。git diff --check PASS。
- 授权 URI 由现有 BOM 的 OAuth2AuthorizationRequest 构造，固定 code／openid profile／PKCE S256／nonce；Token POST Basic 对 client_id 和 secret 分别 form 编码，表单只有 grant_type／code／redirect_uri／verifier，不发 refresh、prompt、resource 或 audience 扩展。实际连接器验证 503 后只发一次 POST，不跟随 302 到未登记路径。
- ID Token 必须 RS256、已登记 Discovery issuer／所有端点及 JWKS，拒绝 jku／jwk／x5u／crit／b64 扩展、HS256、错误签名和私有 JWK；RSA 公钥 2048—8192 bit、指数约束。issuer／sub／aud／必要 azp／nonce／固定租户／workspace／sid／必需时间逐一验证。公钥缓存五分钟，未知 kid 每 30 秒最多一次刷新，两个后续拒绝不重复请求；预算后能读取新 kid。只缓存公钥，不缓存访问允许。
- 退出 URI 只接受显式标记本地已撤销的服务端 Hint 类型，固定 OP／post_logout_redirect_uri／state。过期 ID Token 不能用于登录，但可作为此受限退出 Hint；SDK 兑换与 Controller 的真实撤销证明接线仍待 T059／T063，不把服务端类型本身当成对浏览器的鉴权。
- 有效日志回归：开启真实 WebClient／Reactor Netty／Spring codec DEBUG 并完成成功换码，先复现 Jackson2JsonDecoder 将虚构 AT／IDT 写入日志。改为有界 byte[] 解码后由独立 ObjectMapper 解析（重复 JSON 字段拒绝），不调用默认 JSON／字符串解码器处理秘密响应。再次模拟成功换码、503 和 302，捕获跨线程日志无 code／Basic／secret／AT／IDT／原始上游错误。日志内容全为本机生成的虚构材料，无真实凭据。
- 最初目标类缺失为编译入口缺失；随后编译发现 6.2.4 的 scopes API 接受 Set，已按实际 API 修正，未用升级依赖解决。L1 自审：T056 真实编码／签名／拒绝／刷新／网络工厂及秘密探针 PASS；T057 独立客户端、预算／TLS／禁止跳转、无 code 重试、严格绑定和 Hint 分流 PASS。未改 JustAuth、未调用 UserInfo、未启动网关服务；安全链隔离和浏览器协议仍未完成。
- 当前未完成 T058—T082，共 25 项。


### 第十三批次补充回归：旧声明形态与匿名绑定（T045／T046／T042）

- E-024：backend `pytest test/sso/test_kunlian_http_admission.py test/sso/test_kunlian_internal_api.py test/sso/test_kunlian_management_api.py test/sso/test_kunlian_ws_admission.py test/permission/test_auth_jwt_token_version.py test/dsh/test_web_session.py test/open_api/test_websocket_tenant_revalidation.py -q --disable-warnings --tb=short`，85 passed、17 warnings。真实路由先复现字符串／整数值浮点 user_id 在移除昆联标记后进入旧主体构造并返回 200；仅绑定 Cookie 的匿名请求也错误加载认证运行服务，模拟依赖失败变 503。
- 只为来源分类按旧 Pydantic int 能解析的形态定位真实 user_id，不据此构造主体；发现保留来源或绑定后仍验证原始声明的完整严格字段，因此字符串／浮点缺标记拒绝 403，旧构造器未调用。只有 kunlian_browser_binding 不构成身份，不读登录秘密或控制表；普通匿名路径保留原 404／公开行为。
- 新昆联管理路由的未登录错误局部转为真实 401＋统一信封，无昆联 SESSION_EXPIRED 原因，避免把来源未知的普通用户推入昆联登录。实际全局 AuthJWTException handler 原本就是 HTTP 401/detail，保持不改；首版测试误模拟成 200，读取 main 后纠正，该结果不算有效红灯。纠正后实际复现缺统一 data 字段，再补局部适配。新／修改文件 Ruff、两个实现守卫及 diff 检查 PASS；任务数仍 58/83。


## 第十八批次：跨仓签名及身份 SDK（T058—T059）

- E-025：Java 17 网关工作树 `mvn -B '-Dtest=Kunlian*Test' test`，49 tests，0 failures／errors／skipped，BUILD SUCCESS（8.033s）。包含生产构造器和实际 Reactor Netty 连接器的 localhost 随机端口测试；没有连接真实后端或昆联。首次目标类缺失是编译入口缺失，不算行为红灯。
- 新 v1 签名器与 T033 后端固定向量一致，原始 JSON 只序列化一次；内部登录最多两次，handoff_id 和报文字节不变，每次签名 nonce 更新。连接器显式禁用隐式重试和跳转。单次退票兑换不重试，成功只接受登记 client_id 与 local_session_revoked=true。
- 后端会话只接收固定四字段，绝对期限不由网关延长，不透传任意 Set-Cookie 或原始错误信息。业务拒绝不重试，网络／5xx 登录最多重试一次。内部调用独立超时默认 20 秒，上限 30 秒，区别 OIDC 单次换码预算；未修改运行配置。
- 真实 HTTP 验证首次 503、第二次成功的字节／nonce、302 不跳转，并开启 WebClient／Netty／Spring codec DEBUG，虚构 AT／IDT／JWT／共享秘密／上游错误均未进入日志。秘密响应使用有界 byte[] 与独立严格 JSON 解析，不复用通用客户端的 header 日志过滤器。
- L1 自审：T058 签名／幂等／业务失败／单次退票及真实传输证据 PASS；T059 独立签名和客户端、秘密隔离、预算、契约与设计同步 PASS。SDK 的受信撤销证明仍需 T065／T066 真实后端端点，安全链和浏览器回调仍待 T060—T063。当前未完成 T060—T082，共 23 项，不部署。


## 第十九批次：网关安全链隔离（T060—T061）

- E-026：Java 17 网关 `mvn -B -Dtest=KunlianSecurityConfigurationTest,LicenseExpiredGlobalFilterTest test`，8 tests，0 failures／errors／skipped，BUILD SUCCESS（6.385s）。实际 Reactive 应用上下文同时加载 Boot Reactive Security／默认用户／OAuth2 Client 自动配置，验证默认关闭与启用但注册不全两种状态，不是仅编译单类。
- 仅四个精确昆联路径匹配专用协议链，未就绪返回 503／no-store。普通 v1／v2／v3、旧 SSO／列表、/login、/logout、普通写操作、相似前缀均保持原处理，不新增登录跳转、Basic、默认用户／随机密码、全局 CSRF 拦截或默认 logout 行为。旧许可证过滤器六项回归仍通过；这不等于完整商业网关启动联调。
- 就绪协议链检查登记 Host 与精确 Origin，顶层 GET 回调允许不携 Origin，POST 必须同源，错误方法 405；相似攻击 Origin／其他 Host／null Origin 拒绝。所有地址来自登记值，不能用 Forwarded 头选择回跳。客户端装配只解析真实 env 引用，必须三种独立秘密且 Redis 已注入，缺失时无客户端、不联网；显式不构造默认身份。
- L1 自审：T060 实际上下文和隔离证据 PASS；T061 精确 matcher、关闭态／失败关闭、秘密隔离与生命周期 PASS。当前仍未实现浏览器 Controller，不能部署或宣称真实登录验收。进度 62/83，剩 T062—T082 共 21 项。


## 第二十批次：网关浏览器协议（T062—T063）

- E-027：Java 17 网关 `mvn -B '-Dtest=Kunlian*Test,LicenseExpiredGlobalFilterTest' test`，66 tests，0 failures／errors／skipped，BUILD SUCCESS（9.488s）；含本批 Controller 八项、实际安全上下文、签名／SDK／OIDC／事务、Cookie 属性及旧许可证回归。git diff --check PASS。未连接真实 OP／后端，未部署。
- 四条精确路由完成；回调在处理 code／error 之前原子消费绑定事务，取消后重放不能换码，目录未就绪固定错误页提示稍后重登，不自动循环。成功只写 Host-only／Path=/／HttpOnly／Secure／Lax 的本地访问 Cookie 和服务器绑定 Cookie，保留绝对硬期限，不创建 refresh 凭据。清理范围仅已知同名 Cookie；配置域必须属于登记入口，属性注入或其他域拒绝，重复 Cookie 不选择旧身份。
- 退出必须先从内部 SDK 兑换带本地已撤销证明的绑定票据，再建立 logout_state 和跳 OP。跨浏览器回调不消费正确事务，成功回调仅说明收到 OP 回调，取消明确 LOGOUT_INCOMPLETE；两种回调都消费 state、清理绑定，不声称所有远端会话均已结束。兑换失败不跳 OP、不报告远端成功。
- 有效隐私红灯：Spring HttpWebHandlerAdapter 在 WebFilter 之前以 DEBUG 记录完整回调查询，实际捕获虚构 code／state。新增 Logback 日志生成前的协议 URL 过滤，仅禁止此类 URL／Hint 查询日志；普通日志保留。相同服务器日志探针转绿。反代、网络 wiretap 与外围访问日志仍需 T076 操作说明和 T080 实测，不能据此宣称外围日志已受控。
- 首次测试把已编码 return_to 交字符串 URI 构造器造成二次编码，修正为 URI 后通过；此为测试输入问题，不算实现行为红灯。旧列表只在专用运行组件就绪时增加 kunlian 项，未改旧 JustAuth 登录逻辑。
- 成功 Location 带固定 #kunlian-login 非凭据提示，用于后续前端在第一次用户请求前清理旧 Bearer。前端必须以服务器当前 auth_source 确认昆联来源；片段不授予身份，不承载 JWT／AT／IDT。前端接线及后端退出端点尚未完成，不可部署。L1：T062／T063 PASS；进度 64/83，剩 T064—T082 共 19 项。


## 第二十一批次：本地退出、辅助 CSRF 与材料保留（T064—T066）

- E-028：backend `pytest test/sso/test_kunlian_*.py test/user/test_kunlian_*.py test/tenant/test_kunlian_external_membership.py test/sso/test_sso_api_integration.py test/open_api/test_websocket_tenant_revalidation.py test/open_api/test_websocket_auth.py test/open_api/test_execution_snapshot.py test/permission/test_auth_jwt_token_version.py test/tenant/test_tenant_auth.py test/dsh/test_web_session.py -q --disable-warnings --tb=short`，303 passed、23 warnings（16.49s）。环境为现有 Python 3.11 venv、临时空配置、临时 SQLite／MockTransport／内存 Celery，未访问真实目录／OP／生产服务。
- 受限协议类型只携带隐藏引用／摘要，不构造 UserPayload。精确 GET CSRF 与 POST logout 校验严格 Cookie、原签发主体／连接／客户端、服务器浏览器绑定、Origin／CSRF；拒绝重复绑定、错主体、错路径／方法和误接业务身份依赖。AT 到期及登录／目录／多租户开关关闭后可本地协议退出，业务请求仍失败；无在线内省或原角色／成员放行。
- SQL revoke 独立成功提交后才签票。撤销 SQL 失败返回真实 503、不清 Cookie、不报告退出；重试和重复退出不复活会话。票据按哈希单次保存，兑换同一事务核验连接／客户端／浏览器／期限，失败不消耗正确票据。只给来源网段和新 HMAC 签名均有效的网关返回固定 Hint 三字段，拒绝浏览器头；已消费后仅可确认本地撤销、next_action=null，不再交接 Hint。普通 logout 仍 201 和原 Cookie 清理合同。
- Worker 有登记 connection_id 时每分钟有界处理到期会话／短期回执，关闭登录／目录不停止；默认空登记不调度。每批各最多 100，积压续投，Root headers 严格校验、作用域恢复，纯导入无网络。两条分批数据验证清空后继续下一批，不被已清理头部阻塞；只清空到期密文，不删除状态／审计或业务资产。硬期限即拒绝，物理清理依赖成功调度，不承诺零延迟擦除。
- 到期回执过滤使用 LENGTH，避免对 DM8 CLOB 直接作字符串等值比较；语义参考[达梦官方函数文档](https://eco.dameng.com/document/dm/zh-cn/pm/function)，真实 MySQL／DM8 的 CLOB 空值处理、锁与并发仍待 T078，不把 SQLite 或文档核对当作数据库验收。
- 初次运行缺服务／新接口是入口缺失，非有效业务红灯；新增有界清理入口同样先观察缺实现。独立服务器 DEBUG 泄密已在 E-027 形成有效红绿回归，不重复将编译／导入失败算业务复现。新／改 F118 文件 Ruff PASS，旧 user/api/user.py 及 http_middleware.py 与 HEAD 逐诊断行比较无新增，10 个实际落点逐个运行架构守卫 PASS，git diff --check PASS。
- L1 自审：T064 真实 API／SQL 与失败路径 PASS；T065 Owner 边界、无业务主体、同事务校验和材料清理 PASS；T066 真实 HTTP／固定路径及旧 logout 兼容 PASS。进度 67/83，剩 T067—T082 共 16 项；两端交互、真实服务／浏览器验证及最终交付审查尚未完成，不部署。

## 第二十二批次：两 SPA、可信来源与三语（T067—T077）

- E-029：在 frontend 根使用 Node 24.14.0（PATH 指向本机既有 nvm 目录）、pnpm 9.15.9。`pnpm --filter bisheng exec vitest run src/controllers src/test/kunlianLogout.test.tsx --maxWorkers=1 --minWorkers=1`：19 files、122 passed（7.06s）；日志 /tmp/f118-platform-verified.log。`pnpm --filter bishengchat exec jest --runInBand --runTestsByPath src/api/kunlianSession.test.ts src/hooks/kunlianLogout.test.tsx src/api/clientRequestContract.test.ts src/api/requestUserMessages.test.ts src/utils/loginRedirect.test.ts --coverage=false`：5 suites、39 passed（0.94s）；日志 /tmp/f118-client-final.log。
- `pnpm lint`、`pnpm typecheck` 全部前端工作区检查通过；Platform／Client 严格文件分别 1037／1727，随后三个共享包 tsc 通过，日志 /tmp/f118-frontend-lint-verified.log、/tmp/f118-frontend-typecheck-verified.log。`pnpm --filter @bisheng/locales build` 生成两端三语 shared／api_errors；`pnpm --filter @bisheng/locales check` 与 `pnpm check-i18n` 通过，后者报告 84 个既有 frontend-only code 信息、无新增漂移；日志 /tmp/f118-locales-check.log、/tmp/f118-i18n-check.log。产物没有手改。两个 suppression 账本仅经 lint:prune 缩小，没有增加 ignore 或 suppression。
- 复用现有 api-client 包共享固定 return_to、稳定错误识别、Cookie-only／CSRF 和 next_action 限制；两 SPA 独立交互实例不能授业务身份。平台 request／真实 fetch streaming 与 assistant WS 调用参数均有执行证据。Client 覆盖真实 mutation→API→AuthContext，只有明确成功才清 query／用户状态；失败保留重试。四处 Platform 退出调用者分别覆盖，不以助手函数无人调用冒充接线完成。
- 当前用户来源先形成有效红灯：真实 ASGI 路由对昆联缺 auth_source（1 failed、普通 1 passed）；修复后与退出组合 16 passed。只从认证依赖的主体序列化来源，请求头／查询不能伪造；普通响应不增字段。后端测试已纳入最终 E-030，不重复运行。
- Client 503 路由有效红灯：请求层已拒绝跳转，但真实 RequireLogin 后续仍调用自动重登一次；增加仅本页手动重试标记并由路由消费后通过。管理接口错误不能把普通管理员转换成昆联交互；预期昆联而服务器返回另一来源时拒绝沿用。该状态只控制交互，不提供身份或允许缓存。
- 三个旧 Platform 测试替身问题已独立核对：HEAD 5a359d8e6 临时工作树重现 dshRequestCompatibility 六项与 requestSessionFailure 一项失败（/tmp/f118-platform-head-baseline.log）；前者缺 i18next.exists 且错误文案断言落后于 HEAD 已有安全提示，后者及 requestCompatibilityMatrix 的 Location 缺绝对 href／origin。仅修替身和已有安全文案断言，不修改旧产品错误合同，也不将其算新功能红灯。
- 环境说明：仅实施工作树运行 `pnpm install --frozen-lockfile --ignore-scripts`，未改锁文件或依赖版本。未编译的可选 canvas 导致 jsdom 导入失败，已在本工作树 node_modules 可逆移开五个 canvas 链接，未改包源码／全局缓存；此为测试环境修复，不是业务通过证据。既有 Node url.parse 和 React Router future 警告未作为新失败；没有构建发布制品或启动线上服务。
- L1 同代理任务自审：T067／T072 请求失败、实际调用者、成功后清理及手动重试 PASS；T068—T071／T073—T075 服务器来源、固定路径／动作、写请求与旧通道兼容 PASS；T076—T077 三语源／生成物／静态门禁 PASS。T067 的网络、SQL 和 OP 失败由接口替身模拟，跨层 SQL 失败另复用 E-030，不把组件测试说成真实 OP／浏览器通过。进度 78/83；尚未完成真实 E2E。

## 第二十三批次：旧凭据入口兼容及最终本地回归（T081）

- 先复现 4 项有效失败：过期昆联 Cookie 抢占显式本地密码登录、公钥、验证码／启动配置入口。后端仅对精确方法＋原路径保留既有认证启动流程；新提交凭据仍交原 UserService 验证，昆联影子账号仍拒绝密码登录。共享浏览器分类同步排除这些启动路径，避免先取旧会话 CSRF。没有增加业务路径、内部网关或开放面身份豁免。
- 首轮定向 `test/sso/test_kunlian_compatibility.py test/user/test_kunlian_auth.py test/sso/test_kunlian_http_admission.py test/sso/test_kunlian_logout.py`：52 passed、7 warnings（/tmp/f118-compat-green.log）。兼容路由用 UserService 替身证明交回原凭据流程，不声称它证明密码校验；原 shadow 密码拒绝使用真实服务测试覆盖。
- E-030：backend 临时空 YAML、既有 Python 3.11 venv，`.venv/bin/python -m pytest test/sso/test_kunlian_*.py test/user/test_kunlian_*.py test/tenant/test_kunlian_external_membership.py test/sso/test_sso_api_integration.py test/open_api/test_websocket_tenant_revalidation.py test/open_api/test_websocket_auth.py test/open_api/test_execution_snapshot.py test/permission/test_auth_jwt_token_version.py test/tenant/test_tenant_auth.py test/dsh/test_web_session.py -q --disable-warnings --tb=short`：**309 passed、23 warnings，17.50s，退出 0**；/tmp/f118-backend-final.log。
- 选择理由：覆盖本特性全部后端测试、User／Tenant Owner、原 SSO 入口、旧 JWT token_version、HTTP／WS 租户复核、开放面 execution_snapshot 与 DSH web session。Platform／Client 的旧请求／退出回归复用 E-029，网关旧许可证与安全链隔离复用 E-027 的 66 tests（源码此后未变）。不运行不相关知识解析、存储或全仓测试；真实 DB／Redis／OpenFGA 与昆联 E2E 独立留在 T078—T080，不以本地回归替代。
- 两个新增测试 Ruff check／format PASS；旧 user/api/user.py、http_middleware.py 通过当前源码与 HEAD 相同诊断 code／message／源行差分，零新增 Ruff 诊断。四个本批 Python 落点逐文件架构守卫及 git diff --check PASS。旧文件已有 Ruff 问题未顺手修复，也未增加忽略。
- L1：T081 来源分流、失败关闭、精确入口、原 UserService 验证、影子密码隔离、测试选择与设计同步 PASS。此为同代理任务自审，并非特性独立审查。当前进度 79/83；T078—T080、T082 保持未完成。已准备真实验收清单和配对发布／SQL 禁用／安全回退说明，整体 NOT_READY；未执行其中任何运维步骤，未提交／推送／部署。

## 第二十四批次：T078／T079 测试脚本补齐（真实执行待办）

- 用户明确要求先补齐脚本、缺少真实环境的验证待执行，不部署。本批仅新增五个测试／辅助文件及运行文档，没有修改产品代码、依赖或运行配置，没有创建真实表或访问外部服务。原产品相关回归复用 E-027／E-029／E-030，不重复执行未变化的 309／66／122／39 项选择集。
- T078 两个目标文件已落地：test/integration/kunlian_fixtures.py 与 test_kunlian_consistency.py。四组真实测试覆盖独立连接池租约竞争／旧 fence、原完整目录与失败保留、持久 Owner 投影和人工禁用竞争、并发交接唯一／epoch／恢复／跨实例撤销／到期密文清理、两个签名验证实例共享真实 Redis nonce／TTL。只接受显式的 e2e_kunlian_ 专用 MySQL／DM8 schema 和非 0 Redis DB；不使用 SQLite，不建表，清理按本次随机连接和已登记身份限定，意外角色关联停止清理。这里是两个 Repository／连接池实例，不等于两个已部署进程。
- T079 两个目标文件已落地：test/e2e/test_e2e_kunlian_identity.py 与 helpers/kunlian.py。真实网关授权 URL／未消费的 OP 回调建立 Cookie，真实管理 API 映射／入队、Broker send_task 与 Worker 回执、完整发布和投影共同证明同步；不直调任务本体。A／B 是普通用户，C 为固定租户反例；独立 missing 探针避免用既有绑定 UNKNOWN 冒充首次目录未就绪。用 F048 visible／use／edit／publish 检查和实际读取／编辑入口对照，停用保留 Grant 与资产，人工撤权后恢复不补回，重新授权与本地退出／重放及 OP 回调均有断言。OP 界面／上游状态操作需要真实操作侧通过私有 checkpoint 协作，不是无人参与的上游自动化。
- 已读项目 e2e-test 模板并复用现有统一响应／Cookie 认证助手；未采用模板的默认服务地址、默认密码、Bearer 或自动建租户／全前缀删除。必要账号／租户由专属环境预备，工作流仅清理本次创建且重新核验 id／name／owner／tenant 的记录；创建响应不明的遗留按记录的 UUID 名称人工核查。上游状态和预备账号／映射／菜单不批量删除。具体参数、手工交接、Linux DM8、命令及留存要求见 [live-test-runbook.md](./live-test-runbook.md)。
- **E-031（脚本离线验证 PASS，真实业务 NOT_RUN）**：backend 既有 .venv Python 3.11，临时空 YAML；F118_STORAGE=0、F118_E2E=0，运行 .venv/bin/python -m pytest test/sso/test_kunlian_live_harness.py test/integration/test_kunlian_consistency.py test/e2e/test_e2e_kunlian_identity.py -q -rs --disable-warnings --tb=short，**14 passed、5 skipped、7 warnings，0.57s，退出 0**；日志 /tmp/f118-live-harness-current.log。14 项仅证明防误连、缺参拒绝、私有文件／当前 nonce 交接、Cookie／Origin／真实 CSRF 头、不能用 202 替代 Worker 成功、异属资产不删及错误不回显秘密等测试入口契约；HTTP 为 MockTransport，不是新业务 E2E 通过。
- 另以 --confcutdir=test/integration 和 --confcutdir=test/e2e 独立收集／运行两脚本，分别 **4 skipped** 和 **1 skipped**，退出均 0，未加载根 conftest 的预模拟导入链。跳过原因均为显式真实环境开关未启用；这五项全部保持待执行，不计通过。
- 负向入口验证：清除 F118 环境参数，在禁止 socket.connect 的独立子进程中分别开启 F118_STORAGE=1／F118_E2E=1；两入口均在缺参处明确失败，**预期退出 1**，没有触发连接。日志 /tmp/f118-storage-missing-env-guard.log、/tmp/f118-e2e-missing-env-guard.log；这是防误触证据，不是两项真实测试失败或成功。
- 五个新增 Python 文件 Ruff check／format、AST、逐文件架构守卫及 git diff --check PASS。未添加 ignore、skip-on-error、依赖或 CI 框架。原 spec 26 条 AC 正文不变。L1 同代理脚本层自审：命名／AC 指针、既有助手复用、显式 Root 任务头、参数／秘密／清理边界、默认不联网和失败不降级 PASS；完整 T078／T079 仍 NOT_RUN，不以脚本静态自审打勾。
- **真实执行待办**：T078 MySQL／Redis 与 Linux DM8 各自运行并保存版本／JUnit；T079 在通过 T078 后使用真实 Worker、OpenFGA、测试 OP 和操作侧运行。实际工作流 WS 运行、两 SPA、AT 到期、多进程接续与传播时效仍属 T080。T082 依赖未解除，进度仍 **79/83、NOT_READY**；未提交、推送或部署。

## 第二十五批次：规格对照审查与已发现问题修复

- 范围与结论见 [code-review.md](./code-review.md)：同代理审查并修复，六项发现关闭；五类运行问题为主体错配撤销原因不匹配、上游载荷缓冲无有效前置限制、网关敏感回跳查询、真实测试投递不计入总预算、Origin 就绪／装配不一致；另修正 design 的旧八表／未实现描述。未修改已确认 AC、D01—D08、Owner 归属、权限与退出规则，未扩大功能。
- 有效失败证据：/tmp/f118-review-red.log 记录实际 HTTP＋SQL 错配原返回 403、未执行预期撤销，以及内省响应完整读取 8 块后才拒绝；/tmp/f118-review-red-extra.log 记录目录完整读取 16 块、慢 Broker 投递未超预算拒绝和尾斜线 Origin 误报就绪。userinfo 形式用作补充反例；进一步将回调同步设为登记值后，在 Python 和真实 Binder 就绪上下文中复现大写主机／显式默认端口的误报，日志 /tmp/f118-review-origin-red.log、/tmp/f118-review-gateway-origin-red.log，避免只因回调不匹配而伪通过。初版 IDP 测试元组顺序错误产生 TypeError，已先纠正，未当作业务红灯。网关 /tmp/f118-gateway-review-red.log 为九种敏感／编码查询全部未被拒绝（9 failures、0 errors），不是编译失败。
- **E-032**：backend 既有 Python 3.11 venv、临时空 YAML，显式 F118_STORAGE=0／F118_E2E=0；运行 .venv/bin/python -m pytest test/sso/test_kunlian_*.py test/user/test_kunlian_*.py test/tenant/test_kunlian_external_membership.py test/sso/test_sso_api_integration.py test/open_api/test_websocket_tenant_revalidation.py test/open_api/test_websocket_auth.py test/open_api/test_execution_snapshot.py test/permission/test_auth_jwt_token_version.py test/tenant/test_tenant_auth.py test/dsh/test_web_session.py test/integration/test_kunlian_consistency.py test/e2e/test_e2e_kunlian_identity.py -q -rs --disable-warnings --tb=short：**331 passed、5 skipped、23 warnings，18.55s，退出 0**；/tmp/f118-review-backend-regression.log。五个跳过仍为 T078 四组真实存储及 T079 一条真实链路，不是通过。
- R1 当前证据使用实际 browser／session application／Repository：错配返回 SESSION_EXPIRED 401，SQL 会话已失效，原正确 Cookie 也不可再访问。R2 使用可计数的异步字节流：OIDC 超 1 MiB、目录超 4 MiB 立即中止并关闭响应，非读取完整报文后再判断；正常分页、内省、网络失败和旧通道回归一并通过。R4 总异步预算包含首个管理请求、线程内投递和结果操作；关闭客户端隐式发布重试，并设置网络子预算，不取消已投递任务。R5 在后端与网关拒绝非规范 public_origin（尾斜线、userinfo、大写主机或显式默认端口）；不在请求时猜测／补写配置，合法非默认端口仍支持。
- **E-033**：网关 Java 17（JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home），mvn -B '-Dtest=Kunlian*Test,LicenseExpiredGlobalFilterTest' test：**75 tests，0 failures／errors／skipped，BUILD SUCCESS，9.688s**；/tmp/f118-review-gateway-regression.log。包含九个新增 return_to 参数反例，以及原真实 localhost 连接器、日志秘密探针、安全链、Controller、签名、SDK 和旧许可证测试。没有连接真实 OP／后端／Redis。
- **E-034**：frontend 使用既有 Node 24.14.0／pnpm 9.15.9；pnpm --filter bishengchat exec jest --runInBand --runTestsByPath src/api/kunlianSession.test.ts src/hooks/kunlianLogout.test.tsx src/api/clientRequestContract.test.ts src/api/requestUserMessages.test.ts src/utils/loginRedirect.test.ts --coverage=false：**5 suites、40 passed，0.99s**；/tmp/f118-review-client-regression.log。新增普通 401 探测→原退出实际调用链测试在未改产品代码时已通过，因此撤销该疑似发现，只保留回归。未将 testNamePattern 排除的用例误计为真实环境跳过。
- frontend 根 pnpm lint、pnpm typecheck 均退出 0，日志 /tmp/f118-review-frontend-lint.log、/tmp/f118-review-frontend-typecheck.log；原 url.parse 弃用信息未增加依赖或忽略。Platform 产品／测试及三语源／生成物本轮未改，复用 E-029 的 122 项及语言校验，不重复执行。两个仓库 git diff --check、本批九个 Python Ruff check／format 和 AST、十个实际落点逐文件架构守卫 PASS，没有新增诊断或 suppression。
- 文档现状已更新：九表、已实现数据流、已知坑、流式上限、精确 Origin、网关查询拒绝与真实测试总预算；tasks 保持 79/83。原 E-027／E-030／E-031 保留为历史证据；当前受影响产品与脚本结果以 E-032／033／034 为准，AC 矩阵已更新引用。
- 仍未执行真实 MySQL／DM8、Redis／OpenFGA、OP／浏览器、容量或跨进程验证。整体 NOT_READY；T078—T080、T082 继续待执行，没有部署、迁移、真实授权／目录写入、提交或推送。
