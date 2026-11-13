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
    if manifest.get("version") != 1 or not re.fullmatch(r"[0-9a-f]{32}", manifest.get("revision", "")):
        raise CredentialConfigurationError("bundle: invalid version or revision")
    names = manifest.get("native_files")
    if not isinstance(names, list) or any(not isinstance(name, str) or Path(name).name != name for name in names):
        raise CredentialConfigurationError("bundle: invalid file list")
    for filename in {"config.yaml", "manifest.json", *names}:
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
        "telemetry_elasticsearch": "telemetry_elasticsearch.password",
    }
    if not make_url(settings.database_url).drivername.startswith("mysql"):
        native_name.pop("mysql")
    try:
        for name, filename in native_name.items():
            if password.get(name) and (root / filename).read_text() != password[name]:
                raise CredentialConfigurationError(f"{name}: native and application credentials differ")
        if password.get("minio"):
            milvus_native = yaml.safe_load((root / "milvus.yaml").read_text())
            if (
                milvus_native["minio"]["secretAccessKey"] != password["minio"]
                or milvus_native["minio"]["accessKeyID"] != settings.object_storage.minio.access_key
            ):
                raise CredentialConfigurationError("milvus.minio: object-store credentials differ")
        from bisheng.core.config.credential_bundle import _native

        expected_native = _native(data, password, password["milvus"])
        for filename in ("mysql-client.cnf", "openfga.yaml", "minio.user"):
            if filename in expected_native and (root / filename).read_text() != expected_native[filename]:
                raise CredentialConfigurationError("bundle: native consumer credentials differ")
        if password.get("milvus"):
            native_milvus = yaml.safe_load((root / "milvus.yaml").read_text())
            security = native_milvus["common"]["security"]
            if not security.get("authorizationEnabled") or security.get("defaultRootPassword") != password["milvus"]:
                raise CredentialConfigurationError("milvus: native login credentials differ")
        if password.get("redis"):
            acl = (root / "redis-users.acl").read_text()
            if "#" + hashlib.sha256(password["redis"].encode()).hexdigest() not in acl.split():
                raise CredentialConfigurationError("redis: native ACL credential differs")
        gateway = root / "gateway-application.yml"
        if gateway.exists():
            gateway_config = yaml.safe_load(gateway.read_text())
            if gateway_config["spring"]["data"]["redis"].get("password", "") != password["redis"]:
                raise CredentialConfigurationError("gateway.redis: credentials differ")
    except (OSError, TypeError, KeyError, yaml.YAMLError):
        raise CredentialConfigurationError("bundle: native artifacts cannot be verified") from None
    pending = sorted(name for name, value in password.items() if is_weak(value, name))
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
    requirements = sub.add_parser("requirements")
    requirements.add_argument("--config", type=Path, required=True)
    requirements.add_argument("--env-file", type=Path)
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
    return parser


def main(argv=None):
    created = None
    try:
        args = _parser().parse_args(argv)
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
            read_inputs(args.inputs)
            print("inputs: validated")
            return 0
        if args.command == "requirements":
            from bisheng.core.config.credential_loader import load_config

            data = load_config(args.config, env_file=args.env_file).data
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
        os.environ["BS_SECRET_KEYS_FILE"] = str(args.key_file.absolute())
        get_keyring.cache_clear()
        get_keyring()
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
    except (OSError, ValueError, TypeError):
        if created is not None:
            shutil.rmtree(created)
        print("credential: artifact operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
