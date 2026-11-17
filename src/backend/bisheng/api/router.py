# Router for base api
from fastapi import Depends

from bisheng.admin.api.router import router as admin_router
from bisheng.api.v1 import (
    assistant_router,
    audit_router,
    chat_router,
    endpoints_router,
    flows_router,
    group_router,
    invite_code_router,
    mark_router,
    report_router,
    skillcenter_router,
    tag_router,
    tool_router,
    user_router,
    variable_router,
    workflow_router,
    workstation_router,
)
from bisheng.api.v1.storage import router as storage_router
from bisheng.app_governance.api.router import router as runtime_audit_router
from bisheng.app_publish.api.router import v1_router as app_publish_v1_router
from bisheng.app_publish.api.router import v2_router as app_publish_v2_router
from bisheng.app_runtime.api.router import router as app_runtime_router
from bisheng.approval.api.router import router as approval_router
from bisheng.brand.api.router import router as brand_router
from bisheng.channel.api.router import router as channel_router
from bisheng.chat_session.api.router import router as session_router
from bisheng.citation.api.router import router as citation_router
from bisheng.commercial_license.api.router import router as commercial_license_router
from bisheng.common.request_scope import (
    RequestScope as S,
)
from bisheng.common.request_scope import (
    ScopedAPIRouter as APIRouter,
)
from bisheng.common.request_scope import (
    scope_overrides,
    scope_query_variant,
)
from bisheng.common.services.config_service import settings
from bisheng.department.api.endpoints.department_flow import router as department_flow_router
from bisheng.department.api.router import router as department_router
from bisheng.dev_toolkit.api.router import router as dev_toolkit_router
from bisheng.dsh.api.router import router as dsh_router
from bisheng.dsh_market.api.router import router as dsh_market_router
from bisheng.evaluation.api.router import router as evaluation_router
from bisheng.finetune.api.finetune import router as finetune_router
from bisheng.finetune.api.server import router as server_router
from bisheng.knowledge.api.router import (
    knowledge_router,
    knowledge_space_router,
    knowledge_space_tag_library_router,
    knowledge_version_router,
    qa_router,
)
from bisheng.linsight.api.router import router as linsight_router
from bisheng.llm.api.router import router as llm_router
from bisheng.memory.api.router import router as memory_router
from bisheng.message.api.router import router as message_router
from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.router import management_router as open_api_management_router
from bisheng.open_api.api.router import model_gateway_router
from bisheng.open_api.api.router import rpc_router as open_api_rpc_router
from bisheng.open_endpoints.api.endpoints.llm import router as llm_router_rpc
from bisheng.open_endpoints.api.router import (
    assistant_router_rpc,
    chat_router_rpc,
    citation_router_rpc,
    filelib_router_rpc,
    flow_router_rpc,
    knowledge_router_rpc,
    workflow_router_rpc,
    workstation_router_rpc,
)
from bisheng.org_sync.api.endpoints.relink import router as relink_router
from bisheng.org_sync.api.router import router as org_sync_router
from bisheng.permission.api.router import router as permission_router
from bisheng.public_endpoints.api.endpoints.guest_link import router as guest_link_router
from bisheng.role.api.router import router as role_router
from bisheng.sensitive_word.api.router import router as sensitive_word_policy_router
from bisheng.share_link.api.router import router as share_link_router
from bisheng.sso_sync.api.router import router as sso_sync_router
from bisheng.telemetry_search.api.router import router as telemetry_search_router
from bisheng.tenant.api.router import router as tenant_router
from bisheng.user_group.api.router import router as user_group_router
from bisheng.workstation.api.endpoints.conversation_export import router as conversation_export_router

