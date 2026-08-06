# Release Contract — v2.5.0-sg

> 本文件是首钢定制版本 v2.5.0-sg 的领域归属与全局约束权威来源。
> 本版本继承 [v2.5.0 release contract](../v2.5.0/release-contract.md) 的全部不变量；
> 本文件仅补充首钢定制功能新增的对象、依赖和不变量。
> 所有 v2.5.0-sg 的 `spec.md` 在编写和评审时必须同时对照两份契约。

---

## 表 1：领域对象归属

每个领域对象只能有一个 Owner Feature，负责定义该对象的写入行为。
其他 Feature 只能读取、引用，或调用 Owner Feature 的 Service。

### 本版本新增或扩展对象

| 领域对象 | Owner Feature | 说明 |
|---------|---------------|------|
| PortalRecommendationFileProjection | F056-home-personalized-recommendation | 文件业务域、空间、推荐资格、权限范围和投影版本的在线推荐投影 |
| PortalRecommendationPoolState | F056-home-personalized-recommendation | Redis 中租户级业务域池、通用兜底池、热门轮换状态及 active pool version |
| PortalUserRecommendationState | F056-home-personalized-recommendation | Redis 中用户兴趣 Top 50、近 90 天浏览状态、行为版本和短期 Top N |
| ShougangPortalAdminConfig（扩展） | F056-home-personalized-recommendation | 对齐远端 `domains[].department_ids`，并增加推荐数量、算法、影子模式和灰度参数 |
| PortalTelemetryEvent（扩展） | F056-home-personalized-recommendation | 新增 `portal_search`；阅读事件增加推荐场景和入口来源 |

### 复用对象（Owner 不变）

| 领域对象 | 现有 Owner | Feature 使用方式 |
|---------|------------|--------------|
| Department / UserDepartment | department 模块（F002） | 只读取唯一主部门及部门 ID，不修改组织树和用户部门关系 |
| Knowledge / KnowledgeFile / KnowledgeDocument / KnowledgeDocumentVersion | knowledge 模块 | F056 读取文件、空间、版本和状态并由写入事件触发投影刷新；F057 只通过既有知识文件清理边界删除已确认的部门重复文档；F059 通过 knowledge 模块领域服务扩展逻辑入口/清理字段、文档内容代次和入口级投影状态，转移管理归属并维护版本链，不取得这些模型的所有权 |
| PermissionTuple / AuthorizationModel | permission 模块（F004） | F056 的最终文件权限检查统一调用既有权限服务；F057 只通过权限模块既有清理能力移除目标部门文件 tuple；F059 只通过 Permission Service 校验及迁移入口授权，复用既有 `share_file` |
| Config | config 模块 | 通过既有首钢门户聚合配置 Service 读写，不新建第二配置事实源 |
| BaseTelemetryEvent | telemetry 模块 | ES 继续保存原始浏览和搜索事件；F056 只扩展门户事件类型和派生状态 |
| ApprovalScenario / ApprovalInstance / ApprovalTask | approval 模块 | F059 复用既有发布审批，并通过 approval 模块注册固定两节点的部门文件分享审批，不旁路写审批状态 |
| ShareLink | share_link 模块 | F059 禁止创建新的知识文件链接/邀请码分享；既有记录保持原失效和撤销规则，访问时通过 knowledge 模块动态解析当前入口 |

**规则**：

- `domains[].department_ids` 业务域映射不得写 OpenFGA tuple，也不得扩大可见空间或文件范围。
- 推荐投影与 Redis 池是派生数据，不能成为权限事实源。
- F056 不得为 `KnowledgeFile` 增加重复业务域源字段，必须复用现有文件编码/`split_rule` 解析。
- F057 不取得 Knowledge、KnowledgeFile、PermissionTuple 或 PortalRecommendationFileProjection 的所有权；只能复用各 Owner 的既有删除/失效边界，不新增旁路写入协议。
- F059 不新增领域表；展示入口、入口级投影恢复状态与清理 tombstone 复用 `KnowledgeFile`，管理链和 canonical 内容代次复用 `KnowledgeDocument`，写入必须调用 knowledge 模块领域 Service。
- F059 的发布/分享关系不得以 `KnowledgeFile.user_metadata`、ES 或 Milvus 作为事实源。
- 新增领域对象或改变 Owner 前必须先更新本表。

---

## 表 2：跨 Feature 不变量

除继承 v2.5.0 的 INV-1～INV-15 外，v2.5.0-sg 新增：

