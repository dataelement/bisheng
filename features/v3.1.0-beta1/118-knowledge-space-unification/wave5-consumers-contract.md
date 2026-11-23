# W5 使用准入消费面合同 V1（2026-11-06）

状态：先冻结后实施。功能基线 `abb8dc822215a676393f1fdf5eaa7f26cbb5b3d9`，干净，三方只读审计后由 INT 归并。延续94条 AC 与 [scope-review.md](./scope-review.md) 的157项范围；本波不合入主工作区并发发版线变化。签发加固 T404/T405 继续外移，默认 Embedding 不联动已有空间，其他权限动作和业务条件不放宽。

## 1. 选择的依赖闭合队列

| Owner | 本波任务 | 依赖与唯一生产文件 |
| --- | --- | --- |
| EDGE | T127/128 → T143/144 → T145/146 → T147/148；T226/227 最后接线 | tool 的 f048_tool_permission.py、tool.py、executor.py、api/tool.py；Linsight 的 user_skills.py、skill_permission.py；DSH 的 capability_catalog.py、work_capabilities.py。T226 仍等待 T136，并补 T144 前驱；T127/128 的 Skill 执行联合结论等 T146。 |
| PERM | T153/154、T224/225 | api/services/f048_application_permission.py、tenant/domain/services/resource_share_service.py、permission/domain/services/owner_service.py。T225 最终集成等待 EDGE T128/T146 的 builtin 创建输入去 use；不得单独声称组合已闭合。 |
| API | T135/136、T137/138、T155/156 | app_publish/domain/services/app_publish_current_visibility_service.py、app_runtime/domain/schemas/app_authorization.py、api/v1/assistant.py、channel/domain/services/f048_channel_permission.py。T136 的新动作 DTO 与 INT 前端兼容 T599 一起验收。 |
| INT | 合同/登记/前端 DTO 接缝/文档、合流与验证 | 平台 controllers/API/hostedApp.ts、pages/BuildPage/hostedApp/appActions.ts、test/f114AppActions.test.tsx；审批 skill 对应一句文案。无页面样式/新交互或完整 T193 提前完成。 |

本波原157项中选择20项任务；T598–T603只是这些既定需求发现的前端接缝、旧回归及文档叶子，逐卡至多两文件，非新增功能。其余卡不机械勾选。T063–T076 暂不领取：已有 repo 没有真实确认计划应用层、查询/投递恢复和最新 retry actor 读取、知识专用凭据恢复与同 Session Owner 协调；不能以新建 Service/测试 fake 代替真实接线。既有 worker 的全量分页和 ES 重试源留存随其真实前驱另波处理，不在本波局部改造。

## 2. 原使用资格与其他动作

现 `permission.application.business_authorization` 在 registry.resolve 前将旧 use/use_kb 归一为 visible，批量结果仍可按调用者原请求标签返回。该边界不另建第二套权限服务；新生产调用用 visible，兼容旧 query 的归一化保留在业务/API边界。真实 actor/ContextTenant/principal/credential scope 不换人、不清空、不从 user_id 重造授权；disabled、状态、能力白名单、配额/内容安全等原条件继续独立执行。

系统应用/工具动作仅 `{visible}`；租户共享原 library/workflow/assistant/tool 集合仅 `{visible}`，space/folder/file 原 `{visible,download}` 保持，channel 保持 `{visible}`。Owner 系统动作白名单 `{visible,download}`，空集合及其他动作仍拒绝；合法纯可见模型与其 visibility_level/原 Source 可撤销性复用现 P1，非法空模型不放行。SUPPORTED_SHAREABLE_TYPES 仍仅 llm_server；本波不激活旧 helper 的业务资源 Root→Child 共享，不改变共享范围、发布或签发逻辑。

## 3. Skill 使用与管理边界

生产 registry 使用 skill_permission.py 的 SkillPermissionAdapter，不修改无生产调用且无 use 分支的旧 f048_skill_permission.py。归一化后的可见性不能兼任 enabled 条件：原管理可见/编辑/重新启用 disabled Skill 的链路保留，运行/可选集合独立要求 enabled。

UserSkills.records 的 available_only=True 场景在已有账户开关/身份/范围约束上，还须过滤全局 disabled（包括外部 candidates）；available_only=False 维持原开关管理可见语义，不借此允许执行。候选无参数仍复用原 list_enabled。ensure_builtin_skill_permission 发出的 action_codes 仅 visible，与 T225 一并验证；不新增权限动作或角色模型。

## 4. APP/AS/CH 对外合同

APP_ACTIONS 改为 `(visible,edit,manage_permission,delete,publish,unpublish)`；MANAGEMENT_ACTIONS 排除 visible，具体 required_actions/生命周期/owner/发布与分享资格不改。当前可见摘要四处 use 改 visible，包括前后 Source 一致性检查；这是审批卡已有阅读资格后的只读附加事实，不改审批路由、节点、通知、候选或 outbox。

平台 HostedAppAction canonical 类型相应加入 visible 并移除 use。appActionState 管理入口只认已知管理动作白名单，visible、空/未知动作（含意外旧 use）都不得推导管理权限；具体 edit/publish/unpublish/delete/manage_permission 仍各自判断，rebuild 仍需 edit+publish。不得通过放大 `action != use` 获得管理能力。此最小兼容不等于提前交付完整授权 UI T193。

AS HTTP query 默认 visible，受支持显式 use 按 visible 解释；WS 原 use gate 改 visible，服务本已有相同归一化，不改身份对象、分页游标、envelope或隐藏知识裁剪。频道只读动作仅 visible，跨租户、状态及所属租户管理能力保持原逻辑。

## 5. 测试、交接与合流

实施中补充单叶 T604（INT）：旧 test/permission/test_capability_authorization.py 的 Skill disabled direct-use 断言须移至管理可见/运行禁用分离；该文件另有3个已实测既有 Grant/Catalog fixture 失败，按现纯可见/作用域形状对齐，原租户/owner/撤Source/投影断言不删。本波共20个原卡+7个接缝叶子，仍无新增产品要求。

所有 lane 从本合同提交建立独立 worktree，只有指定文件可写；旧回归叶子按 tasks 登记由相应 lane 唯一维护，docs/tasks/locale/总装配归 INT。先提交行为红测，再实现；既有正确逻辑可记录首轮绿，不伪造红。语义变化的旧 fixture 保留原拒绝/失败/租户/投影断言，只替换退休动作输入。禁止新增生产 fake、联网依赖安装、真实迁移、push/部署。

后端复用主工作区只读 .venv 与 config.yaml，PYTHONPATH 指向当前 lane 的 src/backend，验证 __file__ 不串主源码；SQLite/Port double 不替代 MySQL/DM8/FGA。前端只用已有离线依赖，验证当前 feature 源码；不改锁文件/依赖、不以全库既有错误扩大修复范围。

合流顺序：INT 前端最小兼容 → API 的 T136；EDGE T128/T146 完整交付 → PERM T225；T136/T144 满足后 EDGE T226/227。独立 worktree 各自固定 SHA，由其他 lane 只读交叉检查，再由主 agent 合并。共享热文件不并行写；完成后主 agent 按 task-review 复核范围/依赖、运行组合回归/Ruff/arch-guard/前端必要检查，并同步设计、进度和 HTML。完整 E2E、迁移、Coverage、入向删除协调、处理 worker 与页面待办不因本波而通过。
