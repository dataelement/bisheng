from types import SimpleNamespace

import pytest

from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationBatch,
)
from bisheng.knowledge.domain.services.file_migration.state import (
    calculate_progress,
)
from bisheng.knowledge.domain.services.knowledge_migration_planner import (
    KnowledgeMigrationPlannerService,
)


class _GraphSourceRepository:
    def __init__(self, *, include_all_files: bool):
        self.include_all_files = include_all_files
        self.document = SimpleNamespace(
            id=501,
            knowledge_id=20,
            primary_version_id=702,
            lifecycle_status="active",
            file_level_path="",
            level=0,
            model_dump=lambda **_: {
                "id": 501,
                "knowledge_id": 20,
                "primary_version_id": 702,
                "lifecycle_status": "active",
                "file_level_path": "",
                "level": 0,
            },
        )
        self.versions = [
            SimpleNamespace(
                id=701,
                document_id=501,
                knowledge_file_id=1001,
                version_no=1,
                is_primary=False,
                model_dump=lambda **_: {
                    "id": 701,
                    "document_id": 501,
                    "knowledge_file_id": 1001,
                    "version_no": 1,
                    "is_primary": False,
                },
            ),
            SimpleNamespace(
                id=702,
                document_id=501,
                knowledge_file_id=1002,
                version_no=2,
                is_primary=True,
                model_dump=lambda **_: {
                    "id": 702,
                    "document_id": 501,
                    "knowledge_file_id": 1002,
                    "version_no": 2,
                    "is_primary": True,
                },
            ),
        ]
        self.files = [
            self._file(1001, "v1.pdf"),
            self._file(1002, "v2.pdf"),
        ]

    @staticmethod
    def _file(file_id: int, name: str):
        payload = {
            "id": file_id,
            "knowledge_id": 20,
            "file_name": name,
            "file_level_path": "",
            "file_type": FileType.FILE.value,
            "status": KnowledgeFileStatus.SUCCESS.value,
            "deleted_at": None,
            "object_name": f"{file_id}.pdf",
            "preview_file_object_name": None,
            "bbox_object_name": None,
            "thumbnails": None,
            "user_metadata": {},
        }
        return SimpleNamespace(
            **payload,
            model_dump=lambda **_: dict(payload),
        )

    async def find_versions_by_file_ids(self, file_ids):
        return [version for version in self.versions if version.knowledge_file_id in file_ids]

    async def find_documents_by_ids(self, document_ids):
        return [self.document] if 501 in document_ids else []

    async def find_versions_by_document_ids(self, document_ids):
        return self.versions if 501 in document_ids else []

    async def find_files_by_ids(self, file_ids):
        rows = [file for file in self.files if file.id in file_ids]
        return rows if self.include_all_files else rows[:1]

    async def find_entries_by_document_ids(self, document_ids):
        del document_ids
        return []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("include_all_files", "expected_valid"),
    [(False, False), (True, True)],
)
async def test_overwrite_context_validates_and_snapshots_full_version_graph(
    include_all_files,
    expected_valid,
):
    source_repository = _GraphSourceRepository(include_all_files=include_all_files)
    service = KnowledgeMigrationPlannerService(
        repository=SimpleNamespace(),
        source_repository=source_repository,
        preflight_inspector=SimpleNamespace(),
        dispatcher=SimpleNamespace(),
    )

    (
        file_unit_keys,
        _,
        graph_valid,
        _,
        graph_snapshots,
    ) = await service._target_conflict_context(
        [source_repository.files[-1]],
        target_space_id=20,
    )

    assert graph_valid[501] is expected_valid
    assert file_unit_keys == {
        1001: "document:501",
        1002: "document:501",
    }
    if expected_valid:
        assert {item["record"]["id"] for item in graph_snapshots["document:501"]["target_files"]} == {1001, 1002}


