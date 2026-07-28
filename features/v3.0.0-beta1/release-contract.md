# Release Contract — v3.0.0-beta1

> 本文件是 v3.0.0-beta1 版本级领域归属与全局约束的权威来源。
> **所有 spec.md 在动笔前必须先阅读本文件。**
> 每次 spec 评审时，必须对照本文件检查一致性。
>
> F043～F046 来自 PRD《3.0.0-beta1 需求文档》§四 功能体验优化；
> F047 为灵思任务模式引用溯源；F048 来自 PRD《3.0-beta1 ReBAC 逻辑优化》，
> 是本版本的 P0 权限架构升级 Feature。

---

## 表 1：领域对象归属

每个领域对象只能有一个 Owner Feature，负责定义该对象的写入行为
（创建、更新、删除）。其他 Feature 只能"读取"或"引用"该对象。

| 领域对象 | Owner Feature | 说明 |
|---------|--------------|------|
| —（无新增） | F043-report-node-optimization | 在既有工作流报告节点模板链路上：①新增「手动触发保存」端点（转发 forcesave 指令到 OnlyOffice，落盘仍走既有 callback）；②变量占位符格式扩展为 `{{显示名\|nodeId.field}}`（向后兼容旧 `{{nodeId.field}}`，解析仍以 nodeId 为键）。**范围仅工作流报告节点**——旧「技能」体系独立报告页入口已关闭、变量机制独立（`{id}_{name}`），不纳入、不做兼容投入，待随技能残留代码一并清理；不引入新领域对象/表/DAO |
| —（无新增） | F044-model-status-manual-verify | 在既有 `LLMModel` 上新增 `status_update_time` 字段（Alembic）与「手动验证单模型」对外 API；复用既有按类型探活逻辑，状态写入仍经由既有 LLM service/DAO；不引入新领域对象 |
| —（无新增） | F045-chat-image-preview | 纯 client 前端渲染改造（日常/任务/工作流会话消息附件的图片分流 + 失效占位）；不触碰后端与存储 |
| —（无新增） | F046-channel-source-link-failure-ux | 纯 client 前端改造（添加公众号信息源的失败状态机、弹窗文案、引导浮层）；不改后端识别接口与错误码 |
| —（无新增） | F047-linsight-citation-traceability | 在既有 citation 子系统上新增**灵思任务模式**的溯源接线：`search_knowledge_base` 保留 chunk 元数据并接入 registry、包装 `web_search` 登记来源、完成时经既有 `save_message_citations` 向 `message_citation` 写入（`message_id`=任务轮 `ChatMessage.id`，`chat_id`=会话 id）。只读 / 调用现有 `KnowledgeFile` / `MessageCitation` 与 citation 服务；不拥有 `message_citation` schema、不改日常模式、不改灵思检索的文件级可见性 |
| PermissionAction | F048-rebac-permission-model-grants | 统一细粒度动作、适用资源范围、唯一等级和生效状态 |
| PermissionActionResourceScope | F048-rebac-permission-model-grants | 动作与适用资源类型的规范化关联，不使用 JSON 数组作为运行时真相 |
| PermissionModel | F048-rebac-permission-model-grants | 四个标准模型、自定义模型、派生等级、动作集合、生效状态和模型级同级授权策略 |
| PermissionModelAction | F048-rebac-permission-model-grants | 权限模型与细粒度动作的规范化多对多关联 |
| PermissionGrant | F048-rebac-permission-model-grants | 某一资源与某一权限模型之间的授权集合及其用户、部门、用户组等主体来源 |
| PermissionGrantAssignee | F048-rebac-permission-model-grants | Grant 中的直接用户、部门、用户组等主体、范围、来源和受保护属性 |
| ResourcePermissionMode | F048-rebac-permission-model-grants | 资源的 `INHERIT` / `CUSTOM` 权限模式及直接权限来源 |
| ProtectedPermissionAssignment | F048-rebac-permission-model-grants | 系统创建且不能由普通成员管理接口删除或降级的资源授权 |
| AuthorizationModelRelease / PermissionMigrationRun / PermissionMigrationItem | F048-rebac-permission-model-grants | OpenFGA Authorization Model 版本、生产固定版本，以及权限升级的盘点、逐项映射、校验、切换、回滚点和人工处置结果 |

**规则**：
- 非 Owner Feature 的 AC 中不得出现其他对象的"创建/修改/删除"行为，只能"读取"或"调用" Owner 的 Service
- 新增领域对象时必须先更新本表
- `PermissionModel` 与 `PermissionGrant` 是业务实例，不等于全局 Authorization Model 的版本；全局模型只定义可表达的类型与关系

---

## 表 2：跨 Feature 不变量（INV-N）

全局业务约束，任何 spec 的 AC **不得与之矛盾**。

