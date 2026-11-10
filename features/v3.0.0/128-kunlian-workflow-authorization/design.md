# 昆联对接毕昇 Workflow 授权管理设计

- **Feature ID** `F128`（拟用，合入前复核）
- **版本与状态** `v3.0.0` · 本地 Mock 已验收，正式接入待确认 · 2026-11-10
- **关联** [规格](./spec.md) · [任务清单](./tasks.md) · [开发规划](../../../docs/architecture/proposals/kunlian-workflow-development-plan.md) · [版本契约](../release-contract.md) · [架构约束](../../../docs/constitution.md)

## 1. 目标与边界

昆联后端通过受信委托，以实际用户身份读取毕昇 Workflow 的直接授权、读取自己的有效动作、授予或撤销指定的用户授权。毕昇沿用现有 Workflow 对象、F048 授权与可见性投影、F118 身份与租户事实。首轮在隔离 Mock 验证同租户用户的授权及撤权。

所有者转移、用户组写入、跨平台权限镜像、资源停用入站、创建配额和在途运行取消保留后续范围。既有工作流授权入口继续使用原合同。

## 2. 关键约束与架构核对

遵循 C1–C8、INV-27 与 INV-30。候选入口只挂载到隔离测试应用。请求的调用方、租户、操作人和委托范围由注入的受信身份依赖提供。正式路由启用前须接入开放平台的既有准入机制，并确认 SSO Access Token 的适用范围。

| 约束 | 本设计落点 |
| --- | --- |
| C1、C4 | HTTP 入口调用 Workflow 应用适配。Workflow 所有权服务核对资源范围，F048 应用接口负责权限判定与授权变更。授权事实、投影和修复归 F048。 |
| C2、C3、C8 | 复用 F048 的租户作用域、资源版本及投影操作记录。Mock 回执仅存在于隔离装配，正式回执的持久化与保留期在接线前确认。本轮设计无需生产 Schema 变更。 |
| C5、C6、C7 | 候选返回使用安全分类和统一响应封装。凭据由受信依赖注入，日志仅记录定位所需标识。首轮交付后端候选入口。 |

## 3. 设计决策

| 决策 | 取舍与复核条件 |
| --- | --- |
| D-01 · 复用 F048 授权应用接口 | 直接复用浏览器路由会耦合浏览器登录与完整授权页响应。候选入口复用其底层 `F048ResourcePermissionApi`，额外限定实际操作者、接入范围及可变更主体。正式委托和跨租户策略变化时重新审查。 |
| D-02 · 直接授权与有效动作分别查询 | F048 的 `list_grants` 返回来源级清单，`get_my_permissions` 返回实际用户的动作及来源。分别投影为管理者清单和本人动作。用户组来源可作为有效动作的证据。若后续需要管理者批量查看他人的有效动作，另行确认授权范围和数据最小化。 |
| D-03 · 新变更与原操作查回分开 | F048 先比对资源版本与目录版本，随后生成投影计划。投影校验和包含生成的授权标识及变更明细，提交后无法按新状态重建同一计划。Mock 先按请求范围绑定原请求摘要，重复请求从原操作查回。正式回执的持久化、跨实例查回和保留期确认后再接线。 |

## 4. 当前链路与拟接入点

