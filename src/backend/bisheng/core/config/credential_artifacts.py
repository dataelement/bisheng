"""Versioned authenticated artifacts; plaintext exists only in caller memory.

This module is independent of application initialization and orchestration.
Runtime roles receive derived keyrings rather than deployment master keys.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from bisheng.core.config.secret_crypto import CredentialConfigurationError

FORMAT = "bisheng.credentials.v2"
SALT = b"bisheng/credential-runtime/v2"
ROLES = frozenset(
    {
        "mysql",
        "mysql-init",
        "openfga-migrate",
        "openfga",
        "redis",
        "minio",
        "elasticsearch",
        "milvus",
        "gateway-db-init",
        "gateway",
        "maintenance",
    }
)
MAX_PLAINTEXT = 8 * 1024 * 1024
MAX_ENVELOPE = 32 * 1024 * 1024


def _fail():
    raise CredentialConfigurationError("artifact: invalid, unsafe or unauthenticated material")


def _pairs(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            _fail()
        result[k] = v
    return result


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, TypeError):
        _fail()


def read_private(path, *, allow_symlink=False):
    try:
        flags = os.O_RDONLY | os.O_NONBLOCK
        if not allow_symlink:
            flags |= os.O_NOFOLLOW
        with os.fdopen(os.open(path, flags), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o027:
                _fail()
            content = stream.read(MAX_ENVELOPE + 1)
        if len(content) > MAX_ENVELOPE:
            _fail()
        return content
    except OSError:
        _fail()


def write_private_atomic(path, content, *, mode=0o600):
    """Atomically persist already sealed content or explicitly authorized key material."""
    path = Path(path)
    if path.is_symlink() or mode not in (0o600, 0o640):
        _fail()
    temp = None
    try:
        fd, name = tempfile.mkstemp(prefix=".sealed-", dir=path.parent)
        temp = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        if path.is_symlink():
            _fail()
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        _fail()
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _keys(path):
    raw = read_private(path, allow_symlink=True)
    if len(raw) > 65536:
        _fail()
    data = _json(raw)
    if not isinstance(data, dict) or set(data) != {"version", "keys"} or type(data["version"]) is not int:
        _fail()
    keys = data["keys"]
    if data["version"] != 1 or not isinstance(keys, list) or not keys or len(keys) > 64:
        _fail()
    if any(not isinstance(k, str) for k in keys) or len(set(keys)) != len(keys):
        _fail()
    try:
        for key in keys:
            Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError):
        _fail()
    return keys


def derive_keyring(master_file, role):
    if role not in ROLES:
        _fail()
    keys = []
    for key in _keys(master_file):
        raw = base64.urlsafe_b64decode(key)
        derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=SALT, info=b"role:" + role.encode()).derive(raw)
        keys.append(base64.urlsafe_b64encode(derived).decode("ascii"))
    return {"version": 1, "keys": keys}


def _identity(role, revision, deployment):
    if role not in ROLES or any(
        not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", v) for v in (revision, deployment)
    ):
        _fail()
    return {"format": FORMAT, "role": role, "revision": revision, "deployment_id": deployment}


def _name(name):
    if (
        not isinstance(name, str)
        or len(name) > 1024
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", name)
        or any(p in ("", ".", "..") or len(p) > 255 for p in name.split("/"))
    ):
        _fail()
    return name


def seal_artifact(files, master_file, *, role, revision, deployment):
    identity = _identity(role, revision, deployment)
    if not isinstance(files, dict) or not files or len(files) > 512:
        _fail()
    for name in files:
        _name(name)
    rows = []
    size = 0
    for name, value in sorted(files.items()):
        _name(name)
        if isinstance(value, str):
            value = value.encode("utf-8")
        if not isinstance(value, bytes):
            _fail()
        size += len(value)
        if size > MAX_PLAINTEXT:
            _fail()
        rows.append({"name": name, "content_base64": base64.b64encode(value).decode("ascii"), "mode": 0o440})
    raw = json.dumps({**identity, "files": rows}, separators=(",", ":"), sort_keys=True).encode()
    key = derive_keyring(master_file, role)["keys"][0]
    token = Fernet(key.encode()).encrypt(raw).decode("ascii")
    return json.dumps({"format": FORMAT, "role": role, "revision": revision, "token": token}, sort_keys=True).encode()


def open_artifact(content, key_file, *, role, revision, deployment, derived=False):
    identity = _identity(role, revision, deployment)
    if not isinstance(content, bytes) or len(content) > MAX_ENVELOPE:
        _fail()
    outer = _json(content)
    if not isinstance(outer, dict) or set(outer) != {"format", "role", "revision", "token"}:
        _fail()
    if any(outer[k] != identity[k] for k in ("format", "role", "revision")) or not isinstance(outer["token"], str):
        _fail()
    keys = _keys(key_file) if derived else derive_keyring(key_file, role)["keys"]
    try:
        raw = MultiFernet([Fernet(k.encode()) for k in keys]).decrypt(outer["token"].encode("ascii"))
    except (InvalidToken, ValueError, UnicodeError):
        _fail()
    data = _json(raw)
    if (
        not isinstance(data, dict)
        or set(data) != {*identity, "files"}
        or any(data[k] != v for k, v in identity.items())
    ):
        _fail()
    if not isinstance(data["files"], list) or not data["files"] or len(data["files"]) > 512:
        _fail()
    result = {}
    size = 0
    try:
        for row in data["files"]:
            if not isinstance(row, dict) or set(row) != {"name", "content_base64", "mode"}:
                _fail()
            name = _name(row["name"])
            if name in result or type(row["mode"]) is not int or row["mode"] != 0o440:
                _fail()
            value = base64.b64decode(row["content_base64"], validate=True)
            size += len(value)
            if size > MAX_PLAINTEXT:
                _fail()
            result[name] = value
    except (ValueError, TypeError):
        _fail()
    return result


ROLE_FILES = {
    "mysql": ("mysql.password", "mysql-client.cnf"),
    "mysql-init": ("mysql-client.cnf",),
    "openfga": ("openfga.yaml", "openfga.env"),
    "openfga-migrate": ("openfga.yaml", "openfga.env"),
    "redis": ("redis.password", "redis-users.acl", "redis.conf"),
    "minio": ("minio.user", "minio.password"),
    "elasticsearch": ("elasticsearch.password",),
    "gateway": ("gateway-application.yml",),
}


def _encode_native(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    _fail()


def write_bundle_native(root, native):
    """Persist native middleware files as host plaintext (option C)."""
    root = Path(root)
    if root.is_symlink():
        _fail()
    names = []
    for name, value in sorted(native.items()):
        if name.startswith(("es-config/", "milvus-config/")):
            folder = root / name.rsplit("/", 1)[0]
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            if folder.is_symlink():
                _fail()
            write_private_atomic(root / name, _encode_native(value), mode=0o600)
            continue
        if _name(name) != Path(name).name:
            _fail()
        write_private_atomic(root / name, _encode_native(value), mode=0o600)
        names.append(name)
    return {
        "native_storage": "plaintext",
        "native_files": sorted(names),
        "roles": [],
        "native_sha256": {},
    }


def seal_bundle_native(root, native, key_file, *, revision, deployment):
    """Legacy sealed-files-v2 writer retained only for migration imports."""
    root = Path(root)
    folder = root / "native"
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.is_symlink():
        _fail()
    roles = {}
    for role, names in ROLE_FILES.items():
        selected = {n: native[n] for n in names if n in native}
        if selected:
            roles[role] = selected
    if "milvus.yaml" in native:
        roles["milvus"] = {"milvus-config/user.yaml": native["milvus.yaml"]}
    for name, value in native.items():
        if name.startswith("es-config/"):
            roles.setdefault("elasticsearch", {})[name] = value
        elif name.startswith("milvus-config/"):
            roles.setdefault("milvus", {})[name] = value
        elif name not in {n for names in ROLE_FILES.values() for n in names} | {"milvus.yaml"}:
            _fail()
    hashes = {}
    for role, files in roles.items():
        content = seal_artifact(files, key_file, role=role, revision=revision, deployment=deployment)
        write_private_atomic(folder / (role + ".sealed.json"), content)
        hashes[role] = hashlib.sha256(content).hexdigest()
    return {"roles": sorted(roles), "native_sha256": hashes, "native_storage": "sealed-files-v2"}


def bundle_native_files(root, key_file, *, allow_legacy=False):
    """Read native files. New packages are plaintext; sealed v2 remains import-only."""
    root = Path(root)
    manifest = _json(read_private(root / "manifest.json"))
    storage = manifest.get("native_storage")
    if storage == "plaintext" or (manifest.get("version") == 1 and allow_legacy):
        names = manifest.get("native_files", [])
        if not isinstance(names, list) or any(_name(n) != Path(n).name for n in names):
            _fail()
        result = {n: read_private(root / n) for n in names}
        for folder_name in ("es-config", "milvus-config"):
            folder = root / folder_name
            if folder.is_dir() and not folder.is_symlink():
                for path in sorted(folder.rglob("*")):
                    if path.is_file() and not path.is_symlink():
                        result[f"{folder_name}/{path.relative_to(folder).as_posix()}"] = read_private(path)
        return result
    if not allow_legacy and storage not in {None, "sealed-files-v2"}:
        _fail()
    roles = manifest.get("roles")
    if (
        manifest.get("version") != 2
        or not isinstance(roles, list)
        or not roles
        or any(role not in ROLES or role == "maintenance" for role in roles)
        or len(roles) != len(set(roles))
        or (root / "native").is_symlink()
    ):
        _fail()
    result = {}
    for role in roles:
        raw = read_private(root / "native" / (role + ".sealed.json"))
        if hashlib.sha256(raw).hexdigest() != manifest.get("native_sha256", {}).get(role):
            _fail()
        files = open_artifact(
            raw, key_file, role=role, revision=manifest["revision"], deployment=manifest["deployment_id"]
        )
        for name, value in files.items():
            name = "milvus.yaml" if name == "milvus-config/user.yaml" else name
            if name in result and result[name] != value:
                _fail()
            result[name] = value
    return result


def confidential_context(path, *, deployment=None):
    """Bind sensitive state to a private session context and logical filename."""
    path = Path(path).absolute()
    expected_deployment = deployment or os.environ.get("BS_CREDENTIAL_DEPLOYMENT_ID")
    for parent in path.parents:
        marker = parent / ".artifact-context.json"
        if marker.is_file():
            context = _json(read_private(marker))
            if set(context) != {"version", "revision", "deployment_id"} or context["version"] != 2:
                _fail()
            if expected_deployment and context["deployment_id"] != expected_deployment:
                _fail()
            _identity("maintenance", context["revision"], context["deployment_id"])
            return context["deployment_id"], context["revision"], path.relative_to(parent).as_posix()
    if not expected_deployment:
        _fail()
    _identity("maintenance", "inputs-v2", expected_deployment)
    return expected_deployment, "inputs-v2", path.name


def write_confidential(path, value, *, key_file=None, deployment=None):
    key_file = key_file or os.environ.get("BS_SECRET_KEYS_FILE")
    if not key_file:
        _fail()
    dep, revision, name = confidential_context(path, deployment=deployment)
    raw = seal_artifact({name: value}, key_file, role="maintenance", revision=revision, deployment=dep)
    write_private_atomic(path, raw)


def read_confidential(path, *, key_file=None, deployment=None, allow_plaintext=False):
    raw = read_private(path)
    try:
        outer = _json(raw)
    except CredentialConfigurationError:
        outer = None
    if isinstance(outer, dict) and outer.get("format") == FORMAT:
        key_file = key_file or os.environ.get("BS_SECRET_KEYS_FILE")
        if not key_file:
            _fail()
        dep, revision, name = confidential_context(path, deployment=deployment)
        files = open_artifact(raw, key_file, role="maintenance", revision=revision, deployment=dep)
        if set(files) != {name}:
            _fail()
        return files[name]
    if not allow_plaintext:
        _fail()
    return raw
