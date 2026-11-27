# Tasks: 平台统一认证与会话

**关联规格**：[spec.md](./spec.md) S1。**关联设计**：[design.md](./design.md) D1。**版本**：v3.1.0-alpha1。
**状态日期**：2026-11-27。用户确认spec/design及90天期限后，已授权按tasks实现和测试；仅修改bisheng和bisheng-mobile，网关和桌面源码保持不变。

## 状态

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| spec.md | ✅ 已评审 | S1，用户于2026-11-27确认 |
| design.md | ✅ 已评审 | D1，用户于2026-11-27确认；30天Access，90天闲置Session/Refresh |
| test-cases.md | ✅ 已整理 | QA参考文档，85条全部待执行，不是运行通过 |
| tasks.md | ✅ 已拆解 | 21项任务审查通过，见tasks-review.md；实际路径、92项完成及3项用户集成任务已回填 |
| 实现 | ✅ 开发完成 | T001～T091及T095完成，共92/95；T092～T094真实集成由用户执行 |
| 测试执行／部署 | ✅ 本地单元验证完成；未部署 | 真实集成由用户负责，详见validation.md与handoff.md；最后补充用例结果随验证记录更新 |

## 开发模式与边界

- 用户已授权实现与测试，未授权部署。用户随后明确真实集成由其处理，本轮完成开发及单元测试；T093和T094的真实环境部分交接用户，不作为已执行。实施工作树及可验证基线见[integration-baseline.md](./integration-baseline.md)；先前文档阶段的“未执行”记录仅描述当时状态。
- 任务从已确认spec AC与design D1推导，**不把QA参考test-cases作为任务生成或研发测试验收输入**；QA用例和研发测试各自保留依据。
- 按Wave与显式依赖推进；每项目标为一个短会话，原计划每项最多两个写入逻辑文件；实施按同一Owner的完整业务链合并执行，测试夹具复用及必要consumer接线集中记录，不为文件数额外复制模块。共享文件仅按依赖增量修改；按后端认证、网页认证、手机认证三个完整业务链划定唯一写入Owner，跨链协议先协调；文档与集成验证由主执行者维护。
- 后端测试任务在配对实现之前：先记录有效红测，后实现转绿；测试任务只写测试。新增后端测试位于`test/platform_auth/`或`test/e2e/`，不放test根目录。基础设施含模型、配置、迁移、错误、协议和fixture，先于产品逻辑。
- 文中源码路径除MOBILE_ROOT外均相对毕昇仓库；任务文件列表已同步实施路径；公共边界与附带consumer清单见design职责表及验证记录。`MOBILE_ROOT=/Users/zhangguoqing/.codex/worktrees/platform-auth-mobile-20261127/bisheng-mobile`，已从main建立`fix/mobile-session-refresh`的隔离工作树并读取指引。桌面仓库本期不改源码，安装包回归须有真实目标环境。
- 旧DSH行为等价是抽取条件，不得因统一核心悄改其Token用途或期限。网关仓库不改。第三方OAuth2只适配网页身份接缝。
- Platform使用Zustand，Client使用Recoil，各自API层调用共享认证模块；不得以模板中的旧示例把Client改成Zustand。手机保持Flutter现有框架和Coordinator。
- canon错误码/locale同步后按已有生成流程处理派生文件。任务列出的是最多两个手写逻辑输入；机械生成副本不手改，其实际差异必须在验证记录列清，不伪装为无变更。
- 中央集成环境执行真实MySQL/DM8、网关和多实例；本地单元测试不证明部署。没有测试降级授权，不以mock或缺环境跳过P0对外宣称通过。
- 实施前阅读匹配目录AGENTS，迁移尤其如此。共享工作树禁止repo-wide git写入：不使用stash、reset --hard、clean或无路径restore；保护无关WIP。

## Tasks

### Wave 1：基础设施与输入边界

- [x] **T001** [基础设施／准备]：核对既有入口及外部交付前提
  - **文件**：`features/v3.1.0-alpha1/003-platform-auth-session/discovery.md`, `features/v3.1.0-alpha1/003-platform-auth-session/integration-baseline.md`
  - **逻辑／上下文**：只读确认网关HMAC请求及opaque token落地、受支持旧DSH包、手机最低版本、现有业务活动入口和数据库/模型发现路径；列明生产者与消费者，不改网关。记录真实版本与未满足条件；如发现与已确认D1冲突，按偏差规则暂停，不自行重写确认口径。
  - **覆盖 AC**：AC-03, AC-20, AC-23, AC-25, AC-29
  - **依赖**：无
  - **验证／完成条件**：入口/路由/镜像基线可追踪；外部准备缺失不能被记录为已验证。

- [x] **T002** [基础设施／基础设施]：新增平台认证策略配置
  - **文件**：`src/backend/bisheng/core/config/settings.py`
  - **逻辑／上下文**：加入Access 2592000秒、Session闲置7776000秒、无额外绝对上限、恢复宽限86400秒、提前刷新86400秒（由共享SDK常量实现）、绑定300秒；新会话保存策略快照。发布配置提供minimum_client_version与切换标志，未登记真实最低版本不得启用全量旧JWT拒绝。配置层不得导入用户domain或读取本地文件做共享状态。
  - **覆盖 AC**：AC-05, AC-06, AC-07
  - **依赖**：T001
  - **验证／完成条件**：验证合法默认与非法参数；不覆盖旧DSH配置，也不修改现有Cookie JWT全局秘密。

- [x] **T003** [基础设施／基础设施]：定义平台会话及刷新模型
  - **文件**：`src/backend/bisheng/user/domain/models/platform_session.py`
  - **逻辑／上下文**：定义D1 §4.4两表、Session状态/版本/Home/投递状态/期限快照，Refresh摘要、代次和唯一约束；只管理用户域新表，字段满足MySQL/DM8，不新增一份OAuth客户端表。
  - **覆盖 AC**：AC-06, AC-12, AC-30
  - **依赖**：T002
  - **验证／完成条件**：模型元数据可在独立测试库创建；当前任务不执行生产迁移。

- [x] **T004** [基础设施／基础设施]：增量迁移及模型发现登记
  - **文件**：`src/backend/bisheng/core/database/tenant_filter.py`, `src/backend/test/platform_auth/test_platform_wiring.py`
  - **逻辑／上下文**：按backend AGENTS §Migration policy，独立新表由模型发现与online upgrade的create_all(checkfirst=True)创建，无既有表变更时不增空白Alembic revision；登记租户过滤，验证新装与升级一致，不重定义旧DSH或OAuth表。不删除认证表及退出记录；删除仅允许在专用空库或另行批准的数据退役流程。
  - **覆盖 AC**：AC-29, AC-30
  - **依赖**：T003
  - **验证／完成条件**：核对新装与升级schema、tenant过滤发现；回滚不删活动数据或恢复全量数据库。

- [x] **T005** [基础设施／基础设施]：登记平台认证错误契约
  - **文件**：`src/backend/bisheng/common/errcode/platform_auth.py`
  - **逻辑／上下文**：实施前复查10650至10664占用，冲突按C5重分配并同步契约；定义真实HTTP状态、auth_reason和retryable，保留原10604/10620/19103，不混入前端文件。
  - **覆盖 AC**：AC-10, AC-17, AC-19, AC-25, AC-28
  - **依赖**：T001
  - **验证／完成条件**：错误码唯一；临时503与明确401、客户端426可区分；不把网络故障改为密码错误。

- [x] **T006** [基础设施／基础设施]：补齐canonical中文认证错误
  - **文件**：`src/frontend/packages/locales/src/api_errors/zh-Hans.json`
  - **逻辑／上下文**：使用前驱确定的用户域错误码补齐canonical中文；不新增另一套客户端编号，不手改派生副本。
  - **覆盖 AC**：AC-10, AC-17, AC-19, AC-25, AC-28
  - **依赖**：T005
  - **验证／完成条件**：canonical中文与后端错误语义一致，不含敏感信息。

- [x] **T007** [基础设施／基础设施]：补齐英文和日文认证错误
  - **文件**：`src/frontend/packages/locales/src/api_errors/en.json`, `src/frontend/packages/locales/src/api_errors/ja.json`
  - **逻辑／上下文**：按canonical中文键补齐英文/日文，不新增第二套客户端错误编号；派生api_errors由现有生成流程在验证阶段同步，不手改生成文件。
  - **覆盖 AC**：AC-10, AC-17, AC-25, AC-28
  - **依赖**：T006
  - **验证／完成条件**：三语canonical键一致；各错误原因保持语义。

