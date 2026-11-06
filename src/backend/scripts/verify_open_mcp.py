"""Verify the F067 remote MCP endpoint without mutating business data.

The script connects with the official MCP Python client, initializes a
Streamable HTTP session, lists the tools visible to the supplied credential,
and optionally calls one of the three read-only tools.  It never prints the
credential and does not offer write or destructive tool calls.

Run from ``src/backend``::

    export BISHENG_API_KEY='<api-key-or-personal-access-token>'
    .venv/bin/python scripts/verify_open_mcp.py \
      --url https://bisheng.example.com/api/v2/mcp \
      --expected-profile full

An optional read-only smoke call can be added with ``--call-tool`` and
``--arguments-json``.  The credential can be read from a differently named
environment variable with ``--api-key-env``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

EXPECTED_TOOL_NAMES = frozenset(
    {
        "bisheng_knowledge_list",
        "bisheng_knowledge_create",
        "bisheng_knowledge_update",
        "bisheng_knowledge_delete",
        "bisheng_knowledge_clear",
        "bisheng_knowledge_retrieve",
        "bisheng_knowledge_file_upload",
        "bisheng_knowledge_file_list",
        "bisheng_knowledge_file_delete",
        "bisheng_knowledge_files_delete",
    }
)
READ_ONLY_TOOL_NAMES = frozenset(
    {
        "bisheng_knowledge_list",
        "bisheng_knowledge_retrieve",
        "bisheng_knowledge_file_list",
    }
)
EXPECTED_PROFILES = {
    "full": EXPECTED_TOOL_NAMES,
    "pat": READ_ONLY_TOOL_NAMES,
    "scope-filtered": None,
}


def _parse_json_object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(decoded, dict):
        raise argparse.ArgumentTypeError("arguments must be a JSON object")
    return decoded


def _endpoint(value: str) -> str:
    endpoint = value.strip().rstrip("/")
    parts = urlsplit(endpoint)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise argparse.ArgumentTypeError("URL must be an absolute http(s) endpoint")
    if parts.username or parts.password:
        raise argparse.ArgumentTypeError("URL must not contain userinfo")
    if parts.query or parts.fragment:
        raise argparse.ArgumentTypeError("URL must not contain a query or fragment")
    return endpoint


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        type=_endpoint,
        default=os.getenv("BISHENG_MCP_URL"),
        help="MCP endpoint; defaults to BISHENG_MCP_URL",
    )
    parser.add_argument(
        "--api-key-env",
        default="BISHENG_API_KEY",
        help="environment variable holding the API key or PAT (default: BISHENG_API_KEY)",
    )
    parser.add_argument(
        "--on-behalf-of",
        default=None,
        help="external user ID for a delegated-service-account credential",
    )
    parser.add_argument(
        "--end-user",
        default=None,
        help="optional end-user partition header; mutually exclusive with --on-behalf-of",
    )
    parser.add_argument(
        "--expected-profile",
        choices=sorted(EXPECTED_PROFILES),
        default="full",
        help="expected exact tool set: full (default), pat, or scope-filtered diagnostic mode",
    )
    parser.add_argument(
        "--call-tool",
        choices=sorted(READ_ONLY_TOOL_NAMES),
        help="optionally call one discovered read-only tool",
    )
    parser.add_argument(
        "--arguments-json",
        type=_parse_json_object,
        default={},
        help="JSON object passed to --call-tool (default: {})",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="HTTP connect/request timeout (default: 30)",
    )
    return parser


def _tool_differences(tool_names: Sequence[str], expected_profile: str) -> tuple[list[str], list[str]]:
    visible = set(tool_names)
    expected = EXPECTED_PROFILES[expected_profile]
    if expected is None:
        return [], sorted(visible - EXPECTED_TOOL_NAMES)
    return sorted(expected - visible), sorted(visible - expected)


def _tool_result_summary(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    content = getattr(result, "content", []) or []
    return {
        "is_error": bool(getattr(result, "isError", False)),
        "has_structured_content": structured is not None,
        "structured_content_type": type(structured).__name__ if structured is not None else None,
        "content_block_types": [getattr(item, "type", type(item).__name__) for item in content],
    }


async def _verify(args: argparse.Namespace, api_key: str) -> int:
    headers = {"Authorization": f"Bearer {api_key}"}
    if args.on_behalf_of:
        headers["X-On-Behalf-Of"] = args.on_behalf_of
    if args.end_user:
        headers["X-End-User"] = args.end_user

    async with streamablehttp_client(
        args.url,
        headers=headers,
        timeout=args.timeout_seconds,
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            tool_names = [tool.name for tool in listed.tools]
            missing, unexpected = _tool_differences(tool_names, args.expected_profile)
            print(
                json.dumps(
                    {
                        "endpoint": args.url,
                        "server": initialized.serverInfo.model_dump(mode="json"),
                        "protocol_version": initialized.protocolVersion,
                        "visible_tool_count": len(tool_names),
                        "visible_tools": tool_names,
                        "expected_profile": args.expected_profile,
                        "missing_tools": missing,
                        "unexpected_tools": unexpected,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            if missing or unexpected:
                print(
                    "verification failed: visible tools do not match the selected F067 profile",
                    file=sys.stderr,
                )
                return 4

            if not args.call_tool:
                return 0
            if args.call_tool not in tool_names:
                print(
                    f"verification failed: {args.call_tool} is not visible to this credential",
                    file=sys.stderr,
                )
                return 4

            result = await session.call_tool(args.call_tool, args.arguments_json)
            summary = _tool_result_summary(result)
            print(json.dumps({"called_tool": args.call_tool, **summary}, ensure_ascii=False, indent=2))
            return 4 if summary["is_error"] else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.url:
        parser.error("--url or BISHENG_MCP_URL is required")
    if args.on_behalf_of and args.end_user:
        parser.error("--on-behalf-of and --end-user are mutually exclusive")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    if args.arguments_json and not args.call_tool:
        parser.error("--arguments-json requires --call-tool")

    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key:
        print(f"missing credential: set environment variable {args.api_key_env}", file=sys.stderr)
        return 2

    try:
        return asyncio.run(_verify(args, api_key))
    except KeyboardInterrupt:
        print("verification interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        # Exception text from HTTP clients can contain response data.  Report the
        # exception class only so credentials and protected payloads stay out of logs.
        print(f"MCP verification failed ({type(exc).__name__})", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
