# Tasks: F062 DSH Desktop 接入

**关联**：[Spec](./spec.md) · [Design](./design.md) · [客户端契约](./client-api.md) · [版本契约](../release-contract.md)<br>
**版本**：v3.0.0-beta2 · 客户端 0.3.0<br>
**日期**：2026-09-09

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 已修复验收歧义；用户本轮“继续”承接修订后的 Spec/Design |
| design.md | ✅ 已评审 | R1–R5 修复后设计级 LGTM；用户确认继续下一阶段 |
| tasks.md | ✅ 已拆解 | 21 项任务评审 LGTM，见 tasks-review.md |
| 实现 | 本轮实现遗漏已修复，外部验收待完成 | 两仓 HTTP、策略/配额/恢复、固定席位与 Platform 已落地；外部环境验收独立保留，见下表与各验收报告 |

### 本轮复核与未关闭门禁

勾选表示本地实现及本轮约定检查完成，不表示已部署。用户确认 DM8 实机暂缓，T007/T010/T028/T029 的完成条件调整为真实 MySQL 验证＋SQL 可移植性检查，现已完成；不将 DM skip 记为通过。T110 部署 E2E 按用户授权暂跳过。T111 的目标旧二进制及发行密文仍缺外部证据。T112 本地数据库与万级检索检查已完成（DM 实机暂缓），但原依赖 T111 与完整发布门禁保留；T113 部署主切换/负载指标待现场。T114 的本地实现遗漏已修复，保留未勾选汇总发布验收。最新逐模型额度、强类型配置、无限流及客户端修订见 [修订验收](./model-quota-revision.md)。

| 范围 | 本地实现与复核证据 |
|---|---|
| T001–T023、T026–T039、T066–T067、T080–T085 | [gateway-progress.md](./gateway-progress.md)、[license-compatibility-report.md](./license-compatibility-report.md)；额外长 Unicode 资料、激活 CLI、确定失败及幂等恢复修复记录在最终审查 |
| T024–T025、T040–T043、T086–T089、T094–T099 | [root-integration-progress.md](./root-integration-progress.md)；实际路由与凭据中间件、HTTP/SSE/运行时测试 |
| T044–T047、T054–T061、T068–T073、T090–T093 | [python-policy-progress.md](./python-policy-progress.md)；SQL/用户事务钩子、管理员范围、模型与实际计量 |
| T048–T053、T062–T065、T074–T079 | [python-quota-progress.md](./python-quota-progress.md)、[quota-operations.md](./quota-operations.md)、[recovery-acceptance.md](./recovery-acceptance.md) |
| T100–T109 | [frontend-progress.md](./frontend-progress.md)、[platform-ui-check.md](./platform-ui-check.md)、[desktop-handoff-checklist.md](./desktop-handoff-checklist.md) |
| T110–T114 | [e2e-report.md](./e2e-report.md)、数据库/License/恢复验收与最终代码审查报告；各报告保留现场缺口 |

测试路径按实际职责归并：部门变更不触发 DSH 同步的回归位于 `test_user_profile_changes.py`；Worker 注册用例位于 `test_operations_runtime.py`；三模型 HTTP 用例为 `test_models_api.py`；T094 由 `test_access.py`、`test_identity_api.py`、`test_models_api.py`、`test_middleware.py` 与实际全局 router 导入核对共同覆盖。不会为保持任务草案路径而复制测试。

## 执行约定

- **B**：`/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre`，分支 `feat/3.0.0-beta2-pre`，基线 tag `v3.0.0-beta1-fix`。**G**：`/Users/zhangguoqing/works/bisheng-gateway`，分支 `feat/dsh-access`，基线 main `75a74ff28ea95cba0938ff4912317cade2353337`。任务中的 B/G 表示文件所属仓库，以下均给绝对可点击路径；拟新增文件尚不存在是正常情况。
- 用户已明确授权多agent并行开发。Wave仍表示依赖关系，按冻结契约分工并行实现；跨模块完成以接线和联合测试为准。每项目标约30分钟，最多2个直接编辑文件；若实施发现更大范围，先将该项进一步拆开并重评依赖，再执行，不能把整模块塞进一次任务。工具生成产物按现有生成器操作，并在记录中列出实际影响。
- 后端均测试先行：测试任务只写测试和最小fixture，记录预期失败；实现配对后转绿。Python命令在B/src/backend用 `uv run pytest test/dsh/<对应测试文件>`；Gateway在G用 `mvn -Dtest=<对应测试类> test`（Java17）。真实Redis/SQL测试必须使用独立环境；DM8实机按用户本轮确认暂缓，单独记录未执行，不谎报skip为通过。
- 全局规则以 Constitution C1–C8 及各目录 AGENTS.md 为准，模板旧DAO/Client Zustand示例不适用。新Python业务用Repository，Gateway用既有MyBatis；共享文件只做本项明确增量。新增独立Python表先按现有模型发现/create_all规则处理，涉及旧表DDL再走正式revision；数据回填单独运维，不混DDL。回退保留已经产生的席位/审计/账本。
- DSH默认关闭；客户端只配置Nginx origin，Gateway转发/api/v1和/api/v2。7接口路径和状态码保留；用户确认的逐模型额度修订新增 usage 的可选 model 参数，语义及调用时机同步客户端文档；内部DTO及平台管理补充按Design同步两仓。Secret、客户License与真实身份不写fixture，不主动向客户端团队发送消息。
- 前端只修改Platform；实际编码前重读当前UI规范和已落地组件，命名/i18n/请求封装遵循现行规则；禁止新引入被冻结的react-query v3或新状态库。普通Client /workspace不承担DSH桌面实现。DSH客户端、供应商签名样本/目标旧二进制及可计量模型样本为外部验收依赖，缺失不阻塞独立服务测试，但不允许宣称联调完成。
- 所有Worker从受信Celery headers恢复tenant_id到ContextVar，校验payload/事件归属并finally reset；定时dispatcher逐租户派发，不能依赖tenant1默认值。操作/证据存SQL、Redis或MinIO，不以本机磁盘作为共享真相。
- 不作“测试降级”，不以文档或mock替代真实兼容/容量验证。任务完成后按task-review核对并勾选，实际偏差只记指针到Design。无新增Spec/Design暂停点；若推翻已确认边界再按SDD重新确认。

## Wave 概览

| Wave | 交付边界 |
|---|---|
| 1 | 两仓契约、独立fixture、8表模型与双库DDL、配置/错误码 |
| 2 | 旧License兼容、独立DSH授权和内部服务认证 |
| 3 | 身份/PKCE、固定席位、会话与刷新、撤销及验席 |
| 4 | Python凭据隔离、模型强读、实际用量准入/结算/恢复、策略审计 |
| 5 | 对账CLI、分页/资料投影、Worker与恢复注册 |
| 6 | 26个HTTP端点、两仓路由过滤/认证及遥测 |
| 7 | Platform登录和管理、外部DSH客户端交付边界 |
| 8 | e2e、旧二进制、双库、恢复/性能和交付审查 |

## 实施任务

### Wave 1

- [x] **T001 · 固定两仓公共样例**
  - 分类：基础设施；类型：契约。
  - 文件：[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/contracts/identity-and-errors.json](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/contracts/identity-and-errors.json)、[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/contracts/client-0.3.0.json](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/contracts/client-0.3.0.json)。
  - 逻辑/测试上下文：提取冻结的 7 个客户端成功/失败体、PKCE 绑定及内部 DshIdentitySnapshot。字符串 ID、缺名回退、refresh 同字段、unknown usage=NULL、真实 HTTP、logout 204 都要有样例；只用虚构身份和一次性测试密钥引用。Gateway 测试加载此版本化 fixture 的显式路径，不另维护漂移副本。
  - 依赖：无。
  - 验证/完成条件：所有 JSON 可解析；与 client-api.md 的字段/状态及 Design §6.1 逐项核对，记录 fixture 摘要。

- [x] **T002 · 固定厂商签名与旧字段绑定格式**
  - 分类：基础设施；类型：契约。
  - 文件：[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/contracts/license-entitlement-v1.json](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/contracts/license-entitlement-v1.json)、[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/license-issuer-contract.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/license-issuer-contract.md)。
  - 逻辑/测试上下文：在保留旧密文外层和 version/expireDay 语义前提下，确定 schema、固定签名算法白名单、issuer/audience/kid、公钥交付、实例与字段存在性/原值绑定、时间单位、大小及分段限制；提供旧 trial/pro 与有效/无效扩展的测试向量结构。只有临时生成测试签名材料；真实厂商样本缺失登记为目标兼容门禁，不能冒充厂商签发或宣称旧二进制通过。
  - 依赖：T001。
  - 验证/完成条件：两仓实现与发行工具使用一个明确编码契约；客户端 0.3.0 不变。

- [x] **T003 · Python 测试隔离**
  - 分类：基础设施；类型：基础设施。
  - 文件：[B:src/backend/test/dsh/conftest.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/conftest.py)、[B:src/backend/test/dsh/fixtures.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/fixtures.py)。
  - 逻辑/测试上下文：建立 T1/T2、Root 共享、自有/非共享模型、用户停用、管理员、固定时钟 fixture；mock Gateway/供应商用作协议单测，真实 SQL/Redis fixture 使用显式独立测试配置，不读生产 config.yaml。
  - 依赖：T001。
  - 验证/完成条件：uv run pytest test/dsh/ --collect-only；空 fixture 可加载，不在测试根目录新建文件。

- [x] **T004 · Gateway 测试隔离**
  - 分类：基础设施；类型：基础设施。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshFixtures.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshFixtures.java)、[G:src/test/resources/application-dsh-test.yml](/Users/zhangguoqing/works/bisheng-gateway/src/test/resources/application-dsh-test.yml)。
  - 逻辑/测试上下文：建立独立 test profile、随机测试签名材料、双库可切数据源和可控时钟；商业 License 旧测试保留。禁止复制源码中的旧私钥或配置密码；接口 fixture 路径通过测试配置显式传入。
  - 依赖：T001, T002。
  - 验证/完成条件：Java 17/Maven 测试编译；外部环境凭据未配置时明确缺口，不连默认生产数据源。

