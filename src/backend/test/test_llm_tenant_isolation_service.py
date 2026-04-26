"""F020 T07 LLMService behavioural tests.

Focuses on the two new Service-layer surfaces that carry the Tenant
visibility logic:

- ``LLMService.get_all_llm`` merging leaf-tenant rows with Root-shared
  rows under different caller profiles (AC-03 / AC-13 / AC-14 / AC-15).
- ``LLMService.get_model_for_call`` raising 19802 when the target is
  not reachable and succeeding on Root-shared models for Child callers
  (AC-20 / AC-22 / AC-23).

The full ``add_llm_server`` / ``update_llm_server`` flows are exercised
by T08 API-layer integration tests; unit-testing them here would require
mocking ~7 collaborators (Redis, LangChain model factories, the
post-insert hook that calls get_workbench_llm, etc.) for little marginal
signal.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.llm.domain.services.llm import LLMService


DAO = 'bisheng.llm.domain.services.llm.LLMDao'
CONTEXT = 'bisheng.llm.domain.services.llm'
SUPER_CHECK = 'bisheng.llm.domain.services.llm._check_is_global_super'


def _mk_operator(user_id: int = 1):
    """Lightweight UserPayload stand-in carrying just ``user_id``."""
    op = MagicMock()
    op.user_id = user_id
    return op


@pytest.fixture(autouse=True)
def _mock_tenant_dao():
    """LLMService now resolves the Root tenant name via ``TenantDao``;
    stub it so unit tests don't need a real DB engine. Tests that care
    about the resolved name explicitly re-patch within their own
    ``with`` block — those overrides win because they sit inside this
    fixture's scope."""
    with patch(
        'bisheng.database.models.tenant.TenantDao.aget_by_id',
        new=AsyncMock(return_value=None),
    ):
        yield


def _mk_server(sid: int, tenant_id: int, name: str = ''):
    s = MagicMock()
    s.id = sid
    s.tenant_id = tenant_id
    s.name = name or f's{sid}'
    # model_dump needs to exclude config; the Service uses .model_dump(exclude={'config'})
    # → produce a plain dict return so LLMServerInfo(**dump) constructs cleanly.
    s.model_dump = MagicMock(return_value={
        'id': sid, 'tenant_id': tenant_id, 'name': name or f's{sid}',
        'description': '', 'type': 'openai', 'limit_flag': False, 'limit': 0,
        'user_id': 1,
    })
    return s


# --- get_all_llm merge --------------------------------------------------


@pytest.mark.asyncio
async def test_child_user_llm_list_merges_root_shared():
    """AC-03: Child (leaf=5) sees own servers + Root-shared ones flagged readonly."""
    own = _mk_server(10, tenant_id=5, name='own')
    shared = _mk_server(100, tenant_id=1, name='root-shared')

    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(SUPER_CHECK, new=AsyncMock(return_value=False)), \
            patch(f'{DAO}.aget_all_server', new=AsyncMock(return_value=[own])), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[100])), \
            patch(f'{DAO}.aget_server_by_ids',
                  new=AsyncMock(return_value=[shared])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])):
        result = await LLMService.get_all_llm(operator=_mk_operator())

    ids = [r.id for r in result]
    assert 10 in ids and 100 in ids
    shared_row = [r for r in result if r.id == 100][0]
    own_row = [r for r in result if r.id == 10][0]
    assert shared_row.is_root_shared_readonly is True
    assert own_row.is_root_shared_readonly is False


@pytest.mark.asyncio
async def test_super_admin_without_scope_sees_all_root():
    """AC-15: leaf=1 (super admin without scope) → Root rows writable."""
    root1 = _mk_server(1, tenant_id=1, name='r1')
    root2 = _mk_server(2, tenant_id=1, name='r2')

    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=1), \
            patch(SUPER_CHECK, new=AsyncMock(return_value=True)), \
            patch(f'{DAO}.aget_all_server', new=AsyncMock(return_value=[root1, root2])), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])):
        result = await LLMService.get_all_llm(operator=_mk_operator())

    assert len(result) == 2
    assert all(r.is_root_shared_readonly is False for r in result)


@pytest.mark.asyncio
async def test_root_regular_user_sees_root_servers_readonly():
    """Root-tenant *non-super* user (leaf=ROOT, is_super=False) must see
    Root-tenant servers as readonly. Catches the post-backfill incident
    where a misbound user (e.g. ``user_tenant`` double-default leaving
    them on Root) was rendered the writable Root view, even though
    backend ``_assert_root_writable`` would 19801 their PUT. The flag now
    reflects that 19801 contract so the UI greys out the edit button up
    front instead of letting the user click and bounce."""
    root1 = _mk_server(1, tenant_id=1, name='r1')

    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=1), \
            patch(SUPER_CHECK, new=AsyncMock(return_value=False)), \
            patch(f'{DAO}.aget_all_server', new=AsyncMock(return_value=[root1])), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])):
        result = await LLMService.get_all_llm(operator=_mk_operator())

    assert [r.id for r in result] == [1]
    assert result[0].is_root_shared_readonly is True


