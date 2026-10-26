# marketplace-versions

## summary
应用广场/标签/版本三块的现状是：一套以 flow+assistant UNION 为核心的「应用列表」机制（后端 `/api/v1/workflow/list` 与 `/api/v1/chat/online` 两条链路，均走 ReBAC 可见性过滤），一套完整可复用的标签体系（tag/tag_link 表 + 打标组件 + 首页标签配置），以及一套语义上与 RT-05 完全不符的 flow_version「可变指针」版本机制。工场应用作为第三应用类型接入卡片流与标签体系的扩展点明确且数量有限（约 7-8 处硬编码点），但 RT-05 版本快照/终态/前向回滚和 GOV-09 管理列表（档位/来源/改码权列）基本全新。最大的未决问题是「应用工场」入口页落在 client 还是 platform——两个 SPA 的列表/表格技术栈完全不同。

## current_state
【应用卡片列表的两条后端链路（均已在代码验证）】
1) 构建页链路：`GET /api/v1/workflow/list`（src/backend/bisheng/api/v1/workflow.py:331 `read_flows`）→ `WorkFlowService.get_all_flows_envelope`（src/backend/bisheng/api/services/workflow.py:565）。F027 cursor 分页（keyset (update_time,id)，cursor 已兼容 int 与 UUID 混合 id）。数据源是 `FlowDao.aget_all_apps`（database/models/flow.py:596）→ `_build_apps_subquery`（flow.py:748）：`select(Flow...) UNION ALL select(Assistant...)`，且 docstring 明示租户 auto-filter 对 subquery 失效、每个内层 SELECT 手工注入 `build_tenant_filter_clause`。助手固定以 `FlowType.ASSISTANT.value` 字面量并入。
2) 广场链路：`GET /api/v1/chat/online`（api/v1/chat.py:17 `get_online_chat`）→ `WorkFlowService.get_online_flows_page` / `get_all_flows`，status 固定 `FlowStatus.ONLINE`（flow.py:28，OFFLINE=1/ONLINE=2），支持 tag_id、常用应用置顶排序（ranking_user_id）。未分类默认区：`GET /api/v1/workstation/app/uncategorized`（workstation/api/endpoints/apps.py:80）→ `get_uncategorized_flows`（services/workflow.py:1031）= 全量应用标签取补集（id_list_not_in）。

【可见范围过滤】非 admin 用户走两段：a) 预过滤 `_app_type_ids_for_permission`（services/workflow.py:699）对 targets 硬编码 [("workflow"), ("assistant")] 两个 OpenFGA object type 调 `PermissionService.list_accessible_ids`；b) 逐行细过滤 `ApplicationPermissionService.get_app_permission_map_async`（permission/domain/services/application_permission_service.py，其中 flow_type→FGA object type 映射在该文件 :35）。权限位→FGA relation 映射 `_APP_PERMISSION_TO_MIN_RELATION`（services/workflow.py:59，view/use→can_read、publish/unpublish→can_manage）。FGA 授权模型是代码定义：core/openfga/authorization_model.py:288 `_standard_resource_type('workflow')`。类型白名单 `SUPPORTED_APP_TYPES = {WORKFLOW, ASSISTANT}`（services/workflow.py:58）+ `filter_supported_apps`（:73）双重把关，其他 FlowType（WORKSTATION=15/LINSIGHT=20/CHANNEL_ARTICLE=25/KNOLEDGE_SPACE=30，flow.py:33）不会进入应用列表。

