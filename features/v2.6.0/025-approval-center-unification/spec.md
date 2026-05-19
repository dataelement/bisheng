# Feature: F025-approval-center-unification（统一审批中心与旧审批链路收敛）

**关联 PRD**: [../../../docs/PRD/审批流程PRD/审批流程PRD.md](../../../docs/PRD/%E5%AE%A1%E6%89%B9%E6%B5%81%E7%A8%8BPRD/%E5%AE%A1%E6%89%B9%E6%B5%81%E7%A8%8BPRD.md) §1-§11
**优先级**: P0（主版本新增通用审批能力，覆盖菜单权限申请、频道订阅审批、知识空间加入/订阅审批）
**所属版本**: v2.6.0
**模块编码**: 沿用 181（`approval`，现有 `common/errcode/approval.py`），本 spec 会扩展错误码而不新开模块
**依赖**: F005（角色菜单与 `menu_approval_mode`）+ F011/F012/F013（多租户与租户隔离）+ F019（管理员视角审计字段复用）+ 现有 `approval/`、`message/`、`channel/`、`knowledge/` 模块

> **范围边界**
> - **本次纳入主版本**：审批中心核心域模型、审批管理页、我的审批、我的申请、异常流程列表、站内信提醒、菜单权限申请、频道订阅审批、知识空间加入/订阅审批。
> - **本次明确排除**：PRD §2.3.3 的知识空间创建审批、PRD §2.3.4 的知识空间文件发布审批、首钢分支差异化流程。
> - **本次同步移除**：历史“部门知识空间文件上传审批”能力；部门知识空间上传从本版本开始与普通知识空间一致，只校验 ReBAC 上传权限，不再经过 `approval_request` 或审批消息链路。

---

## 1. 概述与用户故事

**故事 A（申请人）**：
作为 **普通登录用户**，
我希望 **在没有菜单权限或需要他人同意的业务入口上提交审批申请，并持续查看进度、结果和失败原因**，
以便 **不再被“能不能做、做到哪一步、该找谁”这类信息割裂住**。

**故事 B（审批人）**：
作为 **被分配到审批节点的审批人**，
我希望 **在统一的“我的审批”里按节点处理同意/拒绝，并看到结构化业务详情和历史意见**，
以便 **不需要再通过零散站内信或业务页面反推审批上下文**。

**故事 C（管理员）**：
作为 **租户管理员或系统管理员**，
我希望 **通过预置场景、条件分支、顺序节点和异常处理来管理审批流程**，
以便 **把审批规则配置成租户级能力，而不是把审批写死在每个业务按钮里**。

**故事 D（研发）**：
作为 **后端/前端研发**，
我希望 **业务模块只接 `ApprovalGate.request_or_pass()` 和场景 handler 协议，旧站内信审批链路统一迁入审批中心**，
以便 **后续新增审批场景时只做场景注册、payload 组装和 handler 实现，而不再复制“消息 + 状态 + 重试”样板逻辑**。

---

## 2. 验收标准

### 2.1 场景注册与审批网关

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 管理员 | 打开审批管理并新增场景 | 场景名称只能从后端预置目录选择；本次至少提供 `menu_access_request`、`channel_subscribe_request`、`knowledge_space_subscribe_request` 三个场景；同租户内 `scenario_code` 唯一 |
| AC-02 | 业务接口 | 某场景未启用时调用 `ApprovalGate.request_or_pass()` | 创建 `approval_instance`，实例进入 `exception`，异常类型为 `scenario_disabled`；不创建 `approval_task` / `approval_outbox`；管理员在异常流程列表中决定后续处理 |
| AC-03 | 业务接口 | 场景已启用且命中“无需审批”分支 | 创建 `approval_instance`，状态依次进入 `approved -> executing -> executed`；不创建审批任务；写 `approval.route.pass` 审计 |
| AC-04 | 业务接口 | 场景已启用且命中审批流程分支 | 创建 `approval_instance` 和第一个节点的 `approval_task`；返回 `PENDING`；审批人收到站内信提醒；业务动作暂停 |
| AC-05 | 业务接口 | 同申请人 + 同 `scenario_code` + 同 `business_key` 已有 `pending` / `exception` / `execute_failed` 实例时再次提交 | 不创建新实例；返回已有实例 ID 和 `PENDING`/`EXCEPTION` 语义；前端可跳转已有详情 |

### 2.2 流程配置与版本化

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-06 | 管理员 | 在某场景下配置条件分支并调整上下顺序 | 后端按列表顺序自上而下匹配，命中第一条即停止；无“默认分支”保留字 |
| AC-07 | 管理员 | 某分支选择“进入审批流程”并配置多个顺序节点 | 节点按顺序流转；前一节点通过后才生成下一节点任务 |
| AC-08 | 管理员 | 在单节点中添加多个审批人来源并配置“或签” | 任一审批人同意即通过该节点；其余未处理任务变为 `skipped` |
| AC-09 | 管理员 | 在单节点中添加多个审批人来源并配置“会签” | 所有审批人都同意后才通过该节点；任一人拒绝则实例进入 `rejected` |
| AC-10 | 管理员 | 修改分支、流程或节点配置 | 生成新流程版本；已发起实例继续使用其创建时快照；新实例使用最新 active 版本 |

