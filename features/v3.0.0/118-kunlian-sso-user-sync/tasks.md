# Tasks: 昆联 SSO 与用户同步接入

- **Feature ID**: F118
- **Status**: IN_PROGRESS
- **Updated**: 2026-11-04（Asia/Shanghai）
- **关联**: [spec.md](./spec.md)、[design.md](./design.md)、[版本契约](../release-contract.md)、[SDD Guide](../../../docs/SDD-Guide.md)。
- **授权边界**: 用户已于 2026-11-03 明确“确认任务规划，开始实施”。按已确认任务持续实施；运行开关默认关闭，不操作真实目录、数据库迁移或部署，不提交推送。

## 1. 阶段与执行规则

| 项目 | 状态 | 证据／边界 |
| --- | --- | --- |
| spec.md | CONFIRMED | 用户于 2026-11-03 明确确认；9 项 REQ、26 条 AC 不变 |
| design.md | CONFIRMED | 用户本轮“确认设计，继续编写 tasks.md，先不要改代码。” |
| tasks.md | ✅ 已拆解（PLAN_READY） | 21 项静态自审通过，详见 [tasks-review.md](./tasks-review.md)；不代表任务已执行 |
| 实现 | IN_PROGRESS | 79 / 83；已完成 T001—T077、T081、T083；T078—T080、T082 未完成，见 verification.md |
| 本轮代码审查 | 已审查并修复，本地验证通过 | 五类运行问题及设计快照漂移已修复；见 code-review.md、E-032—E-034；不代表最终 L2／发布门禁通过 |
| 业务验证 V-01 至 V-07 | PARTIAL / NOT_VERIFIED | 已执行本地目录／交接／Owner／HTTP／WS／Celery 验证；真实双 DB、两实例、上游及完整浏览器验收未运行 |

Wave 是可交付的行为批次，内部按 Depends 的 DAG 继续分子批次，不表示所有行可同时启动。涉及同一文件、共享 Router／模型注册或 Owner 状态的任务串行；仅不同文件且无依赖时可并行，本清单不指派额外代理。任何任务开始前仍须读取目标文件、最近层 AGENTS 和当前分支，保护已有修改。

安全、权限、状态机、并发和幂等采用测试先行：先完成对应纯测试任务并确认失败原因有效，再做实现；失败不能来自环境导入错误。基础设施声明无机械测试配对，其行为由后续组覆盖。每个执行子步骤最多两个明确文件；单个任务若横跨既有 Owner 边界，须先在任务中列出子步骤及文件，新增包所需的空 __init__.py 作为机械包标记随所属任务列入 diff。相同文件的后续任务均为明确增量，禁止全文件重写前项交付。

一次验证可以覆盖多个任务与 AC。同一代码状态不重复跑相同命令；批次结束跑受影响模块，最终复用成功证据并补真实边界。业务变更按 V3 风险取最小充分范围，不自行加覆盖率门槛、全仓回归或新 CI 框架。无测试降级；真实环境未提供则记录阻塞，不以 Mock 替代。

### 1.1 路径别名（文件可唯一定位）

当前毕昇实施工作树为 /Users/wenruli/code/project/bisheng/bisheng-kunlian-sso-planning，商业网关实施工作树为 /Users/wenruli/code/project/bisheng/bisheng-gateway-kunlian-sso（原 /Users/wenruli/code/project/bisheng/bisheng-gateway 保持 main 不写入）。以下路径相对各自仓库根，迁移工作树后保持仓库相对路径；后续任务新增文件按实际实施进度创建。

| 别名 | 精确目录 |
| --- | --- |
| B | 毕昇 src/backend/bisheng |
| BT | 毕昇 src/backend/test |
| P | 毕昇 src/frontend/platform/src |
| C | 毕昇 src/frontend/client/src |
| L | 毕昇 src/frontend/packages/locales/src |
| F | 毕昇 features/v3.0.0/118-kunlian-sso-user-sync |
| GROOT | 网关仓库根 |
| G | 网关 src/main/java/com/dataelem/gateway |
| GT | 网关 src/test/java/com/dataelem/gateway |

分类在项目六类（基础设施／后端 Domain／后端 API／Platform／Client／Worker）上增加商业网关、共享文案和集成交付，以容纳已确认的跨仓职责。全局约束只引用 constitution；设计理由见 design 的对应章节，不在任务内复制备选论证。

## 2. 外部条件与执行门禁

| 门禁 | 影响任务／动作 | 解除证据 |
| --- | --- | --- |
| IMPL-00 | 所有代码、测试文件、依赖、配置修改 | 已解除：用户于 2026-11-03 明确授权实施；不包含 OPS-01 的真实运维动作 |
| EXT-01 | T080 真实 OIDC／浏览器；T079 若用真实 IDP | 专属客户端、回调登记、允许范围、网络和受保护凭据均核验 |
| EXT-02 | T079／T080 真实全目录及 Worker 联调 | 全租户只读 Key、有效期与出口放行；不可借其他 Key |
| EXT-03／EXT-04 | T080 时效／workspace／到期验收，T082 READY 和正式启用 | 可测语义及陈旧上限已书面固化；未定时 NOT_READY，离线契约测试只用显式测试配置 |
| ENV-01 | T078、T079 真实存储／权限及 DM8 证据 | 受控 MySQL／Redis／OpenFGA 等环境；DM8 由 Linux 中央回归，不声称已有逐 PR DM8 门禁 |
| OPS-01 | 真实建表、数据操作、部署、生产吊销／回退 | 单独可审查操作计划及用户对具体动作的授权；tasks 完成不自动执行 |

EXT-05 的组织树／组成员／空租户发现／增量／事件保持非目标。首期无刷新、Token Exchange、自动迁移、自动授菜单、人工 Grant 清除、在途任务取消或通用权限引擎。外部条件未闭合不妨碍在获实施授权后实现默认关闭的离线契约，但不能把未知事实设为允许。

## 3. Wave 总览

| Wave | 交付结果 | 任务 | 主要设计／验证 |
| --- | --- | --- | --- |
| 1 | 基础契约与数据声明 | T001—T008 | design §4.4、§6；静态／后续组 |
| 2 | 完整目录与持久会话仓储 | T009—T018 | design §4.3—§4.5；V-01、V-03、V-04、V-06 |
| 3 | 本地 Owner 投影与来源隔离 | T083、T019—T030 | design §4.4、§5；V-02、V-05、V-07 |
| 4 | 后端可信登录与准入服务 | T031—T044 | design §4.5、§6；V-01、V-02、V-04 |
| 5 | HTTP／WS 和 Worker 接线 | T045—T053 | design §4.5—§4.6；V-03、V-04、V-05 |
| 6 | 商业网关 OIDC 与浏览器协议 | T054—T063 | design §4.2、§6.1—§6.3；V-01、V-06、V-07 |
| 7 | 退出闭环与两端交互 | T064—T077 | design §6.3、§6.7；V-01、V-04、V-06、V-07 |
| 8 | 真实边界验证及交付准备 | T078—T082 | design §7；V-01 至 V-07 |

## 4. 任务清单

### Wave 1：基础契约与数据声明

- [x] **T001** [基础设施] 声明目录与批次模型并登记发现路径
  - **文件**: `B/sso_sync/domain/models/kunlian.py`、`B/core/database/tenant_filter.py`
  - **逻辑与交付**: 声明 ConnectionState、SyncBatch、DirectoryTenant、DirectoryMember；定义 ROOT 控制面范围、批次唯一键、租约／fence、状态和双 DB 字段；core 只登记模型模块字符串。
  - _Requirements: REQ-03, REQ-06, REQ-09_
  - _Acceptance: AC-05, AC-06, AC-15, AC-16, AC-26_
  - _Verification: V-03；静态检查 JsonType、有界索引和模型发现；真实创建／回滚兼容证据交 T078，不用 SQLite 代替 DM8。_
  - _Depends: NONE_
  - _Boundary: 只新增独立表，不改已有表、不执行建表或迁移；回退关闭功能并保留新表。_

- [x] **T002** [基础设施] 增补身份、映射、会话与回执模型
  - **文件**: `B/sso_sync/domain/models/kunlian.py`
  - **逻辑与交付**: 在 T001 文件内增补 TenantBinding、IdentityBinding、WebSession、HandoffReceipt；约束摘要与原文复核、固定目标租户、会话哈希／密文、auth_epoch、投影修订、local_override 和单次票据。
  - _Requirements: REQ-02, REQ-04, REQ-05, REQ-07, REQ-09_
  - _Acceptance: AC-03, AC-07, AC-09, AC-10, AC-18, AC-26_
  - _Verification: V-02, V-04, V-06；模型唯一键、外键和密文列检查；并发唯一性由 T017、T078 提供行为证据。_
  - _Depends: T001_
  - _Boundary: 不向 User/Tenant 加列，不存明文令牌；保留表回退，不删除历史事实。_

- [x] **T003** [基础设施] 定义跨模块协议与严格 DTO
  - **文件**: `B/sso_sync/domain/schemas/kunlian.py`、`B/sso_sync/application/kunlian.py`
  - **逻辑与交付**: 定义可信交接、验证后身份／租户映射、准入上下文、同步请求与运行状态、退出 next_action；声明 design §6.4 六个协议、手工禁用来源记录及管理查询窄协议和 Owner 边界。API 不接收可自称身份的普通用户字段。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-06, REQ-07, REQ-09_
  - _Acceptance: AC-02, AC-04, AC-07, AC-13, AC-24_
  - _Verification: V-01, V-02, V-04；DTO 必填／未知字段／状态枚举校验；后续业务测试调用同一协议，不另造不兼容测试接口。_
  - _Depends: NONE_
  - _Boundary: 此步只声明契约；application 不暴露 ORM、不建立第二套权限框架。_

- [x] **T004** [基础设施] 扩展后端关闭默认值与就绪策略
  - **文件**: `B/core/config/sso_sync.py`
  - **逻辑与交付**: 在已有 sso_sync.kunlian 子配置声明目录／登录开关、登记身份范围、秘密引用、端点白名单及调用预算；缺目录陈旧上限、workspace／到期语义版本或多租户未开启则 NOT_READY。
  - _Requirements: REQ-03, REQ-04, REQ-06, REQ-09_
  - _Acceptance: AC-07, AC-19, AC-24, AC-25_
  - _Verification: V-03, V-04, V-07；默认值／缺配置拒绝的行为断言由 T031、T035、T043 覆盖。_
  - _Depends: NONE_
  - _Boundary: 不改运行配置，不给 EXT-03／EXT-04 宽松默认，不新增顶层默认启用键。_

- [x] **T005** [基础设施] 落地预留业务码与中文错误文案
  - **文件**: `B/common/errcode/sso_sync.py`、`L/api_errors/zh-Hans.json`
  - **逻辑与交付**: 实施前重新扫描发版线占用，再定义 design §6.7 的 19320—19329，固定 reason_code 与真实 HTTP 状态；中文文案只放共享 api_errors。
  - _Requirements: REQ-01, REQ-04, REQ-06, REQ-07, REQ-09_
  - _Acceptance: AC-02, AC-07, AC-11, AC-13, AC-19, AC-21, AC-24, AC-25_
  - _Verification: V-01, V-03, V-04, V-06；错误码唯一性与 reason／HTTP 对照；后续接口测试证明状态语义。_
  - _Depends: NONE_
  - _Boundary: 占用冲突须先修设计登记，不能覆盖他人编码；与 T006 同批交付。_

- [x] **T006** [基础设施] 补齐英文及日文错误文案
  - **文件**: `L/api_errors/en.json`、`L/api_errors/ja.json`
  - **逻辑与交付**: 补齐 T005 同批全部键；保持三语键一致，生成物统一在 T077 构建，不手改各应用 api_errors 产物。
  - _Requirements: REQ-09_
  - _Acceptance: AC-13, AC-14, AC-24_
  - _Verification: V-07；与 T005 一起进行三语键一致检查，最终复用 check-i18n 证据。_
  - _Depends: T005_
  - _Boundary: 不得提交只有部分语言的错误码批次。_

- [x] **T007** [基础设施] 网关依赖及独立配置声明
  - **文件**: `GROOT/pom.xml`、`G/config/KunlianSsoProperties.java`
  - **执行子步骤**: ① 上述两文件声明 Boot 管理的 OAuth2 Client／JOSE 与默认关闭属性。② `GT/config/KunlianSsoPropertiesTest.java` 用实际 Binder 验证前缀、配置就绪、精确 Origin、默认关闭和秘密引用。全站自动安全链隔离仍由 T060／T061 验证，本项不代表可以部署。
  - **逻辑与交付**: 按现有 Boot BOM 选择 Reactive OAuth2 Client／JOSE、核验许可证并记录解析版本；声明 custom.kunlian、默认关闭、精确回调／Origin 与独立秘密引用。
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-13, AC-14, AC-25_
  - _Verification: V-01, V-07；依赖树与编译、关闭默认值；安全链隔离另由 T060 先测。_
  - _Depends: NONE_
  - _Boundary: 不整体升级依赖、不改运行 application 配置，不开启全站安全默认链；只在未来获实施授权后安装依赖。_

