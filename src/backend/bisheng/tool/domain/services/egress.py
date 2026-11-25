"""Map fixed public-only transport errors to tool business errors."""

from bisheng.common.errcode.tool import (
    ToolDestinationDeniedError,
    ToolRequestFailedError,
    ToolRequestTimeoutError,
    ToolResponseTooLargeError,
)
from bisheng_langchain.utils.egress_policy import DestinationDenied
from bisheng_langchain.utils.safe_http_errors import RequestFailed, RequestTimeout, ResponseTooLarge


def map_tool_egress_error(exc: Exception) -> Exception:
    """Map known safe errors without attaching potentially sensitive error details.

    Unknown failures retain their original identity and must propagate normally.
    """
    for error_type, business_type in (
        (DestinationDenied, ToolDestinationDeniedError),
        (RequestFailed, ToolRequestFailedError),
        (ResponseTooLarge, ToolResponseTooLargeError),
        (RequestTimeout, ToolRequestTimeoutError),
    ):
        if isinstance(exc, error_type):
            return business_type()
    return exc
