"""Register a training dataset that stays in the customer's FTP / FTPS / SFTP / S3 storage.

The platform reads the manifest, confirms every referenced file exists and records its size, and keeps a
small preview. Images and videos never pass through the platform: the training service downloads them
from the source when a job starts.
"""

import base64
import ftplib
import hashlib
import ipaddress
import posixpath
import socket
import ssl
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

import urllib3
from minio import Minio

from .dataset_validation import (
    MEDIA_MAX_BYTES,
    PREVIEW_SAMPLES,
    TEXT_MAX_BYTES,
    build_preview,
    inspect_media,
    parse_manifest,
    safe_path,
    validate_records,
)

MAX_FILES = 200_000  # media files one remote dataset may reference
MAX_SECONDS = 300  # reading the manifest, listing sizes and fetching preview samples


class RemoteDatasetError(ValueError):
    """Public errors contain context and paths, never raw connector exceptions or credentials."""


def checked_endpoint(endpoint: str, source: str):
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        raise RemoteDatasetError("Invalid connection endpoint") from None
    schemes = {"ftp": {"ftp", "ftps"}, "sftp": {"sftp"}}.get(source, {"http", "https"})
    if (
        parsed.scheme not in schemes
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RemoteDatasetError("Connection endpoint must be a protocol and host, without credentials or a file path")
    if any(char in endpoint for char in "\r\n\x00"):
        raise RemoteDatasetError("Invalid endpoint")
    try:
        port = parsed.port or {"ftp": 21, "sftp": 22}.get(source) or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            ip = getattr(ip, "ipv4_mapped", None) or ip
            if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
                raise RemoteDatasetError("Loopback, metadata, multicast and reserved network addresses are not allowed")
    except (ValueError, OSError) as exc:
        if isinstance(exc, RemoteDatasetError):
            raise
        raise RemoteDatasetError("Connection endpoint could not be resolved or has an invalid port") from None
    return parsed, port, addresses[0][4][0]


def checked_remote_path(path: str, *, allow_empty=False):
    stripped = path.strip("/")
    if not stripped and allow_empty:
        return ""
    if not safe_path(stripped) or any(char in path for char in "\r\n"):
        raise RemoteDatasetError("Remote paths must not contain traversal, URLs, backslashes or control characters")
    return stripped


def pinned_http_pool(host: str, address: str, port: int):
    """Keep HTTP Host and TLS SNI while pinning sockets to the validated address."""
    from urllib3.connection import HTTPConnection, HTTPSConnection
    from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
    from urllib3.util.connection import create_connection

    def connect(connection):
        if connection.host != host or connection.port != port:
            raise RemoteDatasetError("S3 redirects to a different endpoint are not allowed")
        return create_connection(
            (address, port),
            connection.timeout,
            source_address=connection.source_address,
            socket_options=connection.socket_options,
        )

    class PinnedHTTPConnection(HTTPConnection):
        _new_conn = connect

    class PinnedHTTPSConnection(HTTPSConnection):
        _new_conn = connect

    class PinnedHTTPPool(HTTPConnectionPool):
        ConnectionCls = PinnedHTTPConnection

    class PinnedHTTPSPool(HTTPSConnectionPool):
        ConnectionCls = PinnedHTTPSConnection

    manager = urllib3.PoolManager(timeout=urllib3.Timeout(connect=10, read=10), retries=False)
    manager.pool_classes_by_scheme = {"http": PinnedHTTPPool, "https": PinnedHTTPSPool}
    return manager


def check_host_key(key, expected: str | None) -> None:
    """Compare the server key with an OpenSSH-style SHA256 fingerprint when the administrator supplies one."""
    if not expected:
        return
    actual = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    if expected.strip().rstrip("=") != actual:
        raise RemoteDatasetError("SFTP host fingerprint does not match; confirm the server key with its administrator")


class _Session:
    """What the plan builder needs from a connector: bounded reads and per-directory size listings."""

    def __init__(self, read, list_dir, deadline):
        self.read = read
        self._list_dir = list_dir
        self._deadline = deadline

    def sizes(self, paths):
        by_directory = {}
        for path in paths:
            by_directory.setdefault(posixpath.dirname(path), []).append(path)
        result = {}
        for directory, members in by_directory.items():
            if time.monotonic() > self._deadline:
                raise RemoteDatasetError("Listing the remote files exceeded the time budget")
            listing = self._list_dir(directory, members)
            for path in members:
                result[path] = listing.get(path)
        return result


def _bounded(chunks, remaining, deadline):
    output = bytearray()
    for chunk in chunks:
        if time.monotonic() > deadline:
            raise RemoteDatasetError("Remote import exceeded its time budget")
        output.extend(chunk)
        if len(output) > remaining:
            raise RemoteDatasetError("Remote file exceeds the size budget")
    return bytes(output)


@contextmanager
def remote_reader(request):
    connection = request.connection
    deadline = time.monotonic() + MAX_SECONDS
    parsed, port, address = checked_endpoint(connection.endpoint, request.source)
    if request.source == "ftp":
        client = (
            ftplib.FTP_TLS(context=ssl.create_default_context())
            if connection.tls or parsed.scheme == "ftps"
            else ftplib.FTP()
        )
        try:
            # Pin the validated control connection address while preserving the TLS hostname.
            client.host = parsed.hostname
            client.timeout = 10
            client.sock = socket.create_connection((address, port), timeout=10)
            client.af = client.sock.family
            client.file = client.sock.makefile("r", encoding=client.encoding)
            client.welcome = client.getresp()
            client.login(
                connection.username or "anonymous",
                connection.password.get_secret_value() if connection.password else "",
            )
            if isinstance(client, ftplib.FTP_TLS):
                client.prot_p()
            client.set_pasv(True)
            client.voidcmd("TYPE I")

            def read(path, remaining):
                chunks = []

                def receive(chunk):
                    chunks.append(chunk)
                    if time.monotonic() > deadline or sum(map(len, chunks)) > remaining:
                        raise RemoteDatasetError("Remote file exceeds the size or time budget")

                client.retrbinary("RETR " + path, receive, blocksize=65536)
                return b"".join(chunks)

            def list_dir(directory, members):
                try:
                    entries = client.mlsd(directory or ".", facts=["size", "type"])
                    names = {name: int(facts["size"]) for name, facts in entries if facts.get("type") == "file"}
                    return {path: names.get(posixpath.basename(path)) for path in members}
                except ftplib.error_perm:
                    # Servers without MLSD answer SIZE for each file instead.
                    listing = {}
                    for path in members:
                        try:
                            listing[path] = client.size(path)
                        except ftplib.error_perm:
                            listing[path] = None
                    return listing

            yield _Session(read, list_dir, deadline)
        except RemoteDatasetError:
            raise
        except ftplib.all_errors:
            raise RemoteDatasetError(
                "FTP connection or read failed; check the account, file path and passive-mode network access"
            ) from None
        finally:
            client.close()
    elif request.source == "sftp":
        if not connection.username:
            raise RemoteDatasetError("SFTP username is required")
        try:
            # Imported here so an image built before the SFTP dependency only loses SFTP, not the module.
            import paramiko
        except ImportError:
            raise RemoteDatasetError(
                "SFTP support is not installed on this server; rebuild the backend image"
            ) from None
        transport = None
        try:
            # Connect to the validated address so DNS cannot change between the check and the session.
            transport = paramiko.Transport(socket.create_connection((address, port), timeout=10))
            transport.banner_timeout = 10
            transport.auth_timeout = 10
            transport.start_client(timeout=10)
            check_host_key(transport.get_remote_server_key(), connection.host_fingerprint)
            transport.auth_password(
                connection.username, connection.password.get_secret_value() if connection.password else ""
            )
            client = paramiko.SFTPClient.from_transport(transport)
            client.get_channel().settimeout(30)

            def read(path, remaining):
                with client.open(path, "rb") as handle:
                    return _bounded(iter(lambda: handle.read(65536), b""), remaining, deadline)

            def list_dir(directory, members):
                try:
                    names = {item.filename: item.st_size for item in client.listdir_attr(directory or ".")}
                except OSError:
                    names = {}
                return {path: names.get(posixpath.basename(path)) for path in members}

            yield _Session(read, list_dir, deadline)
        except RemoteDatasetError:
            raise
        except (paramiko.SSHException, OSError, EOFError):
            raise RemoteDatasetError(
                "SFTP connection or read failed; check the account, host fingerprint, file path and network access"
            ) from None
        finally:
            if transport is not None:
                transport.close()
    else:
        if not connection.bucket:
            raise RemoteDatasetError("S3 bucket is required")
        http = pinned_http_pool(parsed.hostname, address, port)
        try:
            client = Minio(
                parsed.netloc,
                access_key=connection.access_key.get_secret_value() if connection.access_key else None,
                secret_key=connection.secret_key.get_secret_value() if connection.secret_key else None,
                session_token=connection.session_token.get_secret_value() if connection.session_token else None,
                secure=parsed.scheme == "https",
                region=connection.region or "us-east-1",
                http_client=http,
            )
            client.disable_virtual_style_endpoint()

            def read(path, remaining):
                response = client.get_object(connection.bucket, path)
                try:
                    return _bounded(iter(lambda: response.read(65536), b""), remaining, deadline)
                finally:
                    response.close()
                    response.release_conn()

            def list_dir(directory, members):
                prefix = directory + "/" if directory else ""
                names = {
                    item.object_name: item.size
                    for item in client.list_objects(connection.bucket, prefix=prefix, recursive=False)
                    if not item.is_dir
                }
                return {path: names.get(path) for path in members}

            yield _Session(read, list_dir, deadline)
        except RemoteDatasetError:
            raise
        except Exception:
            # Connector errors can embed signed headers; only the sanitized error reaches callers/logs.
            raise RemoteDatasetError(
                "S3 connection or read failed; check endpoint, bucket, credentials and object permissions"
            ) from None
        finally:
            http.clear()


def _source_path(request, path):
    stripped = checked_remote_path(path, allow_empty=True)
    if request.source in {"ftp", "sftp"} and path.startswith("/"):
        return "/" + stripped
    return stripped


def build_remote_plan(request, session):
    """Return (plan, records, preview, facts). Text records are the data itself; media stay at the source."""
    if bool(request.manifest_path) == bool(request.manifest_text):
        raise RemoteDatasetError("Provide either a remote manifest path or a local manifest, not both")
    if request.manifest_path and request.manifest_path.lower().endswith(".zip"):
        zip_path = _source_path(request, request.manifest_path)
        size = session.sizes([zip_path]).get(zip_path)
        if not size:
            raise RemoteDatasetError(f"Remote ZIP not found or empty: {request.manifest_path}")
        plan = {
            "kind": "remote_plan",
            "version": 1,
            "data_type": request.data_type,
            "layout": "zip",
            "zip": {"path": zip_path, "size": size},
        }
        return plan, None, None, {"samples": 0, "media": 0, "total_bytes": size, "validation_stage": "size_checked"}
    name = request.manifest_filename if request.manifest_text else request.manifest_path
    if not name.lower().endswith((".json", ".jsonl")):
        raise RemoteDatasetError("Manifest must be JSON or JSONL, or a self-contained ZIP package")
    try:
        raw = (
            request.manifest_text.encode("utf-8")
            if request.manifest_text
            else session.read(_source_path(request, request.manifest_path), TEXT_MAX_BYTES)
        )
    except RemoteDatasetError:
        raise
    except Exception:
        raise RemoteDatasetError("Unable to read the manifest; check its path and read permission") from None
    if not raw or len(raw) > TEXT_MAX_BYTES:
        raise RemoteDatasetError("Manifest must be between 1 byte and 200 MiB")
    try:
        records = parse_manifest(raw, name.lower())
        validate_records(records, request.data_type)
    except (ValueError, UnicodeDecodeError) as exc:
        # JSONDecodeError text contains only positions, never the document payload.
        raise RemoteDatasetError(f"Invalid manifest: {exc}") from None
    if request.data_type == "text":
        return (
            None,
            records,
            None,
            {"samples": len(records), "media": 0, "total_bytes": len(raw), "validation_stage": "content_checked"},
        )
    media_root = _source_path(request, request.media_root)
    names = {}
    for index, record in enumerate(records):
        for media in record.get("images", []) + record.get("videos", []):
            if not safe_path(media) or any(char in media for char in "\r\n"):
                raise RemoteDatasetError(f"Sample {index + 1}: unsafe media reference")
            names.setdefault(media, index)
    if len(names) > MAX_FILES:
        raise RemoteDatasetError("Dataset references more than 200,000 media files")
    remote = {media: posixpath.join(media_root, media) if media_root else media for media in names}
    sizes = session.sizes(list(remote.values()))
    for media, index in names.items():
        if not sizes.get(remote[media]):
            raise RemoteDatasetError(f"Sample {index + 1}: media not found or empty at the source: {media}")
    files = [{"path": media, "size": sizes[remote[media]]} for media in names]

    def sample(media):
        content = session.read(remote[media], MEDIA_MAX_BYTES)
        inspect_media(content, media, request.data_type)
        return content

    try:
        preview = build_preview(records, sample)
    except ValueError as exc:
        raise RemoteDatasetError(f"Preview sample check failed: {exc}") from None
    plan = {
        "kind": "remote_plan",
        "version": 1,
        "data_type": request.data_type,
        "layout": "manifest",
        "records": records,
        "files": files,
    }
    facts = {
        "samples": len(records),
        "media": len(files),
        "total_bytes": sum(item["size"] for item in files),
        "validation_stage": "manifest_checked",
        "preview_samples": min(len(records), PREVIEW_SAMPLES),
    }
    return plan, records, preview, facts


def plan_remote_dataset(request):
    with remote_reader(request) as session:
        return build_remote_plan(request, session)


def public_source(request, plan):
    """Non-secret connection facts kept with the version; secrets are entered again for every training job."""
    connection = request.connection
    if plan["layout"] == "zip":
        probe = plan["zip"]["path"]
        media_root = ""
    else:
        media_root = _source_path(request, request.media_root)
        first = plan["files"][0]["path"]
        probe = posixpath.join(media_root, first) if media_root else first
    return {
        "type": request.source,
        "endpoint": connection.endpoint.rstrip("/"),
        "username": connection.username,
        "bucket": connection.bucket,
        "region": connection.region,
        "tls": connection.tls,
        "host_fingerprint": connection.host_fingerprint,
        "layout": plan["layout"],
        "path": request.manifest_path or request.manifest_filename,
        "media_root": media_root,
        "probe": probe,
    }
