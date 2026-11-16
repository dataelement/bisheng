"""Static validation of one npm workbench archive, without extracting or executing it."""

import gzip
import hashlib
import io
import json
import re
import tarfile
import unicodedata
import warnings
from urllib.parse import urlparse

import yaml
from PIL import Image, UnidentifiedImageError
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

MAX_WORKBENCH_UPLOAD_BYTES = 100 * 1024 * 1024
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
    def __init__(self, reason, *, code=None, field=None):
        super().__init__(reason)
        self.rule, _, self.message = reason.partition(": ")
        self.code = code or {
            "WB-01": "WORKBENCH_ARCHIVE_INVALID",
            "WB-02": "WORKBENCH_ARCHIVE_LIMIT",
        }.get(self.rule, "WORKBENCH_CONTENT_INVALID")
        self.field = field

    def details(self):
        return {"code": self.code, "rule": self.rule, "field": self.field, "message": self.message}


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


MAX_CONFIG_DEPTH = 16
MAX_CONFIG_NODES = 2048
YAML_PREFIX = "tag:yaml.org,2002:"
HOME_PATH = re.compile(r"dshHomePath\(\s*(['\"])([a-zA-Z0-9][a-zA-Z0-9_-]{0,127})\1\s*\)\Z")


def _patch_require(ok, code, field, message):
    if not ok:
        raise WorkbenchBundleError(f"WB-08: {message}", code=f"WORKBENCH_PATCH_{code}", field=field)


def _check_patch_tree(root):
    # Bound traversal before interpreting fields. Repeated aliases count toward the budget.
    stack = [(root, 0, "patch", frozenset())]
    count = 0
    while stack:
        node, depth, field, ancestors = stack.pop()
        count += 1
        _patch_require(count <= MAX_CONFIG_NODES, "NODE_LIMIT", field, "Patch exceeds 2048 YAML nodes")
        _patch_require(depth <= MAX_CONFIG_DEPTH, "DEPTH_LIMIT", field, "Patch exceeds 16 YAML levels")
        _patch_require(id(node) not in ancestors, "INVALID_CONFIG", field, "Recursive YAML aliases are unsupported")
        ancestors = ancestors | {id(node)}
        if isinstance(node, MappingNode):
            _patch_require(node.tag == YAML_PREFIX + "map", "UNSUPPORTED_TAG", field, "Unsupported YAML mapping tag")
            seen = set()
            for key, value in node.value:
                _patch_require(
                    isinstance(key, ScalarNode) and key.tag == YAML_PREFIX + "str",
                    "INVALID_CONFIG",
                    field,
                    "YAML keys must be strings",
                )
                _patch_require(key.value not in seen, "INVALID_CONFIG", field, "Duplicate YAML key")
                seen.add(key.value)
                stack.append((key, depth + 1, field, ancestors))
                stack.append((value, depth + 1, f"{field}.{key.value}", ancestors))
        elif isinstance(node, SequenceNode):
            _patch_require(node.tag == YAML_PREFIX + "seq", "UNSUPPORTED_TAG", field, "Unsupported YAML sequence tag")
            stack.extend((child, depth + 1, f"{field}[{index}]", ancestors) for index, child in enumerate(node.value))
        else:
            allowed = {YAML_PREFIX + tag for tag in ("str", "null", "bool", "int", "float")}
            _patch_require(
                node.tag in allowed or node.tag == YAML_PREFIX + "js",
                "UNSUPPORTED_TAG",
                field,
                "Unsupported YAML scalar tag",
            )
            if node.tag == YAML_PREFIX + "js":
                _patch_require(
                    re.fullmatch(r"patch\[\d+\]\.insert\[\d+\]\.config\.root", field) is not None
                    and HOME_PATH.fullmatch(node.value) is not None,
                    "UNSUPPORTED_EXPRESSION",
                    field,
                    "Only config.root: !!js dshHomePath('directory-name') is supported",
                )


