# Release Contract — v2.6.0

> 本文件是 v2.6.0 版本级领域归属与全局约束的权威来源。
> **所有 spec.md 在动笔前必须先阅读本文件。**
> 每次 spec 评审时，必须对照本文件检查一致性。

---

## 表 1：领域对象归属

每个领域对象只能有一个 Owner Feature，负责定义该对象的写入行为
（创建、更新、删除）。其他 Feature 只能"读取"或"引用"该对象。

| 领域对象 | Owner Feature | 说明 |
|---------|--------------|------|
| ApprovalScenario / ApprovalRouteRule / ApprovalFlowDefinition / ApprovalFlowVersion / ApprovalNodeDefinition | F025-approval-center-unification | 审批场景配置、条件分支、流程定义、流程版本与顺序节点 |
| ApprovalInstance / ApprovalTask / ApprovalException / ApprovalOutbox / ApprovalActionLog | F025-approval-center-unification | 审批实例、审批任务、异常、业务执行队列、审批时间线 |
| ApprovalNotificationOutbox | F054-file-publish-submit-performance | 发布申请初始待审批通知的独立可靠投递队列；不得推进审批实例业务执行状态 |
| UserMenuAccess | F025-approval-center-unification | 菜单权限申请通过后的用户级菜单授权与撤回记录 |
| ChannelAuthorizationWrite | F026-channel-active-authorization | 频道资源主动授权、撤销授权、频道 relation-model binding 写入与清理行为 |
| SpaceChannelMember(channel relation/source fields) | F026-channel-active-authorization | `space_channel_member` 中 `business_type='channel'` 的四档关系与授权来源字段；不拥有知识空间成员关系 |
| PortalCourse / PortalCourseVideo | F062-portal-course-management | 首钢门户课程目录、课程内标签值对象、视频来源及其创建、更新、启停、排序和删除行为；标签不作为独立领域实体 |
| PortalCourseVideoProgress | F062-portal-course-management | 按租户、登录用户和视频唯一覆盖的播放进度及完成终态 |
| PortalCourseMediaCleanup | F062-portal-course-management | 课程上传对象的 provisional、替换、删除清理任务及最终一致重试 |
| KnowledgeFilePdfArtifact | F063-unified-pdf-artifact | 知识文件统一 PDF 派生产物的当前 generation、独立处理状态、对象引用、重试信息和删除清理；不拥有 KnowledgeFile 解析状态、预览或下载行为 |
| Tag.reviewer_id / Tag.review_time / ReviewTag.reviewer_id（扩展） | F079-tag-management-console | 标签审核留痕字段：谁审的、什么时候审的。审核通过搬运 `review_tag` → `tag` 时一并携带。不取得 `Tag` / `ReviewTag` 本身的创建、命名、打标或 Link A/Link B 解析行为所有权 |
| DeveloperToken.file_sync_rule（扩展） | F066-token-configured-filelib-sync | 每个开发者 Token 最多一份完整的文件同步业务配置；只保存稳定分类/业务域编码、知识空间 ID、可空目录 ID、固定/动态模式及动态来源，不保存路径快照，不取得门户配置、部门、知识空间、目录或文件的所有权 |
| UserPointAccount / UserPointLog / PointRule / PointCopy / PointRankSnapshot / PointSyncOutbox / PointFavoriteTierAward | F070-points-system | 积分账户、append-only 流水、规则/说明文案、排行快照、外部同步 outbox、收藏阶梯已授档位；站内信文案为代码常量（无模板表）；不拥有知识文件/审批/站内信本体写所有权 |
| Department.org_level（扩展） | F070-points-system | 仅拥有部门节点组织层级标签（company/dept/office/squad）的写入与「指定唯一公司根 → 级联打标」行为；不拥有部门树结构、用户挂载、组织同步 |
| Department.short_name（扩展） | F082-department-short-name | 部门简称字段的创建、修改、清空与本地维护语义；不取得 F002 对 Department 其他 CRUD、物化路径和名称唯一性的所有权，不改变 F009/F014/F015 的同步事实源 |