# Mixed routers declare semantic exceptions once, by their actual endpoints.
scope_query_variant(
    app_publish_v1_router,
    {"get_preview", "start_preview", "reclaim_preview"},
    query="purpose",
    value="approval",
    kind=S.IDENTITY,
)
scope_overrides(session_router, S.IDENTITY, "add_chat_messages", "update_chat_message")
scope_overrides(knowledge_router, S.IDENTITY, "upload_file")
scope_overrides(department_router, S.IDENTITY, "get_user_primary_department")
scope_overrides(user_router, S.IDENTITY, "get_admins")
scope_overrides(
    user_router, S.PUBLIC, "regist", "sso", "login", "get_captcha", "get_rsa_publish_key", "change_password_public"
)
scope_overrides(
    user_router,
    S.IDENTITY,
    "get_info",
    "logout",
    "change_password",
    "upload_avatar",
    "update_my_nickname",
    "get_current_tenant",
    "has_mark_access",
)
scope_overrides(
    endpoints_router, S.PUBLIC, "get_env", "get_web_config", "get_version", "get_all_langchain_types_legacy"
)
scope_overrides(endpoints_router, S.PLATFORM, "get_config", "save_config", "update_web_config")
scope_overrides(brand_router, S.PUBLIC, "get_brand_runtime_config")
scope_overrides(share_link_router, S.CREDENTIAL, "get_share_link_info")

router = APIRouter(
    prefix="/api/v1",
)
router.include_router(dsh_market_router, request_scope=S.CREDENTIAL)
router.include_router(dsh_router, request_scope=S.CREDENTIAL)
router.include_router(chat_router, request_scope=S.TENANT)
router.include_router(endpoints_router, request_scope=S.TENANT)
router.include_router(knowledge_router, request_scope=S.TENANT)
router.include_router(knowledge_space_tag_library_router, request_scope=S.TENANT)
router.include_router(knowledge_space_router, request_scope=S.TENANT)
router.include_router(knowledge_version_router, request_scope=S.TENANT)
router.include_router(server_router, request_scope=S.TENANT)
router.include_router(user_router, request_scope=S.TENANT)
router.include_router(qa_router, request_scope=S.TENANT)
router.include_router(variable_router, request_scope=S.TENANT)
router.include_router(report_router, request_scope=S.TENANT)
router.include_router(finetune_router, request_scope=S.TENANT)
router.include_router(assistant_router, request_scope=S.TENANT)
router.include_router(group_router, request_scope=S.TENANT)
router.include_router(audit_router, request_scope=S.TENANT)
router.include_router(evaluation_router, request_scope=S.TENANT)
router.include_router(tag_router, request_scope=S.TENANT)
router.include_router(llm_router, request_scope=S.TENANT)
router.include_router(workflow_router, request_scope=S.TENANT)
router.include_router(mark_router, request_scope=S.TENANT)
router.include_router(workstation_router, request_scope=S.TENANT)
router.include_router(conversation_export_router, request_scope=S.TENANT)
router.include_router(skillcenter_router, request_scope=S.TENANT)
router.include_router(flows_router, request_scope=S.TENANT)
router.include_router(linsight_router, request_scope=S.TENANT)
router.include_router(tool_router, request_scope=S.TENANT)
router.include_router(invite_code_router, request_scope=S.TENANT)
router.include_router(session_router, request_scope=S.PERSONAL)
router.include_router(share_link_router, request_scope=S.TENANT)
router.include_router(telemetry_search_router, request_scope=S.TENANT)
router.include_router(channel_router, request_scope=S.TENANT)
router.include_router(message_router, request_scope=S.PERSONAL)
router.include_router(department_router, request_scope=S.TENANT)
# Department concurrent-session page leases (docs/部门流量控制方案.md). Its own
# prefix is deliberately NOT mounted under ``department/api/router.py`` — that
# router carries ``/departments``, and the client calls
# ``/api/v1/department-flow/presence/*``.
router.include_router(department_flow_router, request_scope=S.TENANT)
router.include_router(user_group_router, request_scope=S.TENANT)
router.include_router(permission_router, request_scope=S.TENANT)
router.include_router(guest_link_router, request_scope=S.TENANT)
router.include_router(role_router, request_scope=S.TENANT)
router.include_router(org_sync_router, request_scope=S.PLATFORM)
router.include_router(sso_sync_router, request_scope=S.CREDENTIAL)
router.include_router(relink_router, request_scope=S.PLATFORM)
router.include_router(tenant_router, request_scope=S.PLATFORM)
router.include_router(citation_router, request_scope=S.TENANT)
router.include_router(memory_router, request_scope=S.TENANT)
router.include_router(commercial_license_router, request_scope=S.PLATFORM)
router.include_router(admin_router, request_scope=S.IDENTITY)
router.include_router(approval_router, request_scope=S.PERSONAL)
router.include_router(brand_router, request_scope=S.PLATFORM)
router.include_router(sensitive_word_policy_router, request_scope=S.TENANT)
router.include_router(storage_router, request_scope=S.PUBLIC)
# Open API management face (features/v3.0.0-beta1/053): service accounts,
# personal tokens, scope catalogue and skill-pack distribution — session auth,
# tenant-admin gated inside the endpoints.
router.include_router(open_api_management_router, request_scope=S.TENANT)
# F054: hosted application state actions, read side and the app-proxy hook.
router.include_router(app_runtime_router, request_scope=S.TENANT)
router.include_router(runtime_audit_router, request_scope=S.TENANT)
# F055: publish status + manual publish for the publish face (session auth).
router.include_router(app_publish_v1_router, request_scope=S.TENANT)
# F053 (features/v3.0.0/053, design D10): CLI installer download + version
# truth, both anonymous.
# The include is **conditional on purpose** — do not "tidy" it into an
# unconditional one. AC-05 asks that these endpoints appear not to exist where
# the open-capability layer is not deployed, and not registering the router is
# how that lands: FastAPI's own 404, no new error code (CON-8), and no way for
# an unauthenticated caller to tell "there is a feature here, it is off" from
# "there is nothing here". ``open_platform.enabled`` is a process-level YAML
# key, so flipping it needs a restart — the existing semantics of that config.
if settings.open_platform.enabled:
    router.include_router(dev_toolkit_router, request_scope=S.PUBLIC)

