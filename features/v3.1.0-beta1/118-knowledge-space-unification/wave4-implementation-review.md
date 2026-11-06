# W4剩余业务来源接线与集成复查

本波补齐 APP、频道、知识自身模型和系统默认配置的实际来源维护与读取接线，完成438/597项任务（较W3新增190项）。先冻结接口合同，分工作树并行开发，固定提交独立复查后由主 agent 合流。spec 保持 94 条 AC，不扩文件 edit、不恢复 use，不增加任务模型绑定或 worker 在途外部 IO 竞态治理。完整 F118 仍在开发，本记录不作为发行验收。

## 基线、责任与依赖

初始功能提交 `24481f0ca12ce1a1ef666e194356e7620c7f2c0a`，共同合同提交 `f5db3c79cb589961bb6d370842fcc5cc2a193c00`。主工作区 `feat/3.1.0-beta1@ac65c2fc5` 保持原状；本波不把其他工作树的并发发版线变化混入冻结基线，不称远端最新。

APP、CH、LLM 从合同 checkpoint 建立独立 lane；CH 完成后将 KN 显式交给空闲 agent 的新工作树。公共 REF、权限、gateway/filelib、背景任务上下文、API/Celery 装配和文档由 INT 唯一写入。APP 原授权薄 Port、LLM native/mixed Model Target、KN cleanup Repository 第二叶均在实施前登记转交；每卡最多两叶，禁止共享目录 repo-wide Git 写入。

KN最后三叶worker及旧可用性测试显式转交空闲LLM agent的WORKER新lane，从已集成前置2467edc94冻结分出；KN继续空间生命周期和C3兼容，不并写worker。

依赖顺序是 native sync/权限 READY 与 mixed 批次接口 → 各来源 Repository/Owner → 实际业务增删改 → 严格读取与原身份 → provider/Importer/worker → 总装配。源码按精确 SHA 正常 merge，不 cherry-pick、不 push。无生产 fake、在线造索引或自动 Coverage ready。

## 实际接线与独立复核

| 模块 | 已核实的行为 | 固定提交及独立复查 |
| --- | --- | --- |
| CH | 完整配置包含 disabled；业务和 R2 同 Session；自动化真实有效主体、DIR/parent/SPACE 成员及原 upload_file；whole-source 拒绝先于 Importer；管理保失效 ID | `6b4ae63ef`，主 agent 固定源码及 314 项回归通过 |
| APP | 实际版本 UUID、所有保存历史引用、停止保留、全版本根删除、单事务持久清理 intent；原 principal/上下文、Gateway 最终别名与冻结 slot 核验；saved inspect 保失效行 | 产品 `bc9a76a16`，最终测试常量 `eae516a95`；LLM agent 固定初版200项及类型窄修64项独立LGTM，主agent后继63/52项；作者27路径317项。计数不累计 |
| LLM | 五默认 key 写/读/恢复继承、raw 管理观察、whole-key strict、纯只读名称 findings、全空间 mixed 同事务更新、commit 后派发 7 字段业务命令 | 产品默认写读 `bc2a44593`、最后10811窄修 `75cb7b09a`，最终含旧回归 `3ab5ab61f`；主 agent分步188/97项独立通过，作者最后10路径140项 |
| KN 前置 | 实际模型槽/transition、创建与出向事务、private 配置读取、删除/清空、后台 finalize 和旧更新入口 | 最终 `03a0135da`；主agent分步47/38/54/44/46/77项固定复查通过，作者最后20路径244项；各阶段不累计 |
| WORKER | 两个重建入口读真实pending、旧消息拒、正常partial finalize和global保stage，外部Session一次提交 | `d3617ccf0`，主agent56项、KN agent5路径64项独立LGTM；作者8路径103项 |
| INT | 原生同步来源/legacy/共享读取、真实启动准备、空 union 辅助锁、独立私有读取 graph、Gateway/filelib 原 principal | 分步固定提交红绿和业务 agent 交叉复查；最终组合验证见下节 |

上表为各固定快照，测试通过数不相加。旧已删应用只允许当前真实 assignment/operation 销毁清理事实，保操作 ID 和 cleanup_pending 诊断；不声称 runtime-manager 已有自动 destroy 恢复或 Docker/K8s 实机证明。

最终文档由独立agent对固定提交 `265e985917a4cbdc2e2414a6764d13e1d395b2fc` 只读复核 **LGTM**：与spec及实际交付口径一致，任务597/完成438/未完159和本波新增190项独立核对；contract/design/upgrade/HTML/report/导航/并行任务一致，94AC/140QA/13SVG保留，未将本地回归写成全特性/L2/E2E或部署通过。其后仅补本条复核记录，受测源码不变。

