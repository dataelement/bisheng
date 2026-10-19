import json
import re
from abc import ABC, abstractmethod
from typing import Any

import requests
from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field
from urllib3.util.url import LocationParseError, parse_url

DEFAULT_MAX_CHARS = 20000
MIN_MAX_CHARS = 1000
MAX_MAX_CHARS = 200000

NOT_CONFIGURED_TEXT = "网页读取尚未配置：请联系管理员在内置工具「网页读取」的设置中填写读取引擎的 API Key。"
INVALID_URL_TEXT = "网页读取失败：网址必须是以 http:// 或 https:// 开头的完整网址，且不能包含用户名或密码。"
EMPTY_CONTENT_TEXT = "该网页没有可读正文。"

# A backslash in front of any character that is not a letter, digit or whitespace.
_ESCAPE_PATTERN = re.compile(r"\\([^\w\s])")
_FENCE_PATTERN = re.compile(r"^\s*(```|~~~)")


class FetchError(Exception):
    """A fetch failure whose message is safe to show to the model."""


class FetchInput(BaseModel):
    url: str = Field(description="要读取的网页地址，必须是 http 或 https 开头的完整网址")


def unescape_markdown(content: str) -> str:
    """Remove the backslashes an engine adds in front of punctuation.

    DeepSeek escapes almost every punctuation mark (``\\#``, ``\\-``, ``\\,``).
    Fenced code blocks keep their text unchanged.
    """
    lines = []
    in_fence = False
    for line in content.split("\n"):
        if _FENCE_PATTERN.match(line):
            in_fence = not in_fence
            lines.append(line)
            continue
        lines.append(line if in_fence else _ESCAPE_PATTERN.sub(r"\1", line))
    return "\n".join(lines)


def get_host_from_url(url: str) -> str:
    try:
        return parse_url(url).host or ""
    except LocationParseError:
        return ""


def is_fetchable_url(url: str) -> bool:
    """Accept only absolute http(s) URLs without credentials."""
    try:
        parsed = parse_url((url or "").strip())
    except LocationParseError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.host) and not parsed.auth


class FetchTool(ABC):
    """A web page reading engine. Subclasses return the page title and Markdown body."""

    # (connect, read) seconds. A fetch takes 5-12 s in practice.
    request_timeout: tuple[float, float] = (10, 60)

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    @abstractmethod
    def is_configured(self) -> bool:
        raise NotImplementedError()

    @abstractmethod
    def fetch(self, url: str) -> dict[str, str]:
        """Return ``{"title": str, "content": str}`` or raise FetchError."""
        raise NotImplementedError()

    @classmethod
    def init_fetch_tool(cls, name: str, **kwargs) -> "FetchTool":
        tool_class: dict[str, type[FetchTool]] = {
            "deepseek": DeepSeekFetch,
        }
        if name not in tool_class:
            raise ValueError(f"Fetch engine {name} not found.")
        return tool_class[name](**kwargs)


class DeepSeekFetch(FetchTool):
    """DeepSeek fetch: https://api-docs.deepseek.com/zh-cn/guides/search/"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.api_key = str(kwargs.get("api_key") or "").strip()
        self.base_url = str(kwargs.get("base_url") or "").strip() or "https://api.deepseek.com/v1/tools/fetch"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch(self, url: str) -> dict[str, str]:
        try:
            response = requests.post(
                self.base_url,
                json={"url": url},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.request_timeout,
            )
        except requests.RequestException as e:
            raise FetchError(f"请求读取引擎失败（{type(e).__name__}）") from e
        if response.status_code != 200:
            raise FetchError(self._error_message(response))
        result = response.json()
        return {"title": result.get("title") or "", "content": result.get("content") or ""}

    @staticmethod
    def _error_message(response) -> str:
        try:
            error = response.json().get("error") or {}
            message = error.get("message")
        except ValueError:
            message = None
        return f"HTTP {response.status_code}：{message or response.text[:200]}"


class WebFetchTool(BaseTool):
    """Read one web page and return its title and Markdown body."""

    name: str = "web_fetch"
    description: str = (
        "读取指定网址的网页，返回网页标题和 Markdown 正文。"
        "当搜索结果的摘要不足以回答问题、需要网页全文时使用。一次只能读取一个网址。"
    )
    args_schema: type[BaseModel] = FetchInput
    api_wrapper: FetchTool | None = Field(default=None, description="The fetch engine; None when unconfigured.")
    max_chars: int = DEFAULT_MAX_CHARS

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, url: str, **kwargs: Any) -> str:
        if self.api_wrapper is None or not self.api_wrapper.is_configured():
            return NOT_CONFIGURED_TEXT
        url = (url or "").strip()
        if not is_fetchable_url(url):
            return INVALID_URL_TEXT
        try:
            page = self.api_wrapper.fetch(url)
        except FetchError as e:
            logger.warning(f"web_fetch failed url={url}: {e}")
            return f"网页读取失败：{e}"

        content = unescape_markdown(page["content"]).strip()
        if not content:
            return EMPTY_CONTENT_TEXT
        total_chars = len(content)
        result: dict[str, Any] = {
            "title": unescape_markdown(page["title"]).strip(),
            "url": url,
            "source": get_host_from_url(url),
            "content": content[: self.max_chars],
            "truncated": total_chars > self.max_chars,
            "total_chars": total_chars,
        }
        if result["truncated"]:
            result["note"] = f"正文已截断：原文共 {total_chars} 字，这里只返回前 {self.max_chars} 字。"
        return json.dumps(result, ensure_ascii=False)


def normalize_max_chars(value: Any) -> int:
    try:
        max_chars = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_CHARS
    return min(max(max_chars, MIN_MAX_CHARS), MAX_MAX_CHARS)


def build_web_fetch_tool(**kwargs: Any) -> WebFetchTool:
    """Build the tool from the built-in tool config. A missing config still yields a tool."""
    engine_name = kwargs.get("type") or ""
    engine_config = (kwargs.get("config") or {}).get(engine_name) or {}
    api_wrapper = FetchTool.init_fetch_tool(engine_name, **engine_config) if engine_name else None
    return WebFetchTool(api_wrapper=api_wrapper, max_chars=normalize_max_chars(kwargs.get("max_chars")))
