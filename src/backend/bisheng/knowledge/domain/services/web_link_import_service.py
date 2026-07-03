import asyncio
import hashlib
import html as html_lib
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Comment
from markdownify import markdownify

from bisheng.common.errcode.knowledge import KnowledgeWebLinkImportError

logger = logging.getLogger(__name__)

WEB_LINK_LOGIN_ENTRY_MARKDOWN = (
    "该网页可能是登录、注册或权限入口页面，未能提取到适合入库的正文内容。"
)
WEB_LINK_NAVIGATION_PORTAL_MARKDOWN = (
    "该网页主要是以导航或门户入口页面，正文信息不足，不建议作为知识库网页正文导入。"
)
WEB_LINK_DYNAMIC_RENDER_MARKDOWN = "该网页可能为动态渲染页面，未能提取到静态正文内容。"

# Fixed low-value import bodies must not collide on content-hash dedup across URLs.
WEB_LINK_NON_DEDUP_MARKDOWN_BODIES = frozenset(
    {
        WEB_LINK_LOGIN_ENTRY_MARKDOWN,
        WEB_LINK_NAVIGATION_PORTAL_MARKDOWN,
        WEB_LINK_DYNAMIC_RENDER_MARKDOWN,
    }
)


def is_web_link_non_dedup_markdown(markdown: str) -> bool:
    return (markdown or "").strip() in WEB_LINK_NON_DEDUP_MARKDOWN_BODIES


