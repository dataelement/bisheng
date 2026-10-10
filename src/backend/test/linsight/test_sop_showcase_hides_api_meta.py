"""F073: the SOP showcase endpoint returns the raw version, so it must drop
``api_meta`` (caller instructions, credential id) explicitly."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.linsight.api.endpoints import linsight as endpoint
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion, SessionVersionStatusEnum


async def test_showcase_result_never_carries_api_meta(monkeypatch):
    version = LinsightSessionVersion(
        id="svid-1",
        session_id="chat-1",
        user_id=7,
        question="q",
        status=SessionVersionStatusEnum.COMPLETED,
        tenant_id=1,
        api_meta={"channel": "open_api_v2", "instructions": "secret context", "credential_id": 54},
    )
    monkeypatch.setattr(endpoint.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=version))
    monkeypatch.setattr(endpoint.LinsightWorkbenchImpl, "get_execute_task_detail", AsyncMock(return_value=[]))

    response = await endpoint.get_sop_showcase_result(
        sop_id=None, linsight_version_id="svid-1", login_user=SimpleNamespace(user_id=9)
    )

    data = response.data["version_info"]
    assert "api_meta" not in data
    assert data["id"] == "svid-1" and data["question"] == "q"
