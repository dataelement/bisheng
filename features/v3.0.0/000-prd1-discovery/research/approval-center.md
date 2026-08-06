# approval-center

## summary
审批中心（F025）是一套通用多场景审批引擎（统一网关 ApprovalGate → 路由分支 → 流程/节点 → 实例/任务 → outbox 异步执行业务 → 站内信），新增「应用发布」场景在框架层无阻塞：或签、撤回、富 JSON payload、outbox、站内信、审计全部现成可复用，接入成本集中在"三件套"注册（preset + 业务入口 Gate + runtime handler 工厂分支）。真正的缺口在 PRD 的四条场景特化规则上：未配置兜底租户管理员（现状是直接抛错或落异常单，且 tenant_admin 解析器错用系统超管近似）、提交人自动跳过（完全没有）、删除应用取消在途单（无系统级 cancel API）、定制审批单详情页与审读视图入口（前端是通用 key-value 渲染，无分区扩展点）。最大歧义是 PRD 把审批单详情写在"平台审批中心"，而现状审批处理界面只存在于 client 端 /workspace 弹窗，platform 端只有场景配置与异常处理。

## current_state
【均为代码核实，路径相对 src/backend/bisheng/ 除注明外】

一、统一网关与主流程。所有场景经 `ApprovalGate.request_or_pass()`（approval/domain/services/approval_gate.py:92）进入：先按 tenant+scenario_code+business_key+applicant_user_id 查在途去重（`ApprovalInstanceRepository.find_duplicate_active_instance`，活跃状态集=pending/exception/execute_failed，repositories/approval_instance_repository.py:16,52-69，命中时静默返回已有实例而非报错）；再取 handler 生成 `detail_snapshot`/`business_name`（handler.build_detail/build_title）；场景行不存在或 disabled → 直接 `raise ApprovalScenarioDisabledError`（gate.py:109-111，即业务调用失败）；路由按 sort_order 自上而下匹配（`_match_first_route`，gate.py:417-460，支持 catch-all `{}`、`applicant_role` 身份标签"包含即命中"、payload 字段等值三种条件）；pass 分支→实例 APPROVED+建 outbox 立即 dispatch；flow 分支→实例 PENDING+首节点每个审批人一条 task；无路由命中/审批人解析为空→实例 EXCEPTION（route_missing/approver_empty）+站内信通知管理员（`_notify_admins_of_exception`）。全部分支写审计（AuditLogDao.ainsert_v2）。

二、场景注册"三件套"（以知识空间加入审批为实证）：① `ApprovalRegistry.with_default_presets()`（services/approval_registry.py:14-45）注册 preset（scenario_code/名称/条件字段/审批人来源类型），是管理后台"新增场景"下拉的唯一来源（`approval_scenario_admin_service.list_presets`:21-22 + platform ApprovalPage 的 AddScenarioDialog 只能从 presets 选，src/frontend/platform/src/pages/ApprovalPage/index.tsx:219-270）；② 业务入口自建 Gate 并注册 handler（`KnowledgeSpaceService._build_space_approval_gate`，knowledge/domain/services/knowledge_space_service.py:4700-4710；调用点 subscribe_space:4607-4664，先过网关再落 membership）；③ `build_runtime_handler()` 硬编码 if 链（services/approval_runtime_handler_factory.py:17-35），供 outbox 执行、多节点 advance、reject/withdraw 钩子重建 handler。Handler 协议（鸭子类型，见 knowledge_space_subscribe_scenario_handler.py）：build_title/build_detail/resolve_approvers/on_approved/on_rejected/on_withdrawn/on_cancelled。

三、审批人配置。节点 `approver_config.sources` 支持 direct_user（任意用户，platform 有用户选择器 UI）/department_admin/tenant_admin/资源角色类（owner/manager，由场景 handler 自解析）。⚠️核实到关键失真：`resolve_approvers_from_sources` 的 tenant_admin 分支（services/approver_resolver.py:63-74）用 AdminRole(role_id=1 系统超管) 做"pragmatic approximation"，并非真租户管理员；而通知侧 `ApprovalNotificationService._get_admin_recipient_ids`（approval_notification_service.py:122-150）才真正走 `TenantAdminService.list_tenant_admins`。

