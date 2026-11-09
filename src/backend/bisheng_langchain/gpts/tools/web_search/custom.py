"""Restricted custom search core with isolated outbound transport."""

import base64
import http.client
import ipaddress
import json
import math
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import quote, quote_plus, urlsplit

import httpx

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_RESULTS = 100
MAX_FIELD_LENGTH = 8192
MAX_DEPTH = 32
_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(?:[.][A-Za-z_][A-Za-z0-9_-]*)*$")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class CustomSearchError(ValueError):
    """Safe user-facing error without upstream details."""


def _path(value, root=False):
    if not isinstance(value, str) or (not value and not root) or (value and not _PATH.fullmatch(value)):
        raise CustomSearchError("Invalid mapping path")
    return value.split(".") if value else []


def _get(value, path):
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise CustomSearchError("Response does not match mapping")
        value = value[key]
    return value


def _redact(value, secret):
    if not secret:
        return value
    variants = {secret, quote(secret, safe=""), quote_plus(secret), base64.b64encode(secret.encode()).decode()}
    marker = next(
        candidate for candidate in ("[REDACTED]", "[MASKED]", "***", "") if not any(v in candidate for v in variants)
    )

    def clean(text):
        for variant in sorted(variants, key=len, reverse=True):
            text = text.replace(variant, marker)
        return text

    def walk(item):
        if isinstance(item, str):
            return clean(item)
        if isinstance(item, list):
            return [walk(v) for v in item]
        if isinstance(item, dict):
            return {clean(k): walk(v) for k, v in item.items()}
        return item

    return walk(value)


def _check_depth(value, depth=0):
    if depth > MAX_DEPTH:
        raise CustomSearchError("Response exceeds structural limit")
    if isinstance(value, dict):
        for child in value.values():
            _check_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_depth(child, depth + 1)


def build_request(operation, query, api_key=None):
    """Build a restricted request description without performing network I/O."""
    if not isinstance(operation, dict) or not isinstance(query, str) or len(query) > MAX_FIELD_LENGTH:
        raise CustomSearchError("Invalid search request")
    server, method, path = operation.get("server"), operation.get("method"), operation.get("path")
    try:
        parsed = urlsplit(server)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
        ):
            raise ValueError()
    except (ValueError, TypeError):
        raise CustomSearchError("Invalid search server") from None
    if (
        method not in ("GET", "POST")
        or not isinstance(path, str)
        or not path.startswith("/")
        or path.startswith("//")
        or any(c in path for c in "?#{}\\")
        or any(ord(c) < 32 for c in path)
    ):
        raise CustomSearchError("Invalid search operation")
    params, body, headers = {}, {}, {}

    def add(location, name, value):
        if location not in ("query", "body") or not isinstance(name, str) or not _NAME.fullmatch(name):
            raise CustomSearchError("Invalid search parameter")
        if location == "body" and method != "POST":
            raise CustomSearchError("Body parameters require POST")
        target = params if location == "query" else body
        if name in target:
            raise CustomSearchError("Duplicate search parameter")
        target[name] = value

    fixed = operation.get("fixed_params", [])
    if not isinstance(fixed, list) or len(fixed) > 100:
        raise CustomSearchError("Invalid fixed parameters")
    for param in fixed:
        if not isinstance(param, dict):
            raise CustomSearchError("Invalid fixed parameters")
        value = param.get("value")
        if (
            not isinstance(value, (str, int, float, bool))
            or (isinstance(value, float) and not math.isfinite(value))
            or (isinstance(value, str) and len(value) > MAX_FIELD_LENGTH)
        ):
            raise CustomSearchError("Invalid fixed parameter value")
        add(param.get("location"), param.get("name"), value)
    qp = operation.get("query_parameter")
    if not isinstance(qp, dict):
        raise CustomSearchError("Invalid query parameter")
    add(qp.get("location"), qp.get("name"), query)
    auth = operation.get("auth")
    if auth and auth != {"location": "none", "name": ""}:
        if (
            not isinstance(auth, dict)
            or auth.get("location") not in ("header", "query")
            or not isinstance(auth.get("name"), str)
            or not _NAME.fullmatch(auth["name"])
            or not isinstance(api_key, str)
            or not api_key
            or any(ord(c) < 32 or ord(c) == 127 for c in api_key)
        ):
            raise CustomSearchError("Invalid search authentication")
        if auth["location"] == "query":
            add("query", auth["name"], api_key)
        else:
            if auth["name"].lower() in ("host", "content-length", "transfer-encoding", "connection", "accept-encoding"):
                raise CustomSearchError("Invalid authentication header")
            headers[auth["name"]] = api_key
    return {"url": server.rstrip("/") + path, "method": method, "params": params, "json": body, "headers": headers}


