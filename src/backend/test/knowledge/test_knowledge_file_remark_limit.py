from bisheng.knowledge.domain.models import knowledge_file as knowledge_file_model


class _SyncSession:
    def __init__(self):
        self.statement = None
        self.committed = False

    def exec(self, statement):
        self.statement = statement

    def commit(self):
        self.committed = True


class _SyncSessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def test_remark_limit_matches_model_column_length():
    assert (
        knowledge_file_model.KnowledgeFile.__table__.c.remark.type.length
        == knowledge_file_model.KNOWLEDGE_REMARK_MAX_LENGTH
    )
    assert (
        knowledge_file_model.QAKnowledge.__table__.c.remark.type.length
        == knowledge_file_model.KNOWLEDGE_REMARK_MAX_LENGTH
    )


def test_update_file_status_limits_long_remark(monkeypatch):
    session = _SyncSession()
    monkeypatch.setattr(
        knowledge_file_model,
        "get_sync_db_session",
        lambda: _SyncSessionContext(session),
    )
    long_remark = "异常" * (knowledge_file_model.KNOWLEDGE_REMARK_MAX_LENGTH + 1)

    knowledge_file_model.KnowledgeFileDao.update_file_status(
        [86692],
        knowledge_file_model.KnowledgeFileStatus.FAILED,
        long_remark,
    )

    assert session.committed is True
    assert (
        session.statement.compile().params["remark"] == long_remark[: knowledge_file_model.KNOWLEDGE_REMARK_MAX_LENGTH]
    )


def test_remark_limit_preserves_none_and_short_values():
    assert knowledge_file_model._limit_remark(None) is None
    assert knowledge_file_model._limit_remark("milvus down") == "milvus down"