| 现有落点 | 已有职责与拟复用 |
| --- | --- |
| [F048 授权应用接口](../../../src/backend/bisheng/permission/application/resource_api.py) | `get_context` 提供权限资源版本和目录版本。`list_grants` 分页读取授权来源。`get_my_permissions` 读取本人有效动作。`get_grantable_models`、`mutate_grants` 使用原有授权模型与权限运行时。 |
| [Workflow 权限资源适配](../../../src/backend/bisheng/api/services/f048_application_permission.py) · [Workflow 管理读入口](../../../src/backend/bisheng/workflow/application/kunlian_workflow_management.py) | 按所属租户、对象类型和 F048 动作判定现有 Workflow 访问。首轮以隔离装配明确的接入范围约束可管理对象。列表、详情和后续业务动作继续走其原有路径。 |
| [身份解析](../../../src/backend/bisheng/permission/application/identity.py) · [F118 身份规格](../118-kunlian-sso-user-sync/spec.md) | 解析 F048 实际用户上下文。复用稳定外部身份映射及租户成员资格。身份匹配使用可信标识和当前状态。 |
| [授权变更](../../../src/backend/bisheng/permission/domain/services/grant_service.py) · [投影运行](../../../src/backend/bisheng/permission/domain/services/projection_service.py) | 校验权限模型、资源修订和来源修订，准备并提交投影计划。SQL 最终确认后记录 `FINALIZED`。原投影修复流程继续管理未收敛操作。 |

### 4.1 请求入口与读取

1. 隔离 HTTP 依赖交付已经验证的接入方、实际用户和租户。应用核对当前成员状态及接入范围，并通过既有 Workflow 适配核实对象类型和租户。请求中的 `subject_ref` 仅表示授予目标。传入 F048 的 actor 必须与受信实际用户及当前租户一致，并保留委托约束及数据范围，避免采用上游残留的服务账号或管理员上下文。
2. 授权清单明确检查 `manage_permission`。结合 `get_context` 取得权限资源修订和 Catalog 修订，复用 `list_grants` 的分页。只返回目标 Workflow 的本地直接来源和允许的字段。已有用户组及受保护来源可按授权显示为只读。分页过滤保留原游标和 `has_more`，允许空页续读。前后校验修订及投影就绪状态，读取期间发生变化时要求重新查询。可授予模型按当前操作者过滤，首轮采用隔离装配中的角色映射。
3. 本人权限查询只接受当前实际用户，复用 `get_my_permissions` 的可见性门槛及有效动作。只输出动作集合。权限、范围或投影状态无法确认时返回不可用，清单与动作均无部分结果。昆联展示数据与 Workflow 后续访问各自按毕昇实时判定。

### 4.2 写入与重复请求

1. 授予仅允许同租户自然人。校验用户映射与有效成员资格后，把隔离样例的角色映射为当前可授予的 F048 普通模型。撤销按 `assignee_id` 和来源修订定位同一 Workflow 的本地直接用户来源，核对同租户、非保护及可管理。F048 仍执行最终的模型级别和版本检查。用户组、继承、所有者或其他受保护来源保持只读。
2. 每次请求先完成实际用户、对象范围和当前管理权限检查，再查回执。按接入方、租户、实际用户、Workflow 和客户端幂等键绑定一条回执。摘要包含操作、授权主体或授权来源、目标模型以及调用者提交的修订。相同键不同内容返回冲突。授权记录和回执都按该范围查读。
3. 隔离回执端口提供原子 `claim_or_read(scope_key, request_digest)` 与条件完成。测试夹具在同一隔离实例的并发请求间共享，夹具生命周期即首轮保留期。首次领取者按原修订把单次 `ADD` 或 `REMOVE` 交给 `mutate_grants`。内部幂等键对规范化的 `F128` 命名空间和作用域计算 SHA-256，以 64 字符十六进制串满足既有请求限制。回执存最小关联标识和处理结果。变更竞争以 F048 对资源、Catalog、授权来源和投影操作的检查为准。
4. 授权已确认时回执保存原生效修订，响应丢失后可查回。回执未完成时，通过权限应用层只读端口查原投影操作，校验租户、Workflow、操作人、内部幂等键及操作类型。只有 `FINALIZED` 可恢复成功。`PREPARED`、`STAGING`、`COMMIT_UNKNOWN`、`COMMITTED`、`FAILED_CLOSED` 或查不到确定事实时保留待确认，按 F048 既有修复流程收敛。明确证实写入前被拒绝时，保存可查回的拒绝结果。重复请求只核对原操作，原请求是否提交不明时维持待确认。后续请求仍以当前权限为准。

