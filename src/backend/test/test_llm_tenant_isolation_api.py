"""F020 T08 Router dependency downgrade smoke tests.

Static checks that ``get_admin_user`` was replaced with
``get_tenant_admin_user`` on the Tenant-scoped CRUD endpoints. System-
level config endpoints (workbench / knowledge / assistant / evaluation
/ workflow) used to require ``get_admin_user`` (super-only) per F020
AC-11 / D9, but **F022 revises that decision**: each Child gets its
own row, so ``get_model_admin_user`` is the right gate (admin or
Child Admin with the model menu). The cross-tenant write guard moved
to a defense-in-depth check inside the router (see F022 spec §6.3).
"""

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.llm.api.router import router


def _endpoint_deps(path: str, method: str) -> list[str]:
    """Return the names of Depends() callables bound to the given
    (path, method) in the LLM router. Used to assert that the CRUD
    endpoints hit ``get_tenant_admin_user`` and the system-level ones
    stay on ``get_admin_user``."""
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
# F020 T08 originally landed on ``get_tenant_admin_user``; the later
# commit ``Align model management with role menu permissions`` widened
# this to ``get_model_admin_user`` (admin or Child Admin holding the
# ``model`` menu permission). The Child-Admin admission contract still
# holds — both deps reject anonymous / non-admin callers — but the
# explicit name has shifted.


def test_post_llm_uses_model_admin_dep():
    """AC-05 / AC-06: Child Admin may register their own tenant's LLM server."""
    deps = _endpoint_deps('/llm', 'POST')
    assert 'get_model_admin_user' in deps
    assert 'get_admin_user' not in deps


def test_put_llm_uses_model_admin_dep():
    """AC-06 / AC-08 (gate): update allowed for Child Admin; DAO layer
    further refuses writes on Root-owned rows."""
    deps = _endpoint_deps('/llm', 'PUT')
    assert 'get_model_admin_user' in deps


def test_delete_llm_uses_model_admin_dep():
    """AC-07 / AC-09 (gate): delete allowed for Child Admin; DAO layer
    refuses Root-owned deletes for non-super."""
    deps = _endpoint_deps('/llm', 'DELETE')
    assert 'get_model_admin_user' in deps


def test_get_info_and_online_endpoints_use_model_admin_dep():
    """Detail read + online toggle follow the same Child-Admin gate."""
    assert 'get_model_admin_user' in _endpoint_deps('/llm/info', 'GET')
    assert 'get_model_admin_user' in _endpoint_deps('/llm/online', 'POST')


# --- System-level config: F022 revises F020 AC-11 ---------------------------
# Child Admin is now allowed to write their own tenant's row (admin-scope or
# direct ``tenant#admin`` grant). The cross-tenant write guard lives in the
# router helper ``_assert_can_write_system_config`` and is covered by
# ``test_llm_system_config_router_authz.py``.


def test_workbench_endpoint_uses_model_admin_dep():
    deps = _endpoint_deps('/llm/workbench', 'POST')
    assert 'get_model_admin_user' in deps
    assert 'get_tenant_admin_user' not in deps


def test_knowledge_config_endpoint_uses_model_admin_dep():
    deps = _endpoint_deps('/llm/knowledge', 'POST')
    assert 'get_model_admin_user' in deps
    assert 'get_tenant_admin_user' not in deps


def test_assistant_config_endpoint_uses_model_admin_dep():
    deps = _endpoint_deps('/llm/assistant', 'POST')
    assert 'get_model_admin_user' in deps
    assert 'get_tenant_admin_user' not in deps


def test_evaluation_config_endpoint_uses_model_admin_dep():
    deps = _endpoint_deps('/llm/evaluation', 'POST')
    assert 'get_model_admin_user' in deps


def test_workflow_config_endpoint_uses_model_admin_dep():
    deps = _endpoint_deps('/llm/workflow', 'POST')
    assert 'get_model_admin_user' in deps


# --- Sanity: both admin deps are UserPayload classmethods ------------------


def test_admin_deps_are_callable_classmethods():
    """``get_tenant_admin_user`` is declared on ``UserPayload``;
    ``get_model_admin_user`` is inherited from ``LoginUser``. Both
    must resolve to a callable classmethod via attribute lookup so
    FastAPI's ``Depends(...)`` can use them as dependencies."""
    fn = UserPayload.__dict__.get('get_tenant_admin_user')
    assert fn is not None, 'get_tenant_admin_user must be declared on UserPayload'
    assert isinstance(fn, classmethod)
    # Inherited from LoginUser — only assert it resolves to something callable.
    assert callable(getattr(UserPayload, 'get_model_admin_user', None))