- [x] **T115 · 基础契约、模型与配置验证**
  - 分类：基础设施；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_foundation.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_foundation.py)。
  - 逻辑/测试上下文：验证冻结接口/PKCE、临时测试公钥签名、身份主体绑定、未知usage不置零、默认关闭/Secret脱敏、SQLite唯一约束与非负量、MySQL DDL编译、用户版本增量迁移保留及错误码映射。测试不实现网关鉴权或真实额度结算。
  - 依赖：T001, T002, T003。
  - 覆盖 AC: AC-01, AC-02, AC-03, AC-13, AC-22, AC-23, AC-29, AC-30, AC-31, AC-32, AC-34。
  - 验证/完成条件：已记录2通过/4预期失败→10通过；命令 `python -m pytest --confcutdir=test/dsh test/dsh/test_foundation.py -q`，不加载旧根conftest的config.yaml；不替代真实双库/客户端验收。

- [x] **T005 · 策略与操作 ORM**
  - 分类：基础设施；类型：基础设施。
  - 文件：[B:src/backend/bisheng/dsh/domain/models/user_policy.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/models/user_policy.py)、[B:src/backend/bisheng/dsh/domain/models/admin_operation.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/models/admin_operation.py)。
  - 逻辑/测试上下文：定义用户唯一策略、占位 version=0/首次生效1、pending_operation_id；操作含五类 action、不可变 payload/前后快照、expected 两类版本、四类时间、lease_generation。使用 JsonType、租户发现与统一时间类型；回退关闭 DSH 保留表，不删除已入账审计。
  - 依赖：T003。
  - 验证/完成条件：模型元数据含唯一键/索引；新表遵循 create_all 发现，不无故新增 Alembic 建表修订。

- [x] **T006 · 用量汇总与调用 ORM**
  - 分类：基础设施；类型：基础设施。
  - 文件：[B:src/backend/bisheng/dsh/domain/models/monthly_usage.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/models/monthly_usage.py)、[B:src/backend/bisheng/dsh/domain/models/model_call.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/models/model_call.py)。
  - 逻辑/测试上下文：月汇总唯一 tenant/user/month/model，明细含原月/模型、usage NULL、provider_request_id、event_version/quota_epoch、结果与计量来源；0 仅可靠零，历史模型删除不级联删账。回退关闭 DSH 保留数据，禁止自动删表。
  - 依赖：T003。
  - 验证/完成条件：双库支持的字段/索引元数据可导入；无跨库外键、无 SQL 原生 JSON 依赖。

- [x] **T007 · 用户资料单调版本字段**
  - 分类：基础设施；类型：基础设施。
  - 文件：[B:src/backend/bisheng/user/domain/models/user.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/user/domain/models/user.py)、[B:src/backend/bisheng/core/database/alembic/versions/v3_0_0_f062_profile_version.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/core/database/alembic/versions/v3_0_0_f062_profile_version.py)。
  - 逻辑/测试上下文：在原用户领域模型增加非空BIGINT dsh_profile_version（内部DTO映射为profile_version），server_default=0；新revision仅DDL，实施前读取迁移AGENTS并接当前真实head，不做数据回填。变更成功事务递增，Gateway首次兑换可使用0；资料回填走后续巡检。回退先停DSH同步并保留字段/版本，不能删列造成旧命令覆盖。
  - 依赖：T003。
  - 验证/完成条件：模型发现与真实MySQL增量/重入/保留字段验证、DM类型路径审查（实机本轮暂缓）；旧业务不依赖新增列含义；回退无数据损失。

- [x] **T008 · Gateway 席位与会话实体**
  - 分类：基础设施；类型：基础设施。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/entity/DshSeat.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/entity/DshSeat.java)、[G:src/main/java/com/dataelem/gateway/dsh/entity/DshSession.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/entity/DshSession.java)。
  - 逻辑/测试上下文：按 Design §4.5.1 建四表中的前两张映射：instance/user 唯一固定席位、grant_version、身份检索投影；session 绑定 auth_id 唯一和刷新 family/绝对到期。回退保留数据，不把会话清理当席位回收。
  - 依赖：T004。
  - 验证/完成条件：实体字段与 SQL 脚本逐项比对；不新增 License 副本表。

- [x] **T009 · Gateway 刷新历史与操作实体**
  - 分类：基础设施；类型：基础设施。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/entity/DshRefreshToken.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/entity/DshRefreshToken.java)、[G:src/main/java/com/dataelem/gateway/dsh/entity/DshOperation.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/entity/DshOperation.java)。
  - 逻辑/测试上下文：保留 refresh 摘要 ACTIVE/USED/REVOKED 安全历史；操作保存 expected_grant_version、payload_hash 和终态结果。回退仍保留摘要及审计；从不持久化明文 refresh。
  - 依赖：T004。
  - 验证/完成条件：字段和唯一键可编译；USED 历史不能随轮换删除。

- [x] **T010 · Gateway 双库增量建表**
  - 分类：基础设施；类型：基础设施。
  - 文件：[G:docker/db/update_dsh_mysql.sql](/Users/zhangguoqing/works/bisheng-gateway/docker/db/update_dsh_mysql.sql)、[G:docker/db/update_dsh_dm.sql](/Users/zhangguoqing/works/bisheng-gateway/docker/db/update_dsh_dm.sql)。
  - 逻辑/测试上下文：仅创建上述四张新表与必要索引，明确 MySQL/DM8 方言；已存在但结构不符要报错，不能静默跳过。升级前备份/停 DSH，回退先关闭功能并保留表，不在常规 downgrade 删除用户授权历史。
  - 依赖：T008, T009。
  - 验证/完成条件：MySQL隔离库与既有旧商业表保护验证，DM DDL/Mapper配对检查（实机本轮暂缓）；不修改旧 trial/pro 或其他业务表。

- [x] **T011 · Python DSH 可选配置与 DTO**
  - 分类：基础设施；类型：基础设施。
  - 文件：[B:src/backend/bisheng/dsh/domain/schemas/contracts.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/schemas/contracts.py)、[B:src/backend/bisheng/dsh/config.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/config.py)。
  - 逻辑/测试上下文：配置默认关闭，固定 Nginx origin、内部 Gateway 地址、独立 HMAC/JWKS/配额 Redis 参数；DTO 固定身份/用量/策略/操作枚举。不开 DSH 不初始化远程依赖；Secret 由受管配置注入。
  - 依赖：T001, T005, T006。
  - 验证/完成条件：导入不发网络请求；样例不含 Secret 值。

- [x] **T012 · Gateway DSH 可选配置与 DTO**
  - 分类：基础设施；类型：基础设施。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/config/DshProperties.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/config/DshProperties.java)、[G:src/main/java/com/dataelem/gateway/dsh/dto/DshContracts.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/dto/DshContracts.java)。
  - 逻辑/测试上下文：DSH 默认关闭，配置公开 origin 与内部 Python 地址、实例、独立签名和 HMAC 引用；用嵌套 DTO 固定身份/会话/管理返回，类型来源于 contract fixture。配置类不改变原 BishengConfig.license。
  - 依赖：T001, T008, T009。
  - 验证/完成条件：可编译；无第二客户端公开地址；未知 DTO 输入明确拒绝。

- [x] **T013 · 分配 Python 错误码**
  - 分类：基础设施；类型：基础设施。
  - 文件：[B:src/backend/bisheng/common/errcode/dsh.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/common/errcode/dsh.py)、[B:features/v3.0.0-beta2/release-contract.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/release-contract.md)。
  - 逻辑/测试上下文：现场扫描已用 MMMEE 后分配独立模块，禁止复用 F053 260；登记 PKCE、席位、身份、配额未知、版本冲突/operation_in_progress 错误，客户端字符串码与 HTTP 映射不改。
  - 依赖：T011。
  - 验证/完成条件：无编号冲突；所有冻结错误可映射；只在当前版本契约登记分配结果。

- [x] **T116 · C5 模块注册同步**
  - 分类：基础设施；类型：契约。
  - 文件：[B:docs/constitution.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/docs/constitution.md)。
  - 逻辑/测试上下文：按C5同步261模块注册，不改架构铁律；运行时错误源和当前release-contract一致，260继续保留给F053。
  - 依赖：T013。
  - 验证/完成条件：源代码模块扫描无261冲突，三语言新增30个键对应26101–26130。

- [x] **T014 · 错误文案 zh/en**
  - 分类：基础设施；类型：基础设施。
  - 文件：[B:src/frontend/packages/locales/src/api_errors/zh-Hans.json](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/packages/locales/src/api_errors/zh-Hans.json)、[B:src/frontend/packages/locales/src/api_errors/en.json](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/packages/locales/src/api_errors/en.json)。
  - 逻辑/测试上下文：为新增 MMMEE 提供中文与英文权威文案；源路径已按 packages/locales/README.md 核对，绝不编辑 generated artifacts。
  - 依赖：T013。
  - 验证/完成条件：与下一任务一起完成三语言 parity 后才验收，不更新冻结 baseline 掩盖缺键。

- [x] **T015 · 错误文案 ja**
  - 分类：基础设施；类型：基础设施。
  - 文件：[B:src/frontend/packages/locales/src/api_errors/ja.json](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/packages/locales/src/api_errors/ja.json)。
  - 逻辑/测试上下文：补齐同一批 MMMEE 日文；按既有生成命令派生平台/Client 错误文案，不手改产物。
  - 依赖：T014。
  - 验证/完成条件：pnpm check-i18n；新增三语言完全齐全，生成产物只由既有工具生成。

本轮验证说明：复用主checkout的Python3.11运行时，新DSH测试用 `--confcutdir=test/dsh` 隔离旧根测试配置；没有修改或复制生产配置。T004使用本机应用内Java17独立编译/读取fixture通过，但不等于项目Maven编译。T007挂当前真实单head，SQLite升级/重入/保留字段检查通过；没有真实MySQL/DM8升级结果，暂不勾选。增量迁移已改用共享column_exists，大写列名回归通过。前端pnpm lint/typecheck已尝试，但worktree缺node_modules（eslint/tsc-strict不可用），全量门禁仍未完成；i18n专项通过。

### Wave 2