四、或签/会签与流转。`decide_task`（approval_center_service.py:658-801）：node_mode=or 任一人通过→同节点其余 PENDING task 置 SKIPPED→`_advance_after_node_approved`（803-966，有后续节点则解析下节点审批人建 task+站内信，无则实例 APPROVED+建 outbox+通知申请人）；拒绝→其余置 CANCELLED、实例 REJECTED、通知申请人、调 on_rejected。and 模式全员通过才 advance。

五、outbox。通过后写 approval_outbox(PENDING)→Celery 默认队列 `execute_approval_outbox`（worker/approval/tasks.py）→`ApprovalOutboxService.execute_outbox`（approval_outbox_service.py:13-76）执行 on_approved：成功→instance=executed；失败→execute_failed+异常单+通知管理员，管理端可重试。

六、撤回。`withdraw_instance`（approval_center_service.py:418-492）：仅申请人本人（430-431）；PENDING task 置 CANCELLED、实例 WITHDRAWN、审计+站内信通知有 task 的审批人、调 on_withdrawn。⚠️无状态守卫——不校验实例当前状态，已 approved/executed 的实例也能被翻成 WITHDRAWN（API 层 approval_user.py:83-97 也无守卫）。

七、富 payload 与详情页。`payload_snapshot`/`detail_snapshot` 均为 JSON 列（models/approval_instance.py:61-62），无 schema 约束，可承载任意富快照；`get_task_detail`（approval_center_service.py:99-203）原样返回两个 snapshot+flow_nodes+tasks+action_logs。前端渲染：client `ApprovalCenterDialog.tsx` 的 TaskDetailPanel（src/frontend/client/src/components/approval/ApprovalCenterDialog.tsx:682-724）把 detail_snapshot 用 Object.entries 过滤 DETAIL_INTERNAL_KEYS 后渲染为通用两列 key-value 网格，无分区/无场景定制渲染机制；唯一场景特例是 menu_access_request 的撤销授权按钮分支（line 380）。审批处理界面（我的审批/我的申请/时间线）只存在于 client 端此弹窗；platform 端 ApprovalPage（2524 行）只有场景/分支/流程/节点配置与异常处理，无审批单处理面。

八、取消与初始化。实例 CANCELLED 状态与 on_cancelled 钩子约定已存在，但唯一触达路径是管理员对 EXCEPTION 态实例的异常取消（approval_exception_service.py:177-215）——没有"业务资源被删→系统取消在途单"的服务方法。场景 seed：`_init_default_approval_scenarios`（common/init_data.py:342-436）只为 DEFAULT_TENANT 幂等 seed 频道/知识空间两场景（catch-all 分支→单 or 节点→资源 owner/manager 来源），菜单场景与新租户均不自动 seed。