- [x] **T008** [基础设施] 补可控目录与时钟测试辅助
  - **文件**: `BT/sso/kunlian_fakes.py`
  - **逻辑与交付**: 复用 test/conftest.py 的现有 SQL／Redis mock，增加可控分页、网络错误、请求计数、冻结时间及暂停点；不新建通用测试框架。用于多任务共享的独立失败及并发观察。
  - _Requirements: REQ-01, REQ-04, REQ-06_
  - _Acceptance: AC-02, AC-06, AC-07, AC-16, AC-19, AC-26_
  - _Verification: V-01, V-03, V-04；辅助响应可复现分页错误、时间推进和内省调用次数；真实锁语义留 T078。_
  - _Depends: T003_
  - _Boundary: 纯测试辅助，无生产实现；只能证明可控契约，不伪装真实 IDP 或数据库锁语义。_


### Wave 2：完整目录与持久会话仓储

- [x] **T009** [后端 Domain] 先写同步租约与暂存存储测试
  - **文件**: `BT/sso/test_kunlian_directory.py`
  - **逻辑与交付**: 参数化同 connection 多执行者、租约过期、旧 fence 写页、续租和恢复；校验重复触发合并请求版本以及失败后 active_batch 不变；续接时 Key 版本变化拒绝并留下脱敏失败关联。
  - **覆盖 AC:** AC-06, AC-16, AC-19, AC-26
  - _Requirements: REQ-06, REQ-09_
  - _Acceptance: AC-06, AC-16, AC-19, AC-26_
  - _Verification: V-03；T010 前记录有效失败原因；同一批证据在 T016 复用。_
  - _Depends: T001, T003, T008_
  - _Boundary: 只写测试；观察 SQL 状态和最终目录，不按内部方法数量生成用例。_

- [x] **T010** [后端 Domain] 实现同步请求、租约和分页暂存仓储
  - **文件**: `B/sso_sync/domain/repositories/kunlian.py`
  - **逻辑与交付**: 提供 request_sync、claim_or_renew_lease、stage_page、mark_failed／abandoned；每次写核对 fence 和租约；只清已覆盖的请求版本，游标密文绑定 Key 版本及 page_size。
  - _Requirements: REQ-06, REQ-09_
  - _Acceptance: AC-06, AC-16, AC-19, AC-26_
  - _Verification: V-03；T009 由红转绿；同轮 Key 更换不能续接旧游标。_
  - _Depends: T009, T004_
  - _Boundary: SQL 只在 Repository；Redis 只辅助去重，不是同步真相；不修改 User／Grant。_

- [x] **T011** [后端 Domain] 先写完整发布与准入版本竞争测试
  - **文件**: `BT/sso/test_kunlian_directory.py`
  - **逻辑与交付**: 在 T009 同文件增量加入整轮校验、重复／冲突页、缺成员 UNKNOWN、停用和恢复、输入不变的新批次；断言一次发布指针与 auth_epoch、旧 Worker 无法 finalize；同名跨租户绑定独立、更名保留稳定身份，角色摘要不扩大登记登录范围，映射冲突整轮失败。
  - **覆盖 AC:** AC-03, AC-05, AC-06, AC-09, AC-15, AC-16, AC-18, AC-20, AC-26
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06, REQ-08_
  - _Acceptance: AC-03, AC-05, AC-06, AC-09, AC-15, AC-16, AC-18, AC-20, AC-26_
  - _Verification: V-02, V-03, V-05；发布失败保留旧完整指针；已发布停用不因投影失败回滚。_
  - _Depends: T010, T002_
  - _Boundary: 纯测试；不把一轮缺失当硬删除，不把 batch_id 当 source_revision。_

- [x] **T012** [后端 Domain] 实现完整目录发布与只读绑定查询
  - **文件**: `B/sso_sync/domain/repositories/kunlian.py`
  - **逻辑与交付**: 提供受限 record_manual_override 的 Repository 更新，原子递增准入版本；提供 validate_staged_batch／publish_directory 事务：发布完整批次、更新关联准入和 epoch；source_revision 按输入指纹计算。提供受限控制面查询与映射 CAS，账号物化后只可停用绑定。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-06_
  - _Acceptance: AC-03, AC-05, AC-06, AC-09, AC-15, AC-16, AC-18, AC-20, AC-26_
  - _Verification: V-02, V-03, V-05；T011 通过；映射冲突、旧修订和长 ID 摘要冲突均拒绝。_
  - _Depends: T011_
  - _Boundary: 只能写 F118 数据；没有真实组织／组事实不推理生成；不以普通 Endpoint 开跨租户 bypass。_

- [x] **T013** [后端 Domain] 先写目录 HTTP 契约与故障测试
  - **文件**: `BT/sso/test_kunlian_directory_client.py`
  - **逻辑与交付**: 验证 X-API-Key、page_size／page_token 及成员详情 id；断言无 Cookie／Bearer／Origin／all_tenants／updated_since，401／403／HTML／游标失效／临时故障可区分。
  - **覆盖 AC:** AC-05, AC-15, AC-16, AC-19, AC-24
  - _Requirements: REQ-03, REQ-06, REQ-09_
  - _Acceptance: AC-05, AC-15, AC-16, AC-19, AC-24_
  - _Verification: V-03；断言请求字节／头和重试预算，永久错误不重试，不跟随跨域跳转。_
  - _Depends: T004, T008_
  - _Boundary: 只写客户端契约测试；不调用真实昆联或借用其他 Key。_

- [x] **T014** [后端 Domain] 实现目录专用客户端
  - **文件**: `B/sso_sync/domain/clients/kunlian.py`
  - **逻辑与交付**: 用独立 httpx 客户端实现列表／详情解析与原样续传；只允许白名单端点，使用单轮固定秘密引用和有限 GET 退避；保持 id、subject、外部租户和 opaque version 原义。
  - _Requirements: REQ-03, REQ-06, REQ-09_
  - _Acceptance: AC-05, AC-15, AC-16, AC-19, AC-24_
  - _Verification: V-03；T013 通过，失败不能返回成功空目录。_
  - _Depends: T013, T005, T006_
  - _Boundary: 不复用通用 org_sync 的认证／DTO，不在日志记录 Key、游标和完整载荷。_

- [x] **T015** [后端 Domain] 先写全轮目录编排与恢复测试
  - **文件**: `BT/sso/test_kunlian_directory.py`
  - **逻辑与交付**: 增量覆盖多页成功、首／中／末页失败、持久请求覆盖边界、崩溃重启、成功空目录与失败未知；目录发布成功但投影 PENDING 必须单列。
  - **覆盖 AC:** AC-05, AC-06, AC-15, AC-16, AC-19, AC-24, AC-26
  - _Requirements: REQ-03, REQ-06, REQ-09_
  - _Acceptance: AC-05, AC-06, AC-15, AC-16, AC-19, AC-24, AC-26_
  - _Verification: V-03；断言全部获准租户完整保存、失败指针不变、状态查询不混淆目录与投影。_
  - _Depends: T012, T014_
  - _Boundary: 纯编排测试，复用 T009／T011 案例证据，不重复复制仓储断言。_

- [x] **T016** [后端 Domain] 实现目录服务全轮编排与需求合并
  - **文件**: `B/sso_sync/domain/services/kunlian_directory.py`、`B/sso_sync/application/kunlian.py`
  - **逻辑与交付**: 串联租约、分页、校验、发布及投影待办；application 绑定同步／发布及 record_manual_override(identity, disabled, expected_revision) 窄协议，手工状态通过本服务委托 Repository；request_directory_sync 合并登录／管理／Beat 触发；错误按原因记录 request_id／fence／计数，不直接在 HTTP 请求拉全目录。
  - _Requirements: REQ-03, REQ-06, REQ-09_
  - _Acceptance: AC-05, AC-06, AC-15, AC-16, AC-19, AC-24, AC-26_
  - _Verification: V-03；T015 通过；基础目录状态可查询，投影状态在 T030、T044 接续。_
  - _Depends: T015_
  - _Boundary: Owner 投影异步恢复，不把排队或拿锁标为成功；无账号硬删除。_

- [x] **T017** [后端 Domain] 先写会话、回执与单次票据仓储测试
  - **文件**: `BT/sso/test_kunlian_session_store.py`
  - **逻辑与交付**: 覆盖 handoff 同摘要幂等、异体冲突、并发最多一个会话、固定绝对到期；多登录策略、auth_epoch、撤销只增不退、票据单次兑换和跨浏览器拒绝。
  - **覆盖 AC:** AC-02, AC-07, AC-09, AC-10, AC-13, AC-18, AC-21, AC-26
  - _Requirements: REQ-01, REQ-04, REQ-05, REQ-07, REQ-09_
  - _Acceptance: AC-02, AC-07, AC-09, AC-10, AC-13, AC-18, AC-21, AC-26_
  - _Verification: V-01, V-04, V-06；检查密文／哈希持久化及事务回滚；双实例唯一性另交 T078。_
  - _Depends: T002, T008_
  - _Boundary: 只写测试；存储层不发起 OIDC 换码或授业务权限。_

- [x] **T018** [后端 Domain] 实现会话与交接回执仓储
  - **文件**: `B/sso_sync/domain/repositories/kunlian.py`
  - **逻辑与交付**: 在目录仓储后增量加入 issue_or_replay_handoff、load_admission_facts、revoke_session、issue／redeem_logout_ticket 与过期状态维护；回执保留同会话引用和原硬期限，票据仅存哈希。
  - _Requirements: REQ-01, REQ-04, REQ-05, REQ-07, REQ-09_
  - _Acceptance: AC-02, AC-07, AC-09, AC-10, AC-13, AC-18, AC-21, AC-26_
  - _Verification: V-01, V-04, V-06；T017 通过；此前目录仓储成功证据仅在受影响方法变化时重跑。_
  - _Depends: T012, T017_
  - _Boundary: 秘密使用现有加密设施；SQL／解密失败拒绝，不生成新密钥或新身份兜底。_


### Wave 3：本地 Owner 投影与来源隔离

- [x] **T083** [基础设施] 声明用户 Owner 的持久投影栅栏
  - **文件**: `B/user/domain/models/external_identity_projection.py`、`B/core/database/tenant_filter.py`
  - **逻辑与交付**: 声明 UserExternalIdentityProjection，记录稳定身份原文与摘要、操作 ID、本地单调 fence、已应用源修订及 user_id；与 User 同一 Owner UoW 校验、更新。显式登记模型发现，不改变 User/Tenant 已有列。
  - _Requirements: REQ-02, REQ-05, REQ-06, REQ-09_
  - _Acceptance: AC-03, AC-09, AC-16, AC-18, AC-23, AC-26_
  - _Verification: V-02, V-03, V-05；模型及 MySQL DDL 检查；旧操作迟到与提交后崩溃在 T019、T029 测试，真实锁与 DM8 仍为 T078。_
  - _Depends: T002_
  - _Boundary: 用户于 2026-11-03 单独批准补充设计。只新增独立表声明，回退关闭昆联投影并保留状态，不实际建表、不部署。_

- [x] **T019** [后端 Domain] 先写 user Owner 影子账号投影测试
  - **文件**: `BT/user/test_kunlian_external_identity.py`
  - **逻辑与交付**: 覆盖改名／同名／跨来源和跨租户、摘要冲突、预期修订、创建无 UserRole／组／菜单、停用来源及幂等重试；验证不认领历史账号和不改资产。
  - **覆盖 AC:** AC-03, AC-09, AC-18, AC-20, AC-22, AC-23
  - _Requirements: REQ-02, REQ-05, REQ-08, REQ-09_
  - _Acceptance: AC-03, AC-09, AC-18, AC-20, AC-22, AC-23_
  - _Verification: V-02, V-05；验证人工授权和原账号主键／source 保持，输出唯一 shadow user 引用。_
  - _Depends: T003, T008_
  - _Boundary: 纯测试，以 user Owner 公开协议观察业务结果；覆盖持久预留 fence、旧操作迟到和原子应用回执。_

- [x] **T020** [后端 Domain] 实现 user Owner 独立投影能力
  - **文件**: `B/user/domain/repositories/external_identity_projection.py`、`B/user/application/external_identity.py`
  - **逻辑与交付**: 按已确认补充设计提供操作预留和带 fence 的 ensure_external_shadow(identity, expected_revision)，新建 source=kunlian 的无默认角色自然人，更新允许的自身资料／同步停用标记；返回投影结果，不把 ORM 暴露给 F118。
  - _Requirements: REQ-02, REQ-05, REQ-08, REQ-09_
  - _Acceptance: AC-03, AC-09, AC-18, AC-20, AC-22, AC-23_
  - _Verification: V-02, V-05；T019 通过；Owner 独立提交不等于跨服务原子成功。_
  - _Depends: T019, T002, T083_
  - _Boundary: 不调用 add_user_and_default_role，不自行写 Grant，不覆盖 manual disable。_

