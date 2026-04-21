from unittest.mock import AsyncMock

import pytest

from bisheng.finetune.api import finetune as finetune_api


@pytest.mark.asyncio
async def test_get_job_does_not_force_user_id_filter_for_model_managers(monkeypatch):
    captured = {}

    async def fake_get_all_job(req_data):
        captured["user_id"] = req_data.user_id
        return [], 0

    monkeypatch.setattr(finetune_api.FinetuneService, "get_all_job", fake_get_all_job)

    login_user = type("LoginUser", (), {"user_id": 7})()

    await finetune_api.get_job(
        server=None,
        status="",
        model_name="",
        page=1,
        limit=10,
        login_user=login_user,
    )

    assert captured["user_id"] is None