### 4.3 拟改动位置

| 位置 | 职责 |
| --- | --- |
| `src/backend/bisheng/open_endpoints/api/endpoints/kunlian_workflow_permissions.py`（拟新增） | 隔离候选路由、严格请求校验、受信依赖和统一错误响应。仅由测试装配显式注册。 |
| `src/backend/bisheng/workflow/application/kunlian_workflow_authorization.py`（拟新增） | 约束接入范围、实际操作者与目标用户，编排 F048 读取及写入和回执查回，裁剪对外结果。应用接收权限和回执端口。 |
| `src/backend/bisheng/permission/application/resource_api.py`（拟扩展只读能力） | 复用既有权限应用入口。为本地直接来源的精确校验和原操作结果查回提供窄接口，权限领域内部查询来源与投影。现有浏览器调用合同继续沿用。 |
| `src/backend/test/workflow/` 与 `src/backend/test/permission/`（拟新增或扩展） | 复用授权策略、来源和投影测试夹具。装配 Mock 身份和回执，串联既有 Workflow 列表、详情及动作判定。 |

## 5. 已知坑与处理

| 事实 | 影响与处理位置 |
| --- | --- |
| `GrantService.mutate` 在准备投影之前检查当前资源版本。 | 用已经生效的请求重试会遇到旧修订。Workflow 应用先查本次回执，再按原投影操作核对。 |
| `REMOVE` 使用授权来源 ID，F048 通用入口也能处理不同主体类型。 | 撤权适配在提交前按准确来源核对类型、对象、租户和保护状态。继续由 F048 检查来源及资源修订，避免查验后并发替换。 |
| `get_context` 本身允许只读查看者读取上下文，身份解析可优先采用已有上下文 actor。 | 授权清单、写入及回执各自显式检查 `manage_permission`。入口核对受信实际用户，保留并验证委托范围，跨租户校验在任何管理员快捷判定前完成。 |
| 直接授权撤销后，用户组等其他来源仍可授予同一动作。 | 用 F048 的有效动作及现有业务入口验证撤权结果。禁止从来源清单推断全部有效动作。 |
| F048 授权来源 ID 可能超出 JavaScript 安全整数，投影 `COMMITTED` 仍可能未完成 SQL 确认。 | 候选 Schema 用十进制字符串承载来源 ID，操作查回仅以原操作 `FINALIZED` 确认成功。 |

## 6. 候选契约与正式依赖

隔离候选基址为 `/__mock__/kunlian/workflows/{workflow_id}`。路由固定资源类型为 Workflow。成功使用统一响应，设置 `Cache-Control: no-store`。下面的路径与字段供本地验收，正式契约待双方确认。

| 接口 | 候选请求与响应 |
| --- | --- |
| `GET …/permissions` | 输入不透明的 `cursor` 与 `limit`，默认 50，范围 1–200。返回 `resource_version`、`catalog_release_id`、`items`、`grantable_models`、`next_cursor` 和 `has_more`。授权条目提供字符串 `assignee_id`、整数 `assignee_version`、主体类型和允许展示的主体标识、模型键及 `editable`。 |
| `GET …/my-permissions` | 返回实际用户当前有效 `actions`，沿用本人可见性校验。 |
| `POST …/permissions/grants` | 请求携带 `Idempotency-Key`、`expected_resource_version`、`expected_catalog_release_id`、`subject_ref` 和 `model_key`。 |
| `POST …/permissions/grants/{assignee_id}/revoke` | 请求携带 `Idempotency-Key`、两个预期修订及 `expected_assignee_version`。授予和撤销返回最小 `operation_ref`、`status` 及已确认时的 `applied_resource_version`。用原请求重试可查回。 |

