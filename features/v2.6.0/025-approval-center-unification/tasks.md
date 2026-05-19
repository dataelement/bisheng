# Tasks: 统一审批中心与旧审批链路收敛（F025）

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0
**基线依赖**: F005 + F011/F012/F013 + 现有 `approval/` / `message/` / `channel/` / `knowledge/`

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | 🔲 草稿 | 待 PRD/架构评审 |
| tasks.md | 🔲 草稿 | 本文件即执行计划 + 任务拆解 |
| 实现 | 🔲 未开始 | 0 / 18 完成 |

---

## 开发模式

- **后端 Test-First**：审批网关、流程流转、异常处理、菜单授权与业务接入改造全部先写测试，再补实现。
- **前端 Test-Alongside**：Platform 仍以手动验证为主；源代码结构可补轻量 source-inspection 测试，避免大面积 UI 回归。
- **迁移式开发**：频道订阅、知识空间加入等旧消息审批链路需完成新旧切换；部门知识空间文件上传审批在本版本直接移除，上传路径回归 ReBAC 权限校验。
- **双库约束**：除 sqlite 单元测试外，审批中心表结构与迁移必须补 MySQL / 达梦方言验证，禁止实现后再补兼容。
- **列优先于 JSON**：凡是审批列表筛选、待办检索、异常处理、重复判定所需字段，必须建显式列，不得只放在 `payload_snapshot` / `detail_snapshot` 里后续再靠 JSON SQL 查询。
- **自包含任务**：每个任务写明文件、逻辑、测试和 AC 覆盖，实现阶段不必反复回读 spec。

---

## 执行阶段计划

1. 先落通用中心模型和审批网关，确保新场景可以创建实例、任务和异常。
2. 再落管理端配置与用户端查询，跑通“场景 -> 分支 -> 流程 -> 节点 -> 详情”主链路。
3. 然后接菜单权限申请，这是新场景里最独特、对数据模型要求最高的一条线。
4. 再移除部门知识空间文件上传审批，统一上传权限口径。
5. 最后迁移频道订阅和知识空间订阅，并补站内信、审计、异常处理联调。

---

## Tasks

### 基础设施与 Domain 模型

- [ ] **T001**: 通用审批中心 ORM / Repository 单元测试
  **文件**: `src/backend/test/approval/test_approval_gate.py`, `src/backend/test/approval/test_approval_flow_runtime.py`
  **逻辑**: 先用 sqlite/aiosqlite 搭内存库，覆盖 `approval_scenario`、`approval_route_rule`、`approval_flow_definition`、`approval_flow_version`、`approval_node_definition`、`approval_instance`、`approval_task`、`approval_exception`、`approval_outbox`、`approval_action_log`、`user_menu_access` 的基本增删查改和 tenant 隔离；通过 repository 而不是直接调用 DAO 风格入口验证主链路
  **测试**:
  - 场景禁用 -> 创建 `scenario_disabled` 异常实例
  - 命中免审批分支 -> 创建 instance，不创建 task
  - 命中审批流程 -> 创建 instance + 首节点 task
  - 重复 `business_key` -> 命中已有实例
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-05
  **依赖**: 无

- [ ] **T002**: 通用审批中心 ORM / Repository 实现
  **文件**: `src/backend/bisheng/approval/domain/models/approval_scenario.py`, `src/backend/bisheng/approval/domain/models/approval_instance.py`, `src/backend/bisheng/approval/domain/models/user_menu_access.py`, `src/backend/bisheng/approval/domain/repositories/approval_scenario_repository.py`, `src/backend/bisheng/approval/domain/repositories/approval_instance_repository.py`, `src/backend/bisheng/approval/domain/repositories/approval_query_repository.py`, `src/backend/bisheng/approval/domain/repositories/user_menu_access_repository.py`
  **逻辑**: 按 spec §5 新建 SQLModel 表与 repository；所有表带 `tenant_id`、`create_time`、`update_time`；JSON 字段、时间戳默认值、DDL 不引入 MySQL 专属写法；所有列表查询、待办检索、幂等判定字段都显式建列；Service 后续统一通过 repository 访问数据
  **测试**: T001 全部通过
  **覆盖 AC**: AC-02~05, AC-28, AC-29, AC-30
  **依赖**: T001