@pytest.mark.asyncio
async def test_super_admin_with_scope_acts_as_child():
    """AC-13 / AC-14: super admin with F019 scope=5 sees the Child 5 view.

    Because ``get_current_tenant_id`` already honours the admin-scope
    override (F019), the Service code path is identical to a genuine
    Child user; mocking ``get_current_tenant_id`` to return 5 simulates
    the middleware outcome.
    """
    own = _mk_server(50, tenant_id=5, name='child5-own')
    shared = _mk_server(200, tenant_id=1, name='root-shared-to-5')

    fake_root_tenant = MagicMock(tenant_name='默认租户')
    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(SUPER_CHECK, new=AsyncMock(return_value=True)), \
            patch(f'{DAO}.aget_all_server', new=AsyncMock(return_value=[own])), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[200])), \
            patch(f'{DAO}.aget_server_by_ids',
                  new=AsyncMock(return_value=[shared])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])), \
            patch('bisheng.database.models.tenant.TenantDao.aget_by_id',
                  new=AsyncMock(return_value=fake_root_tenant)):
        result = await LLMService.get_all_llm(operator=_mk_operator())

    assert [r.id for r in result] == [50, 200]
    # Even a super admin acting under scope=child must see the Root
    # row as readonly — the management view simulates the Child's
    # write surface, not Root's.
    assert {r.id: r.is_root_shared_readonly for r in result} == {50: False, 200: True}
    # Root row carries the Root tenant name so the readonly badge can
    # render "{root_name} 共享 · 只读" instead of a hard-coded "Root".
    by_id = {r.id: r for r in result}
    assert by_id[200].tenant_name == '默认租户'
    assert by_id[50].tenant_name is None


@pytest.mark.asyncio
async def test_child_user_llm_list_runs_own_query_under_strict_filter():
    """Regression guard for the IN-list short-circuit. The Child branch
    must wrap ``aget_all_server`` in ``strict_tenant_filter`` so the
    auto-injected ``WHERE tenant_id IN (leaf, ROOT)`` collapses to
    ``WHERE tenant_id = leaf`` and cannot silently return Root rows.
    Without this, the FGA ``shared_with`` check below is architected
    away (own already covers every Root server)."""
    from bisheng.core.context.tenant import is_strict_tenant_filter

    own = _mk_server(10, tenant_id=5, name='own')
    seen_strict = {}

    async def _capture():
        seen_strict['flag'] = is_strict_tenant_filter()
        return [own]

    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(SUPER_CHECK, new=AsyncMock(return_value=False)), \
            patch(f'{DAO}.aget_all_server', new=AsyncMock(side_effect=_capture)), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])):
        await LLMService.get_all_llm(operator=_mk_operator())

    assert seen_strict.get('flag') is True


@pytest.mark.asyncio
async def test_child_user_unshared_root_server_excluded_from_list():
    """The bug user reported: after ``disable_sharing`` revokes the FGA
    tuple, the Root server must disappear from the Child's list. With
    ``aget_all_server`` returning only the leaf's own rows (strict mode)
    and ``shared_ids`` empty, the merged result must contain no Root
    rows even if the table still holds them."""
    own = _mk_server(10, tenant_id=5, name='own')

    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(SUPER_CHECK, new=AsyncMock(return_value=False)), \
            patch(f'{DAO}.aget_all_server', new=AsyncMock(return_value=[own])), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[])), \
            patch(f'{DAO}.aget_server_by_ids',
                  new=AsyncMock(return_value=[])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])):
        result = await LLMService.get_all_llm(operator=_mk_operator())

    assert [r.id for r in result] == [10]
    assert not any(r.is_root_shared_readonly for r in result)


@pytest.mark.asyncio
async def test_get_all_llm_dedupes_leaf_vs_shared_overlap():
    """Root's own callers should not see duplicate entries when a Root
    row exists in both the leaf query (leaf==Root) and the shared list
    (which is always empty when leaf==Root). Regression guard for the
    short-circuit in ``aget_shared_server_ids_for_leaf(1)``."""
    root1 = _mk_server(1, tenant_id=1)
    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=1), \
            patch(SUPER_CHECK, new=AsyncMock(return_value=True)), \
            patch(f'{DAO}.aget_all_server', new=AsyncMock(return_value=[root1])), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[])), \
            patch(f'{DAO}.aget_server_by_ids',
                  new=AsyncMock(return_value=[])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])):
        result = await LLMService.get_all_llm(operator=_mk_operator())
    assert [r.id for r in result] == [1]