- [x] **T021** [后端 Domain] 先写保留来源与手工停用防绕过测试
  - **文件**: `BT/user/test_kunlian_source_guards.py`、`BT/sso/test_sso_cross_source_user.py`
  - **逻辑与交付**: 验证普通创建／修改不能侵入 kunlian，旧 login-sync fallback 不能认领后改 source；手工禁用记录 local_override，目录 ACTIVE 不能解除；其他来源保留原匹配合同。
  - **覆盖 AC:** AC-03, AC-14, AC-17, AC-18, AC-23, AC-25
  - _Requirements: REQ-02, REQ-05, REQ-09_
  - _Acceptance: AC-03, AC-14, AC-17, AC-18, AC-23, AC-25_
  - _Verification: V-02, V-05, V-07；先于 T022 形成拒绝路径失败证据。_
  - _Depends: T020_
  - _Boundary: 纯测试；同时覆盖直接管理入口和旧 SSO 入口。_

- [x] **T022** [后端 Domain] 接入 user 手工状态与旧 SSO 来源保护
  - **文件／执行子步骤**（补齐 design §4.6 已含的真实管理入口，不新增能力或 AC）:
    1. user Owner 守卫与人工状态写入：`B/user/domain/repositories/external_identity_projection.py`、`B/user/application/external_identity.py`。
    2. F118 身份锁及受限协调：`B/sso_sync/domain/repositories/kunlian.py`、`B/sso_sync/application/kunlian.py`。
    3. 普通用户写入及旧 SSO 保护：`B/user/domain/services/user.py`、`B/sso_sync/domain/services/login_sync_service.py`。
    4. 已有权限闸门后的账号启停接线：`B/user/api/user.py`；退出相关增量仍归 T066。
  - **逻辑与交付**: 在实际用户创建／修改／停用入口通过受限 application 记录 F118 manual override，调用 user Owner 更新自身用户状态，并拒绝对保留来源的创建、认领及改写；手工停用与投影按相同身份锁顺序及预期修订协调。
  - _Requirements: REQ-02, REQ-05, REQ-09_
  - _Acceptance: AC-03, AC-14, AC-17, AC-18, AC-23, AC-25_
  - _Verification: V-02, V-05, V-07；T021 通过，旧 sso／wecom 正常样例继续有效。_
  - _Depends: T021, T016_
  - _Boundary: 新增 SQL 放 user Repository，由 T020 能力承接；不顺手重写旧 SSO 编排。_

- [x] **T023** [后端 Domain] 先写 tenant Owner 显式成员关系测试
  - **文件**: `BT/tenant/test_kunlian_external_membership.py`
  - **逻辑与交付**: 测试只绑定现有有效本地租户、映射唯一、重复幂等、跨租户拒绝、已物化目标不可换绑；无部门账号不落 Root，不自动创建业务租户。
  - **覆盖 AC:** AC-03, AC-04, AC-17, AC-20, AC-23
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-08_
  - _Acceptance: AC-03, AC-04, AC-17, AC-20, AC-23_
  - _Verification: V-02, V-05；断言已有关联／业务资源不迁移，外部租户停用不关闭整个本地 Tenant。_
  - _Depends: T003, T008_
  - _Boundary: 只写测试；外部 UUID 与本地 tenant_id 不能混用。_

- [x] **T024** [后端 Domain] 实现 tenant Owner 成员关联协议
  - **文件**: `B/tenant/domain/repositories/external_membership.py`、`B/tenant/application/external_membership.py`
  - **逻辑与交付**: 实现 ensure_external_membership(user_id, verified_mapping)，通过既有成员生命周期持久化首个明确关联；限定本地租户上下文，拒绝迁移和无效映射。
  - _Requirements: REQ-02, REQ-03, REQ-05, REQ-08_
  - _Acceptance: AC-03, AC-04, AC-17, AC-20, AC-23_
  - _Verification: V-02, V-05；T023 通过；失败结果可供 F118 保持 projection PENDING／FAILED。_
  - _Depends: T023, T020_
  - _Boundary: 不伪造部门，不直接构造 FGA tuple；如需权限投影仍由原 Owner application 处理。_

- [x] **T025** [后端 Domain] 先写昆联租户权威与原路径兼容测试
  - **文件／执行子步骤**:
    1. 旧服务接线：`BT/tenant/test_tenant_resolver.py`、`BT/user/test_user_tenant_sync_service.py`。
    2. 窄协议存储边界：`BT/sso/test_kunlian_directory.py`、`BT/tenant/test_kunlian_external_membership.py`。
  - **逻辑与交付**: 增量验证 Kunlian 委托明确映射、映射未知拒绝、部门为空不回 Root；普通本地用户继续按现有部门计算，不迁移既有资源。
  - **覆盖 AC:** AC-03, AC-04, AC-14, AC-17, AC-23
  - _Requirements: REQ-02, REQ-03, REQ-09_
  - _Acceptance: AC-03, AC-04, AC-14, AC-17, AC-23_
  - _Verification: V-02, V-07；T026 前失败应来自新外部身份权威未接线。_
  - _Depends: T024_
  - _Boundary: 只增相关案例，不复制已有部门分支全套。_

- [x] **T026** [后端 Domain] 接入 resolver 与成员同步豁免
  - **文件／执行子步骤**:
    1. F118 当前映射窄读协议：`B/sso_sync/domain/repositories/kunlian.py`、`B/sso_sync/application/kunlian.py`。
    2. tenant Owner 复核来源和成员：`B/tenant/domain/repositories/external_membership.py`、`B/tenant/application/external_membership.py`。
    3. 接入旧服务：`B/tenant/domain/services/tenant_resolver.py`、`B/tenant/domain/services/user_tenant_sync_service.py`。
  - **逻辑与交付**: 对 source=kunlian 调外部映射协议，禁止部门推导覆盖；保留旧账号的原分支、缓存失效及资源转移规则。
  - _Requirements: REQ-02, REQ-03, REQ-09_
  - _Acceptance: AC-03, AC-04, AC-14, AC-17, AC-23_
  - _Verification: V-02, V-07；T025 通过。_
  - _Depends: T025_
  - _Boundary: 只在已有服务接 application，不加新 DAO 查询或业务权限捷径。_

- [x] **T027** [后端 Domain] 先写批量租户对账不改昆联归属测试
  - **文件**: `BT/tenant/test_user_tenant_reconcile_service.py`、`BT/tenant/test_tenant_reconcile_task.py`
  - **逻辑与交付**: 验证后台批量候选排除昆联部门漂移修正，映射停用不改成 Root；由真实已注册 tenant_reconcile Worker 调用服务确认豁免生效。
  - **覆盖 AC:** AC-03, AC-14, AC-23, AC-26
  - _Requirements: REQ-02, REQ-03, REQ-09_
  - _Acceptance: AC-03, AC-14, AC-23, AC-26_
  - _Verification: V-02, V-07；通过实际 Worker 调用替身确认候选／写入结果，无需新增重复 cron。_
  - _Depends: T026_
  - _Boundary: 纯测试；服务被调用不等于生产调度已验证。_

- [x] **T028** [后端 Domain] 实现批量对账候选豁免
  - **文件**: `B/tenant/domain/services/user_tenant_reconcile_service.py`、`B/tenant/domain/repositories/external_membership.py`
  - **逻辑与交付**: 通过 tenant Owner Repository 获取本批 source／外部关联，跳过部门期望值计算；普通用户继续原对账合同，避免新增 UserDao classmethod。
  - _Requirements: REQ-02, REQ-03, REQ-09_
  - _Acceptance: AC-03, AC-14, AC-23, AC-26_
  - _Verification: V-02, V-07；T027 通过，Worker 原有租户恢复方式保持。_
  - _Depends: T027_
  - _Boundary: 仅修改新增外部来源处理，不扫描或迁移历史全表数据。_

- [x] **T029** [后端 Domain] 先写投影收敛、手工禁用与发布竞争测试
  - **文件**: `BT/sso/test_kunlian_projection.py`
  - **逻辑与交付**: 模拟 user 已提交而 tenant 失败、进程崩溃、旧投影回执晚到、手工禁用与新停用发布竞争；检查相关身份拒绝、其他完成身份可进入，人工 Grant 和资产不变。
  - **覆盖 AC:** AC-03, AC-09, AC-17, AC-18, AC-20, AC-22, AC-23, AC-24, AC-26
  - _Requirements: REQ-02, REQ-05, REQ-06, REQ-08, REQ-09_
  - _Acceptance: AC-03, AC-09, AC-17, AC-18, AC-20, AC-22, AC-23, AC-24, AC-26_
  - _Verification: V-02, V-03, V-05；断言 binding 行串行、锁顺序及 expected source_revision 的 CAS 结果；真实竞争由 T078 补证。_
  - _Depends: T018, T022, T024, T028_
  - _Boundary: 纯测试；不能用一把进程内锁冒充分布式保证。_

- [x] **T030** [后端 Domain] 实现 Owner 投影与恢复编排
  - **文件**: `B/sso_sync/domain/services/kunlian_projection.py`、`B/sso_sync/domain/repositories/kunlian.py`（投影冻结、同事务活性复核及完成 CAS）
  - **逻辑与交付**: 调用 user／tenant Owner 幂等收敛；同身份投影和发布采用一致锁顺序、有界等待和修订回执。保留 UNMAPPED，未完成不准入，失败不回滚完整目录及已生效停用。
  - _Requirements: REQ-02, REQ-05, REQ-06, REQ-08, REQ-09_
  - _Acceptance: AC-03, AC-09, AC-17, AC-18, AC-20, AC-22, AC-23, AC-24, AC-26_
  - _Verification: V-02, V-03, V-05；T029 通过；部分 Owner 提交不冒充全链路完成。_
  - _Depends: T029_
  - _Boundary: F118 只写自身修订／状态；不删人工 Grant、不创建组织关系、不取消在途工作流。_


### Wave 4：后端可信登录与准入服务

- [x] **T031** [后端 Domain] 先写 ID Token 复核和内省客户端测试
  - **文件**: `BT/sso/test_kunlian_idp_client.py`
  - **逻辑与交付**: 参数化 RS256／kid／iss／aud／azp／nonce／exp 与登记端点限制；测试 opaque AT 内省、Basic 认证、active／sub／client／租户／sid／workspace／有效期匹配及超时拒绝。
  - **覆盖 AC:** AC-02, AC-07, AC-13, AC-17, AC-25
  - _Requirements: REQ-01, REQ-04, REQ-09_
  - _Acceptance: AC-02, AC-07, AC-13, AC-17, AC-25_
  - _Verification: V-01, V-04；公钥可缓存、允许决定不可缓存；未知 kid 受控刷新一次；日志不含凭据。_
  - _Depends: T004, T008, T014_
  - _Boundary: 纯客户端契约；EXT-04 未定使用明确测试契约，不回填宽松生产策略。_

- [x] **T032** [后端 Domain] 实现后端 IDP 验签与内省能力
  - **文件**: `B/sso_sync/domain/clients/kunlian.py`
  - **逻辑与交付**: 在目录客户端文件中增加独立认证客户端和现有 PyJWT／cryptography 验证；Discovery／JWKS allowlist，严格令牌关联，有限超时与池预算，拒绝任意 jku 和不支持的身份声明。
  - _Requirements: REQ-01, REQ-04, REQ-09_
  - _Acceptance: AC-02, AC-07, AC-13, AC-17, AC-25_
  - _Verification: V-01, V-04；T031 通过，新增认证分支不改变 T013 的目录头部约束。_
  - _Depends: T031_
  - _Boundary: 目录 Key 与 Basic 完全分离；不解析 AT 为 JWT，不缓存 active=true。_

- [x] **T033** [后端 Domain] 先写新内部签名及重放拒绝测试
  - **文件**: `BT/sso/test_kunlian_trust.py`
  - **逻辑与交付**: 给定确定性签名向量，验证 raw JSON 字节、METHOD／canonical path／key id／时间窗／nonce／摘要；重复 nonce、错密钥、Redis 失败和不可信来源均拒绝。
  - **覆盖 AC:** AC-02, AC-13, AC-25
  - _Requirements: REQ-01, REQ-09_
  - _Acceptance: AC-02, AC-13, AC-25_
  - _Verification: V-01, V-04；新旧协议完全隔离，签后重序列化必失败。_
  - _Depends: T003, T008_
  - _Boundary: 纯测试；旧 F014 签名向量不修改。_