## key_files
- .claude/skills/approval-module/SKILL.md — 审批模块权威架构参考，本次核实其关键声明均与代码一致；含维护契约（改代码须同步改 skill）
- src/backend/bisheng/approval/domain/services/approval_gate.py — 统一网关：在途去重(92-103)、场景缺失抛错(109-111)、pass/flow/exception 分流、路由匹配(417-460)；「未配置兜底租户管理员」缺口的核心改造点
- src/backend/bisheng/approval/domain/services/approval_center_service.py — decide_task 或签/会签流转(658-801)、_advance_after_node_approved(803-966)、withdraw_instance(418-492，无状态守卫)、get_task_detail(99-203)
- src/backend/bisheng/approval/domain/services/approver_resolver.py — 审批人来源解析；tenant_admin 分支(63-74)错用 AdminRole 系统超管近似真租户管理员——兜底需求的前置修复点
- src/backend/bisheng/approval/domain/services/approval_registry.py — preset 目录(with_default_presets:14-45)+handler 注册表；新场景第一件套
- src/backend/bisheng/approval/domain/services/approval_runtime_handler_factory.py — build_runtime_handler 硬编码 if 链(17-35)；新场景第三件套，outbox/advance/钩子共用
- src/backend/bisheng/approval/domain/services/knowledge_space_subscribe_scenario_handler.py — 场景 Handler 协议实证：build_title/build_detail/resolve_approvers/on_approved/on_rejected/on_withdrawn/on_cancelled
- src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py — 业务入口接网关范式(subscribe_space:4607-4664 先过网关再落业务态；_build_space_approval_gate:4700-4710)；新场景第二件套模板
- src/backend/bisheng/approval/domain/models/approval_instance.py — 9 状态实例模型；payload_snapshot/detail_snapshot JSON 列(61-62)可承载富 payload；CANCELLED 枚举已存在(21)
- src/backend/bisheng/approval/domain/repositories/approval_instance_repository.py — find_duplicate_active_instance(52-69)：在途单去重键含 applicant_user_id、活跃集不含 approved/executing，且命中是静默返回非报错——与 PRD「须先撤回」语义有差
- src/backend/bisheng/approval/domain/services/approval_exception_service.py — 唯一的实例取消路径(177-215，仅限 EXCEPTION 态、管理员操作)；cancel-on-delete 缺口对照物
- src/backend/bisheng/approval/domain/services/approval_outbox_service.py — outbox 执行/重试；成功→executed、失败→execute_failed+异常+通知；发布「终检+上线」动作的承载位
- src/backend/bisheng/approval/domain/services/approval_notification_service.py — 站内信统一封装；_get_admin_recipient_ids(122-150)是真租户管理员解析的正确参照实现
- src/backend/bisheng/common/init_data.py — _init_default_approval_scenarios(342-436)：场景 seed 范式（仅 DEFAULT_TENANT），应用发布场景 seed 可仿此
- src/frontend/client/src/components/approval/ApprovalCenterDialog.tsx — 唯一的审批处理界面（client 端弹窗，1037 行）；TaskDetailPanel(682-724) 通用 key-value 渲染 detail_snapshot，menu_access 特例分支(380)是场景定制的最小先例
- src/frontend/platform/src/pages/ApprovalPage/index.tsx — 管理后台审批页（2524 行）：仅场景配置（preset 下拉 219-270、审批人来源 UI 591-840）+异常处理，无审批单处理面

## reuse
- 统一审批网关与全套流转：应用发布作为新 scenario_code 走 ApprovalGate.request_or_pass → 路由 → 节点 task → decide_task，零框架改动（approval_gate.py + approval_center_service.py）
- 或签语义（GOV-02 多名租户管理员任一人处理即出终态）：node_mode=or 已完整实现——任一人通过→其余 SKIPPED→advance，拒绝→其余 CANCELLED→REJECTED（approval_center_service.py:781-790,691-696）
- 场景配置 UI（GOV-02 复用既有配置能力）：platform ApprovalPage 的 preset 下拉新增场景、分支/流程/节点编辑、direct_user 任意用户选择器、tenant_admin 来源选项与 i18n label 均现成（ApprovalPage/index.tsx:136,181-186,591-840）；后端只需在 with_default_presets 加一条 preset
- 审批人候选=租户内任意用户：direct_user source + platform 用户选择器已满足（approver_resolver.py:45-50 + ApprovalPage user picker:622-713）
- outbox 异步执行（RT-03 step5 终检+上线）：通过→approval_outbox→Celery 默认队列→handler.on_approved，失败→execute_failed 异常+管理员通知+可重试（approval_outbox_service.py:13-84，worker/approval/tasks.py）
- 站内信触达（RT-03 step4 审批人收站内消息与待办 + §3.2）：创建任务/下节点/通过/拒绝/撤回/异常全矩阵现成（ApprovalNotificationService + _send_approval_notify），新场景只需新增 action_code 文案
- 撤回（RT-03 验收6 审批中 owner 可撤回、撤回后再提交生成新单）：withdraw_instance 申请人本人限定+on_withdrawn 钩子+通知审批人现成（approval_center_service.py:418-492）；再提交自然生成新实例（WITHDRAWN 不在去重活跃集）
- 富 payload 承载（能力声明摘要/可见范围快照/资源档位/变更摘要）：payload_snapshot/detail_snapshot 双 JSON 列无 schema 约束，handler.build_detail 可写入任意结构，get_task_detail 原样透出（approval_instance.py:61-62, approval_center_service.py:169-170）——存储与 API 层零改动，仅前端渲染需定制
- 同一应用至多一个在途单（部分复用）：find_duplicate_active_instance 以 business_key=app:{id} 即可获得近似约束（approval_instance_repository.py:52-69），但语义差异见 gaps
- 驳回理由/审批意见：decide_task 的 comment 字段+action_log+通知 reason 链路现成（必填校验需补）
- 全链审计（自审强制审计标注的承载点）：提交/pass/通过/拒绝/撤回/handler 成败均写 AuditLogDao.ainsert_v2，metadata 可扩展 self_approval 标注
- 场景 seed 范式：_init_default_approval_scenarios 的『场景→catch-all 分支→单 or 节点』幂等 seed 可直接仿写应用发布默认流程（init_data.py:316-436）