def validate_mapping(mapping):
    """Validate field paths without contacting the search service."""
    if not isinstance(mapping, dict):
        raise CustomSearchError("Invalid mapping")
    paths = {name: _path(mapping.get(name), root=name == "results") for name in ("results", "title", "url", "snippet")}
    for name in ("source", "siteIcon", "datePublished"):
        if mapping.get(name) not in (None, ""):
            paths[name] = _path(mapping[name])
    return paths


def map_response(raw, mapping, normalize, api_key=None):
    """Return a redacted preview and normalized results from bounded JSON."""
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
        raise CustomSearchError("Response exceeds size limit")
    paths = validate_mapping(mapping)
    try:
        data = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _check_depth(data)
        items = _get(data, paths["results"])
        if not isinstance(items, list) or len(items) > MAX_RESULTS:
            raise CustomSearchError("Response results are invalid or exceed limit")
        results = []
        for item in items:
            values = {name: _get(item, path) for name, path in paths.items() if name != "results"}
            if any(not isinstance(value, str) or len(value) > MAX_FIELD_LENGTH for value in values.values()):
                raise CustomSearchError("Response field is invalid or exceeds limit")
            values = {name: _redact(value, api_key) for name, value in values.items()}
            try:
                url = urlsplit(values["url"])
                valid = (
                    url.scheme in ("http", "https")
                    and bool(url.hostname)
                    and url.username is None
                    and url.password is None
                    and url.port != 0
                )
            except ValueError:
                valid = False
            if valid:
                results.append(
                    normalize(
                        title=values["title"],
                        url=values["url"],
                        snippet=values["snippet"],
                        source=values.get("source"),
                        site_icon=values.get("siteIcon"),
                        date_published=values.get("datePublished"),
                    )
                )
        return _redact(data, api_key), results
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, CustomSearchError):
            raise
        raise CustomSearchError("Invalid JSON search response") from None


_NETWORK_SLOTS = threading.BoundedSemaphore(4)
_NETWORK_TIMEOUT = 20


