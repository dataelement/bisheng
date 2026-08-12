from __future__ import annotations

from typing import Literal

import httpx

from bisheng.common.errcode.automotive_sheet_intro_sync import AutomotiveSheetIntroUpstreamError

AUTOMOTIVE_SHEET_INTRO_MAX_PDF_BYTES = 50 * 1024 * 1024
_PDF_MAGIC = b"%PDF-"


class AutomotiveSheetIntroSyncClient:
    async def fetch_pdf(
        self,
        *,
        api_url: str,
        method: Literal["GET", "POST"],
        timeout_seconds: int,
        api_ssl_verify: bool = True,
    ) -> bytes:
        timeout = httpx.Timeout(max(float(timeout_seconds), 1.0))
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                verify=api_ssl_verify,
            ) as client:
                response = await client.request(method, api_url)
        except httpx.TimeoutException as exc:
            raise AutomotiveSheetIntroUpstreamError(msg="upstream PDF request timed out") from exc
        except httpx.HTTPError as exc:
            raise AutomotiveSheetIntroUpstreamError(msg="upstream PDF request failed") from exc

        if response.status_code != 200:
            raise AutomotiveSheetIntroUpstreamError(
                msg=f"upstream PDF request returned status {response.status_code}",
            )

        content_type = str(response.headers.get("content-type") or "").lower()
        if content_type and "application/pdf" not in content_type and "application/octet-stream" not in content_type:
            raise AutomotiveSheetIntroUpstreamError(msg="upstream response is not application/pdf")

        body = response.content or b""
        if not body:
            raise AutomotiveSheetIntroUpstreamError(msg="upstream PDF body is empty")
        if len(body) > AUTOMOTIVE_SHEET_INTRO_MAX_PDF_BYTES:
            raise AutomotiveSheetIntroUpstreamError(msg="upstream PDF exceeds size limit")
        if not body.startswith(_PDF_MAGIC):
            raise AutomotiveSheetIntroUpstreamError(msg="upstream PDF magic header is invalid")
        return body