- [x] **T008** [基础设施／基础设施]：准备无外部依赖的认证测试夹具
  - **文件**：`src/backend/test/platform_auth/test_platform_session.py`, `src/backend/test/platform_auth/test_platform_wiring.py`
  - **逻辑／上下文**：准备可控UTC时钟、已验证普通/管理员身份、Session快照、存储失败及并发屏障；敏感材料只在测试内存。夹具不替代后续真实MySQL/DM8、网关、安装包验收。
  - **覆盖 AC**：AC-05, AC-06, AC-12, AC-30
  - **依赖**：T003, T007
  - **验证／完成条件**：pytest可收集基础夹具；不向运行环境注入生产秘密或修改系统时钟。

- [x] **T009** [基础设施／基础设施]：定义后端响应与窄存储协议
  - **文件**：`src/backend/bisheng/user/domain/schemas/password_identity.py`, `src/backend/bisheng/user/domain/repositories/platform_session.py`
  - **逻辑／上下文**：固定D1响应字段、Session/Refresh快照和服务端策略、store锁内转移接口；平台与旧DSH适配共享规则但各自持有原数据。协议不得接受body中的任意user_id/Home做已验证身份。
  - **覆盖 AC**：AC-01, AC-04, AC-08, AC-27
  - **依赖**：T003
  - **验证／完成条件**：协议值对象可序列化，UTC/整数TTL明确；未写业务行为。

- [x] **T010** [基础设施／基础设施]：定义共享浏览器认证类型
  - **文件**：`src/frontend/packages/api-client/src/authTypes.ts`
  - **逻辑／上下文**：固定cookie/native/host刷新模式、错误原因、到期metadata和Session选择标记类型；该纯声明不依赖任一SPA store，不持久化Token。
  - **覆盖 AC**：AC-01, AC-14, AC-17
  - **依赖**：T009
  - **验证／完成条件**：类型能表达PENDING/BOUND、host及可重试失败，未引入React状态库。

- [x] **T011** [基础设施／基础设施]：登记共享前端auth请求作用域契约
  - **文件**：`src/frontend/packages/api-client/src/requestScopeRoutes.json`
  - **逻辑／上下文**：依据D1方法与路径登记auth的PUBLIC transport、credential-owned和identity分类；此为共享客户端契约输入，不改网关程序、不把认证路径无条件放行。后端真正路由注册由后续API任务完成。
  - **覆盖 AC**：AC-09, AC-26, AC-27, AC-29
  - **依赖**：T010
  - **验证／完成条件**：schema与既有作用域生成检查通过；auth调用不注入管理租户头。


### Wave 2：通用Domain核心（Test-First）

- [x] **T012** [后端 Domain／测试]：轮换状态机红测
  - **文件**：`src/backend/test/platform_auth/test_platform_session.py`
  - **逻辑／上下文**：以锁后时间和快照断言消费、直接未用后继恢复、24小时外重放、撤销优先与过期边界；同时覆盖旧DSH策略参数，测试不包含实现逻辑。
  - **覆盖 AC**：AC-08, AC-10, AC-11, AC-12
  - **依赖**：T009, T008
  - **验证／完成条件**：用pytest运行该文件，先记录缺规则模块导致的红测，再由配对任务变绿。

- [x] **T013** [后端 Domain／实现]：提炼无IO轮换规则
  - **文件**：`src/backend/bisheng/user/domain/services/session_rotation.py`, `src/backend/bisheng/user/application/session_protocol.py`
  - **逻辑／上下文**：输入锁内Session/当前代/后继/时间和服务端策略，输出消费、恢复、撤销或拒绝；保留DSH确定性恢复规则，不能按客户端输入选策略。
  - **覆盖 AC**：AC-08, AC-10, AC-11, AC-12
  - **依赖**：T012
  - **验证／完成条件**：rules_test全部变绿；无SQL、HTTP、文件及domain反向依赖。
  - **前置测试**：T012；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T014** [后端 Domain／测试]：平台Token及用途密钥红测
  - **文件**：`src/backend/test/platform_auth/test_platform_session.py`
  - **逻辑／上下文**：断言30天默认、Session截断、platform typ/kid/iss/aud、字段校验，拒绝DSH/OAuth/错误用途；验证新purpose不改变旧主秘密及派生结果。
  - **覆盖 AC**：AC-05, AC-19, AC-27, AC-30
  - **依赖**：T008, T002
  - **验证／完成条件**：红测覆盖签名、时间与用途，测试内存材料不打印到日志。

- [x] **T015** [后端 Domain／实现]：实现平台codec和用途密钥
  - **文件**：`src/backend/bisheng/user/domain/services/platform_session.py`
  - **逻辑／上下文**：严格校验平台类型与用途并解析规范Principal；Access本身默认30天且不超Session。新Access、Refresh后继、Web首代绑定分别使用purpose key，签名失败不退回普通旧JWT。
  - **覆盖 AC**：AC-05, AC-19, AC-27, AC-30
  - **依赖**：T014, T013
  - **验证／完成条件**：codec_test通过；旧DSH密钥与OAuth ES256派生保持不变。
  - **前置测试**：T014；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T016** [后端 Domain／测试]：仓储事务与并发红测
  - **文件**：`src/backend/test/platform_auth/test_platform_session.py`
  - **逻辑／上下文**：覆盖唯一后继、回滚不半消费、用户锁单点串行、活动到期、Session撤销、历史摘要保留；后续参数化真实MySQL/DM8，当前单元夹具不得替代实库。
  - **覆盖 AC**：AC-06, AC-07, AC-08, AC-11, AC-12, AC-13, AC-15, AC-30
  - **依赖**：T008, T013
  - **验证／完成条件**：红测包含两个Refresh、退出竞争、等待锁跨到期点及双库参数入口。

- [x] **T017** [后端 Domain／实现]：实现平台Session仓储
  - **文件**：`src/backend/bisheng/user/domain/repositories/platform_session.py`
  - **逻辑／上下文**：锁顺序用户准入→Session→Refresh；读取锁后时间，调用共享转移规则并事务写入；ACTIVE family保留USED摘要，撤销O(1)，终结24小时后批量清理。仅经已验证归属进入租户上下文。
  - **覆盖 AC**：AC-06, AC-07, AC-08, AC-11, AC-12, AC-13, AC-15, AC-30
  - **依赖**：T016, T004
  - **验证／完成条件**：仓储单元通过；不得在service写SQL或全链扫描才撤销。
  - **前置测试**：T016；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T018** [后端 Domain／测试]：既有登录校验提取红测
  - **文件**：`src/backend/test/platform_auth/test_platform_wiring.py`
  - **逻辑／上下文**：固定验证码、错误次数、密码过期、账号/组织禁用、Home及权限结果，断言不能由client_id、tenant_id或TTL入参提权。
  - **覆盖 AC**：AC-02, AC-04, AC-10
  - **依赖**：T008, T009
  - **验证／完成条件**：与既有账号登录回归对照；失败不产生可用会话。

- [x] **T019** [后端 Domain／实现]：提取已验证登录身份
  - **文件**：`src/backend/bisheng/user/domain/services/user.py`, `src/backend/bisheng/user/domain/schemas/password_identity.py`
  - **逻辑／上下文**：从既有UserService校验提炼无签发/无Cookie的身份流程，产出服务端VerifiedLoginIdentity；不整体调用会签旧JWT的user_login，不夺组织/角色Owner写入权。
  - **覆盖 AC**：AC-02, AC-04, AC-10
  - **依赖**：T018
  - **验证／完成条件**：identity_test及既有账号校验回归通过；旧入口暂未切换。
  - **前置测试**：T018；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T020** [后端 Domain／测试]：Session期限与策略红测
  - **文件**：`src/backend/test/platform_auth/test_platform_session.py`
  - **逻辑／上下文**：断言30天Access、90天闲置、仅业务活动顺延、Refresh不保活、Access过期可恢复、配置快照、单点及全部退出仅平台范围。
  - **覆盖 AC**：AC-01, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-13, AC-15
  - **依赖**：T017, T019, T015
  - **验证／完成条件**：精确边界用时钟夹具，不等真实30/90天。

