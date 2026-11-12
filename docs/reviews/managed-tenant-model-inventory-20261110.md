# 租户边界：ORM 模型结构清单（2026-11-10）

基线：`24c02859e2582ed319281bb52285c99930daf81c`。该清单为业务边界梳理的结构覆盖依据，不是运行数据库表数，也不是逐接口安全验收。

扫描 `src/backend/bisheng/**/*.py`（排除 Alembic 修订），静态识别显式 `table=True` 的顶层模型，并沿本文件/导入基类追踪 `tenant_id` 声明。共 **184 个模型、184 个不同表名，其中 150 个声明或继承 tenant_id，34 个未发现该字段**。未执行模型导入、数据库连接或 DDL；未声称全部模型当前都注册到运行时过滤器。此统计取代旧架构文档表数作为本轮结构清单，但不修改旧文档。

类别是本轮提出的业务政策归类，不能由列是否存在直接推出：

| 代码 | 分类及约束 | 数量 |
| --- | --- | --- |
| T | 租户业务/运行/授权/操作记录：默认依所属业务租户隔离，子记录继承父对象 | 142 |
| G | 平台目录/控制面：按平台维护资格或明确公共目录契约，不按所选租户机械过滤 | 16 |
| I | 身份/组织/租户目录：跨租户解析须限定主体、关系及组织授权，不是全局开放 | 7 |
| P | 父对象派生/关联：先验证父对象；双父关系同时验证两侧归属 | 9 |
| U | 个人偏好加资源引用：按本人读取，再检查所引用资源当前可见性 | 3 |
| M | 混合定义/预置/配置：按类型或配置 key 的专门协议区分，不能整体 bypass | 4 |
| B | 角色定义关联或用户生效绑定：按正文定义的不同边界读取和写入 | 2 |
| L | 遗留路径：不可因无 tenant_id 认定为公共目录；先验证入口活性 | 1 |

代表性的例外：`channel_info_source` 虽有 tenant_id，运行时明确排除过滤；`user_tenant.tenant_id` 表示成员归属；`department.tenant_id` 可为存储租户；`role` 同表存全局与租户定义；`roleaccess` 继承定义归属而 `userrole` 是用户生效绑定。`dashboard_dataset` 是仪表盘查询 schema 目录，不能据此放开其底层 ES 业务数据。

`dataset` 的旧 `api/v1/dataset.py` 未在当前 `api/router.py` 和 `api/v1/__init__.py` 注册，且全仓引用集中于旧 service/router；作为遗留结构保留，不能将其无过滤实现报告为已证实的当前 HTTP 泄漏。重新启用前须重新设计所属租户和权限。

以下每行只核对模型结构与分类。领域级生产者、消费者和授权语义见 [业务边界正文](managed-tenant-boundary-assessment-20261110.md)；具体接口和外部存储运行验收状态不得从本表推断。

## app_governance（2）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `runtime_audit_export` | 有 | T | [RuntimeAuditExport](../../src/backend/bisheng/app_governance/domain/models/runtime_audit.py)，类起始行 27 |
| `runtime_audit_query_snapshot` | 有 | T | [RuntimeAuditQuerySnapshot](../../src/backend/bisheng/app_governance/domain/models/runtime_audit.py)，类起始行 13 |

## app_publish（5）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `app_deployment` | 有 | T | [AppDeployment](../../src/backend/bisheng/app_publish/domain/models/app_deployment.py)，类起始行 107 |
| `app_preview_session` | 有 | T | [AppPreviewSession](../../src/backend/bisheng/app_publish/domain/models/app_preview_session.py)，类起始行 73 |
| `app_secret_config` | 有 | T | [AppSecretConfig](../../src/backend/bisheng/app_publish/domain/models/app_secret_config.py)，类起始行 12 |
| `app_capability_call_record` | 有 | T | [AppCapabilityCallRecord](../../src/backend/bisheng/app_publish/domain/models/capability_call_record.py)，类起始行 49 |
| `hosted_app_subject` | 无 | P | [HostedAppSubject](../../src/backend/bisheng/app_publish/domain/models/hosted_app_subject.py)，类起始行 44 |