- [x] **T034** [后端 Domain] 实现昆联交接专用信任校验
  - **文件**: `B/sso_sync/domain/services/kunlian_login.py`
  - **逻辑与交付**: 先实现 verify_internal_request 信任边界：独立密钥、恒时比较、时间窗、原子 nonce 消费及登记来源，输出 TrustedHandoff；错误统一转换为稳定原因，不记录令牌报文。
  - _Requirements: REQ-01, REQ-09_
  - _Acceptance: AC-02, AC-13, AC-25_
  - _Verification: V-01, V-04；T033 通过；业务登录编排稍后在 T040 增量加入。_
  - _Depends: T033, T005, T006_
  - _Boundary: 只补新服务的校验部分，不修改旧 hmac_auth 的签名串或放行逻辑。_

- [x] **T035** [后端 Domain] 先写当前资格与每次在线准入测试
  - **文件**: `BT/sso/test_kunlian_admission.py`
  - **逻辑与交付**: 验证 SQL 会话／绑定／连接／投影／手工状态／目录 age，再实际计数内省；停用、UNKNOWN、恢复旧 epoch、声明错配、必需依赖失败均拒绝。AT 到期可保留退出能力但不能读业务。
  - **覆盖 AC:** AC-07, AC-08, AC-09, AC-11, AC-13, AC-17, AC-18, AC-25, AC-26
  - _Requirements: REQ-04, REQ-05, REQ-07, REQ-09_
  - _Acceptance: AC-07, AC-08, AC-09, AC-11, AC-13, AC-17, AC-18, AC-25, AC-26_
  - _Verification: V-04, V-05, V-06；断言每次 admit 调用所需内省次数及持久 REAUTH_REQUIRED／REVOKED 终态。_
  - _Depends: T018, T030, T032_
  - _Boundary: 纯测试；HTTP 单请求可共享结果，跨请求或 WS 新消息不能共享允许。_

- [x] **T036** [后端 Domain] 实现统一准入与会话版本处理
  - **文件／执行子步骤**（落实原设计的当前 Owner 资格，不跨 Owner 查询）:
    1. 准入服务与窄 application：`B/sso_sync/domain/services/kunlian_session.py`、`B/sso_sync/application/kunlian.py`。
    2. 当前目录／固定签发事实与 REAUTH_REQUIRED：`B/sso_sync/domain/repositories/kunlian.py`；认证客户端独立内省上下文类型：`B/sso_sync/domain/clients/kunlian.py`。
    3. 当前用户资格与不可变主体：`B/user/domain/repositories/external_identity_projection.py`、`B/user/application/external_identity.py`。
    4. 当前租户成员窄读包装：`B/tenant/application/external_membership.py`。
    5. 当前用户 SQL／主体边界证据增量：`BT/user/test_kunlian_external_identity.py`。
  - **逻辑与交付**: 实现 admit_kunlian_session、revoke_session、受限本地会话／CSRF 派生；组合 SQL 当前资格与在线内省，返回不可变当前 UserPayload。仅协议辅助可绕开过期 AT，不提供业务数据。
  - _Requirements: REQ-04, REQ-05, REQ-07, REQ-09_
  - _Acceptance: AC-07, AC-08, AC-09, AC-11, AC-13, AC-17, AC-18, AC-25, AC-26_
  - _Verification: V-04, V-05, V-06；T035 通过；应用协议只按已验证引用窄读控制面。_
  - _Depends: T035, T016_
  - _Boundary: 无 Redis／SQL／解密故障放行；不在这里代替 F048 判资源动作。_

- [x] **T037** [后端 Domain] 先写专属 JWT 签发与密码绕过测试
  - **文件**: `BT/user/test_kunlian_auth.py`、`BT/tenant/test_tenant_auth.py`（仅修正当前 Settings 测试绑定，保留旧 JWT 断言）
  - **逻辑与交付**: 覆盖 auth_source／kunlian_session 标记、固定签发上下文与绝对期限、任一标记缺失仍需严格准入；专属来源账号不能密码／重设后变普通会话；其他来源保持 JWT 合同。
  - **覆盖 AC:** AC-01, AC-02, AC-08, AC-11, AC-14, AC-17, AC-25
  - _Requirements: REQ-01, REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-08, AC-11, AC-14, AC-17, AC-25_
  - _Verification: V-01, V-04, V-06, V-07；重复交接不延长本地 exp；source 被伪装不能回退普通认证。_
  - _Depends: T022, T036_
  - _Boundary: 纯测试；不增加外部令牌到 JWT 或前端可读主体。_

- [x] **T038** [后端 Domain] 实现受控本地签发与专属来源登录约束
  - **文件**: `B/user/domain/services/auth.py`、`B/user/domain/services/user.py`
  - **逻辑与交付**: 增加昆联引用及不可变因果字段，支持 Owner 固定绝对签发期限；阻断专属来源密码和重设绕过。保留普通 JWT、DSH 和既有 expires_in 默认行为。
  - _Requirements: REQ-01, REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-08, AC-11, AC-14, AC-17, AC-25_
  - _Verification: V-01, V-04, V-06, V-07；T037 通过，Cookie 属性由 T063 配对落地。_
  - _Depends: T037_
  - _Boundary: 不新增普通认证兜底，不将工作流执行快照当浏览器令牌。_

- [x] **T039** [后端 Domain] 先写可信交接登录与未就绪闭环测试
  - **文件**: `BT/sso/test_kunlian_login_contract.py`
  - **逻辑与交付**: 从受信报文验证到签发：验签／内省、稳定绑定、目录／映射／投影检查、无菜单拒绝、缺目录合并补同步并本次失败；同 handoff 重试同会话、冲突／已撤销结果拒绝。
  - **覆盖 AC:** AC-01, AC-02, AC-03, AC-04, AC-13, AC-20, AC-22, AC-26
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-08, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-13, AC-20, AC-22, AC-26_
  - _Verification: V-01, V-02, V-05；验证登录不自动建普通账号、不授菜单，不回 Root。_
  - _Depends: T034, T036, T038_
  - _Boundary: 纯测试；未知换码结果不能重用 code，内部幂等重试与浏览器重放区分。_

- [x] **T040** [后端 Domain] 完成交接登录业务编排
  - **文件／执行子步骤**:
    1. 交接编排与 application：`B/sso_sync/domain/services/kunlian_login.py`、`B/sso_sync/application/kunlian.py`。
    2. 自身资格／版本状态与注册配置：`B/sso_sync/domain/repositories/kunlian.py`、`B/core/config/sso_sync.py`。
    3. user Owner 菜单与固定签发：`B/user/application/external_identity.py`、`B/user/domain/repositories/external_identity_projection.py`。
    4. 目录需求登记和策略复核：`B/sso_sync/domain/services/kunlian_directory.py`；准入版本一致性增量：`B/sso_sync/domain/services/kunlian_session.py`。
    5. OAuth nonce 只解析不输出：`B/sso_sync/domain/schemas/kunlian.py`。
  - **逻辑与交付**: 在 T034 信任校验后实现当前目录／本地资格与菜单判断，创建或重放唯一交接结果，调用 user Owner 签发固定期限本地 Cookie 描述；目录缺失只登记补同步并明确拒绝。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-08, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-13, AC-20, AC-22, AC-26_
  - _Verification: V-01, V-02, V-05；T039 通过；多登录策略由 SQL 同事务执行。_
  - _Depends: T039, T016_
  - _Boundary: 不调用旧注册／login-sync fallback，不把 UserInfo 当目录；不等补同步后自动继续原失败登录。_

- [x] **T041** [后端 API] 先写内部登录 HTTP 契约测试
  - **文件**: `BT/sso/test_kunlian_internal_api.py`
  - **逻辑与交付**: 真实 Router→Endpoint→application，测试签名入口、报文字节、未知字段、错误 HTTP／reason、幂等结果和非网关请求拒绝；现有 F014 路由行为不改。
  - **覆盖 AC:** AC-01, AC-02, AC-04, AC-13, AC-14
  - _Requirements: REQ-01, REQ-02, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-04, AC-13, AC-14_
  - _Verification: V-01, V-02, V-07；断言未认证浏览器不能直接调用内部登录，且响应无完整目录／外部凭据。_
  - _Depends: T040_
  - _Boundary: 纯 API 测试，不把 HTTP 200 信封里的业务失败当成功。_

- [x] **T042** [后端 API] 注册内部昆联登录端点
  - **文件**: `B/sso_sync/api/endpoints/kunlian.py`、`B/sso_sync/api/router.py`
  - **执行子步骤**: ① `B/core/config/sso_sync.py` 声明显式来源网段，`B/sso_sync/application/kunlian.py` 声明 API 装配值及来源校验。② 上述两个 API 文件只读原始请求并委托，未装配时拒绝。默认关闭、业务范围及 AC 不变。
  - **逻辑与交付**: 实现 POST /api/v1/internal/kunlian/login 并注册聚合 Router；管理路径的 DTO／薄委托也在此接线，具体管理逻辑与 application 绑定留 T044。按 raw body 验新签名、调用 application；仅本功能返回真实 HTTP 状态和 UnifiedResponseModel。
  - _Requirements: REQ-01, REQ-02, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-04, AC-13, AC-14_
  - _Verification: V-01, V-02, V-07；T041 通过；新增路径均不含 config。_
  - _Depends: T041_
  - _Boundary: 不改全局旧异常处理，不在 Endpoint 写 ORM 或跨模块导入 Endpoint。_

- [x] **T043** [后端 API] 先写超管映射与运行状态 API 测试
  - **文件**: `BT/sso/test_kunlian_management_api.py`
  - **逻辑与交付**: 测试 status、GET／PUT tenant-bindings/{external_tenant_id}、POST sync；全局超管、revision 冲突、已有账号不可换绑、202 幂等需求、0 与未知、目录／投影状态分开且无秘密。
  - **覆盖 AC:** AC-04, AC-05, AC-06, AC-16, AC-19, AC-20, AC-23, AC-24
  - _Requirements: REQ-02, REQ-03, REQ-06, REQ-09_
  - _Acceptance: AC-04, AC-05, AC-06, AC-16, AC-19, AC-20, AC-23, AC-24_
  - _Verification: V-02, V-03, V-07；检查凭据缺失／NOT_READY 可诊断，接口不能以已受理冒充同步完成。_
  - _Depends: T030, T042_
  - _Boundary: 纯 API 测试；普通租户管理员和业务用户不可列举控制面。_

- [x] **T044** [后端 API] 接入超管映射与脱敏状态查询
  - **文件**: `B/sso_sync/domain/services/kunlian_directory.py`、`B/sso_sync/application/kunlian.py`
  - **执行子步骤**: ① `B/user/application/external_identity.py`、`B/user/domain/repositories/external_identity_projection.py` 强读操作者当前资格。② `B/tenant/application/external_membership.py`、`B/tenant/domain/repositories/external_membership.py` 只读核验既有目标租户。③ `B/sso_sync/domain/repositories/kunlian.py` 在原事务追加既有 AuditLog 并合并人工同步需求。④ 上述两个主文件装配四种管理操作。⑤ `B/sso_sync/api/endpoints/kunlian.py` 保持局部真实 HTTP／安全失败边界。只细化既定 Owner／审计落点，不新增表或业务权限。
  - **逻辑与交付**: 补齐上述四种管理操作，application 委托既有目录服务；校验全局超管、映射 CAS、操作者审计；提供批次／age／失败关联、投影积压和契约就绪原因。
  - _Requirements: REQ-02, REQ-03, REQ-06, REQ-09_
  - _Acceptance: AC-04, AC-05, AC-06, AC-16, AC-19, AC-20, AC-23, AC-24_
  - _Verification: V-02, V-03, V-07；T043 通过。_
  - _Depends: T043_
  - _Boundary: 不新增管理页面或权限角色，不返回全目录载荷和凭据，不自动造租户。_


### Wave 5：HTTP／WS 和 Worker 接线

- [x] **T045** [后端 API] 先写 HTTP／WS 入口与当前消息身份测试
  - **文件**: `BT/sso/test_kunlian_http_admission.py`、`BT/sso/test_kunlian_ws_admission.py`
  - **逻辑与交付**: 覆盖直达后端、Cookie 歧义／缺引用、伪造身份头／Bearer／WS t、Origin／CSRF，HTTP 请求内去重和跨请求内省；WS 握手及新发送／继续／取消按当前用户检查，GPTS 旧行为与心跳不变；任务消费无秘密因果引用、不能据此铸造登录身份。
  - **覆盖 AC:** AC-07, AC-08, AC-12, AC-13, AC-14, AC-17, AC-25, AC-26
  - _Requirements: REQ-04, REQ-05, REQ-08, REQ-09_
  - _Acceptance: AC-07, AC-08, AC-12, AC-13, AC-14, AC-17, AC-25, AC-26_
  - _Verification: V-04, V-05, V-07；断言 BaseClient／WorkflowClient 实际形参可接线、并发消息不串身份、先准入再 F048 use；T046—T049 共用此证据。_
  - _Depends: T036, T038, T042_
  - _Boundary: 纯入口测试；不得只测握手，也不得只替换 GPTS 专用 execution_context 分支。_