- [x] **T021** [后端 Domain／实现]：实现平台Session生命周期
  - **文件**：`src/backend/bisheng/user/domain/services/platform_session.py`
  - **逻辑／上下文**：编排创建/准入/刷新/活动/撤销，调用仓储和codec，输出既定metadata；用户版本/Home和状态重新确认；临时依赖故障不可fail-open，不继承DSH专用Scope。
  - **覆盖 AC**：AC-01, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-13, AC-15
  - **依赖**：T020
  - **验证／完成条件**：session_test变绿；服务层无SQL和原始凭证日志。
  - **前置测试**：T020；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T022** [后端 Domain／测试]：网关首次Web绑定红测
  - **文件**：`src/backend/test/platform_auth/test_platform_session.py`, `src/backend/test/platform_auth/test_platform_api.py`
  - **逻辑／上下文**：以新WEB PENDING Session验证300秒窗口、首代响应丢失恢复、首代已消费拒绝、旧普通JWT不能升级；不模拟网关转发新Cookie。
  - **覆盖 AC**：AC-03, AC-12, AC-19, AC-23
  - **依赖**：T021
  - **验证／完成条件**：红测覆盖BOUND及PENDING状态、确定性首代与Session撤销。

- [x] **T023** [后端 Domain／实现]：实现受限Web首代绑定
  - **文件**：`src/backend/bisheng/user/domain/services/platform_session.py`
  - **逻辑／上下文**：只对新WEB会话在窗口内绑定首代；摘要存储，恢复同一未用值，不重置已轮换链；过期或撤销不可复活，待绑定态不能准入业务。
  - **覆盖 AC**：AC-03, AC-12, AC-19, AC-23
  - **依赖**：T022
  - **验证／完成条件**：binding_test通过；不是旧网页Token换长期凭证的后门。
  - **前置测试**：T022；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T024** [后端 Domain／测试]：手机Web票据红测
  - **文件**：`src/backend/test/platform_auth/test_platform_api.py`
  - **逻辑／上下文**：覆盖60秒、单次消费、同origin、固定站内回跳、父sid撤销、host模式和Redis故障；票据不建立第二个长期会话。
  - **覆盖 AC**：AC-01, AC-04, AC-15, AC-26, AC-27, AC-28
  - **依赖**：T021
  - **验证／完成条件**：红测不把票据或原生Refresh放入日志/URL报告。

- [x] **T025** [后端 Domain／实现]：实现手机Web票据及存储
  - **文件**：`src/backend/bisheng/user/domain/services/platform_session.py`, `src/backend/bisheng/user/domain/models/platform_session.py`
  - **逻辑／上下文**：Redis摘要存票据，原子消费；绑定验证后parent sid、origin和固定consume入口；网页只得受父Session约束的平台Access，不给原生Refresh。
  - **覆盖 AC**：AC-01, AC-04, AC-15, AC-26, AC-27, AC-28
  - **依赖**：T024
  - **验证／完成条件**：ticket_test通过；服务不可用不放行未知票据。
  - **前置测试**：T024；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T026** [后端 Domain／测试]：网页CSRF恢复红测
  - **文件**：`src/backend/test/platform_auth/test_platform_api.py`
  - **逻辑／上下文**：覆盖同源、错误Origin/Fetch Metadata、会话nonce、Access过期后凭Refresh取得CSRF及native标签不能绕过Cookie认证防护。
  - **覆盖 AC**：AC-04, AC-09, AC-27, AC-28
  - **依赖**：T021
  - **验证／完成条件**：GET csrf不返回身份或原始凭证、不记录业务活动。

- [x] **T027** [后端 Domain／实现]：实现平台CSRF策略
  - **文件**：`src/backend/bisheng/user/domain/services/platform_transport.py`, `src/backend/bisheng/user/domain/services/platform_origin.py`
  - **逻辑／上下文**：按D1为Cookie认证验证完整Origin及绑定nonce，Refresh恢复不要求未过期Access；公开client_id不具备绕过防护能力。
  - **覆盖 AC**：AC-04, AC-09, AC-27, AC-28
  - **依赖**：T026
  - **验证／完成条件**：csrf_test变绿；与第三方OAuth consent原协议隔离。
  - **前置测试**：T026；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T028** [后端 Domain／测试]：公开认证应用协议红测
  - **文件**：`src/backend/test/platform_auth/test_platform_wiring.py`
  - **逻辑／上下文**：验证login_password、issue_verified_login、admit、refresh、revoke、bind_web_refresh的入参及路由结果；HMAC流程只能提供已验证身份，外部user_id不直接签发。
  - **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-08, AC-15
  - **依赖**：T019, T021, T023, T025, T027
  - **验证／完成条件**：使用domain fake验证调用责任，无跨模块API导入。

- [x] **T029** [后端 Domain／实现]：建立用户域公开应用接口
  - **文件**：`src/backend/bisheng/user/application/platform_auth.py`, `src/backend/bisheng/user/platform_auth_runtime.py`
  - **逻辑／上下文**：组合已完成Domain能力，暴露稳定应用入口；保持domain不反向导入application，不反调旧完整登录或写业务权限。
  - **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-08, AC-15
  - **依赖**：T028
  - **验证／完成条件**：facade_test通过；调用方不接触内部ORM。
  - **前置测试**：T028；本任务不修改确认的测试预期以掩盖实现错误。


### Wave 3：准入、活动、旧DSH与延后执行

- [x] **T030** [后端 Domain／测试]：统一准入及用途隔离红测
  - **文件**：`src/backend/test/platform_auth/test_platform_wiring.py`
  - **逻辑／上下文**：验证Session/版本/Home权威、Cookie与Bearer冲突、用途不匹配、普通旧JWT拒绝及存储503不删除凭据；不吞掉失效原因。
  - **覆盖 AC**：AC-04, AC-10, AC-17, AC-19, AC-26, AC-27, AC-28
  - **依赖**：T029
  - **验证／完成条件**：红测含旧DSH桥接专用分支与新格式失败不得降级。

- [x] **T031** [后端 Domain／实现]：实现统一准入及注入Port
  - **文件**：`src/backend/bisheng/user/domain/services/platform_identity.py`, `src/backend/bisheng/user/platform_auth_runtime.py`
  - **逻辑／上下文**：从明确路由拥有者取证明，规范Principal并检查数据库Session；提供旧AuthJwt/LoginUser可注入的准入Port，保留平台管理Home与作用域，不套用DSH principal_scope。
  - **覆盖 AC**：AC-04, AC-10, AC-17, AC-19, AC-26, AC-27, AC-28
  - **依赖**：T030
  - **验证／完成条件**：admission_test通过；依赖方向单向，查询失败503。
  - **前置测试**：T030；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T032** [后端 Domain／测试]：旧身份消费者适配红测
  - **文件**：`src/backend/test/platform_auth/test_platform_wiring.py`
  - **逻辑／上下文**：覆盖UserPayload/HTTP/WS入口，普通旧封装拒绝、真实DSH bridge可用、规范身份和runtime reference生成；避免JSON sub解析残留。
  - **覆盖 AC**：AC-04, AC-19, AC-20, AC-21, AC-26
  - **依赖**：T031
  - **验证／完成条件**：先固定consumer断言，再改旧入口；不借此重签DSH bridge。

- [x] **T033** [后端 Domain／实现]：适配AuthJwt与LoginUser
  - **文件**：`src/backend/bisheng/user/domain/services/auth.py`, `src/backend/bisheng/user/domain/services/platform_identity.py`
  - **逻辑／上下文**：旧业务取身份入口委托已注入准入或已验证request.state；保留DSH bridge验证和旧专用签发用途；生成platform_session引用，不能全局替换AuthJwt.create_access_token。
  - **覆盖 AC**：AC-04, AC-19, AC-20, AC-21, AC-26
  - **依赖**：T032
  - **验证／完成条件**：oldfacade_test及既有token-version/DSH桥接回归通过。
  - **前置测试**：T032；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T034** [后端 API／测试]：HTTP路由认证归属红测
  - **文件**：`src/backend/test/platform_auth/test_platform_api.py`, `src/backend/test/platform_auth/test_mobile_routes.py`
  - **逻辑／上下文**：覆盖cookie/native/host路由分类、Refresh不用有效Access、匿名/v2/OAuth专属协议不被全局JWT逻辑接管。
  - **覆盖 AC**：AC-09, AC-19, AC-21, AC-27, AC-28
  - **依赖**：T033
  - **验证／完成条件**：真实路由fixture验证401/400/503，不把所有auth路径无条件放行。