### 2.3 审批处理与异常

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-11 | 审批人 | 在待处理任务上点击同意，且不是最后节点 | 当前任务状态变 `approved`；生成下一节点任务；实例保持 `pending` |
| AC-12 | 审批人 | 在最后节点点击同意 | 实例进入 `approved` 后创建 `approval_outbox`；业务 handler 执行成功则实例进入 `executed`，失败则进入 `execute_failed` |
| AC-13 | 审批人 | 点击拒绝并填写原因 | 当前任务状态变 `rejected`；实例进入 `rejected`；后续节点不生成；申请人收到拒绝提醒 |
| AC-14 | 申请人 | 对 `pending` 实例执行撤回 | 实例进入 `withdrawn`；所有 `pending` 任务改 `cancelled`；审批人收到撤回提醒 |
| AC-15 | 系统 | 场景已启用但所有条件分支均未命中 | 实例进入 `exception`，异常类型 `route_missing`；不生成任务；管理员在异常流程列表中可重新匹配或指定流程 |
| AC-16 | 系统 | 某节点解析审批人为空 | 实例进入 `exception`，异常类型 `approver_empty`；管理员可手动指定审批人、使用兜底人、跳过节点或取消审批 |
| AC-17 | 管理员 | 对 `scenario_disabled` 异常执行处理 | 可启用场景后重试路由、手动指定流程继续，或取消审批；处理过程写审计和异常处理日志 |
| AC-18 | 管理员 | 对 `execute_failed` 异常执行重试 | 成功则实例进入 `executed`；失败则保留 `execute_failed` 并累计重试次数；审批结论不回退 |
| AC-19 | 管理员 | 对任意异常实例执行取消 | 实例进入 `cancelled`；业务 handler 不再重试；必须填写原因并写审计 |

### 2.4 用户端页面与权限

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-20 | 审批人 | 打开“我的审批” | 只看到分配给自己或自己已处理过的审批任务；默认进入待我审批；可查看详情并在本人待办上操作 |
| AC-21 | 申请人 | 打开“我的申请” | 只看到自己发起的审批实例；可查看详情；仅 `pending` 可撤回，仅 `rejected` 可重新提交 |
| AC-22 | 管理员 | 打开“审批管理” | 可管理本租户场景、分支、流程、异常；普通用户不可访问 |
| AC-23 | 任意用户 | 通过站内信点击审批消息 | 只做跳转和定位，不提供消息内快捷审批；审批详情接口仍做权限校验，不能绕过 |

### 2.5 必做业务场景

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-24 | 普通用户 | 在 `menu_approval_mode=true` 且无菜单权限时进入占位页并提交申请 | 创建 `menu_access_request` 审批；审批通过后只给申请人写个人菜单授权，不修改角色菜单；父级依赖菜单自动补齐 |
| AC-25 | 审批人 | 在菜单权限申请已执行成功的详情页点击“撤回授权” | 撤销对应个人菜单授权；审批实例仍保持审批通过历史，在申请详情中增加“授权已撤回”处理说明 |
| AC-26 | 频道订阅用户 | 订阅 `review` 类型频道 | 不再直接通过 `send_generic_approval` 创建审批消息；改为 `channel_subscribe_request` 进入审批中心；通过后激活成员关系，拒绝后置为 `rejected` |
| AC-27 | 知识空间订阅用户 | 申请加入需要审批的知识空间 | 不再以旧 `request_knowledge_space` 消息为事实来源；改为 `knowledge_space_subscribe_request` 进入审批中心；通过后复用现有成员激活 + ReBAC 授权逻辑 |

### 2.6 审计与多租户

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-28 | 系统/用户/管理员 | 发起申请、审批通过/拒绝、撤回、分支直通、执行成功/失败、异常处理、流程配置变更、场景启停变更 | 同时写 `approval_action_log` 和 `auditlog`；`auditlog.action` 使用 PRD §9.1 的 `approval.*` 枚举 |
| AC-29 | 多租户环境 | 查询实例、任务、异常、消息、审计 | 严格按 `tenant_id` 隔离；申请人只能看自己实例，审批人只能看自己的任务/已处理任务，管理员仅能看本租户全部数据 |
| AC-30 | 运维/研发 | 在 MySQL 与达梦两种数据库上初始化或升级审批中心表结构 | 审批中心新增表、索引、默认值、`update_time` 自动更新时间、JSON/CLOB 序列化在两种数据库上都可正常工作；禁止引入仅 MySQL 可用的 `information_schema`、原生 JSON 函数或 `ON UPDATE CURRENT_TIMESTAMP` 假设 |
| AC-31 | 部门知识空间上传用户 | 向部门知识空间上传文件 | 与普通知识空间上传链路保持一致；后端仅校验 ReBAC 上传权限；不创建 `approval_request`、审批消息或审批中心实例 |
| AC-32 | 普通用户 | `menu_approval_mode=false` 且用户无菜单权限 | 维持现有菜单可见性逻辑：不展示无权限菜单，也不展示菜单权限申请入口、占位页或跳转入口 |

---

## 3. 边界情况

