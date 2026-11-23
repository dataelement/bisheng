# W5 消费面集成、复查与验证（2026-11-06）

本波从范围收敛基线 abb8dc822 延续，先三 agent 只读审计，冻结 [wave5-consumers-contract.md](./wave5-consumers-contract.md) 为 d832ac594，再由 EDGE/PERM/API 三个独立工作树实施，INT 负责前端最小接缝、合流及统一验证。不合入主工作区并发发版线变化；分享签发加固继续外移，无新产品要求。

## 本波完成与边界

完成原157队列中的20项：T127/T128、T135–T138、T143–T148、T153–T156、T224–T227；另完成7个既定需求接缝叶子T598–T604。历史604个编号中465已完成/历史交付（含后续退役）、137当前待办、2外移；当前范围内带复选框602项。新增叶子为遵守每卡至多两文件，不代表新增功能。

生产只改15个Python叶子和2个前端叶子；后端其余19叶为测试，另同步审批skill的一句事实。文件清单见实际diff及下方任务矩阵。use→visible仅替换原使用判断/枚举/旧参数兼容，保publish/share/edit/delete/owner/管理、租户、凭证、状态与业务条件。默认Embedding仍只初始化空间，不联动既有空间；文件edit/rename、旧删除投影顺序和已排除的worker在途IO竞态均未改。

- APP动作DTO现在返回visible，MANAGEMENT_ACTIONS排除visible；前端只认原五类管理动作，unknown/意外旧use不能推导管理能力。required_actions、审批阅读资格与来源前后复核保持。
- AS与工具HTTP默认visible并兼容显式use；原UserPayload、分页/参数/envelope及拒绝路径保持。频道readonly只保visible，所属tenant原管理资格仍独立。
- 工具、Skill和DSH沿原身份/ContextVar/credential scope执行。Skill的全局enabled在available_only使用边界（含显式candidates）独立过滤，管理可见/编辑/重新启用disabled的路径保留；DSH publish仍410。
- 系统应用/工具和builtin Skill不再签出use；Owner只允许非空visible/download。纯可见原等级、Source撤销并集和prepare→projection→finalize复用已有实现。共享支持写类型仍仅llm_server，不激活Root→Child业务资源共享。

T063–T076未冒进：确认计划应用层、job查询/投递恢复及最新retry actor读取、知识专用凭据恢复和同Session Owner协调仍缺真实前置；没有新建fake生产Service或局部改worker来宣称完成。R3/Coverage/迁移、UI与完整E2E仍按137待办推进。

## 任务交付与实际红绿

| 卡组 | 测试/实现固定提交 | 证据 |
| --- | --- | --- |
| T127/T128 | 53df577a0 → e080439f8 | 39绿2红 → 41绿；目标/真实Facade、原actor/scope、活动动作检查 |
| T143/T144 | 27c38136d → a083da9b6 | 10绿2红 → 35绿及9子测试；先纠正测试data_scope常量错误，未伪计产品红 |
| T145/T146 | fcfe99617 → d07bc557f | 8绿5红 → 31绿；使用enabled/管理disabled分离、账户开关保持 |
| T147/T148 | befe25776 → 8c717b7b6 | 4绿5红 → DSH组合49绿 |
| T226/T227 | da2983bf1 → 42980a7ca | 11绿9红 → HTTP20绿；真实ASGI 3动作×4preset选项及错误 |
| T153/T154 | f7bf213e1 → 6caf37df7 | 65绿8红 → 系统/共享/纯可见组合93绿 |
| T224/T225 | 2aa195e76、c34ffa9e4 → 4139adde4 | 15绿8红，真实builtin联合2例首绿；实现后Owner/builtin组合74绿 |
| T135/T136 | 06e51614b → b0ee0e875 | 33绿3红 → APP组合71绿；T599精确前驱正常merge |
| T137/T138 | b9308fb05 → dededfbdb | 8绿4红 → AS组合49绿 |
| T155/T156 | 1ccf0a457 → 9a4dd0be8 | 16绿2红 → CH组合70绿 |
| T598/T599 | c1e94f415 → 82b54376e | 原前端3绿；新6例2红4绿 → 6绿；canonical类型与显式管理白名单 |
| T600 | c6322d987 | 审批skill当前可见来源文案同步，未改审批流程 |
| T601 | b9990c655 | 23例首轮绿，旧preset具体use输入按当前visible合同对齐，拒绝断言保持 |
| T602 | 49d19035e | 旧fixture23绿2红 → 相关组合98绿 |
| T603 | ed7d0680a | 旧fixture6绿1红 → PERM/EDGE最终19文件252绿 |
| T604 | 2bca743bd | 原3个Grant/Catalog fixture既有失败、13绿 → 26绿；原tenant/owner/撤Source/投影断言保留，disabled管理矩阵扩展为15例 |