- [x] **T035** [后端 API／实现]：接入全局HTTP认证边界
  - **文件**：`src/backend/bisheng/utils/http_middleware.py`, `src/backend/bisheng/admin/application/request_admission.py`
  - **逻辑／上下文**：在明确路由owner之后委托用户域应用准入，复用一次已验证身份；普通旧JWT拒绝与旧DSH bridge区分，保留请求管理范围与独立凭证边界。
  - **覆盖 AC**：AC-09, AC-19, AC-21, AC-27, AC-28
  - **依赖**：T034
  - **验证／完成条件**：middleware_test及现有route-login-guard回归通过；未扩大匿名白名单。
  - **前置测试**：T034；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T036** [后端 Domain／测试]：业务活动登记与不保活红测
  - **文件**：`src/backend/test/platform_auth/test_mobile_routes.py`, `src/backend/test/platform_auth/test_platform_session.py`
  - **逻辑／上下文**：根据baseline输出的具体路由清单覆盖聊天/workflow/agent/上传/业务写入、WS action与RPC method；身份读取、Refresh、配置和心跳不续期，未知声明不猜测活动。
  - **覆盖 AC**：AC-07, AC-08, AC-10, AC-12, AC-26
  - **依赖**：T021, T001
  - **验证／完成条件**：覆盖scope能力仅认证后安装，等待锁跨到期不可复活。

- [x] **T037** [后端 Domain／实现]：接入平台活动recorder及路由策略
  - **文件**：`src/backend/bisheng/user/domain/services/platform_identity.py`, `src/backend/bisheng/dsh/api/endpoints/mobile.py`
  - **逻辑／上下文**：复用core中立Activity能力，服务端显式登记baseline已核实的路由/action/method，输出活动metadata；不存在路由声明时失败暴露，不随意把GET都当活动。core不导入user/domain。
  - **覆盖 AC**：AC-07, AC-08, AC-10, AC-12, AC-26
  - **依赖**：T036
  - **验证／完成条件**：activity_test通过，已登记路由可追踪；不改DSH旧活动期限。
  - **前置测试**：T036；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T038** [后端 Domain／测试]：旧DSH轮换等价红测
  - **文件**：`src/backend/test/dsh/test_idle_sessions.py`, `src/backend/test/platform_auth/test_platform_session.py`
  - **逻辑／上下文**：固定旧密钥/typ/aud/9个claims/600秒上限、ABSOLUTE与SLIDING期限、重放恢复及错误映射，对照共享规则；不把新默认套旧数据。
  - **覆盖 AC**：AC-11, AC-12, AC-20, AC-21, AC-24
  - **依赖**：T013, T008
  - **验证／完成条件**：复用现有DSH测试基线；源码等价不等于安装包验收。

- [x] **T039** [后端 Domain／实现]：旧DSH委托通用轮换规则
  - **文件**：`src/backend/bisheng/dsh/domain/repositories/local_session.py`, `src/backend/bisheng/user/application/session_protocol.py`
  - **逻辑／上下文**：仅将可等价共享的状态决策接到用户域公开规则/Port；保留旧存储、codec、期限、错误与身份流。等价失败须记录未完成而非扩大到桌面迁移。
  - **覆盖 AC**：AC-11, AC-12, AC-20, AC-21, AC-24
  - **依赖**：T038
  - **验证／完成条件**：dsh_test与现有DSH回归全过；不要求安装包升级。
  - **前置测试**：T038；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T040** [Worker／测试]：延后身份生产消费红测
  - **文件**：`src/backend/test/platform_auth/test_platform_wiring.py`, `src/backend/test/platform_auth/test_platform_session.py`
  - **逻辑／上下文**：覆盖新platform_session引用从HTTP生成到app_runtime创建/运行，原Access过期、撤销、Home和身份版本变化拒绝；断言原Celery headers.tenant_id恢复ContextVar；旧DSH reference继续其专用校验。
  - **覆盖 AC**：AC-04, AC-16, AC-26, AC-27
  - **依赖**：T033, T039
  - **验证／完成条件**：测试中不持久化原始Token，排队屏障后重新校验，不虚构业务回滚。

- [x] **T041** [Worker／实现]：适配延后执行身份resolver
  - **文件**：`src/backend/bisheng/user/application/runtime_identity.py`, `src/backend/bisheng/app_runtime/domain/services/runtime_authorization_service.py`
  - **逻辑／上下文**：支持platform_session及原Access期限，执行前走统一准入；保留旧DSH引用。若经Celery，复用现有headers.tenant_id→ContextVar，在worker进程初始化认证Port；不只在API lifespan注册，不创建额外任务队列。
  - **覆盖 AC**：AC-04, AC-16, AC-26, AC-27
  - **依赖**：T040
  - **验证／完成条件**：runtime_test通过；后台执行与查询不续期登录闲置。
  - **前置测试**：T040；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T042** [后端 API／测试]：长连接撤销与失败预算红测
  - **文件**：`src/backend/test/platform_auth/test_platform_stream.py`, `src/backend/test/platform_auth/test_mobile_routes.py`
  - **逻辑／上下文**：覆盖HTTP流body、WS收发、Access到期、Session撤销和2秒状态读取超时；5秒以内停止认证输出，不接管匿名或第三方协议。
  - **覆盖 AC**：AC-09, AC-16, AC-26, AC-28
  - **依赖**：T031, T037
  - **验证／完成条件**：以可控时钟和流屏障断言边界，不靠sleep长等。

- [x] **T043** [后端 API／实现]：实现平台连接准入守卫
  - **文件**：`src/backend/bisheng/user/domain/services/platform_stream.py`, `src/backend/bisheng/admin/application/request_admission.py`
  - **逻辑／上下文**：服务端按已验证platform身份安装长连接检查，新消息前重新准入；正常状态最长5秒复查，读取2秒超时即暂停认证输出并报告服务故障。
  - **覆盖 AC**：AC-09, AC-16, AC-26, AC-28
  - **依赖**：T042
  - **验证／完成条件**：stream_test变绿；不承诺停止业务后台进程或回滚已提交结果。
  - **前置测试**：T042；本任务不修改确认的测试预期以掩盖实现错误。


### Wave 4：平台API、组合根与既有认证接缝

- [x] **T044** [后端 API／测试]：Web Cookie交付红测
  - **文件**：`src/backend/test/platform_auth/test_platform_api.py`
  - **逻辑／上下文**：覆盖按sid命名Access/Refresh、121天物理存储与90天逻辑期限区别、选择标记不认证、旧sid迟到Set-Cookie不能覆盖新sid、host无Refresh。
  - **覆盖 AC**：AC-06, AC-07, AC-09, AC-14, AC-18, AC-21, AC-23
  - **依赖**：T023, T027, T033
  - **验证／完成条件**：需验证完整HTTP响应头；不能只延迟JS Promise。

- [x] **T045** [后端 API／实现]：实现Session Cookie传输适配
  - **文件**：`src/backend/bisheng/user/domain/services/platform_transport.py`
  - **逻辑／上下文**：web写HttpOnly会话命名Cookie，不向JS返回RT；固定access_token_cookie仅用于原网关PENDING及旧DSH；服务端Refresh不写选择标记，不扫描孤立Cookie找身份。
  - **覆盖 AC**：AC-06, AC-07, AC-09, AC-14, AC-18, AC-21, AC-23
  - **依赖**：T044
  - **验证／完成条件**：cookie_test变绿；路径、SameSite、内网HTTP和Secure配置符合D1。
  - **前置测试**：T044；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T046** [后端 API／测试]：平台接口真实HTTP契约红测
  - **文件**：`src/backend/test/platform_auth/test_platform_api.py`
  - **逻辑／上下文**：覆盖D1所有auth端点、web/native响应差异、真实HTTP状态、no-store、CSRF恢复、绑定、Web票据、幂等退出及请求冲突；Domain能力可注入以隔离API契约。
  - **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-08, AC-09, AC-10, AC-15, AC-17, AC-23, AC-27, AC-28
  - **依赖**：T029, T045, T035
  - **验证／完成条件**：在真实路由与错误处理中验证，不能HTTP200包所有失败。