**规则**：
- 非 Owner Feature 的 AC 中不得出现其他对象的"创建/修改/删除"行为，只能"读取"或"调用" Owner 的 Service
- 新增领域对象时必须先更新本表

---

## 表 2：跨 Feature 不变量（INV-N）

全局业务约束，任何 spec 的 AC **不得与之矛盾**。

| ID | 不变量描述 | 涉及领域对象 | 来源 spec |
|----|-----------|------------|---------|
| INV-1 | 审批事实源统一为 `approval_instance` / `approval_task`；站内信只负责提醒和跳转，不作为审批状态真相来源 | ApprovalInstance, ApprovalTask, InboxMessage | F025 |
| INV-2 | 审批中心所有新表都必须带 `tenant_id`，并遵守现有多租户隔离规则；申请人/审批人/管理员的数据可见性不能跨租户 | Approval* | F025 |
| INV-3 | 审批通过不等于绕过业务安全检查；handler 执行业务动作前仍需复用原业务校验逻辑 | ApprovalOutbox, 业务资源模块 | F025 |
| INV-4 | 菜单权限申请通过后只写用户级菜单授权，不修改角色菜单权限；用户有效菜单 = 角色菜单 ∪ 个人授权 ∪ 管理员权限 | UserMenuAccess, RoleAccess | F025 |
| INV-5 | 流程变更采用版本快照模型；已发起实例继续使用其创建时的流程版本，新配置仅影响后续新申请 | ApprovalFlowVersion, ApprovalInstance | F025 |
| INV-6 | 走 ReBAC 过滤的高频列表接口采用 cursor-based 分页：请求用 `cursor` 透传上一页位置，响应含 `has_more: bool` 与 `next_cursor: string\|null`，**不再返 `total` / `page_num`**；后端不得为算 total 而扫描全部 batch；cursor 编码统一走 `common/cursor.py`（schema `{"v":1, "k":[...]}`，base64url）；cursor 解析失败必须明确报错（`*InvalidCursorError`），不得静默 fallback 首页。**定向豁免**：`/api/v1/workstation/tags/console/search` 与 `/review/search`（F079，2026-08-07 批准），理由与失效条件见变更历史 | 所有走 ReBAC 过滤的列表接口 | F027 |
| INV-7 | `DeveloperToken.file_sync_rule` 只决定文件分类、业务域和目标知识空间/目录的解析方式，不授予任何资源权限；管理选项、保存和统一同步运行时均按 Token 绑定用户校验最终空间根目录或目录的 `upload_file` 权限，且请求仍须先通过 Token 状态、IP、路由白名单和限流 | DeveloperToken, Knowledge, KnowledgeFile | F066 |
| INV-8 | 动态业务域只读取当前租户首钢门户聚合配置中的 `domains[].department_ids`；Token 仅保存业务域编码引用，不复制部门与业务域映射，不建立第二配置事实源 | DeveloperToken.file_sync_rule, ShougangPortalAdminConfig | F066 |
| INV-9 | 文件同步配置缺失、不完整、空间/目录引用失效、跨租户、目录不属于所选空间、绑定用户无目标节点上传权限、动态来源参数缺失、动态解析无唯一结果或业务域与目标空间未绑定时必须失败关闭；不得回退到根目录、请求中的其他 ID、调用人默认值、任意知识空间或旧接口固定规则 | DeveloperToken.file_sync_rule, Department, Knowledge, KnowledgeFile | F066 |
| INV-10 | F069 的四个 Filelib 查询接口必须先通过 Developer Token 调用资格校验；可选 `external_id` 只在 Token 校验成功后决定业务用户、权限和全局数据作用域，缺失时回退 Token 绑定用户。显式值必须全局唯一匹配有效用户，不存在、禁用或重复均统一失败关闭；目标用户完整继承角色、ReBAC/RBAC 和全局超级管理员权限。该不变量仅适用于未启用租户功能的部署，启用多租户前必须重新评审，禁止直接沿用全局作用域。 | DeveloperToken, User, Knowledge | F069 |
| INV-11 | 积分流水 `user_point_log` 为 append-only：禁止 UPDATE/DELETE；纠错仅追加冲正或调分流水；账户余额与流水在同一事务内更新，可用流水重算对账 | UserPointAccount, UserPointLog | F070 |
| INV-12 | 自动记分必须带租户内唯一 `idempotency_key`；重试/重复事件不得双计；平台超级管理员账号不参与自动发放与激励榜 | UserPointLog, User | F070 |
| INV-13 | `department.org_level` 全租户（或约定作用域）至多一个 `company` 节点；级联打标不得改写 `parent_id`/`path`/用户挂载；组织标签与知识空间 level 不得强绑 | Department.org_level, KnowledgeSpace | F070 |
| INV-14 | 积分规则配置、全站调分与说明文案仅平台超级管理员可写；公共库管理员不得改规则；站内不做申诉流程；积分站内信文案为代码常量不可运营配置 | PointRule, PointCopy, UserPointLog | F070 |
| INV-15 | 首钢门户范围内的动态部门展示统一为 `trim(short_name) or name`，部门路径逐级应用同一规则，搜索同时匹配正式名称和简称，展示排序按展示名称稳定排序；既有 `name` / `department_name` 继续表达正式名称，部门 ID、权限、同步匹配及历史审批快照不得被简称替代或批量改写。该不变量不适用于 Platform 组织架构、首页无部门 ID 的硬编码积分榜、Filelib/同步/遥测事实字段。 | Department, User, Knowledge, Permission, Approval, QAExpert | F083 |
| INV-16 | `POST /api/v2/filelib/retrieve` 仅可为已通过 Developer Token 校验、且已按 F069 业务用户上下文通过文件 `view_file` 可见性过滤的检索结果签发原文件预签名 URL；签发不再要求 `download_file`，也不进入门户下载额度、审计、水印或分发限制链路。URL 是签发后 7 天内无需 Developer Token 的 Bearer 凭证，必须只指向原文件对象、不得记录完整签名；无权文件不得进入响应，文件记录或原对象缺失时对应 URL 必须为空。 | DeveloperToken, KnowledgeFile, Permission, MinIO | F084 |
| INV-17 | 知识库 / 文件夹手动顺序只写已有 `knowledge.sort_weight` 与 `knowledgefile.sort_weight`；写路径资格由毕昇 `KnowledgeSpaceService` 按角色矩阵计算并在写接口再检，Client 下发的 `can_reorder*` 不得作为唯一鉴权。系统管理员既有排序能力不得回退。部门管理员只能移动管辖部门（含下级）在 `department_knowledge_space` 上已绑定的团队/科室库。运营岗不得写入 `is_admin()`。 | Knowledge, KnowledgeFile, DepartmentKnowledgeSpace | F106 |

