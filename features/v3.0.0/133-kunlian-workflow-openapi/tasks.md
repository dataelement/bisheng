# F133 实施任务

- Status：IMPLEMENTATION_AUTHORIZED（2026-11-16 用户确认参考 SG 方式实现）
- 需求：[spec.md](./spec.md)；设计：[design.md](./design.md)
- 使用项目 features 路径及 spec.md 命名，不复制通用 specs/requirements.md。
- 无真实环境部署、数据回填或秘密注入授权。

## W1：凭据与用户上下文

- [x] T001 独立昆联 Key 元数据、仓储及生命周期服务；仅保存哈希，超管管理，支持允许租户/能力、轮换与撤销。
  - _Requirements: REQ-01, REQ-09_
  - _Acceptance: AC-01, AC-20, AC-21_
  - _Verification: Key 生命周期、资格和拒绝路径定向测试，先红后绿。_
  - _Boundary: 不改变 ApiCredential 或普通 service account 合同。_
- [x] T002 增加 sso_sync 只读外部身份解析端口，核验连接、外部租户/用户、目录与本地映射资格，不自动开通。
  - _Requirements: REQ-02, REQ-03_
  - _Acceptance: AC-02, AC-03, AC-05, AC-06_
  - _Verification: 映射唯一性、停用与失效、管理员身份测试。_
  - _Boundary: 不回退 Token 用户、默认租户或显示姓名。_
- [x] T003 统一 SG 式请求用户依赖，Bearer Key 与必填 Query 身份分离，安装/复原可信租户和权限上下文。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-10_
  - _Acceptance: AC-01, AC-02, AC-04, AC-05, AC-06, AC-18_
  - _Verification: ASGI 准入与上下文隔离集成测试。_
  - _Depends: T001, T002_

## W2：管理接口

- [ ] T004 超管 Key 控制面与独立昆联业务路由装配，核对全局中间件及错误处理，不修改普通 v2 鉴权。
  - _Requirements: REQ-01, REQ-10_
  - _Acceptance: AC-01, AC-18, AC-20_
  - _Verification: 正式路由注册、无凭据拒绝、跨入口 Key 拒绝测试。_
  - _Depends: T003_
- [ ] T005 复用管理服务提供列表、详情、创建、元数据与版本读写/选择，必要编排下沉；请求字段白名单与图脱敏。
  - _Requirements: REQ-04, REQ-05_
  - _Acceptance: AC-07, AC-08, AC-09_
  - _Verification: 普通用户/租户管理员双租户管理闭环、修订冲突与创建重试测试。_
  - _Depends: T003_
- [ ] T006 发布及下线接现有工作流服务，禁止元数据绕过发布，返回发布定义。
  - _Requirements: REQ-06_
  - _Acceptance: AC-10, AC-11_
  - _Verification: 发布/下线事务与输入输出定义测试。_
  - _Depends: T005_

## W3：运行与授权

- [ ] T007 正式运行身份/任务装配，复用既有执行器、冻结、交互、取消；将正式可用性与 Mock 登记解耦，支持省略版本选择当前版本的稳定幂等。
  - _Requirements: REQ-07, REQ-09_
  - _Acceptance: AC-11, AC-12, AC-13, AC-14, AC-21, AC-22_
  - _Verification: 同版本运行、人工输入恢复、取消、独立 Worker、撤销与轮换集成测试。_
  - _Depends: T004, T006_
  - _Boundary: 不新增任意图引擎；不把有限文本候选冒充完整 Workflow 支持。_
- [ ] T008 授权接口复用 F048 及候选适配，真实目标身份解析，持久原操作回执替代内存回执。
  - _Requirements: REQ-08_
  - _Acceptance: AC-15, AC-16_
  - _Verification: 授权后实际访问、修订/投影待确认、重启查回和保护来源拒绝。_
  - _Depends: T003, T005_
- [ ] T009 Key/操作人审计、资格变更下的推进阻断及受控处置、现有限流衔接，记录具体保留策略与限制。
  - _Requirements: REQ-09, REQ-10_
  - _Acceptance: AC-14, AC-17, AC-21, AC-22_
  - _Verification: 秘密不落日志/消息、审计故障和失权边界测试。_
  - _Depends: T007, T008_