## gaps
- 未配置兜底=租户管理员（GOV-02 核心规则）：现状三种失败路径没有一条会兜底——场景行缺失/禁用直接 raise ApprovalScenarioDisabledError（发布请求失败）、路由不命中→EXCEPTION(route_missing) 卡异常单、审批人解析为空→EXCEPTION(approver_empty)。需新做兜底机制（gate 级、handler.resolve_approvers 级或按需 seed 级，取向待定）
- tenant_admin 审批人来源解析必须先修：approver_resolver.py:63-74 用 AdminRole(系统超管) 近似，多租户下兜底会落到错误人群；应改用 TenantAdminService.list_tenant_admins（通知侧 approval_notification_service.py:139-141 已有正确实现可搬）
- 提交人自动跳过（GOV-02）：gate 首节点建 task（gate.py:232-248）与 advance 下节点建 task（approval_center_service.py:937-953）均不排除 applicant，需新增排除逻辑 + 『全租户仅一名管理员时允许自审+审计自审标注』分支——现有三场景均无此语义，属新框架能力或场景特化
- 删除应用取消在途审批单（cancel-on-delete）：无系统级 cancel_instance 服务方法；现有终止路径仅申请人撤回与管理员异常取消（仅限 EXCEPTION 态）。CANCELLED 枚举与 on_cancelled 钩子约定已在，需新增可由业务侧（应用删除流程）调用的系统取消方法（置 CANCELLED+取消 PENDING task+通知+审计）
- 应用发布场景『三件套』注册：registry preset + 发布入口构造 Gate/注册 handler + build_runtime_handler if 分支 + AppPublishScenarioHandler（build_detail 组装四类快照、resolve_approvers、on_approved 驱动终检/上线、on_rejected/on_withdrawn/on_cancelled 驱动应用状态机）——全新但有成熟模板
- 定制审批单详情页（RT-03 四分区+操作区）：client TaskDetailPanel 是通用 key-value 网格，需为应用发布做场景定制渲染（头部基本信息/能力声明摘要/可见范围快照+『仅供参考』标注/资源档位/迭代变更摘要分行/『无变更』显式态），现仅 menu_access_request 一个最小特例分支可作先例，建议做成按 scenario_code 分发的详情渲染扩展点
- 『查看待上线版本』审读视图入口 + 预览试用状态区（RT-03 操作区/临时预览实例四态）：审批中心侧需新增入口按钮与状态展示；审读视图/预览实例本体属运行时侧（非审批中心范畴，但详情页需要集成点）
- 驳回理由必填：decide_task 的 comment 可选，需按场景加必填校验（后端 per-scenario 校验或前端强制）
- 在途单语义对齐：PRD『再次提交须先撤回』=显式拒绝，现 gate 去重是静默返回已有实例；且去重键含 applicant_user_id（owner 变更期可能双在途）、活跃状态集不含 approved/executing（审批通过到 executed 之间的窗口可再提交）——发布提交入口需业务层显式 pre-check + 明确报错
- withdraw_instance 状态守卫：需补『仅 PENDING 可撤回』终态守卫，否则发布通过已上线后仍可被翻成 WITHDRAWN（对发布场景是状态机破坏）
- 新租户/存量租户的发布场景初始化：seed 仅覆盖 DEFAULT_TENANT；若走 seed 路线兜底，需要覆盖新建租户钩子或首次提交时懒初始化
- 站内信新 action_code 文案与跳转：应用发布场景的通知文案（build_notify_content）与点击跳转目标（现跳 client 审批弹窗）需按最终处理界面落位调整