| ID | 不变量描述 | 涉及领域对象 | 来源 spec |
|----|------------|--------------|-----------|
| INV-SG-1 | 用户业务域只从当前租户聚合配置 `domains[].department_ids` 精确匹配唯一主部门；不读取次要部门，不向父部门或子部门继承 | ShougangPortalAdminConfig, UserDepartment | F056 |
| INV-SG-2 | 业务域匹配只参与推荐打分，不授予 `view_space` 或 `view_file`，也不改变 `visible_space_ids` | ShougangPortalAdminConfig, PermissionTuple | F056 |
| INV-SG-3 | 已读文章不从候选中排除，只根据最近浏览时间施加可配置算法中定义的固定四档扣分 | PortalUserRecommendationState | F056 |
| INV-SG-4 | 个性化候选必须先轻量打分，再对最终返回候选做权限检查；非公共空间执行完整 `view_file` 校验 | PortalRecommendationFileProjection, PermissionTuple | F056 |
| INV-SG-5 | 公共空间仅复用已确认的公开快速路径；非公共空间不能以投影、池命中或业务域匹配替代权限检查 | PortalRecommendationFileProjection, PermissionTuple | F056 |
| INV-SG-6 | 无权文件的 ID、标题、摘要、标签和路径不得出现在响应或普通日志中；权限异常默认失败关闭 | KnowledgeFile, PortalRecommendationFileProjection | F056 |
| INV-SG-7 | 第一阶段 custom ACL 文件不得进入共享池；投影滞后时仍由最终权限校验阻止越权 | PortalRecommendationFileProjection | F056 |
| INV-SG-8 | 搜索原文和浏览原始事件以 ES 为事实源；Redis 只保存近 90 天浏览时间、派生兴趣、版本和短期结果，不持久化原始搜索词 | PortalTelemetryEvent, PortalUserRecommendationState | F056 |
| INV-SG-9 | 所有推荐 Redis key 必须包含租户前缀；Celery 任务必须恢复租户上下文并沿用租户 fan-out | PortalRecommendationPoolState, PortalUserRecommendationState | F056 |
| INV-SG-10 | 首钢门户配置只通过既有 `/api/v1/shougang-portal/config` 聚合接口同步；配置按当前租户持久化，版本由 BiSheng 服务端在租户内单调递增；`domains[].department_ids` 是唯一部门业务域事实源，不复制到独立字段或表 | ShougangPortalAdminConfig | F056 |
| INV-SG-11 | 匿名首页保持现有公共推荐与公共缓存；登录用户失败降级必须携带当前用户 token，禁止使用系统账号代取 | ShougangPortalAdminConfig, KnowledgeFile | F056 |
| INV-SG-12 | 热度参数变更必须使用双版本池重算并原子切换 active pool version；重算完成前继续使用上一有效版本 | PortalRecommendationPoolState, ShougangPortalAdminConfig | F056 |
| INV-SG-13 | 公共知识空间只作为重复文档见证，任何预览、执行、失败恢复和重试路径都不得删除或修改公共文件及其版本链 | Knowledge, KnowledgeFile | F057 |
| INV-SG-14 | 重复判定只比较公共与部门当前成功文件的非空 MD5 精确值；公共历史版本不得作为见证，部门命中后以完整逻辑文档为删除单元 | KnowledgeFile | F057 |
| INV-SG-15 | 部门重复文档清理必须默认 dry-run，显式 apply 前逐单元重校验；多租户启用时拒绝运行，跨存储失败必须停止并保留可重试报告 | KnowledgeFile, PermissionTuple, PortalRecommendationFileProjection | F057 |
| INV-SG-16 | 一个 `KnowledgeDocument` 在同一租户内至多有一个当前 manager、在同一知识空间至多有一个活跃入口；manager 由当前主版本物理文件推导，发布前驱必须形成无环单线链，share 永不进入管理链 | KnowledgeDocument, KnowledgeFile | F059 |
| INV-SG-17 | 同一物理版本只保留一个 `KnowledgeFile` 和一组 MinIO 对象；publish/share 逻辑文件不得拥有物理对象或计费容量，管理权转移不得复制或重命名 MinIO 对象 | KnowledgeFile, KnowledgeDocumentVersion | F059 |
| INV-SG-18 | 发布只能由当前 manager 按 PERSONAL→TEAM/TEAM_KS/DEPARTMENT/PUBLIC、TEAM/TEAM_KS→DEPARTMENT/PUBLIC、DEPARTMENT→PUBLIC 方向执行；删除当前 manager 时只能恢复 `KnowledgeDocument.predecessor_logic_file_id` 指向的直接前驱 | KnowledgeDocument, KnowledgeFile, ApprovalInstance | F059 |
| INV-SG-19 | 分享只能从部门 manager/publish 入口流向另一个部门空间，必须经过分享方和接收方两次显式管理员审批；share 逻辑文件不转移管理权且不得再次发布或分享 | KnowledgeFile, ApprovalScenario, ApprovalInstance | F059 |
| INV-SG-20 | 入口操作必须同时满足 OpenFGA 本地权限和入口类型硬约束；复用既有 `share_file` 且权限异常失败关闭，任何自定义 editor/owner 授权都不能让非 manager 修改 canonical 内容或让 share 入口继续扩散 | KnowledgeFile, PermissionTuple | F059 |
| INV-SG-21 | ES/Milvus 入口副本是可重建派生数据，必须携带 canonical document/version、入口文件 ID/type 和 generation；搜索和多库问答在入口权限过滤后按 canonical 身份去重，投影不得授予权限 | KnowledgeDocument, KnowledgeFile | F059 |
| INV-SG-22 | 单库文件量按活跃入口计数，跨库总量按 canonical document 去重，存储容量只累计真实物理版本一次；逻辑文件和 ES/Milvus 派生副本不计用户容量 | KnowledgeDocument, KnowledgeFile | F059 |
| INV-SG-23 | 新的知识文件链接/邀请码分享必须停止创建；上线前已创建的链接在原失效、密码、邀请码、下载和撤销规则下继续访问，并动态解析当前业务文档入口 | ShareLink, KnowledgeDocument, KnowledgeFile | F059 |
| INV-SG-24 | canonical 内容变化与 `KnowledgeDocument.content_generation`、入口变化与对应 `KnowledgeFile` 的期望内容/入口代次必须在同一关系事务中提交；Worker 按入口期望/已应用双代次和 lease/CAS 幂等处理并恢复租户上下文，Celery 消息仅加速，定时任务必须补偿未完成或失败状态且不得伪报同步完成 | KnowledgeDocument, KnowledgeFile | F059 |
| INV-SG-25 | F059 不扫描、推断、合并或回填上线前旧发布副本；新不变量只约束上线后由 F059 创建的逻辑入口关系 | KnowledgeDocument, KnowledgeFile | F059 |
| INV-SG-26 | `knowledge_celery` 只允许标题提取、首次文件解析和文件解析重试三个白名单任务；PDF Artifact 继续使用 `knowledge_pdf_celery`，工作流/审批继续使用 `workflow_celery`，其余后台任务进入默认 `celery` | Celery task routing | F060 |

