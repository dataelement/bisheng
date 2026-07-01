import json
import importlib.util
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from bisheng.api.v1.schemas import KnowledgeFileProcess
from bisheng.common.errcode.knowledge import KnowledgeFileTagLimitError
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.schemas.knowledge_space_schema import FileCreateReq
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from test.test_knowledge_space_service import (
    _load_service_class,
    _make_file,
    _make_login_user,
    _make_space,
)


def _load_knowledge_utils(monkeypatch):
    base_module = ModuleType("bisheng.common.services.base")

    class BaseService:
        pass

    base_module.BaseService = BaseService
    monkeypatch.setitem(sys.modules, "bisheng.common.services.base", base_module)

    module_path = (
        Path(__file__).resolve().parents[2]
        / "bisheng/knowledge/domain/services/knowledge_utils.py"
    )
    spec = importlib.util.spec_from_file_location(
        "knowledge_utils_upload_domain_tags_under_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.KnowledgeUtils


def _process_payload(**overrides):
    payload = {
        "knowledge_id": 7,
        "file_list": [{"file_path": "/tmp/a.txt"}],
    }
    payload.update(overrides)
    return payload


def test_upload_process_accepts_optional_business_domain_code():
    req = KnowledgeFileProcess(**_process_payload(business_domain_code=" pp "))

    assert req.business_domain_code == "PP"


def test_upload_process_rejects_invalid_business_domain_code():
    with pytest.raises(ValueError, match="business_domain_code"):
        KnowledgeFileProcess(**_process_payload(business_domain_code="OT"))


def test_upload_process_keeps_old_payload_compatible():
    req = KnowledgeFileProcess(**_process_payload())

    assert req.business_domain_code is None
    assert req.manual_tag_ids == []
    assert req.manual_tag_names == []


def test_space_file_create_req_accepts_upload_metadata():
    req = FileCreateReq(
        file_path=["/tmp/a.txt"],
        business_domain_code=" pp ",
        manual_tag_ids=[1],
        manual_tag_names=["制度"],
    )

    assert req.business_domain_code == "PP"
    assert req.manual_tag_ids == [1]
    assert req.manual_tag_names == ["制度"]


def test_space_file_create_req_keeps_old_payload_compatible():
    req = FileCreateReq(file_path=["/tmp/a.txt"])

    assert req.business_domain_code is None
    assert req.manual_tag_ids == []
    assert req.manual_tag_names == []


def test_space_file_create_req_rejects_invalid_business_domain_code():
    with pytest.raises(ValueError, match="business_domain_code"):
        FileCreateReq(file_path=["/tmp/a.txt"], business_domain_code="OT")


def test_business_domain_split_rule_helpers(monkeypatch):
    KnowledgeUtils = _load_knowledge_utils(monkeypatch)
    split_rule = KnowledgeUtils.with_business_domain_code_in_split_rule(
        {"chunk_size": 1000},
        " it ",
    )

    assert json.loads(split_rule)["business_domain_code"] == "IT"
    assert KnowledgeUtils.get_business_domain_code_from_split_rule(split_rule) == "IT"
    assert KnowledgeUtils.get_business_domain_code_from_split_rule({"business_domain_code": "bad"}) is None
    assert KnowledgeUtils.with_business_domain_code_in_split_rule({"chunk_size": 1000}, None) == json.dumps(
        {"chunk_size": 1000},
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_manual_upload_tags_resolve_create_link_and_mark_files(monkeypatch):
    knowledge = Knowledge(
        id=7,
        tenant_id=3,
        user_id=2,
        name="space",
        type=KnowledgeTypeEnum.SPACE.value,
    )
    login_user = SimpleNamespace(user_id=9, user_name="tester")
    files = [
        KnowledgeFile(id=11, knowledge_id=7, file_name="a.txt", tenant_id=3),
        KnowledgeFile(id=12, knowledge_id=7, file_name="b.txt", tenant_id=3),
    ]
    existing_by_id = Tag(
        id=1,
        name="已有",
        business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
        business_id="7",
    )
    existing_by_name = Tag(
        id=2,
        name="制度",
        business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
        business_id="7",
    )
    created_tag = Tag(
        id=3,
        name="安全",
        business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE,
        business_id="7",
    )
    linked = []
    updated_files = []

    async def fake_insert(tag):
        assert tag.name == "安全"
        assert tag.business_type == TagBusinessTypeEnum.KNOWLEDGE_SPACE
        assert tag.business_id == "7"
        return created_tag

    async def fake_add_tags(tag_ids, resource_id, resource_type, user_id):
        linked.append((tag_ids, resource_id, resource_type, user_id))
        return True

    async def fake_update(file):
        updated_files.append(file)
        return file

    async def fake_get_tags_by_ids(tag_ids):
        return [existing_by_id]

    async def fake_get_tags_by_business(**kwargs):
        return [existing_by_id, existing_by_name]

    monkeypatch.setattr("bisheng.database.models.tag.TagDao.aget_tags_by_ids", fake_get_tags_by_ids)
    monkeypatch.setattr("bisheng.database.models.tag.TagDao.get_tags_by_business", fake_get_tags_by_business)
    monkeypatch.setattr("bisheng.database.models.tag.TagDao.ainsert_tag", fake_insert)
    monkeypatch.setattr("bisheng.database.models.tag.TagDao.add_tags", fake_add_tags)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.async_update",
        fake_update,
    )

    applied_ids = await KnowledgeService.apply_manual_upload_tags(
        login_user=login_user,
        knowledge=knowledge,
        files=files,
        manual_tag_ids=[1],
        manual_tag_names=["制度", "安全", ""],
    )

    assert applied_ids == [1, 2, 3]
    assert linked == [
        ([1, 2, 3], "11", ResourceTypeEnum.SPACE_FILE, 9),
        ([1, 2, 3], "12", ResourceTypeEnum.SPACE_FILE, 9),
    ]
    assert len(updated_files) == 2
    assert all(
        file.user_metadata["manual_upload_tags_applied"] is True
        for file in updated_files
    )


@pytest.mark.asyncio
async def test_manual_upload_tags_enforce_file_tag_limit():
    knowledge = Knowledge(id=7, name="kb", type=KnowledgeTypeEnum.NORMAL.value)
    with pytest.raises(KnowledgeFileTagLimitError):
        await KnowledgeService.apply_manual_upload_tags(
            login_user=SimpleNamespace(user_id=9),
            knowledge=knowledge,
            files=[KnowledgeFile(id=11, knowledge_id=7, file_name="a.txt")],
            manual_tag_ids=[],
            manual_tag_names=["A", "B", "C", "D", "E", "F"],
        )


def test_sync_process_knowledge_file_applies_manual_upload_tags(monkeypatch):
    knowledge = Knowledge(id=7, name="kb", type=KnowledgeTypeEnum.NORMAL.value)
    login_user = SimpleNamespace(user_id=9, user_name="tester")
    process_files = [KnowledgeFile(id=11, knowledge_id=7, file_name="a.txt")]
    req = KnowledgeFileProcess(
        knowledge_id=7,
        file_list=[{"file_path": "/tmp/a.txt"}],
        manual_tag_ids=[1],
        manual_tag_names=["制度"],
    )
    calls = []

    def fake_save_knowledge_file(*args, **kwargs):
        return knowledge, [], process_files, ["preview-key"]

    def fake_process_file_task(**kwargs):
        return None

    def fake_apply_manual_upload_tags(**kwargs):
        calls.append(kwargs)
        return [1, 2]

    monkeypatch.setattr(KnowledgeService, "save_knowledge_file", fake_save_knowledge_file)
    monkeypatch.setattr(KnowledgeService, "upload_knowledge_file_hook", Mock())
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.knowledge_file.KnowledgeFileDao.select_list",
        lambda file_ids: process_files,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.process_file_task",
        fake_process_file_task,
    )
    monkeypatch.setattr(KnowledgeService, "apply_manual_upload_tags_sync", fake_apply_manual_upload_tags)

    result = KnowledgeService.sync_process_knowledge_file(
        request=Mock(),
        login_user=login_user,
        req_data=req,
    )

    assert result == process_files
    assert calls == [{
        "login_user": login_user,
        "knowledge": knowledge,
        "files": process_files,
        "manual_tag_ids": [1],
        "manual_tag_names": ["制度"],
    }]