- 场景未启用：默认创建异常实例 `scenario_disabled`，不能静默通过，也不能回退原业务直通。
- 场景已启用但管理员未配置任何分支：视同 `route_missing`，不做隐式默认通过。
- 节点审批人来源解析出重复用户：合并去重后只保留一条待办任务。
- 审批人离职/停用：系统优先重新解析当前节点审批人；仍为空则进入 `approver_empty` 异常。
- 业务状态变化导致审批通过后再次校验失败：审批实例进入 `execute_failed`，由管理员重试或人工完成，不回滚审批结论。
- 菜单审批模式关闭：前端不展示无权限菜单与申请入口；若用户绕过前端直接调用菜单申请接口，后端按权限/开关校验拒绝请求，不创建审批实例。
- 部门知识空间上传：即使历史环境里存在旧审批表或旧消息记录，新上传请求也不得再落审批事实，只能按上传权限直接放行或拒绝。
- **不支持**：本 Feature 不提供拖拽式流程设计器、不支持嵌套子流程、不支持首钢分支专用知识空间创建/文件发布流程。

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 通用审批中心落表方式 | A: 扩展现有 `approval_request` / B: 新建通用中心表，并下线历史部门知识空间上传审批 | **B** | 现有 `approval_request` 强绑定部门知识空间上传字段，无法表达场景、分支、节点、异常、outbox 等通用能力；该历史审批能力本版本同步移除 |
| AD-02 | 场景目录来源 | A: 管理员自由录入场景编码和 handler / B: 研发预置场景目录，管理员只选择名称并配置启停、分支、流程 | **B** | 避免配置层写入技术字段，保证 handler、条件字段、审批人来源与代码能力一致 |
| AD-03 | 审批事实来源 | A: 站内信消息 / B: `approval_instance` + `approval_task` | **B** | 站内信只做提醒与跳转，审批进度和权限校验必须以审批中心数据为准 |
| AD-04 | 业务执行时机 | A: 最后节点通过后同步执行业务 / B: 通过后写 `approval_outbox`，由异步执行器处理并支持重试 | **B** | PRD 明确要求执行失败可重试、可人工完成、可留痕，必须解耦审批结论与业务补偿 |
| AD-05 | 流程变更对已发起实例的影响 | A: 立即影响运行中实例 / B: 创建实例时快照版本，后续配置只影响新申请 | **B** | 与 PRD §7.8 一致，避免运行中实例因配置变更发生语义漂移 |
| AD-06 | 旧消息审批链路迁移方式 | A: 新旧并行长期保留 / B: 业务入口改走 `ApprovalGate`，旧 message handler 仅做历史兼容跳转 | **B** | 避免双事实源；频道/知识空间订阅必须迁入审批中心，旧入口只做存量兼容 |
| AD-07 | 菜单权限授权模型 | A: 直接改角色菜单 / B: 新增个人菜单授权表，与角色菜单做并集 | **B** | PRD 明确“审批通过只给申请人增加个人菜单授权，不修改角色菜单” |
| AD-08 | 场景未启用时的默认行为 | A: 静默 PASS 回原业务 / B: 创建 `scenario_disabled` 异常实例，交管理员处理 | **B** | 业务不能绕开审批配置直接放行；“未启用”本身也是可追踪、可处置的审批异常 |
| AD-09 | 异常处理入口 | A: 在业务页内各自处理 / B: 审批管理统一异常流程列表 | **B** | `scenario_disabled`、`route_missing`、`approver_empty`、`execute_failed` 是跨场景共性，统一后台处理最稳 |
| AD-10 | 审批中心数据库方言策略 | A: 默认按 MySQL 设计，达梦后补 / B: 复用仓库现有 `dialect_helpers`，新增表和迁移从一开始按 MySQL + 达梦双库约束设计 | **B** | 仓库已落地达梦兼容基础设施，审批中心不能重新引入 MySQL 专属类型、默认值或元数据查询方式 |

---

## 5. 数据库 & Domain 模型

### 5.1 新增表

| 表 | 说明 |
|----|------|
| `approval_scenario` | 租户下某个预置场景的启停与展示配置 |
| `approval_route_rule` | 场景下的条件分支规则，按 `sort_order` 顺序匹配 |
| `approval_flow_definition` | 流程定义头，按场景归属 |
| `approval_flow_version` | 流程版本快照，保存完整 DSL JSON |
| `approval_node_definition` | 某流程版本内的顺序节点定义 |
| `approval_instance` | 一次审批申请实例，承载 `scenario_code`、`business_key`、payload 快照、当前状态 |
| `approval_task` | 分配给审批人的节点待办，支持 `pending/approved/rejected/skipped/cancelled` |
| `approval_action_log` | 审批详情时间线，用于“谁在何时做了什么” |
| `approval_exception` | `scenario_disabled`、`route_missing`、`approver_empty`、`execute_failed` 异常记录 |
| `approval_outbox` | 审批通过后的业务执行队列，支持状态、重试次数、错误摘要 |
| `user_menu_access` | 用户级菜单授权表，保存审批授予与撤回状态 |

### 5.2 历史审批链路处理

| 对象 | 策略 |
|------|------|
| `approval_request` | 本版本停止承载任何在线业务审批事实；部门知识空间文件上传改为直接 ReBAC 校验，不再创建新记录 |
| 部门知识空间上传审批消息 | 本版本停止创建新消息审批事实；历史记录如需保留，只读不续写 |

### 5.3 核心字段设计

```python
class ApprovalInstance(SQLModelSerializable, table=True):
    __tablename__ = "approval_instance"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: Optional[int] = Field(default=None, index=True)
    scenario_code: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    scenario_name: str = Field(sa_column=Column(String(255), nullable=False))
    handler_key: str = Field(sa_column=Column(String(128), nullable=False))
    business_key: str = Field(sa_column=Column(String(255), nullable=False, index=True))
    business_resource_type: str = Field(sa_column=Column(String(64), nullable=False))
    business_resource_id: str = Field(sa_column=Column(String(128), nullable=False))
    business_name: str = Field(sa_column=Column(String(255), nullable=False))
    applicant_user_id: int = Field(index=True)
    applicant_user_name: str = Field(sa_column=Column(String(255), nullable=False))
    applicant_department_id: Optional[int] = Field(default=None, index=True)
    flow_version_id: Optional[int] = Field(default=None, index=True)
    route_rule_id: Optional[int] = Field(default=None, index=True)
    status: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    payload_snapshot: Dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    detail_snapshot: Dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    current_node_name: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    latest_approver_user_id: Optional[int] = Field(default=None, index=True)
    create_time: Optional[datetime] = Field(sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")))
    update_time: Optional[datetime] = Field(sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT))
```