- [x] **T016 · DSH entitlement 独立解析：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshEntitlementTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshEntitlementTest.java)。
  - 逻辑/测试上下文：表驱动覆盖旧有效/过期 × DSH有效/失效四组合，外层无法解析、篡改、kid/算法/实例错误及到期时刻；使用临时测试签名及契约样例。
  - 依赖：T002, T012。
  - 覆盖 AC: AC-05, AC-07, AC-13, AC-14, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T017 · DSH entitlement 独立解析**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/service/DshEntitlementService.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/service/DshEntitlementService.java)、[G:src/main/java/com/dataelem/gateway/dsh/dto/DshEntitlement.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/dto/DshEntitlement.java)。
  - 逻辑/测试上下文：解析可选厂商签名扩展并绑定旧字段、实例、时间、用途；无扩展/错误签名仅关闭 DSH；legacy pro 不授予无限席位，免费10也须签名。返回独立不可变状态，不写旧 holder。
  - 依赖：T002, T012, T016。
  - 验证/完成条件：T016 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T018 · 兼容旧 Loader 接入：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshLicenseLoaderCompatibilityTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshLicenseLoaderCompatibilityTest.java)。
  - 逻辑/测试上下文：通过旧 Loader 的旧输入基线验证向后兼容；断言无扩展旧商业行为不变、坏扩展不污染旧 holder；测试捕获错误无凭据泄漏。
  - 依赖：T017。
  - 覆盖 AC: AC-07, AC-13, AC-14, AC-25, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T019 · 兼容旧 Loader 接入**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/config/LicenseLoader.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/config/LicenseLoader.java)、[G:src/main/java/com/dataelem/gateway/dsh/service/DshLicenseState.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/service/DshLicenseState.java)。
  - 逻辑/测试上下文：保留旧解密、trial 到期日当天失效、非trial既有pro分支、异常降级与原状态接口。解析成功后独立发布 DSH 状态；扩展异常不能落入旧 markExpired。每次发证/验席按当前时间验DSH到期。
  - 依赖：T017, T018。
  - 验证/完成条件：T018 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T020 · License 多副本受控换版：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshLicenseActivationTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshLicenseActivationTest.java)。
  - 逻辑/测试上下文：模拟两副本不同版本、换版失败、降配超员和仍有效在途；状态来源必须共享/受控，单机内存就绪不能证明全部副本一致。
  - 依赖：T019。
  - 覆盖 AC: AC-07, AC-12, AC-14, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T021 · License 多副本受控换版**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/service/DshActivationService.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/service/DshActivationService.java)、[G:src/main/java/com/dataelem/gateway/config/ReloadTask.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/config/ReloadTask.java)。
  - 逻辑/测试上下文：接入暂停所有副本 DSH 新准入/席位变更、等待事务、换受管授权源、核对同摘要/版本后恢复的运维状态；失败关闭，普通业务保留。不得把旧按小时 reload 当到期判定。
  - 依赖：T019, T020。
  - 验证/完成条件：T020 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T022 · Gateway 双向服务认证：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshServiceAuthTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshServiceAuthTest.java)。
  - 逻辑/测试上下文：模拟时钟、独立Redis nonce与Python响应：重放、body改动、实例不符拒绝；连接失败不伪造 active；固定 DTO 用户/租户显示及回退映射。
  - 依赖：T012, T004。
  - 覆盖 AC: AC-02, AC-03, AC-04, AC-13, AC-14, AC-31。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T023 · Gateway 双向服务认证**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/service/DshServiceAuth.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/service/DshServiceAuth.java)、[G:src/main/java/com/dataelem/gateway/dsh/client/DshIdentityClient.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/client/DshIdentityClient.java)。
  - 逻辑/测试上下文：HMAC-SHA256覆盖 method/path/body_hash/instance/key_id/timestamp/nonce，±60s窗口/120s共享nonce；双向密钥隔离。IdentityClient redeem/check 返回 DshIdentitySnapshot，经 key_id 绑定实例；TLS固定地址，超时failclosed。
  - 依赖：T012, T004, T022。
  - 验证/完成条件：T022 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

### Wave 3

- [x] **T024 · Python 身份票据和显示快照：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_identity.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_identity.py)。
  - 逻辑/测试上下文：fake时钟+Redis检验过期/已用/错误绑定、跨租户/停用/服务账号；测试首次兑换与刷新快照改名/空名，失败不返回成功身份。
  - 依赖：T011, T003, T023, T007。
  - 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-13, AC-30, AC-31。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T025 · Python 身份票据和显示快照**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/domain/services/identity.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/services/identity.py)、[B:src/backend/bisheng/dsh/domain/repositories/tickets.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/repositories/tickets.py)。
  - 逻辑/测试上下文：authorize/redeem/check 调原用户/租户业务，真实JWT+Origin/CSRF；票据随机值摘要TTL60s，绑定auth/client/redirect/challenge，原子消费。Snapshot使用当前资料，display_name→username，空租户名→Tenant id，空账号拒绝。
  - 依赖：T011, T003, T023, T007, T024。
  - 验证/完成条件：T024 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T026 · Gateway 公共登录事务：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshAuthorizationTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshAuthorizationTest.java)。
  - 逻辑/测试上下文：授权事务TTL、随机state/PKCE绑定、非法回调与plain拒绝；无浏览器授权不可直接占席；只配置单Nginx公开origin。
  - 依赖：T023, T012。
  - 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-13。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T027 · Gateway 公共登录事务**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/service/DshAuthorizationService.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/service/DshAuthorizationService.java)、[G:src/main/java/com/dataelem/gateway/dsh/repository/DshAuthorizationRepository.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/repository/DshAuthorizationRepository.java)。
  - 逻辑/测试上下文：创建5分钟事务，固定client_id、PKCE S256，动态IPv4 loopback /dsh/callback，无任意URL/query/fragment；state原样绑定。resolve只走服务鉴权，输出规范化绑定字段。
  - 依赖：T023, T012, T026。
  - 验证/完成条件：T026 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T028 · Gateway 席位数据库事务：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshSeatRepositoryTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshSeatRepositoryTest.java)。
  - 逻辑/测试上下文：真实MySQL/DM8两库：空实例11人抢10席、同人并发多设备、deadlock重试、授权容量临界；不能用mock或唯一用户键代替容量证明。
  - 依赖：T010, T008, T004。
  - 覆盖 AC: AC-05, AC-06, AC-07, AC-08, AC-10, AC-12, AC-30。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T029 · Gateway 席位数据库事务**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/repository/DshSeatRepository.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/repository/DshSeatRepository.java)、[G:src/main/java/com/dataelem/gateway/dsh/repository/DshSeatMapper.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/repository/DshSeatMapper.java)。
  - 逻辑/测试上下文：MyBatis mapper使用注解或既有XML策略中的一种，MySQL定义实例范围 SERIALIZABLE COUNT+写入同事务；DM采用READ_COMMITTED且事务首条SQL为席位表EXCLUSIVE锁，有限重试，覆盖空范围；复用相同user席位，REVOKED不能自动分配。Gateway mapper显式限定实例/租户，不复制Python ContextVar机制。
  - 依赖：T010, T008, T004, T028。
  - 验证/完成条件：T028 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T030 · 固定席位资格业务：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshSeatServiceTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshSeatServiceTest.java)。
  - 逻辑/测试上下文：注入identity、entitlement、repository；验证从未分配/已分配/已撤销、无容量、用户失效、换证失败保席与不重复占席。
  - 依赖：T029, T025, T027, T021。
  - 覆盖 AC: AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-10, AC-12, AC-13, AC-14。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T031 · 固定席位资格业务**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/service/DshSeatService.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/service/DshSeatService.java)。
  - 逻辑/测试上下文：先完成一次性身份兑换再调用受实例范围保护的席位事务；License/用户状态错误不分席；发行后续失败已提交席位保留，重登录复用；不做TTL回收。
  - 依赖：T029, T025, T027, T021, T030。
  - 验证/完成条件：T030 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T032 · 会话与刷新原子存储：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshSessionRepositoryTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshSessionRepositoryTest.java)。
  - 逻辑/测试上下文：真实SQL验证并发刷新仅一代成功、重复auth_id、提交后响应丢失、USED可追溯、绝对到期不延长；独立测试数据源。
  - 依赖：T009, T029。
  - 覆盖 AC: AC-06, AC-08, AC-13, AC-14, AC-15, AC-17。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T033 · 会话与刷新原子存储**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/repository/DshSessionRepository.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/repository/DshSessionRepository.java)、[G:src/main/java/com/dataelem/gateway/dsh/repository/DshSessionMapper.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/repository/DshSessionMapper.java)。
  - 逻辑/测试上下文：session+refresh摘要同事务插入，auth_id唯一，轮换锁Session、旧代USED与新代ACTIVE同提交；保留所有USED至绝对到期/审计保留期，重放整family撤销。
  - 依赖：T009, T029, T032。
  - 验证/完成条件：T032 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T034 · Token 签发与刷新：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshTokenServiceTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshTokenServiceTest.java)。
  - 逻辑/测试上下文：校验JWT claims/期限、Snapshot显示、refresh轮换/丢回包重登录、错误aud/kid、无席位、撤销和身份服务超时；公共成功体与冻结fixture逐字段一致。
  - 依赖：T033, T031。
  - 覆盖 AC: AC-06, AC-08, AC-13, AC-14, AC-15, AC-16, AC-17。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T035 · Token 签发与刷新**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/service/DshTokenService.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/service/DshTokenService.java)、[G:src/main/java/com/dataelem/gateway/dsh/service/DshJwtService.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/service/DshJwtService.java)。
  - 逻辑/测试上下文：签发固定iss/aud/sub/instance/tenant/seat/session/grant_version，默认access5分钟/session30天；首次和刷新映射当前IdentitySnapshot，校验License/席位/会话版本，刷新重放撤family。服务Secret不下发。
  - 依赖：T033, T031, T034。
  - 验证/完成条件：T034 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T036 · 撤销与重新分配幂等：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshSeatOperationTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshSeatOperationTest.java)。
  - 逻辑/测试上下文：并发撤销/重分配、重复/乱序操作、同ID不同负载、取消后新请求拒绝；检查每次实际操作者审计和操作原结果。
  - 依赖：T035。
  - 覆盖 AC: AC-09, AC-10, AC-11, AC-12, AC-14, AC-17, AC-28, AC-29。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T037 · 撤销与重新分配幂等**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/service/DshSeatOperationService.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/service/DshSeatOperationService.java)、[G:src/main/java/com/dataelem/gateway/dsh/repository/DshOperationRepository.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/repository/DshOperationRepository.java)。
  - 逻辑/测试上下文：REVOKE/REASSIGN按operation_id/payload_hash/expected_grant_version，在实例事务中记录操作+席位+会话；撤销释放但保留REVOKED，重分配递增grant且不复活旧family，容量满原状态保持。
  - 依赖：T035, T036。
  - 验证/完成条件：T036 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T038 · 验席与退出：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshIntrospectionTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshIntrospectionTest.java)。
  - 逻辑/测试上下文：验证grant变更立即影响新准入、普通JWT/PAT/SAK拒绝、License过期、依赖失败、退出后保席；退出成功204且无响应体。
  - 依赖：T037。
  - 覆盖 AC: AC-08, AC-13, AC-14, AC-15, AC-16, AC-17, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T039 · 验席与退出**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/service/DshIntrospectionService.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/service/DshIntrospectionService.java)。
  - 逻辑/测试上下文：introspect每次读取当前DSH授权/席位/session/version，不缓存正向结果；logout验证一种access或refresh后仅撤销当前会话，DSH关闭/过期仍可撤销，JWKS仍可读。
  - 依赖：T037, T038。
  - 验证/完成条件：T038 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