@pytest.mark.asyncio
async def test_space_add_file_persists_upload_metadata(monkeypatch):
    KnowledgeUtils = _load_knowledge_utils(monkeypatch)
    KnowledgeSpaceService = _load_service_class()
    login_user = _make_login_user(user_id=9, user_name="tester")
    service = KnowledgeSpaceService(None, login_user)
    service.normalize_file_category_code = KnowledgeUtils.normalize_file_category_code
    service.normalize_business_domain_code = KnowledgeUtils.normalize_business_domain_code
    service.file_category_code_key = KnowledgeUtils.file_category_code_key
    service.business_domain_code_key = KnowledgeUtils.business_domain_code_key
    space = _make_space(space_id=7)
    added_file = _make_file(
        file_id=42,
        knowledge_id=7,
        file_name="report.pdf",
        status=KnowledgeFileStatus.SUCCESS.value,
    )
    added_file.file_size = 100
    captured_split_rules = []
    tag_calls = []

    class FakeSession:
        def add(self, _obj):
            return None

        async def flush(self):
            return None

        async def commit(self):
            return None

    @asynccontextmanager
    async def fake_session_ctx():
        yield FakeSession()

    def fake_process_one_file(*args, **kwargs):
        captured_split_rules.append(kwargs["split_rule"])
        return added_file

    async def fake_apply_manual_upload_tags(**kwargs):
        tag_calls.append(kwargs)
        return [1]

    with patch.object(
        service, "_require_permission_id", new_callable=AsyncMock,
    ), patch.object(
        service, "_check_filename_sensitive_words",
        return_value=None,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
        new_callable=AsyncMock,
        return_value=space,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size",
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_tenant_storage_remaining_bytes",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file",
        side_effect=fake_process_one_file,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.apply_manual_upload_tags",
        side_effect=fake_apply_manual_upload_tags,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
        new_callable=AsyncMock,
    ), patch.object(
        service, "update_folder_update_time", new_callable=AsyncMock,
    ), patch.object(
        service, "_initialize_child_resource_permissions", new_callable=AsyncMock,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        new=fake_session_ctx,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.file_worker.parse_knowledge_file_celery",
        new_callable=MagicMock,
    ) as mock_celery:
        mock_celery.delay = MagicMock()

        result = await service.add_file(
            7,
            ["/tmp/report.pdf"],
            file_category_code="RPT",
            business_domain_code="PP",
            manual_tag_ids=[1],
            manual_tag_names=["制度"],
        )

    assert result == [added_file]
    assert captured_split_rules[0]["file_category_code"] == "RPT"
    assert captured_split_rules[0]["business_domain_code"] == "PP"
    assert tag_calls == [{
        "login_user": login_user,
        "knowledge": space,
        "files": [added_file],
        "manual_tag_ids": [1],
        "manual_tag_names": ["制度"],
    }]