- [x] **T047** [后端 API／实现]：接入login与session接口
  - **文件**：`src/backend/bisheng/user/api/endpoints/platform_auth.py`
  - **逻辑／上下文**：实现POST auth/login与GET auth/session，校验client_id等schema；返回data公共metadata、native凭证或web Cookie，host模式可识别；不信任用户请求的Home/TTL。
  - **覆盖 AC**：AC-01, AC-02, AC-04, AC-09, AC-21
  - **依赖**：T046
  - **验证／完成条件**：api_test中login/session用例通过；后续端点以增量任务扩展同一文件。
  - **前置测试**：T046；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T048** [后端 API／实现]：增量接入refresh及退出和csrf
  - **文件**：`src/backend/bisheng/user/api/endpoints/platform_auth.py`
  - **逻辑／上下文**：在已有auth router增量加入refresh/logout/logout-all/csrf；Refresh自证不要求有效Access，Cookie防护和native JSON不混传，统一退出不触碰旧DSH/OAuth。
  - **覆盖 AC**：AC-08, AC-09, AC-10, AC-15, AC-17, AC-27, AC-28
  - **依赖**：T047
  - **验证／完成条件**：api_test相应用例通过；不重写前驱login/session。
  - **前置测试**：T046；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T049** [后端 API／实现]：增量接入bootstrap和Web票据
  - **文件**：`src/backend/bisheng/user/api/endpoints/platform_auth.py`
  - **逻辑／上下文**：增加web-bootstrap、web-session签发/consume；300秒绑定、60秒单次票据、303固定回跳、票据query脱敏；仅写所属sid Cookie，不重新初始化已用链。
  - **覆盖 AC**：AC-03, AC-12, AC-23, AC-26, AC-27, AC-30
  - **依赖**：T048
  - **验证／完成条件**：api_test全通过；新接口必须按自己证明准入。
  - **前置测试**：T046；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T050** [后端 API／测试]：进程组合与路由作用域红测
  - **文件**：`src/backend/test/platform_auth/test_platform_wiring.py`
  - **逻辑／上下文**：验证main真实路由、认证Port在API及worker角色可用、刷新自身认证、模型发现、多副本配置与地板版本协议能力；不是import成功即完成。
  - **覆盖 AC**：AC-09, AC-26, AC-27, AC-29, AC-30
  - **依赖**：T049, T043, T041
  - **验证／完成条件**：真实组合测试失败可定位角色/route，不用缺依赖时默认身份。

- [x] **T051** [后端 API／实现]：组合认证runtime和进程入口
  - **文件**：`src/backend/bisheng/user/platform_auth_runtime.py`, `src/backend/bisheng/main.py`
  - **逻辑／上下文**：定义进程内认证runtime工厂，在API组合根安装Port、连接守卫和活动策略；API与worker复用同一工厂。worker无API lifespan的延迟初始化由后续独立任务完成，core不导入domain。
  - **覆盖 AC**：AC-26, AC-27, AC-29, AC-30
  - **依赖**：T050
  - **验证／完成条件**：composition_test的API组合部分通过；worker无API lifespan场景在下一配对任务完成后全绿。
  - **前置测试**：T050；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T052** [Worker／实现]：接入无API lifespan的worker认证初始化
  - **文件**：`src/backend/bisheng/user/platform_auth_runtime.py`, `src/backend/bisheng/user/application/runtime_identity.py`
  - **逻辑／上下文**：在延后身份resolver首次调用时取得与API相同的进程内runtime工厂，不依赖main.py执行；Celery继续headers.tenant_id→ContextVar，完成当前Session/Home/原Access期限准入。只增量接初始化，不重写前驱身份规则、不新建队列。
  - **覆盖 AC**：AC-16, AC-26, AC-29, AC-30
  - **依赖**：T051, T041
  - **验证／完成条件**：前置runtime_wiring的worker用例及runtime_identity测试全绿；独立worker角色导入/调用可复核。
  - **前置测试**：T050；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T053** [后端 API／实现]：登记后端auth路由及认证归属
  - **文件**：`src/backend/bisheng/api/router.py`, `src/backend/bisheng/user/api/endpoints/platform_auth.py`
  - **逻辑／上下文**：只在后端根router登记新auth router及逐方法认证归属，依赖组合runtime就绪；不触碰共享前端文件，不扩大匿名/v2/OAuth豁免。
  - **覆盖 AC**：AC-09, AC-26, AC-27, AC-29
  - **依赖**：T051
  - **验证／完成条件**：composition_test和middleware_test的真实路由矩阵通过。
  - **前置测试**：T050；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T054** [后端 API／测试]：旧网页登录接口适配红测
  - **文件**：`src/backend/test/platform_auth/test_platform_wiring.py`
  - **逻辑／上下文**：覆盖user/login原密码入参、user/info展示字段、user/logout与普通旧JWT重登；旧DSH网页退出只影响浏览器绑定，不能撤桌面。
  - **覆盖 AC**：AC-01, AC-02, AC-15, AC-19, AC-20, AC-21
  - **依赖**：T053
  - **验证／完成条件**：测试先锁定已有展示语义及无关偏好保护。

- [x] **T055** [后端 API／实现]：接入旧网页路径到平台核心
  - **文件**：`src/backend/bisheng/user/domain/services/user.py`, `src/backend/bisheng/user/api/user.py`
  - **逻辑／上下文**：仅替换普通密码/退出的旧签发编排，调用新应用接口，保留user/info展示；删除废弃普通旧JWT签发与Redis当前Token通用依赖，不能误删DSH桥接专用AuthJwt用途。
  - **覆盖 AC**：AC-01, AC-02, AC-15, AC-19, AC-20, AC-21
  - **依赖**：T054
  - **验证／完成条件**：legacy_web_test及原账号登录回归通过，不清全部localStorage/业务数据。
  - **前置测试**：T054；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T056** [后端 Domain／测试]：网关HMAC签发兼容红测
  - **文件**：`src/backend/test/platform_auth/test_platform_api.py`, `src/backend/test/sso/test_sso_login_sync_service.py`
  - **逻辑／上下文**：保持payload、HMAC、LoginSyncResponse三字段和组织Owner时序；验证同步失败不签Session，成功返回新PENDING平台Token且可绑定；不替网关新增Cookie契约。
  - **覆盖 AC**：AC-02, AC-03, AC-23
  - **依赖**：T023, T053, T001
  - **验证／完成条件**：与已有sso_sync回归对照；真实网关仍需外部验证。

- [x] **T057** [后端 Domain／实现]：SSO Sync后端改为统一签发
  - **文件**：`src/backend/bisheng/sso_sync/domain/services/login_sync_service.py`
  - **逻辑／上下文**：身份/组织同步完成后调用issue_verified_login；user_id/leaf_tenant_id/token与HMAC外部合同不改，只交付新平台PENDING会话；不修改网关仓库。
  - **覆盖 AC**：AC-02, AC-03, AC-23
  - **依赖**：T056
  - **验证／完成条件**：gateway_test和既有SSO同步回归通过。
  - **前置测试**：T056；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T058** [后端 API／测试]：第三方SSO身份接缝红测
  - **文件**：`src/backend/test/oauth2_provider/test_protocol.py`, `src/backend/test/platform_auth/test_platform_wiring.py`
  - **逻辑／上下文**：验证新网页登录后authorize/consent免确认/确认/拒绝、无效平台Session不能自动授权，原ES256 Token和范围不变；新网页登录也能完成旧DSH浏览器授权。
  - **覆盖 AC**：AC-20, AC-22, AC-24, AC-27
  - **依赖**：T053, T033, T039
  - **验证／完成条件**：保留现有OAuth public/confidential/token/revoke回归，不换其会话存储。

- [x] **T059** [后端 API／实现]：适配SSO与DSH读取新网页身份
  - **文件**：`src/backend/bisheng/user/domain/services/auth.py`, `src/backend/bisheng/user/application/legacy_bridge.py`
  - **逻辑／上下文**：仅替换browser identity读取接缝，依赖统一Port/UserPayload；原OAuth协议、DSH票据PKCE与配置保持，不将OAuth Token直接用于平台业务。
  - **覆盖 AC**：AC-20, AC-22, AC-24, AC-27
  - **依赖**：T058
  - **验证／完成条件**：oidc_test与已有OAuth2协议回归通过。
  - **前置测试**：T058；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T060** [后端 API／测试]：手机旧接口退役及业务准入红测
  - **文件**：`src/backend/test/platform_auth/test_mobile_routes.py`, `src/backend/test/platform_auth/test_platform_wiring.py`
  - **逻辑／上下文**：验证旧建会话/刷新返回明确426及minimum_client_version，新平台Token可用于电脑列表/RPC/stream，账户Home匹配；不得把旧手机会话冒充新会话迁移。
  - **覆盖 AC**：AC-01, AC-04, AC-25, AC-26
  - **依赖**：T053, T035
  - **验证／完成条件**：未知实际最低版本不能写成已兼容；业务路径保持。

