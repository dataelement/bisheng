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
| PermissionCatalogRelease | F048-rebac-permission-model-grants | 动作、模型和模型动作的完整版本快照；由单一 active Catalog tuple 原子切换执行状态 |
| PermissionCatalogProjectionTuple | F048-rebac-permission-model-grants | PLATFORM 全局 Catalog release 的分批 staging、commit checksum 与逐 tuple 恢复状态；不伪造 tenant_id |
| PermissionModel | F048-rebac-permission-model-grants | 四个标准模型、自定义模型、派生等级、动作集合、可分配状态和模型级同级授权策略 |
| PermissionModelAction | F048-rebac-permission-model-grants | 权限模型与细粒度动作的规范化多对多关联 |
| PermissionGrant | F048-rebac-permission-model-grants | 某一资源与某一权限模型之间的授权集合及其用户、部门、用户组等主体来源 |
| PermissionGrantAssignee | F048-rebac-permission-model-grants | Grant 中的直接用户、部门、用户组等主体、范围、来源和受保护属性 |
| ResourcePermissionMode | F048-rebac-permission-model-grants | 资源的 `INHERIT` / `CUSTOM` 权限模式及直接权限来源 |
| ProtectedPermissionAssignment | F048-rebac-permission-model-grants | 系统创建且不能由普通成员管理接口删除或降级的资源授权 |
| PermissionProjectionOperation / PermissionProjectionTuple | F048-rebac-permission-model-grants | tenant 级 Grant/mode/resource 到 OpenFGA 的幂等发布意图、分阶段 tuple、commit、补偿和失败关闭状态 |
| AuthorizationModelRelease / PermissionMigrationRun / PermissionMigrationItem | F048-rebac-permission-model-grants | 现有 OpenFGA Store 中的新 Authorization Model 版本、唯一生产固定版本，以及由 `src/backend/scripts/` 专用数据迁移脚本写入的逐项映射、checkpoint、旧 tuple 退役、校验、启服和人工处置结果；不是 Alembic revision 状态 |
| PermissionVisibleSourceProjection | F048-rebac-permission-model-grants | 原 F048 正式迁移和后续运行时从 canonical Grant assignee 生成的展平可见派生索引；随同一 PermissionMigrationRun/Item 追溯；system/public/shared 继续由各 Owner 事实与 system tuple 追溯；均不可独立编辑或参与数据库 ALLOW |

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
| INV-10 | 业务 Service / Repository 负责资源存在性、租户、状态、父级和业务范围，权限领域不得查询或裁决这些业务数据；权限系统只接收业务侧已验证的资源上下文，且不得建立或解析跨租户的模型、Grant 或主体关系 | PermissionModel, PermissionGrant | F048 |
| INV-11 | 标准模型固定为查看者、编辑者、管理者、所有者四个累计等级；其名称、等级和动作集合不可直接编辑，只有包含 `manage_permission` 时的“是否允许授予同级”策略可按模型独立修改。任一动作等级/状态/范围变化必须在同一 Catalog release 中重新生成四个标准模型的累计动作 | PermissionModel | F048 |
| INV-12 | 自定义模型等级始终等于其有效动作的最高等级；动作等级/状态/范围变化必须重算所有自定义模型的派生等级和有效资源动作；空动作、未分级动作和不适用动作均不得形成生效模型 | PermissionAction, PermissionModel | F048 |
| INV-13 | 一个 PermissionGrant 只绑定一个资源和一个 PermissionModel；模型动作变更通过共享模型影响其全部 Grant，不得展开为“资源数 × 用户/部门数”的模型动作重写 | PermissionModel, PermissionGrant | F048 |
| INV-14 | 一个来源模型只有在自身同时满足 `manage_permission`、自身等级和自身同级授权策略时才产生授权能力；不得跨不同模型拼接这三个条件 | PermissionModel, PermissionGrant | F048 |
| INV-15 | 同一主体对同一资源的直接授权、部门授权和其他主体来源独立存在并取权限并集；撤销一个来源不得删除或抵消其他仍有效来源 | PermissionGrant | F048 |
| INV-16 | 权限继承复用资源既有的直接 `parent` 语义，不建立第二套 `permission_parent` 层级；`CUSTOM` 只切断权限继承，不能改变业务结构父子关系 | ResourcePermissionMode | F048 |
| INV-17 | 任一有效 Grant 可以产生资源列表/基础元数据可见性，但可见性不能替代下载、搜索、RAG 或业务变更动作的具体鉴权。文件预览不设置 PermissionAction；只有原件/打包下载必须检查 `download`，不得由“可预览”推导下载能力 | PermissionAction, PermissionGrant | F048 |
| INV-18 | 权限升级采用应用自动阻断业务访问后的单向正式数据迁移：更新镜像并启动进程后，旧 model 只能进入 `MIGRATION_REQUIRED/NOT_READY` 运维态，不初始化 F048 权限运行时、不发布 ready heartbeat，HTTP/WS 迁移门禁除 `/health` 外统一拒绝访问，Celery/Linsight 暂停消费任务；schema upgrade 成功后，由 `src/backend/scripts/` 专用脚本沿用现有 Store 发布一个新 model ID，原地转换 tuple 并退役旧运行数据，校验通过后重启全部进程并自动恢复访问/任务消费。F048 不提供独立迁移预演、旧/新 model 影子运行、应用级回滚、新→旧转换、dual/legacy model client、长期双写、旧动作别名、Config 第二 PDP 或逐请求旧系统 ALLOW fallback；失败保持维护并前向修复 | PermissionMigrationRun | F048 |
| INV-19 | 对需要进入资源 ReBAC 的请求，权限服务不可用、模型未生效、动作未分级、迁移记录不明确或授权状态不可判定时必须 fail closed | PermissionAction, PermissionModel, PermissionGrant | F048 |
| INV-20 | 动作、模型、模型动作、资源 Grant、Grant 主体和权限模式的运行时事实必须存于规范化关系表；`permission_relation_models_v1`、`permission_relation_model_bindings_v1` 及任何新的大 JSON 不得继续作为运行时真相 | PermissionAction, PermissionModel, PermissionGrant, ResourcePermissionMode | F048 |
| INV-21 | 所有生产 OpenFGA Check、List 和 Write 必须显式指定经发布门禁确认的 Authorization Model ID；发布新模型不得依赖“自动使用最新模型”完成切换 | AuthorizationModelRelease | F048 |
| INV-22 | 旧 `owner/manager/editor/viewer` 只迁移直接关系事实；由旧模型计算出的层级、父级或角色蕴含结果不得展开为新的 Grant assignee | PermissionGrant, PermissionGrantAssignee | F048 |
| INV-23 | Authorization Model ID 是 OpenFGA 请求的校验与解释上下文，不是 tuple 的版本标签。F048 必须保持现有 Store ID 不变：仍合法的 system/组织/shared/parent tuple 原地复用；新 tuple 写入同一 Store；已迁移资源的旧四档/废弃 relation tuple 在启服前删除。启服后所有实例只固定新 model ID，旧 model ID 仅为 OpenFGA 不可删除历史；不得启用 auto latest、dual/legacy client 或创建第二 Store | AuthorizationModelRelease, PermissionMigrationRun | F048 |
| INV-24 | 标准模型按等级累计动作；自定义模型只产生其显式选择的动作，派生等级只用于分类和可授予边界，不能自动补齐该等级及以下的其他动作。本不变量替代 v2.5.0 INV-7 在 F048 资源权限范围内的旧四档金字塔语义 | PermissionAction, PermissionModel | F048 |
| INV-25 | user-owned 资源创建仍必须通过 `PermissionService.authorize()` 为创建者建立受保护 owner Grant 并遵守失败补偿；一个资源可以同时有多个 owner，其他 owner 作为独立普通来源存在。F048 启服后不再要求继续写旧资源 `owner` tuple。只有经资源 adapter 代码 allowlist 与 canonical business predicate 双重确认的 platform system-owned 资源可以不伪造用户 owner，并继续只由 C4 system identity 管理。OQ-07 已选择 A：F048 启服时退役既有 F018 owner 交接 API，本期不实现 protected owner transfer；创建者 protected owner 不可通过普通成员接口删除或转让 | ProtectedPermissionAssignment, PermissionGrant | F048 |
| INV-26 | F048 的 Alembic revision 只允许 MySQL/DM8 schema DDL，不得读取、转换、回填、去重、清理或 seed 旧权限数据，也不得访问 OpenFGA。所有旧 Config、业务事实和 tuple 数据迁移必须由运维人员在已启动但 F048 未就绪的 backend 容器内，通过 `src/backend/scripts/` 下的专用脚本于 schema upgrade 成功后显式执行；不得由 API、Celery 或应用启动钩子自动触发 | PermissionMigrationRun, PermissionMigrationItem | F048 |
| INV-27 | 权限模型、Grant、Grant 主体和权限模式以规范化 MySQL/DM8 关系表为控制面真相；组织成员、系统身份和资源状态以各自 Owner 业务域的 canonical 事实为真相；OpenFGA 是这些事实发布后的唯一权限执行面。每条有效资源可见结果必须可追溯到至少一个当前有效来源；模型停用只禁止新增或变更授权，已有授权保持有效；模型删除前必须撤销或替换全部绑定，并在引用、来源投影和残留 tuple 清零后才允许删除。来源撤销只清除该来源贡献，并保证 Check 与可见资源枚举一致，不得删除其他仍有效来源的可见性 | PermissionModel, PermissionGrant, PermissionGrantAssignee, AuthorizationModelRelease | F048 |

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
| F004-rebac-core | v2.5.0 INV-2 的旧 `owner` tuple 形状由 INV-25 的 user-owned 受保护所有者 Grant 投影替代；显式 system-owned 资源不伪造用户 owner；INV-7 的四档金字塔权限语义由 INV-24 替代。统一入口、创建者安全保证、失败补偿和 fail-closed 约束继续有效；F048 多 tuple 原子补偿由 operation ledger 承担，旧 `failed_tuple` 仅保留给 legacy 单 tuple 路径，并同步修订 Constitution C4 的物理表措辞 |
| F006-permission-migration | v2.4→v2.5 的历史迁移结果成为 F048 的迁移来源之一；F048 不修改其历史事实 |
| F007-resource-permission-ui | 成员管理升级为模型、来源、等级、继承/自定义模式和受保护状态展示 |
| F008-resource-rebac-adaptation | 资源生命周期继续统一接入权限服务，但资源存在性/租户/状态/父级等业务校验留在各业务 Service；权限领域只接收已验证上下文并执行 F048 授权 |
| F027/F036/F040 | cursor、批量候选和请求内性能约束继续有效；旧 Config binding / 第二 PDP 的优化路径在切换后退役 |
| F013/F017 | `system`、`tenant`、`department`、`user_group`、`shared_with` 等系统关系继续保留；不得被误转为普通资源 Grant |
| F018-resource-owner-transfer | 当前实现先提交资源 `user_id`、再删除旧/写入新 owner tuple，失败依赖 `failed_tuple` 补写；同时不更新 knowledge_space/channel CREATOR membership，且无已接入前端。OQ-07 已选择 A：F048 启服时退役其 API/Service 调用路径，本期不重构 owner transfer；历史差异按 preservation-first 迁移 |