## risks
- 【界面落位歧义·高】PRD RT-03/GOV-02 写审批单详情在『平台审批中心』（platform 管理后台），但现状审批任务处理界面只存在于 client 端 /workspace 的 ApprovalCenterDialog，platform ApprovalPage 只有场景配置+异常处理、无任何审批单处理面。若按 PRD 字面在 platform 新建整套『我的审批+详情+操作』是大工作量；若复用 client 弹窗则 PRD 表述需修订，且发布审批人（可能是管理后台角色）要有 client 入口
- 【tenant_admin 解析修正的存量影响】把 approver_resolver 的 tenant_admin 从 AdminRole 改为 TenantAdminService 会同时改变存量已配置 tenant_admin source 节点的实际审批人（从系统超管变为真租户管理员）——修复正确但属行为变更，需评估存量租户影响并在 release note 声明
- 【C4/C3 合规】on_approved 上线动作涉及广场可见性/权限写入必须走 PermissionService→OpenFGA（constitution C4）；outbox 在 Celery worker 执行，handler 内查询需 set_current_tenant_id（skill §11 已有范式），新增表需注册 _TENANT_AWARE_MODEL_MODULES（C3）
- 【模块反向依赖】build_runtime_handler 将 approval 模块指向应用运行时模块（on_approved 调上线服务），与现有 channel/knowledge 同模式可接受，但需局部 import 防循环依赖（现有实现均如此）
- 【假成功红线】skill §6 明确：on_approved 前置条件缺失必须 raise、不得 return 状态字符串伪装成功（现 knowledge handler 的 missing_membership return 即为反例被 skill 点名）；发布 handler 的终检不通过（配额不足→待上线态）与执行失败必须严格区分——PRD 语义里『终检配额不足』是合法业务结果而非失败，on_approved 返回语义要精确设计，否则会落 execute_failed 异常单误导管理员
- 【审批通知时点】『通过』站内信在最后节点 finalize 时发、不等 outbox 执行完（skill §8 注）；发布场景『通过≠已上线』（还有终检），通知文案若写『已上线』会说谎，需要在 outbox 成功回调补真正的上线通知或措辞收敛
- 【多节点审批链】GOV-02 说『审批人/审批链』，引擎支持多节点顺序流转已验证；但提交人自动跳过在多节点链中的语义（跳过整节点 vs 仅从该节点候选中剔除）PRD 未细化，or 节点剔除后若候选为空会落 approver_empty 异常，与『发布不因未配置而卡死』冲突，兜底逻辑必须覆盖此路径
- 【审批人预览身份/审计（NFR-1.2）】属运行时侧实现，但审批单操作区要携带入口；审批例外条款（按 owner 权限放行）与审批中心的权限模型无交集，不要试图在 approval 模块内实现

## open_questions
- 应用发布审批单的处理界面落在哪：client 审批中心弹窗（现状唯一处理面，改造小但入口在工作台）还是 platform 管理后台新建审批处理面（符合 PRD 字面但工作量大）？这是前端工作量的最大变量，需产品拍板
- 兜底『租户管理员』的实现取向：A) gate 通用兜底（改框架，所有场景 route_missing/approver_empty 都受影响）；B) 应用发布 handler 内兜底（resolve_approvers 为空时补租户管理员，局部无副作用）；C) 租户首次提交时懒 seed 默认流程（数据态，管理后台可见可改）——三者对『未配置时场景行显式提示』的 UI 需求支持度不同
- 『提交人自动跳过』是应用发布场景特有规则还是审批中心通用能力升级？若通用，存量三场景（如知识空间 owner 自己申请加入自己管理的空间）行为会变
- 在途单唯一性按『应用』还是『应用+提交人』？现 gate 去重键含 applicant_user_id；应用 owner 转移或多管理员代提场景下会出现双在途，business_key 设计（app:{id} vs app:{id}:user:{uid}）需定
- 驳回/撤回/取消对应用状态机的驱动细节：首发回草稿、迭代弃待上线版本、回滚单终止——这些由 on_rejected/on_withdrawn/on_cancelled 钩子驱动，payload_snapshot 需携带哪些判别字段（version_id、publish_type=首发/迭代/回滚、target_version）需与运行时侧状态机设计对齐
- tenant_admin resolver 修正是否随本特性一并落地并接受存量行为变更，还是为应用发布场景单独新增一个正确的 fallback source 类型（如 tenant_admin_fga）保持存量不动？
- 审批单详情四分区的数据冻结口径：detail_snapshot 在提交时一次性冻结（现机制），审批期间可见范围实时变更『仅供参考』标注是否意味着详情页要同时展示快照值与实时值（后者需详情 API 加实时查询）？
