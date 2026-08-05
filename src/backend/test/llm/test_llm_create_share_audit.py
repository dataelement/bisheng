"""``add_llm_server`` audit-extra fidelity for ``share_to_children``.

The create request always carries ``share_to_children`` (pydantic
default True), but the fan-out in ``LLMDao.ainsert_server_with_models``
only fires for Root-owned rows. A global super admin working under a
child-tenant admin scope (F019) creates a child-owned server, so the
flag is inert there — the tenant tree is locked to two layers (INV-T1)
and a child can never have children of its own.

These tests pin the audit row to what actually happened rather than to
the request value. Keeping ``models=[]`` skips the per-model
instantiation block entirely, so the flow needs no LangChain mocks.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.domain.schemas import LLMServerCreateReq
from bisheng.llm.domain.services.llm import LLMService

SERVICE = "bisheng.llm.domain.services.llm"
CHILD_TENANT_ID = 7


def _mk_operator(user_id: int = 1):
    op = MagicMock()
    op.user_id = user_id
    return op


def _mk_request():
    return LLMServerCreateReq(name="openai-1", type="openai", config={}, models=[])


async def _run_create(inserted_tenant_id: int, share_to_children: bool) -> dict:
    """Drive ``add_llm_server`` and return the audit ``extra`` payload."""
    inserted = MagicMock()
    inserted.id = 101
    inserted.tenant_id = inserted_tenant_id

    ret = MagicMock()
    ret.id = 101
    ret.models = []

    audit = AsyncMock()
    req = _mk_request()
    req.share_to_children = share_to_children

    with (
        patch(f"{SERVICE}.LLMDao.aget_server_by_name", new=AsyncMock(return_value=None)),
        patch(
            f"{SERVICE}.LLMDao.ainsert_server_with_models",
            new=AsyncMock(return_value=inserted),
        ),
        patch.object(LLMService, "get_one_llm", new=AsyncMock(return_value=ret)),
        patch.object(LLMService, "add_llm_server_hook", new=AsyncMock()),
        patch(f"{SERVICE}._write_llm_audit", new=audit),
    ):
        await LLMService.add_llm_server(MagicMock(), _mk_operator(), req)

    create_call = audit.await_args
    assert create_call is not None
    return create_call.kwargs["extra"]


@pytest.mark.asyncio
async def test_root_create_with_share_on_audits_true():
    extra = await _run_create(ROOT_TENANT_ID, True)
    assert extra["share_to_children"] is True


@pytest.mark.asyncio
async def test_root_create_with_share_off_audits_false():
    extra = await _run_create(ROOT_TENANT_ID, False)
    assert extra["share_to_children"] is False


@pytest.mark.asyncio
async def test_child_scope_create_audits_false_even_when_requested():
    """The UI hides the toggle under a child scope, but a stale client (or
    a direct API caller) can still send True. The share never happens, so
    the audit row must not claim it did."""
    extra = await _run_create(CHILD_TENANT_ID, True)
    assert extra["share_to_children"] is False