---

## 已分配模块编码（MMMEE）

> 新 Feature 分配错误码时，必须检查此表避免冲突。

| 模块编码 (MMM) | 模块 | Owner Feature |
|----------------|------|---------------|
| —（不新增） | 既有功能体验优化与引用溯源 | F043 复用工作流/报告既有错误响应；F044 验证失败是业务结果（状态=异常）而非错误响应，不占码；F045/F046 纯前端；F047 复用 citation 子系统与 F029 权限过滤的既有错误响应 |
| 250 | ReBAC 权限 Catalog、Grant、投影、迁移与完整枚举 | F048；25001～25014，具体语义见 F048 Design §6.3 |

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-07-24 | 初始化 v3.0.0-beta1 契约；登记 F043~F046 四个功能体验优化 Feature（均无新增领域对象；新增 INV-8 报告模板变量以节点 ID 为键 + 永久兼容旧格式；均不新增错误码） | F043 / F044 / F045 / F046 |
| 2026-07-27 | 登记 F047 灵思任务模式引用溯源（**由 v2.6.0 F040 迁入并改编**——v2.6.0 的 F040 编号已被 `040-rebac-read-path-perf-rollout` 占用，spec/design 内容未变，仅改版本与编号）：表 1 标"无新增领域对象"（在既有 citation 子系统上加灵思接线，写入仍经 `save_message_citations`）、表 3 记跨版本依赖 F035/F029（v2.6.0 存量已上线）；复用 F029 `view_file` 过滤守 v2.6.0 **INV-7**；无新增错误码/对外 API/不变量/alembic 迁移；分期 Phase 1 应用内预览行内角标（KB+Web）/ Phase 2 下载件烘焙可见引用（延后） | F047 |
| 2026-07-28 | 将 ReBAC 权限模型与 Grant 升级 Spec 从独立 v3.0.0 草案并入 v3.0.0-beta1，并因 F043 已占用重编号为 F048；登记权限领域对象、INV-9～INV-25、历史契约替代关系、依赖与迁移边界 | F048、F004/F006/F007/F008/F013/F017/F027/F036/F040 |
| 2026-07-28 | F048 Design 登记 PermissionCatalogRelease、PermissionCatalogProjectionTuple、PermissionProjectionOperation/Tuple，并分配错误码模块 250；Catalog 是业务策略快照，区别于 OpenFGA AuthorizationModelRelease；F048 原子投影 ledger 替代 legacy `failed_tuple` 的物理补偿形态但不降低 C4 保证；INV-25 明确 user-owned protected owner 与显式 system-owned 例外 | F048 / F004 |
| 2026-07-29 | 回写 F048 Design 反馈：dashboard 纳入统一迁移；文件预览不设动作、下载检查 `download`；业务 Service 持有资源数据边界；动作变化全量重算模型；INV-25 允许多 owner 并登记 F018 OQ-07 | F048 / F008 / F018 |
| 2026-07-29 | F048 OQ-07 选择 A，启服时退役 F018；INV-18 固化停服直迁、无独立预演/回滚和失败前向修复合同 | F048 / F018 |
| 2026-07-29 | 纠正 INV-18/23 迁移拓扑：沿用现有 Store、只运行新 model；同 Store 原地转换并在启服前退役旧 tuple/Config，不创建或维护第二 Store/model runtime | F048 |
| 2026-07-29 | 新增 INV-26 并修订 INV-18：Alembic revision 仅负责 MySQL/DM8 schema DDL；F048 旧权限数据和 OpenFGA tuple 迁移由 `src/backend/scripts/` 专用脚本执行，禁止 migration/lifespan/API/Celery 混入数据迁移 | F048 |
| 2026-07-31 | 简化 F048 升级顺序：沿用既有“更新镜像并启动→容器内执行数据脚本”流程；旧 model 下进程只进入不就绪运维态并由应用门禁自动拒绝 HTTP/WS，脚本通过后重启一次即自动恢复访问，不再要求先停止容器、人工切换入口或设置停服变量 | F048 |
| 2026-08-13 | 基于 BENCH-01 追加数据驱动的列表权限策略与来源收敛合同：可见 ID 优先和业务候选优先均为合法路径，按代表性实际业务数据中的候选规模、可见/继承比例、分页扫描放大和端到端成本决定并允许重新评审；个人可见列表不因超管身份自动扩大；明确 SQL/Owner 业务域控制面真相与 OpenFGA 唯一执行面边界，并新增 INV-27 | F048 |
| 2026-08-13 | 为 StreamedListObjects 未完整终止或超过业务容量上限分配 25014，禁止把枚举前缀作为成功全集返回 | F048 |
| 2026-08-13 | 纠正 F048 可见投影迁移拓扑：F048 尚未上线，不新增旧 F048 到新 F048 model 的二次迁移；原 PermissionMigrationRun/Item 从旧 Config/四档关系和 Owner 事实直接生成最终单槽浅层 visible model、Grant/Assignee、PermissionVisibleSourceProjection 与 tuple | F048 |
| 2026-08-13 | 明确模型停用/删除语义：停用只禁止新增或变更授权，已有 Grant 保持有效；删除必须先清零或替换全部绑定并完成残留投影对账。因停用不再触发批量撤权，F048 可见执行投影采用单槽浅层 `visible`，不引入 A/B 槽与运行时 switch | F048 |