## W4：交付

- [ ] T010 接口说明、ABCDE 示例及相关回归/必要 E2E；记录未运行的真实昆联、MySQL/DM8、权限与 Broker 验证，不部署。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08, REQ-09, REQ-10_
  - _Acceptance: AC-01～AC-22_
  - _Verification: 定向与相邻回归、架构检查、调用说明核对、特性代码审查。_
  - _Depends: T004, T005, T006, T007, T008, T009_

## W5：删除客户端请求键（用户已授权）

- [x] T011 五个正式写接口移除Idempotency-Key依赖，每次HTTP生成内部操作引用，保留现有内部事务/状态/Worker保护；同步规格、设计、调用说明与回归。
  - _Requirements: REQ-05, REQ-07, REQ-08, REQ-10_
  - _Acceptance: AC-12, AC-16, AC-23_
  - _Verification: 先RED后GREEN证明五接口无header可调用、重复旧header不复用内部操作引用、OpenAPI不再声明该参数；相邻回归。_
  - _Boundary: 不删候选接口的旧合同，不改If-Match或授权修订，不承诺跨HTTP安全重试。_

## W6：公开身份改为登录账号（用户已授权）

- [x] T012 正式Query只接收user_account；User Owner精确唯一账号/有效租户发现，可信绑定反查；先Key认证再账号解析，最后Key范围复核；保留内部RunSubject/授权/审计映射，拒旧Query，更新测试与文档。
  - _Requirements: REQ-01, REQ-02, REQ-03, REQ-09, REQ-10_
  - _Acceptance: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-14, AC-18, AC-24_
  - _Verification: 先RED后GREEN覆盖无/重名/停用/无或多租户账号、越范围、旧参数拒绝、公开OpenAPI；相邻Worker与授权回归保持内部契约。_
  - _Boundary: 不移除租户隔离，不更改Key tenant_ids外部范围、授权subject_ref或候选API合同，不自动开通。_

## 本地实施检查点（2026-11-16）

本次限定目标为代码实现、隔离测试与交付记录，不含环境部署。该本地阶段已收口；下列未勾选项保留完整发布/真实环境的done condition，不能因此将真实验收冒记完成。后续环境验收应独立授权，不自动无限延长本地实施。

- T001～T003：本地完成，Key/身份/上下文有定向与拒绝路径证据。
- T004～T006：已接正式路由及管理/发布/下线/Schema，本地测试通过；完整权限运行时与双库闭环未验，因此不冒记最终验收。
- T007：正式核心图、交互、取消、身份重验与15秒有界补偿已接；独立Broker/Worker及完整节点/输入输出协议未验，保留未完成。
- T008：正式授权与SQL持久摘要回执已接；真实F048/OpenFGA、claim与ledger间崩溃的受控处置未闭合，保留未完成。
- T009：业务/控制面持久审计、Redis请求限流、可调时限、跨workflow用户行锁活跃配额及过期正式payload有界清理已实现；真实双库竞争、平台受控修复与真实运行时验收未完成。
- T010：api-guide/operations/e2e-checklist与本地验证已写，当前联合375 passed、2项因redis-server缺失跳过；真实环境与最终交付门未完成。

## 实际偏差记录

- 正式业务聚合在单个 kunlian_workflow_api 端点，不直接修改或挂载原候选端点，保留其测试兼容。
- 不迁入SG developer_token整模块；新增窄凭据元数据，身份上下文模式参考SG。
- 使用现有发布事实而非Mock登记受理运行；文本协议内核心图已扩展，不支持的平台节点与多输入输出等明确拒绝。
- 保留期控制查询有效期；新增正式过期终态payload有界清理，永久幂等墓碑保留。跨workflow并发限额以User行锁与当前读实现；SQLite只验证语义和SQL形状，真实双库竞争另验。
- 轮换可查询/取消旧run；原Key撤销后不再恢复其等待执行。真实rotate回归已消除fake resolver造成的虚假恢复证据。
- 版本详情脱敏后写回按同节点保留原SQL密码；正式非Mock详情补原图revision，避免无法保存或误覆盖。
