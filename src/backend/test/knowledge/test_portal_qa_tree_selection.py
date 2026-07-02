from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core import database as core_database
from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
from bisheng.knowledge.domain.services import knowledge_space_service as svc_mod


def _file(
    file_id: int,
    space_id: int = 7101,
    *,
    folder: bool = False,
    path: str = '',
    status: int = KnowledgeFileStatus.SUCCESS.value,
):
    item = SimpleNamespace(
        id=file_id,
        knowledge_id=space_id,
        file_type=FileType.DIR.value if folder else FileType.FILE.value,
        status=status,
        file_level_path=path,
        file_name=f"{'folder' if folder else 'file'}-{file_id}.md",
    )
    item.model_dump = lambda: {
        'id': item.id,
        'knowledge_id': item.knowledge_id,
        'file_type': item.file_type,
        'status': item.status,
        'file_level_path': item.file_level_path,
        'file_name': item.file_name,
    }
    return item


@pytest.mark.asyncio
async def test_resolve_qa_scope_file_ids_expands_folders_and_dedupes(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, user_name='tester')
    service.version_repo = None

    records = {
        3001: _file(3001, folder=True, path=''),
        9001: _file(9001),
        9002: _file(9002, path='/3001'),
    }

    async def _query_by_id(file_id):
        return records.get(file_id)

    async def _children_by_prefix(_space_id, prefix, file_status=None):
        assert prefix == '/3001'
        assert file_status == KnowledgeFileStatus.SUCCESS
        return [records[9001], records[9002]]

    monkeypatch.setattr(service, '_require_read_permission', AsyncMock())
    monkeypatch.setattr(service, '_require_permission_id', AsyncMock())
    monkeypatch.setattr(service, '_filter_visible_child_items', AsyncMock(side_effect=lambda items, **_kwargs: items))
    monkeypatch.setattr(svc_mod.KnowledgeFileDao, 'query_by_id', _query_by_id)
    monkeypatch.setattr(svc_mod.SpaceFileDao, 'get_children_by_prefix', _children_by_prefix)

    result = await service.resolve_qa_scope_file_ids(
        folder_refs=[SimpleNamespace(knowledge_space_id=7101, folder_id=3001)],
        file_refs=[SimpleNamespace(knowledge_space_id=7101, file_id=9001)],
        max_files=20,
    )

    assert result == {7101: [9001, 9002]}
    service._require_permission_id.assert_any_await('folder', 3001, 'view_folder', space_id=7101)
    service._require_permission_id.assert_any_await('knowledge_file', 9001, 'view_file', space_id=7101)


@pytest.mark.asyncio
async def test_resolve_qa_scope_file_ids_rejects_more_than_twenty_files(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, user_name='tester')
    service.version_repo = None
    folder = _file(3001, folder=True, path='')
    files = [_file(9100 + idx, path='/3001') for idx in range(21)]

    async def _query_by_id(file_id):
        return folder if file_id == 3001 else None

    async def _children_by_prefix(_space_id, _prefix, file_status=None):
        return files

    monkeypatch.setattr(service, '_require_read_permission', AsyncMock())
    monkeypatch.setattr(service, '_require_permission_id', AsyncMock())
    monkeypatch.setattr(service, '_filter_visible_child_items', AsyncMock(side_effect=lambda items, **_kwargs: items))
    monkeypatch.setattr(svc_mod.KnowledgeFileDao, 'query_by_id', _query_by_id)
    monkeypatch.setattr(svc_mod.SpaceFileDao, 'get_children_by_prefix', _children_by_prefix)

    with pytest.raises(ValueError, match='一次最多可选择20个文件进行问答。'):
        await service.resolve_qa_scope_file_ids(
            folder_refs=[SimpleNamespace(knowledge_space_id=7101, folder_id=3001)],
            file_refs=[],
            max_files=20,
        )


