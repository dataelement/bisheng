from sqlalchemy import Index

from bisheng.database.models.session import MessageSession
from bisheng.open_api.domain.models.credential_delegate_scope import ApiCredentialDelegateScope


def test_delegate_scope_table_has_only_typed_scope_contract():
    columns = set(ApiCredentialDelegateScope.__table__.columns.keys())
    assert columns == {"id", "tenant_id", "credential_id", "subject_type", "subject_id", "create_time"}
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in ApiCredentialDelegateScope.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("credential_id", "subject_type", "subject_id") in unique_columns


def test_message_session_has_only_designed_open_api_columns_and_index():
    columns = set(MessageSession.__table__.columns.keys())
    assert {"api_subject_type", "api_subject_id", "external_user_id"} <= columns
    api_indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in MessageSession.__table__.indexes
        if isinstance(index, Index) and index.name == "idx_message_session_api_subject"
    }
    assert api_indexes == {
        "idx_message_session_api_subject": (
            "tenant_id",
            "api_subject_type",
            "api_subject_id",
            "update_time",
        )
    }
