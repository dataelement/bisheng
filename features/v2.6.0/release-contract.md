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
| UserMenuAccess | F025-approval-center-unification | 菜单权限申请通过后的用户级菜单授权与撤回记录 |
| ChannelAuthorizationWrite | F026-channel-active-authorization | 频道资源主动授权、撤销授权、频道 relation-model binding 写入与清理行为 |
| SpaceChannelMember(channel relation/source fields) | F026-channel-active-authorization | `space_channel_member` 中 `business_type='channel'` 的四档关系与授权来源字段；不拥有知识空间成员关系 |
| —（无新增） | F029-knowledge-qa-permission-filter | 仅读取/调用现有 KnowledgeSpace / Folder / KnowledgeFile / MessageCitation；不引入新领域对象 |
| —（无新增） | F030-knowledge-resource-unified-api | v2 filelib 统一对外 API；仅经由现有 `KnowledgeService` / `KnowledgeSpaceService` 读写 Knowledge / KnowledgeFile / KnowledgeSpace，不引入新领域对象、不新增 DAO 入口 |
| ChannelInfoSourceSubscription（`channel_info_source` 行生命周期 + 情报服务订阅副作用） | F031-channel-source-subscription-reconcile | 订阅意图唯一真相 = 租户内 `channel.source_list` 并集；`channel_info_source` 行存在 ⟺ 已订阅，行与外部订阅态同生共死；拥有订阅/退订情报服务的调用时机与每日对账写行为。仅读取 `Channel.source_list`，不拥有 `Channel` 本身，不拥有 F026 的频道授权/`space_channel_member` channel 字段 |
| —（无新增） | F032-ofd-upload-support | 仅在现有 RAG 解析链路（`FileExtensionMap` / loader / 预览对象）上新增 `ofd` 扩展名分支：OFD 转 PDF 后复用既有 PDF 解析/预览/检索；不引入新领域对象、不新增 DAO，不改动既有扩展名的处理路径 |
| —（无新增） | F033-department-space-member-scope | 仅在现有 ReBAC 授权链路（`resource_permission.py` 的 `grant-subjects/*` 列表 + `authorize`）上，对 `knowledge_space` 资源按 `DepartmentKnowledgeSpace` 绑定收敛授权范围（绑定部门子树 / 子树成员，禁用 user_group）；只读 `DepartmentKnowledgeSpace` / `Department` / `UserDepartment`，不拥有这些对象、不新增领域对象/表/DAO；普通知识空间授权路径零变化 |
| LinsightSkill（`linsight_skill` 表 + SKILLS_ROOT 磁盘 SKILL.md 生命周期） | F035-linsight-task-mode | 租户自定义技能元数据（name/description/enabled/source，唯一约束 `(tenant_id,name)`）与磁盘正文的创建/编辑/删除/启停；内核 built-in skill 不入表、不经 API。同时拥有：自研 ReAct 内核与 SOP 动态生成链路的**下线**、`linsight_sop`→Skill 一次性迁移写行为；只读 `linsight_session_version`/`linsight_execute_task`（沿用既有模型，不改其归属） |
| —（无新增） | F034-knowledge-space-file-move | 不引入新领域对象；经由 `KnowledgeSpaceService` 新增对 KnowledgeFile / KnowledgeDocument 的「移动」写行为（改 `knowledge_id` / `file_level_path` / `level`，版本链整链迁移）+ 跨空间检索数据迁移 celery 任务；§5.5 新增「文件夹上传」批量编排（按相对路径重建目录树，复用 `add_folder`/`add_file` 管线与配额校验）；不改变 F039 版本模型与 F030 对外 API 语义 |

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
| INV-6 | 走 ReBAC 过滤的高频列表接口采用 cursor-based 分页：请求用 `cursor` 透传上一页位置，响应含 `has_more: bool` 与 `next_cursor: string\|null`，**不再返 `total` / `page_num`**；后端不得为算 total 而扫描全部 batch；cursor 编码统一走 `common/cursor.py`（schema `{"v":1, "k":[...]}`，base64url）；cursor 解析失败必须明确报错（`*InvalidCursorError`），不得静默 fallback 首页 | 所有走 ReBAC 过滤的列表接口 | F027 |
| INV-7 | 知识空间内容的"AI 问答可检索可见性"必须是"列表 UI 可见性"的子集；即对任意 `(user, space, file)`，若用户在列表 UI 中不可见该 `file`（`view_file ∉ effective_permissions`），则任何 AI 问答入口都不得让该 `file` 的 chunk / 文件名 / 来源出现在模型上下文、回答引用、角标溯源 `/api/v1/citations/resolve` 响应的结构化字段中 | KnowledgeSpace, Folder, KnowledgeFile, MessageCitation | F029 |

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
| F028-conversation-export-import | F004, F008（ReBAC core / resource-rebac-adaptation） | 工作台会话回答级导出与导入知识空间；复用 `KnowledgeSpaceService.add_file` 链路，不新增领域对象 |
| F029-knowledge-qa-permission-filter | — | 仅复用现有 ReBAC `list_accessible_ids` + Fine-grained `view_file` 解析；不依赖其他 v2.6.0 Feature |
| F030-knowledge-resource-unified-api | F027, F029 | 列表/文件列表沿用 F027 cursor 协议（INV-6）；代用户检索 `user_id` 闭合 F029 遗留的 RPC 越权口子（对齐 INV-7） |
| F031-channel-source-subscription-reconcile | F026 | 与 F026 同改 `channel_service.py` 但领域解耦（F026 拥有频道授权/`space_channel_member` channel 字段，F031 拥有 `channel_info_source` 订阅生命周期）；缺陷收敛型，不新增表、不新增对外 API、不新增错误码（沿用 190 段 19007） |
| F032-ofd-upload-support | — | 仅在现有 RAG 解析链路新增 `ofd` 扩展名分支（OFD→PDF 后复用 PDF 解析/预览）；不依赖其他 v2.6.0 Feature，不新增领域对象/表/对外 API；新增 109 段错误码 `OfdConvertError`(10917) |
| F033-department-space-member-scope | F006/F007（ReBAC 资源授权）、部门知识空间能力（`DepartmentKnowledgeSpace` 绑定） | 范围收敛型；在既有 ReBAC 授权/列表接口对部门知识空间加部门子树准入，禁用 user_group；不依赖其他 v2.6.0 Feature，不新增领域对象/表/对外 API/错误码（**复用 `PermissionDeniedError`**）；不改动普通知识空间授权路径 |
| F035-linsight-task-mode | F011/F012/F013（多租户基线）、既有角色菜单体系、F029/F030（知识库检索权限过滤，INV-7） | 内核替换型（自研 ReAct → deepagents 适配层，一次性切换不并存）；新增 `linsight_skill` 表 + Alembic、新增 110 段错误码 11050–11069、新增 `/api/v1/linsight/skill` API 与「任务模式」菜单子项；保留 worker.py/Redis queue/WS 协议（`MessageEventType` 不新增枚举）；新增 Redis checkpointer（HITL park-and-release）与 MinIO `workspace/{svid}/` 工作区前缀；设计真相 = `features/v2.6.0/035-linsight-task-mode/design.md`（原《技术方案》） |
| F034-knowledge-space-file-move | F004/F008, F027, F039 | 文件/文件夹移动（同空间 + 跨空间）+ §5.5 文件夹上传；权限走 ReBAC 细粒度 `move_file`/`move_folder`（映射 can_edit，不改 OpenFGA 模型）；列表刷新沿用 F027 cursor 协议（INV-6）；跨空间移动依赖 F039 版本链「同空间」不变式做整链迁移；新增 180 段错误码 18033（无效移动目标）/ 18025（单次批量超 1000）；新增对外 API `POST /knowledge/space/{id}/files/move` 与 `.../folders/upload`；未新增不变量 |