```python
class ApprovalTask(SQLModelSerializable, table=True):
    __tablename__ = "approval_task"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: Optional[int] = Field(default=None, index=True)
    instance_id: int = Field(index=True)
    flow_version_id: int = Field(index=True)
    node_code: str = Field(sa_column=Column(String(64), nullable=False))
    node_name: str = Field(sa_column=Column(String(255), nullable=False))
    node_order: int = Field(default=0, index=True)
    approver_user_id: int = Field(index=True)
    approver_source_type: str = Field(sa_column=Column(String(64), nullable=False))
    node_mode: str = Field(sa_column=Column(String(16), nullable=False))
    status: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    comment: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    acted_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
```

### 5.4 Domain Schema / DTO

- `ApprovalGateRequest`
- `ApprovalGateResult`
- `ApprovalScenarioPreset`
- `ApprovalScenarioConfigReq/Resp`
- `ApprovalRouteRuleReq/Resp`
- `ApprovalFlowVersionResp`
- `ApprovalInstanceListResp`
- `ApprovalTaskDecisionReq`
- `ApprovalExceptionActionReq`
- `MenuAccessApplyReq`
- `UserMenuAccessResp`

### 5.5 双库设计约束（MySQL + 达梦）

- 审批中心新增模型继续复用 `bisheng.core.database.dialect_helpers`，其中 JSON 类字段统一使用 `JsonType`，避免直接声明 MySQL 原生 `JSON`。
- `update_time` 统一使用 `UPDATE_TIME_SERVER_DEFAULT`，不能在审批中心模型或迁移里手写 MySQL 专属 `ON UPDATE CURRENT_TIMESTAMP`。
- 迁移脚本与建表守卫统一走 SQLAlchemy `inspect()` / `dialect_helpers`，不得直接依赖 `information_schema`。
- 审批中心的查询与筛选不得依赖 MySQL 原生 JSON 函数；若后续需要基于 JSON 字段做过滤，必须同时提供达梦兼容分支。
- `payload_snapshot`、`detail_snapshot`、流程 DSL 快照等结构化字段，在达梦中按 `CLOB + Python 序列化` 语义处理，功能表现应与 MySQL 保持一致。

### 5.6 双库风险扫描结论（本 Feature 必须遵守）

- **风险 1：把可检索字段放进 JSON 快照**。`payload_snapshot`、`detail_snapshot`、流程 DSL 只用于详情展示、审计回放和 handler 上下文，不承担列表筛选、排序、唯一性判断；凡是“我的审批/我的申请/异常列表/去重”需要用到的字段，必须落成显式列。
- **风险 2：迁移里偷写 MySQL 时间戳语义**。审批中心所有 `update_time` 字段都走 `UPDATE_TIME_SERVER_DEFAULT` 或其等价 helper，不在 alembic 中直接写 `onupdate=...` 或 `ON UPDATE CURRENT_TIMESTAMP`。
- **风险 3：重复提交幂等依赖复杂唯一索引**。`AC-05` 的重复申请判定基于事务内查询 + 状态判断实现，不依赖跨状态、跨空值语义复杂的数据库唯一索引，以避免 MySQL / 达梦行为漂移。
- **风险 4：消息或审批人查询回退到 JSON SQL**。审批待办查询统一以 `approval_task` 一人一行为准，不额外引入“审批人列表 JSON”做待办过滤；消息跳转只做定位，不承担审批事实检索。
- **风险 5：表存在性或兼容守卫使用 MySQL 元数据 SQL**。审批中心 migration、启动检查、异常修复脚本若需要做表/列/索引探测，统一复用 SQLAlchemy `inspect()` 或仓库现有 helper。

### 5.7 Repository 分层约束（本 Feature 必须遵守）

- 审批中心后端实现默认走 `api -> service -> repository -> database`，不再以 DAO 作为新功能首选数据访问层。
- `ApprovalGate`、`ApprovalCenterService`、`ApprovalScenarioAdminService`、`ApprovalExceptionService`、`ApprovalOutboxService` 统一通过 repository 访问实例、任务、异常、流程配置、outbox、用户菜单授权等数据。
- `Endpoint` 不直接访问 `database/models/` 或手写 ORM 查询；`Service` 不直接持有底层 session 拼装查询。
- 若为兼容历史记录查询需要临时读取 `approval_request` 或旧消息审批链路，必须限制在迁移/只读适配边界内，不扩散到审批中心新主链路。
- 部门知识空间文件上传不接入审批中心；上传入口保持普通知识空间同构，只复用现有 ReBAC 上传权限判断。

---

## 6. API 契约

### 6.1 用户端 API

| Method | Path | 描述 | 认证 |
|--------|------|------|------|
| GET | `/api/v1/approval/my-tasks` | 我的审批列表 | 是 |
| GET | `/api/v1/approval/my-tasks/{task_id}` | 审批详情（按 task 定位） | 是 |
| POST | `/api/v1/approval/tasks/{task_id}/decision` | 同意/拒绝审批任务 | 是 |
| GET | `/api/v1/approval/my-requests` | 我的申请列表 | 是 |
| GET | `/api/v1/approval/instances/{instance_id}` | 审批实例详情 | 是 |
| POST | `/api/v1/approval/instances/{instance_id}/withdraw` | 撤回审批申请 | 是 |
| POST | `/api/v1/approval/instances/{instance_id}/resubmit` | 基于旧申请重新提交 | 是 |
| POST | `/api/v1/approval/menu-access/apply` | 菜单权限申请入口 | 是 |
| POST | `/api/v1/approval/menu-access/{instance_id}/revoke-grant` | 菜单授权撤回 | 是 |

