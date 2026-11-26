"""Explicit native credential maintenance with bounded, authentication-specific probes.

Clients are deliberately independent of the application context: intermediate
credentials may differ across components during a paused maintenance window.
No Docker access or business database models are imported here.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import unquote, urlparse

from bisheng.core.config.credential_rotation import (
    credentials,
    read_journal,
    read_plan,
    record_account,
    record_component,
    resume_decision,
)
from bisheng.core.config.credential_tool import check_bundle
from bisheng.core.config.secret_crypto import CredentialConfigurationError


def _unsupported(reason):
    raise CredentialConfigurationError("rotation: " + reason)


@contextmanager
def _quiet_drivers():
    previous = logging.root.manager.disable
    logging.disable(max(previous, logging.CRITICAL))
    try:
        yield
    finally:
        logging.disable(previous)


def classify_failure(component, error):
    """Only explicit credential rejection is DENIED; permission/network is UNKNOWN."""
    if component == "mysql":
        from sqlalchemy.exc import OperationalError

        if isinstance(error, OperationalError) and getattr(error.orig, "args", ())[:1] == (1045,):
            return "DENIED"
    elif component == "redis":
        from redis.exceptions import AuthenticationError

        if isinstance(error, AuthenticationError):
            return "DENIED"
    elif component == "minio":
        from minio.error import S3Error

        if isinstance(error, S3Error) and error.code in {"SignatureDoesNotMatch", "InvalidAccessKeyId"}:
            return "DENIED"
    elif component in {"elasticsearch", "telemetry_elasticsearch"}:
        from elasticsearch import AuthenticationException

        if isinstance(error, AuthenticationException) and error.status_code == 401:
            return "DENIED"
    elif component == "milvus":
        import grpc
        from pymilvus.exceptions import MilvusException

        if isinstance(error, grpc.RpcError) and error.code() == grpc.StatusCode.UNAUTHENTICATED:
            return "DENIED"
        if isinstance(error, MilvusException) and error.code in {401, 40100}:
            return "DENIED"
    return "UNKNOWN"


# Milvus stores this exact value when authorization is first enabled and
# common.security.defaultRootPassword is empty. It is the server's own
# initial root password, not a candidate list.
_MILVUS_BUILTIN_ROOT_PASSWORD = "Milvus"


def _milvus_initializing(session):
    """True when the captured server has authentication off.

    Password rotation then initializes root from the staged user.yaml. An
    already authenticated server keeps the update_password path.
    """
    from pathlib import Path

    from bisheng.core.config.credential_rotation import _json

    path = Path(session) / "inventory.json"
    if not path.is_file():
        return False
    return _json(path).get("milvus_auth_enabled") is False


def _captured_milvus_root_password(session):
    """Password already stored for root, if initialization did not replace it."""
    from pathlib import Path

    import yaml

    from bisheng.core.config.credential_rotation import _json

    inventory = _json(Path(session) / "inventory.json")
    raw = (inventory.get("native_files") or {}).get("milvus.yaml") or ""
    document = yaml.safe_load(raw) or {}
    password = ((document.get("common") or {}).get("security") or {}).get("defaultRootPassword")
    if isinstance(password, str) and password:
        return password
    return _MILVUS_BUILTIN_ROOT_PASSWORD


def _replace_preexisting_milvus_root(session, new_settings):
    """defaultRootPassword does not change a root user already stored in etcd."""
    args = dict(new_settings.vector_stores.milvus.connection_args or {})
    new_password = args.get("password") or (args.get("token") or "").partition(":")[2]
    if not new_password:
        _unsupported("milvus: new root password is missing")
    current = _captured_milvus_root_password(session)
    if current == new_password:
        return
    prior_args = dict(args)
    prior_args.pop("token", None)
    prior_args["user"] = "root"
    prior_args["password"] = current
    prior = SimpleNamespace(vector_stores=SimpleNamespace(milvus=SimpleNamespace(connection_args=prior_args)))
    with _milvus(prior) as client:
        _milvus_password_once(client, "root", current, new_password)


def _milvus_version(version):
    import pymilvus

    if str(version).removeprefix("v") != "2.5.10" or pymilvus.__version__ != "2.6.15":
        _unsupported("Milvus server/SDK native adapter version has not been validated")
    return {"server_version": version, "sdk_version": pymilvus.__version__}


def milvus_args(settings):
    args = dict(settings.vector_stores.milvus.connection_args or {})
    if not (args.get("token") or (args.get("user") and args.get("password"))):
        _unsupported("milvus requires a current authenticated identity; default passwords are never guessed")
    host, port = args.pop("host", None), args.pop("port", None)
    if not host or not port:
        _unsupported("milvus endpoint is incomplete")
    args["uri"] = f"{'https' if args.get('secure') else 'http'}://{host}:{port}"
    args["timeout"] = 5
    return args


@contextmanager
def _mysql(settings):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    if make_url(settings.database_url).get_backend_name() != "mysql":
        _unsupported("only standard managed MySQL is supported; DM/external databases require separate maintenance")
    options = settings.database_pool.as_engine_kwargs()
    options.setdefault("connect_args", {})["connect_timeout"] = 5
    engine = create_engine(settings.database_url, **options)
    try:
        with engine.connect() as conn:
            yield conn
    finally:
        engine.dispose()


@contextmanager
def _redis(settings):
    from redis import Redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    value = settings.redis_url
    if isinstance(value, str):
        url, options = value, {}
    elif isinstance(value, dict) and value.get("mode") == "single":
        options = dict(value)
        options.pop("mode")
        url = options.pop("url")
    else:
        _unsupported("only standard single Redis is supported")
    options.update(socket_timeout=5, socket_connect_timeout=5, retry_on_timeout=False, retry=Retry(NoBackoff(), 0))
    client = Redis.from_url(url, **options)
    try:
        yield client
    finally:
        client.close()


def _minio(settings):
    import urllib3
    from minio import Minio

    conf = settings.object_storage.minio
    pool = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=5, read=5),
        retries=False,
        cert_reqs="CERT_REQUIRED" if conf.cert_check else "CERT_NONE",
    )
    client = Minio(
        conf.endpoint,
        access_key=conf.access_key,
        secret_key=conf.secret_key,
        secure=conf.secure,
        cert_check=conf.cert_check,
        http_client=pool,
    )

    class ManagedClient:
        # S3Error is a frozen dataclass in the shipped SDK. A generator-based
        # contextmanager assigns __traceback__ and masks authentication errors.
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc_value, traceback):
            pool.clear()
            return False

    return ManagedClient()


@contextmanager
def _es(settings, component):
    from elasticsearch import Elasticsearch

    conf = settings.vector_stores.elasticsearch if component == "elasticsearch" else settings.telemetry_elasticsearch
    options = dict(conf.ssl_verify)
    options.update(request_timeout=5, max_retries=0, retry_on_timeout=False)
    client = Elasticsearch(conf.elasticsearch_url, **options)
    try:
        yield client
    finally:
        client.close()


@contextmanager
def _milvus(settings):
    from pymilvus import MilvusClient

    client = MilvusClient(**milvus_args(settings))
    try:
        yield client
    finally:
        client.close()


def _probe(settings, component):
    if component == "mysql":
        from sqlalchemy import text

        with _mysql(settings) as conn:
            conn.execute(text("SELECT 1"))
    elif component == "redis":
        with _redis(settings) as client:
            client.ping()
    elif component == "minio":
        with _minio(settings) as client:
            client.list_buckets()
    elif component in {"elasticsearch", "telemetry_elasticsearch"}:
        with _es(settings, component) as client:
            client.info()
    elif component == "milvus":
        with _milvus(settings) as client:
            client.list_collections(timeout=5)
    else:
        _unsupported("unknown target")


def authentication_status(settings, component):
    with _quiet_drivers():
        try:
            _probe(settings, component)
            return "OK"
        except Exception as error:
            return classify_failure(component, error)


def validate_redis_acl(lines, username):
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        _unsupported("Redis ACL cannot be captured")
    if any(any(char in line for char in ("\\", "'", '"', "\r", "\n")) for line in lines):
        _unsupported("quoted Redis ACL requires explicit validated adaptation")
    if sum(line.split()[:2] == ["user", username] for line in lines) != 1:
        _unsupported("Redis ACL target is missing or ambiguous")
    return "\n".join(lines) + "\n"


def mysql_local_decision(evidence):
    decision = resume_decision(evidence.get("new", "UNKNOWN"), evidence.get("old", "UNKNOWN"))
    if decision not in {"APPLY", "PERSIST"}:
        _unsupported("MySQL socket identity is unverified; preserve the maintenance state")
    return decision


def capture_runtime(settings, selected, inventory):
    """Read-only permission/identity evidence; never modify account data."""
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    result = {"version": 1, "capabilities": {}, "native_files": {}}
    with _quiet_drivers():
        for component in selected:
            if not (component == "milvus" and inventory.get("milvus_auth_enabled") is False):
                if authentication_status(settings, component) != "OK":
                    _unsupported(component + ": current identity cannot be verified")
            if component == "mysql":
                if make_url(settings.database_url).username != "root" or inventory.get("mysql_socket_old") != "OK":
                    _unsupported("standard managed MySQL root/socket identity required")
                with _mysql(settings) as conn:
                    version = str(conn.execute(text("SELECT VERSION()")).scalar_one())
                    if version != "8.0.43":
                        _unsupported("MySQL native entrypoint version has not been validated")
                    hosts = sorted(conn.execute(text("SELECT Host FROM mysql.user WHERE User='root'")).scalars().all())
                    grants = " ".join(row[0] for row in conn.execute(text("SHOW GRANTS FOR CURRENT_USER()")))
                    if hosts != ["%", "localhost"] or not (
                        "ALL PRIVILEGES ON *.*" in grants or ("CREATE USER" in grants and "SYSTEM_USER" in grants)
                    ):
                        _unsupported("MySQL managed account layout/privileges unsupported")
                    result["capabilities"][component] = {"hosts": hosts, "version": version}
            elif component == "redis":
                if inventory.get("redis_group_drop_supported") is not True:
                    _unsupported("Redis native privilege drop has not been verified")
                value = settings.redis_url
                username = (
                    unquote(urlparse(value).username or "default")
                    if isinstance(value, str)
                    else value.get("username") or unquote(urlparse(value.get("url", "")).username or "default")
                )
                if (
                    username != "default"
                    or urlparse(value if isinstance(value, str) else value.get("url", "")).scheme != "redis"
                    or urlparse(value if isinstance(value, str) else value.get("url", "")).port not in (None, 6379)
                ):
                    _unsupported("only the validated Redis default-user health contract is supported")
                with _redis(settings) as client:
                    if client.info("server").get("redis_version") != "7.0.4":
                        _unsupported("Redis native version has not been validated")
                    lines = [x.decode() if isinstance(x, bytes) else x for x in client.acl_list()]
                    dryrun = client.execute_command("ACL", "DRYRUN", username, "ACL", "SETUSER", username, "resetpass")
                    if dryrun not in (b"OK", "OK"):
                        _unsupported("Redis ACL management permission required")
                    result["native_files"]["redis-users.acl"] = validate_redis_acl(lines, username)
                    result["capabilities"][component] = {"username": username}
            elif component in {"elasticsearch", "telemetry_elasticsearch"}:
                conf = (
                    settings.vector_stores.elasticsearch
                    if component == "elasticsearch"
                    else settings.telemetry_elasticsearch
                )
                auth = conf.ssl_verify.get("basic_auth")
                if not auth or not auth[0] or not auth[1]:
                    _unsupported(component + ": authenticated managed identity required")
                with _es(settings, component) as client:
                    if client.info().get("version", {}).get("number") != "8.12.0":
                        _unsupported(component + ": native version has not been validated")
                    privileges = client.security.has_privileges(cluster=["manage_security"])
                    if not privileges.get("has_all_requested"):
                        _unsupported(component + ": management permission required")
                result["capabilities"][component] = {"username": auth[0]}
            elif component == "minio":
                if "RELEASE.2023-03-20T20-16-18Z" not in inventory.get("minio_version", ""):
                    _unsupported("MinIO native entrypoint version has not been validated")
                conf = settings.object_storage.minio
                if inventory.get("minio_root_user") != conf.access_key:
                    _unsupported("MinIO configured identity is not the managed root identity")
                args = settings.vector_stores.milvus.connection_args or {}
                if inventory.get("milvus_auth_enabled") is True:
                    if authentication_status(settings, "milvus") != "OK":
                        _unsupported("MinIO consumer Milvus identity is unverified")
                elif inventory.get("milvus_auth_enabled") is False and not (args.get("password") or args.get("token")):
                    # Preserve explicitly captured unauthenticated consumers;
                    # no default root credentials are guessed or enabled.
                    from pymilvus import MilvusClient

                    client = MilvusClient(
                        uri=f"{'https' if args.get('secure') else 'http'}://{args.get('host')}:{args.get('port')}",
                        timeout=5,
                    )
                    try:
                        client.list_collections(timeout=5)
                    finally:
                        client.close()
                else:
                    _unsupported("MinIO consumer authentication mode is unknown")
                result["capabilities"][component] = {"username": conf.access_key}
            elif component == "milvus":
                if inventory.get("milvus_auth_enabled") is False:
                    # Authentication is off. Recreate can initialize a missing
                    # root from the staged defaultRootPassword. An existing root
                    # user is updated during verify, because this file does not
                    # replace a credential already stored in etcd.
                    from pymilvus import MilvusClient

                    args = dict(settings.vector_stores.milvus.connection_args or {})
                    host, port = args.get("host"), args.get("port")
                    if not host or not port:
                        _unsupported("milvus endpoint is incomplete")
                    client = MilvusClient(
                        uri=f"{'https' if args.get('secure') else 'http'}://{host}:{port}",
                        timeout=5,
                    )
                    try:
                        version = client.get_server_version(timeout=5)
                    finally:
                        client.close()
                    result["capabilities"][component] = {
                        "username": "root",
                        "mode": "initialize",
                        **_milvus_version(version),
                    }
                else:
                    args = milvus_args(settings)
                    if inventory.get("milvus_auth_enabled") is not True:
                        _unsupported("Milvus authentication/current management identity cannot be verified")
                    user = args.get("user") or args["token"].partition(":")[0]
                    if user != "root":
                        _unsupported("only the validated managed Milvus root identity is supported")
                    with _milvus(settings) as client:
                        version = client.get_server_version(timeout=5)
                    result["capabilities"][component] = {"username": user, **_milvus_version(version)}
    return result


def stage_settings(session, component, *, new, key_file=None):
    from pathlib import Path

    plan = read_plan(session, key_file=key_file)
    path = plan["stages"][component] if new else plan["source"]
    return check_bundle(path, env_file=Path(session) / "env.before")[0]


def _change_mysql(session, old, new, evidence):
    from sqlalchemy import text

    remote = resume_decision(authentication_status(new, "mysql"), authentication_status(old, "mysql"))
    local = mysql_local_decision(evidence)
    if remote not in {"APPLY", "PERSIST"}:
        _unsupported("MySQL TCP identity is unverified")
    admin = new if remote == "PERSIST" else old
    new_password = credentials(new)["mysql"]
    with _mysql(admin) as conn:
        if local == "APPLY":
            record_account(session, "mysql", "root@localhost", "INTENT")
            conn.execute(text("ALTER USER 'root'@'localhost' IDENTIFIED BY :password"), {"password": new_password})
        if remote == "APPLY":
            record_account(session, "mysql", "root@%", "INTENT")
            conn.execute(text("ALTER USER 'root'@'%' IDENTIFIED BY :password"), {"password": new_password})
        conn.commit()


def _milvus_password_once(client, user, old_password, new_password):
    import inspect

    # The SDK retry decorator prioritizes timeout over retry_times, so passing
    # retry_times=0 still retries uncertain writes. Use its original prepared
    # RPC implementation (same auth channel/status checks), without decorators.
    connection = client._get_connection()
    method = inspect.unwrap(type(connection).update_password)
    method(connection, user, old_password, new_password, timeout=5)


def preflight_identities(session, *, key_file=None):
    """Reject ambiguous authentication for the whole selection before any writes."""
    plan = read_plan(session, key_file=key_file)
    journal = read_journal(session)
    decisions = {}
    for component in plan["selected"]:
        old = stage_settings(session, component, new=False, key_file=key_file)
        new = stage_settings(session, component, new=True, key_file=key_file)
        phase = journal.get("components", {}).get(component, {}).get("phase", "PENDING")
        # Before recreate, an unauthenticated Milvus accepts connections with
        # any password, so the old/new probe cannot decide APPLY vs PERSIST.
        if component == "milvus" and _milvus_initializing(session) and phase in {"PENDING", "CHANGE_INTENT"}:
            decision = "APPLY"
        else:
            decision = resume_decision(authentication_status(new, component), authentication_status(old, component))
        if decision not in {"APPLY", "PERSIST"} or (phase == "FILES_PERSISTED" and decision != "PERSIST"):
            _unsupported(component + ": whole-plan authentication preflight failed; no further account writes")
        decisions[component] = decision
    return decisions


def change_component(session, component, *, evidence=None, key_file=None, apply=False):
    """Return the host action; MinIO root changes require host recreation, not IAM."""
    if not apply:
        _unsupported("explicit apply is required")
    plan = read_plan(session, key_file=key_file)
    journal = read_journal(session)
    if (
        component not in plan["selected"]
        or not journal["consumers_stopped"]
        or journal["phase"] not in {"CONSUMERS_STOPPED", "CHANGING"}
    ):
        _unsupported("confirmed maintenance and paused consumers required")
    old = stage_settings(session, component, new=False, key_file=key_file)
    new = stage_settings(session, component, new=True, key_file=key_file)
    initializing = component == "milvus" and _milvus_initializing(session)
    with _quiet_drivers():
        if initializing:
            decision = "APPLY"
        else:
            decision = resume_decision(authentication_status(new, component), authentication_status(old, component))
        record_component(session, component, "CHANGE_INTENT")
        if component == "mysql":
            _change_mysql(session, old, new, evidence or {})
        elif decision == "APPLY":
            # Redis/MinIO: no live process mutation before recreate. Option C mounts
            # redis-users.acl read-only; acl_setuser would leave in-memory auth ≠
            # file/health secret and break whole-plan resume preflight. Staged ACL
            # takes effect on host recreate (same recreate-only pattern as MinIO).
            # Unauthenticated Milvus is the same shape: the staged user.yaml both
            # enables authorization and initializes root. update_password needs a
            # current identity, which does not exist until that recreate.
            if component in {"elasticsearch", "telemetry_elasticsearch"}:
                password = credentials(new)[component]
                conf = old.vector_stores.elasticsearch if component == "elasticsearch" else old.telemetry_elasticsearch
                with _es(old, component) as client:
                    client.security.change_password(username=conf.ssl_verify["basic_auth"][0], password=password)
            elif component == "milvus" and not initializing:
                args = milvus_args(old)
                user = args.get("user") or args["token"].partition(":")[0]
                with _milvus(old) as client:
                    _milvus_password_once(client, user, credentials(old)["milvus"], credentials(new)["milvus"])
            elif component not in {"minio", "redis", "milvus"}:
                _unsupported("unsupported component")
        elif decision != "PERSIST":
            _unsupported("native identity is unknown or accepts both credentials; do not retry")
    # The host updates native mounts and recreates only the approved dependency
    # set. Even an acknowledged RPC is not a final verification checkpoint.
    return "RECREATE"


def verify_component(session, component, *, evidence=None, key_file=None):
    old = stage_settings(session, component, new=False, key_file=key_file)
    new = stage_settings(session, component, new=True, key_file=key_file)
    if component == "milvus" and _milvus_initializing(session):
        # A new data directory accepts defaultRootPassword. An existing root
        # user keeps its stored password until update_password replaces it.
        if authentication_status(new, component) != "OK":
            _replace_preexisting_milvus_root(session, new)
        if authentication_status(new, component) != "OK":
            _unsupported(component + ": initialized root password is not usable")
    elif resume_decision(authentication_status(new, component), authentication_status(old, component)) != "PERSIST":
        _unsupported(component + ": new identity/old rejection not verified")
    if component == "mysql":
        if mysql_local_decision(evidence or {}) != "PERSIST":
            _unsupported("MySQL local account is not verified")
        for account in ("root@localhost", "root@%"):
            record_account(session, component, account, "VERIFIED")
    record_component(session, component, "NATIVE_VERIFIED")