### Wave 4

- [x] **T040 · Python Gateway 受信客户端：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_gateway_client.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_gateway_client.py)。
  - 逻辑/测试上下文：MockTransport覆盖签名canonical内容、重放/时钟、TLS地址、超时、200旧错误体不能作active；管理未知结果不得当0席或成功。
  - 依赖：T025, T039, T013。
  - 覆盖 AC: AC-02, AC-03, AC-15, AC-16, AC-17, AC-25, AC-28, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T041 · Python Gateway 受信客户端**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/infrastructure/gateway_client.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/infrastructure/gateway_client.py)、[B:src/backend/bisheng/dsh/infrastructure/service_auth.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/infrastructure/service_auth.py)。
  - 逻辑/测试上下文：HTTP客户端固定内部地址，2秒验席超时、双向独立HMAC、nonce共享；按契约调用resolve/introspect/management/operations，重试只针对幂等操作且使用新nonce，错误明确unavailable。
  - 依赖：T025, T039, T013, T040。
  - 验证/完成条件：T040 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T042 · DSH 独立认证与上下文：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_access.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_access.py)。
  - 逻辑/测试上下文：普通JWT/PAT/SAK与委托头均拒绝；两租户并行、验席失败、SSE延后迭代、取消上下文恢复；既有凭证行为未改变。
  - 依赖：T041, T011。
  - 覆盖 AC: AC-04, AC-13, AC-14, AC-15, AC-16, AC-17, AC-30, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T043 · DSH 独立认证与上下文**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/domain/services/access.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/services/access.py)。
  - 逻辑/测试上下文：DshAccessService.authenticate固定算法/issuer/aud/JWKS来源，建立DshPrincipal，强校验当前用户/租户并在线验席；每次显式清理租户上下文，流式生命周期覆盖生成器。
  - 依赖：T041, T011, T042。
  - 验证/完成条件：T042 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T044 · 策略与不可变操作存储：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_policy_repository.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_policy_repository.py)。
  - 逻辑/测试上下文：真实SQL隔离两租户、首次并发配置、相同op重复、旧worker更新被拒、提交后快照不覆盖、连续修改可还原actor/版本。
  - 依赖：T005, T003。
  - 覆盖 AC: AC-27, AC-28, AC-29, AC-30。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T045 · 策略与不可变操作存储**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/domain/repositories/policy.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/repositories/policy.py)、[B:src/backend/bisheng/dsh/domain/repositories/admin_operation.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/repositories/admin_operation.py)。
  - 逻辑/测试上下文：通过Repository完成占位/所有者注册、expected_version、不可变快照同事务提交、lease_generation CAS和phase更新；相同op查幂等先于版本判断。使用自动租户过滤和写主体校验，不在Service写ORM。
  - 依赖：T005, T003, T044。
  - 验证/完成条件：T044 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T046 · SQL 明细及月汇总投影：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_usage_repository.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_usage_repository.py)。
  - 逻辑/测试上下文：真实SQL验证乱序终态先到、重复批次、ACK丢失、首次月行并发、UNKNOWN转可靠只累计一次；两用户同version不能混淆。
  - 依赖：T006。
  - 覆盖 AC: AC-22, AC-23, AC-24, AC-30, AC-34。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T047 · SQL 明细及月汇总投影**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/domain/repositories/usage.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/repositories/usage.py)。
  - 逻辑/测试上下文：project_batch按request_id合并完整状态、固定锁顺序、event_version比较；明细/模型月差额同事务，NULL不按0，投影成功才ACK。保留模型删除、跨月原归属和provider_request_id。
  - 依赖：T006, T046。
  - 验证/完成条件：T046 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T048 · Redis 实际用量准入：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_quota_admission.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_quota_admission.py)。
  - 逻辑/测试上下文：真实Redis：900/1000同时准入两请求、不扣used；limit0拒绝、UNKNOWN跨月、不同模型额度独立、Redis断连/坏type不放行。
  - 依赖：T011, T047。
  - 覆盖 AC: AC-22, AC-23, AC-30, AC-31, AC-34。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T049 · Redis 实际用量准入**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/infrastructure/quota_redis.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/infrastructure/quota_redis.py)、[B:src/backend/bisheng/dsh/infrastructure/lua/admit.lua](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/infrastructure/lua/admit.lua)。
  - 逻辑/测试上下文：独立noeviction持久Redis，同槽用户/月/模型量及请求/Stream；只在used<limit且所有门禁可证时登记RUNNING，不预占。跨月UNKNOWN仅作调用明细，不阻断；缺key不能零初始化，Lua写前校验。
  - 依赖：T011, T047, T048。
  - 验证/完成条件：T048 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T050 · Redis 可靠结算与版本幂等：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_quota_settlement.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_quota_settlement.py)。
  - 逻辑/测试上下文：真实Redis复现900+300+300=1500，首结算后新准入拒绝但在途完成；重复/乱序结算、不可靠usage、取消可靠usage及Lua异常失败关闭。
  - 依赖：T049。
  - 覆盖 AC: AC-20, AC-22, AC-23, AC-24, AC-34。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T051 · Redis 可靠结算与版本幂等**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/infrastructure/lua/settle.lua](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/infrastructure/lua/settle.lua)、[B:src/backend/bisheng/dsh/domain/services/usage.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/services/usage.py)。
  - 逻辑/测试上下文：record_usage原子累计用户及模型used、请求终态和完整Stream；允许超额，可靠0有证据；未知usage标NULL及USAGE_UNKNOWN明细，迟到补记版本CAS。所有模型结果均通过此入口结算，失败不重发模型。
  - 依赖：T049, T050。
  - 验证/完成条件：T050 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T052 · Redis 恢复门禁与安全初始化：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_quota_recovery.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_quota_recovery.py)。
  - 逻辑/测试上下文：故障注入旧快照丢尾/双主/自动重试/Stream不完整/SQL滞后，无法证明则冻结用户或分片；新月与恢复已有月分别验证。
  - 依赖：T051, T047。
  - 覆盖 AC: AC-22, AC-23, AC-30, AC-31, AC-34。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T053 · Redis 恢复门禁与安全初始化**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/domain/services/quota_recovery.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/services/quota_recovery.py)、[B:src/backend/bisheng/dsh/infrastructure/quota_topology.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/infrastructure/quota_topology.py)。
  - 逻辑/测试上下文：连接绑定已批准主节点/epoch；重连/切主先闭门并隔离旧主，经SQL/AOF/Stream未决请求核对后恢复；首次月初始化证明无历史后创建，重建UNKNOWN诊断索引，独立于准入阻断，不用复制READY证明完整。
  - 依赖：T051, T047, T052。
  - 验证/完成条件：T052 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T054 · 策略编排与历史审计：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_policy_service.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_policy_service.py)。
  - 逻辑/测试上下文：存储替身穷举每步崩溃并搭配真实Redis CAS：两个操作竞态、旧worker、权限撤销、UNKNOWN不冻结，存储故障仍保护、同op恢复、审计历史不覆盖。
  - 依赖：T045, T053, T043。
  - 覆盖 AC: AC-18, AC-21, AC-22, AC-27, AC-28, AC-29, AC-30, AC-34。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T055 · 策略编排与历史审计**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/domain/services/admin_policy.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/services/admin_policy.py)。
  - 逻辑/测试上下文：UPDATE_POLICY登记所有者→按op冻结→SQL新策略与快照→Redis安装→SQL READY→仅删除本op冻结原因；effective_at与committed_at区分，失败PROCESSING原ID续跑，不反复增version。模型列表先走既有业务可访问性。
  - 依赖：T045, T053, T043, T054。
  - 验证/完成条件：T054 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T056 · 模型强读及同版本构造：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_model_snapshot.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_model_snapshot.py)。
  - 逻辑/测试上下文：覆盖自有、合法Root共享、未授权跨租户、刚取消共享/online=false/删除；强读后SDK构造不能再次用旧缓存；既有非DSH调用回归。
  - 依赖：T043, T003。
  - 覆盖 AC: AC-18, AC-19, AC-21, AC-30。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T057 · 模型强读及同版本构造**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/llm/domain/services/llm.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/llm/domain/services/llm.py)、[B:src/backend/bisheng/llm/domain/llm/base.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/llm/domain/llm/base.py)。
  - 逻辑/测试上下文：提供DSH窄业务入口获取当前可访问模型/供应商版本并用同一快照构造BishengLLM，避免通用旧缓存复活已下线配置。合法Root共享复用现有get_model_for_call；其他模型场景继续现有缓存路径。
  - 依赖：T043, T003, T056。
  - 验证/完成条件：T056 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T058 · Chat/工具协议适配：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_protocol.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_protocol.py)。
  - 逻辑/测试上下文：fake供应商逐块工具参数、多轮tool_call_id、include_usage可选、max_tokens冲突、未知字段400、不支持能力显式拒绝；与冻结JSON/SSE样例对照。
  - 依赖：T057, T001。
  - 覆盖 AC: AC-18, AC-19, AC-20, AC-21, AC-23, AC-24。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T059 · Chat/工具协议适配**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/infrastructure/chat_adapter.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/infrastructure/chat_adapter.py)、[B:src/backend/bisheng/dsh/domain/schemas/chat.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/schemas/chat.py)。
  - 逻辑/测试上下文：严格允许messages/tools/tool_choice与冻结字段，bisheng:id解析，capabilities由验证结果声明；BishengLLM bind_tools/ainvoke/astream外层执行；规范化tool chunks/finish_reason/reasoning_content和usage，不旁路llm.llm。
  - 依赖：T057, T001, T058。
  - 验证/完成条件：T058 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T060 · DSH 模型执行闭环：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_model_service.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_model_service.py)。
  - 逻辑/测试上下文：服务集成验证空模型列表、更换模型不清used、关模型即时拒绝、工具调用与SSE首块立即转发、未知用量后的连续调用时序、成功回答不因usage缺失转为失败。
  - 依赖：T055, T059, T051。
  - 覆盖 AC: AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-27, AC-30, AC-31, AC-34。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T061 · DSH 模型执行闭环**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/domain/services/model.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/services/model.py)。
  - 逻辑/测试上下文：list_models取当前可访问与DSH policy交集；complete按principal→强读model/policy→Redis准入→LLM→结算→响应。未知usage非流503，开流error且无DONE；运行时取消与异常不自动重发，日志只保留trace摘要。
  - 依赖：T055, T059, T051, T060。
  - 验证/完成条件：T060 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

