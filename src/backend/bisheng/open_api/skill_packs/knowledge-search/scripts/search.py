#!/usr/bin/env python3
"""Query the read-only knowledge endpoints (list + retrieve) and manage the key.

Credential lookup order for every call:

1. the environment variable ``KNOWLEDGE_API_KEY`` (explicit per-process override);
2. this skill's own credentials file, profile keyed by the platform Base URL.
   ``--configure`` writes it once; it is readable only by the current user and
   survives new agent sessions, which do not inherit shell profile files.

The script runs on any Python 3.8+ with the standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

# Rendered with the instance address when the pack is downloaded from the
# platform; left as a placeholder when the script runs from the source tree.
DEFAULT_BASE_URL = "{{BASE_URL}}"
ENV_KEY = "KNOWLEDGE_API_KEY"
APP_DIR_NAME = "knowledge-search"
CREDENTIALS_FILE = "credentials.json"
LIST_TYPES = {"space": 3, "doc": 0}
_PLACEHOLDER_KEYS = {"<key>", "<api-key>", "<api_key>", "{{key}}", "$" + ENV_KEY, "${" + ENV_KEY + "}"}


class CredentialError(Exception):
    """A credentials problem the agent must act on; the message says how."""


# ── configuration helpers ────────────────────────────────────────────────────


def _default_base_url() -> str:
    # The renderer blindly replaces the placeholder everywhere in this file, so
    # the "still a placeholder?" test must not spell it out a second time.
    return "" if DEFAULT_BASE_URL.startswith("{{") else DEFAULT_BASE_URL


def _normalize_base_url(raw: str) -> str:
    parts = urlsplit((raw or "").strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("--base-url must be an absolute HTTP(S) URL")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _credentials_path() -> str:
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        root = xdg if os.path.isabs(xdg) else os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, APP_DIR_NAME, CREDENTIALS_FILE)


def _mask(key: str) -> str:
    head = key[:7] if key.startswith("bs-") and key.count("-") >= 2 else ""
    return f"{head}********{key[-4:]}"


def _read_store(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            store = json.load(handle)
    except FileNotFoundError:
        return {"version": 1, "profiles": {}}
    except (OSError, ValueError) as exc:
        raise CredentialError(
            f"credentials file {path} is unreadable or not valid JSON ({exc}). "
            "Fix or delete it, then run --configure again."
        )
    if not isinstance(store, dict) or not isinstance(store.get("profiles"), dict):
        raise CredentialError(
            f"credentials file {path} has an unexpected layout. Delete it, then run --configure again."
        )
    return store


def _write_store(path: str, store: dict) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    if os.name != "nt":
        os.chmod(directory, 0o700)
    # mkstemp gives an O_EXCL 0600 file in the same directory; os.replace then
    # swaps it in atomically and replaces (never follows) a planted symlink.
    fd, temp_path = tempfile.mkstemp(prefix=".credentials-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        for attempt in range(3):
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:  # antivirus / indexer holding the file on Windows
                if attempt == 2:
                    raise
                time.sleep(0.2)
        if os.name != "nt":
            os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _resolve_key(base_url: str) -> tuple[str, str]:
    """Return (key, human-readable source). Raises CredentialError with the fix."""
    env_key = os.environ.get(ENV_KEY, "").strip()
    if env_key:
        return env_key, f"environment variable {ENV_KEY}"
    path = _credentials_path()
    store = _read_store(path)
    profile = store["profiles"].get(base_url) or {}
    key = str(profile.get("api_key") or "").strip()
    if key:
        return key, f"credentials file {path}"
    lines = [
        f"No API key for {base_url}.",
        "Save the user's personal access token once (it then works in every new session):",
        "  python3 scripts/search.py --configure --api-key <key>",
        f"It is stored in {path}, readable only by the current user.",
        f"Alternatively set {ENV_KEY} for this process only.",
    ]
    others = sorted(name for name in store["profiles"] if name != base_url)
    if others:
        lines.append("Other platforms already saved in that file: " + ", ".join(others))
        lines.append("Pass --base-url <one of them> if the user means that platform.")
    raise CredentialError("\n".join(lines))


# ── HTTP ─────────────────────────────────────────────────────────────────────


def _call(url: str, token: str, body: bytes | None = None, *, source: str = "") -> int:
    request = Request(
        url,
        data=body,
        method="POST" if body is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            print(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Surface the API's business error body: its status_code (e.g. 26044
        # data-scope restricted, 26040 capability off) tells the agent which
        # action to take — see references/api.md.
        detail = exc.read().decode("utf-8", "replace")
        print(f"knowledge search failed: HTTP {exc.code}", file=sys.stderr)
        if detail:
            print(detail, file=sys.stderr)
        if exc.code == 401 and source:
            print(_unauthorized_hint(source), file=sys.stderr)
        return 1
    except (URLError, OSError) as exc:
        print(f"knowledge search failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _unauthorized_hint(source: str) -> str:
    if source.startswith("environment variable"):
        return (
            f"The rejected key came from the {source}, which takes precedence over the "
            f"credentials file. Unset {ENV_KEY} if it is stale, or ask the user for a fresh key."
        )
    return (
        f"The rejected key came from the {source}. Ask the user to generate a fresh key on the "
        "platform and run: python3 scripts/search.py --configure --api-key <key>"
    )


# ── --configure ──────────────────────────────────────────────────────────────


def _key_for_configure(explicit: str | None) -> str:
    candidate, origin = "", ""
    if explicit is not None:
        candidate, origin = explicit.strip(), "--api-key"
    else:
        try:
            piped = sys.stdin is not None and not sys.stdin.isatty()
        except ValueError:  # stdin closed
            piped = False
        if piped:
            candidate, origin = (sys.stdin.readline() or "").strip(), "stdin"
        if not candidate:
            candidate, origin = os.environ.get(ENV_KEY, "").strip(), f"environment variable {ENV_KEY}"
    if not candidate:
        raise CredentialError(
            "No key given. Run: python3 scripts/search.py --configure --api-key <key> (or pipe the key on stdin)."
        )
    if candidate in _PLACEHOLDER_KEYS or any(ch.isspace() for ch in candidate) or len(candidate) < 8:
        raise CredentialError(
            f"The value from {origin} does not look like a real key (a placeholder, whitespace "
            "or too short). Paste the key exactly as shown on the platform."
        )
    return candidate


def _verify_key(base_url: str, key: str) -> tuple[str, str, str]:
    """Probe the list endpoint. Returns (decision, reason, response body).

    decision: "ok" (save), "unverified" (save, warn) or "reject" (do not save).
    A once-only key must not be lost to a transient outage, so only proof that
    the key or the address is wrong blocks saving.
    """
    request = Request(
        f"{base_url}/api/v2/filelib/?page_size=1",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code == 401:
            return (
                "reject",
                "the platform rejected this key (HTTP 401): malformed, revoked, expired or holder disabled",
                detail,
            )
        if exc.code in (404, 405):
            return (
                "reject",
                f"{base_url} has no knowledge API at this address (HTTP {exc.code}); check --base-url",
                detail,
            )
        if exc.code == 403:
            return "ok", "the key is valid; the platform answered with a business restriction (see body)", detail
        return "unverified", f"HTTP {exc.code}", detail
    except (URLError, OSError) as exc:
        return "unverified", str(exc), ""
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict) or "status_code" not in parsed:
        return "reject", f"{base_url} answered, but not with this platform's API (a web page?); check --base-url", ""
    return "ok", "verified", raw


def _configure(base_url: str, explicit_key: str | None) -> int:
    key = _key_for_configure(explicit_key)
    path = _credentials_path()
    store = _read_store(path)  # a corrupt file is refused here, never overwritten
    decision, reason, body = _verify_key(base_url, key)
    if decision == "reject":
        print(f"Key not saved: {reason}", file=sys.stderr)
        if body:
            print(body, file=sys.stderr)
        return 1
    store["profiles"][base_url] = {
        "base_url": base_url,
        "api_key": key,
        "key_mask": _mask(key),
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 - datetime.UTC needs 3.11
    }
    _write_store(path, store)
    print(f"Saved API key {_mask(key)} for {base_url} to {path}")
    if decision == "unverified":
        print(
            f"Warning: saved but not verified ({reason}). Run: python3 scripts/search.py --list-knowledge-bases space",
            file=sys.stderr,
        )
    else:
        print(reason)
        if body and decision == "ok" and reason != "verified":
            print(body)
    env_key = os.environ.get(ENV_KEY, "").strip()
    if env_key and env_key != key:
        print(
            f"Warning: {ENV_KEY} is set in this process ({_mask(env_key)}) and takes precedence "
            "over the saved key; unset it if it is stale.",
            file=sys.stderr,
        )
    return 0


# ── entry point ──────────────────────────────────────────────────────────────


def _arguments() -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(
        description="Search the platform's knowledge bases with the user's personal access token.",
        epilog=(
            f"Key lookup: {ENV_KEY} environment variable, then the credentials file written by "
            "--configure (~/.config/knowledge-search/credentials.json; %APPDATA%\\knowledge-search on Windows)."
        ),
    )
    parser.add_argument("--base-url", help="platform address; defaults to the address baked into this pack")
    parser.add_argument("--configure", action="store_true", help="save the key for --base-url, then exit")
    parser.add_argument("--api-key", help="the key to save with --configure (or pipe it on stdin)")
    parser.add_argument(
        "--list-knowledge-bases",
        choices=sorted(LIST_TYPES),
        help="List knowledge spaces or document libraries the token can see, then exit.",
    )
    parser.add_argument("--cursor", help="next_cursor from a previous listing page.")
    parser.add_argument("--query")
    parser.add_argument("--knowledge-base-id", action="append", type=int)
    parser.add_argument("--top-k", type=int, default=10)
    args, unknown = parser.parse_known_args()
    if unknown:
        # Do not echo unknown tokens: a mistyped --api-key flag would leak the key.
        flags = ", ".join(token for token in unknown if token.startswith("-")) or "(values hidden)"
        print(f"unrecognised arguments: {flags}. See --help.", file=sys.stderr)
        return None
    return args


def main() -> int:
    args = _arguments()
    if args is None:
        return 2
    raw_base = args.base_url or _default_base_url()
    if not raw_base:
        print("--base-url is required: this copy of the script has no platform address baked in", file=sys.stderr)
        return 2
    try:
        base = _normalize_base_url(raw_base)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    try:
        if args.configure:
            return _configure(base, args.api_key)
        token, source = _resolve_key(base)
    except CredentialError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.list_knowledge_bases:
        params = {"type": LIST_TYPES[args.list_knowledge_bases], "page_size": 50}
        if args.cursor:
            params["cursor"] = args.cursor
        return _call(f"{base}/api/v2/filelib/?{urlencode(params)}", token, source=source)

    if not args.query or not args.knowledge_base_id:
        print(
            "--query and --knowledge-base-id are required (or use --list-knowledge-bases / --configure)",
            file=sys.stderr,
        )
        return 2
    body = json.dumps(
        {
            "query": args.query,
            "knowledge_base_ids": args.knowledge_base_id,
            "top_k": args.top_k,
        }
    ).encode("utf-8")
    return _call(f"{base}/api/v2/filelib/retrieve", token, body, source=source)


if __name__ == "__main__":
    raise SystemExit(main())