- [x] **T061** [后端 API／实现]：手机服务端切换与旧签发停止
  - **文件**：`src/backend/bisheng/dsh/api/endpoints/mobile.py`, `src/backend/bisheng/user/domain/services/user.py`
  - **逻辑／上下文**：电脑业务入口使用平台身份；切换标志启用后旧手机签发/刷新明确升级语义；停止旧独立引擎新写入，保留未进入退役批次的历史数据，不影响旧DSH桌面。
  - **覆盖 AC**：AC-01, AC-04, AC-25, AC-26
  - **依赖**：T060
  - **验证／完成条件**：mobile_routes_test通过；开关只能与新手机发布协调启用。
  - **前置测试**：T060；本任务不修改确认的测试预期以掩盖实现错误。


### Wave 5：共享浏览器认证模块

- [x] **T062** [共享前端／测试]：跨标签互斥及fencing测试
  - **文件**：`src/frontend/packages/api-client/src/authCoordination.test.ts`
  - **逻辑／上下文**：覆盖Web Locks、IndexedDB租约接管、BroadcastChannel通知、旧持有者恢复及epoch；模拟完整Cookie响应时序，不能以广播替代锁。
  - **覆盖 AC**：AC-14, AC-18
  - **依赖**：T010
  - **验证／完成条件**：测试先行，隔离storage并在用例后恢复环境。

- [x] **T063** [共享前端／实现]：实现跨标签认证协调
  - **文件**：`src/frontend/packages/api-client/src/authCoordination.ts`
  - **逻辑／上下文**：实现同源锁与fallback、login/logout/refresh串行，以及可检查的generation；不依赖Zustand/Recoil，不建立任一端专用刷新器。
  - **覆盖 AC**：AC-14, AC-18
  - **依赖**：T062
  - **验证／完成条件**：coord_test通过。
  - **前置测试**：T062；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T064** [共享前端／测试]：浏览器认证状态机测试
  - **文件**：`src/frontend/packages/api-client/src/authSession.test.ts`
  - **逻辑／上下文**：覆盖启动恢复、Access过期取csrf、Cookie/host模式、单次请求重试、临时503保留、PENDING绑定、sid选择及迟到响应；Token不进localStorage。
  - **覆盖 AC**：AC-01, AC-07, AC-08, AC-09, AC-14, AC-17, AC-18, AC-19, AC-21, AC-23
  - **依赖**：T063, T049, T011
  - **验证／完成条件**：先使用公开契约mock传输，不复制服务端业务规则。

- [x] **T065** [共享前端／实现]：实现共享浏览器认证控制器
  - **文件**：`src/frontend/packages/api-client/src/authSession.ts`, `src/frontend/packages/api-client/src/index.ts`
  - **逻辑／上下文**：导出同一启动/刷新/退出控制器，服务端Refresh不写选择标记，JS仅在epoch有效时选择sid；host交还宿主，临时故障不清凭证；通过API传输适配器调用，不混store。
  - **覆盖 AC**：AC-01, AC-07, AC-08, AC-09, AC-14, AC-17, AC-18, AC-19, AC-21, AC-23
  - **依赖**：T064
  - **验证／完成条件**：browser_test通过；编译及公开导出无循环依赖。
  - **前置测试**：T064；本任务不修改确认的测试预期以掩盖实现错误。


### Wave 6：两套SPA与手机接入

- [x] **T066** [前端 Platform／测试]：Platform请求认证适配测试
  - **文件**：`src/frontend/platform/src/controllers/requestAuthSession.test.ts`
  - **逻辑／上下文**：验证新auth API、过期先合并续期再重试一次、管理范围恢复不与认证混淆、普通旧JWT重登、host不空Refresh。
  - **覆盖 AC**：AC-09, AC-14, AC-17, AC-19, AC-21, AC-27
  - **依赖**：T065, T053
  - **验证／完成条件**：使用共享控制器mock验证边界，不另写刷新状态机。

- [x] **T067** [前端 Platform／实现]：接入Platform请求层及auth API
  - **文件**：`src/frontend/platform/src/controllers/request.ts`, `src/frontend/platform/src/controllers/API/user.ts`
  - **逻辑／上下文**：以共享控制器适配平台Axios及真实HTTP错误；不把auth请求加管理租户头，移除ws_token作为普通新认证持久化路径。
  - **覆盖 AC**：AC-09, AC-14, AC-17, AC-19, AC-21, AC-27
  - **依赖**：T066
  - **验证／完成条件**：Platform相关Vitest与类型检查；手动验证一次过期请求、503恢复、host模式。
  - **前置测试**：T066；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T068** [前端 Platform／测试]：Platform登录及退出交互测试
  - **文件**：`src/frontend/platform/src/pages/LoginPage/platformAuth.test.tsx`
  - **逻辑／上下文**：覆盖验证码/密码过期/默认入口回跳、同会话退出、旧登录标记清理不删偏好；既有SSO入口可回跳。
  - **覆盖 AC**：AC-01, AC-02, AC-15, AC-19, AC-23
  - **依赖**：T067
  - **验证／完成条件**：按可见行为断言，不只搜字符串。

- [x] **T069** [前端 Platform／实现]：接入Platform登录与用户API
  - **文件**：`src/frontend/platform/src/pages/LoginPage/login.tsx`, `src/frontend/platform/src/controllers/API/user.ts`
  - **逻辑／上下文**：登录提交新共享流程，保留既有表单、验证码和回跳语义；退出按sid撤销，不写新Token到localStorage。
  - **覆盖 AC**：AC-01, AC-02, AC-15, AC-19, AC-23
  - **依赖**：T068
  - **验证／完成条件**：交互测试通过；手动从本地与网关入口分别登录。
  - **前置测试**：T068；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T070** [前端 Platform／测试]：Platform启动绑定与查询门控测试
  - **文件**：`src/frontend/platform/src/contexts/userAuthStartup.test.tsx`
  - **逻辑／上下文**：断言启动恢复/网关bootstrap完成前不突发业务401，host模式可读身份，新账号不被旧响应覆盖。
  - **覆盖 AC**：AC-14, AC-18, AC-21, AC-23, AC-24
  - **依赖**：T069
  - **验证／完成条件**：普通新登录及PENDING、BOUND、host四态覆盖。

- [x] **T071** [前端 Platform／实现]：接入Platform启动和上下文
  - **文件**：`src/frontend/platform/src/contexts/userContext.tsx`, `src/frontend/platform/src/store/authSessionStore.ts`
  - **逻辑／上下文**：在挂载业务查询前初始化共享认证，完成PENDING绑定并写非秘密sid标记；Zustand只消费状态，SSO/DSH授权页身份读取不回跳循环。
  - **覆盖 AC**：AC-14, AC-18, AC-21, AC-23, AC-24
  - **依赖**：T070
  - **验证／完成条件**：测试通过；手动旧DSH授权同意/拒绝均可用。
  - **前置测试**：T070；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T072** [前端 Client／测试]：Client请求认证适配测试
  - **文件**：`src/frontend/client/src/api/requestAuthSession.test.ts`
  - **逻辑／上下文**：覆盖共享控制器、过期恢复、503保留、host、匿名链接例外，避免与Platform同时发Refresh。
  - **覆盖 AC**：AC-09, AC-14, AC-17, AC-21, AC-27
  - **依赖**：T065, T053
  - **验证／完成条件**：Client使用Recoil，不引入Platform store。

- [x] **T073** [前端 Client／实现]：接入Client请求层与auth API
  - **文件**：`src/frontend/client/src/api/request.ts`, `src/frontend/client/src/api/chat/data-service.ts`
  - **逻辑／上下文**：接共享控制器及csrf/refresh契约；保留原匿名、分享回跳与管理范围行为；不能恢复注释掉的旧refresh机制作为第二套实现。
  - **覆盖 AC**：AC-09, AC-14, AC-17, AC-21, AC-27
  - **依赖**：T072
  - **验证／完成条件**：请求层测试及Client类型检查；手动与Platform并发过期。
  - **前置测试**：T072；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T074** [前端 Client／测试]：Client用户适配层测试
  - **文件**：`src/frontend/client/src/api/requestAuthSession.test.ts`
  - **逻辑／上下文**：验证getUser、logout与新Session元数据转换，已退出Session不由旧tokenUpdated事件恢复；字段不改变用户展示。
  - **覆盖 AC**：AC-01, AC-15, AC-18
  - **依赖**：T073
  - **验证／完成条件**：覆盖原API dataService调用方，不让网络逻辑进入Recoil store。

