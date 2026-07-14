from datetime import datetime
from types import SimpleNamespace

from bisheng.knowledge.rag.knowledge_file_pipeline import KnowledgeFilePipeline, UserDao


def test_file_metadata_normalizes_null_user_metadata(monkeypatch):
    monkeypatch.setattr(
        UserDao,
        "get_user",
        lambda _user_id: SimpleNamespace(user_name="tester"),
    )
    pipeline = object.__new__(KnowledgeFilePipeline)
    pipeline.invoke_user_id = 1
    pipeline.file_name = "test.md"
    pipeline.db_file = SimpleNamespace(
        id=85044,
        knowledge_id=3124,
        create_time=datetime(2026, 7, 14, 10, 0, 0),
        update_time=datetime(2026, 7, 14, 10, 1, 0),
        updater_id=None,
        user_metadata=None,
        abstract=None,
    )

    metadata = pipeline.file_metadata

    assert metadata["abstract"] == ""
    assert metadata["user_metadata"] == {}
