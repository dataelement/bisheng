"""Static validation of one npm workbench archive, without extracting or executing it."""

import gzip
import io
import json
import re
import tarfile
import unicodedata
from urllib.parse import urlparse

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

MAX_WORKBENCH_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_WORKBENCH_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_WORKBENCH_ENTRIES = 10_000
MAX_METADATA_BYTES = 1024 * 1024
MAX_DECOMPRESSED_STREAM_BYTES = MAX_WORKBENCH_EXPANDED_BYTES + 16 * 1024 * 1024
NAME = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*\Z")
SEMVER = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z"
)
REPOSITORY_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SENSITIVE_NAME = re.compile(
    r"(?:\.env(?:\..*)?|.*\.(?:pem|p12|pfx|key|sqlite|sqlite3|db)|credentials?(?:\..*)?|cookies?(?:\..*)?|secrets?(?:\..*)?)\Z",
    re.I,
)


class WorkbenchBundleError(ValueError):
    pass


class LimitedReader:
    def __init__(self, source):
        self.source = source
        self.total = 0

    def read(self, size=-1):
        size = 65536 if size < 0 else size
        chunk = self.source.read(min(size, MAX_DECOMPRESSED_STREAM_BYTES + 1 - self.total))
        self.total += len(chunk)
        require(self.total <= MAX_DECOMPRESSED_STREAM_BYTES, "WB-02", "Decompressed stream exceeds limit")
        return chunk


def require(ok, rule, reason):
    if not ok:
        raise WorkbenchBundleError(f"{rule}: {reason}")


def semver_parts(value):
    match = SEMVER.fullmatch(value) if isinstance(value, str) else None
    require(match is not None and len(value) <= 64, "WB-05", "Invalid SemVer version")
    prerelease = match.group(4)
    if prerelease:
        require(
            all(not (part.isdigit() and len(part) > 1 and part[0] == "0") for part in prerelease.split(".")),
            "WB-05",
            "Invalid numeric prerelease identifier",
        )
    return tuple(map(int, match.group(1, 2, 3))), prerelease.split(".") if prerelease else None


def compare_semver(left, right):
    left_core, left_pre = semver_parts(left)
    right_core, right_pre = semver_parts(right)
    if left_core != right_core:
        return (left_core > right_core) - (left_core < right_core)
    if left_pre is None or right_pre is None:
        return (left_pre is None) - (right_pre is None)
    for a, b in zip(left_pre, right_pre, strict=False):
        if a == b:
            continue
        a_number, b_number = a.isdigit(), b.isdigit()
        if a_number != b_number:
            return -1 if a_number else 1
        if a_number:
            return (int(a) > int(b)) - (int(a) < int(b))
        return (a > b) - (a < b)
    return (len(left_pre) > len(right_pre)) - (len(left_pre) < len(right_pre))


def _safe_path(path):
    return (
        isinstance(path, str)
        and path.startswith("package/")
        and "\\" not in path
        and ":" not in path
        and "\0" not in path
        and all(31 < ord(char) < 127 or ord(char) > 159 for char in path)
        and all(part not in ("", ".", "..") for part in path.split("/"))
    )


def _json_object(raw, rule):
    require(len(raw) <= MAX_METADATA_BYTES, rule, "Metadata exceeds 1 MiB")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, rule, "Duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise WorkbenchBundleError(f"{rule}: Invalid UTF-8 JSON") from exc
    require(isinstance(value, dict), rule, "Metadata must be an object")
    return value


def _entry_path(value, files):
    require(isinstance(value, str) and len(value) <= 512, "WB-06", "Invalid package entry")
    relative = value.removeprefix("./")
    path = "package/" + relative
    require(_safe_path(path) and path in files, "WB-06", "Package entry is missing or unsafe")
    return relative


def _export_path(value, files):
    if isinstance(value, dict):
        options = [value[key] for key in ("import", "default") if key in value]
        require(options and all(option == options[0] for option in options), "WB-06", "Ambiguous export")
        value = options[0]
    return _entry_path(value, files)


def _repository(value):
    if isinstance(value, dict):
        require(value.get("type") in (None, "git"), "WB-09", "Unsupported repository type")
        value = value.get("url")
    require(isinstance(value, str), "WB-09", "Invalid repository URL")
    parsed = urlparse(value.removeprefix("git+"))
    require(
        parsed.scheme == "https"
        and parsed.netloc.lower() == "github.com"
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and not parsed.params
        and "%" not in parsed.path
        and "//" not in parsed.path,
        "WB-09",
        "Repository must be a GitHub HTTPS URL",
    )
    parts = parsed.path.rstrip("/").removesuffix(".git").strip("/").split("/")
    require(
        len(parts) == 2 and all(REPOSITORY_PART.fullmatch(part) for part in parts),
        "WB-09",
        "Invalid repository identity",
    )
    key = "/".join(part.lower() for part in parts)
    require(len(key) <= 140, "WB-09", "Repository identity is too long")
    return key, f"https://github.com/{key}"


