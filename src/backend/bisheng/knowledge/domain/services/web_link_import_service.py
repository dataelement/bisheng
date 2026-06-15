import asyncio
import hashlib
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Comment
from markdownify import markdownify

from bisheng.common.errcode.knowledge import KnowledgeWebLinkImportError

logger = logging.getLogger(__name__)


@dataclass
class WebLinkImportResult:
    title: str
    markdown: str
    final_url: str
    content_hash: str
    content_length: int


@dataclass
class _RenderedContent:
    html: str
    final_url: str


@dataclass
class _MarkdownExtraction:
    title: str
    body: str
    markdown: str
    needs_rendered_fallback: bool


class KnowledgeWebLinkImportService:
    MAX_REDIRECTS = 5
    MAX_CONTENT_BYTES = 10 * 1024 * 1024
    RENDER_TIMEOUT_MS = 20_000
    MIN_MEANINGFUL_BODY_LENGTH = 80
    BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}
    PLACEHOLDER_TITLES = {"loading", "loading...", "loading…"}
    PLACEHOLDER_BODY_MARKERS = (
        "you need to enable javascript to run this app",
        "please enable javascript",
        "enable javascript to continue",
    )
    CONTENT_SELECTORS = (
        {"id": "js_content"},
        {"class": "rich_media_content"},
        {"class": "TRS_Editor"},
        {"class": "TRS_AUTOADD"},
        {"class": "article-content"},
        {"class": "article-body"},
        {"class": "article_content"},
        {"class": "news_content"},
        {"class": "content_area"},
        {"class": "wp_articlecontent"},
        {"id": "UCAP-CONTENT"},
        {"id": "zoom"},
        {"id": "article_content"},
        {"id": "content"},
        {"class": "content"},
        {"role": "main"},
        {"tag": "article"},
        {"tag": "main"},
    )
    TITLE_SELECTORS = (
        {"id": "activity-name"},
        {"class": "article-title"},
        {"class": "news_title"},
        {"id": "article_title"},
        {"tag": "h1"},
    )
    SKIP_TAGS = (
        "script",
        "style",
        "link",
        "noscript",
        "svg",
        "iframe",
        "canvas",
        "template",
        "form",
        "input",
        "select",
        "textarea",
        "button",
        "nav",
        "footer",
        "aside",
    )
    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    @classmethod
    async def fetch(cls, url: str) -> WebLinkImportResult:
        current_url = cls._normalize_url(url)
        content = b""
        content_type = ""
        response_url = current_url

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=False) as client:
                for _ in range(cls.MAX_REDIRECTS + 1):
                    await cls._validate_url(current_url)
                    async with client.stream("GET", current_url, headers=cls.REQUEST_HEADERS) as response:
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
        except KnowledgeWebLinkImportError:
            raise
        except httpx.HTTPError as exc:
            raise KnowledgeWebLinkImportError(msg=f"Web link request failed: {exc}") from exc

        if not content:
            raise KnowledgeWebLinkImportError(msg="Web link content is empty")

        text = cls._decode_content(content, content_type)
        extraction = cls._extract_markdown(text, response_url, content_type)
        if extraction.needs_rendered_fallback and "text/plain" not in content_type:
            rendered_content = await cls._fetch_rendered_content(response_url)
            if rendered_content:
                rendered_extraction = cls._extract_markdown(
                    rendered_content.html,
                    rendered_content.final_url,
                    "text/html",
                )
                if cls._should_use_rendered_extraction(extraction, rendered_extraction):
                    response_url = rendered_content.final_url
                    extraction = rendered_extraction

        title = extraction.title
        markdown = extraction.markdown
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
    async def _fetch_rendered_content(cls, source_url: str) -> _RenderedContent | None:
        try:
            await cls._validate_url(source_url)
            from playwright.async_api import async_playwright

            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(
                        user_agent=cls.REQUEST_HEADERS["User-Agent"],
                        extra_http_headers={
                            "Accept-Language": cls.REQUEST_HEADERS["Accept-Language"],
                        },
                        ignore_https_errors=True,
                    )
                    page = await context.new_page()
                    response = await page.goto(
                        source_url,
                        wait_until="domcontentloaded",
                        timeout=cls.RENDER_TIMEOUT_MS,
                    )
                    final_url = page.url or source_url
                    await cls._validate_url(final_url)
                    if response and response.status >= 400:
                        return None
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5_000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(1_000)
                    html = await page.content()
                    await context.close()
                    return _RenderedContent(html=html, final_url=final_url)
                finally:
                    await browser.close()
        except Exception as exc:
            logger.info("Rendered web link fallback failed for %s: %s", source_url, exc)
            return None

    @classmethod
    def _extract_markdown(cls, content: str, source_url: str, content_type: str) -> _MarkdownExtraction:
        if "text/plain" in content_type:
            title = cls._title_from_url(source_url)
            body = content.strip()
        else:
            soup = cls._make_soup(content)
            title = cls._extract_title(soup, source_url)
            fallback_body = cls._extract_fallback_body(cls._make_soup(content))
            cls._clean_soup(soup)
            container = cls._select_content_container(soup)
            body = cls._html_to_markdown(str(container)) if container else ""
            if not body:
                body = fallback_body

        body = cls._normalize_markdown_body(body)
        is_placeholder = cls._is_placeholder_body(body)
        needs_rendered_fallback = is_placeholder or cls._is_low_quality_body(body)
        if is_placeholder:
            body = ""
        if not body:
            body = "该网页可能为动态渲染页面，未能提取到静态正文内容。"

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
        return _MarkdownExtraction(
            title=title,
            body=body,
            markdown=markdown,
            needs_rendered_fallback=needs_rendered_fallback,
        )

    @classmethod
    def _make_soup(cls, content: str) -> BeautifulSoup:
        try:
            return BeautifulSoup(content, "lxml")
        except Exception:
            return BeautifulSoup(content, "html.parser")

    @classmethod
    def _clean_soup(cls, soup: BeautifulSoup) -> None:
        for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
            comment.extract()

        cls._remove_hidden_elements(soup)
        for tag_name in cls.SKIP_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        for tag in soup.find_all(True):
            if tag.name in {"html", "body"}:
                continue
            safe_attrs = {"href", "src", "alt", "title", "colspan", "rowspan", "scope", "headers"}
            for attr in list(tag.attrs.keys()):
                if attr not in safe_attrs:
                    del tag[attr]

    @classmethod
    def _remove_hidden_elements(cls, soup: BeautifulSoup) -> None:
        removable = []
        for tag in soup.find_all(True):
            if tag.name in {"html", "body"}:
                continue
            attrs = tag.attrs or {}
            style = str(attrs.get("style", ""))
            normalized_style = re.sub(r"\s+", "", style).lower()
            classes = attrs.get("class") or []
            class_names = classes if isinstance(classes, list) else [classes]
            is_known_content_root = attrs.get("id") == "js_content" or "rich_media_content" in class_names
            if is_known_content_root:
                cleaned_style = re.sub(r"visibility\s*:\s*hidden\s*;?", "", style, flags=re.I)
                cleaned_style = re.sub(r"opacity\s*:\s*0\s*;?", "", cleaned_style, flags=re.I)
                cleaned_style = re.sub(r"display\s*:\s*none\s*;?", "", cleaned_style, flags=re.I)
                if cleaned_style.strip():
                    tag["style"] = cleaned_style.strip()
                elif "style" in tag.attrs:
                    del tag["style"]
                continue
            if (
                attrs.get("hidden") is not None
                or str(attrs.get("aria-hidden", "")).lower() == "true"
                or "display:none" in normalized_style
                or "visibility:hidden" in normalized_style
                or "opacity:0" in normalized_style
            ):
                removable.append(tag)
        for tag in removable:
            tag.decompose()

    @classmethod
    def _select_content_container(cls, soup: BeautifulSoup):
        for selector in cls.CONTENT_SELECTORS:
            element = cls._find_element(soup, selector)
            if element and cls._text_length(element) >= 50:
                return element

        best = None
        best_score = 0
        for element in soup.find_all(["article", "main", "section", "div"]):
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            direct_children = len(element.find_all(["article", "main", "section", "div"], recursive=False))
            if direct_children > 8:
                continue
            link_text_length = sum(len(link.get_text(" ", strip=True)) for link in element.find_all("a"))
            score = len(text) - int(link_text_length * 0.6)
            if score > best_score:
                best = element
                best_score = score
        if best and best_score >= 50:
            return best
        return soup.body or soup

    @classmethod
    def _find_element(cls, soup: BeautifulSoup, selector: dict):
        if "tag" in selector:
            return soup.find(selector["tag"])
        if "class" in selector:
            return soup.find(class_=selector["class"])
        if "id" in selector:
            return soup.find(id=selector["id"])
        if "role" in selector:
            return soup.find(attrs={"role": selector["role"]})
        return None

    @staticmethod
    def _text_length(element) -> int:
        return len(element.get_text(" ", strip=True))

    @classmethod
    def _html_to_markdown(cls, html: str) -> str:
        markdown = markdownify(
            html,
            heading_style="ATX",
            bullets="-",
            strip=["style", "script", "link", "meta", "head"],
        ).strip()
        markdown = re.sub(r"</?[a-zA-Z][^>]*>", "", markdown)
        markdown = cls._remove_markdown_noise(markdown)
        return markdown.strip()

    @staticmethod
    def _remove_markdown_noise(markdown: str) -> str:
        cleaned_lines = []
        for line in markdown.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            if not stripped:
                cleaned_lines.append("")
                continue
            if lower.startswith(("<link ", "<style", "</style", "<script", "</script")):
                continue
            if "rel=\"stylesheet\"" in lower or "rel='stylesheet'" in lower:
                continue
            if re.search(r"[.#][\w\\-]+\s*\{[^}]{0,240}\}", stripped) and not re.search(r"[\u4e00-\u9fff]", stripped):
                continue
            cleaned_lines.append(stripped)
        return "\n".join(cleaned_lines)

    @staticmethod
    def _extract_fallback_body(soup: BeautifulSoup) -> str:
        candidates = []
        for meta_name in ("description", "keywords"):
            meta = soup.find("meta", attrs={"name": meta_name})
            content = meta.get("content", "").strip() if meta else ""
            if content and not KnowledgeWebLinkImportService._is_placeholder_body(content):
                candidates.append(content)
        og_description = soup.find("meta", attrs={"property": "og:description"})
        og_content = og_description.get("content", "").strip() if og_description else ""
        if og_content and not KnowledgeWebLinkImportService._is_placeholder_body(og_content):
            candidates.append(og_content)
        KnowledgeWebLinkImportService._clean_soup(soup)
        text = soup.get_text("\n", strip=True)
        if text and not KnowledgeWebLinkImportService._is_placeholder_body(text):
            candidates.append(text)
        return "\n\n".join(dict.fromkeys(candidates))

    @staticmethod
    def _normalize_markdown_body(body: str, max_line_length: int = 900) -> str:
        normalized_lines = []
        for line in body.splitlines():
            stripped = line.strip()
            if len(stripped) <= max_line_length:
                normalized_lines.append(stripped)
                continue
            normalized_lines.extend(
                stripped[index: index + max_line_length]
                for index in range(0, len(stripped), max_line_length)
            )
        normalized = "\n".join(normalized_lines)
        return re.sub(r"\n{3,}", "\n\n", normalized).strip()

    @classmethod
    def _is_placeholder_body(cls, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", (text or "")).strip().lower()
        if not normalized:
            return True
        if normalized.strip(".… ") == "loading":
            return True
        return any(marker in normalized for marker in cls.PLACEHOLDER_BODY_MARKERS)

    @classmethod
    def _is_low_quality_body(cls, body: str) -> bool:
        normalized = re.sub(r"\s+", " ", (body or "")).strip()
        if not normalized:
            return True

        lower = normalized.lower()
        artifact_markers = (
            "<style",
            "</style",
            "<script",
            "</script",
            "<link",
            "rel=\"stylesheet\"",
            "rel='stylesheet'",
            "display:none",
            "visibility:hidden",
            "data-for=\"result\"",
        )
        if any(marker in lower for marker in artifact_markers):
            return True

        css_rule_count = len(re.findall(r"[.#][\w\\-]+\s*\{[^}]{0,300}\}", normalized))
        if css_rule_count >= 2:
            return True

        meaningful = re.sub(r"https?://\S+", "", normalized)
        meaningful = re.sub(r"!\[[^\]]*]\([^)]+\)|\[[^\]]+]\([^)]+\)", "", meaningful)
        meaningful = re.sub(r"[#*_`>\-\s|:：,，.。/\\{}()[\]\"'=;；]+", "", meaningful)
        if len(meaningful) < cls.MIN_MEANINGFUL_BODY_LENGTH:
            return True

        return False

    @classmethod
    def _should_use_rendered_extraction(
        cls,
        static_extraction: _MarkdownExtraction,
        rendered_extraction: _MarkdownExtraction,
    ) -> bool:
        if static_extraction.needs_rendered_fallback and not rendered_extraction.needs_rendered_fallback:
            return True
        if cls._is_placeholder_body(static_extraction.body) and rendered_extraction.body:
            return True
        return len(rendered_extraction.body) > len(static_extraction.body) * 1.5

    @classmethod
    def _extract_title(cls, soup: BeautifulSoup, source_url: str) -> str:
        for selector in cls.TITLE_SELECTORS:
            candidate = cls._find_element(soup, selector)
            if not candidate:
                continue
            title = candidate.get_text(" ", strip=True)
            if title and title.strip().lower() not in cls.PLACEHOLDER_TITLES:
                return title[:200]
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(" ", strip=True)
            if title and title.strip().lower() not in cls.PLACEHOLDER_TITLES:
                return title[:200]
        return cls._title_from_url(source_url)

    @staticmethod
    def _title_from_url(source_url: str) -> str:
        parsed = urlparse(source_url)
        title = parsed.path.rstrip("/").rsplit("/", 1)[-1] or parsed.netloc or parsed.hostname or "网页链接"
        return title[:200]
