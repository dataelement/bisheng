"""Prepare immutable deployment artifacts; never change a service or account."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse, urlunparse

import yaml
from sqlalchemy.engine import make_url

from bisheng.core.config.credential_inputs import COMPONENTS, is_weak, read_inputs, write_private
from bisheng.core.config.credential_loader import dump_document, load_config
from bisheng.core.config.secret_crypto import CredentialConfigurationError, CredentialDecryptionError, load_keyring


def _object(value, field):
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                raise CredentialConfigurationError(f"{field}: invalid object") from None
    if not isinstance(value, dict):
        raise CredentialConfigurationError(f"{field}: object required")
    return dict(value)


def _plain(value, ring, legacy=False):
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise CredentialConfigurationError("credential: text required")
    if value.startswith("encrypt("):
        if not value.endswith(")"):
            raise CredentialConfigurationError("credential: invalid encrypted value")
        return ring.decrypt(value[8:-1])
    if legacy:
        return value
    raise CredentialConfigurationError("credential: encrypted value required")


def _seal(value, ring, original=None, wrapped=True):
    if not value:
        return ""
    candidate = (
        original[8:-1]
        if isinstance(original, str) and original.startswith("encrypt(") and original.endswith(")")
        else original
    )
    if candidate:
        try:
            if ring.decrypt_primary(candidate) == value:
                return original
        except CredentialDecryptionError:
            pass  # Already decrypted by a retiring key; re-encrypt with primary.
    token = ring.encrypt(value).decode()
    return f"encrypt({token})" if wrapped else token


def _redis(value, ring, replacement, legacy, sentinel_replacement=None):
    if isinstance(value, dict):
        result = dict(value)
        if result.get("url"):
            if result.get("password"):
                raise CredentialConfigurationError("redis: URL and object password conflict")
            result["url"], plain = _redis(result["url"], ring, replacement, legacy)
        else:
            old = result.get("password")
            plain = replacement if replacement is not None else _plain(old, ring, legacy)
            result["password"] = _seal(plain, ring, old)
        if result.get("sentinel_password") or sentinel_replacement is not None:
            old = result.get("sentinel_password")
            selected = sentinel_replacement if sentinel_replacement is not None else _plain(old, ring, legacy)
            result["sentinel_password"] = _seal(selected, ring, old)
        return result, plain
    if not isinstance(value, str):
        raise CredentialConfigurationError("redis: source URL required")
    try:
        parsed = urlparse(value)
        old = parsed.password
        plain = replacement if replacement is not None else (ring.decrypt(old) if old else "")
        if not plain:
            return value, ""
        host = parsed.netloc.rpartition("@")[2]
        username = parsed.netloc.rpartition("@")[0].partition(":")[0] if "@" in parsed.netloc else ""
        encoded = _seal(plain, ring, old, wrapped=False)
        return urlunparse(parsed._replace(netloc=f"{username}:{encoded}@{host}")), plain
    except (ValueError, TypeError):
        raise CredentialConfigurationError("redis: invalid source credential or URL") from None


def _es(conf, ring, replacement, legacy):
    conf = dict(conf)
    options = _object(conf.get("ssl_verify", {}), "elasticsearch.ssl_verify")
    parsed = urlparse(conf.get("url") or conf.get("elasticsearch_url") or "")
    existing = options.get("basic_auth")
    if existing is not None and (not isinstance(existing, (list, tuple)) or len(existing) != 2):
        raise CredentialConfigurationError("elasticsearch: invalid basic_auth")
    username = existing[0] if existing else (unquote(parsed.username) if parsed.username else "elastic")
    old = existing[1] if existing else None
    url_secret = unquote(parsed.password) if parsed.password is not None else None
    if existing and url_secret is not None:
        raise CredentialConfigurationError("elasticsearch: conflicting authentication sources")
    if replacement:
        selected = replacement.get("username", username)
        if existing and selected != username:
            raise CredentialConfigurationError("elasticsearch: account changes are outside password rotation")
        username, password = selected, replacement["password"]
    else:
        password = _plain(old, ring, legacy) if existing else (url_secret or "")
    if parsed.username is not None:
        conf["url"] = urlunparse(parsed._replace(netloc=parsed.netloc.rpartition("@")[2]))
    if password:
        options["basic_auth"] = [username, _seal(password, ring, old)]
    else:
        options.pop("basic_auth", None)
    conf["ssl_verify"] = options
    return conf, password


def _yaml(text):
    return yaml.safe_dump(text, allow_unicode=True, sort_keys=False)


def _client_option(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _native(data, plain, milvus_login, deployment_root=None):
    db = make_url(data["database_url"])
    files = {}
    if db.drivername.startswith("mysql"):
        files["mysql.password"] = plain["mysql"]
        files["mysql-client.cnf"] = (
            "[client]\nuser="
            + _client_option(db.username or "root")
            + "\npassword="
            + _client_option(plain["mysql"])
            + "\n"
        )
        tls = data.get("database_pool", {}).get("ssl", {})
        if tls.get("enabled"):
            mode = "VERIFY_IDENTITY" if tls.get("verify_hostname", True) else "VERIFY_CA"
            files["mysql-client.cnf"] += "ssl-mode=" + mode + "\n"
            for source, option in (("ca_file", "ssl-ca"), ("cert_file", "ssl-cert"), ("key_file", "ssl-key")):
                if tls.get(source):
                    files["mysql-client.cnf"] += option + "=" + _client_option(tls[source]) + "\n"
        host = db.host or "mysql"
        if ":" in host:
            host = f"[{host}]"
        dsn = f"{db.username or 'root'}:{plain['mysql']}@tcp({host}:{db.port or 3306})/openfga?parseTime=true"
        if tls.get("enabled"):
            dsn += "&tls=true"
        files["openfga.yaml"] = _yaml({"datastore": {"engine": "mysql", "uri": dsn}})
    if plain.get("redis"):
        files["redis.password"] = plain["redis"]
        digest = hashlib.sha256(plain["redis"].encode()).hexdigest()
        files["redis-users.acl"] = f"user default on #{digest} ~* &* +@all\n"
    minio = data.get("object_storage", {}).get("minio", {})
    if plain.get("minio"):
        files["minio.password"] = plain["minio"]
        files["minio.user"] = minio.get("access_key") or ""
    for name in ("elasticsearch", "telemetry_elasticsearch"):
        if plain.get(name):
            files[name + ".password"] = plain[name]
    endpoint = minio.get("endpoint", "minio:9000")
    parsed_endpoint = urlparse("//" + endpoint)
    files["milvus.yaml"] = _yaml(
        {
            "common": {
                "security": {"authorizationEnabled": bool(milvus_login), "defaultRootPassword": milvus_login or ""}
            },
            "minio": {
                "address": parsed_endpoint.hostname or "minio",
                "port": parsed_endpoint.port or 9000,
                "useSSL": minio.get("schema", minio.get("secure", False)),
                "accessKeyID": minio.get("access_key") or "",
                "secretAccessKey": plain.get("minio", ""),
            },
        }
    )
    if deployment_root:
        gateway = Path(deployment_root) / "gateway/config/application.yml"
        if gateway.exists():
            try:
                config = yaml.safe_load(gateway.read_text())
                redis = config.setdefault("spring", {}).setdefault("data", {}).setdefault("redis", {})
                redis["password"] = plain.get("redis", "")
                files["gateway-application.yml"] = _yaml(config)
            except (OSError, ValueError, yaml.YAMLError, AttributeError):
                raise CredentialConfigurationError("gateway: invalid source configuration") from None
    return files


def _rotate_acl(source, username, password):
    # Only the simple native ACL syntax is transformed automatically. Quoted
    # or escaped tokens require a validated administrator-supplied ACL rather
    # than a lossy parser changing permissions.
    if any(char in source for char in ("\\", "'", '"')):
        raise CredentialConfigurationError("redis: quoted ACL requires explicit native migration")
    result = []
    found = False
    digest = hashlib.sha256(password.encode()).hexdigest()
    for line in source.splitlines():
        tokens = line.split()
        if len(tokens) >= 2 and tokens[:2] == ["user", username]:
            if found:
                raise CredentialConfigurationError("redis: duplicate ACL identity")
            found = True
            rules = [
                token
                for token in tokens[2:]
                if token not in {"nopass", "resetpass"} and not token.startswith(("#", ">", "<", "!"))
            ]
            result.append(" ".join(["user", username, *rules, "#" + digest]))
        else:
            result.append(line)
    if not found:
        raise CredentialConfigurationError("redis: target ACL identity missing")
    return "\n".join(result) + "\n"


def prepare_bundle(
    *,
    key_file,
    out_dir,
    mode="fresh",
    config=None,
    inputs=None,
    base_bundle=None,
    component=None,
    environ=None,
    env_file=None,
    deployment_root=None,
    runtime_env_file=None,
):
    if mode not in {"fresh", "adopt-key", "password-change", "key-rotation"}:
        raise CredentialConfigurationError("prepare: unknown mode")
    out = Path(out_dir).absolute()
    backend = Path(__file__).resolve().parents[3]
    if out.resolve().is_relative_to(backend) or Path(key_file).resolve().is_relative_to(backend):
        raise CredentialConfigurationError("prepare: secrets must remain outside backend build context")
    if out.exists() or out.is_symlink():
        raise CredentialConfigurationError("prepare: output directory already exists")
    incremental = mode in {"password-change", "key-rotation"}
    if incremental and (not base_bundle or config):
        raise CredentialConfigurationError("prepare: incremental mode requires only base-bundle")
    if not incremental and (not config or base_bundle):
        raise CredentialConfigurationError("prepare: source config required")
    if mode == "password-change" and component not in COMPONENTS:
        raise CredentialConfigurationError("prepare: explicit component required")
    if mode != "password-change" and component:
        raise CredentialConfigurationError("prepare: component is only valid for password-change")
    ring = load_keyring(key_file)
    supplied = read_inputs(inputs)
    if inputs and mode in {"adopt-key", "key-rotation"}:
        raise CredentialConfigurationError("prepare: this mode preserves actual passwords; inputs not permitted")
    targets = set(supplied) if mode == "fresh" else ({component} if mode == "password-change" else set())
    if mode == "fresh" and not set(COMPONENTS[:5]).issubset(supplied):
        raise CredentialConfigurationError("prepare: all base component inputs required")
    if mode == "password-change" and set(supplied) != {component}:
        raise CredentialConfigurationError("prepare: only selected component input required")
    source = Path(base_bundle) / "config.yaml" if incremental else Path(config)
    if runtime_env_file is not None:
        if mode != "adopt-key":
            raise CredentialConfigurationError("prepare: runtime snapshot is only valid for legacy adoption")
        try:
            values = json.loads(Path(runtime_env_file).read_text())
            if not isinstance(values, list):
                raise ValueError
            runtime = dict(os.environ if environ is None else environ)
            seen = set()
            for value in values:
                if not isinstance(value, str) or "=" not in value:
                    raise ValueError
                name, content = value.split("=", 1)
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in seen:
                    raise ValueError
                seen.add(name)
                runtime[name] = content
            environ = runtime
        except (OSError, ValueError, TypeError):
            raise CredentialConfigurationError("prepare: invalid runtime environment snapshot") from None
    document = load_config(source, environ=environ, env_file=env_file)
    data = copy.deepcopy(document.data)
    legacy = mode == "adopt-key"
    pending = set()
    try:
        db = make_url(data["database_url"])
        db_password = supplied["mysql"]["password"] if "mysql" in targets else ring.decrypt(db.password)
        data["database_url"] = db.set(password=_seal(db_password, ring, db.password, wrapped=False)).render_as_string(
            hide_password=False
        )
        plain = {"mysql": db_password}
        redis_replacement = supplied["redis"]["password"] if "redis" in targets else None
        for name in ("redis_url", "celery_redis_url"):
            data[name], password = _redis(
                data.get(name),
                ring,
                redis_replacement,
                legacy,
                supplied.get("redis", {}).get("sentinel_password") if "redis" in targets else None,
            )
            if "redis" in plain and plain["redis"] != password:
                raise CredentialConfigurationError("redis: consumers have inconsistent credentials")
            plain["redis"] = password
        objects = data.setdefault("object_storage", {}).setdefault("minio", {})
        old = objects.get("secret_key")
        minio = supplied.get("minio") if "minio" in targets else None
        plain["minio"] = minio["secret_key"] if minio else _plain(old, ring, legacy)
        if minio and minio.get("access_key"):
            if mode == "password-change" and objects.get("access_key") != minio["access_key"]:
                raise CredentialConfigurationError("minio: account changes are outside password rotation")
            objects["access_key"] = minio["access_key"]
        objects["secret_key"] = _seal(plain["minio"], ring, old)
        vectors = data.setdefault("vector_stores", {})
        es, plain["elasticsearch"] = _es(
            vectors.get("elasticsearch", {}),
            ring,
            supplied.get("elasticsearch") if "elasticsearch" in targets else None,
            legacy,
        )
        vectors["elasticsearch"] = es
        if data.get("telemetry_elasticsearch", {}).get("url"):
            if mode == "fresh" and "telemetry_elasticsearch" not in supplied:
                raise CredentialConfigurationError("telemetry_elasticsearch: explicit credential input required")
            data["telemetry_elasticsearch"], plain["telemetry_elasticsearch"] = _es(
                data["telemetry_elasticsearch"],
                ring,
                supplied.get("telemetry_elasticsearch") if "telemetry_elasticsearch" in targets else None,
                legacy,
            )
        args = _object(vectors.setdefault("milvus", {}).get("connection_args"), "milvus.connection_args")
        if args.get("token") and (args.get("password") or args.get("user")):
            raise CredentialConfigurationError("milvus: conflicting authentication sources")
        old_login = args.get("user") or (
            _plain(args["token"], ring, legacy).partition(":")[0] if args.get("token") else None
        )
        if "milvus" in targets:
            entry = supplied["milvus"]
            if entry.get("token"):
                login, _, milvus_password = entry["token"].partition(":")
                args.pop("password", None)
                args.pop("user", None)
                args["token"] = _seal(entry["token"], ring)
            else:
                login, milvus_password = entry.get("user", args.get("user") or "root"), entry["password"]
                if mode == "password-change" and args.get("user") and login != args["user"]:
                    raise CredentialConfigurationError("milvus: account changes are outside password rotation")
                args.pop("token", None)
                args["user"] = login
                args["password"] = _seal(milvus_password, ring, args.get("password"))
            if mode == "password-change" and old_login and login != old_login:
                raise CredentialConfigurationError("milvus: account changes are outside password rotation")
        elif args.get("token"):
            old_token = args["token"]
            token = _plain(old_token, ring, legacy)
            args["token"] = _seal(token, ring, old_token)
            _, _, milvus_password = token.partition(":")
        else:
            old = args.get("password")
            milvus_password = _plain(old, ring, legacy)
            args["password"] = _seal(milvus_password, ring, old)
        vectors["milvus"]["connection_args"] = args
        plain["milvus"] = milvus_password
        if any(any(char in value for char in ("\r", "\n", "\x00")) for value in plain.values()):
            raise CredentialConfigurationError("prepare: native credentials must be single-line")
        pending.update(name for name, value in plain.items() if is_weak(value, name))
        native = _native(data, plain, milvus_password, deployment_root)
        # Incremental operations must retain unrelated native configuration.
        if incremental:
            base = Path(base_bundle)
            manifest = json.loads((base / "manifest.json").read_text())
            related = {
                "mysql": {"mysql.password", "mysql-client.cnf", "openfga.yaml"},
                "redis": {"redis.password", "redis-users.acl", "gateway-application.yml"},
                "minio": {"minio.user", "minio.password", "milvus.yaml"},
                "elasticsearch": {"elasticsearch.password"},
                "telemetry_elasticsearch": {"telemetry_elasticsearch.password"},
                "milvus": {"milvus.yaml"},
            }.get(component, set())
            for filename in manifest.get("native_files", []):
                if Path(filename).name != filename:
                    raise CredentialConfigurationError("bundle: invalid native filename")
                if filename not in related:
                    native[filename] = (base / filename).read_text()
            if component == "redis":
                source_acl = base / "redis-users.acl"
                value = data["redis_url"]
                username = (
                    value.get("username", "default")
                    if isinstance(value, dict)
                    else (unquote(urlparse(value).username or "default"))
                )
                native["redis-users.acl"] = _rotate_acl(source_acl.read_text(), username, plain["redis"])
                gateway_file = base / "gateway-application.yml"
                if gateway_file.exists():
                    gateway = yaml.safe_load(gateway_file.read_text())
                    gateway["spring"]["data"]["redis"]["password"] = plain["redis"]
                    native["gateway-application.yml"] = _yaml(gateway)
            if component == "milvus":
                previous = yaml.safe_load((base / "milvus.yaml").read_text())
                security = previous.setdefault("common", {}).setdefault("security", {})
                security["authorizationEnabled"] = bool(milvus_password)
                security["defaultRootPassword"] = milvus_password
                native["milvus.yaml"] = _yaml(previous)

            if component == "minio":
                old_milvus = yaml.safe_load((base / "milvus.yaml").read_text())
                old_milvus["minio"]["secretAccessKey"] = plain["minio"]
                old_milvus["minio"]["accessKeyID"] = objects.get("access_key") or ""
                native["milvus.yaml"] = _yaml(old_milvus)
        # Preserve !env references outside the credential fields we own.
        owned = {
            ("database_url",),
            ("redis_url",),
            ("celery_redis_url",),
            ("object_storage", "minio", "secret_key"),
            ("object_storage", "minio", "access_key"),
            ("vector_stores", "milvus", "connection_args"),
            ("vector_stores", "elasticsearch", "ssl_verify"),
            ("vector_stores", "elasticsearch", "url"),
            ("telemetry_elasticsearch", "ssl_verify"),
            (
                "telemetry_elasticsearch",
                "url",
            ),
        }
        for location in () if runtime_env_file is not None else document.sources:
            if any(location[: len(prefix)] == prefix for prefix in owned):
                continue
            raw, target = document.raw, data
            for name in location[:-1]:
                raw = raw[int(name)] if isinstance(raw, list) else raw[name]
                target = target[int(name)] if isinstance(target, list) else target[name]
            name = location[-1]
            target[int(name) if isinstance(target, list) else name] = raw[int(name) if isinstance(raw, list) else name]
        out.mkdir(mode=0o700, parents=True, exist_ok=False)
        try:
            for name, content in native.items():
                write_private(out / name, content)
            write_private(out / "config.yaml", dump_document(data))
            write_private(
                out / "manifest.json",
                json.dumps(
                    {
                        "version": 1,
                        "revision": uuid.uuid4().hex,
                        "mode": mode,
                        "component": component,
                        "pending": sorted(pending),
                        "native_files": sorted(native),
                        "sources": {".".join(k): v for k, v in document.sources.items()},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        except Exception:
            shutil.rmtree(out)
            raise
    except CredentialConfigurationError:
        raise
    except (OSError, TypeError, ValueError, KeyError, yaml.YAMLError):
        raise CredentialConfigurationError("prepare: source configuration cannot be prepared") from None
    return out
