from sqlalchemy import BigInteger, CheckConstraint, String
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.schema import CreateTable

from bisheng.database.models.tenant import UserTenant
from bisheng.open_api.domain.models import ApiCredential, ServiceAccount
from bisheng.open_api.domain.models.api_credential import CREDENTIAL_SUBJECT_KINDS
from bisheng.user.domain.models.user import User


def test_service_account_is_an_independent_subject():
    assert set(ServiceAccount.__table__.columns.keys()) == {
        "id",
        "tenant_id",
        "name",
        "description",
        "resource_owner_user_id",
        "created_by",
        "disabled_at",
        "deleted_at",
        "create_time",
        "update_time",
    }
    assert not ServiceAccount.__table__.foreign_keys
    assert "user_type" not in User.__table__.columns
    assert "service_account_id" not in UserTenant.__table__.columns


def test_api_credential_contract_has_only_supported_subject_kinds():
    """The constant and the CHECK are one lockstep — a kind in one only is an insert error.

    ``hosted_app`` joined the set with F055 T055 (the hosted application's
    runtime credential). This test previously asserted its *absence*, which was
    right while the beta2 base carried no resolver for it: an accepted
    ``subject_kind`` with nothing able to resolve it is a credential that
    authenticates as nothing. What replaces that guard is the pair of assertions
    below plus ``test_app_credential.test_every_subject_kind_has_a_prefix`` —
    every accepted kind must have its own key prefix, so none of them can
    present another's token.
    """
    assert CREDENTIAL_SUBJECT_KINDS == {"service_account", "natural_person", "hosted_app"}
    constraints = [item for item in ApiCredential.__table__.constraints if isinstance(item, CheckConstraint)]
    assert len(constraints) == 1
    for kind in CREDENTIAL_SUBJECT_KINDS:
        assert f"'{kind}'" in str(constraints[0].sqltext)
    assert isinstance(ApiCredential.__table__.c.subject_id.type, BigInteger)


def test_open_api_tables_compile_for_supported_sql_families():
    for dialect in (mysql.dialect(), sqlite.dialect()):
        credential_ddl = str(CreateTable(ApiCredential.__table__).compile(dialect=dialect))
        service_account_ddl = str(CreateTable(ServiceAccount.__table__).compile(dialect=dialect))
        assert "api_credential" in credential_ddl
        assert "service_account" in service_account_ddl
        assert isinstance(ApiCredential.__table__.c.key_prefix.type, String)


def test_tenant_scoped_uniqueness_and_json_contract():
    sa_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in ServiceAccount.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    credential_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in ApiCredential.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("tenant_id", "name") in sa_unique_columns
    assert ("token_hash",) in credential_unique_columns
    assert ApiCredential.__table__.c.scopes.type.__class__.__name__ == "JsonType"