### 后端核心服务（Test-First 配对）

- [ ] **T003**: `ApprovalGate` 单元测试
  **文件**: `src/backend/test/approval/test_approval_gate.py`
  **逻辑**: mock `ApprovalRegistry`、route matcher、repository、handler，覆盖 PASS、PENDING、EXCEPTION、重复申请、场景关闭、无匹配分支、审批人为空
  **测试**:
  - `test_gate_creates_scenario_disabled_exception`
  - `test_gate_pass_when_route_direct_approve`
  - `test_gate_pending_when_route_hits_flow`
  - `test_gate_returns_existing_instance_for_duplicate_business_key`
  - `test_gate_creates_route_missing_exception`
  - `test_gate_creates_approver_empty_exception`
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-05, AC-15, AC-16, AC-17
  **依赖**: T002

- [ ] **T004**: `ApprovalGate` + `ApprovalRegistry` 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_gate.py`, `src/backend/bisheng/approval/domain/services/approval_registry.py`, `src/backend/bisheng/approval/domain/schemas/approval_center_schema.py`
  **逻辑**:
  - 实现 `request_or_pass()`
  - 注册三个主版本场景 preset：`menu_access_request`、`channel_subscribe_request`、`knowledge_space_subscribe_request`
  - preset 内声明 handler、可用条件字段、可用审批人来源
  **测试**: T003 全部通过
  **覆盖 AC**: AC-01~05
  **依赖**: T003

- [ ] **T005**: 流程运行时与异常处理测试
  **文件**: `src/backend/test/approval/test_approval_flow_runtime.py`, `src/backend/test/approval/test_approval_exception_service.py`
  **逻辑**: 覆盖顺序节点、或签、会签、拒绝终止、撤回、异常流程重新指定、场景未启用后的管理员处理、执行失败重试
  **测试**:
  - 或签时一个人通过后其他任务 `skipped`
  - 会签时必须所有任务通过
  - 拒绝时实例终止
  - `scenario_disabled` 启用场景后重新路由继续
  - `route_missing` 指定流程继续
  - `approver_empty` 指定审批人继续/跳过节点
  - `execute_failed` 重试成功与重试失败
  **覆盖 AC**: AC-08~19
  **依赖**: T002

- [ ] **T006**: `ApprovalCenterService`、`ApprovalExceptionService`、`ApprovalOutboxService` 实现
  **文件**: `src/backend/bisheng/approval/domain/services/approval_center_service.py`, `src/backend/bisheng/approval/domain/services/approval_exception_service.py`, `src/backend/bisheng/approval/domain/services/approval_outbox_service.py`, `src/backend/bisheng/worker/approval/tasks.py`
  **逻辑**:
  - 审批任务同意/拒绝
  - 申请撤回/重新提交
  - 异常处理动作
  - outbox 异步执行与重试
  - 统一通过 repository 编排实例、任务、异常、outbox、action log、菜单授权数据访问
  - 关键动作写 `approval_action_log` 和 `auditlog`
  **测试**: T005 全部通过
  **覆盖 AC**: AC-06~19, AC-28, AC-29
  **依赖**: T005

### 后端 API 层

- [ ] **T007**: 用户端/管理端审批 API 集成测试
  **文件**: `src/backend/test/approval/test_approval_api.py`
  **逻辑**: TestClient 覆盖我的审批、我的申请、详情、decision、withdraw、场景列表、场景新增、分支配置、异常处理
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-23
  **依赖**: T006

- [ ] **T008**: 审批 API 实现与 router 注册
  **文件**: `src/backend/bisheng/approval/api/endpoints/approval_user.py`, `src/backend/bisheng/approval/api/endpoints/approval_admin.py`, `src/backend/bisheng/approval/api/router.py`, `src/backend/bisheng/api/router.py`
  **逻辑**:
  - 用户端与管理端接口分离
  - 使用 `UserPayload` 做认证与管理员校验
  - Endpoint 只调用 service，不直接访问 ORM / DAO
  - 统一 `resp_200` 包装
  **测试**: T007 全部通过
  **覆盖 AC**: AC-01, AC-06~23
  **依赖**: T007

- [ ] **T008A**: 审批中心 MySQL / 达梦双库兼容验证
  **文件**: `src/backend/test/approval/test_approval_dialect_compat.py`, `src/backend/bisheng/core/database/dialect_helpers.py`, `src/backend/bisheng/core/database/alembic/versions/*approval*`
  **逻辑**:
  - 为审批中心新增模型补方言级测试，验证 `JsonType`、`UPDATE_TIME_SERVER_DEFAULT`、主键自增、索引与迁移守卫在 MySQL / 达梦下都成立
  - 若审批中心迁移新增任何元数据检查或 DDL 分支，统一复用 `dialect_helpers` / `inspect()`，不得写 MySQL 专属 `information_schema`
  - 审查审批相关查询，确保没有对 MySQL 原生 JSON 函数的隐式依赖
  - 审查 `AC-05` 幂等实现，确认重复申请依赖事务查询 + 状态判断，而不是复杂方言相关唯一索引
  **测试**:
  - mock dialect: `mysql` / `dm` 下 `JsonType.load_dialect_impl()` 与 `UPDATE_TIME_SERVER_DEFAULT` 编译结果符合预期
  - 审批中心迁移文件在 `dm` 方言下不生成非法 DDL
  - 审批中心详情/列表查询不需要对 JSON 快照执行数据库级过滤
  - 有达梦环境时补一次真实连接冒烟；无环境时至少保留方言单测
  **覆盖 AC**: AC-30
  **依赖**: T002, T008

### 菜单权限申请（主场景）

- [ ] **T009**: 菜单权限申请与个人授权测试
  **文件**: `src/backend/test/approval/test_menu_access_approval.py`
  **逻辑**: 覆盖 `menu_approval_mode=true` 时的无权限占位页申请、审批通过授权、父级菜单补齐、授权撤回、重复申请，以及 `menu_approval_mode=false` 时不展示入口且后端拒绝绕过调用
  **测试**:
  - `menu_approval_mode=true` 且场景启用 -> PENDING
  - `menu_approval_mode=false` 且无菜单权限 -> 不展示申请入口；直接调用申请接口被拒绝且不创建审批实例
  - 批准后写入 `user_menu_access`
  - 撤回授权后记录 revoke 状态
  **覆盖 AC**: AC-24, AC-25, AC-32
  **依赖**: T006

- [ ] **T010**: 菜单权限申请实现
  **文件**: `src/backend/bisheng/approval/domain/services/menu_access_handler.py`, `src/backend/bisheng/approval/domain/services/user_menu_access_service.py`, `src/backend/bisheng/common/errcode/approval.py`, `src/frontend/platform/src/pages/MenuPermissionPlaceholder.tsx`
  **逻辑**:
  - 新建菜单申请 handler
  - 新增用户菜单授权表与授权撤回逻辑
  - 仅在 `menu_approval_mode=true` 时展示占位页/申请入口
  - `menu_approval_mode=false` 时维持无权限菜单不展示、无申请入口
  - 新增菜单申请 API
  **测试**: T009 全部通过
  **覆盖 AC**: AC-24, AC-25, AC-32
  **依赖**: T009

### 历史部门知识空间上传审批下线

- [ ] **T010A**: 部门知识空间文件上传审批移除测试与实现
  **文件**: `src/backend/test/knowledge/test_department_knowledge_space_upload_permission.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_service.py`, `src/backend/bisheng/approval/domain/models/approval_request.py`
  **逻辑**:
  - 移除部门知识空间文件上传对 `approval_request` 和旧审批消息链路的依赖
  - 部门知识空间上传与普通知识空间上传保持一致，只校验现有 ReBAC 上传权限
  - 历史 `approval_request` 仅保留只读兼容，不再被新上传流程写入
  **测试**:
  - 有上传权限时部门知识空间上传直接进入正常处理链路
  - 无上传权限时直接按权限拒绝，不创建 `approval_request`
  - 新上传请求不会创建审批消息或审批中心实例
  **覆盖 AC**: AC-31
  **依赖**: T002

### 旧审批链路迁移

- [ ] **T011**: 频道订阅审批迁移测试
  **文件**: `src/backend/test/approval/test_channel_subscription_approval_integration.py`
  **逻辑**: 覆盖 review 频道订阅从旧 `send_generic_approval` 迁入审批中心后的 PENDING/APPROVED/REJECTED 路径
  **覆盖 AC**: AC-26
  **依赖**: T006, T010A

- [ ] **T012**: 频道订阅审批迁移实现
  **文件**: `src/backend/bisheng/channel/domain/services/channel_service.py`, `src/backend/bisheng/approval/domain/services/channel_subscribe_scenario_handler.py`, `src/backend/bisheng/message/domain/services/approval_handler.py`
  **逻辑**:
  - `subscribe_channel()` 切到 `ApprovalGate`
  - 旧 `ChannelSubscribeApprovalHandler` 逻辑抽到新 scenario handler
  - legacy message handler 标记兼容用途
  **测试**: T011 全部通过
  **覆盖 AC**: AC-26
  **依赖**: T011

- [ ] **T013**: 知识空间加入/订阅审批迁移测试
  **文件**: `src/backend/test/approval/test_knowledge_space_subscription_approval_integration.py`
  **逻辑**: 覆盖审批创建、通过后成员激活 + 权限同步、拒绝后状态回写、历史消息兼容跳转
  **覆盖 AC**: AC-27
  **依赖**: T006, T010A

- [ ] **T014**: 知识空间加入/订阅审批迁移实现
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`, `src/backend/bisheng/approval/domain/services/knowledge_space_subscribe_scenario_handler.py`
  **逻辑**:
  - 加入/订阅入口切到 `ApprovalGate`
  - 新 handler 复用现有成员激活与 ReBAC 同步逻辑
  **测试**: T013 全部通过
  **覆盖 AC**: AC-27
  **依赖**: T013

### 前端：Client 工作台审批模块

- [ ] **T015**: Client 前台审批模块与消息提醒联调
  **文件**:
  - `src/frontend/client/src/layouts/UserPopMenu.tsx`
  - `src/frontend/client/src/components/NotificationsDialog.tsx`
  - `src/frontend/client/src/components/approval/`
  - `src/frontend/client/src/api/approval.ts`
  - `src/frontend/client/src/api/channels.ts`
  - `src/frontend/client/src/api/knowledge.ts`
  - `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`
  **逻辑**:
  - 在工作台用户菜单新增“我的审批”“我的申请”入口
  - 复用消息提醒入口，支持审批消息跳转并定位到详情
  - 落地“左列表 + 右详情”的前台审批弹窗
  - 菜单权限申请入口仅在 `menu_approval_mode=true` 且用户无权限时出现
  - 频道订阅、知识空间加入、菜单申请都在 Client 项目接审批返回态
  **覆盖 AC**: AC-20, AC-21, AC-23, AC-24, AC-26, AC-27, AC-32
  **手动验证**:
  - Client 工作台左下角用户菜单可见“我的审批”“我的申请”“消息提醒”
  - 审批人能在“我的审批”处理待办并刷新详情
  - 申请人能在“我的申请”撤回和查看进度
  - 消息提醒点击后能打开审批详情或对应申请
  - 站内信仅跳转，不含快捷审批按钮
  - `menu_approval_mode=false` 时无权限菜单不展示，也没有申请入口
  **依赖**: T008, T010, T012, T014

- [ ] **T016**: Platform 审批管理页、异常流程列表与审计文案联调
  **文件**:
  - `src/frontend/platform/src/pages/ApprovalPage/`
  - `src/frontend/platform/src/controllers/API/approval.ts`
  - `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`
  - `src/backend/bisheng/database/models/audit_log.py`
  **逻辑**:
  - 新增“审批管理”后台模块
  - 落地场景管理、条件分支、流程配置、节点配置、异常流程列表
  - 审计模块加入 `approval` 模块和 `approval.*` 动作文案
  **覆盖 AC**: AC-01, AC-06~19, AC-22, AC-28
  **手动验证**:
  - Platform 后台可进入“审批管理”
  - 管理员能配置场景/分支/流程并处理异常
  - 异常列表可处理 `scenario_disabled` / `route_missing` / `approver_empty` / `execute_failed`
  - 审计页可按“审批”模块筛选并看到结构化动作
  **依赖**: T008

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

- **偏差 1**: <待补充>