## 事务、执行与观察的边界

1. APP业务检索保持原0/3，通用KN目标的0/1/3不扩大QA能力；历史QA配置保ID标不可用，whole-source在provider前拒。APP 使用真实 AppVersion.id，不用 version_no/自增行或虚构 current；零保存版本根用 SourceRootKey 盘点全部 set/raw。终态历史不重新创建来源。
2. 批写先完整模型 server/model union，再 Root/current Tenant 辅助锁，后 KN/default roots；全 own 和空 union 同样不能把 Tenant 锁推到 source root 后。逐 source 收据和 legacy 证据隔离，不能借另一来源的旧失效资格。
3. Default override 排除将被覆盖 key 对同批各来源的 Root 继承贡献。其他仍继承 key/显式共享保留；否则一次确定性的保存就可能让 KN currentA/pendingB 自身失效。已失效或资格已撤销且非 DELETING 的原槽经明确改绑修复为 B；正常变更保 A/B 双槽。
4. source/raw/digest/版本、原身份与 Session 事务当前重验后，业务配置及 R2 唯一提交；再派发 7 字段业务命令。审计 user_id 不是授权身份，任务无模型引用。旧只有 ID/modelHint/审计 UID、无显式 op/revision/generation 或 stage 的重建消息 IO 前明确拒绝，保留诊断；未来 M2/M3 须盘点并受控处置。外部 Session 的调用者须显式接收命令并在 commit 后派发；无命令出口不允许静默丢命令。
5. 受控逐文件部分失败正常完成后finalize B/PUBLISHED；整体异常、过期或guard失败保当前stage与诊断，不以旧无条件PUBLISHED代码伪装未完成操作已成功。单租户内部模型读取/清理沿C3合法默认1，多租户缺context仍10996，不新增跨租户fallback。
6. read composition 为 User、Knowledge 内部模型和 Default 内部模型建立相互独立 authority 的实际 graph；构造无 SQL/FGA/迁移 IO。READY getter 不懒建异步 Session。
7. Knowledge 私有门面只核实际 own 配置、完整模型引用与资格，不额外增加数据 visible；数据访问仍沿原 AS/WF/文件过滤及 knowledge_auth=False。普通用户 inspect 保原 visible，内部身份不成为 HTTP 许可。
8. APP saved 管理观察仅 Core inspect + uncached 批量名称 findings，不签执行 plan/额外锁，不清配置坏 ID；provider 前另外核 whole-source 和请求别名、实际 ID/server、真实 UUID 冻结 slot。
9. 清理构造不调用模型；实际 index 来自当前 own Knowledge 或已持久领取删除 job 的当前租约/manifest，不能以 isFake 绕过执行准入。清空保留出向模型配置和引用，真实删除解除出向；入向强删失效关系仍保留待人工修复。

## 红绿、旧夹具与静态复查

新业务测试先落固定红提交，再实现；第一轮即绿的已有行为和测试辅助错误均单列，不捏造红阶段。native source/legacy、mixed、READY 启动、最终 Gateway、filelib、真实后台上下文、KN 事务和默认联动均有真实核心/SQLModel/C3 监听器路径；外部 FGA/provider/queue/Importer 使用明确 Port double。