- [x] **T046** [后端 API] 接入 HTTP 中间件与身份依赖严格分支
  - **文件**: `B/utils/http_middleware.py`、`B/user/domain/services/auth.py`
  - **执行子步骤**: ① `B/user/domain/repositories/external_identity_projection.py`、`B/user/application/external_identity.py` 判别保留来源／命名空间，`B/sso_sync/domain/repositories/kunlian.py` 定点查本地用户绑定。② `B/sso_sync/application/browser.py` 实现请求级严格准入及作用域。③ `B/sso_sync/application/runtime.py` 显式装配默认关闭的运行服务，`B/core/config/sso_sync.py` 声明独立密文密钥引用。④ 上述两个主文件接严格分支。⑤ `B/sso_sync/api/endpoints/kunlian.py` 复用运行装配，`B/main.py` 关闭运行客户端。不改变旧通道策略，不改真实配置或数据。
  - **逻辑与交付**: 根据标记／引用／保留来源／绑定任一迹象识别昆联；Cookie-only、精确 Origin、写操作 CSRF；中间件与 get_login_user 只共享单请求已验证结果，严格分支先于旧 fail-open。
  - _Requirements: REQ-04, REQ-09_
  - _Acceptance: AC-07, AC-08, AC-13, AC-14, AC-17, AC-25, AC-26_
  - _Verification: V-04, V-07；T045 的 HTTP 子集通过，AT 过期 401 与依赖 503 区分。_
  - _Depends: T045_
  - _Boundary: 其他身份通道保持原认证；协议辅助端点只能按限定用途进入，不能变免内省业务白名单。_

- [x] **T047** [后端 Domain] 接通 BaseClient 与 WorkflowClient 消息上下文
  - **文件**: `B/common/chat/clients/base.py`、`B/common/chat/clients/workflow_client.py`
  - **执行子步骤**: ① `B/common/chat/client.py` 扩展既有不可变消息上下文，`B/sso_sync/domain/services/kunlian_session.py` 给私有运行引用补充非凭据摘要。② 上述两个客户端文件以任务局部上下文读取本次操作者并在队列 headers 携带因果摘要。③ `B/sso_sync/application/browser.py` 构造逐消息作用域。既有开放面 execution_snapshot 与昆联因果信息分开，不扩展委托或主动取消在途任务。
  - **逻辑与交付**: 增加兼容的单消息当前主体上下文，在工作流发送／继续／取消中使用本次准入结果；延迟任务只附无秘密的 Kunlian 来源／绑定／会话因果引用，不用共享对象覆盖身份。
  - _Requirements: REQ-04, REQ-08, REQ-09_
  - _Acceptance: AC-08, AC-12, AC-13, AC-14, AC-17, AC-23_
  - _Verification: V-04, V-05, V-07；T045 工作流消息子集及 GPTS 兼容通过，无 TypeError／并发身份污染。_
  - _Depends: T045_
  - _Boundary: 保留 F041 等现有工作流配置合同；因果引用不能铸造登录、不增加逐节点内省或在途取消。_

- [x] **T048** [后端 Domain] 接通 ChatManager 每消息准入回调
  - **文件**: `B/common/chat/manager.py`
  - **逻辑与交付**: 用既有 message_admission 在每个新业务消息调用 application，随后按当前用户走原 use 检查；将不可变上下文传入 T047 接口，拒绝后不 dispatch。
  - _Requirements: REQ-04, REQ-08, REQ-09_
  - _Acceptance: AC-07, AC-08, AC-12, AC-14, AC-17, AC-25_
  - _Verification: V-04, V-05, V-07；T045 长连接计数与拒绝断言通过。_
  - _Depends: T047, T046_
  - _Boundary: 不在连接上缓存允许，不另建聊天引擎；已有任务不被主动取消。_

- [x] **T049** [后端 API] 接线两个 WS 建连入口
  - **文件**: `B/api/v1/workflow.py`、`B/api/v1/assistant.py`
  - **逻辑与交付**: 建连时调用统一身份依赖并校验 Origin，将受信不可变会话引用接入每消息回调；Kunlian 不接受查询参数 t 或浏览器 Bearer 作为 Cookie 替代。
  - _Requirements: REQ-04, REQ-08, REQ-09_
  - _Acceptance: AC-08, AC-12, AC-13, AC-14, AC-17, AC-25_
  - _Verification: V-04, V-05, V-07；T045 两个真实入口及重复连接／重连路径通过。_
  - _Depends: T048_
  - _Boundary: 旧自然人／开放面各自合同保留，不把服务凭据变成昆联身份。_

- [x] **T050** [Worker] 先写同步 Worker 注册、上下文与恢复测试
  - **文件**: `BT/sso/test_kunlian_worker.py`
  - **逻辑与交付**: 测试纯导入无网络、任务确实注册、Beat 触发持久需求／恢复投影、丢队列后可恢复，headers tenant_id→ContextVar→finally reset，以及非法租户头拒绝。
  - **覆盖 AC:** AC-05, AC-06, AC-19, AC-24, AC-26
  - _Requirements: REQ-03, REQ-06, REQ-09_
  - _Acceptance: AC-05, AC-06, AC-19, AC-24, AC-26_
  - _Verification: V-03, V-04, V-07；T051／T052 共同完成后观察注册表和调度，而非仅存在 cron 字段。_
  - _Depends: T016, T030_
  - _Boundary: 纯测试；外部 UUID 不可作 ContextVar；控制面任务固定受限 ROOT，用户 Owner 调用使用已验证 local_tenant_id。_

- [x] **T051** [Worker] 实现并注册昆联同步及投影恢复任务
  - **文件**: `B/worker/sso_sync/tasks.py`、`B/worker/__init__.py`
  - **执行子步骤**: ① `B/sso_sync/application/runtime.py` 组合既有目录／投影服务给 Worker，按调用关闭客户端。② 上述两个文件注册 Root 控制面任务；当前配置仅登记一个 connection_id，扫描上限为该一个连接，投影每任务最多 25 个身份并用 keyset 续投。保持既有 SQL 租约／fence 和 Owner 分工。
  - **逻辑与交付**: 定义有界连接扫描、sync 和 recover_projection；使用 Celery headers 传已验证本地 tenant_id，执行前设置 ContextVar 并在 finally 恢复。列举控制面范围只在受限 application 短作用域完成。
  - _Requirements: REQ-03, REQ-06, REQ-09_
  - _Acceptance: AC-05, AC-06, AC-19, AC-24, AC-26_
  - _Verification: V-03, V-04, V-07；T050 注册／上下文子集通过，重试必须持有当前 SQL fence。_
  - _Depends: T050_
  - _Boundary: 不传 Key／令牌或完整成员载荷；不在 API lifespan 伪装注册，默认队列不抢工作流执行队列。_

- [x] **T052** [Worker] 接入 Beat 需求扫描与恢复调度
  - **文件**: `B/worker/config.py`
  - **逻辑与交付**: 仅在目录能力允许时登记唯一 Beat 项，扫描 SQL 请求版本和投影积压，使用关闭默认配置与现有队列；所有实例引用同一状态，无内存待办真相。
  - _Requirements: REQ-06, REQ-09_
  - _Acceptance: AC-06, AC-19, AC-24, AC-25, AC-26_
  - _Verification: V-03, V-04, V-07；T050 完整通过，关闭开关不发真实同步请求。_
  - _Depends: T051, T004_
  - _Boundary: 不以 300 秒建议周期承诺撤权上界，不新增全局调度框架。_

- [x] **T053** [Worker] 保留延迟工作流的身份因果边界
  - **文件**: `B/worker/workflow/tasks.py`
  - **执行子步骤**: ① `B/sso_sync/domain/schemas/kunlian.py`、`B/sso_sync/application/workflow_context.py` 严格解析无凭据因果头，仅校验与任务参数／既有 Celery 本地租户头一致。② 主文件在真实注册任务中消费；不构造 PermissionActor、UserPayload 或浏览器会话，不把该信息交给开放面快照恢复器。
  - **逻辑与交付**: 消费 T047 附带的无秘密因果信息并保持 trace／当前执行用户／tenant 区分；现有后台执行合同不增加在线逐节点检查。入口受信来源不允许据此建立浏览器会话。
  - _Requirements: REQ-04, REQ-08, REQ-09_
  - _Acceptance: AC-08, AC-12, AC-13, AC-14, AC-23, AC-26_
  - _Verification: V-04, V-05, V-07；复用 T045 的消息→任务因果断言，必要用现有工作流测试补执行边界案例；不得只检查参数存在。_
  - _Depends: T047, T049_
  - _Boundary: 不改 ApiCredential、Token Exchange 或委托协议；不将 Kunlian 快照冒充开放平台授权快照。_


### Wave 6：商业网关 OIDC 与浏览器协议

- [x] **T054** [商业网关] 先写浏览器事务与退出 state 存储测试
  - **文件**: `GT/sso/kunlian/KunlianLoginTransactionStoreTest.java`
  - **逻辑与交付**: 测试随机 state／nonce／PKCE verifier、浏览器绑定哈希、原子消费含 error 回调、过期／重放、多标签页并存；浏览器绑定硬期限不能跟事务 TTL 一起消失。
  - **覆盖 AC:** AC-02, AC-10, AC-13, AC-21, AC-26
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-02, AC-10, AC-13, AC-21, AC-26_
  - _Verification: V-01, V-06；code 60 秒与建议事务 5 分钟分别计时，Redis 失败拒绝。_
  - _Depends: T007_
  - _Boundary: 纯测试，事务短期 Redis 真相不等于本地长期业务会话。_

- [x] **T055** [商业网关] 实现网关登录／退出事务存储
  - **文件**: `G/sso/kunlian/KunlianLoginTransactionStore.java`
  - **执行子步骤**: 上述存储与同目录 `KunlianProtocolException.java` 实现受控错误、明确注入的 Redis 原子端口和独立 AES-GCM 事务保护；生产适配器只用 Redis Lua 原子取删，测试内存端口仅验证应用状态机，不代替 T078 实际 Redis 并发。
  - **逻辑与交付**: 实现受保护 Redis 事务和原子消费、固定站内 return_to、browser binding／logout_state；仅存所需短期材料，不记录完整回调 URL。
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-02, AC-10, AC-13, AC-21, AC-26_
  - _Verification: V-01, V-06；T054 通过。_
  - _Depends: T054_
  - _Boundary: 多个事务独立消费，不在 Java 节点内存保唯一状态。_

- [x] **T056** [商业网关] 先写昆联 OIDC 专用客户端契约测试
  - **文件**: `GT/sso/kunlian/KunlianOidcClientTest.java`
  - **逻辑与交付**: 验证只发送 code flow／openid profile／PKCE S256／nonce，Basic 换码、RS256／issuer／aud／azp／exp；不自动带不支持扩展或刷新范围，换码超时不重试。
  - **覆盖 AC:** AC-01, AC-02, AC-11, AC-13, AC-14
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-11, AC-13, AC-14_
  - _Verification: V-01, V-06, V-07；包括 unknown kid 受控刷新及日志秘密探针。_
  - _Depends: T007_
  - _Boundary: 纯网关测试；用现有测试工具构造响应，不引入真实密钥或未知版本 API。_

- [x] **T057** [商业网关] 实现专用 OIDC 客户端与退出 URL 构造
  - **文件**: `G/sso/kunlian/KunlianOidcClient.java`
  - **逻辑与交付**: 使用已批准 BOM 下库实现授权、一次换码、ID Token 验证、登记 Discovery／JWKS；构造精确 OP 退出地址，过期 ID Token 仅允许已撤销会话的退出 Hint 用途。
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-10, AC-11, AC-13, AC-14, AC-21_
  - _Verification: V-01, V-06, V-07；T056 通过，Hint 不可作为任何业务凭据。_
  - _Depends: T056, T055_
  - _Boundary: 不改 JustAuth，不调用 UserInfo 建号，不盲刷 Token；秘密不进异常和日志。_

- [x] **T058** [商业网关] 先写跨仓签名交接与有限重试测试
  - **文件**: `GT/utils/KunlianRequestSignerTest.java`、`GT/sdk/KunlianIdentityClientTest.java`
  - **逻辑与交付**: 复用 T033 确定性签名向量，断言同 raw body 发出；内部重试保留 handoff_id 但换 nonce，不重换 code；只接受固定 Cookie 描述和稳定错误原因，兑换票据要求绑定。
  - **覆盖 AC:** AC-02, AC-10, AC-11, AC-13, AC-21, AC-26
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-02, AC-10, AC-11, AC-13, AC-21, AC-26_
  - _Verification: V-01, V-06；与后端向量双向一致；返回结果未知的重试不可创建第二会话或延长 exp。_
  - _Depends: T003, T034, T007_
  - _Boundary: 纯测试；不使用全局 WebClient 的 header／body 日志和全异常重试器。_

