"""Offline credential preparation and explicitly requested read-only checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from cryptography.fernet import Fernet

from bisheng.core.config.credential_inputs import COMPONENTS, is_weak, read_inputs, write_private
from bisheng.core.config.secret_crypto import CredentialConfigurationError, get_keyring, load_keyring


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CredentialConfigurationError("arguments: invalid request; use --help")


def _fresh_generatable(data):
    """Allow only the shipped single-node endpoints without customer credentials."""
    # Fingerprint the delivered MySQL template URL (which has a legacy ciphertext),
    # never interpret arbitrary ciphertext on a local endpoint as an unset password.
    db = data.get("database_url", "")
    if isinstance(db, str) and (
        db == "mysql+pymysql://root@mysql:3306/bisheng?charset=utf8mb4"
        or hashlib.sha256(db.encode()).hexdigest() == "76de9e92169ca3b0c570ed53a8eb6bdb16022a485d0b84deb77aa6510a751ca2"
    ):
        yield "mysql"
    if data.get("redis_url") == "redis://redis:6379/1" and data.get("celery_redis_url") == "redis://redis:6379/2":
        yield "redis"
    storage = data.get("object_storage") or {}
    minio = storage.get("minio") or {}
    if storage.get("type") == "minio" and minio.get("endpoint") == "minio:9000" and not minio.get("secret_key"):
        yield "minio"
    vectors = data.get("vector_stores") or {}
    es = vectors.get("elasticsearch") or {}
    if (
        es.get("url") == "http://elasticsearch:9200"
        and set(es) <= {"url", "ssl_verify"}
        and es.get("ssl_verify", {}) in ({}, "{}")
    ):
        yield "elasticsearch"
    args = (vectors.get("milvus") or {}).get("connection_args")
    if isinstance(args, str):
        args = json.loads(args)
    if (
        isinstance(args, dict)
        and set(args) <= {"host", "port", "user", "password", "secure"}
        and args.get("host") == "milvus"
        and str(args.get("port")) == "19530"
        and args.get("user") in (None, "", "root")
        and not args.get("password")
    ):
        yield "milvus"


def redis_password(value):
    if isinstance(value, dict):
        return redis_password(value["url"]) if value.get("url") else value.get("password", "")
    return unquote(urlparse(value or "").password or "")


def check_bundle(bundle, *, enforce=False, component=None, environ=None, env_file=None):
    import yaml
    from sqlalchemy.engine import make_url

    from bisheng.core.config.credential_loader import load_config, validate_runtime

    root = Path(bundle).resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text())
    except (OSError, ValueError):
        raise CredentialConfigurationError("bundle: readable manifest required") from None
    if manifest.get("version") not in (1, 2) or not re.fullmatch(r"[0-9a-f]{32}", manifest.get("revision", "")):
        raise CredentialConfigurationError("bundle: invalid version or revision")
    names = manifest.get("native_files")
    if not isinstance(names, list) or any(not isinstance(name, str) or Path(name).name != name for name in names):
        raise CredentialConfigurationError("bundle: invalid file list")
    storage = manifest.get("native_storage")
    if storage == "plaintext" or manifest.get("version") == 1:
        physical = list(names)
    else:
        physical = ["native/" + role + ".sealed.json" for role in manifest.get("roles", [])]
    for filename in {"config.yaml", "manifest.json", *physical}:
        file = root / filename
        if file.is_symlink() or not file.is_file() or stat.S_IMODE(file.stat().st_mode) & 0o027:
            raise CredentialConfigurationError("bundle: missing or unsafe artifact")
    data = load_config(root / "config.yaml", environ=environ, env_file=env_file).data
    settings = validate_runtime(data)
    password = {
        "mysql": make_url(settings.database_url).password or "",
        "redis": redis_password(settings.redis_url),
        "minio": settings.object_storage.minio.secret_key if settings.object_storage.minio else "",
    }
    if redis_password(settings.celery_redis_url) != password["redis"]:
        raise CredentialConfigurationError("redis: consumers have inconsistent credentials")
    for name, conf in [
        ("elasticsearch", settings.vector_stores.elasticsearch),
        ("telemetry_elasticsearch", settings.telemetry_elasticsearch),
    ]:
        if conf.elasticsearch_url or name == "elasticsearch":
            auth = conf.ssl_verify.get("basic_auth")
            password[name] = auth[1] if auth else ""
    args = settings.vector_stores.milvus.connection_args or {}
    password["milvus"] = args.get("password") or (args.get("token") or "").partition(":")[2]
    password = {name: str(value or "") for name, value in password.items()}
    native_name = {
        "mysql": "mysql.password",
        "redis": "redis.password",
        "minio": "minio.password",
        "elasticsearch": "elasticsearch.password",
    }
    if not make_url(settings.database_url).drivername.startswith("mysql"):
        native_name.pop("mysql")
    try:
        from bisheng.core.config.credential_artifacts import bundle_native_files

        native_files = bundle_native_files(root, os.environ["BS_SECRET_KEYS_FILE"], allow_legacy=True)
        # The old key-adoption bundle described only the application config.
        # Reconstruct expectations in memory, never write legacy password files.
        if manifest["version"] == 1 and manifest.get("mode") == "adopt-key" and not names:
            from bisheng.core.config.credential_bundle import _native

            native_files = {k: v.encode() for k, v in _native(data, password, password["milvus"]).items()}
        for name, filename in native_name.items():
            if password.get(name) and native_files[filename].decode() != password[name]:
                raise CredentialConfigurationError(f"{name}: native and application credentials differ")
        if password.get("minio"):
            milvus_native = yaml.safe_load(native_files["milvus.yaml"])
            if (
                milvus_native["minio"]["secretAccessKey"] != password["minio"]
                or milvus_native["minio"]["accessKeyID"] != settings.object_storage.minio.access_key
            ):
                raise CredentialConfigurationError("milvus.minio: object-store credentials differ")
        from bisheng.core.config.credential_bundle import _native

        expected_native = _native(data, password, password["milvus"])
        for filename in ("mysql-client.cnf", "openfga.yaml", "minio.user"):
            if filename in expected_native and native_files[filename].decode() != expected_native[filename]:
                raise CredentialConfigurationError("bundle: native consumer credentials differ")
        if password.get("milvus"):
            native_milvus = yaml.safe_load(native_files["milvus.yaml"])
            security = native_milvus["common"]["security"]
            if not security.get("authorizationEnabled") or security.get("defaultRootPassword") != password["milvus"]:
                raise CredentialConfigurationError("milvus: native login credentials differ")
        if password.get("redis"):
            acl = native_files["redis-users.acl"].decode()
            if "#" + hashlib.sha256(password["redis"].encode()).hexdigest() not in acl.split():
                raise CredentialConfigurationError("redis: native ACL credential differs")
        if "gateway-application.yml" in native_files:
            gateway_config = yaml.safe_load(native_files["gateway-application.yml"])
            if gateway_config["spring"]["data"]["redis"].get("password", "") != password["redis"]:
                raise CredentialConfigurationError("gateway.redis: credentials differ")
    except (OSError, TypeError, KeyError, yaml.YAMLError):
        raise CredentialConfigurationError("bundle: native artifacts cannot be verified") from None
    pending = sorted(name for name, value in password.items() if is_weak(value, name))
    if manifest.get("es_security_enabled") is False:
        pending = sorted(set(pending) | {"elasticsearch"})
    if enforce and component:
        raise CredentialConfigurationError("check: component subset cannot enforce full deployment")
    if component and component not in password:
        raise CredentialConfigurationError("check: requested component not configured")
    return settings, manifest, pending


def _parser():
    parser = _Parser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    validate = sub.add_parser("validate-inputs")
    validate.add_argument("--inputs", type=Path, required=True)
    validate.add_argument("--key-file", type=Path)
    validate.add_argument("--allow-legacy-inputs", action="store_true")
    requirements = sub.add_parser("requirements")
    requirements.add_argument("--config", type=Path, required=True)
    requirements.add_argument("--env-file", type=Path)
    requirements.add_argument("--fresh-generatable", action="store_true", help=argparse.SUPPRESS)
    validate_key = sub.add_parser("validate-keyring")
    validate_key.add_argument("--key-file", type=Path, required=True)
    join = sub.add_parser("join-keyrings")
    join.add_argument("--primary-file", type=Path, required=True)
    join.add_argument("--retiring-file", type=Path, required=True)
    join.add_argument("--out", type=Path, required=True)
    key = sub.add_parser("keygen")
    key.add_argument("--out", type=Path, required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--mode", choices=["fresh", "adopt-key", "password-change", "key-rotation"], default="fresh")
    prepare.add_argument("--config", type=Path)
    prepare.add_argument("--inputs", type=Path)
    prepare.add_argument("--base-bundle", type=Path)
    prepare.add_argument("--component", choices=COMPONENTS)
    prepare.add_argument("--env-file", type=Path)
    prepare.add_argument("--runtime-env-file", type=Path)
    prepare.add_argument("--deployment-root", type=Path)
    prepare.add_argument("--key-file", type=Path, required=True)
    prepare.add_argument("--out-dir", type=Path, required=True)
    check = sub.add_parser("check")
    check.add_argument("--bundle", type=Path, required=True)
    check.add_argument("--key-file", type=Path, required=True)
    check.add_argument("--component", choices=COMPONENTS)
    check.add_argument("--env-file", type=Path)
    check.add_argument("--enforce", action="store_true")
    check.add_argument("--online", action="store_true")
    from bisheng.core.config.credential_rotation_cli import parser as rotation_parser

    rotation_parser(sub)
    from bisheng.core.config.credential_artifact_cli import parser as artifact_parser

    artifact_parser(sub)
    for name, child in sub.choices.items():
        if name != "artifact":
            child.add_argument("--deployment-id")
    return parser


def main(argv=None):
    created = None
    try:
        args = _parser().parse_args(argv)
        if getattr(args, "key_file", None):
            os.environ["BS_SECRET_KEYS_FILE"] = str(args.key_file.absolute())
            get_keyring.cache_clear()
        if getattr(args, "deployment_id", None):
            os.environ["BS_CREDENTIAL_DEPLOYMENT_ID"] = args.deployment_id
        if args.command == "artifact":
            from bisheng.core.config.credential_artifact_cli import execute

            return execute(args)
        if args.command == "rotation" and args.action in {"capabilities", "request-id", "request-components"}:
            from bisheng.core.config.credential_rotation_cli import execute

            return execute(args)
        if args.command == "join-keyrings":
            if args.out.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
                raise CredentialConfigurationError("keyring: output must remain outside backend build context")
            for path in (args.primary_file, args.retiring_file):
                load_keyring(path)
            primary = json.loads(args.primary_file.read_text())["keys"]
            retiring = json.loads(args.retiring_file.read_text())["keys"]
            write_private(args.out, json.dumps({"version": 1, "keys": list(dict.fromkeys([*primary, *retiring]))}))
            print("keyring: transition prepared")
            return 0
        if args.command == "validate-inputs":
            read_inputs(args.inputs, allow_plaintext=args.allow_legacy_inputs)
            print("inputs: validated")
            return 0
        if args.command == "requirements":
            from bisheng.core.config.credential_loader import load_config

            data = load_config(args.config, env_file=args.env_file).data
            if args.fresh_generatable:
                for component in _fresh_generatable(data):
                    print(component)
                return 0
            for component in COMPONENTS[:5]:
                print(component)
            telemetry = data.get("telemetry_elasticsearch") or {}
            if not isinstance(telemetry, dict):
                raise CredentialConfigurationError("telemetry_elasticsearch: configuration object required")
            if telemetry.get("url"):
                print("telemetry_elasticsearch")
            return 0
        if args.command == "keygen":
            path = args.out.absolute()
            if path.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
                raise CredentialConfigurationError("keygen: output must remain outside backend build context")
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_private(path, json.dumps({"version": 1, "keys": [Fernet.generate_key().decode()]}))
            print("keygen: created private external key file")
            return 0
        if args.key_file is None:
            raise CredentialConfigurationError("keyring: explicit key file required")
        os.environ["BS_SECRET_KEYS_FILE"] = str(args.key_file.absolute())
        get_keyring.cache_clear()
        get_keyring()
        if args.command in {"prepare", "rotation"} and getattr(args, "inputs", None):
            read_inputs(args.inputs, allow_plaintext=False)
        if args.command == "rotation":
            from bisheng.core.config.credential_rotation_cli import execute

            try:
                return execute(args)
            except CredentialConfigurationError:
                raise
            except Exception:
                # Native SDK exceptions may include credentials/SQL. Keep the
                # durable plan and fail explicitly without emitting their text.
                print(
                    "rotation: operation failed; preserve the plan and inspect native service health", file=sys.stderr
                )
                return 3
        if args.command == "validate-keyring":
            print("keyring: validated")
            return 0
        if args.command == "prepare":
            from bisheng.core.config.credential_bundle import prepare_bundle

            created = prepare_bundle(
                key_file=args.key_file.absolute(),
                out_dir=args.out_dir,
                mode=args.mode,
                config=args.config,
                inputs=args.inputs,
                base_bundle=args.base_bundle,
                component=args.component,
                env_file=args.env_file,
                deployment_root=args.deployment_root,
                runtime_env_file=args.runtime_env_file,
            )
            # The output owns a materialized database URL; the legacy source
            # was used during import and must not override this new target.
            legacy = os.environ.pop("bisheng_DATABASE_URL", None)
            try:
                _, manifest, pending = check_bundle(created, env_file=args.env_file)
            finally:
                if legacy is not None:
                    os.environ["bisheng_DATABASE_URL"] = legacy
            print(f"prepare: staged revision={manifest['revision']} pending={','.join(pending) or 'none'}")
            return 0
        settings, manifest, pending = check_bundle(
            args.bundle, enforce=args.enforce, component=args.component, env_file=args.env_file
        )
        if args.online:
            from bisheng.core.config.credential_checks import check_online

            check_online(settings, component=args.component)
        print(
            f"check: revision={manifest['revision']} phase={'online' if args.online else 'offline'} pending={','.join(pending) or 'none'}"
        )
        return 4 if args.enforce and pending else 0
    except CredentialConfigurationError as error:
        if created is not None:
            shutil.rmtree(created)
        print(str(error), file=sys.stderr)
        from bisheng.core.config.credential_checks import CredentialConnectionError

        return 3 if isinstance(error, CredentialConnectionError) else 2
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        if created is not None:
            shutil.rmtree(created)
        print("credential: artifact operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
