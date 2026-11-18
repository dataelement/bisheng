from bisheng_langchain.utils.safe_http import arequest
from bisheng_langchain.utils.safe_http_errors import RequestFailed


async def get_url_content(url: str) -> str:
    """Download a bounded schema through the same pinned tool transport."""
    response = await arequest("GET", url, max_bytes=2 * 1024 * 1024)
    if response.status != 200:
        raise RequestFailed()
    try:
        return response.body.decode("utf-8")
    except UnicodeError:
        raise RequestFailed() from None