**规则**：
- 新增不变量：先在此表追加，再写 AC
- 修改不变量：必须列出 Impacted Specs 清单，逐一回写并重新评审
- 冲突检测：若 AC 与不变量矛盾，spec 评审不通过

---

## 表 3：Feature 依赖图

| Feature | 依赖（必须先完成） | 说明 |
|---------|-----------------|------|
| F025-approval-center-unification | F005, F011, F012, F013 | 依赖菜单审批模式、多租户、租户解析与权限隔离基线 |
| F026-channel-active-authorization | F006, F013 | 依赖统一 ReBAC/OpenFGA 授权与多租户权限隔离基线 |
| F027-rebac-list-perf-optim | F004, F008, F011/F012/F013 | 性能优化型；不新增领域对象，仅修改高频列表接口分页协议与部门树 member_count |
| F054-file-publish-submit-performance | F025 | 复用统一审批事实和任务模型；新增独立通知 outbox，不修改业务执行 outbox 语义 |
| F062-portal-course-management | F012, F017, F019 | 依赖租户解析、租户共享存储与管理员租户范围基线；复用现有首钢门户会话/BFF |
| F063-unified-pdf-artifact | F017, F056 | 依赖租户共享存储路径与 Celery 单循环运行时基线；新增独立 PDF Artifact，不修改知识解析、预览或下载契约 |
| F064-portal-watermarked-pdf-download | F063 | 只读 F063 提供的当前有效 `KnowledgeFilePdfArtifact` 引用；不创建、更新或删除统一 PDF 产物，不取得其写所有权 |
| F066-token-configured-filelib-sync | F044, F047, F060 | 扩展开发者 Token 配置，收口 F047 的 11 个固定规则接口，复用 F060 动态空间解析器、Knowledge 目录只读契约与 PermissionService；不复制门户业务域配置或授权事实 |
| F079-tag-management-console | F013 | 依赖多租户权限隔离基线；复用 workstation 现有审核标签可见空间解析与 knowledge 标签库服务；只为 `tag` / `review_tag` 追加审核留痕字段，不新增领域对象、不改 Link A/Link B 打标解析行为 |
| F069-filelib-external-user-context | F004, F044 | 复用统一 PermissionService 与 Developer Token 认证；不新增身份或授权事实，只为四个 Filelib 查询接口组合调用资格与可选业务用户上下文；仅允许在未启用租户功能的部署发布 |
| F084-filelib-retrieve-original-links | F069, F017 | 复用 F069 的 Token/业务用户权限上下文及知识检索可见性过滤，读取 KnowledgeFile 原对象并通过现有 MinIO 能力签发 7 天 URL；不修改门户下载、水印、额度或审计链路，沿用 F069 的无租户部署边界 |
| F070-points-system | F002, F004, F009, F012, F025（发布审批结果只读）, 现有 knowledge/qa_expert/message/telemetry | 新建积分域；扩展 Department.org_level；挂钩只读/调用知识上传发布、收藏、采纳、日活与站内信，不取得其写所有权；外部协同办公同步不阻塞 MVP |
| F082-department-short-name | F002, F009, F014/F015 | 扩展 F002 的 Department 字段与既有创建/详情/更新链路；简称由本地维护，F009/F014/F015 组织同步不得覆盖 |
| F083-portal-department-display-name | F082, F025, F060, F064, F065 | 只读 F082 的 `Department.short_name`，统一首钢门户、嵌入式知识门户、成员管理、审批、专家和水印展示；保留正式名称、历史快照、权限与同步契约，不新增领域对象或数据迁移 |
| F106-knowledge-reorder-auth | F013, 现有 knowledge sort_weight、department_knowledge_space、运营岗身份 | 只扩展谁能写已有 `sort_weight` 并下发 `can_reorder*`；不取得 Knowledge / KnowledgeFile / 部门绑定表写所有权，不改置顶与个人库 |