### 6.2 管理端 API

| Method | Path | 描述 | 认证 |
|--------|------|------|------|
| GET | `/api/v1/approval/admin/scenario-presets` | 预置场景目录 | 管理员 |
| GET | `/api/v1/approval/admin/scenarios` | 已配置场景列表 | 管理员 |
| POST | `/api/v1/approval/admin/scenarios` | 新增场景配置 | 管理员 |
| PUT | `/api/v1/approval/admin/scenarios/{scenario_id}` | 更新场景启停/展示配置 | 管理员 |
| GET | `/api/v1/approval/admin/scenarios/{scenario_id}/routes` | 条件分支列表 | 管理员 |
| POST | `/api/v1/approval/admin/scenarios/{scenario_id}/routes` | 新增条件分支 | 管理员 |
| PUT | `/api/v1/approval/admin/routes/{route_id}` | 更新分支 | 管理员 |
| POST | `/api/v1/approval/admin/flows` | 创建流程定义/新版本 | 管理员 |
| GET | `/api/v1/approval/admin/flows/{flow_id}/versions/{version_id}` | 流程版本预览 | 管理员 |
| GET | `/api/v1/approval/admin/exceptions` | 异常流程列表 | 管理员 |
| POST | `/api/v1/approval/admin/exceptions/{exception_id}/retry` | 重试执行 / 重新路由 | 管理员 |
| POST | `/api/v1/approval/admin/exceptions/{exception_id}/assign-approver` | 指定审批人继续 | 管理员 |
| POST | `/api/v1/approval/admin/exceptions/{exception_id}/assign-flow` | 指定流程继续 | 管理员 |
| POST | `/api/v1/approval/admin/exceptions/{exception_id}/skip-node` | 跳过节点继续 | 管理员 |
| POST | `/api/v1/approval/admin/exceptions/{exception_id}/cancel` | 取消异常审批 | 管理员 |

### 6.3 业务接入 API 变更

| 业务 | 现状 | F025 后 |
|------|------|---------|
| 菜单权限申请 | 前端仅有空白占位页，无统一申请接口 | 新增 `POST /api/v1/approval/menu-access/apply`，占位页提交 `menu_key/menu_name/reason` |
| 频道订阅 | `channel_service.subscribe_channel()` 直接改成员状态并发 `send_generic_approval` | 调 `ApprovalGate.request_or_pass()`；PENDING 时保持业务暂停，APPROVED 后由 handler 激活成员 |
| 知识空间加入/订阅 | 旧 `request_knowledge_space` 消息审批 | 改调 `ApprovalGate.request_or_pass()`；审批通过后复用现有成员激活与权限同步 |

### 6.4 错误码表

| HTTP Status | MMMEE Code | Error Class | 场景 | 关联 AC |
|-------------|------------|-------------|------|---------|
| 200 (body) | 18100 | `ApprovalRequestNotFoundError` | 实例/任务不存在 | AC-19, AC-20 |
| 200 (body) | 18101 | `ApprovalRequestPermissionDeniedError` | 无权限查看或处理 | AC-19~22 |
| 200 (body) | 18102 | `ApprovalRequestAlreadyProcessedError` | 任务已处理/实例不可重复操作 | AC-11~18 |
| 200 (body) | 18103 | `ApprovalRejectReasonRequiredError` | 驳回/取消时未填必填原因 | AC-13, AC-18 |
| 200 (body) | 18105 | `ApprovalScenarioDuplicateError` | 场景重复创建 | AC-01 |
| 200 (body) | 18106 | `ApprovalScenarioDisabledError` | 场景未启用（仅网关内部落异常，不直返前端失败） | AC-02, AC-17 |
| 200 (body) | 18107 | `ApprovalRouteNotMatchedError` | 分支未命中（仅网关内部抛转 exception，不直返前端） | AC-15 |
| 200 (body) | 18108 | `ApprovalApproverEmptyError` | 审批人解析为空（仅网关内部抛转 exception） | AC-16 |
| 200 (body) | 18109 | `ApprovalDuplicatePendingError` | 存在重复申请 | AC-05 |
| 200 (body) | 18110 | `ApprovalGrantNotRevokableError` | 授权撤回条件不满足 | AC-25 |

---

## 7. Service 层逻辑

> F025 的后端主链路遵循 `api -> service -> repository -> database`。本节列出的 service 不直接操作 DAO / session，统一通过 repository 编排数据访问。

### 7.1 核心服务

| 服务 | 文件 | 职责 |
|------|------|------|
| `ApprovalGate` | `approval/domain/services/approval_gate.py` | 场景启停判断、重复申请检查、分支匹配、审批实例创建、PASS/PENDING/EXCEPTION 返回 |
| `ApprovalCenterService` | `approval/domain/services/approval_center_service.py` | 审批任务处理、撤回、重新提交、详情聚合 |
| `ApprovalScenarioAdminService` | `approval/domain/services/approval_scenario_admin_service.py` | 场景/分支/流程/节点配置管理与版本化 |
| `ApprovalExceptionService` | `approval/domain/services/approval_exception_service.py` | scenario_disabled / route_missing / approver_empty / execute_failed 统一处理 |
| `ApprovalOutboxService` | `approval/domain/services/approval_outbox_service.py` | 审批通过后异步执行业务 handler、失败重试、人工完成标记 |
| `ApprovalRegistry` | `approval/domain/services/approval_registry.py` | 预置场景、条件字段、审批人来源、handler 注册 |
| `UserMenuAccessService` | `approval/domain/services/user_menu_access_service.py` | 菜单个人授权、依赖菜单补齐、撤回授权 |

