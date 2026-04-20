"""F020 T05 LLMDao write-method tests.

No real DB / FGA — mocks the async session context manager, the
``_check_is_global_super`` middleware helper, ``TenantDao.aget``, and
``ResourceShareService.enable_sharing / disable_sharing``. Tests validate
the Service-facing branch decisions of the updated DAO methods:

- ``ainsert_server_with_models``: tenant_id fill, endpoint whitelist
  guard, Root → Children fanout (AC-01, AC-02, AC-05, 19804).
- ``aupdate_server_share``: only Root + only super admin may flip
  (AC-04, 19801, 19802).
- ``update_server_with_models``: Root server read-only for non-super
  (AC-08 DAO side).
- ``adelete_server_by_id``: same guard + idempotent FGA cleanup (AC-09).
- AC-18 / AC-19 (mount-time fanout) reduce to "llm_server is declared
  in F017 SUPPORTED_SHAREABLE_TYPES" — the actual fanout is F017
  ResourceShareService's contract, already covered in F017 tests.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.llm.domain.models.llm_server import LLMDao, LLMServer


# --- fixtures ---------------------------------------------------------------


def _mk_user(user_id: int = 42) -> MagicMock:
    u = MagicMock()
    u.user_id = user_id
    return u


def _mk_root_tenant(share_default: bool = True) -> MagicMock:
    t = MagicMock()
    t.parent_tenant_id = None
    t.share_default_to_children = share_default
    return t


def _session_context(mock_session):
    """Async context manager that yields ``mock_session``."""

    @asynccontextmanager
    async def _cm():
        yield mock_session

    return _cm


def _build_session(flushed_id: int = 100):
    """Build a SQLModel-ish mock session supporting add/add_all (sync)
    + flush/commit/refresh/exec (async)."""
    s = MagicMock()
    s.add = MagicMock()
    s.add_all = MagicMock()
    s.flush = AsyncMock()
    s.commit = AsyncMock()
    s.exec = AsyncMock()

    # Simulate post-flush id assignment by refresh / flush side-effects.
    def _flush_effect(*args, **kwargs):
        # flush doesn't know which object to write; tests set server.id
        # manually before the refresh happens.
        return None

    s.flush.side_effect = _flush_effect

    def _refresh_effect(obj):
        if getattr(obj, 'id', None) is None:
            obj.id = flushed_id
        return obj

    s.refresh = AsyncMock(side_effect=_refresh_effect)
    return s


# --- ainsert_server_with_models --------------------------------------------


@pytest.mark.asyncio
async def test_root_llm_default_shared_writes_viewer_tuple():
    """AC-01: Root + share_to_children=True + share_default_to_children=True
    → enable_sharing fanout."""
    session = _build_session(flushed_id=100)
    server = LLMServer(name='s1', type='openai', config={})

    enable_mock = AsyncMock(return_value=[5, 7])
    with patch('bisheng.llm.domain.models.llm_server.get_async_db_session',
               _session_context(session)), \
         patch('bisheng.llm.domain.models.llm_server.get_current_tenant_id',
               return_value=1), \
         patch('bisheng.database.models.tenant.TenantDao.aget_by_id',
               new=AsyncMock(return_value=_mk_root_tenant(share_default=True))), \
         patch('bisheng.tenant.domain.services.resource_share_service.'
               'ResourceShareService.enable_sharing', new=enable_mock), \
         patch('bisheng.llm.domain.models.llm_server._check_is_global_super',
               new=AsyncMock(return_value=True)):
        await LLMDao.ainsert_server_with_models(
            server, models=[], share_to_children=True, operator=_mk_user(),
        )

    enable_mock.assert_awaited_once_with('llm_server', '100')
    assert server.tenant_id == 1


@pytest.mark.asyncio
async def test_root_llm_share_off_skips_viewer_tuple():
    """AC-02: share_to_children=False → enable_sharing NOT called."""
    session = _build_session(flushed_id=101)
    server = LLMServer(name='s2', type='openai', config={})

    enable_mock = AsyncMock()
    with patch('bisheng.llm.domain.models.llm_server.get_async_db_session',
               _session_context(session)), \
         patch('bisheng.llm.domain.models.llm_server.get_current_tenant_id',
               return_value=1), \
         patch('bisheng.database.models.tenant.TenantDao.aget_by_id',
               new=AsyncMock(return_value=_mk_root_tenant(share_default=True))), \
         patch('bisheng.tenant.domain.services.resource_share_service.'
               'ResourceShareService.enable_sharing', new=enable_mock), \
         patch('bisheng.llm.domain.models.llm_server._check_is_global_super',
               new=AsyncMock(return_value=True)):
        await LLMDao.ainsert_server_with_models(
            server, models=[], share_to_children=False, operator=_mk_user(),
        )

    enable_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_child_admin_creates_own_llm_not_shared():
    """AC-05: tenant_id=5 (Child) → tenant_id fill is 5, no fanout."""
    session = _build_session(flushed_id=102)
    server = LLMServer(name='s3', type='openai', config={})

    enable_mock = AsyncMock()

    class _NoWhitelist:
        class llm:
            endpoint_whitelist: list = []

    with patch('bisheng.llm.domain.models.llm_server.get_async_db_session',
               _session_context(session)), \
         patch('bisheng.llm.domain.models.llm_server.get_current_tenant_id',
               return_value=5), \
         patch('bisheng.llm.domain.models.llm_server.settings', _NoWhitelist()), \
         patch('bisheng.tenant.domain.services.resource_share_service.'
               'ResourceShareService.enable_sharing', new=enable_mock), \
         patch('bisheng.llm.domain.models.llm_server._check_is_global_super',
               new=AsyncMock(return_value=False)):
        await LLMDao.ainsert_server_with_models(
            server, models=[], share_to_children=True, operator=_mk_user(),
        )

    enable_mock.assert_not_awaited()  # tenant_id != 1, no fanout
    assert server.tenant_id == 5


@pytest.mark.asyncio
async def test_endpoint_whitelist_enforced_for_child_admin():
    """Boundary: non-super + whitelist + mismatched endpoint → 19804."""
    from fastapi import HTTPException

    server = LLMServer(name='s4', type='openai',
                       config={'openai_api_base': 'https://attacker.example.com/v1'})

    class _FakeLLMConf:
        endpoint_whitelist = ['https://api.openai.com', 'https://*.azure.com']

    class _FakeSettings:
        llm = _FakeLLMConf()

    with patch('bisheng.llm.domain.models.llm_server.settings', _FakeSettings()), \
         patch('bisheng.llm.domain.models.llm_server.get_current_tenant_id',
               return_value=5), \
         patch('bisheng.llm.domain.models.llm_server._check_is_global_super',
               new=AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as excinfo:
            await LLMDao.ainsert_server_with_models(
                server, models=[], share_to_children=False, operator=_mk_user(),
            )

    assert excinfo.value.status_code == 19804  # BaseErrorCode.http_exception uses Code as status_code


# --- aupdate_server_share --------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_root_llm_share_enables_fga_tuple():
    """AC-04 on: share_to_children True → enable_sharing fanout."""
    root_server = MagicMock(id=200, tenant_id=1)

    enable_mock = AsyncMock(return_value=[5])
    disable_mock = AsyncMock()
    with patch.object(LLMDao, 'aget_server_by_id',
                      new=AsyncMock(return_value=root_server)), \
         patch('bisheng.tenant.domain.services.resource_share_service.'
               'ResourceShareService.enable_sharing', new=enable_mock), \
         patch('bisheng.tenant.domain.services.resource_share_service.'
               'ResourceShareService.disable_sharing', new=disable_mock), \
         patch('bisheng.llm.domain.models.llm_server._check_is_global_super',
               new=AsyncMock(return_value=True)):
        await LLMDao.aupdate_server_share(200, True, _mk_user())

    enable_mock.assert_awaited_once_with('llm_server', '200')
    disable_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_toggle_root_llm_share_off_removes_fga_tuple():
    """AC-04 off: share_to_children False → disable_sharing."""
    root_server = MagicMock(id=200, tenant_id=1)

    enable_mock = AsyncMock()
    disable_mock = AsyncMock(return_value=[5])
    with patch.object(LLMDao, 'aget_server_by_id',
                      new=AsyncMock(return_value=root_server)), \
         patch('bisheng.tenant.domain.services.resource_share_service.'
               'ResourceShareService.enable_sharing', new=enable_mock), \
         patch('bisheng.tenant.domain.services.resource_share_service.'
               'ResourceShareService.disable_sharing', new=disable_mock), \
         patch('bisheng.llm.domain.models.llm_server._check_is_global_super',
               new=AsyncMock(return_value=True)):
        await LLMDao.aupdate_server_share(200, False, _mk_user())

    disable_mock.assert_awaited_once_with('llm_server', '200')
    enable_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_toggle_share_on_non_root_raises_19802():
    """aupdate_server_share on a Child server → 19802."""
    from fastapi import HTTPException

    child_server = MagicMock(id=301, tenant_id=5)
    with patch.object(LLMDao, 'aget_server_by_id',
                      new=AsyncMock(return_value=child_server)), \
         patch('bisheng.llm.domain.models.llm_server._check_is_global_super',
               new=AsyncMock(return_value=True)):
        with pytest.raises(HTTPException) as excinfo:
            await LLMDao.aupdate_server_share(301, True, _mk_user())

    assert excinfo.value.status_code == 19802


@pytest.mark.asyncio
async def test_toggle_share_by_non_super_raises_19801():
    """aupdate_server_share by Child Admin → 19801 (even on a Root target)."""
    from fastapi import HTTPException

    root_server = MagicMock(id=200, tenant_id=1)
    with patch.object(LLMDao, 'aget_server_by_id',
                      new=AsyncMock(return_value=root_server)), \
         patch('bisheng.llm.domain.models.llm_server._check_is_global_super',
               new=AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as excinfo:
            await LLMDao.aupdate_server_share(200, True, _mk_user())

    assert excinfo.value.status_code == 19801


# --- adelete_server_by_id --------------------------------------------------


@pytest.mark.asyncio
async def test_child_admin_cannot_delete_root_shared_llm():
    """AC-09: Child Admin attempts delete on Root server → 19801."""
    from fastapi import HTTPException

    root_server = MagicMock(id=200, tenant_id=1)
    with patch.object(LLMDao, 'aget_server_by_id',
                      new=AsyncMock(return_value=root_server)), \
         patch('bisheng.llm.domain.models.llm_server._check_is_global_super',
               new=AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as excinfo:
            await LLMDao.adelete_server_by_id(200, operator=_mk_user())

    assert excinfo.value.status_code == 19801


@pytest.mark.asyncio
async def test_delete_missing_server_raises_19802():
    """Delete with operator + no such server → 19802."""
    from fastapi import HTTPException

    with patch.object(LLMDao, 'aget_server_by_id',
                      new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as excinfo:
            await LLMDao.adelete_server_by_id(999, operator=_mk_user())

    assert excinfo.value.status_code == 19802


# --- update_server_with_models --------------------------------------------


@pytest.mark.asyncio
async def test_child_admin_cannot_update_root_shared_llm():
    """DAO side of AC-08: Child Admin updates Root server → 19801."""
    from fastapi import HTTPException

    existing = MagicMock(id=200, tenant_id=1)
    incoming = MagicMock(id=200, config={}, tenant_id=5)

    with patch.object(LLMDao, 'aget_server_by_id',
                      new=AsyncMock(return_value=existing)), \
         patch('bisheng.llm.domain.models.llm_server._check_is_global_super',
               new=AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as excinfo:
            await LLMDao.update_server_with_models(
                incoming, models=[], operator=_mk_user(),
            )

    assert excinfo.value.status_code == 19801


# --- AC-18 / AC-19 mount-time fanout contract (F017) -----------------------


# --- aget_shared_server_ids_for_leaf (T06) --------------------------------


@pytest.mark.asyncio
async def test_aget_shared_server_ids_for_leaf_returns_root_shared():
    """AC-03 source: FGA list_objects response → int id list."""
    fga = MagicMock()
    fga.list_objects = AsyncMock(return_value=[
        'llm_server:123', 'llm_server:456',
    ])
    with patch('bisheng.core.openfga.manager.aget_fga_client',
               new=AsyncMock(return_value=fga)):
        ids = await LLMDao.aget_shared_server_ids_for_leaf(5)

    assert sorted(ids) == [123, 456]
    fga.list_objects.assert_awaited_once_with(
        user='tenant:5', relation='shared_with', type='llm_server',
    )


@pytest.mark.asyncio
async def test_aget_shared_server_ids_for_leaf_root_returns_empty():
    """AC-03 edge: leaf=1 (Root) never has shares pointing at itself."""
    fga = MagicMock()
    fga.list_objects = AsyncMock()
    with patch('bisheng.core.openfga.manager.aget_fga_client',
               new=AsyncMock(return_value=fga)):
        ids = await LLMDao.aget_shared_server_ids_for_leaf(1)

    assert ids == []
    fga.list_objects.assert_not_awaited()  # short-circuit before FGA call


@pytest.mark.asyncio
async def test_aget_shared_server_ids_for_leaf_fga_disabled_returns_empty():
    """AC-03 edge: OpenFGA disabled → empty list, no exception."""
    with patch('bisheng.core.openfga.manager.aget_fga_client',
               new=AsyncMock(return_value=None)):
        ids = await LLMDao.aget_shared_server_ids_for_leaf(5)

    assert ids == []


@pytest.mark.asyncio
async def test_aget_shared_server_ids_for_leaf_fga_failure_degrades_to_empty():
    """Boundary: FGA raise on list_objects → log + empty list (fail-closed)."""
    fga = MagicMock()
    fga.list_objects = AsyncMock(side_effect=RuntimeError('FGA down'))
    with patch('bisheng.core.openfga.manager.aget_fga_client',
               new=AsyncMock(return_value=fga)):
        ids = await LLMDao.aget_shared_server_ids_for_leaf(5)

    assert ids == []


def test_llm_server_registered_in_shareable_types():
    """AC-18 / AC-19: F017 uses SUPPORTED_SHAREABLE_TYPES to decide which
    resource types fan out when ``TenantMountService.mount_child(...,
    auto_distribute=True)`` walks the shared resources. F020 T02b added
    ``llm_server`` to this set — that single piece of config is the
    entire coupling between F020 and the F011/F017 mount flow."""
    from bisheng.tenant.domain.services.resource_share_service import (
        SUPPORTED_SHAREABLE_TYPES,
    )
    assert 'llm_server' in SUPPORTED_SHAREABLE_TYPES
