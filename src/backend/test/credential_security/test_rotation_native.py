"""AC-50, AC-51, AC-52, AC-53, AC-54, AC-55: exact native auth evidence.

Run with --confcutdir=test/credential_security; no application pre-mocks.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bisheng.core.config.secret_crypto import CredentialConfigurationError


def test_mysql_access_denied_is_distinct_from_network_or_database_permissions():
    import pymysql
    from sqlalchemy.exc import OperationalError

    from bisheng.core.config.credential_rotation_native import classify_failure

    def error(code):
        return OperationalError(None, None, pymysql.err.OperationalError(code, "private diagnostic"))

    assert classify_failure("mysql", error(1045)) == "DENIED"
    assert classify_failure("mysql", error(1044)) == "UNKNOWN"
    assert classify_failure("mysql", error(2003)) == "UNKNOWN"


def test_redis_and_minio_authorization_are_not_arbitrary_authentication_failures():
    from minio.error import S3Error
    from redis.exceptions import AuthenticationError, ConnectionError, ResponseError

    from bisheng.core.config.credential_rotation_native import classify_failure

    assert classify_failure("redis", AuthenticationError("wrong password")) == "DENIED"
    assert classify_failure("redis", ConnectionError("offline")) == "UNKNOWN"
    assert classify_failure("redis", ResponseError("NOPERM")) == "UNKNOWN"
    for code, expected in [
        ("SignatureDoesNotMatch", "DENIED"),
        ("InvalidAccessKeyId", "DENIED"),
        ("AccessDenied", "UNKNOWN"),
    ]:
        error = S3Error(code=code, message="private diagnostic", resource="", request_id="", host_id="", response=None)
        assert classify_failure("minio", error) == expected


def test_milvus_grpc_authentication_code_is_required():
    import grpc

    from bisheng.core.config.credential_rotation_native import classify_failure

    class Rpc(grpc.RpcError):
        def __init__(self, code):
            self._code = code

        def code(self):
            return self._code

    assert classify_failure("milvus", Rpc(grpc.StatusCode.UNAUTHENTICATED)) == "DENIED"
    assert classify_failure("milvus", Rpc(grpc.StatusCode.UNAVAILABLE)) == "UNKNOWN"
    assert classify_failure("milvus", RuntimeError("authentication text in unrelated exception")) == "UNKNOWN"


def test_probe_never_exposes_driver_error_or_retries(monkeypatch):
    from bisheng.core.config import credential_rotation_native as mod

    call = MagicMock(side_effect=RuntimeError("marker-private-password"))
    monkeypatch.setattr(mod, "_probe", call)
    assert mod.authentication_status(SimpleNamespace(), "mysql") == "UNKNOWN"
    call.assert_called_once()


def test_milvus_without_verifiable_identity_is_rejected_before_rpc(monkeypatch):
    from bisheng.core.config import credential_rotation_native as mod

    settings = SimpleNamespace(
        vector_stores=SimpleNamespace(milvus=SimpleNamespace(connection_args={"host": "milvus", "port": "19530"}))
    )
    with pytest.raises(CredentialConfigurationError, match="current authenticated identity"):
        mod.milvus_args(settings)


def test_redis_capture_keeps_all_users_and_rejects_lossy_acl():
    from bisheng.core.config.credential_rotation_native import validate_redis_acl

    acl = ["user default on nopass ~* &* +@all", "user audit on #abcd ~audit:* -@all +get"]
    assert validate_redis_acl(acl, "default") == "\n".join(acl) + "\n"
    for value in [
        ["user other on nopass ~* +@all"],
        ["user default on nopass ~* +@all", "user default on nopass ~* +@all"],
        ['user default on nopass ~"quoted pattern" +@all'],
    ]:
        with pytest.raises(CredentialConfigurationError):
            validate_redis_acl(value, "default")


def test_mysql_socket_evidence_must_be_verified_not_merely_rpc_ack():
    from bisheng.core.config.credential_rotation_native import mysql_local_decision

    assert mysql_local_decision({"new": "DENIED", "old": "OK"}) == "APPLY"
    assert mysql_local_decision({"new": "OK", "old": "DENIED"}) == "PERSIST"
    for evidence in ({"new": "UNKNOWN", "old": "OK"}, {"new": "OK", "old": "OK"}, {}):
        with pytest.raises(CredentialConfigurationError):
            mysql_local_decision(evidence)


@pytest.fixture
def native_attempt(monkeypatch):
    from bisheng.core.config import credential_rotation_native as mod

    old = SimpleNamespace(
        redis_url="redis://default:old@redis:6379/1",
        vector_stores=SimpleNamespace(
            elasticsearch=SimpleNamespace(ssl_verify={"basic_auth": ["elastic", "old"]}),
            milvus=SimpleNamespace(
                connection_args={"host": "milvus", "port": "19530", "user": "root", "password": "old"}
            ),
        ),
    )
    new = SimpleNamespace()
    monkeypatch.setattr(
        mod, "read_plan", lambda *a, **k: {"selected": ["mysql", "redis", "elasticsearch", "minio", "milvus"]}
    )
    monkeypatch.setattr(mod, "read_journal", lambda *a: {"consumers_stopped": True, "phase": "CONSUMERS_STOPPED"})
    monkeypatch.setattr(mod, "stage_settings", lambda *a, new, **k: new_settings if new else old)
    new_settings = new
    monkeypatch.setattr(mod, "authentication_status", lambda s, c: "DENIED" if s is new else "OK")
    monkeypatch.setattr(
        mod,
        "credentials",
        lambda s: dict.fromkeys(
            ("mysql", "redis", "minio", "elasticsearch", "milvus"), "new-value" if s is new else "old-value"
        ),
    )
    record = MagicMock()
    monkeypatch.setattr(mod, "record_component", record)
    monkeypatch.setattr(mod, "record_account", MagicMock())
    return mod, old, new, record


def test_redis_password_change_defers_to_host_recreate_not_live_acl(native_attempt, monkeypatch):
    """Live acl_setuser before recreate desyncs RO-mounted ACL and breaks resume preflight."""
    mod, _old, _new, record = native_attempt
    connection = MagicMock(side_effect=AssertionError("Redis must not mutate live ACL before recreate"))
    monkeypatch.setattr(mod, "_redis", connection)
    assert mod.change_component("session", "redis", apply=True) == "RECREATE"
    connection.assert_not_called()
    record.assert_called_once_with("session", "redis", "CHANGE_INTENT")


def test_minio_root_write_requires_host_recreation_not_iam(native_attempt, monkeypatch):
    mod, _old, _new, record = native_attempt
    connection = MagicMock(side_effect=AssertionError("No IAM password API is permitted"))
    monkeypatch.setattr(mod, "_minio", connection)
    assert mod.change_component("session", "minio", apply=True) == "RECREATE"
    connection.assert_not_called()
    record.assert_called_once_with("session", "minio", "CHANGE_INTENT")


def test_mysql_sql_parameters_and_subaccount_intents(native_attempt, monkeypatch):
    from contextlib import contextmanager

    mod, old, _new, record = native_attempt
    conn = MagicMock()

    @contextmanager
    def connection(s):
        assert s is old
        yield conn

    monkeypatch.setattr(mod, "_mysql", connection)
    mod.change_component("session", "mysql", evidence={"new": "DENIED", "old": "OK"}, apply=True)
    assert conn.execute.call_count == 2
    for call in conn.execute.call_args_list:
        statement, values = call.args
        assert "new-value" not in str(statement)
        assert values == {"password": "new-value"}
    assert mod.record_account.call_count == 2
    record.assert_called_once_with("session", "mysql", "CHANGE_INTENT")


def test_milvus_timeout_does_not_retry_native_password_update(native_attempt, monkeypatch):
    from contextlib import contextmanager

    mod, _old, new, record = native_attempt
    client = MagicMock()
    update = MagicMock(side_effect=TimeoutError("uncertain RPC result"))
    monkeypatch.setattr(mod, "_milvus_password_once", update)

    @contextmanager
    def connection(s):
        yield client

    monkeypatch.setattr(mod, "_milvus", connection)
    with pytest.raises(TimeoutError):
        mod.change_component("session", "milvus", apply=True)
    update.assert_called_once_with(client, "root", "old-value", "new-value")
    record.assert_called_once_with("session", "milvus", "CHANGE_INTENT")
    monkeypatch.setattr(mod, "authentication_status", lambda s, c: "OK" if s is new else "DENIED")
    assert mod.change_component("session", "milvus", apply=True) == "RECREATE"
    assert update.call_count == 1


def test_unreachable_native_never_causes_write(native_attempt, monkeypatch):
    mod, _old, _new, _record = native_attempt
    monkeypatch.setattr(mod, "authentication_status", lambda s, c: "UNKNOWN")
    write = MagicMock()
    monkeypatch.setattr(mod, "_redis", write)
    with pytest.raises(CredentialConfigurationError, match="unknown"):
        mod.change_component("session", "redis", apply=True)
    write.assert_not_called()


def test_minio_frozen_sdk_error_survives_resource_cleanup(monkeypatch):
    from dataclasses import FrozenInstanceError

    from minio.error import S3Error

    from bisheng.core.config.credential_rotation_native import authentication_status

    class FrozenS3Error(S3Error):
        def __setattr__(self, name, value):
            if name == "__traceback__":
                raise FrozenInstanceError("frozen SDK error")
            super().__setattr__(name, value)

    error = FrozenS3Error(
        response=None,
        code="SignatureDoesNotMatch",
        message="private-sdk-detail",
        resource="/",
        request_id="test",
        host_id="test",
    )
    client = MagicMock()
    client.list_buckets.side_effect = error
    monkeypatch.setattr("minio.Minio", lambda *a, **k: client)
    settings = SimpleNamespace(
        object_storage=SimpleNamespace(
            minio=SimpleNamespace(
                endpoint="minio:9000", access_key="user", secret_key="private", secure=False, cert_check=True
            )
        )
    )
    assert authentication_status(settings, "minio") == "DENIED"


def test_mysql_preflight_accepts_explicit_privilege_list(monkeypatch):
    from contextlib import contextmanager

    from bisheng.core.config import credential_rotation_native as mod

    conn = MagicMock()
    version = MagicMock()
    version.scalar_one.return_value = "8.0.43"
    hosts = MagicMock()
    hosts.scalars.return_value.all.return_value = ["%", "localhost"]
    conn.execute.side_effect = [version, hosts, [("GRANT CREATE USER, SYSTEM_USER ON *.* TO root",)]]

    @contextmanager
    def connection(settings):
        yield conn

    monkeypatch.setattr(mod, "_mysql", connection)
    monkeypatch.setattr(mod, "authentication_status", lambda *a: "OK")
    settings = SimpleNamespace(database_url="mysql+pymysql://root:private@mysql/bisheng")
    captured = mod.capture_runtime(settings, ["mysql"], {"mysql_socket_old": "OK"})
    assert captured["capabilities"]["mysql"]["hosts"] == ["%", "localhost"]


def test_milvus_native_write_bypasses_sdk_retry_decorator():
    import functools

    from bisheng.core.config.credential_rotation_native import _milvus_password_once

    calls = []

    def retry(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            raise AssertionError("retry decorator must not run for an uncertain write")

        return wrapped

    class Handler:
        @retry
        def update_password(self, user, old_password, new_password, timeout=None):
            calls.append((user, old_password, new_password, timeout))
            raise TimeoutError("uncertain single RPC result")

    client = SimpleNamespace(_get_connection=lambda: Handler())
    with pytest.raises(TimeoutError):
        _milvus_password_once(client, "root", "old-value", "new-value")
    assert calls == [("root", "old-value", "new-value", 5)]


@pytest.mark.parametrize("version", ["2.5.10", "v2.5.10"])
def test_milvus_preflight_normalizes_server_version_prefix(monkeypatch, version):
    from contextlib import contextmanager

    import pymilvus

    from bisheng.core.config import credential_rotation_native as mod

    client = MagicMock()
    client.get_server_version.return_value = version

    @contextmanager
    def connection(settings):
        yield client

    monkeypatch.setattr(pymilvus, "__version__", "2.6.15")
    monkeypatch.setattr(mod, "_milvus", connection)
    monkeypatch.setattr(mod, "authentication_status", lambda *a: "OK")
    settings = SimpleNamespace(
        vector_stores=SimpleNamespace(
            milvus=SimpleNamespace(
                connection_args={"host": "milvus", "port": 19530, "user": "root", "password": "private"}
            )
        )
    )
    captured = mod.capture_runtime(settings, ["milvus"], {"milvus_auth_enabled": True})
    assert captured["capabilities"]["milvus"]["server_version"] == version


def _private_inventory(session, payload):
    path = session / "inventory.json"
    path.write_text(payload)
    path.chmod(0o600)


def test_unauthenticated_milvus_capture_initializes_root_without_guessing_password(monkeypatch):
    import pymilvus

    from bisheng.core.config import credential_rotation_native as mod

    opened = {}

    class FakeClient:
        def __init__(self, **kwargs):
            opened.update(kwargs)

        def get_server_version(self, timeout=None):
            return "2.5.10"

        def close(self):
            return None

    monkeypatch.setattr(pymilvus, "__version__", "2.6.15")
    monkeypatch.setattr(mod, "MilvusClient", FakeClient, raising=False)
    monkeypatch.setattr("pymilvus.MilvusClient", FakeClient)
    settings = SimpleNamespace(
        vector_stores=SimpleNamespace(
            milvus=SimpleNamespace(connection_args={"host": "milvus", "port": 19530, "secure": False})
        )
    )
    captured = mod.capture_runtime(settings, ["milvus"], {"milvus_auth_enabled": False})
    assert captured["capabilities"]["milvus"]["mode"] == "initialize"
    assert captured["capabilities"]["milvus"]["username"] == "root"
    assert "password" not in opened
    assert "token" not in opened


def test_unauthenticated_milvus_change_recreates_without_update_password(tmp_path, monkeypatch):
    from bisheng.core.config import credential_rotation_native as mod

    session = tmp_path / "session"
    session.mkdir()
    _private_inventory(session, '{"milvus_auth_enabled": false}\n')
    monkeypatch.setattr(mod, "read_plan", lambda *a, **k: {"selected": ["milvus"]})
    monkeypatch.setattr(mod, "read_journal", lambda *a: {"consumers_stopped": True, "phase": "CONSUMERS_STOPPED"})
    monkeypatch.setattr(mod, "stage_settings", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(mod, "record_component", MagicMock())
    update = MagicMock(side_effect=AssertionError("no current Milvus identity to update"))
    monkeypatch.setattr(mod, "_milvus_password_once", update)
    assert mod.change_component(session, "milvus", apply=True) == "RECREATE"
    update.assert_not_called()


def test_unauthenticated_milvus_verify_requires_new_root_password(tmp_path, monkeypatch):
    from bisheng.core.config import credential_rotation_native as mod
    from bisheng.core.config.secret_crypto import CredentialConfigurationError

    session = tmp_path / "session"
    session.mkdir()
    _private_inventory(session, '{"milvus_auth_enabled": false}\n')
    monkeypatch.setattr(mod, "stage_settings", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(mod, "record_component", MagicMock())
    monkeypatch.setattr(mod, "authentication_status", lambda *a: "DENIED")
    monkeypatch.setattr(mod, "_replace_preexisting_milvus_root", MagicMock())
    with pytest.raises(CredentialConfigurationError, match="initialized root password"):
        mod.verify_component(session, "milvus")
    mod._replace_preexisting_milvus_root.assert_called_once()


def test_existing_milvus_root_is_updated_when_default_password_file_does_not_apply(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from bisheng.core.config import credential_rotation_native as mod

    session = tmp_path / "session"
    session.mkdir()
    _private_inventory(
        session,
        '{"milvus_auth_enabled": false, "native_files": {"milvus.yaml": "common:\\n  security:\\n    authorizationEnabled: false\\n    defaultRootPassword: \\"\\"\\n"}}',
    )
    probes = iter(("DENIED", "OK"))
    monkeypatch.setattr(mod, "authentication_status", lambda *a: next(probes))
    monkeypatch.setattr(mod, "record_component", MagicMock())
    new_settings = SimpleNamespace(
        vector_stores=SimpleNamespace(
            milvus=SimpleNamespace(
                connection_args={"host": "milvus", "port": 19530, "user": "root", "password": "new-value"}
            )
        )
    )
    monkeypatch.setattr(mod, "stage_settings", lambda *a, **k: new_settings)
    seen = {}

    @contextmanager
    def connection(settings):
        seen["current"] = settings.vector_stores.milvus.connection_args["password"]
        yield MagicMock()

    monkeypatch.setattr(mod, "_milvus", connection)
    monkeypatch.setattr(
        mod,
        "_milvus_password_once",
        lambda client, user, old, new: seen.update(user=user, old=old, new=new),
    )
    mod.verify_component(session, "milvus")
    assert seen == {"current": "Milvus", "user": "root", "old": "Milvus", "new": "new-value"}


def test_whole_plan_preflight_refuses_later_dual_auth_before_any_native_write(native_attempt, monkeypatch):
    mod, old, _new, record = native_attempt
    monkeypatch.setattr(
        mod,
        "authentication_status",
        lambda settings, component: "OK" if settings is old or component == "milvus" else "DENIED",
    )
    with pytest.raises(CredentialConfigurationError, match="whole-plan authentication preflight"):
        mod.preflight_identities("session")
    record.assert_not_called()


def test_whole_plan_preflight_is_read_only_and_accepts_known_native_states(native_attempt):
    mod, _, _, record = native_attempt
    assert set(mod.preflight_identities("session").values()) == {"APPLY"}
    record.assert_not_called()