# /api/v2 carries ONE router-level dependency. ``verify_open_api_access``
# authenticates the bearer, then reads the ``@open_api_scope`` marker off the
# matched endpoint to enforce scope and identity mode; an endpoint without a
# marker fails closed (OpenApiEndpointUnregisteredError). Every sub-router
# included below therefore marks each endpoint and never resolves identity on
# its own — it reads ``get_current_open_api_principal()`` instead.
router_rpc = APIRouter(prefix="/api/v2", dependencies=[Depends(verify_open_api_access)])
router_rpc.include_router(open_api_rpc_router, request_scope=S.CREDENTIAL)
router_rpc.include_router(knowledge_router_rpc, request_scope=S.CREDENTIAL)
router_rpc.include_router(filelib_router_rpc, request_scope=S.CREDENTIAL)
router_rpc.include_router(assistant_router_rpc, request_scope=S.CREDENTIAL)
router_rpc.include_router(workflow_router_rpc, request_scope=S.CREDENTIAL)
router_rpc.include_router(llm_router_rpc, request_scope=S.CREDENTIAL)
router_rpc.include_router(flow_router_rpc, request_scope=S.CREDENTIAL)
router_rpc.include_router(citation_router_rpc, request_scope=S.CREDENTIAL)
router_rpc.include_router(workstation_router_rpc, request_scope=S.CREDENTIAL)
router_rpc.include_router(chat_router_rpc, request_scope=S.CREDENTIAL)
# F055: /api/v2/apps/** — what `bisheng deploy` / `bisheng logs` talk to. Same
# contract as every other v2 sub-router: the credential dependency is inherited
# from router_rpc, each endpoint carries @open_api_scope("app:manage") and reads
# the principal from get_current_open_api_principal().
router_rpc.include_router(app_publish_v2_router, request_scope=S.CREDENTIAL)
# F051: /api/v2/model/v1/** — the OpenAI-compatible model protocol face. The
# **only** conditionally mounted v2 sub-router: AC-28 asks that the face be
# indistinguishable from "no such endpoint" where the open capability layer is
# not deployed, and a 403 for a missing scope cannot deliver that. `app:manage`
# above is mounted unconditionally and closed by making its scope unissuable
# instead — do not "tidy" these two into the same shape.
if settings.open_platform.enabled:
    router_rpc.include_router(model_gateway_router, request_scope=S.CREDENTIAL)