- [x] **T075** [前端 Client／实现]：替换Client旧认证API适配
  - **文件**：`src/frontend/client/src/api/chat/data-service.ts`, `src/frontend/client/src/pages/DevLogin/index.tsx`
  - **逻辑／上下文**：user信息保持原展示结构，logout委托新共享控制器；旧未用登录/refresh API不再参与主链路，不扩大第三方协议边界。
  - **覆盖 AC**：AC-01, AC-15, AC-18
  - **依赖**：T074
  - **验证／完成条件**：适配层测试变绿，原会话展示回归不变。
  - **前置测试**：T074；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T076** [前端 Client／测试]：Client上下文与启动门控测试
  - **文件**：`src/frontend/client/src/hooks/authStartup.test.tsx`
  - **逻辑／上下文**：覆盖Recoil身份与共享Session同步、先恢复后查询、旧凭证一次重登、已验证user不被effect晚一帧误跳登录。
  - **覆盖 AC**：AC-14, AC-17, AC-18, AC-19, AC-21, AC-23
  - **依赖**：T075
  - **验证／完成条件**：与现有RequireLogin/回跳测试一起验证。

- [x] **T077** [前端 Client／实现]：接入Client身份上下文与Root
  - **文件**：`src/frontend/client/src/hooks/AuthContext.tsx`
  - **逻辑／上下文**：用共享认证结果驱动Recoil和查询开关，不恢复旧静默刷新hook；host不跳普通登录，旧普通JWT只清认证标记。
  - **覆盖 AC**：AC-14, AC-17, AC-18, AC-19, AC-21, AC-23
  - **依赖**：T076
  - **验证／完成条件**：测试通过；手动跨SPA切换及独立分享链接。
  - **前置测试**：T076；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T078** [前端 Platform／实现]：补齐Platform认证界面中文文案
  - **文件**：`src/frontend/platform/public/locales/zh-Hans/bs.json`
  - **逻辑／上下文**：仅在Platform既有bs.json增量加入会话结束、服务暂不可用、升级和host重连文案；不得写Client目录，不新增竞争locale。
  - **覆盖 AC**：AC-10, AC-17, AC-25, AC-28
  - **依赖**：T071
  - **验证／完成条件**：Platform三语键检查；在/admin验证相应状态文案，不修改认证逻辑。

- [x] **T079** [前端 Client／实现]：补齐Client认证界面中文文案
  - **文件**：`src/frontend/client/src/locales/zh-Hans/translation.json`
  - **逻辑／上下文**：仅在已核实的Client现有translation.json增量加入前驱同一组认证文案，保持Recoil区独立，不写Platform文件或手改生成错误副本。
  - **覆盖 AC**：AC-10, AC-17, AC-25, AC-28
  - **依赖**：T077
  - **验证／完成条件**：Client三语键检查；在/workspace验证结束原因、重试或升级提示，不改变协议。

- [x] **T080** [前端 Platform／实现]：补齐Platform认证界面英文文案
  - **文件**：`src/frontend/platform/public/locales/en-US/bs.json`
  - **逻辑／上下文**：仅在Platform既有bs.json增量加入会话结束、服务暂不可用、升级和host重连文案；不得写Client目录，不新增竞争locale。
  - **覆盖 AC**：AC-10, AC-17, AC-25, AC-28
  - **依赖**：T078
  - **验证／完成条件**：Platform三语键检查；在/admin验证相应状态文案，不修改认证逻辑。

- [x] **T081** [前端 Client／实现]：补齐Client认证界面英文文案
  - **文件**：`src/frontend/client/src/locales/en/translation.json`
  - **逻辑／上下文**：仅在已核实的Client现有translation.json增量加入前驱同一组认证文案，保持Recoil区独立，不写Platform文件或手改生成错误副本。
  - **覆盖 AC**：AC-10, AC-17, AC-25, AC-28
  - **依赖**：T079
  - **验证／完成条件**：Client三语键检查；在/workspace验证结束原因、重试或升级提示，不改变协议。

- [x] **T082** [前端 Platform／实现]：补齐Platform认证界面日文文案
  - **文件**：`src/frontend/platform/public/locales/ja/bs.json`
  - **逻辑／上下文**：仅在Platform既有bs.json增量加入会话结束、服务暂不可用、升级和host重连文案；不得写Client目录，不新增竞争locale。
  - **覆盖 AC**：AC-10, AC-17, AC-25, AC-28
  - **依赖**：T080
  - **验证／完成条件**：Platform三语键检查；在/admin验证相应状态文案，不修改认证逻辑。

- [x] **T083** [前端 Client／实现]：补齐Client认证界面日文文案
  - **文件**：`src/frontend/client/src/locales/ja/translation.json`
  - **逻辑／上下文**：仅在已核实的Client现有translation.json增量加入前驱同一组认证文案，保持Recoil区独立，不写Platform文件或手改生成错误副本。
  - **覆盖 AC**：AC-10, AC-17, AC-25, AC-28
  - **依赖**：T081
  - **验证／完成条件**：Client三语键检查；在/workspace验证结束原因、重试或升级提示，不改变协议。

- [x] **T084** [手机端／测试]：手机响应解析及API测试
  - **文件**：`MOBILE_ROOT/test/mobile_protocol_test.dart`, `MOBILE_ROOT/test/platform_auth_lifecycle_test.dart`
  - **逻辑／上下文**：覆盖统一平台响应、可选metadata、auth_reason、native Bearer与Refresh，公开API保持单一AccessClient/HttpTransport；避免硬编码服务器或凭据。
  - **覆盖 AC**：AC-01, AC-08, AC-09, AC-10, AC-25
  - **依赖**：T009, T049
  - **验证／完成条件**：纯协议测试覆盖缺字段、空值、类型不符，不把协议解析与Widget混写。

- [x] **T085** [手机端／实现]：接入手机平台协议
  - **文件**：`MOBILE_ROOT/lib/src/bisheng_session.dart`, `MOBILE_ROOT/lib/src/access_client.dart`
  - **逻辑／上下文**：使用单次auth/login和统一refresh/logout，保存Session与到期metadata；拒绝本地TTL猜测覆盖服务端；不再走旧二次建会话。
  - **覆盖 AC**：AC-01, AC-08, AC-09, AC-10, AC-25
  - **依赖**：T084
  - **验证／完成条件**：相关flutter test和flutter analyze；原电脑业务API不重写。
  - **前置测试**：T084；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T086** [手机端／测试]：手机生命周期与存储竞争测试
  - **文件**：`MOBILE_ROOT/test/platform_auth_lifecycle_test.dart`, `MOBILE_ROOT/test/session_coordinator_test.dart`
  - **逻辑／上下文**：断言并发刷新合并、网络/503保留、明确401结束、退出/换账号后迟到响应丢弃、存储原子性及先恢复origin后刷新。
  - **覆盖 AC**：AC-09, AC-17, AC-18, AC-30
  - **依赖**：T085
  - **验证／完成条件**：使用注入客户端和安全存储，禁止真账号数据。

- [x] **T087** [手机端／实现]：接入手机统一协调与恢复
  - **文件**：`MOBILE_ROOT/lib/src/session_coordinator.dart`, `MOBILE_ROOT/lib/main.dart`
  - **逻辑／上下文**：维持同一Coordinator，加入origin绑定、epoch、原子持久化及可恢复错误；不凭旧本地Refresh时间直接删除仍可能有效的Session。
  - **覆盖 AC**：AC-09, AC-17, AC-18, AC-30
  - **依赖**：T086
  - **验证／完成条件**：测试与analyze通过；真机前后台及更换服务器另验。
  - **前置测试**：T086；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T088** [手机端／测试]：手机登录注册交互测试
  - **文件**：`MOBILE_ROOT/test/login_page_test.dart`, `MOBILE_ROOT/test/platform_auth_login_test.dart`
  - **逻辑／上下文**：覆盖一次登录、验证码、密码过期/停用/最低版本、注册后同一认证流程；不复刻服务端校验规则。
  - **覆盖 AC**：AC-01, AC-02, AC-10, AC-25
  - **依赖**：T087
  - **验证／完成条件**：Widget以手机视口和可见行为断言。

- [x] **T089** [手机端／实现]：更新手机登录与注册调用
  - **文件**：`MOBILE_ROOT/lib/src/login_page.dart`, `MOBILE_ROOT/lib/src/register_page.dart`
  - **逻辑／上下文**：保留现有原生表单，调用统一认证；接验证码与现有注册后登录，不再completePasswordLogin后另开mobile Session；明确最低版本错误。
  - **覆盖 AC**：AC-01, AC-02, AC-10, AC-25
  - **依赖**：T088
  - **验证／完成条件**：flutter测试与analyze；不新引状态管理/路由库。
  - **前置测试**：T088；本任务不修改确认的测试预期以掩盖实现错误。