@pytest.mark.asyncio
async def test_retry_space_files_preserves_upload_metadata(monkeypatch):
    KnowledgeUtils = _load_knowledge_utils(monkeypatch)
    KnowledgeSpaceService = _load_service_class()
    login_user = _make_login_user(user_id=9, user_name="tester")
    service = KnowledgeSpaceService(None, login_user)
    service.normalize_file_category_code = KnowledgeUtils.normalize_file_category_code
    service.normalize_business_domain_code = KnowledgeUtils.normalize_business_domain_code
    service.with_file_category_code_in_split_rule = KnowledgeUtils.with_file_category_code_in_split_rule
    service.with_business_domain_code_in_split_rule = KnowledgeUtils.with_business_domain_code_in_split_rule
    space = _make_space(space_id=7)
    db_file = _make_file(file_id=42, knowledge_id=7, file_name="report.pdf")
    retry_input = {
        "id": 42,
        "split_rule": json.dumps({"chunk_size": 1000}),
    }
    tag_calls = []
    process_calls = []

    async def fake_process_retry_files(db_files, id2input, login_user_arg):
        process_calls.append((db_files, id2input, login_user_arg))
        return [db_file], {""}

    async def fake_apply_manual_upload_tags(**kwargs):
        tag_calls.append(kwargs)
        return [1]

    with patch.object(
        service, "_require_read_permission", new_callable=AsyncMock,
    ), patch.object(
        service, "_require_resource_permission", new_callable=AsyncMock,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
        new_callable=AsyncMock,
        return_value=space,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_file_by_ids",
        new_callable=AsyncMock,
        return_value=[db_file],
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.apply_manual_upload_tags",
        side_effect=fake_apply_manual_upload_tags,
    ), patch.object(
        service,
        "process_retry_files",
        side_effect=fake_process_retry_files,
    ), patch.object(
        service,
        "update_folder_update_time",
        new_callable=AsyncMock,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceContentStat.enqueue_file_stat_async",
        new_callable=AsyncMock,
    ), patch(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
        new_callable=AsyncMock,
    ):
        await service.retry_space_files(
            7,
            {
                "file_objs": [retry_input],
                "file_category_code": "RPT",
                "business_domain_code": "PP",
                "manual_tag_ids": [1],
                "manual_tag_names": ["制度"],
            },
        )

    split_rule = json.loads(retry_input["split_rule"])
    assert split_rule["file_category_code"] == "RPT"
    assert split_rule["business_domain_code"] == "PP"
    assert process_calls[0][2] == login_user
    assert tag_calls == [{
        "login_user": login_user,
        "knowledge": space,
        "files": [db_file],
        "manual_tag_ids": [1],
        "manual_tag_names": ["制度"],
    }]
