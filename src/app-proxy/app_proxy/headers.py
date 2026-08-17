"""What we take off the request, and what we put on it (AC-31 / AC-32).

The strip is a **normalised prefix match**, never a name list. Normalise
(``lower()`` + ``_`` → ``-``), then drop anything under ``x-bisheng-``. This is
the CVE-2025-64484 lesson: oauth2-proxy stripped the exact hyphenated spellings
it knew about, and ``X_Forwarded_User`` walked straight past it because
WSGI-family frameworks fold underscores and hyphens onto one key. A list also
rots — every header added later is a hole until someone remembers the list.

The injection is the mirror image: the backend hands us **material**, and we
map it onto the canonical ten. Anything in that material outside our namespace
is dropped too, so a compromised or simply buggy internal endpoint cannot make
us set ``Authorization`` on a request into a hosted app.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from urllib.parse import quote

from app_proxy.config import ACCESS_TOKEN_COOKIE, DEFAULT_ENTRY_PREFIX

#: Normalised prefix owned by the platform. Everything under it is ours to
#: write and no one else's to send.
PLATFORM_HEADER_PREFIX = "x-bisheng-"

#: The ten of design §4.2 ③, in the order they go on the wire. F053's
#: ``bisheng dev`` mini-proxy injects the same set (INV-32).
INJECTED_HEADER_NAMES: tuple[str, ...] = (
    "X-BiSheng-User-Id",
    "X-BiSheng-User-Name",
    "X-BiSheng-Tenant-Id",
    "X-BiSheng-Dept-Id",
    "X-BiSheng-Dept-Name",
    "X-BiSheng-Dept-Path",
    "X-BiSheng-Subject-Kind",
    "X-BiSheng-App-Id",
    "X-BiSheng-Access-Token",
    "X-BiSheng-Request-Id",
)

_CANONICAL_BY_NORMALISED = {name.lower(): name for name in INJECTED_HEADER_NAMES}

#: Dropped outright before forwarding.
#:
#: * ``x-forwarded-*`` / ``forwarded`` — we rewrite these (D5.2). Passing the
#:   client's value through lets a visitor make the app generate links and
#:   redirects pointing at a host of their choosing.
#: * hop-by-hop — RFC 9110 §7.6.1. Forwarding ``Transfer-Encoding`` on a
#:   request we re-frame ourselves is a request-smuggling primitive.
#: * ``host`` / ``content-length`` — httpx recomputes both for the upstream
#:   request; forwarding the originals produces a mismatch.
DROPPED_HEADERS = frozenset(
    {
        "x-forwarded-prefix",
        "x-forwarded-proto",
        "x-forwarded-host",
        "x-forwarded-port",
        "forwarded",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)

_CONTROL_CHARS = frozenset(chr(i) for i in range(0x20)) | {chr(0x7F)}


def normalize_header_name(name: str) -> str:
    """``X_BiSheng_User_Id`` and ``X-BiSheng-User-Id`` are the same header."""
    return name.strip().lower().replace("_", "-")


def is_platform_header(name: str) -> bool:
    return normalize_header_name(name).startswith(PLATFORM_HEADER_PREFIX)


def encode_header_value(value: str) -> str:
    """Make a value latin-1 safe without ever double-encoding it (坑 9).

    ASCII in, ASCII out — so material the backend already percent-encoded
    survives unchanged (its ``%`` would otherwise become ``%25`` and the user
    would read ``%E5%BC%A0`` as their own name inside the app). Control
    characters are encoded even when ASCII: a raw CR/LF in a header value is a
    response-splitting primitive.
    """
    text = str(value)
    if text.isascii() and not (_CONTROL_CHARS & set(text)):
        return text
    return quote(text, safe="/")


def _filter_cookie(value: str, session_cookie_name: str) -> str:
    kept = []
    for chunk in value.split(";"):
        pair = chunk.strip()
        if not pair:
            continue
        name = pair.split("=", 1)[0].strip()
        if name == session_cookie_name:
            continue
        kept.append(pair)
    return "; ".join(kept)


def strip_platform_headers(
    headers: Iterable[tuple[str, str]],
    *,
    session_cookie_name: str = ACCESS_TOKEN_COOKIE,
    strip_session_cookie: bool = True,
) -> list[tuple[str, str]]:
    """Everything the client sent, minus what it must not be able to say.

    ``strip_session_cookie`` removes **only** the platform session cookie from
    the ``Cookie`` header, leaving the hosted app's own cookies alone. The
    browser sends that cookie to ``/apps/*`` for free (host-only, ``path=/``,
    K7) — which is what makes AC-26's "no second login" work, and equally what
    would otherwise hand every hosted container a credential strictly more
    powerful than the scoped 900s OBO token we mint for it on purpose (AC-34).
    It is a flag rather than a constant so a deployment can put it back if a
    real app turns out to need it.
    """
    kept: list[tuple[str, str]] = []
    for name, value in headers:
        normalised = normalize_header_name(name)
        if normalised.startswith(PLATFORM_HEADER_PREFIX):
            continue
        if normalised in DROPPED_HEADERS:
            continue
        if normalised == "cookie" and strip_session_cookie:
            filtered = _filter_cookie(value, session_cookie_name)
            if not filtered:
                continue
            kept.append((name, filtered))
            continue
        kept.append((name, value))
    return kept


def build_injected_headers(
    material: Mapping[str, str] | None,
    *,
    slug: str,
    request_id: str,
    obo_token: str | None = None,
    proto: str = "http",
    host: str = "",
    app_id: str | None = None,
    entry_prefix: str = DEFAULT_ENTRY_PREFIX,
) -> list[tuple[str, str]]:
    """The ten identity headers plus the three forwarding headers we own.

    Absent material is **omitted**, not emitted empty: an app doing
    ``if request.headers.get("X-BiSheng-Dept-Id"):`` must be able to tell "no
    department" from "empty department".
    """
    values: dict[str, str] = {}
    for raw_name, raw_value in (material or {}).items():
        canonical = _CANONICAL_BY_NORMALISED.get(normalize_header_name(raw_name))
        if canonical is None:
            # Material outside our namespace is data the backend sent us, not a
            # licence to set arbitrary headers on the upstream request.
            continue
        if raw_value is None or str(raw_value) == "":
            continue
        values[canonical] = str(raw_value)

    if app_id:
        values["X-BiSheng-App-Id"] = app_id
    if obo_token:
        values["X-BiSheng-Access-Token"] = obo_token
    # Ours, always: correlation across app-proxy → app → platform logs only
    # works if exactly one hop mints the id (D14 / §7 log contract).
    values["X-BiSheng-Request-Id"] = request_id

    injected = [(name, encode_header_value(values[name])) for name in INJECTED_HEADER_NAMES if name in values]

    injected.append(("X-Forwarded-Prefix", f"{entry_prefix.rstrip('/')}/{slug}"))
    if proto:
        injected.append(("X-Forwarded-Proto", proto))
    if host:
        injected.append(("X-Forwarded-Host", host))
    return injected


def build_upstream_headers(
    inbound: Iterable[tuple[str, str]],
    material: Mapping[str, str] | None,
    *,
    slug: str,
    request_id: str,
    obo_token: str | None = None,
    proto: str = "http",
    host: str = "",
    app_id: str | None = None,
    entry_prefix: str = DEFAULT_ENTRY_PREFIX,
    strip_session_cookie: bool = True,
) -> list[tuple[str, str]]:
    """Strip then inject, in that order — the only order that is safe.

    Injecting first and stripping after would delete our own headers; the WS
    upgrade path (Wave 4) calls this same function for the same reason.
    """
    return strip_platform_headers(inbound, strip_session_cookie=strip_session_cookie) + build_injected_headers(
        material,
        slug=slug,
        request_id=request_id,
        obo_token=obo_token,
        proto=proto,
        host=host,
        app_id=app_id,
        entry_prefix=entry_prefix,
    )