- [x] **T090** [手机端／测试]：手机WebView票据与父会话测试
  - **文件**：`MOBILE_ROOT/test/web_session_test.dart`
  - **逻辑／上下文**：覆盖单次票据、同origin、epoch后选sid、父撤销、host续期及两个平台Cookie差异；禁止原生Refresh进入网页。
  - **覆盖 AC**：AC-01, AC-04, AC-15, AC-18, AC-26, AC-27
  - **依赖**：T087, T025
  - **验证／完成条件**：协议与Widget验证分别保持现有组织；无真实Token fixture。

- [x] **T091** [手机端／实现]：替换手机内嵌网页凭证交付
  - **文件**：`MOBILE_ROOT/lib/src/workspace_home.dart`, `MOBILE_ROOT/lib/src/access_client.dart`
  - **逻辑／上下文**：取得平台Web票据后在当前epoch下选择响应实际host子sid再加载固定consume入口；删除把长平台Token直接注入document.cookie的旧回退，host续期仍由手机持有Refresh。
  - **覆盖 AC**：AC-01, AC-04, AC-15, AC-18, AC-26, AC-27
  - **依赖**：T090, T089
  - **验证／完成条件**：flutter测试与analyze；Android/iOS真机在交付验证任务执行。
  - **前置测试**：T090；本任务不修改确认的测试预期以掩盖实现错误。


### Wave 7：验证和协调发布交付

- [ ] **T092** [后端 API／真实集成，用户执行]：API E2E与升级/回滚协议验证
  - **文件**：`features/v3.1.0-alpha1/003-platform-auth-session/e2e-checklist.md`, `features/v3.1.0-alpha1/003-platform-auth-session/handoff.md`
  - **逻辑／上下文**：按用户U-10，本轮交付基于spec AC的真实环境API验收步骤与配置，部署E2E由用户执行，不假称已执行。覆盖web/native、旧JWT重登、网关绑定、Session撤销、v2/OAuth边界、多副本及地板版本；复用已批准测试账号和环境。
  - **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-15, AC-16, AC-17, AC-19, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30
  - **依赖**：T082, T091, T057, T059, T061, T043, T041, T083, T052
  - **验证／完成条件**：实现获授权后按/e2e-test技能执行；记录实际环境及未完成项，禁止文档先填PASS。

- [ ] **T093** [验证与交付／验证，用户执行]：执行双DB与多副本并发验证
  - **文件**：`features/v3.1.0-alpha1/003-platform-auth-session/validation.md`
  - **逻辑／上下文**：仅在实现及测试环境操作获授权后执行现有单元/契约、MySQL/DM8新装升级与事务屏障、多副本验证；证据包含版本和回滚地板。没有DM8或网关环境时明确未验收，不用SQLite或mock替代。
  - **覆盖 AC**：AC-12, AC-26, AC-28, AC-29, AC-30
  - **依赖**：T092
  - **验证／完成条件**：证据可复核；运行失败先修复原任务，不以改预期放行。

- [ ] **T094** [验证与交付／验证，用户执行真实环境部分]：执行两SPA、真机及旧DSH验收
  - **文件**：`features/v3.1.0-alpha1/003-platform-auth-session/validation.md`
  - **逻辑／上下文**：实现后在同origin两SPA、多标签fallback、迟到Set-Cookie、iOS/Android、旧DSH安装包/模型/插件/桥接真实流程验证；记录包版本和主秘密未变的脱敏证据。QA参考用例可由QA自行使用，但本任务研发验收以spec AC和D1手动策略为准。
  - **覆盖 AC**：AC-01, AC-14, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25
  - **依赖**：T092
  - **验证／完成条件**：两个App各自规范检查通过不替代真机/安装包；缺环境就保留未验收状态。

- [x] **T095** [验证与交付／交付]：整理协调发布及回滚交付包
  - **文件**：`features/v3.1.0-alpha1/003-platform-auth-session/handoff.md`, `features/v3.1.0-alpha1/003-platform-auth-session/tasks.md`
  - **逻辑／上下文**：仅整理审批可检查的发布步骤、最低手机版本、两SPA和后端协调顺序、旧JWT拒绝开关、兼容DSH、地板镜像与保留新表的回滚；同步实际任务状态。此任务不授权部署、推送、合并或数据删除。
  - **覆盖 AC**：AC-19, AC-20, AC-23, AC-25, AC-29, AC-30
  - **依赖**：T093, T094
  - **验证／完成条件**：执行/sdd-code-review并核对全部AC交付，明确真实已验与限制；发布动作另获授权。

## 阶段收尾条件

| 阶段 | 进入下一阶段前必须成立 |
| --- | --- |
| 核心 | 新平台规则已验证，旧DSH等价及错误映射保持；不得仅以改名宣称统一 |
| 网页 | 两SPA和后端同时具备新协议；网关绑定、SSO身份、runtime reference完整；旧JWT拒绝与手机发布协调 |
| 手机 | 新版协议、最低版本和两平台真机证据齐全；不能把用户无法看到升级提示当兼容完成 |
| 发布准备 | 真实双DB/多副本/网关/旧桌面证据、地板镜像及回滚文档可检查；未获授权不执行发布 |

## AC追溯索引（只列测试任务）

| AC | 测试任务 |
| --- | --- |
| AC-01 | T020, T024, T028, T046, T054, T060, T064, T068, T074, T084, T088, T090, T092 |
| AC-02 | T018, T028, T046, T054, T056, T068, T088, T092 |
| AC-03 | T022, T028, T046, T056, T092 |
| AC-04 | T018, T024, T026, T028, T030, T032, T040, T046, T060, T090, T092 |
| AC-05 | T014, T020, T092 |
| AC-06 | T016, T020, T044, T092 |
| AC-07 | T016, T020, T036, T044, T064, T092 |
| AC-08 | T012, T016, T020, T028, T036, T046, T064, T084, T092 |
| AC-09 | T020, T026, T034, T042, T044, T046, T050, T064, T066, T072, T084, T086, T092 |
| AC-10 | T012, T018, T020, T030, T036, T046, T084, T088, T092 |
| AC-11 | T012, T016, T038, T092 |
| AC-12 | T012, T016, T022, T036, T038, T092 |
| AC-13 | T016, T020, T092 |
| AC-14 | T044, T062, T064, T066, T070, T072, T076 |
| AC-15 | T016, T020, T024, T028, T046, T054, T068, T074, T090, T092 |
| AC-16 | T040, T042, T092 |
| AC-17 | T030, T046, T064, T066, T072, T076, T086, T092 |
| AC-18 | T044, T062, T064, T070, T074, T076, T086, T090 |
| AC-19 | T014, T022, T030, T032, T034, T054, T064, T066, T068, T076, T092 |
| AC-20 | T032, T038, T054, T058 |
| AC-21 | T032, T034, T038, T044, T054, T064, T066, T070, T072, T076, T092 |
| AC-22 | T058, T092 |
| AC-23 | T022, T044, T046, T056, T064, T068, T070, T076, T092 |
| AC-24 | T038, T058, T070, T092 |
| AC-25 | T060, T084, T088, T092 |
| AC-26 | T024, T030, T032, T036, T040, T042, T050, T060, T090, T092 |
| AC-27 | T014, T024, T026, T030, T034, T040, T046, T050, T058, T066, T072, T090, T092 |
| AC-28 | T024, T026, T030, T034, T042, T046, T092 |
| AC-29 | T050, T092 |
| AC-30 | T014, T016, T050, T086, T092 |

## 实际偏差记录

- 当前无实现偏差；仅更新确认状态并整理文档，所有任务未开始。
- 本轮任务审查拆开了后端错误码与locale、后端路由与前端分类、Platform与Client文案，并独立列出worker初始化；只是细化执行边界，不改变D1协议或需求。
- 后续如推翻S1或D1，先重新确认；小实现细节回写design并在这里保留一行指针，不擅改期限、兼容或权限边界。

## 实施组织记录

2026-11-27：按后端认证、两SPA认证、手机认证三个完整业务链推进；原计划的细碎模块合并为现有服务、具体窄仓储和共享纯规则，不新增无消费者的Port副本。表中目标文件已对齐实际实现；跨模块延后凭证引用的必要consumer同步纳入同一Owner。单元结果与L1/L2审查回填后才勾选，真实集成由用户执行。

最终开发执行结果见[validation.md](./validation.md)，L1合规与任务元数据见[task-reviews.md](./task-reviews.md)，L2特性检查见[code-review.md](./code-review.md)。QA参考表仍由用户/QA执行并记录，不从本地单元结果回填。