def _run_worker(payload, command):
    if not _NETWORK_SLOTS.acquire(blocking=False):
        raise CustomSearchError("Search network capacity exceeded")
    process = None
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={}, close_fds=True
        )
        try:
            output, _ = process.communicate(payload, timeout=_NETWORK_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise CustomSearchError("Search service request timed out") from None
        if process.returncode != 0 or len(output) > 4 * ((MAX_RESPONSE_BYTES + 2) // 3):
            raise CustomSearchError("Search service request failed")
        try:
            return base64.b64decode(output, validate=True)
        except ValueError:
            raise CustomSearchError("Search service request failed") from None
    except OSError:
        raise CustomSearchError("Search service request failed") from None
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        _NETWORK_SLOTS.release()


def execute_request(request, *, schema=False):
    """Run the isolated worker with separately authorized search or schema origins."""
    try:
        if schema:
            if (
                not isinstance(request, dict)
                or request.get("method") != "GET"
                or any(request.get(key) != {} for key in ("params", "json", "headers"))
            ):
                raise CustomSearchError("Invalid schema request")
            parsed = urlsplit(request.get("url"))
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.port == 0
            ):
                raise CustomSearchError("Invalid schema URL")
        origin_key = "BS_CUSTOM_SCHEMA_ORIGINS" if schema else "BS_CUSTOM_SEARCH_ORIGINS"
        origins = list(filter(None, os.environ.get(origin_key, "").split(",")))
        ports = [int(value) for value in os.environ.get("BS_CUSTOM_SEARCH_PORTS", "").split(",") if value]
        networks = list(filter(None, os.environ.get("BS_CUSTOM_SEARCH_PRIVATE_CIDRS", "").split(",")))
        if not origins or not ports:
            raise CustomSearchError("Search network policy is not configured")
        payload = json.dumps(
            {
                "request": request,
                "origins": origins,
                "ports": ports,
                "private_cidrs": networks,
                "ca_file": os.environ.get("BS_CUSTOM_SEARCH_CA_FILE") or None,
            },
            allow_nan=False,
        ).encode()
        if len(payload) > MAX_RESPONSE_BYTES:
            raise CustomSearchError("Search request exceeds size limit")
    except (TypeError, ValueError):
        raise CustomSearchError("Invalid search network policy") from None
    return _run_worker(payload, [sys.executable, "-I", str(Path(__file__).resolve())])


_LIMIT = 1024 * 1024


_PRIVATE = tuple(map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")))


def allowed(address, private):
    ip = ipaddress.ip_address(address)
    if (
        getattr(ip, "ipv4_mapped", None) is not None
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        return False
    return ip.is_global or (any(ip in net for net in _PRIVATE) and any(ip in net for net in private))


def fetch(data):
    request = data["request"]
    parsed = urlsplit(request["url"])
    host = parsed.hostname
    if (
        not host
        or parsed.scheme not in ("http", "https")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid destination")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    authority = f"[{host}]" if ":" in host else host
    origin = f"{parsed.scheme}://{authority}:{port}"
    if origin not in data["origins"] or port not in data["ports"]:
        raise ValueError("destination not authorized")
    private = [ipaddress.ip_network(net, strict=True) for net in data["private_cidrs"]]
    addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    if not addresses or any(not allowed(address, private) for address in addresses):
        raise ValueError("destination not allowed")
    headers = dict(request["headers"])
    headers["Host"] = authority + (f":{port}" if parsed.port is not None else "")
    headers["Accept-Encoding"] = "identity"
    prepared = httpx.Request(
        request["method"],
        request["url"],
        params=request["params"],
        json=request["json"] if request["method"] == "POST" else None,
        headers=headers,
    )
    connection = http.client.HTTPConnection(host, port, timeout=5)
    candidates = sorted(addresses)
    for index, address in enumerate(candidates):
        try:
            sock = socket.create_connection((address, port), timeout=5)
            break
        except (PermissionError, ssl.SSLError):
            raise
        except OSError:
            if index == len(candidates) - 1:
                raise
    try:
        if ipaddress.ip_address(sock.getpeername()[0]) != ipaddress.ip_address(address):
            raise ValueError("peer mismatch")
        if parsed.scheme == "https":
            sock = ssl.create_default_context(cafile=data.get("ca_file")).wrap_socket(sock, server_hostname=host)
        connection.sock = sock
        connection.request(
            prepared.method,
            prepared.url.raw_path.decode("ascii"),
            body=prepared.content,
            headers=dict(prepared.headers),
        )
        response = connection.getresponse()
        if not 200 <= response.status < 300 or response.getheader("content-encoding", "identity").lower() != "identity":
            raise ValueError("upstream error")
        declared = response.getheader("content-length")
        if declared is not None and (
            not declared.isdecimal() or int(declared) > _LIMIT or response.getheader("transfer-encoding")
        ):
            raise ValueError("invalid response length")
        body = bytearray()
        while True:
            chunk = response.read(min(65536, _LIMIT + 1 - len(body)))
            if not chunk:
                if declared is not None and len(body) != int(declared):
                    raise ValueError("truncated response")
                return bytes(body)
            body.extend(chunk)
            if len(body) > _LIMIT:
                raise ValueError("response too large")
    finally:
        connection.close()
        sock.close()


def main():
    try:
        data = json.loads(sys.stdin.buffer.read(_LIMIT + 1))
        result = fetch(data)
        sys.stdout.buffer.write(base64.b64encode(result))
    except Exception:
        # Do not print exception text, request data, response data, or headers.
        sys.exit(1)


if __name__ == "__main__":
    main()
