"""F062 T115: foundation contracts and persistence safety checks.

Coverage AC: AC-01, AC-02, AC-03, AC-13, AC-22, AC-23, AC-29, AC-30, AC-31, AC-32, AC-34.
These checks do not replace MySQL/DM8 or distributed quota acceptance.
"""

import base64
import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable
from sqlmodel import Session, SQLModel


def test_client_contract_surface_and_pkce(dsh_contracts):
    client = dsh_contracts["client-0.4.0"]
    assert len({(e["method"], e["path"]) for e in client["endpoints"]}) == 7
    assert next(e for e in client["endpoints"] if e["path"].endswith("logout"))["response"] == {
        "http_status": 204,
        "body": None,
    }
    pkce = dsh_contracts["identity-and-errors"]["pkce"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(pkce["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == pkce["challenge"]
    assert all(
        value is None
        for key, value in dsh_contracts["identity-and-errors"]["unknown_usage"].items()
        if key.endswith("tokens")
    )


def test_license_vectors_signed_by_test_public_key_only(dsh_contracts):
    bundle = dsh_contracts["license-entitlement-v1"]
    jwk = bundle["verification_jwks"]["keys"][0]
    assert not ({"d", "p", "q", "dp", "dq", "qi"} & jwk.keys())

    def decode(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    public = rsa.RSAPublicNumbers(
        int.from_bytes(decode(jwk["e"]), "big"), int.from_bytes(decode(jwk["n"]), "big")
    ).public_key()
    for vector in bundle["vectors"]:
        header, payload, signature = vector["outer_plaintext"]["dsh_entitlement"].split(".")
        if vector["name"] == "tampered_signature":
            from cryptography.exceptions import InvalidSignature

            with pytest.raises(InvalidSignature):
                public.verify(decode(signature), f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
        else:
            public.verify(decode(signature), f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
            assert isinstance(json.loads(decode(payload)), dict)


def test_config_default_off_and_enabled_requires_trust():
    from bisheng.dsh.config import DshSettings

    assert DshSettings().enabled is False
    with pytest.raises(ValidationError):
        DshSettings(enabled=True)
    with pytest.raises(ValidationError):
        DshSettings(platform_public_url="https://example.com/path")
    with pytest.raises(ValidationError):
        DshSettings(enabled="false")


def test_identity_contract_is_strict(dsh_contracts):
    from bisheng.dsh.domain.schemas.contracts import DshIdentitySnapshot

    fixture = dsh_contracts["identity-and-errors"]
    for key in ["snapshot", "snapshot_name_fallback", "inactive_snapshot"]:
        value = DshIdentitySnapshot.model_validate(fixture[key])
        assert value.model_dump(exclude_none=not value.active) == fixture[key]
    invalid = deepcopy(fixture["snapshot"])
    invalid["user"]["id"] = "999"
    with pytest.raises(ValidationError):
        DshIdentitySnapshot.model_validate(invalid)
    invalid = deepcopy(fixture["snapshot"])
    invalid["profile_version"] = True
    with pytest.raises(ValidationError):
        DshIdentitySnapshot.model_validate(invalid)


def test_usage_dto_does_not_turn_unknown_into_zero():
    from bisheng.dsh.domain.schemas.contracts import DshTokenUsage

    assert DshTokenUsage().total_tokens is None
    with pytest.raises(ValidationError):
        DshTokenUsage(input_tokens=1, output_tokens=2, total_tokens=0)
    with pytest.raises(ValidationError):
        DshTokenUsage(total_tokens=0)
    assert DshTokenUsage(input_tokens=0, output_tokens=0, total_tokens=0).total_tokens == 0


def test_models_preserve_unknown_and_policy_history():
    from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
    from bisheng.dsh.domain.models.model_call import DshModelCall
    from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
    from bisheng.dsh.domain.models.user_policy import DshUserPolicy

    models = (DshUserPolicy, DshAdminOperation, DshMonthlyUsage, DshModelCall)
    engine = create_engine("sqlite://")
    tables = [model.__table__ for model in models]
    SQLModel.metadata.create_all(engine, tables=tables)
    with Session(engine) as session:
        row = DshModelCall(
            request_id=str(uuid4()),
            tenant_id=2,
            user_id=1001,
            model_id=42,
            seat_id=str(uuid4()),
            session_id=str(uuid4()),
            grant_version=1,
            usage_month="2026-09",
            policy_version=1,
            event_version=1,
            quota_epoch=1,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        assert row.total_tokens is None
        assert row.usage_source is None
        session.add(DshUserPolicy(model_id=4, enabled=1, tenant_id=2, user_id=1001, updated_by=1004))
        session.commit()
        session.add(DshUserPolicy(model_id=4, enabled=1, tenant_id=2, user_id=1001, updated_by=1004))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(
            DshMonthlyUsage(
                tenant_id=2, user_id=1001, model_id=42, usage_month="2026-09", billing_timezone="UTC", used_tokens=-1
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    from sqlalchemy.dialects.mysql import dialect

    for table in tables:
        ddl = str(CreateTable(table).compile(dialect=dialect()))
        assert "tenant_id" in ddl and "create_time" in ddl and "update_time" in ddl
        assert not table.foreign_keys
    engine.dispose()


def test_profile_migration_is_additive_and_retained(monkeypatch):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text

    path = Path(__file__).resolve().parents[2] / "bisheng/core/database/alembic/versions/v3_0_0_f062_profile_version.py"
    spec = importlib.util.spec_from_file_location("dsh_profile_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE "user" (user_id INTEGER PRIMARY KEY)'))
        connection.execute(text('INSERT INTO "user" (user_id) VALUES (1)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
            assert connection.execute(text('SELECT dsh_profile_version FROM "user"')).scalar_one() == 0
            migration.downgrade()
        assert "dsh_profile_version" in {column["name"] for column in inspect(connection).get_columns("user")}
    engine.dispose()

    # DM8 reflection returns uppercase identifiers; retained columns must not be added again.
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text('CREATE TABLE "USER" (USER_ID INTEGER PRIMARY KEY, DSH_PROFILE_VERSION BIGINT NOT NULL)')
        )
        connection.execute(text('INSERT INTO "USER" VALUES (1, 7)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.execute(text('SELECT DSH_PROFILE_VERSION FROM "USER"')).scalar_one() == 7
    engine.dispose()


def test_error_registry_matches_frozen_envelope(dsh_contracts):
    from bisheng.common.errcode.dsh import ERROR_BY_CLIENT_CODE

    for case in dsh_contracts["client-0.4.0"]["errors"]:
        detail = case["body"]["error"]
        error = ERROR_BY_CLIENT_CODE[detail["code"]]
        assert error.HttpStatus == case["http_status"]
        assert error.ErrorType == detail["type"]
    assert len({error.Code for error in ERROR_BY_CLIENT_CODE.values()}) == len(ERROR_BY_CLIENT_CODE)
    assert all(error.Code // 100 == 261 for error in ERROR_BY_CLIENT_CODE.values())


def test_enabled_config_has_no_duplicate_secret_or_redis_fields():
    from bisheng.dsh.config import DshSettings

    settings = DshSettings(
        enabled=True,
        installation_id="test-installation",
        platform_public_url="https://bisheng.example.com",
        gateway_internal_url="https://gateway.example.com",
    )
    fields = settings.model_dump()
    assert not any("hmac" in key or "redis_url" in key or "verified_model" in key for key in fields)


def test_missing_external_stores_fail_explicitly(monkeypatch):
    from test.dsh.conftest import dsh_database_url, dsh_redis_url

    monkeypatch.delenv("DSH_TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("DSH_TEST_REDIS_URL", raising=False)
    with pytest.raises(pytest.UsageError):
        dsh_database_url.__wrapped__()
    with pytest.raises(pytest.UsageError):
        dsh_redis_url.__wrapped__()


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_config_accepts_http_and_https_origins(scheme):
    from bisheng.dsh.config import DshSettings

    settings = DshSettings(
        platform_public_url=f"{scheme}://192.168.106.109:13001/",
        gateway_internal_url=f"{scheme}://gateway:8080/",
    )
    assert settings.platform_public_url == f"{scheme}://192.168.106.109:13001"
    assert settings.gateway_internal_url == f"{scheme}://gateway:8080"


@pytest.mark.parametrize(
    "origin",
    [
        "ftp://gateway",
        "http://user:password@gateway",
        "http://gateway/path",
        "http://gateway?key=value",
        "http://gateway#fragment",
        "http://gateway:invalid",
        "http:///",
    ],
)
def test_config_rejects_non_origin_addresses(origin):
    from bisheng.dsh.config import DshSettings

    for field in ("platform_public_url", "gateway_internal_url"):
        with pytest.raises(ValidationError):
            DshSettings(**{field: origin})
