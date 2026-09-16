"""MCP server face + unified retrieval facade error codes — module 263 (F052).

Module 263 is claimed by F052. It is deliberately **not** part of the 260 band
(F049 open API auth): 260 still reserves 26032-26039 and 26045-26049 as holes
that ``test/open_api/test_error_codes.py`` pins, and squatting there would make
"one code, one meaning" depend on remembering which holes are free.

Sub-ranges:

* ``26300-26319`` MCP transport + tool face (owned by ``open_api/mcp/``)
* ``26320-26339`` unified retrieval facade (shared by its four callers: the MCP
  search tool, ``POST /api/v2/filelib/retrieve``, the hosted-app runtime and the
  SDK's ``retrieve``)
* ``26340+`` reserved

Two constraints that are easy to miss:

* Every subclass declares its code **with the ``Code: int`` annotation**.
  ``pnpm check-i18n`` collects backend codes by matching that annotated form, so
  the un-annotated ``Code = <number>`` spelling used throughout ``open_api.py``
  is invisible to it — a missing translation would pass CI silently. (Prose in
  this file avoids writing the annotated form with a number attached, or the
  collector would read the example as a real code.)
* Copy for every code lives in
  ``src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`` and ships
  in the same change. The ``next_step`` guidance an MCP client reads is **not**
  there — the backend process does not carry the frontend locale package, so it
  lives in ``open_api/mcp/errors.py: NEXT_STEP_COPY`` instead.
"""

from typing import Any

from bisheng.common.errcode.base import BaseErrorCode


class McpFaceError(BaseErrorCode):
    """Base of the 263xx family; carries the real transport status for v2."""

    Code: int = 26300
    Msg: str = "MCP face error"
    http_status: int = 400

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


# ---------------------------------------------------------------------------
# 26300-26319 — MCP transport and tool face
# ---------------------------------------------------------------------------


class McpUnknownToolError(McpFaceError):
    """No such tool, or the tool's server-side dependency has not shipped yet."""

    Code: int = 26301
    Msg: str = "Unknown MCP tool"
    http_status: int = 404


class McpToolScopeMissingError(McpFaceError):
    """The credential does not hold the scope this tool maps to.

    A separate code from 26003 (which answers an HTTP endpoint): one code, one
    meaning, and the agent must be able to tell "this tool needs a scope you do
    not have" from "this endpoint needs a scope you do not have".
    """

    Code: int = 26302
    Msg: str = "API credential lacks the scope required by this tool"
    http_status: int = 403

    def __init__(self, required: str, **kwargs):
        super().__init__(required=required, **kwargs)


class McpIdentityHeaderRefusedError(McpFaceError):
    """An identity-passing header reached the MCP face (AC-30)."""

    Code: int = 26303
    Msg: str = "The MCP face does not carry delegated identity"
    http_status: int = 403


class McpToolArgumentInvalidError(McpFaceError):
    """The tool arguments failed validation."""

    Code: int = 26304
    Msg: str = "Invalid MCP tool arguments"
    http_status: int = 400

    def __init__(self, errors: Any = None, **kwargs):
        super().__init__(errors=errors, **kwargs)


class McpAppNotOwnedError(McpFaceError):
    """Not an application this credential's resource owner owns (AC-34).

    The same answer for "does not exist", "another tenant's" and "someone
    else's", and it never names the owner.
    """

    Code: int = 26305
    Msg: str = "Not an application owned by this credential"
    http_status: int = 403


class McpIdentityNotFoundError(McpFaceError):
    """User or department absent, or in another tenant — one answer (AC-32)."""

    Code: int = 26306
    Msg: str = "User or department not found"
    http_status: int = 404


# ---------------------------------------------------------------------------
# 26320-26339 — unified retrieval facade (all four callers)
# ---------------------------------------------------------------------------


class RetrievalIdentityMissingError(McpFaceError):
    """No execution identity could be established — refuse, never fall back."""

    Code: int = 26320
    Msg: str = "Retrieval requires an execution identity"
    http_status: int = 403


class KnowledgeUnreachableError(McpFaceError):
    """One answer for missing / ungranted / unsupported / outside-whitelist."""

    Code: int = 26321
    Msg: str = "Knowledge base is unreachable"
    http_status: int = 404

    def __init__(self, unreachable_ids: Any = None, **kwargs):
        super().__init__(unreachable_ids=list(unreachable_ids or []), **kwargs)


class KnowledgeCapabilityRevokedError(McpFaceError):
    """A declared (whitelisted) knowledge base is gone — a distinguishable signal."""

    Code: int = 26322
    Msg: str = "Declared knowledge capability has been revoked"
    http_status: int = 409

    def __init__(self, knowledge_id: Any = None, **kwargs):
        super().__init__(knowledge_id=knowledge_id, **kwargs)


class RetrievalScopeTooLargeError(McpFaceError):
    """Too many targets, or too wide a granted scope to enumerate."""

    Code: int = 26323
    Msg: str = "Retrieval scope is too large; name the knowledge bases explicitly"
    http_status: int = 400
