from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import httpx

from bisheng.common.errcode.automotive_sheet_intro_sync import AutomotiveSheetIntroUpstreamError

AUTOMOTIVE_SHEET_INTRO_MAX_PDF_BYTES = 50 * 1024 * 1024
_PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True)
class AutomotiveSheetIntroFetchedPdf:
    """一次成功的上游 PDF 拉取结果."""

    content: bytes
    upstream_ip: str
    succeeded_at: datetime


def _validated_pdf_body(response: httpx.Response) -> bytes:
    """确认上游响应是未超限的 PDF.

    Args:
        response: 上游 HTTP 响应.

    Returns:
        PDF 字节.

    Raises:
        AutomotiveSheetIntroUpstreamError: 状态, 类型, 正文或文件头不符合 PDF.
    """
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


def _upstream_peer_ip(response: httpx.Response) -> str:
    """读取本次响应所在连接的对端 IP.

    Args:
        response: 已完成的上游 HTTP 响应.

    Returns:
        对端 IP 字符串.

    Raises:
        AutomotiveSheetIntroUpstreamError: 响应里没有可读取的连接地址.
    """
    extensions = getattr(response, "extensions", None) or {}
    stream = extensions.get("network_stream") if isinstance(extensions, dict) else None
    getter = getattr(stream, "get_extra_info", None)
    addr = getter("server_addr") if callable(getter) else None
    host = addr[0] if isinstance(addr, tuple) and addr else None
    if isinstance(host, str) and host.strip():
        return host.strip()
    raise AutomotiveSheetIntroUpstreamError(msg="upstream peer address is unavailable")


class AutomotiveSheetIntroSyncClient:
    async def fetch_pdf(
        self,
        *,
        api_url: str,
        method: Literal["GET", "POST"],
        timeout_seconds: int,
        api_ssl_verify: bool = True,
    ) -> AutomotiveSheetIntroFetchedPdf:
        """请求上游地址并确认返回的是 PDF.

        Args:
            api_url: 上游地址.
            method: GET 或 POST.
            timeout_seconds: 超时秒数.
            api_ssl_verify: 是否校验 HTTPS 证书.

        Returns:
            PDF 内容, 上游连接 IP, 以及校验通过的时间.

        Raises:
            AutomotiveSheetIntroUpstreamError: 超时, 非成功状态, 非 PDF, 或读不到上游 IP.
        """
        timeout = httpx.Timeout(max(float(timeout_seconds), 1.0))
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                verify=api_ssl_verify,
            ) as client:
                response = await client.request(method, api_url)
                body = _validated_pdf_body(response)
                # 客户端关闭前读取对端地址, 关闭后连接信息可能已经丢掉.
                upstream_ip = _upstream_peer_ip(response)
        except httpx.TimeoutException as exc:
            raise AutomotiveSheetIntroUpstreamError(msg="upstream PDF request timed out") from exc
        except httpx.HTTPError as exc:
            raise AutomotiveSheetIntroUpstreamError(msg="upstream PDF request failed") from exc

        return AutomotiveSheetIntroFetchedPdf(
            content=body,
            upstream_ip=upstream_ip,
            succeeded_at=datetime.now().replace(microsecond=0),
        )