def _patch_id(raw, package_name):
    require(len(raw) <= MAX_METADATA_BYTES, "WB-08", "Patch exceeds 1 MiB")
    try:
        text = raw.decode("utf-8")
        # Bound the parser before compose allocates the entire node graph.
        depth = nodes = 0
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)):
                depth += 1
                nodes += 1
            elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
                depth -= 1
            elif isinstance(event, (yaml.events.ScalarEvent, yaml.events.AliasEvent)):
                nodes += 1
            _patch_require(depth <= MAX_CONFIG_DEPTH, "DEPTH_LIMIT", "patch", "Patch exceeds 16 YAML levels")
            _patch_require(nodes <= MAX_CONFIG_NODES, "NODE_LIMIT", "patch", "Patch exceeds 2048 YAML nodes")
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise WorkbenchBundleError("WB-08: Invalid patch YAML") from exc
    require(isinstance(root, SequenceNode) and len(root.value) <= 1000, "WB-08", "Patch must be a short YAML array")
    _check_patch_tree(root)
    ids = []
    for operation_index, operation in enumerate(root.value):
        mapping = _mapping(operation, "WB-08")
        require(
            set(mapping) == {"insert"}
            and isinstance(mapping["insert"], SequenceNode)
            and len(mapping["insert"].value) <= 1000,
            "WB-08",
            "Only insert operations are supported",
        )
        for entry_index, entry in enumerate(mapping["insert"].value):
            field = f"patch[{operation_index}].insert[{entry_index}]"
            fields = _mapping(entry, "WB-08")
            for required in ("name", "id"):
                _patch_require(
                    required in fields, "MISSING_FIELD", f"{field}.{required}", f"Patch entry requires {required}"
                )
            for extra in fields.keys() - {"name", "id", "config"}:
                _patch_require(
                    False, "UNSUPPORTED_FIELD", f"{field}.{extra}", "Only name, id and optional config are supported"
                )
            name, entry_id = fields["name"], fields["id"]
            _patch_require(
                isinstance(name, ScalarNode) and name.tag == YAML_PREFIX + "str" and name.value == package_name,
                "NAME_MISMATCH",
                f"{field}.name",
                "Patch name must match package name",
            )
            _patch_require(
                isinstance(entry_id, ScalarNode)
                and entry_id.tag == YAML_PREFIX + "str"
                and 0 < len(entry_id.value) <= 128
                and bool(entry_id.value.strip()),
                "INVALID_ID",
                f"{field}.id",
                "Patch ID must be a non-empty string of at most 128 characters",
            )
            if "config" in fields:
                _patch_require(
                    isinstance(fields["config"], MappingNode),
                    "INVALID_CONFIG",
                    f"{field}.config",
                    "Patch config must be a YAML mapping",
                )
            ids.append(entry_id.value)
    _patch_require(len(ids) == 1, "INSERT_COUNT", "patch", "Patch must insert this package once")
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


MAX_SCREENSHOTS = 8
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
MAX_SCREENSHOTS_BYTES = 20 * 1024 * 1024
MAX_SCREENSHOT_PIXELS = 16_000_000
MAX_SCREENSHOT_DIMENSION = 8192
SCREENSHOT_TYPES = {
    ".png": ("PNG", "image/png"),
    ".jpg": ("JPEG", "image/jpeg"),
    ".jpeg": ("JPEG", "image/jpeg"),
    ".webp": ("WEBP", "image/webp"),
}


def _screenshot_require(ok, code, field, message):
    if not ok:
        raise WorkbenchBundleError(f"WB-12: {message}", code=f"WORKBENCH_SCREENSHOT_{code}", field=field)


def _screenshot_path(value, field):
    _screenshot_require(isinstance(value, str) and 0 < len(value) <= 512, "PATH", field, "Invalid screenshot path")
    path = value.removeprefix("./")
    _screenshot_require(
        _safe_path("package/" + path) and not any(char in path for char in "%?#"),
        "PATH",
        field,
        "Screenshot path must be package-relative and safe",
    )
    extension = "." + path.rsplit(".", 1)[-1].lower()
    _screenshot_require(
        extension in SCREENSHOT_TYPES, "TYPE", field, "Only PNG, JPEG and WebP screenshots are supported"
    )
    return path, SCREENSHOT_TYPES[extension]


def _read_screenshot_files(data, paths):
    """Read only declared members from an already validated archive; never extract to disk."""
    result = {}
    total = 0
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            with tarfile.open(fileobj=LimitedReader(compressed), mode="r|") as archive:
                for item in archive:
                    if item.name not in paths:
                        continue
                    _screenshot_require(item.isfile(), "PATH", paths[item.name], "Screenshot must be a regular file")
                    _screenshot_require(
                        0 < item.size <= MAX_SCREENSHOT_BYTES,
                        "LIMIT",
                        paths[item.name],
                        "Screenshot exceeds 5 MiB or is empty",
                    )
                    total += item.size
                    _screenshot_require(
                        total <= MAX_SCREENSHOTS_BYTES,
                        "LIMIT",
                        "dsh.workbench.screenshots",
                        "Screenshots exceed 20 MiB",
                    )
                    source = archive.extractfile(item)
                    _screenshot_require(source is not None, "IMAGE", paths[item.name], "Unreadable screenshot")
                    raw = source.read(MAX_SCREENSHOT_BYTES + 1)
                    _screenshot_require(len(raw) == item.size, "IMAGE", paths[item.name], "Truncated screenshot")
                    result[item.name] = raw
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise WorkbenchBundleError(
            "WB-12: Unreadable screenshot archive", code="WORKBENCH_SCREENSHOT_IMAGE", field="dsh.workbench.screenshots"
        ) from exc
    _screenshot_require(
        set(result) == set(paths), "MISSING", "dsh.workbench.screenshots", "Declared screenshot is missing from archive"
    )
    return result