# --- get_one_llm child×Root visibility ----------------------------------


@pytest.mark.asyncio
async def test_get_one_llm_child_root_unshared_raises_not_found():
    """URL-direct GET must not leak a Root server whose share has been
    revoked. Even though the IN-list ``visible_tenant_ids = {leaf, ROOT}``
    lets ``aget_server_by_id`` return the row, the FGA cross-check below
    enforces the same visibility contract as the list.

    ``conftest.premock_import_chain`` swaps ``NotFoundError`` for a Mock
    whose ``.http_exception()`` returns another Mock — which raises
    ``TypeError`` when raised. Substitute a thin stub that yields a real
    HTTPException so the assertion can target a real status code.
    """
    from fastapi import HTTPException

    class _StubNotFound:
        @classmethod
        def http_exception(cls):
            return HTTPException(status_code=404, detail='not found')

    root = _mk_server(100, tenant_id=1, name='unshared-root')
    with patch(f'{CONTEXT}.NotFoundError', _StubNotFound), \
            patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(SUPER_CHECK, new=AsyncMock(return_value=False)), \
            patch(f'{DAO}.aget_server_by_id', new=AsyncMock(return_value=root)), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[])):
        with pytest.raises(HTTPException) as excinfo:
            await LLMService.get_one_llm(100, operator=_mk_operator())
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_get_one_llm_child_root_shared_returns_readonly_info():
    """Counterpart: when the Root server is in the Child's FGA shared
    list, ``get_one_llm`` returns the row tagged
    ``is_root_shared_readonly=True``. ``share_to_children`` must stay at
    its default (False) for Child callers — only Root scope hydrates it."""
    root = _mk_server(100, tenant_id=1, name='shared-root')
    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(SUPER_CHECK, new=AsyncMock(return_value=False)), \
            patch(f'{DAO}.aget_server_by_id', new=AsyncMock(return_value=root)), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[100])), \
            patch(f'{DAO}.aget_model_by_server_ids', new=AsyncMock(return_value=[])):
        info = await LLMService.get_one_llm(100, operator=_mk_operator())

    assert info.id == 100
    assert info.is_root_shared_readonly is True
    assert info.is_root_shared_readonly is True
    assert info.share_to_children is False


@pytest.mark.asyncio
async def test_get_one_llm_root_regular_user_marks_root_readonly():
    """Root-tenant non-super caller opening a Root row in detail must
    receive ``is_root_shared_readonly=True`` and a default-False
    ``share_to_children`` (the truthful FGA value is suppressed for
    non-super callers — they cannot write the toggle anyway, so leaking
    the share state would be a data-leak with no upside)."""
    root = _mk_server(7, tenant_id=1, name='r7')
    with patch(f'{CONTEXT}.get_current_tenant_id', return_value=1), \
            patch(SUPER_CHECK, new=AsyncMock(return_value=False)), \
            patch(f'{DAO}.aget_server_by_id', new=AsyncMock(return_value=root)), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[])), \
            patch(f'{DAO}.aget_model_by_server_ids', new=AsyncMock(return_value=[])):
        info = await LLMService.get_one_llm(7, operator=_mk_operator())

    assert info.id == 7
    assert info.is_root_shared_readonly is True
    assert info.share_to_children is False


# --- get_model_for_call -------------------------------------------------


@pytest.mark.asyncio
async def test_get_model_for_call_own_model_returns():
    """AC-22: caller tenant owns the model → returned directly (event
    filter finds it; no bypass needed)."""
    own = MagicMock(id=10, server_id=50, tenant_id=5)
    with patch(f'{DAO}.aget_model_by_id', new=AsyncMock(return_value=own)):
        result = await LLMService.get_model_for_call(10)
    assert result is own


@pytest.mark.asyncio
async def test_get_model_for_call_root_shared_accessible_for_child():
    """AC-20: model hidden by event filter but owned by a Root server in
    the caller's shared list → bypass lookup resolves it."""
    raw = MagicMock(id=100, server_id=200, tenant_id=1)
    mock_fn = AsyncMock()
    mock_fn.side_effect = [None, raw]  # event-filtered miss, then bypass hit

    with patch(f'{DAO}.aget_model_by_id', mock_fn), \
            patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[200])):
        result = await LLMService.get_model_for_call(100)
    assert result is raw