INV-SG-1 的“不继承”只约束推荐业务域特征，不修改基线 INV-12 中部门管理员的权限继承语义。

**规则**：

- 新增不变量：先在本表追加，再写对应 AC。
- 若修改继承的 v2.5.0 不变量，必须回写上游契约并重新评审受影响 spec。
- spec 中任何验收标准与上述不变量冲突时，评审不通过。

---

## 表 3：Feature 依赖图

| Feature | 依赖（必须先完成） | 说明 |
|---------|-------------------|------|
| F056-home-personalized-recommendation | F001-multi-tenant-core | 依赖租户上下文、Redis 隔离和 Celery tenant fan-out |
| F056-home-personalized-recommendation | F002-department-tree | 依赖 Department/UserDepartment 和主部门标识 |
| F056-home-personalized-recommendation | F004-rebac-core, F008-resource-rebac-adaptation | 依赖统一权限服务和知识文件 `view_file` 校验 |
| F056-home-personalized-recommendation | 既有 shougang_portal_config / telemetry / knowledge 模块 | 复用聚合配置、ES 遥测、文件浏览和门户权限上下文 |
| F057-department-space-document-dedup | 既有 knowledge 模块 | 依赖空间 scope、文件状态、文档版本和跨存储删除能力 |
| F057-department-space-document-dedup | F004-rebac-core | 依赖既有文件权限 tuple 清理边界 |
| F057-department-space-document-dedup | F056-home-personalized-recommendation | 删除目标文件时清理 F056 拥有的推荐投影和派生缓存，不改变其所有权 |
| F059-knowledge-publish-share-unification | 既有 knowledge / version / tag / search / QA / stats 模块 | 依赖业务文档版本链、知识空间目录、MinIO、ES/Milvus、水印下载和统计能力 |
| F059-knowledge-publish-share-unification | F004-rebac-core, F008-resource-rebac-adaptation | 依赖统一入口权限检查、`share_file` 和 OpenFGA 失败补偿 |
| F059-knowledge-publish-share-unification | 既有 approval / share_link 模块 | 复用发布审批，新增固定两节点分享审批，并兼容已有知识文件分享链接 |
| F060-knowledge-parse-queue-isolation | 既有 Celery Worker 与 knowledge 文件解析任务 | 只调整任务路由所有权，不修改任务协议、解析实现或存量消息 |

