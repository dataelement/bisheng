from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from bisheng.open_endpoints.domain.services import (
    filelib_retrieve_source_service as source_service_mod,
)
from bisheng.open_endpoints.domain.services.filelib_retrieve_source_service import (
    EMPTY_RETRIEVE_SOURCE_LINK,
    FilelibRetrieveSourceService,
    RetrieveSourceLink,
    RetrieveSourceRef,
)


@pytest.fixture(autouse=True)
def _restore_source_object_resolution(monkeypatch) -> None:
    def resolve_source_object_name(
        cls,
        file_id: int,
        file_name: str,
        object_name: str | None = None,
    ) -> str | None:
        if object_name:
            return object_name
        if not file_name:
            return None
        return f"original/{file_id}.{file_name.rsplit('.', 1)[-1]}"

    monkeypatch.setattr(
        source_service_mod.KnowledgeUtils,
        "resolve_source_object_name",
        classmethod(resolve_source_object_name),
    )


def _file(
    file_id: int,
    *,
    file_name: str = "report.pdf",
    object_name: str | None = None,
):
    return SimpleNamespace(
        id=file_id,
        file_name=file_name,
        object_name=object_name,
    )


def _storage() -> MagicMock:
    storage = MagicMock()
    storage.bucket = "public"
    storage.object_exists = AsyncMock(return_value=True)
    storage.get_share_link = AsyncMock()
    storage.clear_minio_share_host.side_effect = lambda value: value.replace(
        "https://files.example.com",
        "",
        1,
    )
    return storage


def _version_repository() -> MagicMock:
    repository = MagicMock()
    repository.find_by_ids = AsyncMock(return_value=[])
    return repository


async def test_resolve_links_batches_deduplicates_and_reuses_one_signature_per_file() -> None:
    repository = MagicMock()
    repository.find_by_ids = AsyncMock(
        return_value=[
            _file(11, object_name="persisted/original-report.pdf"),
            _file(12, file_name="legacy.docx"),
        ]
    )
    storage = _storage()
    storage.get_share_link.side_effect = [
        "https://files.example.com/public/original/12.docx?X-Amz-Signature=AAA",
        "https://files.example.com/public/persisted/original-report.pdf?X-Amz-Signature=BBB",
    ]
    service = FilelibRetrieveSourceService(
        repository,
        storage,
        version_repository=_version_repository(),
    )

    result = await service.resolve_links([12, 11, 12, None, 0, -1, True])

    repository.find_by_ids.assert_awaited_once_with([12, 11])
    assert storage.object_exists.await_args_list == [
        call(bucket_name="public", object_name="original/12.docx"),
        call(bucket_name="public", object_name="persisted/original-report.pdf"),
    ]
    assert storage.get_share_link.await_args_list == [
        call("original/12.docx", clear_host=False, expire_days=7),
        call("persisted/original-report.pdf", clear_host=False, expire_days=7),
    ]
    assert result == {
        12: RetrieveSourceLink(
            source_url="/public/original/12.docx?X-Amz-Signature=AAA",
            source_full_url=("https://files.example.com/public/original/12.docx?X-Amz-Signature=AAA"),
        ),
        11: RetrieveSourceLink(
            source_url="/public/persisted/original-report.pdf?X-Amz-Signature=BBB",
            source_full_url=("https://files.example.com/public/persisted/original-report.pdf?X-Amz-Signature=BBB"),
        ),
    }