| 问题 / 任务 | 证据 |
| --- | --- |
| T424–T432 native source/legacy/权限 | 同步 SQL 路径不经 async 数据库桥；共享 backend 故障不吞成空共享集，只有稳定的 permission_runtime_not_ready 映射 10994 |
| T433–T435 / T575–T576 mixed | 空 union 红 `8bb477fcc` → `16d01cb3f`；全 own Tenant 锁顺序红 `34bebd75f` → `8eac53a14`；逐来源证据隔离，SQLite 只证明 SQL 顺序 |
| T446–T449 Gateway/filelib | Gateway 8 新用例及既有 range/errors/stream 58 项；filelib fixture 必填 ID 修正后旧 archive 实际 KeyError principal 红 → `5512d38cf`，新旧 18 项；不把 fixture 自身错误算业务红 |
| T532–T542 根/启动/别名 | 实际零版本根、持久清理事实、显式 API/Celery READY bootstrap、原 NamePlan alias 不扩集合，分别由业务 agent 独立复查 |
| T545 / T573 | C3 全目录组合表注册和 AS 默认配置改用真实 SQL 来源，分别保原来源数/tenant 管理 pin/credential OWNED 断言，不注入生产 fake |
| T553–T558 KN finalize/后台 | 删除/清空同外部事务、原对象/事务 proof、实际任务生命周期与 current operation/revision/generation，复制/跨任务/退出后的 proof 均拒绝 |
| T569–T578 APP 旧测试 | 原 entry/preview、capability/model/knowledge/revoked/audit 断言保留，以真实 SQL source/rootGuard/tombstone/原凭证替换退休 DAO 夹具；env4 + credential21 在固定旧 `2a4e7e991` 同失败，共 25 failed/26 passed，生产相关文件与新基线零差异。凭证测试仅显式 legacy v1 与真实 Session 隔离；env 测试 trace 确认旧 provider 回调已无调用方，改验现有 RuntimeDeliveryCoordinator 的事务 stage/真实版本派生 scopes/平台与存储环境/保留变量覆盖及失败不保存 sealed_env、不 wake。旧 env={} / provider callback 契约明确退役，不伪造旧调用，不放宽生产 guard |
| T579–T581 LLM 旧测试 | 从退休 DAO/源签名迁至冻结门面；typed 配置、raw envelope、局部 models 保留/清空/替换及 tenant 透传继续验证。原 explicit tenant 覆盖 Context 和无 tenant 回 Root 与冻结合同冲突，改测当前 tenant 一致和明确拒绝 |

普通文件和QA清理的实际消费者另由INT补T584/T585：2b79b568a 在真实删除模型及重定向 tenant/index场景8红、原空文件行为1首绿，dbcfc2c60 两处构造窄修后与RAG/cleanup组合33通过。保原document_id/file_id过滤和上游引用/授权/投影顺序。

最后盘点清理两处GET自动重建旧消息：T593三个语义红、一个原状态首绿，12523d86f仅移除队列副作用、保只读状态和阶段诊断；旧Info40项、清理残留/space-worker/quota37项和主agent固定最终5路径77项通过。T591/T592把旧DAO/私有signature测试迁到真实命令，保partial/schema，global异常按新stage保护明确差异。

T597在首次81路径总组中暴露4个旧助手发布夹具未配置知识模型读取实例（2384pass/4fail）；只改测试叶883ced181，用真实Knowledge/Model/R2/Core替换退休_get_knowledge stub，保10425/库名/原cause/发布回滚和Milvus错误。新增缺来源index时10994及零provider/vector，Root固定3路径41项独立通过；生产0diff，不以改错误码或放宽guard迁就测试。

知识旧 Endpoint/Service 存在既有 Ruff 诊断。本波逐项比较冻结基线的 rule/message/source 行，区分新增与旧债；不通过全文件 noqa 或随意删旧业务消除告警。arch-guard 按实际 VIOLATION 文本与基线比对，脚本 exit 0 不等于全零。

## 主 agent 最终验证

受测源码：`d4d02e48b7d724c9ffe31d9650b75951eeb94e14`。同一组 **81 个 pytest 路径，2390 passed、6 subtests passed**（55.40秒），无fail/skip；日志`/private/tmp/f118-wave4-integrated-tests.log`，路径/退出码/源码见同名json。包含完整F118、W3全部46路径及本波全部测试卡、APP/CH/LLM/KN相关旧回归、真实后台上下文、最终Gateway/filelib和GET诊断。第一次总组4失败为T597旧夹具，修正后按相同81路径完整重跑；不累计历史2043或各lane结果。

静态：**170个改动Python文件format通过，架构新增违规0，Ruff新增诊断0**。四个legacy文件仍有55条基线诊断：knowledge endpoint10、KnowledgeService38、knowledge_imp6、QA worker1；逐rule/message/source行核对，QA `new_col`仅格式重排用同一AST赋值比较，未把它当新增或声称全文件lint零诊断。完整证据`/private/tmp/f118-wave4-static.json`；原有架构诊断和warning另存，不把脚本exit0当全零。全提交/工作diff-check通过。

任务共**597**，完成**438**，较W3的248新增190项；其余159项保持未完成。唯一ID/DAG/每卡1–2叶/完成依赖及配对/实际文件和94AC自动覆盖索引均核验。原94AC与140QA不变；计数不等于产品AC验收。HTML保13张SVG，ID、锚点/导航/本地链接及全部feature Markdown相对链接验证通过。

