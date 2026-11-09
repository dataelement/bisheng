"""Retired type=2 must not be recreated by the legacy workstation routes.

Temporary conversation attachments use /workstation/files and are independent.
Exercise the real compatibility endpoints and services before any external IO.
"""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, UploadFile

from bisheng.common.errcode.knowledge import KnowledgeTypeNotSupportedError
from bisheng.core.cache import utils as cache_utils
from bisheng.knowledge.api.endpoints import knowledge as knowledge_api
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.role.domain.services.quota_service import QuotaService
from bisheng.workstation.api.endpoints import knowledge as workstation_api
from bisheng.workstation.domain.services.workstation_service import WorkStationService


def test_retired_personal_info_has_no_lazy_creation_or_old_data_read(monkeypatch):
    read = Mock(side_effect=AssertionError("retired personal resources are not listed or created"))
    monkeypatch.setattr(KnowledgeDao, "get_user_knowledge", read)
    response = knowledge_api.get_personal_knowledge_info(request=None, login_user=SimpleNamespace(user_id=1))
    assert response.data == []
    read.assert_not_called()


def test_retired_personal_state_does_not_block_other_chat_resources(monkeypatch):
    read = Mock(side_effect=AssertionError("retired personal state is not an active chat dependency"))
    monkeypatch.setattr(KnowledgeDao, "get_user_knowledge", read)
    response = knowledge_api.get_knowledge_status(login_user=SimpleNamespace(user_id=1))
    assert response.data == {"status": "success"}
    read.assert_not_called()


async def test_retired_personal_list_preserves_empty_legacy_envelope(monkeypatch):
    read = Mock(side_effect=AssertionError("retired personal resources are not browsable"))
    monkeypatch.setattr(KnowledgeDao, "get_user_knowledge", read)
    response = await workstation_api.query_knowledge_list(None, page=1, size=20, login_user=SimpleNamespace(user_id=1))
    assert response.data == {"list": [], "total": 0}
    read.assert_not_called()


async def test_retired_personal_upload_rejects_before_staging_and_preserves_error(monkeypatch):
    stage = Mock(side_effect=AssertionError("no attachment staging for retired personal KB"))
    quota = AsyncMock(side_effect=AssertionError("no quota or model work for retired personal KB"))
    monkeypatch.setattr(cache_utils, "save_download_file", stage)
    monkeypatch.setattr(QuotaService, "get_knowledge_space_upload_limit_bytes", quota)
    file = UploadFile(filename="legacy.txt", file=BytesIO(b"unwritten"))
    with pytest.raises(KnowledgeTypeNotSupportedError):
        await workstation_api.knowledge_upload(None, BackgroundTasks(), file, SimpleNamespace(user_id=1))
    assert file.file.closed
    stage.assert_not_called()
    quota.assert_not_awaited()


async def test_retired_upload_service_cannot_be_used_to_create_type_two(monkeypatch):
    read = AsyncMock(side_effect=AssertionError("no retired personal DB access"))
    monkeypatch.setattr(KnowledgeDao, "aget_user_knowledge", read)
    with pytest.raises(KnowledgeTypeNotSupportedError):
        await WorkStationService.uploadPersonalKnowledge(
            None, SimpleNamespace(user_id=1), "legacy.txt", BackgroundTasks()
        )
    read.assert_not_awaited()
