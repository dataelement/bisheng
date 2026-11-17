"""Read a bounded training package from a single administrator-selected source."""

import ftplib
import io
import ipaddress
import json
import posixpath
import socket
import ssl
import time
import zipfile
from contextlib import contextmanager
from urllib.parse import urlsplit

import urllib3
from minio import Minio

from .dataset_validation import MAX_BYTES, inspect_package, safe_path, validate_records

MAX_FILES = 500
MAX_SECONDS = 90


class RemoteDatasetError(ValueError):
    """Public errors contain context and paths, never raw connector exceptions or credentials."""


def checked_endpoint(endpoint: str, source: str):
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        raise RemoteDatasetError("Invalid connection endpoint") from None
    schemes = {"ftp", "ftps"} if source == "ftp" else {"http", "https"}
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
        port = parsed.port or (21 if source == "ftp" else 443 if parsed.scheme == "https" else 80)
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

            def read(path, remaining):
                if remaining <= 0:
                    raise RemoteDatasetError("Dataset exceeds the 20 MiB import budget")
                chunks = []
                size = 0

                def receive(chunk):
                    nonlocal size
                    if time.monotonic() > deadline:
                        raise RemoteDatasetError("Remote import exceeded its time budget")
                    size += len(chunk)
                    if size > remaining:
                        raise RemoteDatasetError("Dataset exceeds the 20 MiB import budget")
                    chunks.append(chunk)

                client.retrbinary("RETR " + path, receive, blocksize=65536)
                return b"".join(chunks)

            yield read
        except RemoteDatasetError:
            raise
        except ftplib.all_errors:
            raise RemoteDatasetError(
                "FTP connection or read failed; check the account, file path and passive-mode network access"
            ) from None
        finally:
            client.close()
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
                if remaining <= 0:
                    raise RemoteDatasetError("Dataset exceeds the 20 MiB import budget")
                response = client.get_object(connection.bucket, path)
                try:
                    output = bytearray()
                    while True:
                        if time.monotonic() > deadline:
                            raise RemoteDatasetError("Remote import exceeded its time budget")
                        chunk = response.read(min(65536, remaining + 1 - len(output)))
                        if not chunk:
                            return bytes(output)
                        output.extend(chunk)
                        if len(output) > remaining:
                            raise RemoteDatasetError("Dataset exceeds the 20 MiB import budget")
                finally:
                    response.close()
                    response.release_conn()

            yield read
        except RemoteDatasetError:
            raise
        except Exception:
            # Connector errors can embed signed headers; only the sanitized error reaches callers/logs.
            raise RemoteDatasetError(
                "S3 connection or read failed; check endpoint, bucket, credentials and object permissions"
            ) from None
        finally:
            http.clear()


def assemble_remote_dataset(request, read):
    start = time.monotonic()
    if bool(request.manifest_path) == bool(request.manifest_text):
        raise RemoteDatasetError("Provide either a remote manifest path or a local manifest, not both")
    name = request.manifest_filename if request.manifest_text else request.manifest_path
    try:
        source_path = checked_remote_path(request.manifest_path) if request.manifest_path else ""
        if request.source == "ftp" and (request.manifest_path or "").startswith("/"):
            source_path = "/" + source_path
        raw = request.manifest_text.encode("utf-8") if request.manifest_text else read(source_path, MAX_BYTES)
    except RemoteDatasetError:
        raise
    except Exception:
        raise RemoteDatasetError("Unable to read the manifest; check its path and read permission") from None
    if not raw or len(raw) > MAX_BYTES:
        raise RemoteDatasetError("Manifest/package must be between 1 byte and 20 MiB")
    if name.lower().endswith(".zip"):
        try:
            modality, _, _ = inspect_package(raw)
        except (ValueError, OSError, zipfile.BadZipFile) as exc:
            raise RemoteDatasetError(f"Invalid ZIP package: {exc}") from None
        if modality != request.data_type:
            raise RemoteDatasetError("Dataset modality differs from the selected task type")
        return raw
    if not name.lower().endswith((".json", ".jsonl")):
        raise RemoteDatasetError("Manifest must be JSON or JSONL, or a self-contained ZIP package")
    try:
        text = raw.decode("utf-8-sig")
        records = (
            [json.loads(line) for line in text.splitlines() if line.strip()]
            if name.lower().endswith(".jsonl")
            else json.loads(text)
        )
        validate_records(records, request.data_type)
    except (ValueError, UnicodeDecodeError) as exc:
        # JSONDecodeError text contains only positions, never the document payload.
        raise RemoteDatasetError(f"Invalid manifest: {exc}") from None
    media_root = checked_remote_path(request.media_root, allow_empty=True)
    if request.source == "ftp" and request.media_root.startswith("/"):
        media_root = "/" + media_root
    output = io.BytesIO()
    normalized = json.dumps(records, ensure_ascii=False).encode("utf-8")
    used = len(normalized)
    if used > MAX_BYTES:
        raise RemoteDatasetError("Normalized manifest exceeds the 20 MiB import budget")
    seen = set()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("train.json", normalized)
        for index, record in enumerate(records):
            for media in record.get("images", []) + record.get("videos", []):
                if not safe_path(media) or any(char in media for char in "\r\n"):
                    raise RemoteDatasetError(f"Sample {index + 1}: unsafe media reference")
                if media in seen:
                    continue
                if len(seen) >= MAX_FILES or time.monotonic() - start > MAX_SECONDS:
                    raise RemoteDatasetError("Import exceeds 500 media files or the time budget")
                try:
                    content = read(posixpath.join(media_root, media), MAX_BYTES - used)
                except Exception:
                    raise RemoteDatasetError(
                        f"Sample {index + 1}: cannot read media {media}; check its path, permission and size budget"
                    ) from None
                used += len(content)
                if used > MAX_BYTES:
                    raise RemoteDatasetError("Dataset exceeds the 20 MiB import budget")
                archive.writestr(media, content)
                seen.add(media)
    raw = output.getvalue()
    try:
        inspect_package(raw)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise RemoteDatasetError(f"Imported dataset validation failed: {exc}") from None
    return raw


def import_remote_bytes(request):
    with remote_reader(request) as read:
        return assemble_remote_dataset(request, read)
