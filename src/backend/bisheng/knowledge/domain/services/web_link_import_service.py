import asyncio
import hashlib
import ipaddress
import socket
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from bisheng.common.errcode.knowledge import KnowledgeWebLinkImportError


@dataclass
class WebLinkImportResult:
    title: str
    markdown: str
    final_url: str
    content_hash: str
    content_length: int


class KnowledgeWebLinkImportService:
    MAX_REDIRECTS = 5
    MAX_CONTENT_BYTES = 10 * 1024 * 1024
    USER_AGENT = "BiSheng-Knowledge-WebImporter/1.0"
    BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}

    @classmethod
    async def fetch(cls, url: str) -> WebLinkImportResult:
        current_url = cls._normalize_url(url)
        content = b""
        content_type = ""
        response_url = current_url

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=False) as client:
            for _ in range(cls.MAX_REDIRECTS + 1):
                await cls._validate_url(current_url)
                async with client.stream(
                    "GET",
                    current_url,
                    headers={"User-Agent": cls.USER_AGENT},
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise KnowledgeWebLinkImportError(msg="Web link redirect location is missing")
                        current_url = str(response.url.join(location))
                        continue

                    if response.status_code >= 400:
                        raise KnowledgeWebLinkImportError(
                            msg=f"Web link request failed with status {response.status_code}"
                        )

                    content_type = response.headers.get("content-type", "").lower()
                    if not cls._is_supported_content_type(content_type):
                        raise KnowledgeWebLinkImportError(msg="Web link content type is not supported")

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > cls.MAX_CONTENT_BYTES:
                            raise KnowledgeWebLinkImportError(msg="Web link content is too large")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    response_url = str(response.url)
                    break
            else:
                raise KnowledgeWebLinkImportError(msg="Web link redirects too many times")

        if not content:
            raise KnowledgeWebLinkImportError(msg="Web link content is empty")

        text = cls._decode_content(content, content_type)
        title, markdown = cls._extract_markdown(text, response_url, content_type)
        markdown_bytes = markdown.encode("utf-8")
        return WebLinkImportResult(
            title=title,
            markdown=markdown,
            final_url=response_url,
            content_hash=hashlib.sha256(markdown_bytes).hexdigest(),
            content_length=len(markdown_bytes),
        )

    @classmethod
    def _normalize_url(cls, url: str) -> str:
        normalized = (url or "").strip()
        if not normalized:
            raise KnowledgeWebLinkImportError(msg="Web link URL is empty")
        return normalized

    @classmethod
    async def _validate_url(cls, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise KnowledgeWebLinkImportError(msg="Only http/https web links are supported")
        if not parsed.hostname:
            raise KnowledgeWebLinkImportError(msg="Web link host is missing")

        hostname = parsed.hostname.rstrip(".").lower()
        if hostname in cls.BLOCKED_HOSTS:
            raise KnowledgeWebLinkImportError(msg="This web link host is not allowed")

        for ip_address in await cls._resolve_host(hostname, parsed.port):
            if cls._is_blocked_ip(ip_address):
                raise KnowledgeWebLinkImportError(msg="This web link address is not allowed")

    @classmethod
    async def _resolve_host(
        cls,
        hostname: str,
        port: int | None,
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        try:
            return [ipaddress.ip_address(hostname)]
        except ValueError:
            pass

        def resolve() -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
            try:
                infos = socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
            except socket.gaierror as exc:
                raise KnowledgeWebLinkImportError(msg="Web link host cannot be resolved") from exc
            resolved = []
            for info in infos:
                ip_value = info[4][0]
                try:
                    resolved.append(ipaddress.ip_address(ip_value))
                except ValueError:
                    continue
            return resolved

        addresses = await asyncio.to_thread(resolve)
        if not addresses:
            raise KnowledgeWebLinkImportError(msg="Web link host cannot be resolved")
        return addresses

    @staticmethod
    def _is_blocked_ip(ip_address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return (
            ip_address.is_loopback
            or ip_address.is_link_local
            or ip_address.is_multicast
            or ip_address.is_unspecified
            or ip_address.is_reserved
        )

    @staticmethod
    def _is_supported_content_type(content_type: str) -> bool:
        if not content_type:
            return True
        return any(
            allowed in content_type
            for allowed in ("text/html", "application/xhtml+xml", "text/plain")
        )

    @staticmethod
    def _decode_content(content: bytes, content_type: str) -> str:
        encoding = "utf-8"
        if "charset=" in content_type:
            encoding = content_type.rsplit("charset=", 1)[-1].split(";", 1)[0].strip() or encoding
        return content.decode(encoding, errors="replace")

    @classmethod
    def _extract_markdown(cls, content: str, source_url: str, content_type: str) -> tuple[str, str]:
        if "text/plain" in content_type:
            title = cls._title_from_url(source_url)
            body = content.strip()
        else:
            soup = BeautifulSoup(content, "html.parser")
            for tag in soup(["script", "style", "noscript", "svg", "iframe", "header", "footer", "nav", "aside"]):
                tag.decompose()
            title = cls._extract_title(soup, source_url)
            container = soup.find("article") or soup.find("main") or soup.body or soup
            body = markdownify(str(container), heading_style="ATX", bullets="-").strip()

        if not body:
            raise KnowledgeWebLinkImportError(msg="Web link body is empty after cleanup")

        imported_at = datetime.now().isoformat(timespec="seconds")
        markdown = "\n".join(
            [
                f"# {title}",
                "",
                f"- 来源链接: {source_url}",
                f"- 导入时间: {imported_at}",
                "",
                body,
                "",
            ]
        )
        return title, markdown

    @classmethod
    def _extract_title(cls, soup: BeautifulSoup, source_url: str) -> str:
        for candidate in (soup.find("h1"), soup.find("title")):
            if not candidate:
                continue
            title = candidate.get_text(" ", strip=True)
            if title:
                return title[:200]
        return cls._title_from_url(source_url)

    @staticmethod
    def _title_from_url(source_url: str) -> str:
        parsed = urlparse(source_url)
        title = parsed.path.rstrip("/").rsplit("/", 1)[-1] or parsed.hostname or "网页链接"
        return title[:200]