每卡实际文件、配对和前驱已核，生产/测试提交分开；T604为旧回归对齐，未新增生产行为。T127的Skill联合执行结论等待T146后才勾选。所有新卡和20个原卡仅在主组合与交叉复查后标完成。

## 固定快照复查与正常合流

- PERM agent只读复核API 9a4dd0be8的APP/AS/CH及前端82b54376e，无确认缺陷；核对visible不等管理/发布/分享、原审批资格、actor/分页/状态及readonly管理边界。
- API agent只读复核EDGE 8c717b7b6与PERM ed7d0680a，无确认缺陷；核对Skill enabled、工具原ContextVar/SA/data_scope、DSH410及真实builtin→F048 Runtime→Owner链，关键逻辑未被全链mock掉。
- PERM agent再核EDGE最终42980a7ca的工具HTTP及INT 2bca743bd旧回归，无确认缺陷；原拒绝断言保留，disabled目标可解析不等于执行许可。
- INT逐段审生产diff并正常merge精确SHA：API fa39a9b86，EDGE后PERM最终总装配 **34fcbd7fec1809e5d4dc0513e7c2420f4489f6bc**。无cherry-pick/强制覆盖，三lane提交全部保留。

## 主agent统一验证与限制

受测干净源码：**34fcbd7fec1809e5d4dc0513e7c2420f4489f6bc**。原81路径加本波变更测试及实际相关消费面归一后100路径，**2852 passed、15 subtests passed**，61.64秒，无fail/skip。日志 `/private/tmp/f118-wave5-integrated-tests.log`、同名JSON记录完整命令路径与SHA。所有34个变更Python文件 Ruff/check/format通过，架构违规0、diff-check通过；AS原RULE-3 warning为既有import，未新增架构依赖。

前端主工作树复用本机已有离线依赖，仅建立ignored node_modules只读复用链接；没有安装或改锁文件。当前特性源码测试路径已核。目标6例全绿；全frontend `pnpm lint`通过。平台 `pnpm typecheck` 有22条现存诊断，独立git archive d832基线同环境同命令逐条一致，新增0。初始缺package node_modules造成的解析错误通过补齐本地只读依赖复用解决，不计产品缺陷；剩余22条未扩大修复。日志 `/private/tmp/f118-w5-platform-typecheck-{complete-deps,baseline}.log`。

扩大回归没有伪报全绿：

- 前端同5文件、同测试内容：冻结生产基线9失败/23通过，当前7失败/25通过，逐node确认7个旧失败集合相同、新增0，修复两项预期红。旧 hostedAppDeleteEligibility / hostedAppMenuTrim 的过时身份/菜单测试未改。目标f114AppActions6例全绿。对照日志 `/private/tmp/f118-wave5-platform-tests{,-baseline}.log`。
- API同17路径、同4测试叶：完整archive d832基线34失败/204通过，当前25失败/213通过；剩余25个旧APP query缺permission_runtime、旧hook与owner-only断言完全同集合，新增0，修复9个预期红。未扩写 test_app_query_service.py / test_app_query_service_entry.py；另15相关路径211绿。JUnit基线 `/private/tmp/f118-w5-api-baseline-d832ac594.xml`。

以上均为本地SQLite/领域及真实调用链配IO端口的证据，不证明真实MySQL/DM8、OpenFGA、Redis/Celery、ES/Milvus、模型或浏览器E2E。CI、真实中间件、完整特性E2E、正式回填/Coverage/迁移、演练及部署未执行；无push。27卡完成不等于94条产品AC全验收。

## 临时工作区收束

EDGE/PERM/API三个agent完成并停止写入后，INT两次核对其暂存/未暂存/未跟踪均为空、忽略内容仅Python/pytest/Ruff缓存；三个提交头均已为功能主分支祖先。远端精确查询无同名分支，使用git worktree remove及git branch -d逐个删除，无force；目录和本地分支引用已确认不存在，全部提交由功能主分支保留。保留功能主工作区及其他不相关工作树，未push。

| 已清理分支 | 保留的原提交头 |
| --- | --- |
| codex/3.1.0-beta1/118-w5-edge | 42980a7ca6b7abe545a5eb56c997ebbefe048850 |
| codex/3.1.0-beta1/118-w5-perm | ed7d0680ab4da88b27e837c6e5c45dfd04ea66d1 |
| codex/3.1.0-beta1/118-w5-api | 9a4dd0be803184b1a06ff58de1f1cdc345bc54e1 |

## 本次主组合的100个路径

