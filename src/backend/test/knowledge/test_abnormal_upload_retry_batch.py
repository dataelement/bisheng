from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.services.abnormal_upload_service import AbnormalUploadService


class _File:
    def __init__(self, file_id: int):
        self.id = file_id
        self.status = 3
        self.remark = "failed"
        self.updater_id = None
        self.updater_name = None
        self.tenant_id = 1
        self.knowledge_id = 8


class _Repo:
    def __init__(self):
        self.session = SimpleNamespace(commit=AsyncMock())
        self.listed = None

    async def lock_abnormal_source_file(self, file_id: int):
        if file_id == 9:
            return None
        return _File(file_id)

    async def list_abnormal_source_uploads(self, **kwargs):
        self.listed = kwargs
        return [{"file_id": 1, "company_name": "首钢"}], 1


@pytest.mark.asyncio
async def test_retry_batch_counts_missing_files_and_keeps_dispatched_ones(monkeypatch):
    dispatched: list[int] = []

    async def _dispatch(**kwargs):
        dispatched.append(int(kwargs["file_id"]))

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.abnormal_upload_service.AuditLogDao.ainsert_v2",
        AsyncMock(),
    )
    service = AbnormalUploadService(
        login_user=SimpleNamespace(
            user_id=3,
            user_name="运营",
            tenant_id=1,
            role_names=["平台管理员"],
            is_global_super=False,
        ),
        file_repository=_Repo(),
        space_service=SimpleNamespace(),
        dispatcher=_dispatch,
    )

    result = await service.retry_batch([4, 9])

    assert result == {"retried": 1, "failed": 1}
    assert dispatched == [4]


@pytest.mark.asyncio
async def test_list_uploads_passes_org_name_filters():
    repo = _Repo()
    service = AbnormalUploadService(
        login_user=SimpleNamespace(
            user_id=3,
            user_name="运营",
            tenant_id=1,
            role_names=["平台管理员"],
            is_global_super=False,
        ),
        file_repository=repo,
        space_service=SimpleNamespace(),
    )

    await service.list_uploads(
        page=1,
        page_size=20,
        uploader_company="首钢",
        uploader_department="设备部",
        uploader_office="点检科",
    )

    assert repo.listed["uploader_company"] == "首钢"
    assert repo.listed["uploader_department"] == "设备部"
    assert repo.listed["uploader_office"] == "点检科"