### Wave 5

- [x] **T062 · UNKNOWN 受控补记业务：先写测试**
  - 分类：Worker；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_reconciliation.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_reconciliation.py)。
  - 逻辑/测试上下文：两条UNKNOWN不阻断，先补一条不影响其他明细，重复同op无重复扣费、不同op冲突、旧月入账、actor失权、证据hash错误；Worker在可信消息headers中传tenant_id，任务前恢复ContextVar，finally reset。
  - 依赖：T061, T045, T053, T047。
  - 覆盖 AC: AC-22, AC-23, AC-24, AC-28, AC-29, AC-30, AC-31, AC-34。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T063 · UNKNOWN 受控补记业务**
  - 分类：Worker；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/domain/services/reconciliation.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/services/reconciliation.py)、[B:src/backend/bisheng/dsh/infrastructure/evidence_store.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/infrastructure/evidence_store.py)。
  - 逻辑/测试上下文：submit/status/resume验证真实super_admin作用域、逐请求MinIO证据版本/hash/usage和expected_event_version，登记RECONCILE_USAGE；复用结算CAS+Stream/SQL投影，仅更新该 UNKNOWN 明细和诊断索引，证据不足保留未知但不冻结。
  - 依赖：T061, T045, T053, T047, T062。
  - 验证/完成条件：T062 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T064 · 受控对账 CLI：先写测试**
  - 分类：后端 API；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_reconciliation_cli.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_reconciliation_cli.py)。
  - 逻辑/测试上下文：CLI解析、隐藏凭据输入、非法参数和无权限拒绝、PROCESSING与SUCCESS输出；正常fake service测试，不伪造实际供应商证据。
  - 依赖：T063。
  - 覆盖 AC: AC-23, AC-28, AC-29, AC-30, AC-31。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T065 · 受控对账 CLI**
  - 分类：后端 API；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/cli/reconcile.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/cli/reconcile.py)。
  - 逻辑/测试上下文：实现Design §4.7.4 submit/status输入；隐藏交互管理员JWT，禁止--actor-id和强制解冻/置零参数，薄入口调Service，不直改DB/Redis、不取任意URL、不保存本地恢复真相。
  - 依赖：T063, T064。
  - 验证/完成条件：T064 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T066 · Gateway 万级检索与资料投影：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshManagementTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshManagementTest.java)。
  - 逻辑/测试上下文：真实SQL覆盖同排序键翻页、两租户、5万席执行计划、模型/用量无查询；乱序资料更新、删除用户、旧投影不参与鉴权。
  - 依赖：T037, T039。
  - 覆盖 AC: AC-08, AC-25, AC-26, AC-28, AC-30, AC-33。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T067 · Gateway 万级检索与资料投影**
  - 分类：后端 Domain；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/service/DshManagementService.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/service/DshManagementService.java)、[G:src/main/java/com/dataelem/gateway/dsh/repository/DshManagementRepository.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/repository/DshManagementRepository.java)。
  - 逻辑/测试上下文：management/read在SQL过滤keyword/seat_state/login，游标有界分页后聚合会话/最近活跃；profiles/upsert≤100条按profile_version更新已有席位，不创建席位不改资格；license/session摘要不触达模型表。
  - 依赖：T037, T039, T066。
  - 验证/完成条件：T066 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T068 · 用户资料同步业务适配：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_profile_outbox.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_profile_outbox.py)。
  - 逻辑/测试上下文：真实事务测试成功/回滚、版本递增、同version重复、无席位不分配；profile_version/身份主数据与outbox同提交。
  - 依赖：T007, T045, T067。
  - 覆盖 AC: AC-04, AC-08, AC-25, AC-26, AC-29, AC-30, AC-33。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T069 · 用户资料同步业务适配**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/domain/services/profile.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/services/profile.py)、[B:src/backend/bisheng/user/domain/repositories/dsh_profile.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/user/domain/repositories/dsh_profile.py)。
  - 逻辑/测试上下文：提供record_change(session,user)与当前页batch_snapshot入口，原用户业务拥有资料/版本；用户Repository只递增版本并返回快照；原用户业务调用DSH Profile服务，在同一session中由DSH自己的操作Repository登记SYNC_PROFILE，不跨模块直调Repository、不另起独立提交。DSH关闭不初始化Gateway；初始/巡检查询有界游标。
  - 依赖：T007, T045, T067, T068。
  - 验证/完成条件：T068 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T070 · 用户改名删除接入事务钩子：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_user_profile_changes.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_user_profile_changes.py)。
  - 逻辑/测试上下文：对实际用户API测试改名/停用/删除成功有意图、失败回滚无意图；原角色/权限/JWT回归；不因资料同步释放席位。
  - 依赖：T069。
  - 覆盖 AC: AC-04, AC-08, AC-17, AC-25, AC-26, AC-29, AC-30, AC-33。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T071 · 用户改名删除接入事务钩子**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/user/api/user.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/user/api/user.py)、[B:src/backend/bisheng/user/domain/services/user.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/user/domain/services/user.py)。
  - 逻辑/测试上下文：现有改名/停用/删除写入口在user/api/user.py，改为调用用户业务入口完成该段写事务；Service通过用户Repository及record_change登记版本与意图，不在端点新增ORM或跨模块Endpoint调用。保持既有JWT失效、权限钩子和删除语义。
  - 依赖：T069, T070。
  - 验证/完成条件：T070 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T072 · 主部门变更不触发 DSH 同步：回归测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_user_profile_changes.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_user_profile_changes.py)。
  - 逻辑/测试上下文：真实主部门变更不增加 dsh_profile_version、不登记 SYNC_PROFILE；保留既有主部门和租户同步行为。
  - 依赖：T071。
  - 覆盖 AC: AC-04, AC-08, AC-25, AC-26, AC-29, AC-30, AC-33。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T073 · 删除主部门变更的 DSH 事务钩子**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/user/domain/services/user_department_service.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/user/domain/services/user_department_service.py)。
  - 逻辑/测试上下文：删除 UserDepartmentService.change_primary_department 中新增的 record_dsh_profile_change 调用；原主部门、租户、权限投影业务保持既有行为。
  - 依赖：T071, T072。
  - 验证/完成条件：T072 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T074 · 操作恢复与资料同步 Worker：先写测试**
  - 分类：Worker；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_operation_worker.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_operation_worker.py)。
  - 逻辑/测试上下文：两租户连续执行/失败重试不串租户，过期lease接管、旧worker写入拒绝、投递丢失巡检、资料乱序；共享状态只在SQL/Redis。
  - 依赖：T063, T055, T073, T041。
  - 覆盖 AC: AC-09, AC-11, AC-23, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-33, AC-34。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T075 · 操作恢复与资料同步 Worker**
  - 分类：Worker；类型：实现。
  - 文件：[B:src/backend/bisheng/worker/dsh/operations.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/worker/dsh/operations.py)、[B:src/backend/bisheng/worker/dsh/profiles.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/worker/dsh/profiles.py)。
  - 逻辑/测试上下文：UPDATE_POLICY/RECONCILE_USAGE按租约代次恢复，席位动作仅查询/重试同op；SYNC_PROFILE每批≤100用户游标补齐/巡检。dispatcher从受信操作行派发，Celery headers传tenant_id→任务前ContextVar→finally reset，拒绝header/payload不符，跨租户调度逐租户显式派发。
  - 依赖：T063, T055, T073, T041, T074。
  - 验证/完成条件：T074 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T076 · Stream 投影与 UNKNOWN 巡检：先写测试**
  - 分类：Worker；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_projection_worker.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_projection_worker.py)。
  - 逻辑/测试上下文：真实Redis/SQL模拟消费者崩溃、ACK丢失、事件乱序、超过背压阈值；完整状态恢复后不重复累计，UNKNOWN影响用户级门禁。
  - 依赖：T047, T053, T075。
  - 覆盖 AC: AC-20, AC-22, AC-23, AC-24, AC-30, AC-31, AC-34。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T077 · Stream 投影与 UNKNOWN 巡检**
  - 分类：Worker；类型：实现。
  - 文件：[B:src/backend/bisheng/worker/dsh/usage.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/worker/dsh/usage.py)、[B:src/backend/bisheng/dsh/domain/services/projection.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/services/projection.py)。
  - 逻辑/测试上下文：消费者按用户/租户分区批量project_batch，提交后XACK；PEL认领、积压>30s/高水位背压、超时RUNNING→UNKNOWN。Celery headers→ContextVar，每批核对事件tenant与key归属，finally reset；不能用跨租户无界内存聚合。
  - 依赖：T047, T053, T075, T076。
  - 验证/完成条件：T076 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T078 · Worker 与周期任务注册：先写测试**
  - 分类：Worker；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_operations_runtime.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_operations_runtime.py)。
  - 逻辑/测试上下文：任务发现、两租户headers、DSH关闭无远程依赖、Beat重复投递幂等；普通knowledge/workflow队列配置保持。
  - 依赖：T077。
  - 覆盖 AC: AC-23, AC-27, AC-28, AC-30, AC-31, AC-32, AC-34。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T079 · Worker 与周期任务注册**
  - 分类：Worker；类型：实现。
  - 文件：[B:src/backend/bisheng/worker/main.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/worker/main.py)、[B:src/backend/bisheng/worker/config.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/worker/config.py)。
  - 逻辑/测试上下文：仅DSH启用时接线操作/资料/投影任务与Beat；API、Worker各自读取可选配置；跨租户定时dispatcher按受信租户业务返回逐个派发headers，禁止默认tenant1。共享main/config保留旧队列与调度。
  - 依赖：T077, T078。
  - 验证/完成条件：T078 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

### Wave 6

