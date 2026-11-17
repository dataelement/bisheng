"""Internal stdin-based ciphertext operations for the original host installer."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tarfile
import uuid
from pathlib import Path

from bisheng.core.config.credential_artifacts import (
    MAX_PLAINTEXT,
    bundle_native_files,
    derive_keyring,
    read_confidential,
    read_private,
    write_bundle_native,
    write_confidential,
    write_private_atomic,
)
from bisheng.core.config.credential_inputs import COMPONENTS, validate_password
from bisheng.core.config.secret_crypto import CredentialConfigurationError


def seal_input_value(raw, out, *, key_file, deployment, component):
    if not isinstance(raw, bytes) or len(raw) > MAX_PLAINTEXT:
        raise CredentialConfigurationError("input: invalid size")
    try:
        value = validate_password(raw.decode("utf-8"), component)
    except UnicodeError:
        raise CredentialConfigurationError("input: invalid text") from None
    write_confidential(out, value, key_file=key_file, deployment=deployment)


def parser(sub):
    p = sub.add_parser("artifact")
    p.add_argument(
        "action",
        choices=[
            "capabilities",
            "seal-input",
            "seal-stream",
            "open-stream",
            "native-stream",
            "context",
            "role-keys",
            "seed",
            "publish",
            "info",
            "sanitize-env",
            "migrate-prepare",
            "migrate-info",
            "migrate-verify",
            "migrate-bindings",
            "migrate-mark",
            "migrate-clean",
            "legacy-seal",
            "es-discover",
            "es-info",
            "es-freeze",
            "es-capture",
            "es-export",
            "es-observe",
            "es-intent",
            "es-verify",
            "es-rollback",
            "es-persist",
            "es-compile-current",
        ],
    )
    p.add_argument("--key-file", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--file", type=Path)
    p.add_argument("--key-dir", type=Path)
    p.add_argument("--bundle", type=Path)
    p.add_argument("--out-dir", type=Path)
    p.add_argument("--destination", type=Path)
    p.add_argument("--role", choices=["redis", "elasticsearch", "milvus"])
    p.add_argument(
        "--field",
        choices=[
            "seeds",
            "deployment",
            "version",
            "phase",
            "request",
            "source",
            "bundle",
            "source-mode",
            "es-mode",
            "es-phase",
            "es-security",
        ],
    )
    p.add_argument("--es-mode", choices=["enable", "retain", "recover", "existing"])
    p.add_argument("--inputs", type=Path)
    # Option C removed the Go credential-runtime. Hidden so old installer argv that
    # still passes --binary=/dev/null does not break; value is ignored and warned.
    p.add_argument("--binary", help=argparse.SUPPRESS)
    p.add_argument("--secret-gid", default="0")
    p.add_argument("--retry", action="store_true")
    p.add_argument("--allow-external-source", action="store_true")
    p.add_argument("--preserve-redis-acl", action="store_true")
    p.add_argument("--name")
    p.add_argument("--policy-root", type=Path)
    p.add_argument("--session-dir", type=Path)
    p.add_argument("--env-file", type=Path)
    p.add_argument("--phase")
    p.add_argument("--request")
    p.add_argument("--deployment-id")
    p.add_argument("--component", choices=COMPONENTS)
    return p


def seed_bundle(base, out, key_file, role, stream, *, preserve_redis_acl=False, env_file=None):
    """Copy ciphertext and seal template streams without a plaintext staging file."""
    import re

    base, out = Path(base), Path(out)
    if out.exists() or out.is_symlink() or role not in {"redis", "elasticsearch", "milvus"}:
        raise CredentialConfigurationError("seed: new private output and supported role required")
    manifest = json.loads(read_private(base / "manifest.json"))
    native = bundle_native_files(base, key_file)
    if role == "redis":
        content = stream.read(MAX_PLAINTEXT + 1)
        if len(content) > MAX_PLAINTEXT:
            raise CredentialConfigurationError("seed: configuration too large")
        try:
            text = content.decode("utf-8")
        except UnicodeError:
            raise CredentialConfigurationError("redis: invalid configuration") from None
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                command = stripped.split()[0].lower()
                if command in {"include", "user", "masterauth", "replicaof", "slaveof"}:
                    raise CredentialConfigurationError("redis: unsupported native configuration")
                if command in {"requirepass", "aclfile"}:
                    continue
            lines.append(line)
        native["redis.conf"] = ("\n".join(lines) + "\n").encode()
        if preserve_redis_acl:
            from bisheng.core.config.credential_es_migration import settings_for
            from bisheng.core.config.credential_rotation_native import _quiet_drivers, _redis, validate_redis_acl

            try:
                with _quiet_drivers(), _redis(settings_for(base, env_file)) as client:
                    lines = [line.decode() if isinstance(line, bytes) else line for line in client.acl_list()]
                    native["redis-users.acl"] = validate_redis_acl(lines, "default").encode()
            except CredentialConfigurationError:
                raise
            except Exception:
                raise CredentialConfigurationError(
                    "seed: current Redis ACL cannot be captured; no native settings changed"
                ) from None
    else:
        prefix = "es-config/" if role == "elasticsearch" else "milvus-config/"
        total = 0
        count = 0
        try:
            with tarfile.open(fileobj=stream, mode="r|*") as archive:
                for member in archive:
                    if member.isdir():
                        continue
                    if not member.isfile() or member.size < 0:
                        raise ValueError
                    name = member.name.removeprefix("./")
                    pieces = name.split("/")
                    if pieces[0] in {"config", "configs"}:
                        name = "/".join(pieces[1:])
                    if not re.fullmatch(r"[A-Za-z0-9_./-]+", name) or any(
                        p in {"", ".", ".."} for p in name.split("/")
                    ):
                        raise ValueError
                    total += member.size
                    count += 1
                    if total > MAX_PLAINTEXT or count > 500:
                        raise ValueError
                    if role == "milvus" and name == "user.yaml":
                        continue  # Current rendered identities override the vendor's defaults.
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError
                    native[prefix + name] = source.read(member.size + 1)
        except (tarfile.TarError, ValueError, OSError):
            raise CredentialConfigurationError("seed: invalid or unsupported image templates") from None
        required = prefix + ("elasticsearch.yml" if role == "elasticsearch" else "milvus.yaml")
        has_vendor_sample = role == "elasticsearch" and "es-config/es_config.sample" in native
        if required not in native and not has_vendor_sample:
            raise CredentialConfigurationError("seed: required native template missing")
        if role == "elasticsearch" and "es_security_enabled" in manifest:
            from bisheng.core.config.credential_es_migration import rewrite_security_config

            rewrite_security_config(native, manifest["es_security_enabled"])
    try:
        out.mkdir(mode=0o700, parents=False)
        write_private_atomic(out / "config.yaml", read_private(base / "config.yaml"))
        manifest["revision"] = uuid.uuid4().hex
        manifest.update(write_bundle_native(out, native))
        manifest["runtime_seeded"] = sorted(set(manifest.get("runtime_seeded", [])) | {role})
        write_private_atomic(out / "manifest.json", json.dumps(manifest, indent=2).encode())
    except Exception:
        shutil.rmtree(out)
        raise
    return out


def publish_bundle(source, destination, key_file):
    from bisheng.core.config.credential_rotation import _hashes

    source, destination = Path(source).absolute(), Path(destination).absolute()
    bundle_native_files(source, key_file)
    source_hashes = _hashes(source)
    if destination.resolve().is_relative_to(Path(__file__).resolve().parents[3]) or destination.is_symlink():
        raise CredentialConfigurationError("publish: private immutable destination required")
    if destination.exists():
        if source_hashes != _hashes(destination):
            raise CredentialConfigurationError("publish: existing revision differs; preserve both versions")
        return destination
    temporary = destination.parent / (".publish-" + uuid.uuid4().hex)
    try:
        shutil.copytree(source, temporary)
        if source_hashes != _hashes(temporary) or source_hashes != _hashes(source):
            raise CredentialConfigurationError("publish: ciphertext copy verification failed")
        for path in temporary.rglob("*"):
            if path.is_file():
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
        for path in [*sorted((p for p in temporary.rglob("*") if p.is_dir()), reverse=True), temporary]:
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.rename(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination


def execute(args):
    if args.action == "capabilities":
        print("plaintext-native-v1")
        return 0
    dep = args.deployment_id or os.environ.get("BS_CREDENTIAL_DEPLOYMENT_ID")
    if args.action.startswith("es-"):
        from bisheng.core.config import credential_es_migration as es

        try:
            if args.action == "es-discover":
                print(es.discover(args.bundle, args.env_file))
            elif args.action == "es-info":
                if args.session_dir:
                    value = es._state(args.session_dir, args.key_file)["es"]
                    print(value["phase" if args.field == "es-phase" else "mode"])
                else:
                    print(
                        "configured"
                        if es.credentials(es.settings_for(args.bundle, args.env_file)).get("elasticsearch")
                        else "missing"
                    )
            elif args.action == "es-freeze":
                es.freeze(args.session_dir, args.key_file, args.env_file)
            elif args.action == "es-compile-current":
                if args.binary:
                    print(
                        "artifact: ignoring deprecated --binary (Option C plaintext mounts)",
                        file=sys.stderr,
                    )
                print(json.dumps(es.compile_current(args.bundle, sys.stdin, args.secret_gid, args.env_file)))
            elif args.action == "es-capture":
                if not args.session_dir:
                    raise CredentialConfigurationError("ES migration: session directory required")
                if args.binary:
                    print(
                        "artifact: ignoring deprecated --binary (Option C plaintext mounts)",
                        file=sys.stderr,
                    )
                es.compile_es(
                    args.session_dir,
                    args.key_file,
                    sys.stdin,
                    args.secret_gid,
                    args.env_file,
                )
            elif args.action == "es-export":
                print(json.dumps(es.export_es(args.session_dir, args.key_file)))
            elif args.action == "es-observe":
                print(es.observe_target(args.session_dir, args.key_file, args.env_file))
            elif args.action == "es-intent":
                es.reset_intent(args.session_dir, args.key_file, retry=args.retry)
            elif args.action == "es-verify":
                es.verify(args.session_dir, args.key_file, args.env_file)
            elif args.action == "es-persist":
                es.persist_password(args.session_dir, args.key_file, args.env_file)
            elif args.action == "es-rollback":
                es.prepare_rollback(args.session_dir, args.key_file)
        except CredentialConfigurationError:
            raise
        except Exception:
            # Driver diagnostics may contain URLs, passwords or index contents.
            raise CredentialConfigurationError(
                "ES migration: operation failed; preserve encrypted state and retry the original installer"
            ) from None
        return 0
    if args.action == "sanitize-env":
        from bisheng.core.config.credential_sealed_migration import sanitize_environment

        if not all([args.bundle, args.env_file, args.session_dir, args.key_file]):
            raise CredentialConfigurationError(
                "environment: explicit bundle, environment, key and private backup directory required"
            )
        sanitize_environment(args.bundle, args.env_file, args.session_dir, key_file=args.key_file)
        return 0
    if args.action.startswith("migrate-"):
        from bisheng.core.config import credential_sealed_migration as migration

        if not args.key_file:
            raise CredentialConfigurationError("migration: explicit key required")
        if args.action == "migrate-prepare":
            if not all([args.bundle, args.out_dir, args.policy_root, dep]):
                raise CredentialConfigurationError("migration: source, private store, deployment and output required")
            migration.prepare_migration(
                args.bundle,
                store=args.policy_root,
                key_file=args.key_file,
                out_dir=args.out_dir,
                deployment=dep,
                env_file=args.env_file,
                es_mode=args.es_mode,
                inputs=args.inputs,
                allow_external_source=args.allow_external_source,
            )
        elif not args.session_dir:
            raise CredentialConfigurationError("migration: session required")
        elif args.action == "migrate-info":
            value = migration.status(args.session_dir, key_file=args.key_file)
            if args.field == "source-mode":
                print(value.get("source_mode", ""))
                return 0
            if args.field in {"es-mode", "es-phase"}:
                print(value.get("es", {}).get("mode" if args.field == "es-mode" else "phase", "none"))
                return 0
            if args.field not in {"bundle", "source", "phase", "request"}:
                raise CredentialConfigurationError("migration: safe field required")
            print(value[args.field])
        elif args.action == "migrate-verify":
            if not args.bundle:
                raise CredentialConfigurationError("migration: staged bundle required")
            migration.verify_staged(args.session_dir, args.bundle, key_file=args.key_file, env_file=args.env_file)
        elif args.action == "migrate-mark":
            migration.mark_phase(args.session_dir, args.phase, key_file=args.key_file, request=args.request)
        elif args.action == "migrate-bindings":
            data = sys.stdin.buffer.read(MAX_PLAINTEXT + 1)
            if len(data) > MAX_PLAINTEXT:
                raise CredentialConfigurationError("migration: binding inventory too large")
            # Docker's formatted output adds empty separator lines, including for
            # containers without bind mounts. Keep actual paths byte-for-byte.
            migration.verify_bindings(
                args.session_dir, [line for line in data.decode().splitlines() if line], key_file=args.key_file
            )
        elif args.action == "migrate-clean":
            if (
                not args.policy_root
                or args.policy_root.absolute()
                != Path(migration.status(args.session_dir, key_file=args.key_file)["store"]).absolute()
            ):
                raise CredentialConfigurationError("migration: cleanup requires the exact mounted managed store")
            migration.cleanup(args.session_dir, key_file=args.key_file)
        return 0
    if args.action == "legacy-seal":
        if not args.session_dir or not args.key_file:
            raise CredentialConfigurationError("migration: private legacy directory and key required")
        for name in ("source.yaml", "runtime-env.json", "read-runtime.log", "read-key.log"):
            path = args.session_dir / name
            if path.exists():
                value = read_confidential(path, key_file=args.key_file, deployment=dep, allow_plaintext=True)
                write_confidential(path, value, key_file=args.key_file, deployment=dep)
        return 0
    if args.action == "info":
        if not args.bundle:
            raise CredentialConfigurationError("artifact: bundle required")
        m = json.loads(read_private(args.bundle / "manifest.json"))
        if args.field == "seeds":
            if m.get("native_storage") == "plaintext":
                # Option C mounts host plaintext files; redis.conf comes from docker/redis.
                print("")
            else:
                print(
                    "\n".join(
                        role
                        for role in ("redis", "elasticsearch", "milvus")
                        if role in m.get("roles", []) and role not in m.get("runtime_seeded", [])
                    )
                )
        elif args.field == "deployment":
            print(m["deployment_id"])
        elif args.field == "es-security":
            print("true" if m.get("es_security_enabled", True) else "false")
        elif args.field == "version":
            print(m["version"])
        else:
            raise CredentialConfigurationError("artifact: safe field required")
        return 0
    if args.action == "publish":
        if not args.bundle or not args.destination or not args.key_file:
            raise CredentialConfigurationError("publish: source, destination and key required")
        publish_bundle(args.bundle, args.destination, args.key_file)
    elif args.action == "seed":
        if not all([args.bundle, args.out_dir, args.key_file, args.role]):
            raise CredentialConfigurationError("seed: bundle, output, key and role required")
        if args.preserve_redis_acl and args.role != "redis":
            raise CredentialConfigurationError("seed: ACL preservation applies to Redis only")
        seed_bundle(
            args.bundle,
            args.out_dir,
            args.key_file,
            args.role,
            sys.stdin.buffer,
            preserve_redis_acl=args.preserve_redis_acl,
            env_file=args.env_file,
        )
    elif args.action == "context":
        if not dep or not args.out:
            raise CredentialConfigurationError("artifact: deployment and context output required")
        marker = {"version": 2, "revision": uuid.uuid4().hex, "deployment_id": dep}
        write_private_atomic(args.out, json.dumps(marker).encode())
    elif args.action in {"seal-input", "seal-stream"}:
        if not args.out or not args.key_file:
            raise CredentialConfigurationError("artifact: key and output required")
        raw = sys.stdin.buffer.read(MAX_PLAINTEXT + 1)
        if len(raw) > MAX_PLAINTEXT:
            raise CredentialConfigurationError("artifact: input too large")
        if args.action == "seal-input":
            if not args.component:
                raise CredentialConfigurationError("input: component required")
            try:
                validate_password(raw.decode("utf-8"), args.component)
            except (CredentialConfigurationError, UnicodeError):
                print("input: password does not meet component requirements", file=sys.stderr)
                return 4
            seal_input_value(raw, args.out, key_file=args.key_file, deployment=dep, component=args.component)
        else:
            write_confidential(args.out, raw, key_file=args.key_file, deployment=dep)
    elif args.action == "native-stream":
        if not args.bundle or not args.name or not args.key_file or sys.stdout.isatty():
            raise CredentialConfigurationError("artifact: bundle, safe filename and private output pipe required")
        values = bundle_native_files(args.bundle, args.key_file)
        if args.name not in values:
            raise CredentialConfigurationError("artifact: native file not available")
        sys.stdout.buffer.write(values[args.name])
        return 0
    elif args.action == "open-stream":
        if not args.file or not args.key_file or sys.stdout.isatty():
            raise CredentialConfigurationError("artifact: private output pipe and key required")
        sys.stdout.buffer.write(read_confidential(args.file, key_file=args.key_file, deployment=dep))
        return 0
    elif args.action == "role-keys":
        if not args.key_file or not args.bundle or not args.key_dir:
            raise CredentialConfigurationError("artifact: key, bundle and role key directory required")
        bundle_native_files(args.bundle, args.key_file)  # Authenticate before touching live role keys.
        manifest = json.loads(read_private(args.bundle / "manifest.json"))
        args.key_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        for role in manifest["roles"]:
            raw = json.dumps(derive_keyring(args.key_file, role)).encode()
            path = args.key_dir / (role + ".json")
            if path.exists() and read_private(path) == raw:
                continue
            write_private_atomic(path, raw)
    else:
        raise CredentialConfigurationError("artifact: unsupported action")
    print("artifact: saved authenticated material")
    return 0