```text
F001 ──┐
F002 ──┼──> F056-home-personalized-recommendation
F004 ──┤
F008 ──┘

knowledge ──┬──> F057-department-space-document-dedup
F004 ───────┤
F056 ───────┘

knowledge/version/search/QA/stats ──┬──> F059-knowledge-publish-share-unification
F004/F008 ──────────────────────────┤
approval/share_link ────────────────┘
```

---

## 已分配模块编码（MMMEE）

本版本新增 Feature 不分配新模块编码。参数校验使用 schema/CLI 校验错误；知识推荐和清理脚本复用既有模块边界，不新增与现有编码冲突的错误码。

| 模块编码 | 模块 | 本 Feature 用途 |
|---------|------|----------------|
| 109 | knowledge | 文件与知识空间既有错误；F059 使用 `10995` 关闭新链接/邀请码分享 |
| 170 | telemetry | 门户遥测既有错误 |
| 180 | knowledge_space | 首钢门户文件浏览既有错误；F059 使用 `18094`～`18099` 表达入口冲突、入口策略、并发和删除阻断 |

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-07-15 | 建立 v2.5.0-sg 契约，登记 F056 对象、依赖及推荐权限不变量 | F056 |
| 2026-07-16 | 对齐远端业务域部门绑定实现，删除独立绑定领域对象和表，改用 `domains[].department_ids` 唯一配置源 | F056 |
| 2026-07-19 | 登记 F057 对既有知识、权限和推荐投影的复用边界，并增加公共数据保护、判重与安全执行不变量 | F057 |
| 2026-07-27 | 登记 F059 对 `KnowledgeFile` 逻辑入口及 `KnowledgeDocument` 状态驱动投影补偿的扩展边界；不新增领域表，并增加单实体发布、同级分享、权限、检索去重、容量和旧链接兼容不变量 | F059 |
| 2026-08-05 | 登记 F060 的 Celery 队列所有权：`knowledge_celery` 仅承载三个文件解析白名单任务 | F060 |

---

## F058 知识运营实时看板补充契约

### 新增或扩展对象归属

| 领域对象 | Owner Feature | 说明 |
|---|---|---|
| RealtimeKnowledgeFileProjection（扩展） | F058-realtime-knowledge-dashboard | 复用 `mid_knowledge_space_content_stat`，补充空间类型、知识分类、业务域与主部门维度 |
| RealtimeQaQuestionFact | F058-realtime-knowledge-dashboard | 专家问答、智能问答和文档 AI 对话的幂等成功问题事实 |
| UserDailyParticipation | F058-realtime-knowledge-dashboard | 用户自然日登录状态、登录次数和有效员工分母 |
| DashboardPivotTable | F058-realtime-knowledge-dashboard | 数据看板通用交叉表组件，不包含知识库业务硬编码 |
| DashboardDimensionFilter | F058-realtime-knowledge-dashboard | 可搜索多选维度筛选及目标图表绑定协议 |

### F058 不变式

- **INV-SG-16**：统计投影和字段选项不得成为资源授权事实源；看板资源访问继续由后端校验，统计数据范围由看板配置的租户、部门、知识空间等维度筛选决定，查询服务不得按当前用户隐式追加数据集范围条件。
- **INV-SG-17**：文件总数只包含公共库、部门库、团队库、科室库和普通个人库中的当前成功实体主版本文件；文件夹、失败、处理中、“我的收藏”和历史版本不得计入。
- **INV-SG-18**：同一成功用户问题只生成一个问答事实；失败、重试和重新生成不得重复计数。
- **INV-SG-19**：参与人数按 Asia/Shanghai 自然日和 user_id 去重；Token 刷新不得写入登录事实。
- **INV-SG-20**：维度筛选只影响显式绑定的图表；旧查询组件和旧图表配置必须保持兼容。

### 依赖

- F058 依赖 F002 的主部门与部门树、F004/F008 的统一资源权限，以及 F056 已扩展的门户遥测与文件业务域解析。

### 变更历史

| 日期 | 变更内容 | 影响范围 |
|---|---|---|
| 2026-07-27 | 登记 F058 实时文件、问答、参与度投影，以及通用维度筛选和交叉表组件 | F058 |