| ID | 不变量描述 | 涉及领域对象 | 来源 spec |
|----|-----------|------------|---------|
| INV-8 | 报告模板变量解析必须以**节点 ID** 为取数键；显示名仅作展示，不参与执行期取数。解析端必须永久兼容存量旧格式 `{{nodeId.field}}`（不迁移、不改写存量模板） | 工作流报告模板 / 独立报告模板 | F043 |
| INV-9 | 在 C4 明确的系统级身份短路之后，进入资源 ReBAC 的每个业务动作只以 OpenFGA 对该具体动作的结果作为最终结论；不得由 Config、数据库细粒度模型、creator 或其他旧路径二次放行，也不得在 OpenFGA 故障后临时启用 admin fallback | PermissionAction, PermissionGrant | F048 |
| INV-10 | 业务 Repository 先限定当前租户可访问的数据范围；权限系统不得建立或解析跨租户的模型、Grant 或主体关系 | PermissionModel, PermissionGrant | F048 |
| INV-11 | 标准模型固定为查看者、编辑者、管理者、所有者四个累计等级；其名称、等级和动作集合不可直接编辑，只有包含 `manage_permission` 时的“是否允许授予同级”策略可按模型独立修改 | PermissionModel | F048 |
| INV-12 | 自定义模型等级始终等于其有效动作的最高等级；空动作、未分级动作和不适用动作均不得形成生效模型 | PermissionAction, PermissionModel | F048 |
| INV-13 | 一个 PermissionGrant 只绑定一个资源和一个 PermissionModel；模型动作变更通过共享模型影响其全部 Grant，不得展开为“资源数 × 用户/部门数”的模型动作重写 | PermissionModel, PermissionGrant | F048 |
| INV-14 | 一个来源模型只有在自身同时满足 `manage_permission`、自身等级和自身同级授权策略时才产生授权能力；不得跨不同模型拼接这三个条件 | PermissionModel, PermissionGrant | F048 |
| INV-15 | 同一主体对同一资源的直接授权、部门授权和其他主体来源独立存在并取权限并集；撤销一个来源不得删除或抵消其他仍有效来源 | PermissionGrant | F048 |
| INV-16 | 权限继承复用资源既有的直接 `parent` 语义，不建立第二套 `permission_parent` 层级；`CUSTOM` 只切断权限继承，不能改变业务结构父子关系 | ResourcePermissionMode | F048 |
| INV-17 | 任一有效 Grant 可以产生资源列表/基础元数据可见性，但可见性不能替代文件正文、预览、下载、搜索、RAG 或业务变更动作的具体鉴权 | PermissionAction, PermissionGrant | F048 |
| INV-18 | 权限升级采用有门禁的一次切换；切换后不保留长期双写、旧动作别名、Config 第二 PDP 或逐请求旧系统 ALLOW fallback | PermissionMigrationRun | F048 |
| INV-19 | 对需要进入资源 ReBAC 的请求，权限服务不可用、模型未生效、动作未分级、迁移记录不明确或授权状态不可判定时必须 fail closed | PermissionAction, PermissionModel, PermissionGrant | F048 |
| INV-20 | 动作、模型、模型动作、资源 Grant、Grant 主体和权限模式的运行时事实必须存于规范化关系表；`permission_relation_models_v1`、`permission_relation_model_bindings_v1` 及任何新的大 JSON 不得继续作为运行时真相 | PermissionAction, PermissionModel, PermissionGrant, ResourcePermissionMode | F048 |
| INV-21 | 所有生产 OpenFGA Check、List 和 Write 必须显式指定经发布门禁确认的 Authorization Model ID；发布新模型不得依赖“自动使用最新模型”完成切换 | AuthorizationModelRelease | F048 |
| INV-22 | 旧 `owner/manager/editor/viewer` 只迁移直接关系事实；由旧模型计算出的层级、父级或角色蕴含结果不得展开为新的 Grant assignee | PermissionGrant, PermissionGrantAssignee | F048 |
| INV-23 | Authorization Model ID 是 OpenFGA 请求的校验与解释上下文，不是 tuple 的版本标签；A/B 在同一 Store 共存时，新 tuple 必须证明不改变 A 的结果，否则采用隔离 Store 或兼容阶段模型 | AuthorizationModelRelease, PermissionMigrationRun | F048 |
| INV-24 | 标准模型按等级累计动作；自定义模型只产生其显式选择的动作，派生等级只用于分类和可授予边界，不能自动补齐该等级及以下的其他动作。本不变量替代 v2.5.0 INV-7 在 F048 资源权限范围内的旧四档金字塔语义 | PermissionAction, PermissionModel | F048 |
| INV-25 | 资源创建仍必须通过 `PermissionService.authorize()` 建立受保护所有者授权并遵守失败补偿；F048 切换后其物理形态是受保护 owner Grant 的 OpenFGA 投影，不再要求继续写旧资源 `owner` tuple。本不变量替代 v2.5.0 INV-2 的旧 tuple 形状，不降低其业务安全保证 | ProtectedPermissionAssignment, PermissionGrant | F048 |

（INV-1~7 为 v2.6.0 存量不变量，继续有效，见 `features/v2.6.0/release-contract.md`。）

**规则**：
- 新增不变量：先在此表追加，再写 AC
- 修改不变量：必须列出 Impacted Specs 清单，逐一回写并重新评审
- 冲突检测：若 AC 与不变量矛盾，spec 评审不通过

