"""Only new formats may be imported; historical legacy rows stay convertible."""

import json
from unittest.mock import MagicMock

import pytest

from bisheng.finetune.domain.services import datasets as module
from test.finetune.test_dataset_admin_visibility import datasets as datasets
from test.finetune.test_dataset_menu_api import web as web
from test.fixtures.tenant_filter import isolated_tenant_filter as isolated_tenant_filter

LEGACY = [{"instruction": "question", "output": "answer"}]


@pytest.mark.parametrize("category", ["legacy", "text"])
async def test_new_local_import_rejects_legacy_label_and_legacy_content(web, category):
    response = await web.client.post(
        "/api/v1/finetune/dataset-catalog/files",
        data={"name": "rejected", "data_type": category},
        files={"files": ("old.json", json.dumps(LEGACY).encode())},
    )
    assert response.status_code == 422 or response.json()["status_code"] == 10129
    assert not web.objects.data


async def test_retained_local_entry_cannot_import_legacy_files(web):
    stage = await web.client.post(
        "/api/v1/finetune/job/file/preset/upload", files={"file": ("old.json", json.dumps(LEGACY).encode())}
    )
    url = stage.json()["data"]["file_path"]
    response = await web.client.post("/api/v1/finetune/job/file/preset", json={"name": "rejected", "files": url})
    assert response.json()["status_code"] == 10129
    assert all(bucket == web.objects.tmp_bucket for bucket, _ in web.objects.data)


async def test_remote_legacy_category_is_rejected_before_any_connector_call(web, monkeypatch):
    connect = MagicMock(side_effect=AssertionError("A legacy import must not connect to a source"))
    monkeypatch.setattr(module, "plan_remote_dataset", connect)
    response = await web.client.post(
        "/api/v1/finetune/dataset-catalog/import",
        json={
            "name": "rejected",
            "data_type": "legacy",
            "source": "ftp",
            "connection": {"endpoint": "ftp://files.example.com"},
            "manifest_path": "train.json",
        },
    )
    assert response.json()["status_code"] == 10129
    connect.assert_not_called()
    assert not web.objects.data


@pytest.mark.parametrize("layout", ["manifest", "zip"])
async def test_remote_text_cannot_disguise_legacy_content(web, monkeypatch, layout):
    import io
    import zipfile
    from contextlib import contextmanager
    from types import SimpleNamespace

    if layout == "manifest":
        plan = None
        records = LEGACY
    else:
        plan = {"zip": {"path": "data.zip"}}
        records = None
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("train.json", json.dumps(LEGACY))

        @contextmanager
        def reader(_request):
            yield SimpleNamespace(read=lambda _path, _limit: archive.getvalue())

        monkeypatch.setattr(module, "remote_reader", reader)
    monkeypatch.setattr(module, "plan_remote_dataset", MagicMock(return_value=(plan, records, None, {})))
    response = await web.client.post(
        "/api/v1/finetune/dataset-catalog/import",
        json={
            "name": "rejected",
            "data_type": "text",
            "source": "ftp",
            "connection": {"endpoint": "ftp://files.example.com"},
            "manifest_path": "train.json",
        },
    )
    assert response.json()["status_code"] == 10129
    assert not web.objects.data
