"""Bound live event streams by current permissions, including idle streams."""

import asyncio
import time

from app_proxy.authz import authorize, authorize_preview, extract_access_token
from app_proxy.config import get_config


async def authorized_events(response, request, verdict, *, slug, request_id):
    iterator = response.aiter_raw().__aiter__()
    pending = None
    interval = max(1.0, float(get_config().ws_reauthorize_interval_seconds))
    deadline = time.monotonic() + interval
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(iterator))
            done, _ = await asyncio.wait({pending}, timeout=max(0, deadline - time.monotonic()))
            if time.monotonic() >= deadline:
                token = extract_access_token(request)
                if verdict.preview_session:
                    current = await authorize_preview(session=verdict.preview_session, access_token=token, request_id=request_id)
                else:
                    current = await authorize(slug=slug, access_token=token, request_id=request_id)
                if not current.allowed:
                    break
                deadline = time.monotonic() + interval
            if pending in done:
                try:
                    chunk = pending.result()
                except StopAsyncIteration:
                    break
                pending = None
                yield chunk
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await response.aclose()