【标签体系（PRD 要求复用的部分，完整存在）】表：`tag` + `tag_link`（database/models/tag.py，Tag 带 business_type/business_id/tenant_id；TagLink 带 resource_id+resource_type+唯一约束 resource_tag_uniq）。应用标签统一用 `business_type=APPLICATION`（api/services/tag.py:26）。API：`/api/v1/tag` CRUD（建/改/删标签限 `get_admin_user`）+ `/tag/link`（打标，登录用户）+ `/tag/home`（广场首页展示标签集，存 `ConfigKeyEnum.HOME_TAGS` 配置，api/v1/tag.py:72-92）。打标权限 `TagService.check_tag_link_permission`（api/services/tag.py:72）：admin 或对资源有写权限者均可自助打标，且 resource_type 只认 ASSISTANT/WORK_FLOW 否则 NotFoundError——即现状与 PRD「打标仅租户管理员、收口管理列表」不同。列表打标筛选的资源枚举 `ResourceTypeEnum`（database/models/group_resource.py:14，ASSISTANT=3/WORK_FLOW=5 等）。tag 过滤在列表侧的硬编码点：services/workflow.py:192、:607 `get_resources_by_tags_batch([tag_id],[WORK_FLOW,ASSISTANT])`、:540、:1052-1053。

【前端两个 App 的呈现】client（端用户广场）：`pages/apps/explore.tsx`（ExplorePlaza，滚动加载调 `getChatOnlineApi`→/chat/online；分类 tab 组件 `components/AgentNavigation.tsx` 用 `getHomeLabelApi`(/tag/home) + 固定「未分类」tab 调 `getUncategorized`）；`pages/apps/index.tsx`（AppCenter 应用中心，hooks/useAppCenter.ts 同样走 chat/online）；卡片 `components/AgentCard.tsx` 展示 logo/name/description/tags（无 tags 时显示「精选」占位），**未展示 owner**。API 封装 `src/api/apps.ts`（getAppsApi/getChatOnlineApi/getUncategorized/getRecommendedAppsApi；getAppsApi 内 hardcode `map={assistant:5,skill:1,flow:10}`）。platform（构建页）：`pages/BuildPage/apps.tsx`（卡片流，`useInfiniteCursorTable` + controllers/API/flow.ts:206 getAppsApi 带 cursor/managed/status/tag_id/permission_id；标签筛选用 `useQueryLabels`（BuildPage/hook.ts）；卡片上打标组件 `components/bs-comp/cardComponent/LabelShow.tsx` + `selectComponent/LabelSelect.tsx`，调 controllers/API/label.ts 的 createLinkApi/deleteLinkApi，并内嵌标签建/改/删）。

【版本机制现状】只有工作流/技能有版本：`flow_version` 表（database/models/flow_version.py，字段 data=完整 DAG JSON 快照、is_current、is_delete、original_version_id、flow_type）。assistant 表无任何版本概念（database/models/assistant.py grep "version" 为空；client apps.ts:393 给助手补空 version_list）。版本 API：`/api/v1/workflow/versions*` + `POST /change_version`（api/v1/workflow.py:214-271）。语义关键点：`FlowVersionDao.change_current_version`（flow_version.py:207）= 原地切换 is_current 指针并把 version.data 回写 flow.data——**切换/回退不产生新版本记录**；`update_version` 同理直接覆盖。上线 `PATCH /workflow/status`→`WorkFlowService.update_flow_status`（services/workflow.py:829）校验 publish_app/unpublish_app 权限位后直接改 status，**不经审批中心**（F025 审批场景仅菜单权限/频道订阅/知识空间加入）。无终态标注、无审批单关联、无能力声明/配置/档位快照、无结构迁移与数据快照。

【GOV-09 可克隆的管理表格模式（platform）】标准三件套 `useTable`（@/util/hook）+ bs-ui `Table` + `SearchInput` + `AutoPagination`：最典型是 `pages/SystemPage/components/Users.tsx`（:92 useTable、:196 搜索、:203 表格、含 useResizableColumns 列宽拖拽）与 `pages/LogPage/useAppLog/index.tsx`（:65 useTable + 多筛选 Select + :396 分页）——后者本身就是「按应用检索」的列表，最接近 GOV-09 形态。导航：`layout/MainLayout.tsx` 侧边栏按 `user.web_menu` key（'build'/'sys'/'model'…）+ `isMenu()`/`showAdminNav()` 控制入口（:93-113），路由注册在 `routes/index.tsx`（permission 字段同名）。全仓 grep「应用工场/appFactory」无任何既有代码。