- [x] **T059** [商业网关] 实现新签名器与后端专用客户端
  - **文件**: `G/utils/KunlianRequestSigner.java`、`G/sdk/KunlianIdentityClient.java`
  - **执行子步骤**: ① `G/config/KunlianSsoProperties.java` 增加独立内部交接超时，`G/sso/kunlian/KunlianProtocolException.java` 保留稳定业务码。② 上述两个主文件实现 raw-byte 签名和专用客户端；禁用连接层隐式重试，登录仅显式两次上限，单次退票不重试。出站错误不记录原文，成功结果只接受固定会话字段，不透传 Set-Cookie。
  - **逻辑与交付**: 实现新签名串及 nonce；独立无敏感日志客户端调用 login／logout-ticket:redeem，连接池／超时有界，内部交接可有限幂等重试；区分业务拒绝与依赖故障。
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-02, AC-10, AC-11, AC-13, AC-21, AC-26_
  - _Verification: V-01, V-06；T058 通过。_
  - _Depends: T058_
  - _Boundary: 不复用客户 OIDC／目录 Key 或旧 HMAC key；不透传任意 Set-Cookie。_

- [x] **T060** [商业网关] 先写专用安全链与旧通道隔离测试
  - **文件**: `GT/config/KunlianSecurityConfigurationTest.java`
  - **逻辑与交付**: 在实际 Reactive 应用上下文测试 matcher 只覆盖昆联路由，关闭时不接管普通请求；精确 Origin、允许回调与全局默认安全链影响均有反例，旧路由不被重定向／拦截。
  - **覆盖 AC:** AC-02, AC-13, AC-14, AC-25
  - _Requirements: REQ-01, REQ-09_
  - _Acceptance: AC-02, AC-13, AC-14, AC-25_
  - _Verification: V-01, V-07；不能以单类编译代替应用启动与路由隔离；回归原网关路由合同。_
  - _Depends: T007, T055, T057, T059_
  - _Boundary: 纯配置契约测试；验证新增 Spring Security 依赖实际自动配置影响。_

- [x] **T061** [商业网关] 装配昆联专用安全与客户端 Bean
  - **文件**: `G/config/KunlianSecurityConfiguration.java`
  - **逻辑与交付**: 注册限定 matcher 和专用协议客户端／属性 Bean，明确旧路由的原允许合同，避免自动安全默认登录或 CSRF 改写全站；关闭态和未就绪态明确拒绝昆联新入口。
  - _Requirements: REQ-01, REQ-09_
  - _Acceptance: AC-02, AC-13, AC-14, AC-25_
  - _Verification: V-01, V-07；T060 通过，端点不会依赖 JustAuth 登录凭据。_
  - _Depends: T060_
  - _Boundary: design §3.1 专用 matcher 的精确文件落点；不是新增全站身份方案。_

- [x] **T062** [商业网关] 先写网关路由、Cookie 与退出浏览器契约测试
  - **文件**: `GT/controller/KunlianSsoControllerTest.java`
  - **逻辑与交付**: 测试四条新路由、return_to allowlist、固定 Origin／Host、Cookie Host-only／HttpOnly／SameSite／Secure、旧同名 Cookie 歧义；本地先撤销、票据跨浏览器拒绝、OP 取消／回跳失败、固定错误页与脱敏。
  - **覆盖 AC:** AC-01, AC-02, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25_
  - _Verification: V-01, V-06, V-07；接口列表只在显式启用且就绪时增加昆联项；不清未知应用 Cookie。_
  - _Depends: T061, T059_
  - _Boundary: 纯网关契约测试，真实浏览器与 OP 确认仍需 T080；不能宣称 Mock 完成远端退出。_

- [x] **T063** [商业网关] 落地网关登录回调与退出路由
  - **文件**: `G/controller/KunlianSsoController.java`、`G/controller/OauthController.java`
  - **执行子步骤**: ① 两个 Controller 实现固定浏览器协议与列表。② `G/config/KunlianSsoProperties.java` 校验已知旧 Cookie 清理范围，`G/config/KunlianSecurityConfiguration.java` 增加仅协议 URL 的日志生成前保护，避免框架在 WebFilter 前输出 code；配对属性／上下文测试复用。③ 成功回跳附固定非凭据片段 #kunlian-login，T068／T069／T073／T074 清理旧 Bearer 并由后端 auth_source 确认来源；不以片段授予身份。
  - **逻辑与交付**: 实现 GET /api/oauth2/kunlian、GET /api/kunlian/callback、POST /api/kunlian/logout、GET /api/kunlian/logout/callback；校验／消费事务、一次换码、受信交接、固定 Cookie 写入及退出结果页。旧登录列表仅增独立项。
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25_
  - _Verification: V-01, V-06, V-07；T062 通过；进入远端退出前本地已撤销这一事实必须由后端票据证明。_
  - _Depends: T062_
  - _Boundary: 不认领用户、不授菜单、不生成伪 refresh Cookie；拒绝任意 Host／Forwarded 构造回跳。_


### Wave 7：退出闭环与两端交互

- [x] **T064** [后端 Domain] 先写本地退出、辅助 CSRF 与票据兑换测试
  - **文件**: `BT/sso/test_kunlian_logout.py`、`BT/sso/test_kunlian_internal_api.py`
  - **逻辑与交付**: 验证 AT 到期可本地协议退出但不可读业务；SQL 撤销成功后才发票据，失败不报本地已退出；票据单次／绑定／到期、CSRF／Origin、已撤销结果、普通 logout 兼容。
  - **覆盖 AC:** AC-07, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25, AC-26
  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-07, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25, AC-26_
  - _Verification: V-04, V-06, V-07；同一会话退出重试不复活；跨实例重放被 SQL 拒绝。_
  - _Depends: T018, T036, T042_
  - _Boundary: 纯测试；只结束该次本地会话，不声称清除所有 OP／BiSheng 会话。_

- [x] **T065** [后端 Domain] 实现退出编排与单次材料交接
  - **文件**: `B/sso_sync/domain/services/kunlian_logout.py`、`B/sso_sync/application/kunlian.py`
  - **执行子步骤**: ① 两主文件实现受限协议、先撤销后签票及已撤销幂等结果。② `B/sso_sync/domain/repositories/kunlian.py` 在原消费事务核验登记连接／客户端，协议仅读原签发绑定，不解密令牌；补有界到期密文清理。③ `B/sso_sync/application/browser.py`、`B/sso_sync/application/runtime.py` 与 `B/utils/http_middleware.py` 装配精确方法／路径的独立协议类型，不构造业务主体。④ `B/worker/sso_sync/tasks.py`、`B/worker/config.py` 复用既有 Worker 清理到期会话与短期回执材料；仅有登记 connection_id 时调度，即使登录／目录关闭也不延长秘密保留。复用并扩展 T050／T064 测试。
  - **逻辑与交付**: 先持久 revoke，再返回限定 next_action 票据；实现 redeem_logout_ticket 的签名／浏览器绑定验证，提供过期 AT 下仅协议用途的本地验证；ID Token 密文仅给登记网关。
  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-07, AC-10, AC-11, AC-13, AC-21, AC-25, AC-26_
  - _Verification: V-04, V-06；T064 服务子集通过；CSRF 值本身不能认证身份。_
  - _Depends: T064, T034, T044_
  - _Boundary: SQL 撤销失败不清成成功态、不生成票据；远端取消不会重新激活会话。_

- [x] **T066** [后端 API] 接入本地 logout、退票兑换与 CSRF 路由
  - **文件**: `B/user/api/user.py`、`B/sso_sync/api/endpoints/kunlian.py`
  - **逻辑与交付**: 既有 POST /api/v1/user/logout 分支调用统一协议；增加 POST /api/v1/internal/kunlian/logout-ticket:redeem、GET /api/v1/identity-integrations/kunlian/session/csrf。清本地访问 Cookie，保留浏览器绑定给网关核对。
  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-07, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25_
  - _Verification: V-04, V-06, V-07；T064 HTTP 子集通过；ticket 不进入普通业务认证依赖。_
  - _Depends: T065, T063_
  - _Boundary: 辅助端点不提供业务数据，不受外部 AT 到期阻止；其他 logout 行为不变。_

- [x] **T067** [前端 Platform] 先写 Platform 请求与退出调用链测试
  - **文件**: `P/controllers/kunlianSession.test.ts`、`P/test/kunlianLogout.test.tsx`
  - **逻辑与交付**: 用 Vitest 验证 401／409／403／503 分流、固定站内 return_to、CSRF 取值及提交、next_action POST；MainLayout／Page403／TenantSelect／userContext 不能被旧 finally 或 localStorage 退出 URL 抢走新流程。
  - **覆盖 AC:** AC-01, AC-04, AC-07, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25
  - _Requirements: REQ-01, REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-04, AC-07, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25_
  - _Verification: V-01, V-04, V-06, V-07；SQL 撤销失败显示重试且不声称退出成功；503 不制造重登循环。_
  - _Depends: T042, T066_
  - _Boundary: 纯前端测试，不从 localStorage 决定安全身份；复用现有 ApiError，失败 Promise 保留拒绝。_

- [x] **T068** [前端 Platform] 实现 Platform 请求准入与固定跳转助手
  - **文件**: `P/controllers/request.ts`、`P/utils/loginReturnTo.ts`
  - **补充落点**: `P/controllers/kunlianSession.ts` 独立持有交互实例，避免既有 returnTo 测试替身截断请求模块；旧 `requestCompatibilityMatrix.test.ts`、`requestSessionFailure.test.ts` 补完整 Location，`dshRequestCompatibility.test.ts` 补 i18next.exists 和已有本地安全文案断言。先在 HEAD 工作树复现旧测试失败，未改其生产合同。
  - **执行子步骤**: ① 两主文件接入固定协议。② 复用已有 `@bisheng/api-client` 包，在 `packages/api-client/src/kunlianBrowser.ts` 与 `index.ts` 共享纯契约／交互约束，不建身份或权限状态；两端各自持有仅本页的交互实例。③ `P/controllers/requestStream.ts` 补写请求 CSRF；`P/pages/BuildPage/assistant/editAssistant/TestChat.tsx` 与 `P/components/bs-comp/chatComponent/ChatInput.tsx` 使昆联 WS 不带查询 t，保留旧通道。④ 配对测试覆盖并修正旧测试中不完整的浏览器 Location 替身，不改旧生产分流。
  - **逻辑与交付**: 识别昆联 reason_code，仅 SESSION_EXPIRED 触发固定同源重登；409 显示待同步、403 权限提示、503 留落点；写请求取得会话 CSRF、重复错误合并呈现，next_action 仅允许固定站内 POST。
  - _Requirements: REQ-01, REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-04, AC-07, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25_
  - _Verification: V-01, V-04, V-06, V-07；T067 请求与助手子集通过。_
  - _Depends: T067_
  - _Boundary: 不改变普通第三方错误分支，不在 store 直接发 HTTP，不接受响应里任意外链。_

- [x] **T069** [前端 Platform] 接入 Platform 用户 API 与昆联登录入口
  - **文件**: `P/controllers/API/user.ts`、`P/pages/LoginPage/loginBridge.tsx`
  - **补充落点**: `P/pages/LoginPage/login.tsx` 防止既有自动重定向抢走明确昆联交互，保留显式本地登录；配对 T067 真实页面测试。
  - **执行子步骤**: ① 两主文件接入口／退出。② `P/types/api/user.ts` 增可选服务端来源类型；`B/user/api/user.py` 的当前用户响应仅对已认证昆联主体增加 auth_source=kunlian，普通响应保持原字段，`BT/sso/test_kunlian_user_info.py` 检查不能用请求头／查询伪造。
  - **逻辑与交付**: 类型化 logout 结果和 CSRF 请求；登录列表独立显示昆联入口，携带经验证 return_to，目录未就绪可重登且不自动授菜单。
  - _Requirements: REQ-01, REQ-02, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-04, AC-10, AC-11, AC-13, AC-14, AC-21, AC-22_
  - _Verification: V-01, V-02, V-06, V-07；T067 登录／用户 API 子集通过；普通 SSO／企微按钮继续原行为。_
  - _Depends: T068, T063_
  - _Boundary: 外部令牌不进前端；使用共享文案键，不在 API 层吞掉退出失败。_

- [x] **T070** [前端 Platform] 接入主布局与 403 页的退出结果处理
  - **文件**: `P/layout/MainLayout.tsx`、`P/pages/Page403.tsx`
  - **逻辑与交付**: 消费明确 local logout 结果：Kunlian 成功按 next_action 表单 POST，失败保留可重试提示；旧身份继续原流程。取消 Page403 对昆联失败也 finally 跳转并声称已退出的路径。
  - _Requirements: REQ-07, REQ-09_
  - _Acceptance: AC-10, AC-13, AC-14, AC-21, AC-25_
  - _Verification: V-06, V-07；T067 两个调用者断言通过。_
  - _Depends: T069_
  - _Boundary: 只改退出分支，不重构布局或导航；本地 UI 清理不能冒充 SQL 撤销。_