def _mapping(node, rule):
    require(isinstance(node, MappingNode), rule, "Expected YAML mapping")
    result = {}
    for key, value in node.value:
        require(isinstance(key, ScalarNode) and key.value not in result, rule, "Duplicate or invalid YAML key")
        result[key.value] = value
    return result


def _patch_id(raw, package_name):
    require(len(raw) <= MAX_METADATA_BYTES, "WB-08", "Patch exceeds 1 MiB")
    try:
        root = yaml.compose(raw.decode("utf-8"), Loader=yaml.SafeLoader)
    except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise WorkbenchBundleError("WB-08: Invalid patch YAML") from exc
    require(isinstance(root, SequenceNode) and len(root.value) <= 1000, "WB-08", "Patch must be a short YAML array")
    ids = []
    for operation in root.value:
        mapping = _mapping(operation, "WB-08")
        require(
            set(mapping) == {"insert"}
            and isinstance(mapping["insert"], SequenceNode)
            and len(mapping["insert"].value) <= 1000,
            "WB-08",
            "Only insert operations are supported",
        )
        for entry in mapping["insert"].value:
            fields = _mapping(entry, "WB-08")
            name, entry_id = fields.get("name"), fields.get("id")
            require(
                set(fields) == {"name", "id"}
                and isinstance(name, ScalarNode)
                and name.value == package_name
                and name.tag == "tag:yaml.org,2002:str"
                and isinstance(entry_id, ScalarNode)
                and 0 < len(entry_id.value) <= 128
                and entry_id.tag == "tag:yaml.org,2002:str",
                "WB-08",
                "Patch must insert this package with an ID",
            )
            ids.append(entry_id.value)
    require(len(ids) == 1, "WB-08", "Patch must insert this package once")
    return ids[0]


def _read_patch(data, path):
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
        with tarfile.open(fileobj=LimitedReader(compressed), mode="r|") as archive:
            for item in archive:
                if item.name == path:
                    require(item.isfile() and item.size <= MAX_METADATA_BYTES, "WB-08", "Invalid patch file")
                    source = archive.extractfile(item)
                    require(source is not None, "WB-08", "Unreadable patch file")
                    return source.read(MAX_METADATA_BYTES + 1)
    raise WorkbenchBundleError("WB-08: Patch file missing")