## app_runtime（18）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `runtime_artifact` | 有 | T | [RuntimeArtifact](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 56 |
| `runtime_assignment` | 有 | T | [RuntimeAssignment](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 105 |
| `runtime_capacity_reservation` | 有 | T | [RuntimeCapacityReservation](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 133 |
| `runtime_credential_binding` | 有 | T | [RuntimeCredentialBinding](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 157 |
| `runtime_delivery` | 有 | T | [RuntimeDelivery](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 73 |
| `runtime_dependency_plan` | 有 | T | [RuntimeDependencyPlan](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 231 |
| `runtime_egress_policy` | 有 | T | [RuntimeEgressPolicy](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 181 |
| `runtime_execution_fact` | 有 | T | [RuntimeExecutionFact](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 144 |
| `runtime_node` | 无 | G | [RuntimeNode](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 115 |
| `runtime_operation` | 有 | T | [RuntimeOperation](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 84 |
| `runtime_profile` | 无 | G | [RuntimeProfile](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 35 |
| `runtime_profile_default` | 无 | G | [RuntimeProfileDefault](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 48 |
| `runtime_route` | 有 | T | [RuntimeRoute](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 166 |
| `runtime_storage_binding` | 有 | T | [RuntimeStorageBinding](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 219 |
| `runtime_transfer` | 有 | T | [RuntimeTransfer](../../src/backend/bisheng/app_runtime/domain/models/runtime_delivery.py)，类起始行 195 |
| `runtime_host_isolation_report` | 无 | G | [RuntimeHostIsolationReport](../../src/backend/bisheng/app_runtime/domain/models/runtime_host_isolation.py)，类起始行 12 |
| `runtime_execution_resource` | 有 | T | [RuntimeExecutionResource](../../src/backend/bisheng/app_runtime/domain/models/runtime_kubernetes.py)，类起始行 18 |
| `runtime_material_delegation` | 有 | T | [RuntimeMaterialDelegation](../../src/backend/bisheng/app_runtime/domain/models/runtime_kubernetes.py)，类起始行 49 |

## approval（12）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `approval_action_log` | 有 | T | [ApprovalActionLog](../../src/backend/bisheng/approval/domain/models/approval_instance.py)，类起始行 155 |
| `approval_exception` | 有 | T | [ApprovalException](../../src/backend/bisheng/approval/domain/models/approval_instance.py)，类起始行 120 |
| `approval_instance` | 有 | T | [ApprovalInstance](../../src/backend/bisheng/approval/domain/models/approval_instance.py)，类起始行 69 |
| `approval_outbox` | 有 | T | [ApprovalOutbox](../../src/backend/bisheng/approval/domain/models/approval_instance.py)，类起始行 138 |
| `approval_task` | 有 | T | [ApprovalTask](../../src/backend/bisheng/approval/domain/models/approval_instance.py)，类起始行 101 |
| `approval_request` | 有 | T | [ApprovalRequest](../../src/backend/bisheng/approval/domain/models/approval_request.py)，类起始行 82 |
| `approval_flow_definition` | 有 | T | [ApprovalFlowDefinition](../../src/backend/bisheng/approval/domain/models/approval_scenario.py)，类起始行 59 |
| `approval_flow_version` | 有 | T | [ApprovalFlowVersion](../../src/backend/bisheng/approval/domain/models/approval_scenario.py)，类起始行 76 |
| `approval_node_definition` | 有 | T | [ApprovalNodeDefinition](../../src/backend/bisheng/approval/domain/models/approval_scenario.py)，类起始行 96 |
| `approval_route_rule` | 有 | T | [ApprovalRouteRule](../../src/backend/bisheng/approval/domain/models/approval_scenario.py)，类起始行 43 |
| `approval_scenario` | 有 | T | [ApprovalScenario](../../src/backend/bisheng/approval/domain/models/approval_scenario.py)，类起始行 23 |
| `user_menu_access` | 有 | T | [UserMenuAccess](../../src/backend/bisheng/approval/domain/models/user_menu_access.py)，类起始行 40 |

## channel（5）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `channel_article_read` | 有 | T | [ArticleReadRecord](../../src/backend/bisheng/channel/domain/models/article_read_record.py)，类起始行 12 |
| `channel` | 有 | T | [Channel](../../src/backend/bisheng/channel/domain/models/channel.py)，类起始行 62 |
| `channel_info_source` | 有 | G | [ChannelInfoSource](../../src/backend/bisheng/channel/domain/models/channel_info_source.py)，类起始行 11 |
| `channel_knowledge_sync` | 无 | P | [ChannelKnowledgeSync](../../src/backend/bisheng/channel/domain/models/channel_knowledge_sync.py)，类起始行 32 |
| `channel_user_pin` | 无 | U | [ChannelUserPin](../../src/backend/bisheng/channel/domain/models/channel_user_pin.py)，类起始行 30 |

## chat_session（5）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `chat_project` | 有 | T | [ChatProject](../../src/backend/bisheng/chat_session/domain/models/project.py)，类起始行 13 |
| `chat_project_membership` | 有 | T | [ChatProjectMembership](../../src/backend/bisheng/chat_session/domain/models/project.py)，类起始行 24 |
| `chat_project_receipt` | 有 | T | [ChatProjectReceipt](../../src/backend/bisheng/chat_session/domain/models/project.py)，类起始行 39 |
| `chat_project_revision` | 有 | T | [ChatProjectRevision](../../src/backend/bisheng/chat_session/domain/models/project.py)，类起始行 32 |
| `workflow_file_manifest` | 有 | T | [WorkflowFileManifest](../../src/backend/bisheng/chat_session/domain/models/workflow_file_manifest.py)，类起始行 9 |

## citation（2）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `message_citation` | 无 | P | [MessageCitation](../../src/backend/bisheng/citation/domain/models/message_citation.py)，类起始行 30 |
| `message_citation_relation` | 有 | T | [MessageCitationRelation](../../src/backend/bisheng/citation/domain/models/message_citation.py)，类起始行 55 |

## commercial_license（1）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `license_info` | 无 | G | [LicenseInfo](../../src/backend/bisheng/commercial_license/domain/models/license_info.py)，类起始行 10 |

## common（2）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `config` | 无 | M | [Config](../../src/backend/bisheng/common/models/config.py)，类起始行 45 |
| `space_channel_member` | 无 | P | [SpaceChannelMember](../../src/backend/bisheng/common/models/space_channel_member.py)，类起始行 99 |

## database（36）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `app` | 有 | T | [App](../../src/backend/bisheng/database/models/app.py)，类起始行 58 |
| `app_access_log` | 有 | T | [AppAccessLog](../../src/backend/bisheng/database/models/app_access_log.py)，类起始行 44 |
| `app_instance` | 有 | T | [AppInstance](../../src/backend/bisheng/database/models/app_instance.py)，类起始行 46 |
| `app_version` | 无 | P | [AppVersion](../../src/backend/bisheng/database/models/app_version.py)，类起始行 54 |
| `assistant` | 有 | T | [Assistant](../../src/backend/bisheng/database/models/assistant.py)，类起始行 88 |
| `assistantlink` | 有 | T | [AssistantLink](../../src/backend/bisheng/database/models/assistant.py)，类起始行 92 |
| `auditlog` | 有 | T | [AuditLog](../../src/backend/bisheng/database/models/audit_log.py)，类起始行 199 |
| `dataset` | 无 | L | [Dataset](../../src/backend/bisheng/database/models/dataset.py)，类起始行 25 |
| `department` | 有 | I | [Department](../../src/backend/bisheng/database/models/department.py)，类起始行 50 |
| `user_department` | 无 | I | [UserDepartment](../../src/backend/bisheng/database/models/department.py)，类起始行 252 |
| `department_admin_grant` | 无 | I | [DepartmentAdminGrant](../../src/backend/bisheng/database/models/department_admin_grant.py)，类起始行 21 |
| `failed_tuple` | 有 | T | [FailedTuple](../../src/backend/bisheng/database/models/failed_tuple.py)，类起始行 53 |
| `flow` | 有 | T | [Flow](../../src/backend/bisheng/database/models/flow.py)，类起始行 118 |
| `flowversion` | 有 | T | [FlowVersion](../../src/backend/bisheng/database/models/flow_version.py)，类起始行 56 |
| `group` | 有 | T | [Group](../../src/backend/bisheng/database/models/group.py)，类起始行 30 |
| `groupresource` | 有 | T | [GroupResource](../../src/backend/bisheng/database/models/group_resource.py)，类起始行 43 |
| `invitecode` | 有 | T | [InviteCode](../../src/backend/bisheng/database/models/invite_code.py)，类起始行 35 |
| `markappuser` | 有 | T | [MarkAppUser](../../src/backend/bisheng/database/models/mark_app_user.py)，类起始行 31 |
| `markrecord` | 有 | T | [MarkRecord](../../src/backend/bisheng/database/models/mark_record.py)，类起始行 40 |
| `marktask` | 有 | T | [MarkTask](../../src/backend/bisheng/database/models/mark_task.py)，类起始行 36 |
| `chatmessage` | 有 | T | [ChatMessage](../../src/backend/bisheng/database/models/message.py)，类起始行 90 |
| `recallchunk` | 无 | P | [RecallChunk](../../src/backend/bisheng/database/models/recall_chunk.py)，类起始行 25 |
| `t_report` | 有 | T | [Report](../../src/backend/bisheng/database/models/report.py)，类起始行 34 |
| `resource_tier` | 无 | G | [ResourceTier](../../src/backend/bisheng/database/models/resource_tier.py)，类起始行 54 |
| `role` | 有 | M | [Role](../../src/backend/bisheng/database/models/role.py)，类起始行 60 |
| `roleaccess` | 有 | B | [RoleAccess](../../src/backend/bisheng/database/models/role_access.py)，类起始行 30 |
| `message_session` | 有 | T | [MessageSession](../../src/backend/bisheng/database/models/session.py)，类起始行 92 |
| `tag` | 有 | T | [Tag](../../src/backend/bisheng/database/models/tag.py)，类起始行 40 |
| `taglink` | 有 | T | [TagLink](../../src/backend/bisheng/database/models/tag.py)，类起始行 63 |
| `template` | 有 | M | [Template](../../src/backend/bisheng/database/models/template.py)，类起始行 31 |
| `tenant` | 无 | I | [Tenant](../../src/backend/bisheng/database/models/tenant.py)，类起始行 33 |
| `user_tenant` | 有 | I | [UserTenant](../../src/backend/bisheng/database/models/tenant.py)，类起始行 125 |
| `usergroup` | 有 | T | [UserGroup](../../src/backend/bisheng/database/models/user_group.py)，类起始行 38 |
| `user_link` | 无 | I | [UserLink](../../src/backend/bisheng/database/models/user_link.py)，类起始行 24 |
| `userrole` | 有 | B | [UserRole](../../src/backend/bisheng/database/models/user_role.py)，类起始行 27 |
| `t_variable_value` | 有 | T | [Variable](../../src/backend/bisheng/database/models/variable_value.py)，类起始行 59 |

## dsh（28）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `dsh_admin_operation` | 有 | T | [DshAdminOperation](../../src/backend/bisheng/dsh/domain/models/admin_operation.py)，类起始行 13 |
| `dsh_content_safety_event` | 有 | T | [DshContentSafetyEvent](../../src/backend/bisheng/dsh/domain/models/content_safety_event.py)，类起始行 13 |
| `dsh_refresh_token` | 有 | T | [DshRefreshToken](../../src/backend/bisheng/dsh/domain/models/local_session.py)，类起始行 31 |
| `dsh_session` | 有 | T | [DshSession](../../src/backend/bisheng/dsh/domain/models/local_session.py)，类起始行 11 |
| `dsh_model_audit_body_access` | 有 | T | [DshModelAuditBodyAccess](../../src/backend/bisheng/dsh/domain/models/model_audit_content.py)，类起始行 76 |
| `dsh_model_audit_content` | 有 | T | [DshModelAuditContent](../../src/backend/bisheng/dsh/domain/models/model_audit_content.py)，类起始行 21 |
| `dsh_model_audit_occurrence` | 有 | T | [DshModelAuditOccurrence](../../src/backend/bisheng/dsh/domain/models/model_audit_content.py)，类起始行 51 |
| `dsh_model_audit_conversation` | 有 | T | [DshModelAuditConversation](../../src/backend/bisheng/dsh/domain/models/model_audit_conversation.py)，类起始行 12 |
| `dsh_model_audit_evidence` | 有 | T | [DshModelAuditEvidence](../../src/backend/bisheng/dsh/domain/models/model_audit_request.py)，类起始行 133 |
| `dsh_model_audit_manifest` | 有 | T | [DshModelAuditManifest](../../src/backend/bisheng/dsh/domain/models/model_audit_request.py)，类起始行 157 |
| `dsh_model_audit_request` | 有 | T | [DshModelAuditRequest](../../src/backend/bisheng/dsh/domain/models/model_audit_request.py)，类起始行 23 |
| `dsh_model_audit_setting` | 有 | T | [DshModelAuditSetting](../../src/backend/bisheng/dsh/domain/models/model_audit_setting.py)，类起始行 21 |
| `dsh_model_audit_setting_change` | 有 | T | [DshModelAuditSettingChange](../../src/backend/bisheng/dsh/domain/models/model_audit_setting.py)，类起始行 48 |
| `dsh_model_audit_conversation_title` | 有 | T | [DshModelAuditConversationTitle](../../src/backend/bisheng/dsh/domain/models/model_audit_title.py)，类起始行 12 |
| `dsh_audit_tree_node` | 有 | T | [DshAuditTreeNode](../../src/backend/bisheng/dsh/domain/models/model_audit_tree.py)，类起始行 50 |
| `dsh_audit_tree_path` | 有 | T | [DshAuditTreePath](../../src/backend/bisheng/dsh/domain/models/model_audit_tree.py)，类起始行 100 |
| `dsh_audit_tree_state` | 有 | T | [DshAuditTreeState](../../src/backend/bisheng/dsh/domain/models/model_audit_tree.py)，类起始行 12 |
| `dsh_model_call` | 有 | T | [DshModelCall](../../src/backend/bisheng/dsh/domain/models/model_call.py)，类起始行 12 |
| `dsh_monthly_usage` | 有 | T | [DshMonthlyUsage](../../src/backend/bisheng/dsh/domain/models/monthly_usage.py)，类起始行 12 |
| `dsh_subject_grant` | 有 | T | [DshSubjectGrant](../../src/backend/bisheng/dsh/domain/models/subject_grant.py)，类起始行 10 |
| `dsh_subject_policy` | 有 | T | [DshSubjectPolicy](../../src/backend/bisheng/dsh/domain/models/subject_policy.py)，类起始行 12 |
| `dsh_subject_policy_audit` | 有 | T | [DshSubjectPolicyAudit](../../src/backend/bisheng/dsh/domain/models/subject_policy.py)，类起始行 52 |
| `dsh_credit_rule` | 有 | T | [CreditRule](../../src/backend/bisheng/dsh/domain/models/unified_policy.py)，类起始行 34 |
| `dsh_model_visibility` | 有 | T | [ModelVisibility](../../src/backend/bisheng/dsh/domain/models/unified_policy.py)，类起始行 12 |
| `dsh_personal_ledger_state` | 有 | T | [PersonalLedgerState](../../src/backend/bisheng/dsh/domain/models/unified_policy.py)，类起始行 72 |
| `dsh_unified_policy_audit` | 有 | T | [UnifiedPolicyAudit](../../src/backend/bisheng/dsh/domain/models/unified_policy.py)，类起始行 56 |
| `dsh_user_policy` | 有 | T | [DshUserPolicy](../../src/backend/bisheng/dsh/domain/models/user_policy.py)，类起始行 12 |
| `dsh_work_publication` | 有 | T | [DshWorkPublication](../../src/backend/bisheng/dsh/domain/models/work_publication.py)，类起始行 8 |

## dsh_market（9）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `dsh_market_audit` | 有 | T | [MarketAudit](../../src/backend/bisheng/dsh_market/domain/models/__init__.py)，类起始行 59 |
| `dsh_market_device` | 有 | T | [MarketDevice](../../src/backend/bisheng/dsh_market/domain/models/__init__.py)，类起始行 74 |
| `dsh_market_import` | 有 | T | [MarketImport](../../src/backend/bisheng/dsh_market/domain/models/__init__.py)，类起始行 46 |
| `dsh_market_install_policy` | 有 | T | [MarketInstallPolicy](../../src/backend/bisheng/dsh_market/domain/models/__init__.py)，类起始行 85 |
| `dsh_market_plugin` | 有 | T | [MarketPlugin](../../src/backend/bisheng/dsh_market/domain/models/__init__.py)，类起始行 16 |
| `dsh_market_version` | 有 | T | [MarketVersion](../../src/backend/bisheng/dsh_market/domain/models/__init__.py)，类起始行 31 |
| `dsh_market_workbench` | 有 | T | [MarketWorkbench](../../src/backend/bisheng/dsh_market/domain/models/__init__.py)，类起始行 96 |
| `dsh_market_workbench_import` | 有 | T | [MarketWorkbenchImport](../../src/backend/bisheng/dsh_market/domain/models/__init__.py)，类起始行 129 |
| `dsh_market_workbench_version` | 有 | T | [MarketWorkbenchVersion](../../src/backend/bisheng/dsh_market/domain/models/__init__.py)，类起始行 116 |

## evaluation（1）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `evaluation` | 有 | T | [Evaluation](../../src/backend/bisheng/evaluation/domain/models/evaluation.py)，类起始行 50 |

## finetune（5）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `finetune` | 有 | T | [Finetune](../../src/backend/bisheng/finetune/domain/models/finetune.py)，类起始行 88 |
| `modeldeploy` | 有 | T | [ModelDeploy](../../src/backend/bisheng/finetune/domain/models/model_deploy.py)，类起始行 32 |
| `presettrain` | 有 | T | [PresetTrain](../../src/backend/bisheng/finetune/domain/models/preset_train.py)，类起始行 33 |
| `server` | 有 | T | [Server](../../src/backend/bisheng/finetune/domain/models/server.py)，类起始行 29 |
| `sftmodel` | 有 | T | [SftModel](../../src/backend/bisheng/finetune/domain/models/sft_model.py)，类起始行 27 |

## knowledge（9）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `department_knowledge_space` | 有 | T | [DepartmentKnowledgeSpace](../../src/backend/bisheng/knowledge/domain/models/department_knowledge_space.py)，类起始行 81 |
| `knowledge` | 有 | T | [Knowledge](../../src/backend/bisheng/knowledge/domain/models/knowledge.py)，类起始行 129 |
| `knowledge_document` | 无 | P | [KnowledgeDocument](../../src/backend/bisheng/knowledge/domain/models/knowledge_document.py)，类起始行 38 |
| `knowledge_document_version` | 无 | P | [KnowledgeDocumentVersion](../../src/backend/bisheng/knowledge/domain/models/knowledge_document_version.py)，类起始行 35 |
| `knowledgefile` | 有 | T | [KnowledgeFile](../../src/backend/bisheng/knowledge/domain/models/knowledge_file.py)，类起始行 209 |
| `qaknowledge` | 有 | T | [QAKnowledge](../../src/backend/bisheng/knowledge/domain/models/knowledge_file.py)，类起始行 215 |
| `knowledge_space_delete_job` | 有 | T | [KnowledgeSpaceDeleteJob](../../src/backend/bisheng/knowledge/domain/models/knowledge_space_delete_job.py)，类起始行 19 |
| `knowledge_space_tag_library` | 有 | T | [KnowledgeSpaceTagLibrary](../../src/backend/bisheng/knowledge/domain/models/knowledge_space_tag_library.py)，类起始行 85 |
| `knowledge_space_user_pin` | 无 | U | [KnowledgeSpaceUserPin](../../src/backend/bisheng/knowledge/domain/models/knowledge_space_user_pin.py)，类起始行 30 |

## linsight（5）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `linsight_execute_task` | 有 | T | [LinsightExecuteTask](../../src/backend/bisheng/linsight/domain/models/linsight_execute_task.py)，类起始行 82 |
| `linsight_session_version` | 有 | T | [LinsightSessionVersion](../../src/backend/bisheng/linsight/domain/models/linsight_session_version.py)，类起始行 152 |
| `linsight_skill` | 有 | T | [LinsightSkill](../../src/backend/bisheng/linsight/domain/models/linsight_skill.py)，类起始行 127 |
| `linsight_sop` | 有 | T | [LinsightSOP](../../src/backend/bisheng/linsight/domain/models/linsight_sop.py)，类起始行 45 |
| `linsight_sop_record` | 有 | T | [LinsightSOPRecord](../../src/backend/bisheng/linsight/domain/models/linsight_sop.py)，类起始行 53 |

## llm（5）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `llm_call_log` | 有 | T | [LLMCallLog](../../src/backend/bisheng/llm/domain/models/llm_call_log.py)，类起始行 70 |
| `llm_model` | 有 | T | [LLMModel](../../src/backend/bisheng/llm/domain/models/llm_server.py)，类起始行 100 |
| `llm_server` | 有 | T | [LLMServer](../../src/backend/bisheng/llm/domain/models/llm_server.py)，类起始行 93 |
| `llm_token_log` | 有 | T | [LLMTokenLog](../../src/backend/bisheng/llm/domain/models/llm_token_log.py)，类起始行 80 |
| `tenant_system_model_config` | 有 | T | [TenantSystemModelConfig](../../src/backend/bisheng/llm/domain/models/tenant_system_model_config.py)，类起始行 66 |

## message（2）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `inbox_message` | 有 | T | [InboxMessage](../../src/backend/bisheng/message/domain/models/inbox_message.py)，类起始行 22 |
| `inbox_message_read` | 有 | T | [InboxMessageRead](../../src/backend/bisheng/message/domain/models/inbox_message_read.py)，类起始行 10 |

## open_api（5）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `api_credential` | 有 | T | [ApiCredential](../../src/backend/bisheng/open_api/domain/models/api_credential.py)，类起始行 49 |
| `api_credential_delegate_scope` | 有 | T | [ApiCredentialDelegateScope](../../src/backend/bisheng/open_api/domain/models/credential_delegate_scope.py)，类起始行 15 |
| `model_call_record` | 有 | T | [ModelCallRecord](../../src/backend/bisheng/open_api/domain/models/model_call_record.py)，类起始行 36 |
| `open_api_tenant_setting` | 有 | T | [OpenApiTenantSetting](../../src/backend/bisheng/open_api/domain/models/open_api_tenant_setting.py)，类起始行 20 |
| `service_account` | 有 | T | [ServiceAccount](../../src/backend/bisheng/open_api/domain/models/service_account.py)，类起始行 14 |

## org_sync（2）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `org_sync_config` | 有 | T | [OrgSyncConfig](../../src/backend/bisheng/org_sync/domain/models/org_sync.py)，类起始行 59 |
| `org_sync_log` | 有 | T | [OrgSyncLog](../../src/backend/bisheng/org_sync/domain/models/org_sync.py)，类起始行 191 |

## permission（15）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `permission_action` | 无 | G | [PermissionAction](../../src/backend/bisheng/permission/domain/models/catalog.py)，类起始行 111 |
| `permission_action_resource_scope` | 无 | G | [PermissionActionResourceScope](../../src/backend/bisheng/permission/domain/models/catalog.py)，类起始行 165 |
| `permission_catalog_projection_tuple` | 无 | G | [PermissionCatalogProjectionTuple](../../src/backend/bisheng/permission/domain/models/catalog.py)，类起始行 327 |
| `permission_catalog_release` | 无 | G | [PermissionCatalogRelease](../../src/backend/bisheng/permission/domain/models/catalog.py)，类起始行 36 |
| `permission_model` | 无 | G | [PermissionModel](../../src/backend/bisheng/permission/domain/models/catalog.py)，类起始行 206 |
| `permission_model_action` | 无 | G | [PermissionModelAction](../../src/backend/bisheng/permission/domain/models/catalog.py)，类起始行 279 |
| `permission_grant` | 有 | T | [PermissionGrant](../../src/backend/bisheng/permission/domain/models/grant.py)，类起始行 49 |
| `permission_grant_assignee` | 有 | T | [PermissionGrantAssignee](../../src/backend/bisheng/permission/domain/models/grant.py)，类起始行 110 |
| `resource_permission_mode` | 有 | T | [ResourcePermissionMode](../../src/backend/bisheng/permission/domain/models/grant.py)，类起始行 195 |
| `authorization_model_release` | 无 | G | [AuthorizationModelRelease](../../src/backend/bisheng/permission/domain/models/migration.py)，类起始行 55 |
| `permission_migration_item` | 有 | T | [PermissionMigrationItem](../../src/backend/bisheng/permission/domain/models/migration.py)，类起始行 244 |
| `permission_migration_run` | 无 | G | [PermissionMigrationRun](../../src/backend/bisheng/permission/domain/models/migration.py)，类起始行 119 |
| `permission_projection_operation` | 有 | T | [PermissionProjectionOperation](../../src/backend/bisheng/permission/domain/models/projection.py)，类起始行 50 |
| `permission_projection_tuple` | 有 | T | [PermissionProjectionTuple](../../src/backend/bisheng/permission/domain/models/projection.py)，类起始行 131 |
| `permission_visible_source_projection` | 有 | T | [PermissionVisibleSourceProjection](../../src/backend/bisheng/permission/domain/models/projection.py)，类起始行 194 |

## sensitive_word（1）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `sensitive_word_policy` | 有 | T | [SensitiveWordPolicy](../../src/backend/bisheng/sensitive_word/domain/models/sensitive_word_policy.py)，类起始行 70 |

## share_link（1）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `share_link` | 有 | T | [ShareLink](../../src/backend/bisheng/share_link/domain/models/share_link.py)，类起始行 46 |

## telemetry_search（4）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `dashboard` | 有 | M | [Dashboard](../../src/backend/bisheng/telemetry_search/domain/models/dashboard.py)，类起始行 69 |
| `dashboard_component` | 无 | P | [DashboardComponent](../../src/backend/bisheng/telemetry_search/domain/models/dashboard.py)，类起始行 84 |
| `dashboard_default` | 无 | U | [DashboardDefault](../../src/backend/bisheng/telemetry_search/domain/models/dashboard.py)，类起始行 45 |
| `dashboard_dataset` | 无 | G | [DashboardDataset](../../src/backend/bisheng/telemetry_search/domain/models/dashboard_dataset.py)，类起始行 74 |

## tool（2）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `t_gpts_tools` | 有 | T | [GptsTools](../../src/backend/bisheng/tool/domain/models/gpts_tools.py)，类起始行 92 |
| `t_gpts_tools_type` | 有 | T | [GptsToolsType](../../src/backend/bisheng/tool/domain/models/gpts_tools.py)，类起始行 104 |

## user（1）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `user` | 无 | I | [User](../../src/backend/bisheng/user/domain/models/user.py)，类起始行 84 |

## workstation（1）

| 表 | tenant_id 字段 | 分类 | 模型源码 |
| --- | --- | --- | --- |
| `tenant_workstation_config` | 有 | T | [TenantWorkstationConfig](../../src/backend/bisheng/workstation/domain/models/tenant_workstation_config.py)，类起始行 60 |