async def test_resolve_links_uses_canonical_version_file_for_authorized_share_entries() -> None:
    entries = [
        SimpleNamespace(
            id=entry_id,
            file_name="shared.xlsx",
            object_name=None,
            reference_document_id=2694,
            allow_download=False,
        )
        for entry_id in (3058, 3059)
    ]
    manager = SimpleNamespace(
        id=3040,
        file_name="shared.xlsx",
        object_name="original/3040.xlsx",
        reference_document_id=2694,
    )
    version = SimpleNamespace(
        id=2702,
        document_id=2694,
        knowledge_file_id=3040,
    )
    repository = MagicMock()
    repository.find_by_ids = AsyncMock(side_effect=[entries, [manager]])
    version_repository = MagicMock()
    version_repository.find_by_ids = AsyncMock(return_value=[version])
    storage = _storage()
    storage.get_share_link.return_value = (
        "https://files.example.com/public/original/3040.xlsx?X-Amz-Signature=AAA"
    )
    service = FilelibRetrieveSourceService(
        repository,
        storage,
        version_repository=version_repository,
    )

    result = await service.resolve_links(
        [
            RetrieveSourceRef(
                entry_file_id=3058,
                canonical_document_id=2694,
                canonical_version_id=2702,
            ),
            RetrieveSourceRef(
                entry_file_id=3059,
                canonical_document_id=2694,
                canonical_version_id=2702,
            ),
        ]
    )

    expected_link = RetrieveSourceLink(
        source_url="/public/original/3040.xlsx?X-Amz-Signature=AAA",
        source_full_url=(
            "https://files.example.com/public/original/3040.xlsx"
            "?X-Amz-Signature=AAA"
        ),
    )
    assert result == {3058: expected_link, 3059: expected_link}
    assert repository.find_by_ids.await_args_list == [
        call([3058, 3059]),
        call([3040]),
    ]
    version_repository.find_by_ids.assert_awaited_once_with([2702])
    storage.object_exists.assert_awaited_once_with(
        bucket_name="public",
        object_name="original/3040.xlsx",
    )
    storage.get_share_link.assert_awaited_once_with(
        "original/3040.xlsx",
        clear_host=False,
        expire_days=7,
    )


async def test_resolve_links_rejects_mismatched_canonical_document() -> None:
    entry = SimpleNamespace(
        id=3058,
        file_name="shared.xlsx",
        object_name=None,
        reference_document_id=2694,
    )
    repository = MagicMock()
    repository.find_by_ids = AsyncMock(return_value=[entry])
    version_repository = MagicMock()
    version_repository.find_by_ids = AsyncMock()
    storage = _storage()
    service = FilelibRetrieveSourceService(
        repository,
        storage,
        version_repository=version_repository,
    )

    result = await service.resolve_links(
        [
            RetrieveSourceRef(
                entry_file_id=3058,
                canonical_document_id=9999,
                canonical_version_id=2702,
            )
        ]
    )

    assert result == {3058: EMPTY_RETRIEVE_SOURCE_LINK}
    version_repository.find_by_ids.assert_not_awaited()
    storage.object_exists.assert_not_awaited()
    storage.get_share_link.assert_not_awaited()


async def test_resolve_links_keeps_empty_values_for_missing_rows_paths_and_objects() -> None:
    repository = MagicMock()
    repository.find_by_ids = AsyncMock(
        return_value=[
            _file(11, file_name="", object_name=None),
            _file(13, object_name="missing/original.pdf"),
        ]
    )
    storage = _storage()
    storage.object_exists.return_value = False
    service = FilelibRetrieveSourceService(
        repository,
        storage,
        version_repository=_version_repository(),
    )

    result = await service.resolve_links([11, 12, 13])

    assert result == {
        11: EMPTY_RETRIEVE_SOURCE_LINK,
        12: EMPTY_RETRIEVE_SOURCE_LINK,
        13: EMPTY_RETRIEVE_SOURCE_LINK,
    }
    storage.object_exists.assert_awaited_once_with(
        bucket_name="public",
        object_name="missing/original.pdf",
    )
    storage.get_share_link.assert_not_awaited()


@pytest.mark.parametrize("failure_stage", ["exists", "sign"])
async def test_resolve_links_degrades_non_missing_storage_errors_to_empty_links(
    failure_stage: str,
    caplog,
) -> None:
    repository = MagicMock()
    repository.find_by_ids = AsyncMock(return_value=[_file(11, object_name="original/secret.pdf")])
    storage = _storage()
    sensitive_url = "https://files.example.com/public/original/secret.pdf?X-Amz-Signature=SECRET"
    if failure_stage == "exists":
        storage.object_exists.side_effect = RuntimeError("storage unavailable")
    else:
        storage.get_share_link.side_effect = RuntimeError("signing unavailable")
    service = FilelibRetrieveSourceService(
        repository,
        storage,
        version_repository=_version_repository(),
    )

    result = await service.resolve_links([11])

    assert result == {11: EMPTY_RETRIEVE_SOURCE_LINK}
    assert sensitive_url not in caplog.text


async def test_resolve_links_skips_repository_for_empty_input() -> None:
    repository = MagicMock()
    repository.find_by_ids = AsyncMock()
    storage = _storage()
    service = FilelibRetrieveSourceService(
        repository,
        storage,
        version_repository=_version_repository(),
    )

    assert await service.resolve_links([None, 0, -1, True]) == {}
    repository.find_by_ids.assert_not_awaited()
    storage.object_exists.assert_not_awaited()