- [x] **T071** [前端 Platform] 接入租户选择及被挤下线退出分支
  - **文件**: `P/pages/LoginPage/TenantSelect.tsx`、`P/contexts/userContext.tsx`
  - **逻辑与交付**: 复用同一明确退出结果，Kunlian 不在 catch／finally 沿用旧第三方 URL 或丢掉 next_action；已失效会话保留重新授权入口，普通身份原合同保持。
  - _Requirements: REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-08, AC-10, AC-11, AC-14, AC-21, AC-25_
  - _Verification: V-04, V-06, V-07；T067 全部通过；手动验证保留在 T080，不为每调用者再建独立 E2E。_
  - _Depends: T070_
  - _Boundary: 不恢复旧会话、不把被挤下线提示当远端全局退出成功。_

- [x] **T072** [前端 Client] 先写 Client 请求与退出状态测试
  - **文件**: `C/api/kunlianSession.test.ts`、`C/hooks/kunlianLogout.test.tsx`
  - **逻辑与交付**: 用现有 Jest 测试 request、loginRedirect 及真实 useLogoutUserMutation→用户 API→AuthContext 的错误分流／CSRF／next_action；证明 AT 到期仍可退出，logout onError 不假成功，不由旧 thirdPartyLogoutUrl 覆盖。
  - **覆盖 AC:** AC-01, AC-04, AC-07, AC-08, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25
  - _Requirements: REQ-01, REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-04, AC-07, AC-08, AC-10, AC-11, AC-13, AC-14, AC-21, AC-25_
  - _Verification: V-01, V-04, V-06, V-07；测试需要真实拒绝 Promise；不因模拟直接成功掩盖请求层合同。_
  - _Depends: T066_
  - _Boundary: 纯 Client 测试；不把 Platform Vitest 配置移过来。_

- [x] **T073** [前端 Client] 实现 Client 请求与登录落点处理
  - **文件**: `C/api/request.ts`、`C/utils/loginRedirect.ts`
  - **执行子步骤**: 使用 T068 的共享窄约束及 Client 本页交互实例，不恢复存储中的身份。只修改实际浏览器传输／错误分流；接口凭据和普通源继续原合同。 `C/utils/kunlianSession.ts` 持有交互实例，`C/routes/RequireLogin.tsx` 消费用户信息故障的手动重试状态，防止请求层 503 不跳转却被后续路由守卫强制重登；不提供业务允许缓存。
  - **逻辑与交付**: 按相同 HTTP／reason 合同分流、Cookie-only 和写请求 CSRF；固定站内登录与允许落点，不读写外部 Token，不因503循环登录。
  - _Requirements: REQ-01, REQ-04, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-04, AC-07, AC-08, AC-10, AC-11, AC-13, AC-14, AC-25_
  - _Verification: V-01, V-04, V-06, V-07；T072 请求／落点子集通过。_
  - _Depends: T072_
  - _Boundary: 保留已有 Client 认证合同；不新增 Recoil 状态或更换状态库。_

- [x] **T074** [前端 Client] 定义真实退出链的 API 与响应类型
  - **文件**: `C/api/user.ts`、`C/types/chat/mutations.ts`
  - **逻辑与交付**: 增加 CSRF／logout 的窄 API 并类型化明确本地结果及 next_action；扩展现有 TLogoutResponse／LogoutOptions 的兼容字段，供真实 useLogoutUserMutation 消费。不能只给无人调用的 api/user.ts 增加函数。
  - _Requirements: REQ-07, REQ-09_
  - _Acceptance: AC-10, AC-11, AC-13, AC-14, AC-21, AC-25_
  - _Verification: V-06, V-07；复用 T072 真实 hook 调用链测试并做类型检查；响应外部令牌不可进入浏览器类型。_
  - _Depends: T073_
  - _Boundary: 旧调用者的 message／redirect 合同保持；不改通用 dataService 或所有 mutation 的语义。_

- [x] **T075** [前端 Client] 接通真实退出 mutation 与 AuthContext
  - **文件**: `C/hooks/queries/auth/mutations.ts`、`C/hooks/AuthContext.tsx`
  - **逻辑与交付**: 将现有 useLogoutUserMutation 接入 T074 API／类型，保留 query 清理及旧身份合同；只有明确本地撤销后清对应状态并按 next_action POST 固定网关。失败保留重试，onError 不沿旧 thirdPartyLogoutUrl 声称成功。
  - _Requirements: REQ-07, REQ-09_
  - _Acceptance: AC-10, AC-11, AC-13, AC-14, AC-21, AC-25_
  - _Verification: V-06, V-07；T072 全部通过，证明真实 mutation→API→响应→AuthContext 的结果传递，普通 Client 登录／退出兼容。_
  - _Depends: T074, T063_
  - _Boundary: 不新增 Recoil state／import 或迁移状态库，不将票据当业务凭据，不把 query 清理等同 SQL 撤销。_

- [x] **T076** [共享文案] 补齐共享会话提示中英源文案
  - **文件**: `L/shared/zh-Hans.json`、`L/shared/en.json`
  - **逻辑与交付**: 为两端复用的昆联登录、同步等待、重新授权及本地／远端退出结果提示增加明确键；面向用户不展示内部对象名或源协议秘密。
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-04, AC-11, AC-13, AC-21, AC-24_
  - _Verification: V-01, V-06, V-07；核对两端取键方式和错误文案优先级，禁止硬编码中文。_
  - _Depends: T006_
  - _Boundary: 仅文案，不新造页面／权限策略；与 T077 作为同一三语批次交付。_

- [x] **T077** [共享文案] 补齐共享日文并生成语言产物
  - **文件**: `L/shared/ja.json`
  - **逻辑与交付**: 补齐 T076 日文；用现有 @bisheng/locales 构建脚本生成共享 shared／api_errors 产物，检查三语键与已实现后端错误码覆盖。生成文件列入 diff，绝不手改。
  - _Requirements: REQ-01, REQ-07, REQ-09_
  - _Acceptance: AC-01, AC-04, AC-11, AC-13, AC-14, AC-21, AC-24_
  - _Verification: V-01, V-06, V-07；pnpm --filter @bisheng/locales build／check、pnpm check-i18n，并按项目要求运行前端 lint／typecheck。_
  - _Depends: T076, T071, T075_
  - _Boundary: 生成物不计手工改动文件数；不更新基线掩盖新增缺键，不重新安装无关依赖。_


### Wave 8：真实边界验证及交付准备

- [ ] **T078** [集成与交付] 验证真实存储与跨实例竞争
  - **当前状态**: 脚本已补齐，本地入口／安全契约检查通过；真实 MySQL、Redis、Linux DM8 验证待执行（NOT_RUN，ENV-01），任务保持未完成。新增脚本可作为中央环境的显式执行入口，不把旧 cursor 骨架或本地跳过算通过。
  - **执行子步骤**: ① 两目标文件提供真实双连接池／Repository、Owner fence、交接／epoch／撤销、CLOB 清理与 Redis 签名 nonce 竞争；默认跳过，不建表。② BT/sso/test_kunlian_live_harness.py 验证防误连／清理边界等入口契约；F/live-test-runbook.md 记录参数和独立 DM8 命令，不增加产品接口或测试依赖。
  - **文件**: `BT/integration/test_kunlian_consistency.py`、`BT/integration/kunlian_fixtures.py`
  - **逻辑与交付**: 在受控 MySQL／Redis 环境运行两个独立 Repository／服务实例，验证租约交接、旧 fence、发布与 Owner 投影／手工禁用竞争、交接唯一、撤销跨实例、停用后恢复旧会话仍拒绝；复用中央 DM8 回归入口。
  - **覆盖 AC:** AC-03, AC-05, AC-06, AC-07, AC-09, AC-16, AC-17, AC-18, AC-23, AC-24, AC-26
  - _Requirements: REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-09_
  - _Acceptance: AC-03, AC-05, AC-06, AC-07, AC-09, AC-16, AC-17, AC-18, AC-23, AC-24, AC-26_
  - _Verification: V-02, V-03, V-04, V-05；记录 DB 方言、实例数、版本、命令与最终状态；DM8 中央结果单列，不虚构现有 CI 自动门禁。_
  - _Depends: T044, T049, T052, T053, T066_
  - _Boundary: 这是存储边界的独立证据，不复制全部 Mock 案例；中央环境缺失即 BLOCKED，不用 SQLite 锁证明等价。_

- [ ] **T079** [集成与交付] 落实强制 API E2E 与授权边界
  - **当前状态**: 脚本已补齐，本地入口／安全契约检查通过；真实 API／Worker／OpenFGA／昆联链路待执行（NOT_RUN）。用户本轮明确允许先补齐脚本；真实执行仍依赖 T078 和专属环境，不以 Mock 代替。
  - **执行子步骤**: ① 两目标文件通过真实网关授权／Cookie、管理 API、Broker Worker 回执和 F048 接口执行生命周期；上游无自动化接口的部分使用受保护 checkpoint 交接真实操作，不伪造上游接口／JWT。② 复用 T078 的离线入口测试与运行说明；A／B、跨租户 C、独立首次缺目录探针分开，避免以旧绑定缺失冒充首次未同步。真实页面／WS 运行／多进程及传播时效仍由 T080 验收。
  - **文件**: `BT/e2e/test_e2e_kunlian_identity.py`、`BT/e2e/helpers/kunlian.py`
  - **逻辑与交付**: 按 /e2e-test 技能实现并执行最小端到端链：完整目录／显式映射、无默认菜单、人工授权后按 A／B 各自身份访问工作流、对象动作拒绝、停用保留人工 Grant 与资产、恢复需新会话；验证真实 Worker 而非直接调用服务代替调度。
  - **覆盖 AC:** AC-01, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-12, AC-17, AC-18, AC-20, AC-22, AC-23, AC-24, AC-26
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-01, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-12, AC-17, AC-18, AC-20, AC-22, AC-23, AC-24, AC-26_
  - _Verification: V-01, V-02, V-03, V-04, V-05, V-06；用现有 E2E helper；接口 E2E 与浏览器验收共用环境和状态证据，不为 AC 数量复制测试。_
  - _Depends: T078, T063, T077_
  - _Boundary: 只用专属测试租户／用户／工作流，凭据由安全配置注入；不改生产目录，不以 Mock 通过关闭真实上游验收。_

- [ ] **T080** [集成与交付] 执行真实浏览器登录／退出与上游时效验收
  - **当前状态**: PARTIAL / MANUAL_REQUIRED；2026-11-11 已经用户授权完成试点真实 SSO、管理页和编辑回跳、新建、统一退出及旧 Cookie 拒绝。多账号、上游传播及完整 T079 等仍未闭合，不勾选，见[本次真实记录](./联调部署与验证记录-20261111.md)。
  - **文件**: `F/e2e-browser-checklist.md`、`F/verification.md`
  - **逻辑与交付**: 按 design §7.2 完成专属 A／B／跨租户对照、目标页面、五分钟 AT 到期、Cookie／CSRF、每次 HTTP／WS 内省、OP 确认／取消及多节点重放；记录 EXT-03 的传播实测及 EXT-04 的 workspace／到期反例。
  - **覆盖 AC:** AC-01, AC-02, AC-04, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-17, AC-18, AC-20, AC-21, AC-22, AC-25, AC-26
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-07, REQ-08, REQ-09_
  - _Acceptance: AC-01, AC-02, AC-04, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-17, AC-18, AC-20, AC-21, AC-22, AC-25, AC-26_
  - _Verification: V-01, V-02, V-04, V-05, V-06；缺条件标 BLOCKED／MANUAL_REQUIRED，保留证据差项；含 ID Token Hint 的 HAR／截图先脱敏，不宣称清除了所有 OP 会话。_
  - _Depends: T079_
  - _Boundary: EXT-01 至 EXT-04、网络、批准测试账号和专属凭据是必需门禁；本任务不替用户联系外部人员或批准正式启用。_