- [x] **T080 · Gateway 公共四端点：先写测试**
  - 分类：后端 API；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshPublicControllerTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshPublicControllerTest.java)。
  - 逻辑/测试上下文：WebTestClient验证四端点请求字段、无Secret、refresh同成功体、PKCE失败、logout204、关闭仍可读JWKS/可验证撤销。
  - 依赖：T035, T027, T039。
  - 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-08, AC-13, AC-14, AC-15, AC-16, AC-17, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T081 · Gateway 公共四端点**
  - 分类：后端 API；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/controller/DshPublicController.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/controller/DshPublicController.java)。
  - 逻辑/测试上下文：提供 POST /api/dsh/authorizations、POST /api/dsh/token、POST /api/dsh/logout、GET /api/dsh/jwks；委托对应Service，裸JSON/204与冻结错误HTTP，禁止普通商业200错误包装。
  - 依赖：T035, T027, T039, T080。
  - 验证/完成条件：T080 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T082 · Gateway 七个内部端点：先写测试**
  - 分类：后端 API；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshInternalControllerTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshInternalControllerTest.java)。
  - 逻辑/测试上下文：服务auth拒绝、越权管理、UNKNOWN结果非成功、分页有界、upsert无席位不创建；无客户端Secret授权这些端点。
  - 依赖：T067, T023, T037。
  - 覆盖 AC: AC-09, AC-10, AC-11, AC-12, AC-14, AC-17, AC-25, AC-26, AC-28, AC-29, AC-30, AC-33。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T083 · Gateway 七个内部端点**
  - 分类：后端 API；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/dsh/controller/DshInternalController.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/controller/DshInternalController.java)。
  - 逻辑/测试上下文：POST /api/internal/dsh 下 introspect、authorizations/resolve、management/read、seats/revoke、seats/reassign、operations/read、profiles/upsert；服务HMAC和管理目标作用域校验后委托Service，不能从任意header取得管理员。
  - 依赖：T067, T023, T037, T082。
  - 验证/完成条件：T082 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T084 · Gateway 路由/License 过滤接线：先写测试**
  - 分类：后端 API；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshRoutingTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshRoutingTest.java)。
  - 逻辑/测试上下文：运行真实filter链验证单Nginx版本路由、旧11001包装、DSH错误HTTP、关闭与两类License组合；mapper可发现、SSE逐块透传、普通业务回归。
  - 依赖：T081, T083, T019。
  - 覆盖 AC: AC-01, AC-13, AC-15, AC-16, AC-17, AC-20, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T085 · Gateway 路由/License 过滤接线**
  - 分类：后端 API；类型：实现。
  - 文件：[G:src/main/java/com/dataelem/gateway/filter/LicenseExpiredGlobalFilter.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/filter/LicenseExpiredGlobalFilter.java)、[G:src/main/java/com/dataelem/gateway/dsh/config/DshConfiguration.java](/Users/zhangguoqing/works/bisheng-gateway/src/main/java/com/dataelem/gateway/dsh/config/DshConfiguration.java)。
  - 逻辑/测试上下文：旧商业过滤器仅移交精确DSH路由到独立策略，V1/V2仍原路代理；Spring显式扫描DSH mapper，保留既有MapperScan。不开DSH仍保留旧商业与代理路径，不将所有/api豁免；SSE禁止完整缓存改写。
  - 依赖：T081, T083, T019, T084。
  - 验证/完成条件：T084 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T086 · Python 配置/浏览器授权/内部身份：先写测试**
  - 分类：后端 API；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_identity_api.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_identity_api.py)。
  - 逻辑/测试上下文：HTTP集成四端点、非法Origin/票据、服务auth与普通JWT隔离、disabled无远程依赖、Snapshot DTO字段；与Gateway fixture对照。
  - 依赖：T025, T041, T083。
  - 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-13, AC-30, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T087 · Python 配置/浏览器授权/内部身份**
  - 分类：后端 API；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/api/endpoints/identity.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/api/endpoints/identity.py)。
  - 逻辑/测试上下文：GET /api/v1/dsh/config 裸JSON；POST /api/v1/dsh/authorize 浏览器JWT+Origin/CSRF沿用统一包装；POST /api/v1/internal/dsh/identity/redeem、identity/check 使用服务HMAC返回规范Snapshot。关闭config仅enabled=false，不泄露地址。
  - 依赖：T025, T041, T083, T086。
  - 验证/完成条件：T086 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T088 · Python 模型/用量三端点：先写测试**
  - 分类：后端 API；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_models_api.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_models_api.py)。
  - 逻辑/测试上下文：HTTP流消费而非仅headers断言：tool chunks、usage块、error不DONE、非流unknown503、quota429、跨租户/错误token、源不可用不伪零。
  - 依赖：T061, T043, T077。
  - 覆盖 AC: AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-30, AC-31, AC-34。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T089 · Python 模型/用量三端点**
  - 分类：后端 API；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/api/endpoints/models.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/api/endpoints/models.py)。
  - 逻辑/测试上下文：GET /api/v1/dsh/models、POST /api/v1/dsh/chat/completions、GET /api/v1/dsh/usage：依赖DshPrincipal，裸JSON/SSE；usage实时或带as_of的persisted/unavailable，不用SQL降级授权。流式上下文在生成器结束后清理。
  - 依赖：T061, T043, T077, T088。
  - 验证/完成条件：T088 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T090 · Python 统一管理聚合：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_admin_service.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_admin_service.py)。
  - 逻辑/测试上下文：模拟Gateway超时、分页游标、N+1计数、两租户与普通用户拒绝；连续policy审计与撤销/重分配异步状态，不显示伪成功。
  - 依赖：T075, T067, T041, T055。
  - 覆盖 AC: AC-09, AC-11, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-33。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T091 · Python 统一管理聚合**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/domain/services/admin.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/services/admin.py)。
  - 逻辑/测试上下文：users先Gateway分页再当前页用户业务批量补齐，不查模型/用量；policy视图读用户策略/实时用量；revoke/reassign先存意图，再调用/查询原op；operations返回actor/前后值/phase与结果，管理员合法作用域。
  - 依赖：T075, T067, T041, T055, T090。
  - 验证/完成条件：T090 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T092 · Python 八个管理端点：先写测试**
  - 分类：后端 API；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_admin_api.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_admin_api.py)。
  - 逻辑/测试上下文：八端点Admin/普通用户/跨租户表驱动；policy保存重试幂等与PROCESSING、operations审计字段、Gateway不可用显式unavailable。
  - 依赖：T091。
  - 覆盖 AC: AC-09, AC-11, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-33。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T093 · Python 八个管理端点**
  - 分类：后端 API；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/api/endpoints/admin.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/api/endpoints/admin.py)。
  - 逻辑/测试上下文：提供 /api/v1/dsh/admin 下 GET users、GET license、PUT users/{id}/policy、POST users/{id}/revoke、POST users/{id}/reassign、GET operations/{id}、GET users/{id}/policy、GET users/{id}/sessions；统一管理包装，真实actor、版本和operation_id必校验。
  - 依赖：T091, T092。
  - 验证/完成条件：T092 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T094 · Python Router 与独立认证接线：先写测试**
  - 分类：后端 API；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_access.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_access.py)。
  - 逻辑/测试上下文：实际主app路由表验证15个Python端点均存在、重复前缀不存在；无内部接口被普通DSH token调用；旧API可用。
  - 依赖：T087, T089, T093。
  - 覆盖 AC: AC-01, AC-03, AC-04, AC-15, AC-16, AC-17, AC-30, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T095 · Python Router 与独立认证接线**
  - 分类：后端 API；类型：实现。
  - 文件：[B:src/backend/bisheng/dsh/api/router.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/api/router.py)、[B:src/backend/bisheng/api/router.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/api/router.py)。
  - 逻辑/测试上下文：注册精确DSH路由及internal/dsh，不改变原V2认证；分组public/browser/dsh/service/admin依赖，DSH关闭无启动远程依赖。
  - 依赖：T087, T089, T093, T094。
  - 验证/完成条件：T094 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T096 · 认证中间件与流上下文回归：先写测试**
  - 分类：后端 API；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_middleware.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_middleware.py)。
  - 逻辑/测试上下文：app真实中间件验证几类凭证不可混用、停用/跨租户、SSE迭代前后ContextVar、不记录票据和token；普通JWT/PAT/SAK回归。
  - 依赖：T095, T043。
  - 覆盖 AC: AC-01, AC-04, AC-15, AC-16, AC-17, AC-20, AC-30, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T097 · 认证中间件与流上下文回归**
  - 分类：后端 API；类型：实现。
  - 文件：[B:src/backend/bisheng/utils/http_middleware.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/utils/http_middleware.py)。
  - 逻辑/测试上下文：为DSH路径交由独立依赖处理而精确接线，不能把全/v1前缀豁免；浏览器JWT和原API继续现有认证。HTTP访问日志对票据/Authorization/回调query脱敏，SSE上下文持续到结束。
  - 依赖：T095, T043, T096。
  - 验证/完成条件：T096 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

- [x] **T098 · DSH 遥测与日志区分：先写测试**
  - 分类：后端 Domain；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_telemetry.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_telemetry.py)。
  - 逻辑/测试上下文：与非DSH调用分开，旧枚举序列化不改；遥测失败不把成功账本回滚，敏感字段不进入日志。
  - 依赖：T061, T097。
  - 覆盖 AC: AC-19, AC-23, AC-24, AC-31, AC-32。
  - 验证/完成条件：只增加测试/fixture，不混入实现；先记录预期失败，再由配对实现转绿。真实存储用例必须实际运行，未具备环境保持待验证。

- [x] **T099 · DSH 遥测与日志区分**
  - 分类：后端 Domain；类型：实现。
  - 文件：[B:src/backend/bisheng/common/constants/enums/telemetry.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/common/constants/enums/telemetry.py)、[B:src/backend/bisheng/dsh/domain/services/model.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/bisheng/dsh/domain/services/model.py)。
  - 逻辑/测试上下文：新增DSH应用类型并在既有模型调用上下文传递，保留旧枚举含义；关联request/trace但不记录完整消息/Secret。遥测仅展示，硬用量账本仍走Redis。
  - 依赖：T061, T097, T098。
  - 验证/完成条件：T098 全部通过；执行本任务所列文件的静态检查，保留失败/环境缺口证据。

### Wave 7

- [x] **T100 · 核对当前 UI 与语言源**
  - 分类：前端 Platform；类型：检查。
  - 文件：[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/platform-ui-check.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/platform-ui-check.md)。
  - 逻辑/测试上下文：每次真正编写页面前读取 packages/ui/docs/index.md、components/index.mdx 的done组件与既有SystemPage实现；记录复用组件和交互，不改设计规范/组件视觉。新代码使用平台封装API与现有异步模式，不新增被冻结的react-query v3 import；不触碰Recoil Client。
  - 依赖：T093, T087。
  - 验证/完成条件：记录各组件实际文件与语言namespace；无设计系统样式改动。