@pytest.mark.asyncio
async def test_get_model_for_call_cross_child_raises_19802():
    """AC-22 / AC-23: model exists but belongs to a different Child and
    is not Root-shared → 19802."""
    from fastapi import HTTPException

    raw = MagicMock(id=100, server_id=201, tenant_id=7)
    mock_fn = AsyncMock()
    mock_fn.side_effect = [None, raw]

    with patch(f'{DAO}.aget_model_by_id', mock_fn), \
            patch(f'{CONTEXT}.get_current_tenant_id', return_value=5), \
            patch(f'{DAO}.aget_shared_server_ids_for_leaf',
                  new=AsyncMock(return_value=[])):
        with pytest.raises(HTTPException) as excinfo:
            await LLMService.get_model_for_call(100)
    assert excinfo.value.status_code == 19802


# --- only_shared preview (T10) -----------------------------------------


@pytest.mark.asyncio
async def test_mount_child_preview_shared_llm_list():
    """AC-17: super admin + only_shared=true → list Root servers that
    have ≥1 Child via FGA shared_with. The implementation walks Root
    servers and probes each with ``list_sharing_children`` because
    OpenFGA's /read rejects relation-only queries."""
    shared = _mk_server(1, tenant_id=1, name='shared-root')
    unshared = _mk_server(2, tenant_id=1, name='unshared-root')
    leaf = _mk_server(3, tenant_id=5, name='leaf')

    async def _list_children(_type, oid):
        return ['5', '7'] if oid == '1' else []

    operator = MagicMock(user_id=99)
    with patch(f'{DAO}.aget_all_server',
               new=AsyncMock(return_value=[shared, unshared, leaf])), \
            patch(f'{DAO}.aget_model_by_server_ids',
                  new=AsyncMock(return_value=[])), \
            patch('bisheng.llm.domain.services.llm.ResourceShareService.list_sharing_children',
                  new=AsyncMock(side_effect=_list_children)), \
            patch('bisheng.llm.domain.services.llm._check_is_global_super',
                  new=AsyncMock(return_value=True)):
        result = await LLMService.get_all_llm(only_shared=True, operator=operator)

    assert [r.id for r in result] == [1]
    assert result[0].name == 'shared-root'


@pytest.mark.asyncio
async def test_mount_child_preview_forbidden_for_non_super_admin():
    """Boundary: only_shared=true + non-super → 19803."""
    from fastapi import HTTPException

    operator = MagicMock(user_id=42)
    with patch('bisheng.llm.domain.services.llm._check_is_global_super',
               new=AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as excinfo:
            await LLMService.get_all_llm(only_shared=True, operator=operator)
    assert excinfo.value.status_code == 19803


@pytest.mark.asyncio
async def test_mount_child_preview_without_operator_forbidden():
    """Defensive: only_shared=true must always present an operator so
    the super-admin check can run. None → 19803 fail-closed."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        await LLMService.get_all_llm(only_shared=True, operator=None)
    assert excinfo.value.status_code == 19803


# --- audit_log write (T09) ---------------------------------------------


def test_api_key_hash_is_16_char_sha256_prefix():
    """AC-12: audit payload stores only sha256[:16] of the key; plaintext
    never appears in the hash or in a round-tripped form."""
    import hashlib
    from bisheng.llm.domain.services.llm import _llm_api_key_hash

    key = 'sk-supersecret-abc-1234567890'
    config = {'openai_api_key': key}

    h = _llm_api_key_hash(config)
    assert h is not None
    assert len(h) == 16
    assert h == hashlib.sha256(key.encode()).hexdigest()[:16]
    # Plaintext must not be discoverable from the hash body.
    assert 'supersecret' not in h


def test_api_key_hash_returns_none_when_no_key_field():
    """Missing key → None so the audit row can distinguish 'no key' from
    'rotated / empty string'."""
    from bisheng.llm.domain.services.llm import _llm_api_key_hash
    assert _llm_api_key_hash(None) is None
    assert _llm_api_key_hash({}) is None
    assert _llm_api_key_hash({'openai_api_key': ''}) is None
    assert _llm_api_key_hash({'openai_api_key': None}) is None


def test_api_key_hash_accepts_alternative_field_name():
    """``config.api_key`` is the generic alias — also fingerprint it."""
    from bisheng.llm.domain.services.llm import _llm_api_key_hash
    assert _llm_api_key_hash({'api_key': 'abc123'}) is not None


@pytest.mark.asyncio
async def test_get_model_for_call_unknown_id_raises_19802():
    """Boundary: model id is simply unknown (no row at all) → 19802."""
    from fastapi import HTTPException

    mock_fn = AsyncMock(return_value=None)  # both attempts miss
    with patch(f'{DAO}.aget_model_by_id', mock_fn):
        with pytest.raises(HTTPException) as excinfo:
            await LLMService.get_model_for_call(9999)
    assert excinfo.value.status_code == 19802