---

## 已分配模块编码（MMMEE）

> 新 Feature 分配错误码时，必须检查此表避免冲突。

| 模块编码 (MMM) | 模块 | Owner Feature |
|----------------|------|---------------|
| 181 | approval | F025（沿用现有 `common/errcode/approval.py`，扩展为统一审批中心错误码） |
| 190 | channel / bisheng_information | F026 沿用现有 `common/errcode/channel.py`，扩展频道授权错误码时不得与既有 190xx 冲突 |
| 120 | workstation | F028 沿用现有 `common/errcode/workstation.py`，会话导出 / 导入知识空间错误码段位 12060-12079，不得与既有 1204X / 1205X 冲突 |
| 109 | knowledge | F030 沿用现有 `common/errcode/knowledge.py`，新增 `KnowledgeTypeNotSupportedError`(10962)；复用 10900/10901/10991。180 (knowledge_space) 复用 18001/18010/18040 |
| 109 | knowledge | F032 沿用现有 `common/errcode/knowledge.py`，新增 `OfdConvertError`(10917)；不得与既有 10915/10916/10962 冲突 |
| 110 | linsight | F035 沿用现有 `common/errcode/linsight.py`，Skill 管理占用段位 **11050–11069**。实际落码（避让段内既有码）：**11051** 校验失败 / **11052** 超 10MB / **11053** 不存在 / **11054** 无权限 / **11055** 重名。⚠️ 重名由原定 11050 顺延 11055：11050/11060/11070 已被存量 SOP 检索码（`LinsightVectorModelError`/`LinsightDocSearchError`/`LinsightDocNotFoundError`，design §8.6 计划下线）占用——原契约「既有 110xx ≤11040」的判断有误（既有码实达 11190），下线完成后该段彻底归 Skill |
| 180 | knowledge_space | F034 沿用现有 `common/errcode/knowledge_space.py`，新增 `SpaceMoveInvalidTargetError`(18033) / `SpaceFolderUploadCountExceededError`(18025)；复用 18011（层级）/ 18012（文件夹重名）/ 18021 / 18024（容量）/ 18040 / 18041（跨租户）；§5.5 文件夹上传租户容量超限复用 190 段 19403 |