### 7.1A 核心 Repository

| Repository | 文件 | 职责 |
|------------|------|------|
| `ApprovalScenarioRepository` | `approval/domain/repositories/approval_scenario_repository.py` | 场景、分支、流程定义、流程版本、节点配置读写 |
| `ApprovalInstanceRepository` | `approval/domain/repositories/approval_instance_repository.py` | 审批实例、审批任务、异常、action log、outbox 读写 |
| `UserMenuAccessRepository` | `approval/domain/repositories/user_menu_access_repository.py` | 用户菜单授权写入、查询、撤回 |
| `ApprovalQueryRepository` | `approval/domain/repositories/approval_query_repository.py` | 我的审批、我的申请、异常列表、详情聚合查询 |

### 7.2 Handler 协议

> 旧 `message.domain.services.approval_handler.ApprovalHandler` 仅有 `get_action_code()/on_approved()/on_rejected()`，无法承载新中心所需的标题、详情、审批人解析和撤回逻辑。F025 新增统一 handler 基类，旧 handler 逐步适配。

```python
class ApprovalScenarioHandler(ABC):
    scenario_code: str

    @abstractmethod
    async def validate(self, req: ApprovalGateRequest, login_user: UserPayload) -> None: ...

    @abstractmethod
    async def build_title(self, req: ApprovalGateRequest) -> str: ...

    @abstractmethod
    async def build_detail(self, req: ApprovalGateRequest) -> dict: ...

    @abstractmethod
    async def build_business_link(self, req: ApprovalGateRequest) -> dict: ...

    @abstractmethod
    async def resolve_approvers(self, node_config: dict, req: ApprovalGateRequest) -> list[int]: ...

    @abstractmethod
    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict: ...

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None: ...

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None: ...
```

### 7.3 业务 handler 映射

| 场景 | handler | 说明 |
|------|---------|------|
| `menu_access_request` | `MenuAccessApprovalHandler` | 新增，负责菜单申请校验、详情、个人菜单授权、授权撤回 |
| `channel_subscribe_request` | `ChannelSubscribeScenarioHandler` | 复用并扩展现有 `ChannelSubscribeApprovalHandler` 的激活/拒绝逻辑 |
| `knowledge_space_subscribe_request` | `KnowledgeSpaceSubscribeScenarioHandler` | 复用并扩展现有 `KnowledgeSpaceSubscribeHandler` 的成员激活与权限同步逻辑 |

### 7.4 权限检查

- 用户端列表和详情通过“实例申请人 / 当前审批人 / 历史审批人 / 管理员”四类准入判断。
- 管理端场景配置、异常处理要求 `get_tenant_admin_user` 或系统管理员。
- 菜单授权撤回仅允许当前审批人、历史审批人、管理员执行。
- 审批通过后的业务动作仍调用原业务权限/存在性校验，审批通过不等于绕过业务安全检查。

### 7.5 Worker / Outbox

- 新增 `worker/approval/tasks.py`
- 任务：
  - `execute_approval_outbox`
  - `retry_approval_outbox`
  - `rebind_approval_approver_on_user_disabled`
- 所有任务参数必须带 `tenant_id`，执行前恢复 `current_tenant_id`

---

## 8. 前端设计

### 8.1 Client 前端（工作台 / 前台审批模块）

> 路径：`src/frontend/client/src/`
> 路由基础路径：`/workspace`
> 技术约束：沿用 Client 现有约定，使用 `~/api/*`、`useLocalize()`、Recoil/store、现有 `Dialog`/`Tabs`/`DropdownMenu` 组件体系；**不要**引入 Platform 的 `controllers/API`、Zustand 或 `useTranslation()+t()` 方案。

PRD §5 的“我的审批”“我的申请”“消息提醒”都属于工作台前台能力，应落在 Client 项目，而不是 Platform。

**入口归属**

- `我的审批`、`我的申请`、`消息提醒` 入口挂在 Client 工作台左下角用户菜单。
- 现有 [UserPopMenu.tsx](/Users/zhangguoqing/works/bisheng/src/frontend/client/src/layouts/UserPopMenu.tsx:1) 已承载“消息提醒”入口；F025 在同一菜单体系内新增“我的审批”“我的申请”入口，交互与消息提醒保持一致。
- 现有 [NotificationsDialog.tsx](/Users/zhangguoqing/works/bisheng/src/frontend/client/src/components/NotificationsDialog.tsx:1) 已有审批消息和 `decideApprovalRequestApi` 基础；F025 应在此基础上把“提醒入口”与“审批事实详情”解耦，而不是另起一套消息中心。

**推荐实现形态**

优先使用“工作台用户菜单 -> 弹窗/抽屉 -> 左列表 + 右详情”的形态，对齐 PRD 草图，而不是新开一个完整独立主页面。

组件树：

```text
client approval module
├── layouts/UserPopMenu.tsx                  # 新增“我的审批”“我的申请”入口
├── components/NotificationsDialog.tsx       # 继续承担消息提醒入口，不承载审批事实真相
├── components/approval/
│   ├── MyApprovalsDialog.tsx                # 我的审批弹窗
│   ├── MyApplicationsDialog.tsx             # 我的申请弹窗
│   ├── ApprovalDetailPanel.tsx              # 右侧详情
│   ├── ApprovalListCard.tsx                 # 列表卡片
│   ├── ApprovalTimeline.tsx                 # 审批进度/处理说明
│   ├── ApprovalDecisionDialog.tsx           # 同意/拒绝填写意见
│   └── RevokeMenuGrantDialog.tsx            # 撤回授权（二次确认）
├── api/approval.ts                          # 扩展为统一审批中心 API
└── hooks/queries/approval/                  # 如需要，新增前台审批查询 hooks
```

