"""T448: hosted retrieval preserves its actual credential principal object.

覆盖 AC: AC-68, AC-71, AC-87, AC-88, AC-89, AC-92
APP bus owns visitor qualification; the endpoint must not manufacture identity.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalFacadeResult
from bisheng.open_endpoints.api.endpoints import filelib
from bisheng.open_endpoints.domain.schemas.filelib import RetrieveReq
from test.open_api.model_gateway_fixtures import hosted_app_principal


@pytest.mark.parametrize("visitor", [None, 77])
async def test_hosted_endpoint_forwards_original_principal_even_without_visitor(monkeypatch, visitor):
    principal = hosted_app_principal(scopes=frozenset({"knowledge:read"}))
    monkeypatch.setattr(filelib, "get_current_open_api_principal", lambda: principal)
    monkeypatch.setattr(filelib, "hosted_app_access_user", lambda request, value: visitor)
    retrieve = AsyncMock(return_value=RetrievalFacadeResult(chunks=[], total=0, effective_scope=[]))
    monkeypatch.setattr(filelib.CapabilityBusService, "retrieve", retrieve)
    repository = MagicMock()
    await filelib.retrieve_chunks(request=MagicMock(), req=RetrieveReq(query="q"), version_repo=repository)
    passed = retrieve.call_args.kwargs
    assert passed["principal"] is principal
    assert passed["access_user_id"] == visitor
    assert passed["app_id"] == principal.subject_ref
    assert passed["credential_id"] == principal.credential_id
    assert passed["version_repo"] is repository