- [x] **T101 · 管理与授权文案 zh/en**
  - 分类：前端 Platform；类型：实现。
  - 文件：[B:src/frontend/platform/public/locales/zh-Hans/bs.json](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/public/locales/zh-Hans/bs.json)、[B:src/frontend/platform/public/locales/en-US/bs.json](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/public/locales/en-US/bs.json)。
  - 逻辑/测试上下文：新增DSH登录确认、复制票据、深链、席位/登录、模型额度、审计状态与不可用文案；只增DSH keys，不硬编码中文。
  - 依赖：T100。
  - 验证/完成条件：与下一任务同批完成；不改其他模块已有文案。

- [x] **T102 · 管理与授权文案 ja**
  - 分类：前端 Platform；类型：实现。
  - 文件：[B:src/frontend/platform/public/locales/ja/bs.json](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/public/locales/ja/bs.json)。
  - 逻辑/测试上下文：补齐完全一致的DSH日文keys；导出的错误文案只引用api_errors权威源。
  - 依赖：T101。
  - 验证/完成条件：三语言parity、pnpm check-i18n，不扩大baseline。

- [x] **T103 · 平台请求与 DTO**
  - 分类：前端 Platform；类型：实现。
  - 文件：[B:src/frontend/platform/src/controllers/API/dsh.ts](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/controllers/API/dsh.ts)、[B:src/frontend/platform/src/types/dsh.ts](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/types/dsh.ts)。
  - 逻辑/测试上下文：封装admin八接口、config/authorize请求，区分裸JSON和统一data；类型包含游标、unavailable、op phase/审计、版本。仅导入controllers/request，不在store发HTTP。
  - 依赖：T102, T093, T087。
  - 验证/完成条件：类型检查；用Mock响应验证disabled、不完整响应和PROCESSING，不新增403业务分支。

- [x] **T104 · 浏览器授权及固定入口**
  - 分类：前端 Platform；类型：实现。
  - 文件：[B:src/frontend/platform/src/pages/DshLogin/index.tsx](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/pages/DshLogin/index.tsx)、[B:src/frontend/platform/src/pages/DshLogin/useDshAuthorization.ts](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/pages/DshLogin/useDshAuthorization.ts)。
  - 逻辑/测试上下文：实现/desktop-login固定入口和auth_id授权：未登录走既有登录后回到页面，真实用户确认POST authorize；校验服务端redirect后loopback送票据，失败可手动复制。深链只带server，不含票据；固定地址首次开启客户端后再发起PKCE。
  - 依赖：T103。
  - 验证/完成条件：在{BASE}/desktop-login验证登录/取消/过期/非法auth、未安装客户端与粘贴兜底；截图/日志不含真实票据。

- [x] **T105 · 席位与登录视图**
  - 分类：前端 Platform；类型：实现。
  - 文件：[B:src/frontend/platform/src/pages/SystemPage/dsh/SeatsView.tsx](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/pages/SystemPage/dsh/SeatsView.tsx)、[B:src/frontend/platform/src/pages/SystemPage/dsh/SeatSessions.tsx](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/pages/SystemPage/dsh/SeatSessions.tsx)。
  - 逻辑/测试上下文：游标分页keyword/state/department/login筛选，列表只显示身份/席位/登录；会话展开独立分页。撤销/重分配使用稳定opID和expected_grant_version，满席/处理中/失败明确展示。
  - 依赖：T103。
  - 验证/完成条件：万级Mock只加载当前页、无模型/用量列；操作未完成不显示成功，改筛选重置游标。

- [x] **T106 · 模型与额度视图**
  - 分类：前端 Platform；类型：实现。
  - 文件：[B:src/frontend/platform/src/pages/SystemPage/dsh/PolicyView.tsx](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/pages/SystemPage/dsh/PolicyView.tsx)、[B:src/frontend/platform/src/pages/SystemPage/dsh/PolicyEditor.tsx](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/pages/SystemPage/dsh/PolicyEditor.tsx)。
  - 逻辑/测试上下文：分开查看当前用户模型集合、各模型独立月限额、各model用量和source/as_of；保存expected_version+opID，冲突刷新重选，PROCESSING展示phase。quota未知不是0，不提供UNKNOWN强制解冻。
  - 依赖：T103。
  - 验证/完成条件：合法共享可选、空集合/limit0禁止、900/1000并发最终1500、persisted不可用显式展示，保存失败保留输入。

- [x] **T107 · 管理进度与审计展示**
  - 分类：前端 Platform；类型：实现。
  - 文件：[B:src/frontend/platform/src/pages/SystemPage/dsh/OperationStatus.tsx](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/pages/SystemPage/dsh/OperationStatus.tsx)、[B:src/frontend/platform/src/pages/SystemPage/dsh/index.tsx](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/pages/SystemPage/dsh/index.tsx)。
  - 逻辑/测试上下文：同一System入口两视图+License摘要；有界轮询operations展示actor/前后值/版本及committed/effective时间，离开页取消轮询；Gateway不可用不伪造0席。
  - 依赖：T105, T106。
  - 验证/完成条件：连续两次修改可分别查看op审计；PROCESSING→成功/失败，旧响应不能覆盖新操作。

- [x] **T108 · 路由和系统入口接线**
  - 分类：前端 Platform；类型：实现。
  - 文件：[B:src/frontend/platform/src/routes/index.tsx](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/routes/index.tsx)、[B:src/frontend/platform/src/pages/SystemPage/index.tsx](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/frontend/platform/src/pages/SystemPage/index.tsx)。
  - 逻辑/测试上下文：增加/desktop-login及DSH系统管理入口，遵守原页面管理员能力与navigation控制；既有登录/系统页流程保持。触及已有中文按i18n规则提取且同批三语言完成。
  - 依赖：T104, T107。
  - 验证/完成条件：pnpm lint/typecheck/check-i18n；管理员可见、普通用户不能打开管理页；原系统路由及登录回跳回归。

- [x] **T109 · DSH Desktop 外部交付边界**
  - 分类：外部 Desktop 交付；类型：联调依赖。
  - 文件：[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/desktop-handoff-checklist.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/desktop-handoff-checklist.md)。
  - 逻辑/测试上下文：本仓src/frontend/client（Recoil /workspace）无本期改动；DSH Desktop源码未提供，不编造路径或任务完成。用冻结7接口/7时序图列出客户端待实现：安全存储、PKCE/loopback/深链粘贴、串行refresh、provider模型、tools/SSE、usage/错误和logout；需要客户端团队提供版本/实现后联调，不主动发送外部消息。
  - 依赖：T108, T085, T099。
  - 验证/完成条件：逐条对应client-api C01–C18，记录客户端版本/负责人/样本缺失为待联调，不扩大客户端接口。

### Wave 8

- [ ] **T110 · API 端到端与三角色回归**
  - 分类：后端 API；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_dsh_e2e.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_dsh_e2e.py)、[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/e2e-report.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/e2e-report.md)。
  - 逻辑/测试上下文：调用仓库e2e-test技能；以真实Nginx/Gateway/Python测试环境跑T1/T2+Root、10席、11用户：授权→Token→models→tools/SSE→usage→登出保席→撤销/重分配→旧token拒绝；执行UNKNOWN CLI补记/冻结和审计。记录服务SHA/配置版本/测试License样本摘要；环境缺失保持待执行，不用mock结果充当e2e。
  - 依赖：T109, T079。
  - 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34。
  - 验证/完成条件：命令：在B/src/backend运行 python -m pytest --confcutdir=test/dsh test/dsh/test_dsh_e2e.py；记录每个AC通过/失败/阻塞及脱敏request_id。

- [ ] **T111 · 目标旧版本 License 二进制兼容**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshLicenseLoaderCompatibilityTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshLicenseLoaderCompatibilityTest.java)、[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/license-compatibility-report.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/license-compatibility-report.md)。
  - 逻辑/测试上下文：固定目标旧Gateway artifact摘要，真实旧trial/pro样本在新程序保持行为；含扩展新密文交给旧二进制解码，测大小/分段/未知字段，验证原功能与回退旧license。供应商生产签名私钥不进测试仓库；无目标artifact/授权样本时标未验证。
  - 依赖：T110, T019, T085。
  - 覆盖 AC: AC-07, AC-13, AC-14, AC-25, AC-31, AC-32。
  - 验证/完成条件：分别记录新旧程序输入/输出和artifact摘要；不得只测新Loader即声称双向兼容。

- [ ] **T112 · MySQL/DM8 与万级检索门禁**
  - 分类：后端 Domain；类型：测试。
  - 文件：[G:src/test/java/com/dataelem/gateway/dsh/DshManagementTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshManagementTest.java)、[G:src/test/java/com/dataelem/gateway/dsh/DshSeatRepositoryTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshSeatRepositoryTest.java)、[G:src/test/java/com/dataelem/gateway/dsh/DshSessionRepositoryTest.java](/Users/zhangguoqing/works/bisheng-gateway/src/test/java/com/dataelem/gateway/dsh/DshSessionRepositoryTest.java)、[B:src/backend/test/dsh/test_usage_repository.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_usage_repository.py)、[B:src/backend/test/dsh/test_projection_worker.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_projection_worker.py)、[B:src/backend/test/dsh/test_quota_shards.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_quota_shards.py)、[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/database-acceptance.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/database-acceptance.md)。
  - 逻辑/测试上下文：在独立MySQL/DM8各跑席位空范围竞争/死锁重试/刷新family/撤销乱序；5万席位过滤分页执行计划。Python SQL策略审计和用量投影运行同方言用例；只记录数据，不另建一套计量实现。
  - 依赖：T111, T029, T047。
  - 覆盖 AC: AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-17, AC-23, AC-25, AC-26, AC-29, AC-30, AC-33, AC-34。
  - 验证/完成条件：macOS不承诺DM8驱动可用，使用Linux集中回归并保存结果；真实双库未通过不关闭上线门禁。

  - 本地验收状态：MySQL 8.0.46 专属空库五文件复跑 22 项通过；Gateway 最新 48 项及 package 通过，另一次 50,000 席位 scale 已通过。DM8 真库尚未执行；静态 DDL/方言检查不等于双库验收，保持未勾选。