---

## 表 3：Feature 依赖图

| Feature | 依赖（必须先完成） | 说明 |
|---------|-----------------|------|
| F043-report-node-optimization | 无 | 前后端小改；不依赖本版本其他 Feature |
| F044-model-status-manual-verify | 无 | 前后端小改 + 1 个 Alembic 字段；不依赖本版本其他 Feature |
| F045-chat-image-preview | 无 | 纯前端；不依赖本版本其他 Feature |
| F046-channel-source-link-failure-ux | 无 | 纯前端；不依赖本版本其他 Feature |
| F047-linsight-citation-traceability | F035, F029（均为 v2.6.0 存量，已上线） | 接线型；把灵思任务模式产物接入既有 citation 溯源子系统（Phase 1 应用内预览行内角标，覆盖 KB 文档 + Web 网页；Phase 2 下载 Word/PDF 烘焙可见 `[1]` 编号 + 参考资料，延后）；不新增领域对象/表/对外 API/错误码/不变量/`MessageEventType` 枚举；无 alembic 迁移（复用 `message_citation`）；不写 `LinsightExecuteTask.history`（避 DM8 写放大）；角标解析复用 F029 `view_file` 过滤守 **INV-7**（见 v2.6.0 契约） |
| F048-rebac-permission-model-grants | F004, F006, F007, F008 | 依赖既有 OpenFGA 核心、历史 ReBAC 迁移、资源权限界面和资源接入基线，并替换其中的四档静态关系与 Config 细粒度执行语义 |
| F048-rebac-permission-model-grants | F027, F036, F040 | 依赖既有候选枚举、继承评估和列表性能基线；实现时必须保证分页与性能契约不倒退，并移除对旧 binding 第二次求值的依赖 |

---

## 表 4：受影响的既有契约

| 既有 Feature | v3.0.0-beta1 影响 |
|-------------|-------------------|
| F004-rebac-core | v2.5.0 INV-2 的旧 `owner` tuple 形状由 INV-25 的受保护所有者 Grant 投影替代；INV-7 的四档金字塔权限语义由 INV-24 替代。统一入口、创建者安全保证、失败补偿和 fail-closed 约束继续有效 |
| F006-permission-migration | v2.4→v2.5 的历史迁移结果成为 F048 的迁移来源之一；F048 不修改其历史事实 |
| F007-resource-permission-ui | 成员管理升级为模型、来源、等级、继承/自定义模式和受保护状态展示 |
| F008-resource-rebac-adaptation | 资源生命周期继续统一接入权限服务，但授权写入和具体动作检查改用 F048 语义 |
| F027/F036/F040 | cursor、批量候选和请求内性能约束继续有效；旧 Config binding / 第二 PDP 的优化路径在切换后退役 |
| F013/F017 | `system`、`tenant`、`department`、`user_group`、`shared_with` 等系统关系继续保留；不得被误转为普通资源 Grant |

---

## 已分配模块编码（MMMEE）

> 新 Feature 分配错误码时，必须检查此表避免冲突。

| 模块编码 (MMM) | 模块 | Owner Feature |
|----------------|------|---------------|
| —（不新增） | 既有功能体验优化与引用溯源 | F043 复用工作流/报告既有错误响应；F044 验证失败是业务结果（状态=异常）而非错误响应，不占码；F045/F046 纯前端；F047 复用 citation 子系统与 F029 权限过滤的既有错误响应 |
| 待 Design 盘点 | ReBAC 权限模型与 Grant 升级 | F048 的对外错误码由 Design 阶段在 `common/errcode/` 盘点后分配，本契约暂不预占编号 |

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-07-24 | 初始化 v3.0.0-beta1 契约；登记 F043~F046 四个功能体验优化 Feature（均无新增领域对象；新增 INV-8 报告模板变量以节点 ID 为键 + 永久兼容旧格式；均不新增错误码） | F043 / F044 / F045 / F046 |
| 2026-07-27 | 登记 F047 灵思任务模式引用溯源（**由 v2.6.0 F040 迁入并改编**——v2.6.0 的 F040 编号已被 `040-rebac-read-path-perf-rollout` 占用，spec/design 内容未变，仅改版本与编号）：表 1 标"无新增领域对象"（在既有 citation 子系统上加灵思接线，写入仍经 `save_message_citations`）、表 3 记跨版本依赖 F035/F029（v2.6.0 存量已上线）；复用 F029 `view_file` 过滤守 v2.6.0 **INV-7**；无新增错误码/对外 API/不变量/alembic 迁移；分期 Phase 1 应用内预览行内角标（KB+Web）/ Phase 2 下载件烘焙可见引用（延后） | F047 |
| 2026-07-28 | 将 ReBAC 权限模型与 Grant 升级 Spec 从独立 v3.0.0 草案并入 v3.0.0-beta1，并因 F043 已占用重编号为 F048；登记权限领域对象、INV-9～INV-25、历史契约替代关系、依赖与迁移边界 | F048、F004/F006/F007/F008/F013/F017/F027/F036/F040 |