```text
test/api/test_assistant_knowledge_auth_gate.py
test/api/test_assistant_runlog_frames.py
test/api/test_f040_assistant_list_cursor.py
test/app_publish/reference_fixtures.py
test/app_publish/test_app_credential.py
test/app_publish/test_capability_audit.py
test/app_publish/test_capability_knowledge.py
test/app_publish/test_capability_model.py
test/app_publish/test_capability_revoked.py
test/app_publish/test_f115_current_visibility.py
test/app_runtime/test_capability_env_injection.py
test/app_runtime/test_entry_authz_service.py
test/app_runtime/test_f114_action_authorization.py
test/app_runtime/test_f114_management_content.py
test/app_runtime/test_preview_entry.py
test/assistant
test/celery/test_celery_tenant.py
test/channel/test_channel_create_quota.py
test/channel/test_channel_dismiss_notifications.py
test/channel/test_channel_source_subscription.py
test/channel/test_creation_permission_context_api.py
test/channel/test_f048_channel_permissions.py
test/channel/test_information_knowledge_delivery.py
test/channel/test_information_sync_integration.py
test/channel/test_subscription_state_consistency.py
test/channel/test_unified_permission_creation.py
test/channel/test_unified_permission_update.py
test/chat/test_assistant_stop_lifecycle.py
test/common/test_workflow_auto_rerun_config.py
test/dsh/test_capability_catalog.py
test/dsh/test_work_capabilities.py
test/evaluation
test/knowledge/test_direct_delete_consistency.py
test/knowledge/test_knowledge_create_atomicity.py
test/knowledge/test_knowledge_space_create_quota.py
test/knowledge/test_knowledge_space_info_optimization.py
test/knowledge/test_rebuild_keeps_container_usable.py
test/knowledge/test_rebuild_knowledge_schema.py
test/knowledge/test_space_delete_worker.py
test/knowledge/test_unified_permission_creation.py
test/knowledge_unification
test/linsight/test_personal_skill_lists.py
test/linsight/test_skill_permission_port.py
test/linsight/test_skill_runtime_guard.py
test/linsight/test_user_skills.py
test/llm/test_assistant_llm_executor_default.py
test/llm/test_llm_system_config_consumers.py
test/llm/test_llm_system_config_service.py
test/llm/test_model_catalog.py
test/llm/test_workbench_update_merge.py
test/open_api/test_assistant_completion_errors.py
test/open_api/test_execution_snapshot.py
test/open_api/test_filelib_retrieve_facade.py
test/open_api/test_model_gateway_errors.py
test/open_api/test_model_gateway_stream.py
test/open_api/test_model_range_policy.py
test/open_api/test_workflow_invoke_input_errors.py
test/permission/test_capability_authorization.py
test/permission/test_catalog_model_presets.py
test/permission/test_disabled_catalog_action_listing.py
test/permission/test_f048_action_catalog_policy.py
test/permission/test_f048_api_process_runtime.py
test/permission/test_f048_application_adapters.py
test/permission/test_f048_authorization_model.py
test/permission/test_f048_catalog_api.py
test/permission/test_f048_catalog_bootstrap.py
test/permission/test_f048_catalog_runtime.py
test/permission/test_f048_catalog_service.py
test/permission/test_f048_decision_api.py
test/permission/test_f048_grant_policy.py
test/permission/test_f048_grant_sources.py
test/permission/test_f048_grant_subjects.py
test/permission/test_f048_mode_switch_impact.py
test/permission/test_f048_model_policy.py
test/permission/test_f048_owner_projection.py
test/permission/test_f048_projection_service.py
test/permission/test_f048_resource_api.py
test/permission/test_f048_resource_share_boundary.py
test/permission/test_f048_skill_grant_subjects.py
test/permission/test_f048_visibility_projection.py
test/permission/test_f048_worker_runtime.py
test/permission/test_inactive_model_existing_roster.py
test/permission/test_initial_grant_application.py
test/permission/test_prospective_grant_application.py
test/public_endpoints/test_chat_compatibility.py
test/public_endpoints/test_public_session_ownership.py
test/public_endpoints/test_public_websocket_denial.py
test/tenant/test_tenant_context.py
test/tool/test_f048_tool_permissions.py
test/tool/test_preset_tool_classification.py
test/tool/test_tool_executor_availability.py
test/tool/test_tool_executor_permissions.py
test/workflow/test_app_center_excludes_hosted.py
test/workflow/test_flow_dao_tenant_isolation.py
test/workflow/test_flow_soft_delete.py
test/workflow/test_run_once_off_event_loop.py
test/workflow/test_workflow_action_map.py
test/workflow/test_workflow_auto_rerun_status.py
test/workflow/test_workflow_session_title.py
test/workstation/test_assistant_name_config.py
```