class _PagedPlanRepository:
    def __init__(self, batch):
        self.batch = batch
        self.units = []
        self.append_sizes = []

    async def compare_and_set_batch_status(
        self,
        batch_id,
        expected,
        target,
        **values,
    ):
        if batch_id != self.batch.id or self.batch.status not in expected:
            return False
        self.batch.status = target
        for key, value in values.items():
            setattr(self.batch, key, value)
        return True

    async def find_batch_by_id(self, batch_id):
        return self.batch if batch_id == self.batch.id else None

    async def clear_plan(self, batch_id):
        assert batch_id == self.batch.id
        self.units.clear()

    async def append_plan(self, batch_id, rows):
        assert batch_id == self.batch.id
        self.append_sizes.append(len(rows))
        self.units.extend(unit for unit, _ in rows)

    async def recompute_progress(self, batch_id):
        assert batch_id == self.batch.id
        return calculate_progress(unit.status for unit in self.units)

    async def commit(self):
        return None

    async def rollback(self):
        return None


class _PagedSourceRepository:
    def __init__(self, files):
        self.files = files
        self.page_calls = []

    async def expand_selection_page(
        self,
        selection_snapshot,
        *,
        after_id,
        limit,
    ):
        del selection_snapshot
        self.page_calls.append((after_id, limit))
        return [file for file in self.files if int(file.id) > after_id][:limit]

    async def find_spaces_by_ids(self, space_ids):
        assert space_ids == {20}
        return [SimpleNamespace(space=SimpleNamespace(model="embedding"))]

    async def find_versions_by_file_ids(self, file_ids):
        del file_ids
        return []

    async def find_documents_by_ids(self, document_ids):
        del document_ids
        return []

    async def find_versions_by_document_ids(self, document_ids):
        del document_ids
        return []

    async def find_files_by_ids(self, file_ids):
        del file_ids
        return []

    async def find_entries_by_document_ids(self, document_ids):
        del document_ids
        return []

    async def list_target_folders_page(self, *args, **kwargs):
        del args, kwargs
        return []

    async def list_target_conflict_candidates_page(
        self,
        *args,
        **kwargs,
    ):
        del args, kwargs
        return []


class _NoStorageErrors:
    async def find_storage_errors(self, files):
        assert len(files) <= 2
        return {}


class _NoopDispatcher:
    def dispatch_execution(self, batch_id, round_no):
        del batch_id, round_no
        return None


@pytest.mark.asyncio
async def test_preflight_consumes_and_persists_fixed_size_pages():
    files = [
        KnowledgeFile(
            id=file_id,
            tenant_id=1,
            knowledge_id=10,
            user_id=1,
            user_name="owner",
            updater_id=1,
            updater_name="owner",
            file_name=f"{file_id}.pdf",
            file_type=FileType.FILE.value,
            file_level_path="",
            status=KnowledgeFileStatus.SUCCESS.value,
            md5=f"md5-{file_id}",
        )
        for file_id in range(1, 6)
    ]
    batch = KnowledgeMigrationBatch(
        id=1,
        batch_no="paged-preflight",
        request_id="paged-preflight",
        operator_id=1,
        operator_name="admin",
        source_selection_snapshot=[
            {
                "space_id": 10,
                "nodes": [
                    {
                        "node_id": int(file.id),
                        "node_type": "file",
                        "file_level_path": "",
                    }
                    for file in files
                ],
            }
        ],
        source_spaces_snapshot=[{"id": 10, "name": "来源库", "model": "embedding"}],
        target_space_id=20,
        target_space_name="目标库",
    )
    repository = _PagedPlanRepository(batch)
    source_repository = _PagedSourceRepository(files)
    service = KnowledgeMigrationPlannerService(
        repository=repository,
        source_repository=source_repository,
        preflight_inspector=_NoStorageErrors(),
        dispatcher=_NoopDispatcher(),
        page_size=2,
    )

    await service.run_preflight(1)

    assert source_repository.page_calls == [(0, 2), (2, 2), (4, 2)]
    assert repository.append_sizes == [2, 2, 1]
    assert len(repository.units) == 5
    assert batch.scanned_count == 5
    assert batch.status == "queued"
