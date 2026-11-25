"""Evaluation result download requires an actual owned evaluation record."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.evaluation.api.endpoints import evaluation as endpoint


async def test_arbitrary_key_denied_before_sdk(monkeypatch):
    storage = SimpleNamespace(bucket="bisheng", tmp_bucket="tmp-dir", get_share_link=AsyncMock(return_value="signed"))
    monkeypatch.setattr(endpoint, "get_minio_storage", AsyncMock(return_value=storage), raising=False)
    with pytest.raises(UnAuthorizedError):
        await endpoint.get_download_url(file_url="original/1.pdf", login_user=SimpleNamespace(user_id=11, tenant_id=7))
    storage.get_share_link.assert_not_awaited()


@pytest.mark.parametrize(
    "tenant,user,deleted,allowed", [(7, 11, 0, True), (8, 11, 0, False), (7, 22, 0, False), (7, 11, 1, False)]
)
async def test_only_owned_live_evaluation_file_is_signed(monkeypatch, tenant, user, deleted, allowed):
    from bisheng.evaluation.domain.services import evaluation_service as service

    monkeypatch.setattr(
        service.EvaluationRepository,
        "find_download_owner",
        lambda _: SimpleNamespace(tenant_id=tenant, user_id=user, is_delete=deleted),
    )
    storage = SimpleNamespace(get_share_link=AsyncMock(return_value="signed"))
    monkeypatch.setattr("bisheng.core.storage.minio.minio_manager.get_minio_storage", AsyncMock(return_value=storage))
    actor = SimpleNamespace(user_id=11, tenant_id=7)
    if allowed:
        assert await service.EvaluationService.get_download_url("evaluation/result/id.csv", actor) == "signed"
        storage.get_share_link.assert_awaited_once_with("evaluation/result/id.csv")
    else:
        with pytest.raises(UnAuthorizedError):
            await service.EvaluationService.get_download_url("evaluation/result/id.csv", actor)
        storage.get_share_link.assert_not_awaited()


def test_repository_resolves_exact_stored_object_not_prefix(sqlite_session_patch):
    from bisheng.evaluation.domain.models.evaluation import Evaluation
    from bisheng.evaluation.domain.repositories.evaluation_repository import EvaluationRepository

    row = Evaluation(
        user_id=11,
        tenant_id=7,
        unique_id="app",
        exec_type="assistant",
        file_path="evaluation/dataset/in.csv",
        result_file_path="evaluation/result/out.csv",
    )
    sqlite_session_patch.add(row)
    sqlite_session_patch.commit()
    assert EvaluationRepository.find_download_owner("evaluation/dataset/in.csv").user_id == 11
    assert EvaluationRepository.find_download_owner("evaluation/result/out.csv").tenant_id == 7
    assert EvaluationRepository.find_download_owner("evaluation/result/other.csv") is None
    row.is_delete = 1
    sqlite_session_patch.add(row)
    sqlite_session_patch.commit()
    assert EvaluationRepository.find_download_owner("evaluation/result/out.csv") is None
