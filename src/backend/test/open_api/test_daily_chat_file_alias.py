"""Daily chat checks ownership of the same attachment value that the model reads."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.open_api.domain.schemas.workstation import OpenDailyChatCompletionReq
from bisheng.open_api.domain.services import daily_chat_service as service_module
from bisheng.open_api.domain.services.daily_chat_service import OpenDailyChatService

CONFIG = {"models": [{"id": "7"}], "tools": []}
URL = "http://minio.test/tmp-bucket/open-api/sa-1/a.txt"


@pytest.mark.parametrize("key", ["filepath", "file_path"])
async def test_ownership_check_and_model_input_share_one_value(monkeypatch, key):
    assert_owned = AsyncMock()
    monkeypatch.setattr(service_module.TempUploadService, "assert_owned_references", assert_owned)
    monkeypatch.setattr(service_module, "session_subject_from_principal", lambda _principal: SimpleNamespace())
    monkeypatch.setattr(service_module.WorkStationService, "get_open_api_daily_config", AsyncMock(return_value=CONFIG))
    request = OpenDailyChatCompletionReq.model_validate(
        {"clientTimestamp": "t", "model": "7", "files": [{key: URL, "name": "a.txt"}]}
    )

    internal, _subject = await OpenDailyChatService.prepare_request(
        principal=SimpleNamespace(), request=request, login_user=SimpleNamespace()
    )

    checked = assert_owned.await_args.args[0]
    assert checked == [{"filepath": URL, "name": "a.txt"}]
    assert internal.files == checked