@pytest.mark.asyncio
async def test_folder_extra_info_uses_visible_success_file_count(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    folder = _file(3001, folder=True, path='')
    visible_file = _file(9001, path='/3001')
    hidden_file = _file(9002, path='/3001')

    class _ExecResult:
        def all(self):
            return [(KnowledgeFileStatus.SUCCESS.value, 2)]

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def exec(self, _statement):
            return _ExecResult()

    async def _children_by_prefix(space_id, prefix, file_status=None):
        assert space_id == 7101
        assert prefix == '/3001'
        assert file_status == KnowledgeFileStatus.SUCCESS
        return [visible_file, hidden_file]

    monkeypatch.setattr(core_database, 'get_async_db_session', lambda: _Session())
    monkeypatch.setattr(svc_mod, 'get_async_db_session', lambda: _Session())
    monkeypatch.setattr(svc_mod.SpaceFileDao, 'get_children_by_prefix', _children_by_prefix)
    monkeypatch.setattr(service, '_build_child_permission_context', AsyncMock(return_value={}))
    monkeypatch.setattr(service, '_filter_visible_child_items', AsyncMock(return_value=[visible_file]))

    result = await service._handle_file_folder_extra_info([folder])

    assert result[0]['success_file_num'] == 2
    assert result[0]['visible_success_file_num'] == 1


@pytest.mark.asyncio
async def test_get_space_folder_stats_returns_counts_in_request_order(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, user_name='tester')

    folder_a = _file(3001, folder=True, path='')
    folder_b = _file(3002, folder=True, path='')

    async def _get_files_by_ids(file_ids):
        assert file_ids == [3002, 3001]
        return [folder_a, folder_b]

    monkeypatch.setattr(service, '_require_read_permission', AsyncMock())
    monkeypatch.setattr(service, '_require_resource_permission', AsyncMock())
    monkeypatch.setattr(
        service,
        '_load_folder_stat_counts',
        AsyncMock(return_value={
            3001: {
                'file_num': 7,
                'success_file_num': 5,
                'visible_success_file_num': 4,
                'processing_file_num': 1,
            },
            3002: {
                'file_num': 3,
                'success_file_num': 2,
                'visible_success_file_num': 2,
                'processing_file_num': 0,
            },
        }),
    )
    monkeypatch.setattr(svc_mod.KnowledgeFileDao, 'aget_file_by_ids', staticmethod(_get_files_by_ids))

    result = await service.get_space_folder_stats(7101, [3002, 3001, 3002])

    assert result == {
        'stats': [
            {
                'folder_id': 3002,
                'file_num': 3,
                'success_file_num': 2,
                'visible_success_file_num': 2,
                'processing_file_num': 0,
            },
            {
                'folder_id': 3001,
                'file_num': 7,
                'success_file_num': 5,
                'visible_success_file_num': 4,
                'processing_file_num': 1,
            },
        ]
    }
    service._require_read_permission.assert_awaited_once_with(7101)
    service._require_resource_permission.assert_any_await('can_read', 'folder', 3001)
    service._require_resource_permission.assert_any_await('can_read', 'folder', 3002)


@pytest.mark.asyncio
async def test_get_space_folder_stats_applies_filters(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    service.login_user = SimpleNamespace(user_id=7, user_name='tester')

    space = SimpleNamespace(id=7101, index_name='idx')
    folder = _file(3001, folder=True, path='')

    async def _get_files_by_ids(file_ids):
        assert file_ids == [3001]
        return [folder]

    monkeypatch.setattr(service, '_require_read_permission', AsyncMock(return_value=space))
    monkeypatch.setattr(service, '_require_resource_permission', AsyncMock())
    monkeypatch.setattr(
        service,
        '_load_filtered_folder_stat_counts',
        AsyncMock(return_value={
            3001: {
                'file_num': 2,
                'success_file_num': 1,
                'visible_success_file_num': 1,
                'processing_file_num': 1,
            },
        }),
    )
    monkeypatch.setattr(service, '_load_folder_stat_counts', AsyncMock())
    monkeypatch.setattr(svc_mod.KnowledgeFileDao, 'aget_file_by_ids', staticmethod(_get_files_by_ids))

    result = await service.get_space_folder_stats(
        7101,
        [3001],
        file_status=[KnowledgeFileStatus.SUCCESS.value, KnowledgeFileStatus.WAITING.value],
        keyword='制度',
        tag_ids=[11],
    )

    assert result == {
        'stats': [
            {
                'folder_id': 3001,
                'file_num': 2,
                'success_file_num': 1,
                'visible_success_file_num': 1,
                'processing_file_num': 1,
            },
        ]
    }
    service._load_filtered_folder_stat_counts.assert_awaited_once_with(
        space=space,
        folders=[folder],
        file_status=[KnowledgeFileStatus.SUCCESS.value, KnowledgeFileStatus.WAITING.value],
        keyword='制度',
        tag_ids=[11],
    )
    service._load_folder_stat_counts.assert_not_called()


@pytest.mark.asyncio
async def test_load_filtered_folder_stat_counts_aggregates_descendant_files(monkeypatch):
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    service.version_repo = None
    space = SimpleNamespace(id=7101, index_name='idx')
    folder = _file(3001, folder=True, path='')
    visible_success = _file(9001, path='/3001')
    waiting = _file(9002, path='/3001/sub', status=KnowledgeFileStatus.WAITING.value)
    outside = _file(9003, path='', status=KnowledgeFileStatus.SUCCESS.value)
    captured = {}

    async def _aget_file_by_filters(*args, **kwargs):
        captured['args'] = args
        captured['kwargs'] = kwargs
        return [visible_success, waiting, outside]

    monkeypatch.setattr(service, '_resolve_folder_stats_tag_file_ids', AsyncMock(return_value=[9001, 9002]))
    monkeypatch.setattr(service, '_resolve_folder_stats_keyword_file_ids', AsyncMock(return_value=[9001]))
    monkeypatch.setattr(service, '_build_child_permission_context', AsyncMock(return_value={}))
    monkeypatch.setattr(service, '_filter_visible_child_items', AsyncMock(return_value=[visible_success]))
    monkeypatch.setattr(svc_mod.KnowledgeFileDao, 'aget_file_by_filters', staticmethod(_aget_file_by_filters))

    result = await service._load_filtered_folder_stat_counts(
        space=space,
        folders=[folder],
        file_status=[KnowledgeFileStatus.SUCCESS.value, KnowledgeFileStatus.WAITING.value],
        keyword='制度',
        tag_ids=[11],
    )

    assert result[3001] == {
        'file_num': 2,
        'success_file_num': 1,
        'visible_success_file_num': 1,
        'processing_file_num': 1,
    }
    assert captured['args'][0] == 7101
    assert captured['kwargs']['file_name'] == '制度'
    assert captured['kwargs']['status'] == [
        KnowledgeFileStatus.SUCCESS.value,
        KnowledgeFileStatus.WAITING.value,
    ]
    assert captured['kwargs']['file_ids'] == [9001, 9002]
    assert captured['kwargs']['extra_file_ids'] == [9001]
    assert captured['kwargs']['file_type'] == FileType.FILE.value


@pytest.mark.asyncio
async def test_handle_file_folder_extra_info_can_skip_folder_counts():
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    folder = _file(3001, folder=True, path='')

    result = await service._handle_file_folder_extra_info([folder], include_folder_counts=False)

    assert result[0]['summary'] == ''
    assert 'file_num' not in result[0]
    assert 'success_file_num' not in result[0]
    assert 'visible_success_file_num' not in result[0]
    assert 'processing_file_num' not in result[0]


@pytest.mark.asyncio
async def test_handle_file_folder_extra_info_uses_folder_count_override():
    service = object.__new__(svc_mod.KnowledgeSpaceService)
    folder = _file(3001, folder=True, path='')

    result = await service._handle_file_folder_extra_info(
        [folder],
        folder_counts_override={
            3001: {
                'file_num': 2,
                'success_file_num': 1,
                'visible_success_file_num': 1,
                'processing_file_num': 1,
            },
        },
    )

    assert result[0]['file_num'] == 2
    assert result[0]['success_file_num'] == 1
    assert result[0]['visible_success_file_num'] == 1
    assert result[0]['processing_file_num'] == 1
