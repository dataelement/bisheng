"""Every /api/v1 route must carry a login-enforcing dependency.

GHSA-p2wv-9g25-xrqr showed that CustomMiddleware authenticates only when a
token is present, so a handler without its own login dependency is fully
anonymous. This guard freezes the routes that lack one today (shrink-only:
delete an entry when the route gains auth) so no new anonymous route can land
silently.

The frozen set is debt, not an approval: some entries authenticate through
other mechanisms (service accounts, share tokens, HMAC callbacks), others are
intentionally public (login/regist/captcha). Each entry still needs review
before it is trusted.

Auth wrappers recognized here: get_login_user and the helpers that call it
internally (get_admin_user, get_tenant_admin_user, get_model_admin_user,
get_app_creator_user).
"""

from fastapi.routing import APIRoute

from bisheng.main import app

AUTH_DEPENDENCIES = frozenset(
    {"get_login_user", "get_admin_user", "get_tenant_admin_user", "get_model_admin_user", "get_app_creator_user"}
)


def _dependency_names(dependant) -> set[str]:
    names, stack = set(), [dependant]
    while stack:
        node = stack.pop()
        call = getattr(node, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", type(call).__name__))
        stack.extend(getattr(node, "dependencies", []) or [])
    return names


def _routes_without_login() -> set[str]:
    routes = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        if _dependency_names(route.dependant) & AUTH_DEPENDENCIES:
            continue
        routes.update(f"{method} {route.path}" for method in route.methods)
    return routes


LEGACY_ROUTES_WITHOUT_LOGIN_DEPENDENCY = frozenset(
    """
DELETE /api/v1/apps/{app_id}/storage/objects/{key:path}
DELETE /api/v1/dsh/market/admin/plugins/{plugin_id}
DELETE /api/v1/service-accounts/{service_account_id}
DELETE /api/v1/tenants/{tenant_id}/users/{user_id}
GET /api/v1/all
GET /api/v1/apps/_unavailable
GET /api/v1/apps/{app_id}/storage/meta/{key:path}
GET /api/v1/apps/{app_id}/storage/objects
GET /api/v1/apps/{app_id}/storage/objects/{key:path}
GET /api/v1/brand/runtime-config
GET /api/v1/chat/info
GET /api/v1/citations/{citation_id}
GET /api/v1/dsh/apps
GET /api/v1/dsh/apps/deploy-limits
GET /api/v1/dsh/apps/{app_id}/deployments/{deployment_id}
GET /api/v1/dsh/apps/{app_id}/versions/{version_id}/source
GET /api/v1/dsh/browser-config
GET /api/v1/dsh/config
GET /api/v1/dsh/market/admin/context
GET /api/v1/dsh/market/admin/devices
GET /api/v1/dsh/market/admin/imports
GET /api/v1/dsh/market/admin/install-policy
GET /api/v1/dsh/market/admin/plugins
GET /api/v1/dsh/market/admin/plugins/{plugin_id}
GET /api/v1/dsh/market/admin/workbenches
GET /api/v1/dsh/market/admin/workbenches/imports
GET /api/v1/dsh/market/capabilities
GET /api/v1/dsh/market/catalog
GET /api/v1/dsh/market/plugins/{plugin_id}/versions/{version_id}/artifact
GET /api/v1/dsh/market/workbenches
GET /api/v1/dsh/market/workbenches/{workbench_id}
GET /api/v1/dsh/market/workbenches/{workbench_id}/versions/{version_id}/artifact
GET /api/v1/dsh/models
GET /api/v1/dsh/profile
GET /api/v1/dsh/usage
GET /api/v1/env
GET /api/v1/internal/app-runtime/v2/admission/plans/{resource_ref}
GET /api/v1/internal/app-runtime/v2/apps/{app_id}/execution
GET /api/v1/internal/app-runtime/v2/data-public-keys
GET /api/v1/internal/app-runtime/v2/egress-policies
GET /api/v1/internal/app-runtime/v2/host-isolation
GET /api/v1/internal/app-runtime/v2/nodes/plan
GET /api/v1/internal/app-runtime/v2/operations/{operation_id}
GET /api/v1/internal/app-runtime/v2/resources
GET /api/v1/internal/app-runtime/v2/resources/{resource_ref}
GET /api/v1/internal/app-runtime/v2/routes/apps/{app_id}
GET /api/v1/internal/app-runtime/v2/routes/previews/{session_id}
GET /api/v1/internal/app-runtime/v2/transfers/{transfer_id}
GET /api/v1/internal/app-runtime/v2/transfers/{transfer_id}/content
GET /api/v1/knowledge/qa/export/template
GET /api/v1/mark/get_record
GET /api/v1/mark/get_user
GET /api/v1/open-api/skill-packs/{pack_name}
GET /api/v1/personal-tokens
GET /api/v1/personal-tokens/settings
GET /api/v1/qa/keyword
GET /api/v1/service-accounts
GET /api/v1/service-accounts/management-scope
GET /api/v1/service-accounts/owner-candidates
GET /api/v1/service-accounts/scopes
GET /api/v1/service-accounts/{service_account_id}
GET /api/v1/service-accounts/{service_account_id}/grantable-resources
GET /api/v1/service-accounts/{service_account_id}/keys
GET /api/v1/service-accounts/{service_account_id}/keys/page
GET /api/v1/service-accounts/{service_account_id}/resource-grants
GET /api/v1/share-link/{share_token}
GET /api/v1/telemetry/dashboard/dataset/field/enums
GET /api/v1/telemetry/dashboard/dataset/list
GET /api/v1/tool/linsight/preset
GET /api/v1/user/get_captcha
GET /api/v1/user/public_key
GET /api/v1/version
GET /api/v1/web/config
PATCH /api/v1/dsh/market/admin/install-policy
PATCH /api/v1/service-accounts/{service_account_id}
PATCH /api/v1/service-accounts/{service_account_id}/keys/{key_id}
POST /api/v1/chat/comment
POST /api/v1/chat/copied
POST /api/v1/citations/resolve
POST /api/v1/departments/sync
POST /api/v1/dsh/apps/deploy
POST /api/v1/dsh/apps/{app_id}/launch
POST /api/v1/dsh/audit/conversations/title
POST /api/v1/dsh/audit/message-feedback
POST /api/v1/dsh/authorizations
POST /api/v1/dsh/chat/completions
POST /api/v1/dsh/logout
POST /api/v1/dsh/market/admin/imports
POST /api/v1/dsh/market/admin/imports/preview
POST /api/v1/dsh/market/admin/imports/{task_id}/resume
POST /api/v1/dsh/market/admin/plugins/{plugin_id}/transition
POST /api/v1/dsh/market/admin/workbenches/imports
POST /api/v1/dsh/market/admin/workbenches/imports/preview
POST /api/v1/dsh/market/admin/workbenches/imports/{task_id}/resume
POST /api/v1/dsh/market/sync
POST /api/v1/dsh/responses
POST /api/v1/dsh/token
POST /api/v1/dsh/tools/{toolCode}/invoke
POST /api/v1/dsh/web-session
POST /api/v1/internal/app-proxy/authorize
POST /api/v1/internal/app-proxy/authorize-preview
POST /api/v1/internal/app-proxy/desktop-session
POST /api/v1/internal/app-runtime/host-isolation-reports
POST /api/v1/internal/app-runtime/v2/controllers/claim
POST /api/v1/internal/app-runtime/v2/controllers/renew
POST /api/v1/internal/app-runtime/v2/dependency-plans
POST /api/v1/internal/app-runtime/v2/downloads
POST /api/v1/internal/app-runtime/v2/egress-bindings
POST /api/v1/internal/app-runtime/v2/material-delegations
POST /api/v1/internal/app-runtime/v2/material-delegations/{delegation_id}/bind
POST /api/v1/internal/app-runtime/v2/nodes/heartbeat
POST /api/v1/internal/app-runtime/v2/nonces
POST /api/v1/internal/app-runtime/v2/observations
POST /api/v1/internal/app-runtime/v2/operations/{operation_id}/authorize-step
POST /api/v1/internal/app-runtime/v2/operations/{operation_id}/claim
POST /api/v1/internal/app-runtime/v2/operations/{operation_id}/facts
POST /api/v1/internal/app-runtime/v2/resources
POST /api/v1/internal/app-runtime/v2/resources/{resource_ref}/observations
POST /api/v1/internal/app-runtime/v2/transfers
POST /api/v1/internal/app-runtime/v2/transfers/{transfer_id}/finalize
POST /api/v1/internal/departments/relink
POST /api/v1/internal/departments/relink/resolve-conflict
POST /api/v1/internal/dsh/content-safety-events
POST /api/v1/internal/sso/gateway-wecom-org-sync
POST /api/v1/internal/sso/login-sync
POST /api/v1/knowledge/upload
POST /api/v1/liked
POST /api/v1/personal-tokens/holders/{user_id}/revoke
POST /api/v1/personal-tokens/{credential_id}/revoke
POST /api/v1/qa/chunk
POST /api/v1/report/callback
POST /api/v1/service-accounts
POST /api/v1/service-accounts/{service_account_id}/delegate-candidates:filter
POST /api/v1/service-accounts/{service_account_id}/disable
POST /api/v1/service-accounts/{service_account_id}/enable
POST /api/v1/service-accounts/{service_account_id}/keys
POST /api/v1/service-accounts/{service_account_id}/keys/revoke-all
POST /api/v1/service-accounts/{service_account_id}/keys/{key_id}/revoke
POST /api/v1/service-accounts/{service_account_id}/resource-grants:mutate
POST /api/v1/tenants/
POST /api/v1/tenants/{tenant_id}/users
POST /api/v1/upload/{flow_id}
POST /api/v1/user/change_password_public
POST /api/v1/user/login
POST /api/v1/user/logout
POST /api/v1/user/regist
POST /api/v1/user/sso
POST /api/v1/user/switch-tenant
POST /api/v1/workflow/report/callback
PUT /api/v1/apps/{app_id}/storage/objects/{key:path}
PUT /api/v1/internal/app-runtime/v2/transfers/{transfer_id}/content
PUT /api/v1/personal-tokens/settings
PUT /api/v1/service-accounts/management-scope
""".strip().splitlines()
)


def test_no_new_route_without_login_dependency():
    new_routes = _routes_without_login() - LEGACY_ROUTES_WITHOUT_LOGIN_DEPENDENCY
    assert new_routes == set(), (
        "New /api/v1 routes must declare Depends(UserPayload.get_login_user) "
        f"(or an admin wrapper). Missing auth: {sorted(new_routes)}"
    )


def test_reported_report_temp_route_is_authenticated():
    assert "GET /api/v1/report/report_temp" not in _routes_without_login()