@dataclass
class WebLinkImportResult:
    title: str
    markdown: str
    final_url: str
    content_hash: str
    content_length: int
    html_snapshot: str = ""


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
    low_value_reason: str = ""


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
    LOW_VALUE_PAGE_MARKERS = (
        "don't have an account? register",
        "do not have an account? register",
        "forgot password",
        "remember me",
        "sign in",
        "sign up",
        "login",
        "register",
        "请输入用户名",
        "请输入密码",
        "忘记密码",
        "立即登录",
        "注册账号",
    )
    DECORATIVE_IMAGE_MARKERS = (
        "logo",
        "icon",
        "avatar",
        "qrcode",
        "qr_code",
        "二维码",
        "头像",
        "图标",
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
                                msg=cls._http_status_error_message(response.status_code)
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
        html_snapshot = cls._build_readable_html_snapshot(title, extraction.body, response_url)
        markdown_bytes = markdown.encode("utf-8")
        return WebLinkImportResult(
            title=title,
            markdown=markdown,
            final_url=response_url,
            content_hash=hashlib.sha256(markdown_bytes).hexdigest(),
            content_length=len(markdown_bytes),
            html_snapshot=html_snapshot,
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
    def _http_status_error_message(status_code: int) -> str:
        if status_code == 401:
            return "Target site requires authentication"
        if status_code == 403:
            return "Target site refused server-side access"
        if status_code == 429:
            return "Target site rate limited server-side access"
        return f"Web link request failed with status {status_code}"

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
    def _build_html_snapshot(cls, content: str, source_url: str, content_type: str) -> str:
        if "text/plain" in content_type:
            title = cls._title_from_url(source_url)
            escaped_title = html_lib.escape(title)
            escaped_body = html_lib.escape(content)
            return "\n".join(
                [
                    "<!doctype html>",
                    '<html lang="zh-CN">',
                    "<head>",
                    '<meta charset="utf-8">',
                    f"<title>{escaped_title}</title>",
                    "</head>",
                    "<body>",
                    f"<pre>{escaped_body}</pre>",
                    "</body>",
                    "</html>",
                ]
            )

        soup = cls._make_soup(content)
        if not soup.find("base"):
            head = soup.head
            if head is None:
                html_tag = soup.html
                head = soup.new_tag("head")
                if html_tag:
                    html_tag.insert(0, head)
                else:
                    soup.insert(0, head)
            base_tag = soup.new_tag("base", href=source_url)
            head.insert(0, base_tag)
        if not soup.find("meta", attrs={"charset": True}):
            head = soup.head
            if head:
                meta = soup.new_tag("meta", charset="utf-8")
                head.insert(0, meta)
        return str(soup)

    @classmethod
    def _build_readable_html_snapshot(cls, title: str, body: str, source_url: str) -> str:
        escaped_title = html_lib.escape(title or cls._title_from_url(source_url))
        escaped_source = html_lib.escape(source_url)
        escaped_body = html_lib.escape(body or "")
        return "\n".join(
            [
                "<!doctype html>",
                '<html lang="zh-CN">',
                "<head>",
                '<meta charset="utf-8">',
                '<meta name="viewport" content="width=device-width, initial-scale=1">',
                f"<title>{escaped_title}</title>",
                "<style>",
                "body{margin:0;background:#f5f7fb;color:#1d2129;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}",
                "main{box-sizing:border-box;max-width:860px;margin:32px auto;padding:32px;background:#fff;box-shadow:0 2px 12px rgba(0,0,0,.06);}",
                "h1{margin:0 0 18px;font-size:28px;line-height:1.35;font-weight:700;}",
                ".source{margin:0 0 24px;color:#86909c;font-size:14px;}",
                ".source a{color:#165dff;text-decoration:none;word-break:break-all;}",
                "article{white-space:pre-wrap;font-size:16px;line-height:1.85;word-break:break-word;}",
                "</style>",
                "</head>",
                "<body>",
                "<main>",
                f"<h1>{escaped_title}</h1>",
                f'<p class="source">来源链接：<a href="{escaped_source}" target="_blank" rel="noreferrer">{escaped_source}</a></p>',
                f"<article>{escaped_body}</article>",
                "</main>",
                "</body>",
                "</html>",
            ]
        )

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
            cls._clean_soup(soup, source_url)
            container = cls._select_content_container(soup)
            body = cls._html_to_markdown(str(container)) if container else ""
            if not body:
                body = fallback_body

        body = cls._normalize_markdown_body(body)
        body = cls._strip_leading_title_heading(body, title)
        is_placeholder = cls._is_placeholder_body(body)
        low_value_reason = cls._get_low_value_reason(title, body)
        needs_rendered_fallback = is_placeholder or bool(low_value_reason) or cls._is_low_quality_body(body)
        if is_placeholder:
            body = ""
        elif low_value_reason:
            body = low_value_reason
        if not body:
            body = WEB_LINK_DYNAMIC_RENDER_MARKDOWN

        markdown = body.strip() + "\n"
        return _MarkdownExtraction(
            title=title,
            body=body,
            markdown=markdown,
            needs_rendered_fallback=needs_rendered_fallback,
            low_value_reason=low_value_reason,
        )

    @classmethod
    def _make_soup(cls, content: str) -> BeautifulSoup:
        try:
            return BeautifulSoup(content, "lxml")
        except Exception:
            return BeautifulSoup(content, "html.parser")

    @staticmethod
    def _strip_leading_title_heading(body: str, title: str) -> str:
        normalized_title = re.sub(r"\s+", " ", (title or "").strip()).strip("# ")
        if not normalized_title:
            return body
        lines = body.splitlines()
        index = 0
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            return body
        first_line = lines[index].strip()
        if not first_line.startswith("#"):
            return body
        heading_text = re.sub(r"^#+\s*", "", first_line).strip()
        heading_text = re.sub(r"\s+", " ", heading_text)
        if heading_text != normalized_title:
            return body
        remaining = lines[:index] + lines[index + 1 :]
        return "\n".join(remaining).strip()

    @classmethod
    def _clean_soup(cls, soup: BeautifulSoup, source_url: str = "") -> None:
        for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
            comment.extract()

        cls._remove_hidden_elements(soup)
        for tag_name in cls.SKIP_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        if source_url:
            cls._absolutize_links(soup, source_url)
        cls._remove_decorative_images(soup)

        for tag in soup.find_all(True):
            if tag.name in {"html", "body"}:
                continue
            safe_attrs = {"href", "src", "alt", "title", "colspan", "rowspan", "scope", "headers"}
            for attr in list(tag.attrs.keys()):
                if attr not in safe_attrs:
                    del tag[attr]

    @classmethod
    def _absolutize_links(cls, soup: BeautifulSoup, source_url: str) -> None:
        for tag in soup.find_all(["a", "img", "source"]):
            attr = "href" if tag.name == "a" else "src"
            value = (tag.get(attr) or "").strip()
            if not value:
                if tag.name == "img":
                    tag.decompose()
                continue
            if value.startswith(("data:", "mailto:", "tel:", "javascript:")):
                if tag.name == "img" and value.startswith("data:image/svg"):
                    tag.decompose()
                continue
            tag[attr] = urljoin(source_url, value)

    @classmethod
    def _remove_decorative_images(cls, soup: BeautifulSoup) -> None:
        seen_srcs = set()
        for image in list(soup.find_all("img")):
            src = (image.get("src") or "").strip()
            if not src:
                image.decompose()
                continue
            alt_title = " ".join(
                str(image.get(attr, ""))
                for attr in ("alt", "title", "class", "id")
            ).lower()
            if src in seen_srcs and any(marker in alt_title for marker in cls.DECORATIVE_IMAGE_MARKERS):
                image.decompose()
                continue
            if any(marker in alt_title for marker in cls.DECORATIVE_IMAGE_MARKERS):
                image.decompose()
                continue
            seen_srcs.add(src)

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
    def _get_low_value_reason(cls, title: str, body: str) -> str:
        visible_text = cls._visible_markdown_text(body)
        normalized = re.sub(r"\s+", " ", f"{title} {visible_text}".strip()).lower()
        if not normalized:
            return ""

        matched_markers = sum(1 for marker in cls.LOW_VALUE_PAGE_MARKERS if marker in normalized)
        if matched_markers >= 2:
            return WEB_LINK_LOGIN_ENTRY_MARKDOWN

        words_for_navigation = (
            "首页",
            "注册",
            "登录",
            "管理",
            "应用",
            "工具",
            "工作台",
            "don't have an account",
            "register",
        )
        nav_hits = sum(1 for word in words_for_navigation if word.lower() in normalized)
        meaningful = re.sub(r"https?://\S+", "", normalized)
        meaningful = re.sub(r"!\[[^\]]*]\([^)]+\)|\[[^\]]+]\([^)]+\)", "", meaningful)
        meaningful = re.sub(r"[#*_`>\-\s|:：,，.。/\\{}()[\]\"'=;；]+", "", meaningful)
        if nav_hits >= 4 and len(meaningful) < 220:
            return WEB_LINK_NAVIGATION_PORTAL_MARKDOWN

        return ""

    @staticmethod
    def _visible_markdown_text(markdown: str) -> str:
        text = re.sub(r"!\[([^\]]*)]\([^)]+\)", r"\1", markdown or "")
        text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
        return re.sub(r"https?://\S+", "", text)

    @classmethod
    def _should_use_rendered_extraction(
        cls,
        static_extraction: _MarkdownExtraction,
        rendered_extraction: _MarkdownExtraction,
    ) -> bool:
        if static_extraction.needs_rendered_fallback and not rendered_extraction.needs_rendered_fallback:
            return True
        if (
            static_extraction.needs_rendered_fallback
            and rendered_extraction.low_value_reason
            and rendered_extraction.body != static_extraction.body
        ):
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
