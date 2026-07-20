import pytest
from pydantic import ValidationError

from bisheng.knowledge.domain.models.knowledge_file import (
    KNOWLEDGE_FILE_NAME_MAX_LENGTH,
    KnowledgeFile,
    KnowledgeFileCreate,
)


def test_knowledge_file_name_allows_500_characters() -> None:
    file_name = "a" * KNOWLEDGE_FILE_NAME_MAX_LENGTH

    knowledge_file = KnowledgeFileCreate(knowledge_id=1, file_name=file_name)

    assert knowledge_file.file_name == file_name
    assert KnowledgeFile.__table__.c.file_name.type.length == KNOWLEDGE_FILE_NAME_MAX_LENGTH


def test_knowledge_file_name_rejects_more_than_500_characters() -> None:
    with pytest.raises(ValidationError, match="String should have at most 500 characters"):
        KnowledgeFileCreate(
            knowledge_id=1,
            file_name="a" * (KNOWLEDGE_FILE_NAME_MAX_LENGTH + 1),
        )
