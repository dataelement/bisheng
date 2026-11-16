"""Read-only acceptance scanner. Password candidates remain in process memory.

The caller must supply every old/current/staged bundle and every persisted scope.
Absence of a match proves only those explicit scopes and encodings were checked.
"""

import argparse
import base64
import json
import os
import stat
import sys
from pathlib import Path
from urllib.parse import quote, quote_plus


def variants(values):
    result = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        raw = value.encode()
        result.update([
            raw, quote(value, safe="").encode(), quote_plus(value).encode(),
            json.dumps(value, ensure_ascii=True)[1:-1].encode(),
            json.dumps(value, ensure_ascii=False)[1:-1].encode(),
            repr(value)[1:-1].encode(), base64.b64encode(raw),
            base64.urlsafe_b64encode(raw),
        ])
    if not result:
        raise ValueError("scan requires nonempty in-memory candidates")
    return result


def scan_stream(stream, patterns, *, chunk_size=1024 * 1024):
    if not patterns:
        return False
    overlap = max(map(len, patterns)) - 1
    tail = b""
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            return False
        block = tail + chunk
        if any(p in block for p in patterns):
            return True
        tail = block[-overlap:] if overlap else b""


def scan_paths(paths, values, *, milvus_base64_values=(), milvus_data_root=None, mysql_socket_link=None):
    patterns = variants(values)
    allowed = {base64.b64encode(v.encode()) for v in milvus_base64_values if v}
    other_values = {v for v in values if v} - set(milvus_base64_values)
    if other_values:
        allowed -= variants(other_values)
    native_root = Path(milvus_data_root).resolve() if milvus_data_root else None
    # Never emit candidate-bearing filenames or file contents in evidence.
    def safe_path(path):
        raw = os.fsencode(str(path))
        for pattern in sorted(patterns, key=len, reverse=True):
            raw = raw.replace(pattern, b"<redacted>")
        return os.fsdecode(raw)

    result = {"files_scanned": 0, "matches": [], "unreadable": [], "symlinks": [], "accepted_exceptions": []}
    seen = set()
    for requested in paths:
        root = Path(requested).absolute()
        candidates = [root]
        if root.is_dir() and not root.is_symlink():
            # os.walk reports directory access failures instead of hiding gaps.
            def walk_error(error):
                result["unreadable"].append(safe_path(error.filename))
            for directory, directories, files in os.walk(root, followlinks=False, onerror=walk_error):
                for name in list(directories):
                    p = Path(directory) / name
                    if p.is_symlink():
                        result["symlinks"].append(safe_path(p))
                        directories.remove(name)
                candidates.extend(Path(directory) / name for name in files)
        for path in candidates:
            if str(path) in seen:
                continue
            seen.add(str(path))
            descriptor = None
            try:
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    if (
                        mysql_socket_link and path == Path(mysql_socket_link).absolute()
                        and path.name == "mysql.sock" and os.readlink(path) == "/var/run/mysqld/mysqld.sock"
                    ):
                        result["accepted_exceptions"].append({"path": safe_path(path), "scope": "verified_mysql_socket_link"})
                        continue
                    result["symlinks"].append(safe_path(path))
                    continue
                if stat.S_ISDIR(metadata.st_mode):
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    result["unreadable"].append(safe_path(path))
                    continue
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                actual = os.fstat(descriptor)
                if (actual.st_dev, actual.st_ino) != (metadata.st_dev, metadata.st_ino) or not stat.S_ISREG(actual.st_mode):
                    raise OSError("scan source changed")
                with os.fdopen(descriptor, "rb") as stream:
                    descriptor = None
                    hit = scan_stream(stream, patterns)
                    accepted = False
                    if hit and allowed and native_root and any(
                        path.resolve().is_relative_to(native_root / sub)
                        for sub in ("rdb_data", "rdb_data_meta_kv")
                    ):
                        stream.seek(0)
                        accepted = not scan_stream(stream, patterns - allowed)
                result["files_scanned"] += 1
                if hit:
                    if accepted:
                        result["accepted_exceptions"].append({"path": safe_path(path), "scope": "user_confirmed_milvus_native_base64_message"})
                    else:
                        result["matches"].append(safe_path(path))
            except OSError:
                result["unreadable"].append(safe_path(path))
            finally:
                if descriptor is not None:
                    os.close(descriptor)
    result["status"] = "passed" if not any(result[k] for k in ("matches", "unreadable", "symlinks")) else "failed"
    if result["status"] == "passed" and result["accepted_exceptions"]:
        result["status"] = "passed_with_accepted_exceptions"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--bundle", action="append", required=True)
    parser.add_argument("--env-file")
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--stream-label")
    parser.add_argument("--accepted-milvus-native-root")
    parser.add_argument("--mysql-socket-link")
    args = parser.parse_args()
    from bisheng.core.config.credential_rotation import credentials
    from bisheng.core.config.credential_tool import check_bundle
    from bisheng.core.config.secret_crypto import get_keyring

    os.environ["BS_SECRET_KEYS_FILE"] = args.key_file
    get_keyring.cache_clear()
    phase = "source-validation"
    bundle_index = None
    try:
        values = set()
        milvus_values, other_values = set(), set()
        for index, bundle in enumerate(args.bundle):
            bundle_index = index
            settings, _, _ = check_bundle(bundle, env_file=args.env_file)
            component_values = credentials(settings)
            values.update(component_values.values())
            milvus_values.add(component_values.get("milvus", ""))
            other_values.update(v for k, v in component_values.items() if k != "milvus")
        phase = "scope-scan"
        if not args.path and not args.stream_label:
            raise ValueError("explicit scan scope required")
        result = scan_paths(
            args.path, values, milvus_base64_values=milvus_values - other_values,
            milvus_data_root=args.accepted_milvus_native_root, mysql_socket_link=args.mysql_socket_link,
        )
        if args.stream_label:
            patterns = variants(values)
            label = args.stream_label.encode()
            for pattern in sorted(patterns, key=len, reverse=True):
                label = label.replace(pattern, b"<redacted>")
            result["stream"] = label.decode("utf-8", "replace")
            if scan_stream(sys.stdin.buffer, patterns):
                result["matches"].append(result["stream"])
                result["status"] = "failed"
    except Exception as error:
        # Paths/config/parser exceptions may contain credentials. Fixed message only.
        print(json.dumps({"status": "failed", "reason": "source validation or scanning failed", "phase": phase, "bundle_index": bundle_index, "error_type": type(error).__name__}))
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] in {"passed", "passed_with_accepted_exceptions"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
