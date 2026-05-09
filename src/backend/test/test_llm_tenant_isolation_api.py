"""LLM router dependency contract.

All LLM management endpoints — Tenant-scoped CRUD and system-level
config — are gated by ``UserPayload.get_tenant_admin_user`` so global
super admins **and** Child Admins on their own tenant can both pass.

History:
- F020 T08 originally chose ``get_tenant_admin_user`` for the CRUD set.
- A later commit (``Align model management with role menu permissions``)
  swapped the gate to ``get_model_admin_user`` (admin or any non-admin
  holding the ``model`` web_menu entry). That broke Child Admins —
  the backend strips ``model`` from their web_menu, so the page guard
  redirected them to /403 even though PRD §6.1 allows them to manage
  models within their own tenant.
- The current revision restores ``get_tenant_admin_user`` everywhere,
  matching the v2.5.1 LLM multi-tenant decisions (admin-scope switch,
  Root-shared toggle, Child Admin autonomy, legacy data → Root) and the
  technical spec §11.1 ruling.

The cross-tenant write guard for system config remains in the router
helper ``_assert_can_write_system_config`` and is covered by
``test_llm_system_config_router_authz.py``.
"""

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.llm.api.router import router


def _endpoint_deps(path: str, method: str) -> list[str]:
    """Return the names of Depends() callables bound to the given
    (path, method) in the LLM router."""
    for r in router.routes:
        if getattr(r, 'path', None) == path and method in getattr(r, 'methods', set()):
            names = []
            for dep in r.dependant.dependencies:
                fn = dep.call
                # classmethods attach to a class via __func__
                fn = getattr(fn, '__func__', fn)
                names.append(fn.__name__)
            return names
    raise AssertionError(f'no route matched {method} {path}')


# --- Tenant-scoped CRUD: must admit Child Admins ---------------------------


def test_post_llm_uses_tenant_admin_dep():
    """AC-05 / AC-06: Child Admin may register their own tenant's LLM server."""
    deps = _endpoint_deps('/llm', 'POST')
    assert 'get_tenant_admin_user' in deps
    assert 'get_admin_user' not in deps
    assert 'get_model_admin_user' not in deps


def test_put_llm_uses_tenant_admin_dep():
    """AC-06 / AC-08 (gate): update allowed for Child Admin; DAO layer
    further refuses writes on Root-owned rows."""
    deps = _endpoint_deps('/llm', 'PUT')
    assert 'get_tenant_admin_user' in deps
    assert 'get_model_admin_user' not in deps


def test_delete_llm_uses_tenant_admin_dep():
    """AC-07 / AC-09 (gate): delete allowed for Child Admin; DAO layer
    refuses Root-owned deletes for non-super."""
    deps = _endpoint_deps('/llm', 'DELETE')
    assert 'get_tenant_admin_user' in deps
    assert 'get_model_admin_user' not in deps


def test_get_info_and_online_endpoints_use_tenant_admin_dep():
    """Detail read + online toggle follow the same Child-Admin gate."""
    assert 'get_tenant_admin_user' in _endpoint_deps('/llm/info', 'GET')
    assert 'get_tenant_admin_user' in _endpoint_deps('/llm/online', 'POST')
    assert 'get_model_admin_user' not in _endpoint_deps('/llm/info', 'GET')
    assert 'get_model_admin_user' not in _endpoint_deps('/llm/online', 'POST')


# --- System-level config: same gate, plus _assert_can_write_system_config ---
# Child Admin is allowed to write their own tenant's row (admin-scope or
# direct ``tenant#admin`` grant). The cross-tenant write guard lives in
# the router helper ``_assert_can_write_system_config`` and is covered
# by ``test_llm_system_config_router_authz.py``.


def test_workbench_endpoint_uses_tenant_admin_dep():
    deps = _endpoint_deps('/llm/workbench', 'POST')
    assert 'get_tenant_admin_user' in deps
    assert 'get_model_admin_user' not in deps


def test_knowledge_config_endpoint_uses_tenant_admin_dep():
    deps = _endpoint_deps('/llm/knowledge', 'POST')
    assert 'get_tenant_admin_user' in deps
    assert 'get_model_admin_user' not in deps


def test_assistant_config_endpoint_uses_tenant_admin_dep():
    deps = _endpoint_deps('/llm/assistant', 'POST')
    assert 'get_tenant_admin_user' in deps
    assert 'get_model_admin_user' not in deps


def test_evaluation_config_endpoint_uses_tenant_admin_dep():
    deps = _endpoint_deps('/llm/evaluation', 'POST')
    assert 'get_tenant_admin_user' in deps
    assert 'get_model_admin_user' not in deps


def test_workflow_config_endpoint_uses_tenant_admin_dep():
    deps = _endpoint_deps('/llm/workflow', 'POST')
    assert 'get_tenant_admin_user' in deps
    assert 'get_model_admin_user' not in deps


# --- Sanity: tenant_admin dep is a UserPayload classmethod ------------------


def test_tenant_admin_dep_is_callable_classmethod():
    """``get_tenant_admin_user`` is declared on ``UserPayload`` directly
    so FastAPI's ``Depends(...)`` resolves it correctly."""
    fn = UserPayload.__dict__.get('get_tenant_admin_user')
    assert fn is not None, 'get_tenant_admin_user must be declared on UserPayload'
    assert isinstance(fn, classmethod)