---

## 已分配模块编码（MMMEE）

> 新 Feature 分配错误码时，必须检查此表避免冲突。

| 模块编码 (MMM) | 模块 | Owner Feature |
|----------------|------|---------------|
| 181 | approval | F025（沿用现有 `common/errcode/approval.py`，扩展为统一审批中心错误码） |
| 190 | channel / bisheng_information | F026 沿用现有 `common/errcode/channel.py`，扩展频道授权错误码时不得与既有 190xx 冲突 |
| 198 | developer_token | F044 开发者 Token 管理与认证错误码；F066 在该模块追加文件同步规则 19813 与目标树游标 19814 |
| 199 | filelib_sync | F047 文件同步既有错误码；F066 只在该模块内追加 Token 文件同步配置缺失等运行时错误码 |
| 250 | portal_course | F062 门户课程管理、媒体校验与播放进度错误码 |
| 182 | points | F070 积分账户、流水、规则、排行、组织打标与同步 outbox 错误码 |
| 120 | workstation（工作台） | 沿用现有 `common/errcode/workstation.py`（12000–12099）；F079 追加标签管理控制台错误码 12046–12049，不得与既有 12040–12045 冲突 |

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-05-18 | 初始化 v2.6.0 契约，并登记 F025 统一审批中心的领域对象、依赖与不变量 | F025 |
| 2026-05-28 | 登记 F026 频道主动授权的领域对象归属、依赖与 190 模块错误码边界 | F026 |
| 2026-05-28 | 登记 F027 ReBAC 列表性能优化：新增 INV-6（cursor-based 分页 + 统一 cursor 契约）；未新增领域对象；扩展现有模块错误码 109 / 105 / 180 各新增 1 个 `*InvalidCursorError` | F027 |
| 2026-06-10 | 登记 F044 开发者 Token 管理与认证模块错误码 198 | F044 |
| 2026-07-14 | 登记 F054 发布申请提交性能优化及 `ApprovalNotificationOutbox` 领域归属 | F054 |
| 2026-07-18 | 登记 F062 门户课程、视频、学习进度、媒体清理领域归属，依赖关系及 250 模块错误码；标签确认为 PortalCourse 内值对象，不建立独立实体/表 | F062 |
| 2026-07-20 | 登记 F063 知识文件统一 PDF 产物的领域归属与 F017/F056 依赖；明确其不拥有解析状态、预览和下载行为 | F063 |
| 2026-07-21 | 登记 F064 门户带水印 PDF 下载依赖 F063；明确仅通过 accessor 读取统一 PDF 产物，不取得 `KnowledgeFilePdfArtifact` 写所有权 | F064, F063 |
| 2026-07-22 | 登记 F066 的 `DeveloperToken.file_sync_rule` 扩展所有权、F044/F047/F060 依赖、199 错误码边界及权限不扩张、门户配置单一事实源和失败关闭不变量 | F066, F044, F047, F060 |
| 2026-07-22 | 扩展 F066 固定目标到知识空间根目录或目录；明确选项、保存和运行时按 Token 绑定用户过滤/复核 `upload_file`，目录失效或无权不得回退根目录 | F066, Knowledge, Permission |
| 2026-08-07 | 登记 F079 标签管理控制台：`Tag` / `ReviewTag` 审核留痕字段写所有权、120 模块错误码段 12046–12049、F013/F063 依赖；**批准 INV-6 定向豁免**——`/api/v1/workstation/tags/console/search` 与 `/review/search` 使用 page/total 分页，理由为可见空间集合一次性解析后下推 `IN`，不做逐行 ReBAC 判定，且属低频管理后台；豁免仅限这两个端点，接口若演化为逐行判权则自动失效 | F079, INV-6 |
| 2026-08-02 | 登记 F069 Filelib 外部用户上下文：新增 INV-10 与 F004/F044 依赖，明确 Token 资格优先、可选目标用户完整权限、全局唯一匹配失败关闭及无租户部署边界 | F069, F004, F044, User, Knowledge |
| 2026-08-06 | 登记 F070 积分系统：领域对象、Department.org_level 扩展、INV-11~14、模块编码 182；外部同步不阻塞 MVP | F070, F002, Department, Knowledge, Message |
| 2026-08-10 | 登记 F082 部门简称：为 `Department.short_name` 建立字段扩展所有权，明确可空 64 字符、本地维护、同步不覆盖及不改变组织树/搜索/权限边界 | F082, F002, F009, F014, F015 |
| 2026-08-10 | 登记 F083 门户部门简称统一展示：新增 INV-11 与 F082/F025/F060/F064/F065 依赖；门户动态展示、搜索、排序和路径使用简称回退，正式名称字段、历史快照、部门 ID、权限及同步事实保持不变 | F083, F082, User, Knowledge, Permission, Approval, QAExpert |
| 2026-08-21 | 登记 F084 Filelib 检索原文件链接：新增 INV-16 与 F069/F017 依赖，明确 `view_file` 可见结果可获得 7 天原文件 Bearer URL，并显式绕过 `download_file`、门户下载额度、审计、水印和分发限制；无权或原对象缺失时不得签发 | F084, F069, F017, DeveloperToken, KnowledgeFile, Permission, MinIO |
| 2026-09-01 | 登记 F106 库/文件夹排序权限：新增 INV-17；不新增领域对象与错误码段，复用 18040/18041；部门管理员按绑定表，运营岗不得写入 `is_admin()` | F106, INV-17, Knowledge, KnowledgeFile |
