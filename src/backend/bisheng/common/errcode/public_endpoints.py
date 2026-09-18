"""Anonymous public v3 channel errors (module 261).

The public v3 surface serves guest share links. Callers are anonymous, so the
messages here must stay free of internal object names and must never reveal
why a lookup failed beyond the two states a visitor can act on: "the link is
not usable" and "the application is offline".

``Code`` carries the type annotation on purpose: ``scripts/check-i18n.mjs``
scans for ``Code: int = <n>`` to enforce that every backend code ships
``api_errors`` copy in all three languages.
"""

from bisheng.common.errcode.base import BaseErrorCode


class PublicAccessError(BaseErrorCode):
    """Base error carrying the real transport status for the v3 handler.

    Abstract on purpose: it declares no ``Code`` of its own, so it is only ever
    raised through one of the concrete subclasses below. It exists to give the
    exception handler and the WebSocket adapters a single type to catch.
    """

    http_status: int = 403

    def __init__(
        self,
        exception: Exception | None = None,
        msg: str | None = None,
        code: int | None = None,
        http_status: int | None = None,
        **kwargs,
    ):
        super().__init__(exception=exception, msg=msg, code=code, **kwargs)
        if http_status is not None:
            self.http_status = http_status


class PublicLinkInvalidError(PublicAccessError):
    """The link points at nothing we can serve — wrong, truncated or deleted."""

    Code: int = 26101
    Msg: str = "This link is invalid or has expired"
    http_status: int = 404


class PublicApplicationOfflineError(PublicAccessError):
    """The application exists but its owner took it offline."""

    Code: int = 26102
    Msg: str = "This app has been taken offline and is unavailable"
    http_status: int = 404


class PublicGuestAccessDisabledError(PublicAccessError):
    """Guest access is switched off platform-wide, or its operator is unusable."""

    Code: int = 26103
    Msg: str = "Link sharing is turned off. Contact whoever shared the link."
    http_status: int = 403


class PublicIdentityHeaderRejectedError(PublicAccessError):
    """An anonymous caller tried to assert a v2 identity header."""

    Code: int = 26104
    Msg: str = "Identity headers are not accepted by the public API"
    http_status: int = 403


__all__ = [
    "PublicAccessError",
    "PublicApplicationOfflineError",
    "PublicGuestAccessDisabledError",
    "PublicIdentityHeaderRejectedError",
    "PublicLinkInvalidError",
]