def validate_workbench_bundle(data: bytes) -> dict:
    require(0 < len(data) <= MAX_WORKBENCH_UPLOAD_BYTES, "WB-02", "Archive exceeds 8 MiB")
    require(data.startswith(b"\x1f\x8b"), "WB-01", "Expected gzip tar archive")
    folded = set()
    files = set()
    selected = {}
    count = expanded = 0
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            limited = LimitedReader(compressed)
            with tarfile.open(fileobj=limited, mode="r|") as archive:
                for item in archive:
                    count += 1
                    require(count <= MAX_WORKBENCH_ENTRIES, "WB-02", "Too many archive entries")
                    path = item.name.rstrip("/") if item.isdir() else item.name
                    require(_safe_path(path) or (item.isdir() and path == "package"), "WB-03", "Unsafe archive path")
                    normalized = unicodedata.normalize("NFC", path).casefold()
                    require(normalized not in folded, "WB-03", "Duplicate archive path")
                    folded.add(normalized)
                    require(item.isfile() or item.isdir(), "WB-03", "Only regular files and directories are supported")
                    if item.isdir():
                        continue
                    require(
                        not any(SENSITIVE_NAME.fullmatch(part) for part in path.split("/")),
                        "WB-04",
                        "Sensitive file path",
                    )
                    expanded += item.size
                    require(expanded <= MAX_WORKBENCH_EXPANDED_BYTES, "WB-02", "Expanded archive exceeds 256 MiB")
                    files.add(path)
                    source = archive.extractfile(item)
                    require(source is not None, "WB-01", "Unreadable archive entry")
                    keep = (
                        path == "package/package.json"
                        or path == "package/workbench.json"
                        or path.endswith("/cordis.patch.yml")
                    )
                    chunks = []
                    remaining = item.size
                    while remaining:
                        chunk = source.read(min(65536, remaining))
                        require(bool(chunk), "WB-01", "Truncated archive entry")
                        remaining -= len(chunk)
                        if keep:
                            require(item.size <= MAX_METADATA_BYTES, "WB-02", "Metadata exceeds 1 MiB")
                            chunks.append(chunk)
                    if keep:
                        selected[path] = b"".join(chunks)
            while limited.read(65536):
                pass
    except (OSError, EOFError, tarfile.TarError, ValueError) as exc:
        if isinstance(exc, WorkbenchBundleError):
            raise
        raise WorkbenchBundleError("WB-01: Invalid or truncated gzip tar archive") from exc
    require("package/package.json" in selected, "WB-01", "Missing package.json")
    package = _json_object(selected["package/package.json"], "WB-05")
    name, version = package.get("name"), package.get("version")
    require(isinstance(name, str) and len(name) <= 214 and NAME.fullmatch(name), "WB-05", "Invalid npm package name")
    semver_parts(version)
    exports = package.get("exports")
    require(isinstance(exports, dict), "WB-06", "Missing exports")
    server_entry = _entry_path(package.get("main"), files)
    require(_export_path(exports.get("."), files) == server_entry, "WB-06", "Main and root export differ")
    client_entry = _export_path(exports.get("./client"), files)
    dsh = package.get("dsh")
    require(isinstance(dsh, dict), "WB-07", "Missing DSH declaration")
    bundle, client = dsh.get("bundle"), dsh.get("client")
    require(isinstance(bundle, dict) and isinstance(client, dict), "WB-07", "Invalid DSH declaration")
    require(
        client.get("platform") == "web"
        and isinstance(client.get("inject"), list)
        and "dsh-desktop-workbenches" in client["inject"]
        and all(isinstance(value, str) for value in client["inject"]),
        "WB-07",
        "Invalid Desktop client declaration",
    )
    patch = _entry_path(bundle.get("patch"), files)
    patch_data = selected.get("package/" + patch)
    if patch_data is None:
        patch_data = _read_patch(data, "package/" + patch)
    patch_id = _patch_id(patch_data, name)
    legacy = None
    if "package/workbench.json" in selected:
        legacy = _json_object(selected["package/workbench.json"], "WB-10")
        require(legacy.get("version") == version, "WB-10", "Legacy manifest version differs")
        _entry_path(legacy.get("entry"), files)
        require(
            isinstance(legacy.get("id"), str) and len(legacy["id"]) <= 128 and REPOSITORY_PART.fullmatch(legacy["id"]),
            "WB-10",
            "Invalid legacy ID",
        )
    if package.get("repository") is not None:
        workbench_key, repository_url = _repository(package["repository"])
        identity_kind, legacy_id = "repository", None
    else:
        require(legacy is not None, "WB-09", "Repository or legacy ID is required")
        workbench_key, repository_url = None, None
        identity_kind, legacy_id = "legacy", legacy["id"]
    description = package.get("description") or (legacy.get("description") if legacy else "") or ""
    require(isinstance(description, str) and len(description) <= 2000, "WB-05", "Invalid description")
    title = (legacy.get("title") if legacy else None) or name
    require(isinstance(title, str) and 0 < len(title) <= 128, "WB-05", "Invalid display name")
    dependencies = package.get("dependencies") or {}
    peers = package.get("peerDependencies") or {}
    require(isinstance(dependencies, dict) and isinstance(peers, dict), "WB-11", "Invalid dependency declarations")
    engine = package.get("engines") or {}
    require(isinstance(engine, dict), "WB-11", "Invalid engines declaration")
    license_value = package.get("license")
    require(license_value is None or isinstance(license_value, str), "WB-11", "Invalid license")
    return {
        "package_name": name,
        "version": version,
        "identity_kind": identity_kind,
        "identity_key": f"github:{workbench_key}" if workbench_key else f"legacy:{legacy_id}",
        "workbench_key": workbench_key,
        "legacy_id": legacy_id,
        "display_name": title,
        "description": description,
        "verification_level": "static",
        "warnings": ["legacy_identity", "runtime_not_verified"]
        if identity_kind == "legacy"
        else ["runtime_not_verified"],
        "package_metadata": {
            "repository_url": repository_url,
            "patch_entry_id": patch_id,
            "server_entry": server_entry,
            "client_entry": client_entry,
            "bundle_patch": patch,
            "license": license_value,
            "node_engine": engine.get("node") if isinstance(engine.get("node"), str) else None,
            "dependencies": sorted(set(dependencies) | set(peers)),
            "legacy_manifest": legacy is not None,
        },
    }
