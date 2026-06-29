"""Tests for the knowledge-space reparse maintenance script."""

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

import scripts.reparse_knowledge_space_files as script_mod
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileStatus,
)


async def _seed_space(
    session: AsyncSession,
    knowledge_id: int,
    *,
    knowledge_type: int = KnowledgeTypeEnum.SPACE.value,
) -> None:
    await session.exec(
        text("INSERT INTO knowledge (id, user_id, name, type) VALUES (:id, :user_id, :name, :type)").bindparams(
            id=knowledge_id,
            user_id=1,
            name=f"space-{knowledge_id}",
            type=knowledge_type,
        )
    )
    await session.commit()


async def _seed_file(
    session: AsyncSession,
    *,
    file_id: int,
    knowledge_id: int,
    status: int = KnowledgeFileStatus.SUCCESS.value,
    file_type: int = FileType.FILE.value,
    file_name: str | None = None,
    file_level_path: str | None = None,
) -> None:
    session.add(
        KnowledgeFile(
            id=file_id,
            knowledge_id=knowledge_id,
            file_name=file_name or f"file-{file_id}.pdf",
            file_type=file_type,
            status=status,
            file_level_path=file_level_path,
            object_name=f"knowledge/{knowledge_id}/{file_id}.pdf",
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_collect_default_selects_all_space_eligible_files(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_space(async_db_session, 2, knowledge_type=KnowledgeTypeEnum.NORMAL.value)
    await _seed_file(async_db_session, file_id=101, knowledge_id=1, status=KnowledgeFileStatus.SUCCESS.value)
    await _seed_file(async_db_session, file_id=102, knowledge_id=1, status=KnowledgeFileStatus.FAILED.value)
    await _seed_file(async_db_session, file_id=103, knowledge_id=1, status=KnowledgeFileStatus.TIMEOUT.value)
    await _seed_file(async_db_session, file_id=104, knowledge_id=1, status=KnowledgeFileStatus.VIOLATION.value)
    await _seed_file(async_db_session, file_id=105, knowledge_id=1, status=KnowledgeFileStatus.WAITING.value)
    await _seed_file(async_db_session, file_id=106, knowledge_id=1, file_type=FileType.DIR.value)
    await _seed_file(async_db_session, file_id=201, knowledge_id=2, status=KnowledgeFileStatus.SUCCESS.value)

    report = await script_mod.collect_candidate_files(async_db_session)

    assert [item.id for item in report.selected_files] == [101, 102, 103, 104]
    assert report.skipped_status_records == 1
    assert report.skipped_folder_records == 1


@pytest.mark.asyncio
async def test_collect_explicit_scopes_are_unioned_and_folders_recurse(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_space(async_db_session, 2)
    await _seed_space(async_db_session, 3)
    await _seed_file(async_db_session, file_id=10, knowledge_id=1, file_type=FileType.DIR.value)
    await _seed_file(async_db_session, file_id=11, knowledge_id=1, file_level_path="/10")
    await _seed_file(async_db_session, file_id=12, knowledge_id=1, file_type=FileType.DIR.value, file_level_path="/10")
    await _seed_file(async_db_session, file_id=13, knowledge_id=1, file_level_path="/10/12")
    await _seed_file(
        async_db_session, file_id=14, knowledge_id=1, status=KnowledgeFileStatus.PROCESSING.value, file_level_path="/10"
    )
    await _seed_file(async_db_session, file_id=21, knowledge_id=2)
    await _seed_file(async_db_session, file_id=31, knowledge_id=3)

    report = await script_mod.collect_candidate_files(
        async_db_session,
        space_ids=[3],
        folder_ids=[10],
        file_ids=[21],
    )

    assert [item.id for item in report.selected_files] == [11, 13, 21, 31]
    assert report.skipped_count == 0


@pytest.mark.asyncio
async def test_run_reparse_files_continues_after_single_file_failure():
    files = [
        KnowledgeFile(id=1, knowledge_id=1, file_name="a.pdf"),
        KnowledgeFile(id=2, knowledge_id=1, file_name="b.pdf"),
        KnowledgeFile(id=3, knowledge_id=1, file_name="c.pdf"),
    ]
    attempts: list[int] = []

    def fake_reparse(file_id: int) -> script_mod.FileReparseResult:
        attempts.append(file_id)
        if file_id == 2:
            raise RuntimeError("boom")
        return script_mod.FileReparseResult(
            file_id=file_id,
            knowledge_id=1,
            file_name=f"{file_id}.pdf",
            success=True,
            final_status=KnowledgeFileStatus.SUCCESS.value,
        )

    report = await script_mod.run_reparse_files(files, concurrency=2, reparse_func=fake_reparse)

    assert sorted(attempts) == [1, 2, 3]
    assert report.success == 2
    assert report.failed == 1
    failed = [item for item in report.results if not item.success]
    assert failed[0].file_id == 2
    assert "RuntimeError: boom" in failed[0].error


def test_reparse_one_file_clears_vectors_and_runs_pipeline(monkeypatch):
    db_file = KnowledgeFile(
        id=100,
        knowledge_id=10,
        file_name="doc.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        simhash="abcdef0123456789",
        similar_status=1,
    )
    knowledge = Knowledge(id=10, name="space", type=KnowledgeTypeEnum.SPACE.value, user_id=1)
    calls: list[str] = []

    monkeypatch.setattr(script_mod, "_get_file_sync", lambda file_id: db_file)
    monkeypatch.setattr(script_mod, "_get_knowledge_sync", lambda knowledge_id: knowledge)

    def fake_update(file: KnowledgeFile) -> KnowledgeFile:
        calls.append(f"update:{file.status}:{file.simhash}:{file.similar_status}")
        return file

    def fake_delete(file_id: int, db_knowledge: Knowledge) -> None:
        calls.append(f"delete:{file_id}:{db_knowledge.id}")

    def fake_parse(db_knowledge: Knowledge, file: KnowledgeFile) -> None:
        calls.append(f"parse:{file.id}:{db_knowledge.id}")
        file.status = KnowledgeFileStatus.SUCCESS.value
        file.remark = ""

    monkeypatch.setattr(script_mod, "_update_file_sync", fake_update)
    monkeypatch.setattr(script_mod, "_delete_existing_vectors", fake_delete)
    monkeypatch.setattr(script_mod, "_run_parse_pipeline", fake_parse)

    result = script_mod.reparse_one_file(100)

    assert result.success is True
    assert calls == [
        "update:1:None:0",
        "delete:100:10",
        "parse:100:10",
    ]


def test_parse_args_defaults_to_dry_run_and_single_concurrency():
    args = script_mod.parse_args([])

    assert args.apply is False
    assert args.concurrency == 1
    assert args.space_ids == []
    assert args.folder_ids == []
    assert args.file_ids == []
