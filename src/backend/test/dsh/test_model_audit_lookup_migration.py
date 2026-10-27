"""Main-based installs create complete model lookup indexes from table metadata."""

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import dialect
from sqlalchemy.schema import CreateIndex

from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest

INDEXES = {
    "ix_dma_request_model": ["tenant_id", "model_id", "started_at", "request_id"],
    "ix_dma_request_name": ["tenant_id", "model_name_digest", "started_at", "request_id"],
}


def test_model_lookup_indexes_are_created_with_the_new_table():
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            DshModelAuditRequest.__table__.create(connection)
            indexes = {
                index["name"]: index["column_names"]
                for index in sa.inspect(connection).get_indexes("dsh_model_audit_request")
            }
            for name, columns in INDEXES.items():
                assert indexes[name] == columns
    finally:
        engine.dispose()


def test_mysql_and_dm_indexes_have_only_bounded_columns():
    for index in DshModelAuditRequest.__table__.indexes:
        if index.name in INDEXES:
            ddl = str(CreateIndex(index).compile(dialect=dialect()))
            assert "model_name," not in ddl and "LIKE" not in ddl
            assert all(not isinstance(column.type, sa.String) or column.type.length <= 64 for column in index.columns)