---

## 变更历史

| 日期 | 变更内容 | 影响范围 |
|------|---------|---------|
| 2026-05-18 | 初始化 v2.6.0 契约，并登记 F025 统一审批中心的领域对象、依赖与不变量 | F025 |
| 2026-05-28 | 登记 F026 频道主动授权的领域对象归属、依赖与 190 模块错误码边界 | F026 |
| 2026-05-28 | 登记 F027 ReBAC 列表性能优化：新增 INV-6（cursor-based 分页 + 统一 cursor 契约）；未新增领域对象；扩展现有模块错误码 109 / 105 / 180 各新增 1 个 `*InvalidCursorError` | F027 |
| 2026-05-29 | 登记 F029 知识空间 AI 问答检索权限过滤：表 1 标注"无新增领域对象"、表 2 追加 INV-7（AI 问答可见性 ⊆ 列表 UI 可见性）、表 3 标注无依赖；未新增模块编码（沿用 180 `knowledge_space`）；不影响 F025 范围 | F029 |
| 2026-05-30 | 登记 F028 工作台会话导出 / 导入知识空间：不新增领域对象，不新增不变量；扩展 120 (workstation) 错误码段位 12060-12079；复用 `KnowledgeSpaceService.add_file` 与 `AddToKnowledgeModal` | F028 |
| 2026-06-02 | 登记 F030 知识资源统一对外 API（v2 filelib 改造）：表 1 标注"无新增领域对象"、表 3 追加依赖 F027/F029；新增模块 109 错误码 `KnowledgeTypeNotSupportedError`(10962)；列表/文件列表遵循 INV-6 cursor 协议（PRD 同步改造）；代用户检索 `user_id` 对齐 INV-7；个人库 type=2 对外不暴露但枚举保留（workstation/linsight 内部继续使用）；未新增不变量 | F030 |
| 2026-06-04 | 登记 F031 频道信息源订阅状态对账：表 1 新增 `ChannelInfoSourceSubscription` 领域归属（订阅意图真相 = `channel.source_list` 并集，`channel_info_source` 为物化视图）、表 3 追加依赖 F026；订阅同步即时、退订改每日对账驱动；不新增表/对外 API/错误码（沿用 190 段 19007）；未新增不变量 | F031 |
| 2026-06-08 | 登记 F032 全平台 OFD 上传支持：表 1 标注"无新增领域对象"（仅在 RAG 解析链路加 `ofd` 分支，OFD→PDF 后复用 PDF 解析/预览）、表 3 追加（无依赖）；新增 109 段错误码 `OfdConvertError`(10917)；未新增不变量、未新增表/对外 API | F032 |
| 2026-06-10 | 登记 F033 部门知识空间成员授权范围收敛：表 1 标注"无新增领域对象"（仅在 ReBAC 授权/列表接口对 `knowledge_space` 按 `DepartmentKnowledgeSpace` 绑定收敛至部门子树/子树成员、禁用 user_group）、表 3 追加依赖 F006/F007 + 部门空间能力；复用 `PermissionDeniedError`，未新增错误码/表/对外 API/不变量；普通知识空间授权路径零变化 | F033 |
| 2026-06-11 | 登记 F035 灵思任务模式（deepagents 适配层）：表 1 新增 `LinsightSkill` 领域归属（元数据 `linsight_skill` 表 + SKILLS_ROOT 磁盘正文；含旧内核下线与 SOP→Skill 迁移写行为）、表 3 追加依赖多租户基线/角色菜单/F029/F030；新增 110 段错误码 11050–11069、`linsight_skill` 表 + Alembic、`/skill` API、「任务模式」菜单子项；WS 协议 `MessageEventType` 不新增枚举；未新增不变量；设计真相在 feature 目录 design.md | F035 |
| 2026-06-11 | 登记 F034 知识空间文件/文件夹移动（同空间 + 跨空间）+ §5.5 文件夹上传：表 1 标注"无新增领域对象"（经 `KnowledgeSpaceService` 新增移动写行为 + 跨空间检索数据迁移 celery 任务 + 文件夹上传批量编排按相对路径重建目录树）、表 3 追加依赖 F004/F008、F027、F039；新增 180 段错误码 `SpaceMoveInvalidTargetError`(18033)、`SpaceFolderUploadCountExceededError`(18025)；新增细粒度权限 id `move_file`/`move_folder`（can_edit 档，不改 OpenFGA 模型）；新增对外 API 移动接口与 `folders/upload`；未新增不变量 | F034 |
| 2026-06-11 | F035 Track 0 落地修正：①**后端升级 Python 3.10→3.11**（deepagents 全版本要求 ≥3.11；连带 `cchardet`→`faust-cchardet`；Docker 基础镜像/dmPython 3.11 待人工跟进）；②110 段错误码实际落码 11051–11055（重名由 11050 顺延 11055，避让存量 SOP 检索码），更正原「既有 110xx ≤11040」误判。详见 `035-linsight-task-mode/tasks.md §8` D1/D2 | F035（含全后端 Python 基线） |
