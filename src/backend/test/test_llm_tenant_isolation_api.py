"""F020 T08 Router dependency downgrade smoke tests.

Static checks that ``get_admin_user`` was replaced with
``get_tenant_admin_user`` on the Tenant-scoped CRUD endpoints while
system-level config endpoints (workbench / knowledge / assistant /
evaluation) kept ``get_admin_user`` per AC-11 / D9.

A full TestClient-backed integration pass requires mocking 4+ Service
collaborators (model factories, background tasks, LLMDao, etc.) so end-
to-end behaviour is deferred to the 114 pytest run in T16. The checks
here catch the most likely regression — accidental dependency rollback —
by inspecting the FastAPI route table.
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


# --- Tenant-scoped CRUD: must now admit Child Admins -----------------------


def test_post_llm_uses_tenant_admin_dep():
    """AC-05 / AC-06: Child Admin may register their own tenant's LLM server."""
    deps = _endpoint_deps('/llm', 'POST')
    assert 'get_tenant_admin_user' in deps
    assert 'get_admin_user' not in deps


def test_put_llm_uses_tenant_admin_dep():
    """AC-06 / AC-08 (gate): update allowed for Child Admin; DAO layer
    further refuses writes on Root-owned rows."""
    deps = _endpoint_deps('/llm', 'PUT')
    assert 'get_tenant_admin_user' in deps


def test_delete_llm_uses_tenant_admin_dep():
    """AC-07 / AC-09 (gate): delete allowed for Child Admin; DAO layer
    refuses Root-owned deletes for non-super."""
    deps = _endpoint_deps('/llm', 'DELETE')
    assert 'get_tenant_admin_user' in deps


def test_get_info_and_online_endpoints_use_tenant_admin_dep():
    """Detail read + online toggle follow the same Child-Admin gate."""
    assert 'get_tenant_admin_user' in _endpoint_deps('/llm/info', 'GET')
    assert 'get_tenant_admin_user' in _endpoint_deps('/llm/online', 'POST')


# --- System-level config: must stay super-admin only (AC-11 / D9) ----------


def test_workbench_endpoint_stays_super_admin_only():
    deps = _endpoint_deps('/llm/workbench', 'POST')
    assert 'get_admin_user' in deps
    assert 'get_tenant_admin_user' not in deps


def test_knowledge_config_endpoint_stays_super_admin_only():
    deps = _endpoint_deps('/llm/knowledge', 'POST')
    assert 'get_admin_user' in deps
    assert 'get_tenant_admin_user' not in deps


def test_assistant_config_endpoint_stays_super_admin_only():
    deps = _endpoint_deps('/llm/assistant', 'POST')
    assert 'get_admin_user' in deps
    assert 'get_tenant_admin_user' not in deps


# --- Sanity: get_tenant_admin_user is actually a UserPayload classmethod ---


def test_get_tenant_admin_user_is_a_userpayload_classmethod():
    fn = UserPayload.__dict__.get('get_tenant_admin_user')
    assert fn is not None, 'T03 dependency must be declared on UserPayload'
    assert isinstance(fn, classmethod)