- [x] **T081** [集成与交付] 补原身份通道最小相关回归
  - **文件**: `BT/sso/test_kunlian_compatibility.py`
  - **执行子步骤**: ① 兼容测试先复现旧昆联 Cookie 误拦原凭据入口／匿名启动路由。② `B/utils/http_middleware.py` 仅对精确方法与原始路径保留原密码登录、注册、公钥、验证码和 env 合同；原 UserService 独立验证新凭据，影子账号仍拒绝密码登录。③ `src/frontend/packages/api-client/src/kunlianBrowser.ts` 对齐浏览器传输分类，避免在显式密码登录前获取旧会话 CSRF；不扩展业务、内部网关或开放 API 的豁免。
  - **逻辑与交付**: 增加旧本地／企微／DSH／开放面与昆联的判别回归：其他身份不内省、不能改写 source 侵入专属账号；固定受影响的既有 JWT、菜单／资源与资产合同，复用网关 T060 隔离证据。
  - **覆盖 AC:** AC-08, AC-12, AC-13, AC-14, AC-20, AC-23, AC-25
  - _Requirements: REQ-04, REQ-08, REQ-09_
  - _Acceptance: AC-08, AC-12, AC-13, AC-14, AC-20, AC-23, AC-25_
  - _Verification: V-04, V-05, V-07；执行现有 sso／tenant／user／WS／DSH／open_api 受影响测试选择集，选择理由及排除项记入 verification，不无关全仓测试。_
  - _Depends: T049, T053, T066, T071, T075_
  - _Boundary: 只增加已受影响边界的业务断言，不新建全量回归框架；不改变 F041 或开放 API 身份政策。_

- [ ] **T082** [集成与交付] 形成配对发布、禁用与安全回退交付说明
  - **当前状态**: NOT_READY；release-readiness.md 已准备。2026-11-11 经后续授权完成试点配置、备份和部署，见[本次真实记录](./联调部署与验证记录-20261111.md)；完整 T080、真实容量和回退演练未完成，保留未勾选。
  - **文件**: `F/release-readiness.md`、`F/verification.md`
  - **逻辑与交付**: 汇总后端／网关配对版本和证据，给出默认关闭→目录初始化→映射／人工授权→受控测试→启用的检查表，记录 SQL 禁用／会话撤销／排空及保留能识别昆联会话版本的回退；内省容量按实际 HTTP／WS 动作量核验。
  - **覆盖 AC:** AC-06, AC-07, AC-09, AC-13, AC-14, AC-19, AC-21, AC-24, AC-25, AC-26
  - _Requirements: REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-09_
  - _Acceptance: AC-06, AC-07, AC-09, AC-13, AC-14, AC-19, AC-21, AC-24, AC-25, AC-26_
  - _Verification: V-03, V-04, V-05, V-06, V-07；全部 AC 有实际结果／未验原因，EXT 未闭合不标 READY；保留新表和人工授权，写明可逆边界与不可回滚操作。_
  - _Depends: T080, T081_
  - _Boundary: 只编写和核对操作说明；不授权部署、真实吊销、Schema／数据操作或直接退回忽略 kunlian_session 的旧后端。_


## 5. 验收与证据追溯

以下是完整 AC 的整体验收状态；PARTIAL 表示本地证据通过、真实边界仍未验收，逐项证据与缺口见 verification.md 的当前矩阵；已完成的定向证据见 verification.md，并不表示整条跨层 AC 已验收。主证据组沿用 spec；同一 AC 需要跨仓／存储独立边界时才引用多个入口。每个测试任务自身也逐项列 Coverage，不使用 AC 范围写法。

| AC | Requirements | 测试／验收任务 | 主证据组 | 当前状态 |
| --- | --- | --- | --- | --- |
| AC-01 | REQ-01 | T039, T056, T062, T079, T080 | V-01 | PARTIAL |
| AC-02 | REQ-01、REQ-09 | T033, T037, T039, T041, T054, T056, T058, T060, T062, T080 | V-01 | PARTIAL |
| AC-03 | REQ-02 | T019, T023, T025, T027, T029, T078, T079 | V-02 | PARTIAL |
| AC-04 | REQ-02、REQ-03 | T023, T039, T043, T067, T072, T079, T080 | V-02 | PARTIAL |
| AC-05 | REQ-03、REQ-06 | T011, T013, T015, T043, T050, T078, T079 | V-03 | PARTIAL |
| AC-06 | REQ-06 | T009, T011, T015, T043, T050, T078, T079 | V-03 | PARTIAL |
| AC-07 | REQ-04 | T031, T035, T045, T064, T067, T072, T078, T079, T080 | V-04 | PARTIAL |
| AC-08 | REQ-04、REQ-09 | T035, T037, T045, T072, T079, T080, T081 | V-04 | PARTIAL |
| AC-09 | REQ-05 | T011, T019, T029, T035, T078, T079, T080 | V-05 | PARTIAL |
| AC-10 | REQ-07 | T017, T054, T062, T064, T067, T072, T079, T080 | V-06 | PARTIAL |
| AC-11 | REQ-04、REQ-07 | T035, T037, T056, T058, T062, T064, T067, T072, T080 | V-06 | PARTIAL |
| AC-12 | REQ-08 | T045, T079, T080, T081 | V-05 | PARTIAL |
| AC-13 | REQ-09 | T017, T031, T033, T039, T041, T045, T056, T058, T060, T062, T064, T067, T072, T080, T081 | V-01、V-04 | PARTIAL |
| AC-14 | REQ-09 | T021, T025, T027, T037, T041, T045, T056, T060, T062, T064, T067, T072, T081 | V-07 | PARTIAL |
| AC-15 | REQ-03、REQ-08 | T011, T013, T015 | V-03 | PARTIAL |
| AC-16 | REQ-02、REQ-03、REQ-06 | T009, T011, T013, T015, T043, T078 | V-03 | PARTIAL |
| AC-17 | REQ-04、REQ-05 | T021, T023, T031, T035, T045, T078, T079, T080 | V-04、V-05 | PARTIAL |
| AC-18 | REQ-05、REQ-08 | T011, T019, T021, T029, T035, T078, T079, T080 | V-05 | PARTIAL |
| AC-19 | REQ-06、REQ-09 | T013, T015, T043, T050 | V-03 | PARTIAL |
| AC-20 | REQ-03、REQ-08 | T019, T023, T029, T039, T043, T079, T080, T081 | V-02、V-05 | PARTIAL |
| AC-21 | REQ-07 | T017, T054, T062, T064, T067, T072, T080 | V-06 | PARTIAL |
| AC-22 | REQ-01、REQ-08 | T019, T029, T039, T079, T080 | V-02、V-05 | PARTIAL |
| AC-23 | REQ-05、REQ-08、REQ-09 | T019, T021, T023, T025, T027, T029, T078, T079, T081 | V-05、V-07 | PARTIAL |
| AC-24 | REQ-06、REQ-09 | T013, T015, T029, T043, T050, T078, T079 | V-03 | PARTIAL |
| AC-25 | REQ-04、REQ-07、REQ-09 | T021, T031, T033, T035, T037, T045, T060, T062, T064, T067, T072, T080, T081 | V-04、V-07 | PARTIAL |
| AC-26 | REQ-02、REQ-04、REQ-06 | T009, T011, T015, T017, T027, T029, T035, T039, T050, T058, T064, T078, T079, T080 | V-04 | PARTIAL |

### 5.1 验证批次与命令入口

下列命令保留为各阶段计划入口；已经执行的批次、环境和结果以 verification.md 的 E-* 证据为准。未执行项仍为 NOT_RUN，不把示例命令当成成功结果。运行前复用已验证解释器／依赖和最近 AGENTS，不安装未知版本解决示例命令。

| 批次 | 证据 | 执行及复用策略 |
| --- | --- | --- |
| B-DIR | V-03 | T009／T011／T015 同一 directory 文件增量测试只在相关实现变化时执行；T013 证明 HTTP 头与重试独立边界。真实锁语义只由 T078 补充 |
| B-OWNER | V-02、V-05、V-07 | T019／T021／T023／T025／T027／T029 按 Owner 独立结果验证，T079 复用状态并补菜单／资源授权闭环，不重复构造每条 AC |
| B-SESSION | V-01、V-04、V-06 | T017／T031／T033／T035／T037／T039／T041 和 T064 只覆盖各自存储、协议、服务、API 边界；HTTP／WS 实际接线由 T045 证明 |
| B-GATEWAY | V-01、V-06、V-07 | Maven 运行新增专用测试及旧路由隔离选择集；失败回调、换码未知、退出取消共用参数化协议案例 |
| B-UI | V-01、V-04、V-06、V-07 | Platform Vitest、Client Jest；T067／T072 承担主要交互逻辑证据，T080 补真实 Cookie、跳转和 OP 确认 |
| B-REAL | V-01 至 V-07 | T078／T079 中央受控中间件；DM8 单列中央结果；T080 上游／浏览器、T081 兼容；T082 汇总缺口与启用结论 |

计划命令示例（仓库相对路径）：

```bash
# cwd: 毕昇 src/backend；按已完成批次选具体文件，不每步跑全 test/
uv run pytest test/sso/test_kunlian_directory.py test/sso/test_kunlian_directory_client.py
uv run pytest test/sso/test_kunlian_login_contract.py test/sso/test_kunlian_admission.py test/sso/test_kunlian_logout.py
# cwd: 商业网关；仓库当前无 mvnw
mvn -Dtest=KunlianLoginTransactionStoreTest,KunlianOidcClientTest,KunlianRequestSignerTest,KunlianIdentityClientTest,KunlianSecurityConfigurationTest,KunlianSsoControllerTest test
# cwd: 毕昇 src/frontend；分别使用两端现有测试运行器
pnpm --filter bisheng exec vitest run src/controllers/kunlianSession.test.ts src/test/kunlianLogout.test.tsx --maxWorkers=1 --minWorkers=1
pnpm --filter bishengchat exec jest --runInBand --runTestsByPath src/api/kunlianSession.test.ts src/hooks/kunlianLogout.test.tsx --coverage=false
pnpm --filter @bisheng/locales build
pnpm --filter @bisheng/locales check
pnpm check-i18n
pnpm lint
pnpm typecheck
```

本地定向 pytest 不证明 MySQL／DM8 行锁和真实中间件；T078／T079 的环境及选择命令按实际中央环境记录，不编造当前可用的服务地址。Ruff 针对实际修改文件，架构守卫按 scripts/arch-guard.sh 逐文件执行。上面是命令入口示例；实际解释器、Node／JDK 和已运行命令／结果以 verification.md 为准，不将静态检查冒充全特性通过。

### 5.2 完成与审查检查点

- 每个行为批次结束：按 /task-review 的项目入口审查受影响任务，记录命令、代码版本、环境、结果与覆盖；任务勾选只基于对应证据。跨仓版本分别记录。
- T079 必须按项目 /e2e-test 执行；T080 的真实上游条件未具备时保持未完成，不能因单元通过替代。
- 特性合入前按 /sdd-code-review --base feat/3.0.0 审查毕昇范围，并明确网关基线／配对 diff 的额外审查范围。该检查点不自动创建 PR、提交、推送或合并。
- 只有验证完成、未验证项明确、所有启用门禁已解除，才能给出相应 READY 结论；静态任务自审不等于 IMPLEMENTED／VERIFIED。

## 6. 实际偏差记录

- 2026-11-04 规格对照审查：T004／T007 Origin 合同、T014／T032 上游流式读取预算、T037／T045／T046 主体错配撤销、T055 回跳查询和 T079 端到端预算均在既有职责内修复并补回归；新原因不扩充仓储枚举，复用 IDENTITY_CHANGED。Client 普通 401 实测正常，只补测试、不改产品请求实现。没有新增业务能力、依赖、运行配置或任务 ID；79/83 和真实待执行项不变。

- T022 在实施检索后细化为四个至多两文件的执行子步骤：原任务只列 service／login-sync，但真实手工启停在 user/api/user.py，且新 SQL 必须落既有 Owner Repository。该落点原已在 design §4.6 内；业务规则、角色和 AC 不变。
- 初版任务拆解仅补明 design §4.6 已有职责对应的精确文件：网关专用安全装配、Platform 四个退出调用者、延迟工作流因果接线、Client 真实退出 mutation／响应类型及共享提示源文件；未改变 D01—D08 或 AC。
- 实施若推翻已确认决策，先按 SDD Guide §3 暂停并重新确认；细节调整只回写 design 并在此留一行任务指针，不复制设计论证。

## 修订历史

| 日期 | 改动 | 触发 |
| --- | --- | --- |
| 2026-11-03 | 首版 82 项、8 个 Wave，实施 0 项 | 用户确认设计，仅授权继续 tasks.md |
| 2026-11-04 | 更新至 79/83；补两端实际落点、T081 兼容性修复及完整 AC 缺口；真实验收和回退文档已准备 | 按已授权任务持续实施，环境受限任务保留未完成；不部署 |
| 2026-11-04 | 补齐 T078／T079 四个测试文件、离线入口检查及真实运行说明；真实结果保持 NOT_RUN，79/83 不变 | 用户明确要求先补脚本，缺环境验证待执行，不部署 |
| 2026-11-04 | 对照 spec／design／tasks 审查，关闭六项发现并更新当前验证证据 | 用户要求审查并修复；真实环境继续待执行，不部署 |

2026-11-03 追加：用户批准 [Owner 持久投影栅栏](./design-owner-projection-fencing.md)，新增 T083，原任务 ID 保留；依赖以拓扑顺序判断，不按 ID 数值大小判断。独立预留操作不写用户资料，原子应用及回执均由 user Owner 事务完成。