修订字段使用非负整数，`expected_catalog_release_id` 为正整数。Mock `Idempotency-Key` 为 1–64 个可见 ASCII 字符。`operation_ref` 为稳定且不含原始请求键的操作标识。候选分类为 `200 APPLIED`、`202 PENDING`、`409 REVISION_CONFLICT` 或 `IDEMPOTENCY_CONFLICT`、`422 INVALID_INPUT`。未通过身份验证用 `401`，越权或对象不可见用统一 `404`，权限服务无法确认时用 `503`。对外错误只返回安全分类。实际服务端错误码和状态码映射随正式合同确认。

| 待确认 | 依赖与替换点 |
| --- | --- |
| `TODO [F128][EXT-01]` | 正式开放平台准入、昆联实际用户委托及 SSO Access Token 可复用边界。受众、租户、接入范围和撤权时效影响每次调用。 |
| `TODO [F128][EXT-02]` | 确定昆联自然人标识与毕昇角色模型映射。用户组写入单独定范围。 |
| `TODO [F128][EXT-03]` | 定案正式路径、授权和修订字段、幂等及回执查回。正式回执须支持跨实例、重启恢复、保留期与租户隔离。明确在领取回执后但 F048 未记录操作时的恢复责任与时限。需新增生产数据结构或改变 F048 变更协议时，回到设计确认。 |
| `TODO [F128][EXT-04]` | 双方提供 OpenAPI、测试地址、同租户管理者及受权人、撤权和越权样例。真实权限环境依赖现有 F048 SQL、Redis 一致性标记和 OpenFGA。 |

## 7. 验证、观测与回退

| 验证 | 需求与验收 | 执行方式与状态 |
| --- | --- | --- |
| V-01 | REQ-01、REQ-02、REQ-04、REQ-05 · AC-01、AC-04、AC-05、AC-06 | 隔离端口、并发与故障注入。覆盖错误操作者、目标租户、保护来源、同键变体、版本竞争及提交后响应丢失。`PASS`，隔离 Mock。 |
| V-02 | REQ-01、REQ-02、REQ-03、REQ-05、REQ-06 · AC-01、AC-02、AC-03、AC-04、AC-07 | 同一隔离权限事实串联候选 HTTP 与既有 Workflow 读入口和动作判定。验证撤掉最后来源、保留独立来源、毕昇现有入口变更后的查询。`PASS`，隔离 Mock。 |
| V-03 | REQ-02、REQ-03、REQ-04、REQ-05、REQ-06 · AC-03、AC-05、AC-06 | 受控 SQL、Redis 和 OpenFGA 核对并发写入、最终确认、原操作查回与撤权传播。`NOT_RUN`，待环境。 |
| V-04 | REQ-01、REQ-02、REQ-03、REQ-05、REQ-06 · AC-02、AC-03、AC-04、AC-07 | 使用昆联测试接入及受信用户走完授权、撤权和越权拒绝。`NOT_RUN`，待正式契约与测试环境。 |

本地实现后使用 Mock 管理者 A 获取 `/permissions` 的修订和可授予模型，提交给 B 的授权。以 B 查询 `/my-permissions`、Workflow 列表和详情，复核编辑及管理动作，再以 A 撤销该来源。用原键重试，并让 B 再访问。分别预置无其他来源和保留已有组授权两组数据。

观测记录关联标识、租户、Workflow、实际操作者、动作、原修订和安全结果类别，核对重试次数、修订冲突及待确认操作。撤除隔离候选路由即停止首轮入口。已受理的 F048 操作仍由既有修复流程收敛，正式启用前需验证回执保留和故障恢复。测试数据随夹具清理。

## 8. 后续范围与修订

权限镜像和昆联入站事件分别依赖事件来源、同步时效及对账合同。所有者转移和在途运行策略按后续规格确认。

| 日期 | 修订 |
| --- | --- |
| 2026-11-10 | 根据已确认的 6B 首轮规格编写初版设计。Mock 实施与环境验证待执行。 |
| 2026-11-10 | 候选授权接口、F048 只读检查及查回已完成隔离验证。 [验证记录](./verification.md) |
