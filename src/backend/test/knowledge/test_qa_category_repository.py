from datetime import datetime

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)


async def test_category_candidates_execute_filtered_cursor_query(async_db_session):
    def file(file_id, **extra):
        values = {
            "id": file_id,
            "tenant_id": 1,
            "knowledge_id": 10,
            "file_name": f"{file_id}.pdf",
            "file_encoding": "SG-ZC-A-001",
            "file_subcategory_code": "A",
            "status": 2,
            "file_type": 1,
        }
        values.update(extra)
        return KnowledgeFile(**values)

    async_db_session.add_all(
        [
            file(100),
            file(99),
            file(98),
            file(97),
            file(105, knowledge_id=11),
            file(104, status=3),
            file(103, file_type=0),
            file(102, file_subcategory_code="B"),
            file(101, deleted_at=datetime(2026, 9, 10)),
            file(106, file_encoding="SG-BG-A-001"),
            file(96, file_encoding=" SG - zc - A - 001 ", file_subcategory_code=" a "),
        ]
    )
    await async_db_session.commit()
    repository = KnowledgeFileRepositoryImpl(async_db_session)
    first = await repository.list_qa_category_candidates(
        space_ids=[10], document_type="ZC", file_subcategory_code="A", before_id=None, limit=2
    )
    second = await repository.list_qa_category_candidates(
        space_ids=[10], document_type="ZC", file_subcategory_code="A", before_id=first[-1].id, limit=2
    )
    assert [f.id for f in first] == [100, 99]
    assert [f.id for f in second] == [98, 97]
    third = await repository.list_qa_category_candidates(
        space_ids=[10], document_type="ZC", file_subcategory_code="A", before_id=97, limit=2,
    )
    assert [f.id for f in third] == [96]
    assert (
        await repository.list_qa_category_candidates(
            space_ids=[], document_type=None, file_subcategory_code=None, before_id=None, limit=2
        )
        == []
    )