- [ ] **T113 · 跨进程账本恢复与延迟验收**
  - 分类：Worker；类型：测试。
  - 文件：[B:src/backend/test/dsh/test_dsh_failure_acceptance.py](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/src/backend/test/dsh/test_dsh_failure_acceptance.py)、[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/recovery-acceptance.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/recovery-acceptance.md)。
  - 逻辑/测试上下文：真实Redis/AOF/Stream/SQL：旧快照丢尾、切主旧主隔离、SQL故障/ACK丢失、UNKNOWN跨月、同op恢复。Worker消息headers tenant→ContextVar→reset必须断言；两副本50并发测额外准入p95≤200ms目标、2秒验席超时、5秒投影及30秒背压。
  - 依赖：T112, T077, T075。
  - 覆盖 AC: AC-20, AC-22, AC-23, AC-24, AC-27, AC-28, AC-29, AC-30, AC-31, AC-34。
  - 验证/完成条件：记录实际数据及未达到目标的瓶颈；未知状态必须拒绝，不为跑通测试降低failclosed或改预占。

  - 本地验收状态：真实 Redis/MySQL/MinIO、七独立子进程故障验收已通过；实际样本与时延测法见 recovery-acceptance.md。独占 Redis AOF 重启/关闭旧主后晋升两项已实测通过，配额联合 62 项通过；部署主切换/旧主网络隔离、两副本 50 并发与 p95≤200ms 准入目标待环境，保持未勾选。

- [ ] **T114 · 两仓代码与交付审查**
  - 分类：基础设施；类型：检查。
  - 文件：[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/code-review.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/code-review.md)、[B:features/v3.0.0-beta2/062-dsh-desktop-model-access/rollout.md](/Users/zhangguoqing/works/bisheng/.worktrees/feat-3.0.0-beta2-pre/features/v3.0.0-beta2/062-dsh-desktop-model-access/rollout.md)。
  - 逻辑/测试上下文：执行仓库code-review/task-review，B相对v3.0.0-beta1-fix、G相对已核对main审差异；上线顺序为备份→双库结构→配置/公钥/证据→服务关闭态部署→签名授权受控切换→客户端联调→小流量启用，回退关闭DSH保留席位/账本。汇总静态/e2e/旧二进制/双库/恢复证据；提交、push、合并或部署按用户另行授权，不写已完成。
  - 依赖：T113。
  - 验证/完成条件：修复所有本期阻塞项并回写Design偏差；pnpm lint/typecheck/check-i18n、Python ruff、目标pytest、Gateway Maven测试有实际结果。

## AC → 测试追溯

| AC | 测试任务 |
|---|---|
| AC-01 | T024, T026, T080, T084, T086, T094, T096, T110 |
| AC-02 | T022, T024, T026, T040, T080, T086, T110 |
| AC-03 | T022, T024, T026, T030, T040, T080, T086, T094, T110 |
| AC-04 | T022, T024, T026, T030, T042, T068, T070, T072, T080, T086, T094, T096, T110 |
| AC-05 | T016, T028, T030, T110, T112 |
| AC-06 | T028, T030, T032, T034, T110, T112 |
| AC-07 | T016, T018, T020, T028, T030, T110, T111, T112 |
| AC-08 | T028, T030, T032, T034, T038, T066, T068, T070, T072, T080, T110, T112 |
| AC-09 | T036, T074, T082, T090, T092, T110, T112 |
| AC-10 | T028, T030, T036, T082, T110, T112 |
| AC-11 | T036, T074, T082, T090, T092, T110, T112 |
| AC-12 | T020, T028, T030, T036, T082, T110, T112 |
| AC-13 | T016, T018, T022, T024, T026, T030, T032, T034, T038, T042, T080, T084, T086, T110, T111 |
| AC-14 | T016, T018, T020, T022, T030, T032, T034, T036, T038, T042, T080, T082, T110, T111 |
| AC-15 | T032, T034, T038, T040, T042, T080, T084, T088, T094, T096, T110 |
| AC-16 | T034, T038, T040, T042, T080, T084, T088, T094, T096, T110 |
| AC-17 | T032, T034, T036, T038, T040, T042, T070, T080, T082, T084, T088, T094, T096, T110, T112 |
| AC-18 | T054, T056, T058, T060, T088, T110 |
| AC-19 | T056, T058, T060, T088, T098, T110 |
| AC-20 | T050, T058, T060, T076, T084, T088, T096, T110, T113 |
| AC-21 | T054, T056, T058, T060, T088, T110 |
| AC-22 | T046, T048, T050, T052, T054, T060, T062, T076, T088, T110, T113 |
| AC-23 | T046, T048, T050, T052, T058, T060, T062, T064, T074, T076, T078, T088, T098, T110, T112, T113 |
| AC-24 | T046, T050, T058, T060, T062, T076, T088, T098, T110, T113 |
| AC-25 | T018, T040, T066, T068, T070, T072, T074, T082, T090, T092, T110, T111, T112 |
| AC-26 | T066, T068, T070, T072, T074, T082, T090, T092, T110, T112 |
| AC-27 | T044, T054, T060, T074, T078, T090, T092, T110, T113 |
| AC-28 | T036, T040, T044, T054, T062, T064, T066, T074, T078, T082, T090, T092, T110, T113 |
| AC-29 | T036, T044, T054, T062, T064, T068, T070, T072, T074, T082, T090, T092, T110, T112, T113 |
| AC-30 | T024, T028, T042, T044, T046, T048, T052, T054, T056, T060, T062, T064, T066, T068, T070, T072, T074, T076, T078, T082, T086, T088, T090, T092, T094, T096, T110, T112, T113 |
| AC-31 | T016, T018, T020, T022, T024, T038, T040, T042, T048, T052, T060, T062, T064, T076, T078, T080, T084, T086, T088, T094, T096, T098, T110, T111, T113 |
| AC-32 | T016, T018, T020, T038, T040, T042, T078, T080, T084, T086, T094, T096, T098, T110, T111 |
| AC-33 | T066, T068, T070, T072, T074, T082, T090, T092, T110, T112 |
| AC-34 | T046, T048, T050, T052, T054, T060, T062, T074, T076, T078, T088, T110, T112, T113 |

## HTTP / 数据 / Service 责任索引

| 契约 | 实现任务 |
|---|---|
| Gateway公共4接口：authorizations/token/logout/jwks | T081 |
| Gateway内部7接口：introspect/resolve/read/revoke/reassign/operations/profiles | T083 |
| Python身份4接口：config/authorize/redeem/check | T087 |
| Python模型3接口：models/chat/completions/usage | T089 |
| Python管理8接口：users/license/policy写/revoke/reassign/operations/policy读/sessions | T093 |
| dsh_user_policy / dsh_admin_operation | T005 |
| dsh_monthly_usage / dsh_model_call | T006 |
| gt_dsh_seat / gt_dsh_session | T008 |
| gt_dsh_refresh_token / gt_dsh_operation | T009 |
| DshIdentityService.authorize/redeem/check | T025 |
| DshAccessService.authenticate | T043 |
| DshModelService.list_models/complete | T061 |
| DshUsageService.check_and_start | T049 |
| DshUsageService.record_usage/reconcile_unknown 原子结算 | T051 |
| DshUsageService.project_batch / projection adapter | T077 |
| DshAdminService.update_policy | T055 |
| DshAdminService.revoke/reassign + users/license/policy/session聚合 | T091 |
| DshReconciliationService.submit/status/resume | T063 |
| 浏览器授权与固定desktop-login | T104 |
| 统一系统管理入口与审计进度 | T107 |

总计 4+7+4+3+8=26 个 HTTP 端点；CLI 不增加 HTTP 接口。模型/字段的唯一来源仍是 Design；本表只标实施责任，不另定义协议。

## 实际偏差记录

T001/T002 → Design §4.1/§4.5.4/§6：可执行fixture与发行契约已固定；真实旧二进制与发行样本仍为后续门禁。

T005/T006/T011/T013 → Design §4.5.1/§6：物理通用时间字段、独立配置/DTO和261错误码已落地。

T115/T116：补充有意义的基础验证与C5注册，原114项任务ID不变；本期共116项。

2026-09-09 任务拆解采用当前Platform禁止新增react-query v3 import的约束、既有MyBatis技术栈和Python新表发现规则；这些是实现接线细节，不改变已确认产品或客户端契约。实施发现新边界时回写Design，并在这里记录“任务ID → Design章节”的一行指针。

## 用户确认的逐模型修订

以下任务基于用户已确认的配置含义，评审及证据见 [model-quota-revision.md](./model-quota-revision.md)；未新增限流需求。

- [x] **T117 · 强类型主配置**：DshSettings / ChatCapabilities，API与Worker共用，字段说明/边界/Secret脱敏验证。
- [x] **T118 · 逐模型策略对象与持久化**：用户内模型唯一，完整列表CAS/操作幂等，各额度分别校验；管理API移除共享额度字段。
- [x] **T119 · 逐模型准入与恢复**：Redis按模型真实用量检查；SQL回显与恢复摘要绑定每项额度；保留在途结算、历史与UNKNOWN门禁。
- [x] **T120 · 管理界面**：逐模型编辑/用量/剩余，缺计数显示未知，三语言与类型检查通过。
- [x] **T121 · 客户端修订**：usage可选model查询、七张时序图、调用时机与交接记录同步，尚未对外发送。
- [x] **T122 · SQL兼容性修复与验收**：毕昇新增业务无手写SQL；Gateway沿用Mapper，修正DM字节容量和空表占席锁方案；真实MySQL迁移及Gateway回归通过，DM实机明确暂缓。

## 用户确认后的 0.3.0 收敛

- [x] 缺失用量仅记录调用明细，不冻结；正常 JSON/SSE 保留结果。
- [x] 分离 UNKNOWN 诊断与策略/存储保护，验证跨月、恢复、重复补记和下一次调用。
- [x] 删除部门筛选、DTO/表字段/索引及同步接线，保留用户名检索。
- [x] 更新客户端契约 0.3.0、时序图和两仓回归，详见 [修订记录](./usage-and-search-revision.md)。
- [ ] 客户端团队确认与真实联调。

### 2026-09-10：已批准的 demo 界面对齐

- [x] 模型管理新增 DSH 开放范围弹窗，按用户＋当前模型修改额度，移除原用户维度的编辑入口。
- [x] 新增模型维度分页用户查询，包含尚无额度策略的有效毕昇用户，不依赖 DSH 登录；复用原保存、版本校验和操作审计，不修改其他模型配置。
- [x] 提供方与实际模型名称展示；会话改弹窗；三语文案与差异边界落盘。
- [x] 完成本地接口与页面回归、代码质量检查，证据见 ui-demo-alignment.md。
- [ ] 用户部署后完成真实环境联调；按用户要求，本次仅提交并推送，不部署 109。
