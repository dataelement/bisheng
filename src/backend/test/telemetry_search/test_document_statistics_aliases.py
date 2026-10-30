"""Usage aliases query only the requested identities and keep the same mapping."""

from bisheng.knowledge.domain.document_identity import document_identity
from bisheng.telemetry.domain.repositories.implementations.knowledge_statistics_repository_impl import (
    KnowledgeStatisticsRepositoryImpl,
)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def __init__(self, statements):
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement):
        self.statements.append(statement)
        text = str(statement)
        if "IS NULL" in text.upper() or "is null" in text.lower() or "IS NULL" in text:
            return _Rows([(12, None)])
        return _Rows([(11, 5), (99, 8)])


def test_aliases_lookup_matches_identity_filter(monkeypatch):
    statements = []
    monkeypatch.setattr(
        "bisheng.telemetry.domain.repositories.implementations.knowledge_statistics_repository_impl.get_sync_db_session",
        lambda: _Session(statements),
    )
    monkeypatch.setattr(
        "bisheng.telemetry.domain.repositories.implementations.knowledge_statistics_repository_impl.get_current_tenant_id",
        lambda: 1,
    )
    result = KnowledgeStatisticsRepositoryImpl.aliases({"document:5", "file:12", "not-an-identity"})
    assert result[11] == document_identity(11, 5) == "document:5"
    assert result[12] == document_identity(12, None) == "file:12"
    assert 99 not in result
    assert len(statements) == 2
    compiled = " ".join(str(statement) for statement in statements)
    assert "knowledge_space_scope" in compiled
    assert "IN" in compiled.upper() or "in_" in compiled or "IN (" in compiled
