"""Legacy process must use the real SPACE registration and whole-batch lifecycle."""

import json
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from bisheng.api.v1.schemas import KnowledgeFileProcess
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from test.knowledge_unification import test_kn_upload as native

store = native.store
tenant = native.tenant
business = native.business
admission = native.admission
processing = native.processing
application = native.application
files = native.files
legacy = native.legacy
upload = native.upload


async def rows(case):
    async with case.context.sessions() as session:
        result = []
        for model in (KnowledgeFile, KnowledgeDocument, KnowledgeDocumentVersion):
            result.append(tuple((await session.execute(select(model.__table__).order_by(model.id))).mappings()))
        return tuple(result)


def request():
    return KnowledgeFileProcess.model_validate(
        {
            "knowledge_id": 40,
            "callback_url": "https://consumer.invalid/parsed",
            "excel_rule": {"slice_length": 22},
            "file_list": [
                {"file_path": "opaque-document"},
                {"file_path": "opaque-table", "excel_rule": {"header_start_row": 2, "header_end_row": 3}},
            ],
        }
    )


async def test_native_legacy_batch_rules_callback_and_version_closure(upload):
    req = request()
    accepted = await upload.service.add_file(
        40,
        [one.file_path for one in req.file_list],
        callback_url=req.callback_url,
        _legacy_inputs=tuple(req.file_list),
        _legacy_request=req,
        skip_dedup=True,
    )
    assert len(accepted) == 2 and upload.publish.call_count == 2
    assert {call.kwargs["callback_url"] for call in upload.publish.call_args_list} == {req.callback_url}
    table = json.loads(accepted[1].split_rule)["excel_rule"]
    assert table["slice_length"] == 22 and table["header_start_row"] == 2 and table["header_end_row"] == 3
    async with upload.context.sessions() as session:
        for row in accepted:
            version = (
                await session.execute(
                    select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.knowledge_file_id == row.id)
                )
            ).scalar_one()
            document = await session.get(KnowledgeDocument, version.document_id)
            assert document.knowledge_id == 40 and document.primary_version_id == version.id


@pytest.mark.parametrize("fault", ["unpaired", "root", "path", "overrides", "deferred_callback"])
async def test_legacy_pair_rejected_before_storage_or_sql_changes(upload, fault):
    req = request()
    before = await rows(upload)
    kwargs = dict(callback_url=req.callback_url, _legacy_inputs=tuple(req.file_list), _legacy_request=req)
    if fault == "unpaired":
        kwargs["_legacy_request"] = None
    elif fault == "root":
        req.knowledge_id = 41
    elif fault == "path":
        req.file_list[0].file_path = "foreign"
    elif fault == "overrides":
        kwargs["processing_overrides"] = {"document": {"chunk_size": 33}}
    else:
        from bisheng.knowledge.domain.services.knowledge_space_service import _UploadDispatchBatch

        kwargs.update(_application=upload.service.upload_application_factory(), _deferred=_UploadDispatchBatch())
    with pytest.raises(ValueError):
        await upload.service.add_file(40, ["opaque-document", "opaque-table"], **kwargs)
    upload.publish.assert_not_called()
    upload.legacy.storage.put_object_sync.assert_not_called()
    assert await rows(upload) == before


async def test_later_fatal_file_compensates_actual_earlier_registration_without_dispatch(upload, monkeypatch):
    before = await rows(upload)
    original = upload.legacy.cls.prepare_one_file
    calls = 0

    def prepare(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second input failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(upload.legacy.cls, "prepare_one_file", prepare)
    req = request()
    with pytest.raises(OSError, match="second input"):
        await upload.service.add_file(
            40,
            [one.file_path for one in req.file_list],
            callback_url=req.callback_url,
            _legacy_inputs=tuple(req.file_list),
            _legacy_request=req,
        )
    upload.publish.assert_not_called()
    assert await rows(upload) == before


async def test_actual_old_process_never_calls_flat_file_writer(upload, monkeypatch):
    from bisheng.knowledge.application import legacy_files

    monkeypatch.setattr(legacy_files, "make_legacy_space_service", lambda _request, _user: upload.service)
    cls = upload.legacy.cls
    monkeypatch.setattr(cls, "asave_knowledge_file", AsyncMock(side_effect=AssertionError("flat file writer")))
    monkeypatch.setattr(cls, "upload_knowledge_file_hook", Mock())
    accepted = await cls.aprocess_knowledge_file(None, upload.context.user, None, request())
    assert len(accepted) == 2 and upload.publish.call_count == 2