## key_files
- src/backend/bisheng/database/models/tag.py — Tag/TagLink 模型 + TagDao 全部打标/查询方法；business_type=APPLICATION 即应用标签命名空间
- src/backend/bisheng/api/services/tag.py — TagService：标签 CRUD（admin）、打标权限 check_tag_link_permission（resource_type 只认 ASSISTANT/WORK_FLOW，owner 可自助打标——与 PRD 收口要求相悖处）、HOME_TAGS 首页标签配置
- src/backend/bisheng/api/v1/tag.py — /api/v1/tag 路由：CRUD + /link 打标 + /home 广场分类配置
- src/backend/bisheng/database/models/flow.py — FlowType/FlowStatus 枚举、FlowDao.aget_all_apps（F027 cursor）、_build_apps_subquery（flow+assistant UNION，租户条款手工注入的陷阱说明）
- src/backend/bisheng/database/models/flow_version.py — 版本表：data JSON 快照 + is_current 指针；change_current_version=原地切换非前向新建（RT-05 语义缺口的核心证据）
- src/backend/bisheng/api/services/workflow.py — SUPPORTED_APP_TYPES(:58)、权限位→relation 映射(:59)、get_all_flows_envelope(:565)、_app_type_ids_for_permission(:699 硬编码 workflow/assistant 两 FGA 类型)、add_extra_field(:87 附 user_name/version_list/tags)、get_uncategorized_flows(:1031)、update_flow_status(:829 上线不走审批)
- src/backend/bisheng/api/v1/workflow.py — /workflow/list(:331) 与 /workflow/versions* + change_version(:214-271) 路由
- src/backend/bisheng/api/v1/chat.py — /chat/online 广场列表端点（status=ONLINE + ReBAC + 常用排序）
- src/backend/bisheng/workstation/api/endpoints/apps.py — 广场辅助端点：/app/uncategorized(未分类默认区)、/app/recommended、/app/used
- src/backend/bisheng/permission/domain/services/application_permission_service.py — FlowType→OpenFGA object type 映射(:35)与应用细粒度权限图谱查询——第三类型接入 ReBAC 的改造点
- src/backend/bisheng/core/openfga/authorization_model.py — FGA 授权模型代码定义，_standard_resource_type('workflow')(:288)——新增对象类型在此扩展并需模型迁移
- src/backend/bisheng/database/models/group_resource.py — ResourceTypeEnum(:14)——打标/授权共用的资源类型枚举，工场应用需新增成员
- src/frontend/client/src/pages/apps/explore.tsx — client 应用广场页（ExplorePlaza）：home 标签 tab + 未分类 tab + 滚动加载
- src/frontend/client/src/pages/apps/components/AgentCard.tsx — 广场卡片：logo/name/description/tags，当前不展示 owner（RT-02 卡片构成差一项）
- src/frontend/client/src/api/apps.ts — client 应用 API 封装；getAppsApi 内 flow_type map hardcode {assistant:5,skill:1,flow:10}——第三类型需扩
- src/frontend/platform/src/pages/BuildPage/apps.tsx — platform 构建页卡片流（cursor 无限滚动 + 状态/标签筛选 + LabelShow 打标）——PRD 明确 GOV-09 不并入此页
- src/frontend/platform/src/components/bs-comp/selectComponent/LabelSelect.tsx — 打标交互组件（含标签建/改/删内嵌），GOV-09 行操作「标签设置」可直接移植
- src/frontend/platform/src/pages/SystemPage/components/Users.tsx — GOV-09 最佳克隆模板之一：useTable+bs-ui Table+SearchInput+AutoPagination+列宽拖拽
- src/frontend/platform/src/pages/LogPage/useAppLog/index.tsx — 另一克隆模板：多筛选 Select + 按应用检索的表格列表，形态最接近应用管理列表
- src/frontend/platform/src/layout/MainLayout.tsx — 侧边导航 web_menu key 机制（isMenu/showAdminNav）——新增「应用工场」一级入口的落点
- src/frontend/platform/src/routes/index.tsx — platform 路由表（permission 字段与菜单 key 对应）

