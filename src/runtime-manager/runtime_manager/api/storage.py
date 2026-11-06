"""Attachment storage RPC — the app-facing side of the handle (AC-45, T084).

``/v1/apps/{app_id}/storage/**`` is the one router in this process with **two**
callers and therefore two credentials:

* **The hosted app itself**, with the per-app bearer token minted at deploy
  (``BISHENG_APP_STORAGE_TOKEN``). It is the credential F057's SDK sends, and
  it is bound to *this* ``app_id``: the token of app A on the URL of app B is a
  401, not a scoping decision. Compared in constant time against the desired
  state record — which is also why a destroyed app's token stops working the
  moment its record is gone.
* **The platform backend** (F052 MCP tools, later a data tab), with the same
  HMAC signature every other ``/v1`` route takes.

The bearer path is tried first because it is cheap to recognise; anything
without a bearer header falls through to HMAC, so a backend caller that also
happens to send ``Authorization`` for some unrelated reason still verifies.

Bodies are raw bytes, not multipart: the signature covers the exact bytes and
the SDK has nothing to encode. The size cap is checked on ``Content-Length``
*before* the body is read, then on the bytes as they arrive — the read stops
at the first chunk that takes the total over the cap — and once more on the
assembled body. A client that lies about its length, or sends chunked with no
length at all, therefore never gets more than ``cap`` bytes into memory here.
"""

from __future__ import annotations

import hmac
from dataclasses import asdict

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse

from runtime_manager.auth import verify_hmac
from runtime_manager.config import get_config
from runtime_manager.desired_state import get_store
from runtime_manager.errors import UnauthorizedError
from runtime_manager.storage import (
    DEFAULT_CONTENT_TYPE,
    DEFAULT_LIST_LIMIT,
    ENV_STORAGE_TOKEN,
    MAX_LIST_LIMIT,
    AppStorageService,
    ObjectMeta,
)

CALLER_APP = "app"
CALLER_PLATFORM = "platform"


def storage_token_of(record_env: dict[str, str] | None) -> str | None:
    """The token an instance was deployed with, or ``None`` (pre-storage record)."""
    return (record_env or {}).get(ENV_STORAGE_TOKEN) or None


async def verify_storage_caller(request: Request, app_id: str) -> str:
    """Bearer (the app, scoped to ``app_id``) or HMAC (the platform)."""
    header = request.headers.get("authorization", "") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer":
        token = token.strip()
        record = get_store(get_config()).get(app_id)
        expected = storage_token_of(record.env if record else None)
        # Compare as bytes: ``compare_digest`` on ``str`` raises TypeError for
        # non-ASCII input, and the header is attacker supplied — that would be
        # a 500 where a 401 is due.
        if not token or not expected or not hmac.compare_digest(expected.encode(), token.encode()):
            raise UnauthorizedError("invalid storage token for this application")
        return CALLER_APP
    await verify_hmac(request)
    return CALLER_PLATFORM


router = APIRouter(prefix="/v1/apps/{app_id}/storage", tags=["storage"], dependencies=[Depends(verify_storage_caller)])


def _service() -> AppStorageService:
    return AppStorageService(get_config())


def _as_dict(meta: ObjectMeta) -> dict:
    return asdict(meta)


@router.get("/objects")
async def list_objects(
    app_id: str,
    prefix: str = Query(""),
    cursor: str | None = Query(None),
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
) -> dict:
    """``{objects: [{key, size, content_type, etag, last_modified}], next_cursor}``."""
    page = _service().list(app_id, prefix=prefix, cursor=cursor, limit=limit)
    return {"objects": [_as_dict(m) for m in page["objects"]], "next_cursor": page["next_cursor"]}


@router.get("/meta/{key:path}")
async def object_meta(app_id: str, key: str) -> dict:
    """Metadata only; 404 when the attachment does not exist."""
    return _as_dict(_service().stat(app_id, key))


@router.put("/objects/{key:path}")
async def upload_object(app_id: str, key: str, request: Request) -> dict:
    """Raw-body upload. ``Content-Type`` is stored as the object's type."""
    service = _service()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit():
        service.check_size(int(declared))
    body = await _read_capped(request, service)
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip() or DEFAULT_CONTENT_TYPE
    return _as_dict(service.upload(app_id, key, body, content_type))


async def _read_capped(request: Request, service: AppStorageService) -> bytes:
    """Read the body, stopping at the first chunk that takes it over the cap.

    Without this a chunked upload (no ``Content-Length``) would be buffered in
    full before ``upload`` could refuse it — the cap must bound memory, not
    just what reaches the store. Under the HMAC path the body was already
    consumed by the signature check; Starlette then replays it as one chunk.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        service.check_size(total)
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/objects/{key:path}")
async def download_object(app_id: str, key: str) -> Response:
    """Streams the bytes back; ``Content-Type`` / ``Content-Length`` from the object."""
    meta, chunks = _service().download(app_id, key)
    headers = {"content-length": str(meta.size)}
    if meta.etag:
        headers["etag"] = meta.etag
    return StreamingResponse(chunks, media_type=meta.content_type or DEFAULT_CONTENT_TYPE, headers=headers)


@router.delete("/objects/{key:path}")
async def delete_object(app_id: str, key: str) -> dict:
    """404 for a missing attachment — never a silent success (F057 AC-25)."""
    _service().delete(app_id, key)
    return {}