**菜单占位页**

- `menu_approval_mode` 相关占位入口属于 Client 工作台。
- 只有 `menu_approval_mode=true` 时，前台才展示对应“无权限/待申请”页面与“提交申请”入口。
- `menu_approval_mode=false` 时，维持现有逻辑：无权限菜单不展示，也没有申请入口、占位页和审批提示。
- Platform 里的 [MenuPermissionPlaceholder.tsx](/Users/zhangguoqing/works/bisheng/src/frontend/platform/src/pages/MenuPermissionPlaceholder.tsx:1) 仅覆盖后台 `/admin` 路由占位，不应承担工作台“我的审批/我的申请”模块。

**Client API 封装**

- 扩展 [src/frontend/client/src/api/approval.ts](/Users/zhangguoqing/works/bisheng/src/frontend/client/src/api/approval.ts:1)
- 新增：
  - `listMyApprovalTasksApi`
  - `getApprovalTaskDetailApi`
  - `decideApprovalTaskApi`
  - `listMyApprovalInstancesApi`
  - `getApprovalInstanceDetailApi`
  - `withdrawApprovalInstanceApi`
  - `resubmitApprovalInstanceApi`
  - `applyMenuAccessApi`
  - `revokeMenuGrantApi`
- 频道订阅、知识空间加入等前台业务入口分别在 `~/api/channels.ts`、`~/api/knowledge.ts` 接审批返回态，不要从 Platform 调接口。

**Client 路由与状态**

- F025 不强制新增 `/approval` 独立路由。
- 若需要 URL 深链，建议采用 query 参数或 `message_id / instance_id` 方式打开对应弹窗并聚焦详情，复用现有 `useNotificationsFromUrl()` 模式。
- 列表状态、筛选、选中详情可在组件内状态或 hooks 中维护；遵循 Client 既有 Recoil / hooks 模式。

### 8.2 Platform 前端（审批管理 / 异常流程）

> 路径：`src/frontend/platform/src/`
> 技术约束：沿用 Platform 现有约定，使用 `@/controllers/API/*`、`useTranslation()`、`bs-ui` 组件和页面级目录结构；**不要**混入 Client 的 `~/api` 和 `useLocalize()` 方案。

PRD §5.4 的“审批管理”“异常流程列表”属于管理后台能力，应落在 Platform 项目。

**页面归属**

- 放在管理后台菜单下，作为独立审批模块页面。
- 推荐路由形态：
  - `/approval` 或 `/sys?tab=approval`
- 考虑现有 Platform 后台结构，若希望减少一级菜单改动，也可挂在 `SystemPage` 下作为新 Tab，但应保持“流程管理 / 异常流程列表”两个清晰分区。

组件树：

```text
platform approval admin
├── pages/ApprovalPage/
│   ├── index.tsx
│   ├── components/
│   │   ├── ScenarioList.tsx
│   │   ├── ScenarioEditorDialog.tsx
│   │   ├── RouteRuleList.tsx
│   │   ├── FlowEditor.tsx
│   │   ├── NodeEditor.tsx
│   │   ├── FlowPreviewDialog.tsx
│   │   ├── ExceptionList.tsx
│   │   └── ExceptionActionDialog.tsx
├── controllers/API/approval.ts
└── public/locales/{lang}/bs.json
```

**Platform API 封装**

- 新建 `src/frontend/platform/src/controllers/API/approval.ts`
- 覆盖：
  - 场景目录
  - 场景新增/启停
  - 条件分支 CRUD / 排序 / 启停
  - 流程定义 / 版本预览
  - 异常列表 / 重试 / 指定审批人 / 指定流程 / 跳过 / 取消

**Platform i18n**

- 新增 `approvalAdmin.*`
- 扩展审计页筛选文案：
  - `audit.modules.approval`
  - `audit.actions.approval.*`

### 8.3 双端边界