任务级L1对照已读task-review清单检查范围、依赖、原权限/C3身份、同Session与失败错误、红绿/真实断言、静态和文档。临时热点转交先登记，所有新增接缝有明确Owner；不将观察当执行、不用fake Runtime进生产，也不靠改预期掩盖错误。特性级L2/E2E另待完整任务完成。

<details><summary>受测81条pytest选择路径（src/backend，父目录不重复选择子文件）</summary>

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
test/app_runtime/test_capability_env_injection.py
test/app_runtime/test_entry_authz_service.py
test/app_runtime/test_preview_entry.py
test/assistant
test/celery/test_celery_tenant.py
test/channel/test_channel_create_quota.py
test/channel/test_channel_dismiss_notifications.py
test/channel/test_channel_source_subscription.py
test/channel/test_information_knowledge_delivery.py
test/channel/test_information_sync_integration.py
test/channel/test_subscription_state_consistency.py
test/channel/test_unified_permission_creation.py
test/channel/test_unified_permission_update.py
test/chat/test_assistant_stop_lifecycle.py
test/common/test_workflow_auto_rerun_config.py
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
test/permission/test_catalog_model_presets.py
test/permission/test_disabled_catalog_action_listing.py
test/permission/test_f048_action_catalog_policy.py
test/permission/test_f048_api_process_runtime.py
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
test/permission/test_f048_projection_service.py
test/permission/test_f048_resource_api.py
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
test/workflow/test_app_center_excludes_hosted.py
test/workflow/test_flow_dao_tenant_isolation.py
test/workflow/test_flow_soft_delete.py
test/workflow/test_run_once_off_event_loop.py
test/workflow/test_workflow_action_map.py
test/workflow/test_workflow_auto_rerun_status.py
test/workflow/test_workflow_session_title.py
test/workstation/test_assistant_name_config.py
```

本轮复用主工作区既有Python3.11.13 venv、只读config路径，`PYTHONPATH=.`指当前功能源码；未同步依赖/锁文件、未启动真实API/worker或访问中间件。

</details>

## 剩余范围与升级约束

原 94 条产品 AC 保持，任务完成数不是 AC 验收数。真实 Coverage 持久适配、六类来源全量回填与对账、完整入向 R3 删除协调/恢复、处理框架、两端页面、分享签发 ACL T404/T405、正式迁移脚本及全特性 L2/E2E 仍按未完成卡推进。实际业务出向接线不替代这些前置。

API 取消两个默认 JSON 在线 backfill。正式升级必须由运维停服/停写并一致备份，再正式盘点和冻结引用及全平台权限 baseline/plan；M3 转换和回填沿同 run，脚本不检测或控制停服。缺 index/coverage 拒绝，不在线自愈。

本地 SQLite/SQL 形状与 Port 测试不证明真实 MySQL/DM8 锁竞争、OpenFGA、Redis/Celery、ES/Milvus、模型服务或浏览器 E2E。CI、正式迁移、部署均未执行；本波无 push，未修改主工作区。


## 独立评审后修正：Linsight进程装配

在945b52282基础上复核发现，独立Linsight进程原来仅注册F048，缺少业务默认模型/知识读取graph，冷启动后get_workbench_llm会10994。本次按单生产文件的hotfix修正：ScheduleCenterProcess.run在原进程事件循环内、F048上下文登记后准备READY权限runtime并注册真实引用composition，之后才创建NodeManager/心跳或接收任务；openfga关闭时仍装配读取graph。权限准备或装配失败明确阻止继续启动，不懒建另一数据库桥，不改变来源/模型权限或配置返回协议。

新增test_linsight_reference_bootstrap.py直接执行真实run入口和真实composition，隔离Redis/权限transport/heartbeat：enabled开关两种冷启动及两类失败共4项，修复前4红、修后4绿。与既有native/bootstrap/composition/default读取及Linsight stranded/HITL/deferred、F048 API/worker组合11路径109 passed；两Python文件Ruff/format及arch-guard通过。该结果是定向本地回归，不替代前述W4全组历史结果或真实进程/中间件E2E。

同次评审的ASR响应问题随后修复：普通GET /llm/workbench在既有用户目录投影后，复制响应配置并按实际asr_rt模型类型派生realtime，不信持久化的旧布尔值；模型/服务已删除或ID格式无效时保留原ID、能力为False，查询故障明确传播，不初始化provider。GET /llm/workbench/settings继续无模型查询的raw读取，不改存储或全来源执行校验。新增9项行为覆盖，修前8红/原空ASR1绿，修后相关默认配置组合72项通过；测试中对冻结DSH配置的错误修改已改为隔离外部目录投影边界，不算业务红。
