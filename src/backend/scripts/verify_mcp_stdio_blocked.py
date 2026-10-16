"""Verify a remote BiSheng rejects STDIO MCP on /mcp/test and /mcp/refresh.

Patched servers return business code 15025 on /mcp/test (and /mcp/schema)
without spawning a process. /mcp/refresh stays HTTP 200; any saved STDIO
server must appear in the returned error-name list instead of reconnecting.

This is a read-mostly probe. The STDIO payload uses a non-existent command
name so an unpatched host cannot run a real OS utility.

Run from src/backend/:

    bash scripts/verify_mcp_stdio_blocked.sh --base-url http://HOST:7860 \\
        --username admin --password '***'

    BISHENG_PASSWORD='***' bash scripts/verify_mcp_stdio_blocked.sh \\
        --base-url http://HOST:7860 --username admin

Exit 0 = required checks passed. Exit 1 = login/network. Exit 2 = /mcp/test
did not return 15025. Exit 3 = refresh still executed a saved STDIO tool.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from typing import Any
from urllib.parse import urljoin

import httpx

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

# Non-existent argv0: if the host is unpatched, spawn fails with ENOENT.
_PROBE_COMMAND = "bisheng-stdio-probe-not-a-binary"
_STDIO_SCHEMA = {
    "mcpServers": {
        "stdio-probe": {
            "type": "stdio",
            "command": _PROBE_COMMAND,
            "args": ["--noop"],
        }
    }
}
_EXPECTED_STDIO_CODE = 15025
_MCP_PRESET = 2


def _is_stdio_schema(raw: Any) -> bool:
    if not raw:
        return False
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        servers = payload.get("mcpServers") or {}
    except (TypeError, json.JSONDecodeError, AttributeError):
        return False
    for item in servers.values():
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").lower()
        if kind == "stdio" or "command" in item:
            return True
    return False


def _encrypt_password(password: str, public_key_pem: str) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


def _fetch_captcha(client: httpx.Client, api_base: str) -> tuple[str, bool, str]:
    resp = client.get(f"{api_base}/user/get_captcha")
    resp.raise_for_status()
    body = resp.json()
    if body.get("status_code") != 200:
        raise RuntimeError(f"get_captcha failed: {body}")
    data = body["data"]
    captcha_key = data["captcha_key"]
    required = bool(data.get("user_capthca"))
    image_b64 = data.get("captcha") or ""
    image_path = ""
    if image_b64:
        png = base64.b64decode(image_b64)
        image_path = os.path.abspath("mcp-stdio-login-captcha.png")
        with open(image_path, "wb") as fh:
            fh.write(png)
    return captcha_key, required, image_path


def _resolve_captcha_text(required: bool, image_path: str, provided: str) -> str:
    if provided:
        return provided.strip()
    if image_path:
        print(f"captcha image written to {image_path}")
    if not sys.stdin.isatty():
        raise RuntimeError(
            "this host requires a login captcha. Re-run with --captcha <4 chars> "
            "after opening the PNG, or pass --token from a browser cookie "
            "(access_token_cookie)."
        )
    hint = f" ({image_path})" if image_path else ""
    return input(f"enter login captcha{hint}: ").strip()


def _login(
    client: httpx.Client,
    api_base: str,
    username: str,
    password: str,
    captcha_text: str = "",
) -> str:
    key_resp = client.get(f"{api_base}/user/public_key")
    key_resp.raise_for_status()
    key_body = key_resp.json()
    if key_body.get("status_code") != 200:
        raise RuntimeError(f"public_key failed: {key_body}")
    encrypted = _encrypt_password(password, key_body["data"]["public_key"])

    captcha_key, captcha_required, image_path = _fetch_captcha(client, api_base)
    login_payload: dict[str, Any] = {"user_name": username, "password": encrypted}
    if captcha_required or captcha_text:
        login_payload["captcha_key"] = captcha_key
        login_payload["captcha"] = _resolve_captcha_text(captcha_required, image_path, captcha_text)

    login_resp = client.post(f"{api_base}/user/login", json=login_payload)
    login_resp.raise_for_status()
    login_body = login_resp.json()
    if login_body.get("status_code") != 200:
        raise RuntimeError(
            f"login failed: {login_body.get('status_message')}. If the host uses captcha, pass --captcha or --token."
        )
    token = login_body["data"]["access_token"]
    if not token:
        raise RuntimeError("login returned an empty access_token")
    return token


def _print_check(name: str, ok: bool, detail: str) -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}: {detail}")


def _check_mcp_test(client: httpx.Client, api_base: str) -> bool:
    resp = client.post(
        f"{api_base}/tool/mcp/test",
        json={
            "openapi_schema": json.dumps(_STDIO_SCHEMA, ensure_ascii=False),
            "extra": json.dumps(
                {"name": "stdio-probe", "description": "probe", "inputSchema": {}},
                ensure_ascii=False,
            ),
            "request_params": {},
        },
    )
    body = resp.json()
    code = body.get("status_code")
    ok = resp.status_code == 200 and code == _EXPECTED_STDIO_CODE
    _print_check(
        "POST /tool/mcp/test",
        ok,
        f"http={resp.status_code} status_code={code} message={body.get('status_message')!r}",
    )
    return ok


def _check_mcp_schema(client: httpx.Client, api_base: str) -> bool:
    resp = client.post(
        f"{api_base}/tool/mcp/schema",
        json={"file_content": json.dumps(_STDIO_SCHEMA, ensure_ascii=False)},
    )
    body = resp.json()
    code = body.get("status_code")
    ok = resp.status_code == 200 and code == _EXPECTED_STDIO_CODE
    _print_check(
        "POST /tool/mcp/schema",
        ok,
        f"http={resp.status_code} status_code={code} message={body.get('status_message')!r}",
    )
    return ok


def _list_stdio_tool_names(client: httpx.Client, api_base: str) -> list[str]:
    resp = client.get(f"{api_base}/tool", params={"is_preset": _MCP_PRESET, "action": "visible"})
    resp.raise_for_status()
    body = resp.json()
    if body.get("status_code") != 200:
        raise RuntimeError(f"list tools failed: {body}")
    names: list[str] = []
    for item in body.get("data") or []:
        if _is_stdio_schema(item.get("openapi_schema")):
            names.append(str(item.get("name") or item.get("id")))
    return names


def _check_mcp_refresh(client: httpx.Client, api_base: str) -> tuple[bool, bool]:
    """Return (refresh_http_ok, stdio_not_executed)."""
    stdio_names = _list_stdio_tool_names(client, api_base)
    resp = client.post(f"{api_base}/tool/mcp/refresh")
    body = resp.json()
    http_ok = resp.status_code == 200 and body.get("status_code") == 200
    error_names = [str(n) for n in (body.get("data") or [])]
    _print_check(
        "POST /tool/mcp/refresh",
        http_ok,
        f"http={resp.status_code} status_code={body.get('status_code')} "
        f"error_names={error_names} saved_stdio={stdio_names}",
    )
    if not stdio_names:
        print("      (no saved STDIO MCP tools; refresh cannot prove execution is blocked)")
        return http_ok, True
    executed = [name for name in stdio_names if name not in error_names]
    blocked = not executed
    _print_check(
        "refresh did not reconnect saved STDIO",
        blocked,
        f"unblocked={executed}" if executed else "all saved STDIO names are in the error list",
    )
    return http_ok, blocked


def run(args: argparse.Namespace) -> int:
    origin = args.base_url.rstrip("/")
    api_base = origin if origin.endswith("/api/v1") else urljoin(origin + "/", "api/v1")
    password = args.password or os.environ.get("BISHENG_PASSWORD", "")
    token = args.token or os.environ.get("BISHENG_TOKEN", "")

    try:
        with httpx.Client(timeout=args.timeout, follow_redirects=True) as client:
            if not token:
                if not args.username or not password:
                    print("need --username/--password or BISHENG_PASSWORD, or --token", file=sys.stderr)
                    return 1
                token = _login(client, api_base, args.username, password, captcha_text=args.captcha)
                print(f"logged in as {args.username} @ {api_base}")
            client.headers["Cookie"] = f"access_token_cookie={token}"

            test_ok = _check_mcp_test(client, api_base)
            schema_ok = True
            if args.include_schema:
                schema_ok = _check_mcp_schema(client, api_base)
            refresh_http_ok, refresh_blocked = _check_mcp_refresh(client, api_base)
    except httpx.HTTPError as exc:
        print(f"[FAIL] network: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    if not test_ok:
        return 2
    if not schema_ok:
        return 2
    if not refresh_http_ok or not refresh_blocked:
        return 3
    print("all required checks passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="e.g. http://192.168.1.10:7860")
    parser.add_argument("--username", default=os.environ.get("BISHENG_USERNAME", ""))
    parser.add_argument("--password", default="", help="or set BISHENG_PASSWORD")
    parser.add_argument("--token", default="", help="or set BISHENG_TOKEN (skips login)")
    parser.add_argument(
        "--captcha",
        default="",
        help="4-char login captcha; image is saved to mcp-stdio-login-captcha.png",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--skip-schema", action="store_true", help="skip POST /tool/mcp/schema")
    args = parser.parse_args()
    args.include_schema = not args.skip_schema
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