## reuse
- 标签体系整套复用（RT-02 明确要求）：tag/tag_link 表、/api/v1/tag CRUD+link、HOME_TAGS 首页分类配置、未分类补集逻辑（services/workflow.py:1031 get_uncategorized_flows）全部现成；工场应用接入只需 ResourceTypeEnum 加成员并在 4 处 tag 查询硬编码点（services/workflow.py:192/:540/:607/:1052）扩列表
- 广场页与卡片 UI 复用：client pages/apps/explore.tsx + AgentCard + AgentNavigation 已是「标签 tab + 卡片 + 滚动加载 + 未分类默认区」的完整实现，工场应用只是列表数据里多一种 flow_type（卡片按 flow_type 分流头像 AppAvator 已参数化）
- 可见范围过滤复用：ReBAC 两段式过滤（PermissionService.list_accessible_ids 预过滤 + ApplicationPermissionService.get_app_permission_map_async 细过滤 + F027 cursor 补扫 _scan_visible_flows_cursor）对新类型是通用机制，新增 FGA object type 后即可套用（authorization_model.py _standard_resource_type 模式）
- 打标交互组件复用：platform LabelSelect/LabelShow（controllers/API/label.ts createLinkApi/deleteLinkApi）可直接作为 GOV-09 行操作「标签设置」的弹层
- 管理表格模式复用：SystemPage/components/Users.tsx 与 LogPage/useAppLog/index.tsx 的 useTable+bs-ui Table+SearchInput+AutoPagination 组合即 GOV-09 表格骨架；审计入口可链 LogPage/audit（audit_log 模型已存在）
- 上线/下线状态与权限位复用：FlowStatus ONLINE/OFFLINE + publish_app/unpublish_app→can_manage 映射（services/workflow.py:59）可作 RT-07 下线/启用的权限基础
- 版本快照存储 pattern 可参考：flow_version 的 data-JSON 快照 + original_version_id 溯源字段是「版本=内容快照」的既有先例（但仅作蓝本，语义需重做，见 gaps）
- 菜单可见性机制复用：web_menu key + MainLayout isMenu/showAdminNav + routes permission 字段，新增『应用工场』只是加一个 key（GOV-07 一份控制的现成载体）

## gaps
- 第三应用类型「工场应用」本体：FlowType 新枚举值（避开 15/20/25/30 已占用的非应用成员）、SUPPORTED_APP_TYPES 与 filter_supported_apps 扩类型、_build_apps_subquery UNION 第三支（或复用 flow 表新 flow_type）、_app_type_ids_for_permission targets 扩项、application_permission_service 映射表扩项、FGA 授权模型新 object type + 存量环境模型迁移、ResourceTypeEnum 新成员、client api/apps.ts 的 flow_type map 扩项——扩展点明确但分散约 7-8 处硬编码
- RT-05 版本模型全新：现 flow_version 是可变指针（change_current_version 原地切换 + 回写 flow.data，删除是软删），无「版本记录不可变、终态标注（已上线/被驳回/已撤回）、回滚=前向新建记录、单一在途、审批单关联、档位/能力声明/注入配置入快照、结构迁移确认与迁移前数据快照」中的任何一项；且 assistant 根本无版本概念
- GOV-09 应用管理列表后端：无任何接口输出 owner/发布状态机/资源档位/来源（平台内造 vs CLI 导入）/改码权归属组合列；「档位」「来源」「改码权」三个概念在数据模型中完全不存在，需新字段/新表 + 新列表端点（/workflow/list?managed=true 只是最接近的雏形）
- GOV-09 前端页面全新：「应用工场」一级导航入口页（应用管理 tab + 我的应用列表 tab）+ 新 web_menu key + 路由 + 菜单权限（GOV-07 部署开关）
- 应用实例数配额用量条（GOV-03）：v2.5 配额收窄后只剩 storage_gb，应用实例数配额的模型、校验与 UI 全新
- 打标权限收口改造：现 check_tag_link_permission 允许 owner/写权限者自助打标且 resource_type 白名单只有 ASSISTANT/WORK_FLOW；PRD 要求工场应用打标仅租户管理员且入口唯一在 GOV-09——需要按资源类型分派不同打标权限规则（工作流/助手保持现状 vs 工场应用 admin-only）
- 广场卡片展示 owner：AgentCard 现不渲染 owner（后端 /workflow/list 的 add_extra_field 已附 user_name，/chat/online 返回是否带 user_name 未逐行核实）——小改造但涉及与既有工作流/助手卡片的一致性决策
- 发布/下线接审批：现 update_flow_status 直改 status 不经 F025 审批中心；PRD 的发布审批（RT-03/GOV-02）与状态机（§3.2）需在新类型上新建（且不应改动存量工作流/助手的直接上线行为）