def _screenshot_image(raw, expected, field):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                _screenshot_require(
                    image.format == expected[0], "TYPE", field, "Screenshot extension does not match actual image type"
                )
                width, height = image.size
                _screenshot_require(
                    0 < width <= MAX_SCREENSHOT_DIMENSION
                    and 0 < height <= MAX_SCREENSHOT_DIMENSION
                    and width * height <= MAX_SCREENSHOT_PIXELS,
                    "LIMIT",
                    field,
                    "Screenshot exceeds 8192 pixels per dimension or 16 megapixels",
                )
                _screenshot_require(
                    getattr(image, "n_frames", 1) == 1, "TYPE", field, "Animated screenshots are unsupported"
                )
                image.verify()
            # verify() checks container integrity; load() also checks the compressed pixel data.
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
    except (
        OSError,
        SyntaxError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        if isinstance(exc, WorkbenchBundleError):
            raise
        raise WorkbenchBundleError(
            "WB-12: Invalid screenshot image", code="WORKBENCH_SCREENSHOT_IMAGE", field=field
        ) from exc
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "media_type": expected[1],
        "width": width,
        "height": height,
        "bytes": len(raw),
    }


def screenshot_id(artifact_digest, path, image_digest):
    return hashlib.sha256(f"{artifact_digest}\0{path}\0{image_digest}".encode()).hexdigest()


def _screenshots(data, dsh, files):
    if "workbench" not in dsh:
        return []
    workbench = dsh["workbench"]
    field = "dsh.workbench.screenshots"
    _screenshot_require(
        isinstance(workbench, dict), "DECLARATION", "dsh.workbench", "Workbench declaration must be an object"
    )
    declarations = workbench.get("screenshots", [])
    _screenshot_require(isinstance(declarations, list), "DECLARATION", field, "Screenshots must be an array")
    _screenshot_require(len(declarations) <= MAX_SCREENSHOTS, "LIMIT", field, "At most 8 screenshots are supported")
    entries, seen = [], set()
    for index, entry in enumerate(declarations):
        item_field = f"{field}[{index}]"
        _screenshot_require(
            isinstance(entry, dict) and "path" in entry and set(entry) <= {"path", "alt"},
            "DECLARATION",
            item_field,
            "Screenshot requires path and optional alt only",
        )
        path, expected = _screenshot_path(entry["path"], item_field + ".path")
        _screenshot_require(path not in seen, "DECLARATION", item_field + ".path", "Duplicate screenshot path")
        seen.add(path)
        _screenshot_require(
            "package/" + path in files, "MISSING", item_field + ".path", "Declared screenshot is missing from archive"
        )
        alt = entry.get("alt", "")
        _screenshot_require(
            isinstance(alt, str)
            and len(alt) <= 256
            and not any(ord(char) < 32 or 127 <= ord(char) <= 159 or 0xD800 <= ord(char) <= 0xDFFF for char in alt),
            "DECLARATION",
            item_field + ".alt",
            "Alt must be text of at most 256 characters without control characters or surrogates",
        )
        entries.append((path, expected, alt, item_field))
    if not entries:
        return []
    raw_files = _read_screenshot_files(data, {"package/" + path: field for path, _expected, _alt, field in entries})
    digest = hashlib.sha256(data).hexdigest()
    result = []
    for path, expected, alt, field in entries:
        metadata = _screenshot_image(raw_files["package/" + path], expected, field)
        result.append({"id": screenshot_id(digest, path, metadata["sha256"]), "path": path, "alt": alt, **metadata})
    return result


def read_workbench_screenshot(data, metadata):
    """Read one persisted, declared screenshot and verify it against import metadata."""
    path, expected = _screenshot_path(metadata["path"], "screenshot.path")
    raw = _read_screenshot_files(data, {"package/" + path: "screenshot.path"})["package/" + path]
    actual = _screenshot_image(raw, expected, "screenshot")
    _screenshot_require(
        all(metadata.get(key) == value for key, value in actual.items()),
        "IMAGE",
        "screenshot",
        "Screenshot metadata mismatch",
    )
    return raw


def validate_workbench_bundle(data: bytes) -> dict:
    require(0 < len(data) <= MAX_WORKBENCH_UPLOAD_BYTES, "WB-02", "Archive exceeds 100 MiB")
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
        "screenshots": _screenshots(data, dsh, files),
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
