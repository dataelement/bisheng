"""Credential-free transport results and errors shared by sync/async clients."""

from dataclasses import dataclass


class RequestFailed(ValueError):
    def __init__(self):
        super().__init__("Outbound request failed")


class ResponseTooLarge(ValueError):
    def __init__(self):
        super().__init__("Outbound response exceeds size limit")


class RequestTimeout(ValueError):
    def __init__(self):
        super().__init__("Outbound request timed out")


@dataclass(frozen=True)
class SafeHttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def text(self) -> str:
        # Keep the existing textual tool contract without propagating decode exceptions.
        return self.body.decode("utf-8", errors="replace")