## risks
- C4 风险：新 FGA object type 必须改 core/openfga/authorization_model.py 并对存量环境做授权模型迁移——记忆中 F048 迁移在存量环境被 permissions_explicit 缺省值拦截的教训直接适用，迁移设计需前置演练
- C3 风险：应用列表的 UNION 子查询绕过租户 auto-filter（_build_apps_subquery docstring 明示），第三支 SELECT 必须手工注入 build_tenant_filter_clause；任何新表还须注册 tenant-aware 模块，否则跨租户泄漏
- C2/DM8 风险：RT-05 版本快照若含大 JSON（代码包元数据/能力声明/DAG），每次发布写入 flow_version 式大 JSON 在 DM8 有 undo 写放大前科（灵思 history -7120 事故），快照存储建议 MinIO 引用而非行内 JSON，需在 design 阶段定
- 语义冲突风险：PRD『回滚=前向新建版本记录』与现有 change_current_version『指针切换』两套语义若共存于同一 flow_version 表，is_current/is_delete 字段含义会分叉；建议工场应用独立版本表而非复用 flow_version，否则存量工作流版本 UI（CardSelectVersion 等多处消费 version_list）会被波及
- 前端双栈风险：client（Recoil/shadcn/react-query v4）没有 platform 的 useTable/bs-ui Table 组件体系；若「应用工场」入口页落在 client，GOV-09 表格模式无法直接克隆，需在 client 重建表格组件或页面落 platform——技术选型受产品定位牵制
- 标签查重现状：TagDao.get_tag_by_name 仅按 name 查（依赖租户 auto-filter 隔离，不含 business_type 条件），跨 business_type 重名会被误判存在——扩标签用途时需留意
- chat/online 与 /workflow/list 两条列表链路行为已有细微分叉（排序/分页/字段），工场应用要同时进两条链路，验收需覆盖双链路一致性

## open_questions
- 「应用工场」入口页落在哪个 SPA？PRD 称 GOV-09 在『应用工场』主导航入口页内 tab 且与 owner『我的应用列表』并列（PRD-2 §3.1）——广场在 client、构建/管理表格模式在 platform，这决定 GOV-09 是克隆 platform Users.tsx 模式还是在 client 重建表格体系，是本切片最大的产品/技术分叉点
- 工场应用的存储载体：复用 flow 表新增 flow_type（自动进 UNION 与 cursor 分页，但混入既有表语义）还是独立新表 + UNION 第三支（id 类型自由但 4 处 tag 查询与权限映射都要显式扩）？
- 版本模型归属：RT-05 版本列表在 WB-14/15（PRD-2 工作台发布面），版本表/审批联动是否随 PRD-1 先建后端模型、UI 留待 PRD-2？被驳回/已撤回终态依赖 RT-03 审批流，切片顺序需拍板
- 打标双规则是否可接受：存量工作流/助手保留 owner 自助打标，工场应用 admin-only 收口 GOV-09——还是全平台统一收口（会改变存量行为）？
- 广场卡片加 owner 展示是只给工场应用卡片加，还是三类应用卡片统一加（AgentCard 是共用组件）？
- 『未分类』tab 现状（未打标应用落 uncategorized 补集）是否即满足 RT-02『默认分类中正常可见』的验收，还是需要新的『默认分类』概念？
- GOV-09 的『来源（平台内造/CLI 导入）』『资源档位』『改码权归属』三字段的数据来源定义在 DEV-04/DEV-06（CLI 通道），本切片是否只预留列与枚举、由 CLI 切片回填？