- Client 只承担：我的审批、我的申请、消息提醒、业务入口发起申请、审批详情查看、审批人处理动作。
- Platform 只承担：审批场景、条件分支、审批流程、审批节点、异常流程列表、后台审计筛选。
- 两端共享同一后端审批中心数据，但**不共享前端实现代码**。
- 站内信只在 Client 侧呈现；Platform 不实现“消息提醒”入口。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/approval/domain/models/approval_scenario.py` | 场景、分支、流程、版本、节点 ORM 实体 |
| `src/backend/bisheng/approval/domain/models/approval_instance.py` | 实例、任务、异常、outbox、action_log ORM 实体 |
| `src/backend/bisheng/approval/domain/models/user_menu_access.py` | 用户菜单授权 ORM 实体 |
| `src/backend/bisheng/approval/domain/repositories/approval_scenario_repository.py` | 场景、分支、流程配置 repository |
| `src/backend/bisheng/approval/domain/repositories/approval_instance_repository.py` | 实例、任务、异常、outbox repository |
| `src/backend/bisheng/approval/domain/repositories/approval_query_repository.py` | 列表、详情、聚合查询 repository |
| `src/backend/bisheng/approval/domain/repositories/user_menu_access_repository.py` | 用户菜单授权 repository |
| `src/backend/bisheng/approval/domain/schemas/approval_center_schema.py` | 新中心 DTO |
| `src/backend/bisheng/approval/domain/services/approval_gate.py` | 审批网关 |
| `src/backend/bisheng/approval/domain/services/approval_center_service.py` | 用户端审批服务 |
| `src/backend/bisheng/approval/domain/services/approval_scenario_admin_service.py` | 管理端配置服务 |
| `src/backend/bisheng/approval/domain/services/approval_exception_service.py` | 异常处理服务 |
| `src/backend/bisheng/approval/domain/services/approval_outbox_service.py` | outbox 执行与重试 |
| `src/backend/bisheng/approval/domain/services/approval_registry.py` | 预置场景目录 |
| `src/backend/bisheng/approval/domain/services/menu_access_handler.py` | 菜单权限审批 handler |
| `src/backend/bisheng/approval/domain/services/channel_subscribe_scenario_handler.py` | 频道审批 handler 适配器 |
| `src/backend/bisheng/approval/domain/services/knowledge_space_subscribe_scenario_handler.py` | 知识空间审批 handler 适配器 |
| `src/backend/bisheng/approval/api/endpoints/approval_admin.py` | 管理端接口 |
| `src/backend/bisheng/approval/api/endpoints/approval_user.py` | 用户端接口 |
| `src/backend/bisheng/worker/approval/tasks.py` | outbox / 异常 worker 任务 |
| `src/backend/test/approval/test_approval_gate.py` | 审批网关单测 |
| `src/backend/test/approval/test_approval_flow_runtime.py` | 流程流转单测 |
| `src/backend/test/approval/test_approval_exception_service.py` | 异常处理单测 |
| `src/backend/test/approval/test_menu_access_approval.py` | 菜单权限审批单测 |
| `src/backend/test/approval/test_channel_subscription_approval_integration.py` | 频道审批接入测试 |
| `src/backend/test/approval/test_knowledge_space_subscription_approval_integration.py` | 知识空间审批接入测试 |
| `src/backend/test/knowledge/test_department_knowledge_space_upload_permission.py` | 部门知识空间上传回归 ReBAC 权限测试 |
| `src/frontend/client/src/components/approval/` | 我的审批 / 我的申请 / 详情 / 决策相关 UI |
| `src/frontend/platform/src/pages/ApprovalPage/index.tsx` | 审批管理页入口 |
| `src/frontend/platform/src/controllers/API/approval.ts` | 管理后台审批 API 封装 |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/approval/api/router.py` | 注册新用户端/管理端路由 |
| `src/backend/bisheng/api/router.py` | 确保 approval 模块路由纳入全局 |
| `src/backend/bisheng/common/errcode/approval.py` | 扩展 18105+ 错误码 |
| `src/backend/bisheng/message/domain/services/approval_handler.py` | 标记 legacy，并补迁移注释 |
| `src/backend/bisheng/channel/domain/services/channel_service.py` | 订阅入口切到 `ApprovalGate` |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | 加入/订阅入口切到 `ApprovalGate` |
| `src/backend/bisheng/database/models/audit_log.py` | 审计 action/module 白名单扩展 `approval.*` |
| `src/frontend/client/src/layouts/UserPopMenu.tsx` | 工作台用户菜单增加“我的审批”“我的申请”入口 |
| `src/frontend/client/src/components/NotificationsDialog.tsx` | 消息提醒与审批详情跳转联动 |
| `src/frontend/client/src/api/approval.ts` | 扩展前台审批 API |
| `src/frontend/client/src/api/channels.ts` | 频道订阅接口兼容审批返回结果 |
| `src/frontend/client/src/api/knowledge.ts` | 知识空间加入接口兼容审批返回结果 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_service.py` | 移除部门知识空间文件上传审批，回归 ReBAC 上传权限校验 |
| `src/backend/bisheng/approval/domain/models/approval_request.py` | 标记为历史只读兼容对象，不再承载新上传审批 |
| `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json` | 前台审批、消息提醒文案 |
| `src/frontend/platform/src/pages/MenuPermissionPlaceholder.tsx` | 若后台 `/admin` 侧也需申请入口，占位页改为可申请页面 |
| `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json` | 审批管理、异常流程、审计文案 |
| `features/v2.6.0/release-contract.md` | 登记新对象 Owner、依赖、模块编码 181、变更历史 |
| `features/v2.6.0/README.md` | 增加 F025 索引 |

---

## 10. 非功能要求

- **性能**：`ApprovalGate.request_or_pass()` 单次请求在无审批路径下不应明显慢于原业务接口；列表接口分页默认 20 条。
- **安全**：审批中心所有表严格带 `tenant_id`；详情接口做申请人/审批人/管理员准入校验；消息跳转不绕过详情权限。
- **可靠性**：outbox 执行幂等；基于 `instance_id + business_key` 防重复；重试不回滚审批结论。
- **可观测性**：所有关键操作写 `approval_action_log` + `auditlog`，并带 `trace_id`、`instance_id`、`scenario_code`、`handler`。
- **兼容性**：历史 `approval_request` 和旧站内信审批记录如需保留，可只读查看；新业务不再创建旧消息审批事实。
- **能力收敛**：部门知识空间文件上传审批在本版本移除；新增/现行上传链路不再写 `approval_request`，只走 ReBAC 权限校验。
- **数据库兼容性**：审批中心新增模型、索引、迁移、默认值与时间戳行为必须同时兼容 MySQL 与达梦；实现时默认遵循 [达梦数据库支持设计](../../../docs/superpowers/specs/2026-04-28-dameng-database-support-design.md) 的单代码库、方言分支方案。

---

## 相关文档

- 版本契约: [../release-contract.md](../release-contract.md)
- 版本索引: [../README.md](../README.md)
- 关联 PRD: [../../../docs/PRD/审批流程PRD/审批流程PRD.md](../../../docs/PRD/%E5%AE%A1%E6%89%B9%E6%B5%81%E7%A8%8BPRD/%E5%AE%A1%E6%89%B9%E6%B5%81%E7%A8%8BPRD.md)
