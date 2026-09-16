"""MCP face and unified retrieval facade error codes — module 263 (F052).

Module 263 was claimed by F052 because the 260 band is **full in the places
that matter**: ``common/errcode/open_api.py`` owns 26001-26031 / 26040-26044 /
26050-26051 and keeps 26032-26039 plus 26045-26049 *reserved* (pinned by
``test/open_api/test_error_codes.py``). Squeezing the MCP face into those holes
would have collided with that reservation, so the whole face lives here.

Sub-ranges (design §4.2 ④):

* ``26300-26319`` MCP transport / tool face (owned by the MCP server slice)
* ``26320-26339`` unified retrieval facade — shared by all four callers
  (MCP search tool, v2 ``POST /filelib/retrieve``, F055 hosted runtime,
  F057 SDK retrieve)
* ``26340+`` reserved

Three constraints that are easy to miss:

* Every subclass declares its code **with the ``: int`` annotation**.
  ``check-i18n.mjs`` finds backend codes by matching that exact annotated form,
  so it is what makes a code visible to the three-language parity check. Do
  **not** copy the un-annotated ``Code = 26001`` style used by ``open_api.py``.
  (Nor write the annotated form with a placeholder digit-plus-letters value in
  prose anywhere — the scanner's ``\\d+`` stops at the first non-digit and would
  register a bogus truncated code.)
* Each class carries a real ``http_status``; ``open_api/api/exception_handlers.py``
  returns it on ``/api/v2`` paths and keeps the 200 envelope everywhere else.
* Copy for every code lives in
  ``src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`` and
  ships in the same change (CI ``pnpm check-i18n``). The ``next_step`` hint the
  MCP face returns to a local agent is **not** stored there — the backend
  process does not ship the frontend locale package and cannot read it.
"""

from bisheng.common.errcode.base import BaseErrorCode


class McpFaceError(BaseErrorCode):
    """Base of the 263xx family (MCP face + unified retrieval facade)."""

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
# 26300-26319 — MCP transport / tool face
# ---------------------------------------------------------------------------


class McpUnknownToolError(McpFaceError):
    """No such tool in the registry (also: a tool whose backend is not landed)."""

    Code: int = 26301
    Msg: str = "Unknown MCP tool"
    http_status: int = 404


class McpToolScopeMissingError(McpFaceError):
    """The key does not carry the scope this tool maps to (AC-04)."""

    Code: int = 26302
    Msg: str = "API credential lacks the scope required by this tool"
    http_status: int = 403

    def __init__(self, required: str, **kwargs):
        super().__init__(required=required, **kwargs)


class McpIdentityHeaderRefusedError(McpFaceError):
    """The MCP face never carries delegation — identity headers are refused."""

    Code: int = 26303
    Msg: str = "The MCP face does not carry delegated identity"
    http_status: int = 403


class McpToolArgumentInvalidError(McpFaceError):
    """Tool arguments failed validation; ``data.errors`` carries the summary."""

    Code: int = 26304
    Msg: str = "Invalid MCP tool arguments"
    http_status: int = 400


class McpAppNotOwnedError(McpFaceError):
    """Not an application owned by this key's resource owner (AC-34).

    Missing, other-tenant and other-owner applications all answer with this
    one shape, and it never names the owner.
    """

    Code: int = 26305
    Msg: str = "Not an application owned by this credential"
    http_status: int = 403


class McpIdentityNotFoundError(McpFaceError):
    """User / department absent or in another tenant — one shared answer (AC-32)."""

    Code: int = 26306
    Msg: str = "User or department not found"
    http_status: int = 404


# ---------------------------------------------------------------------------
# 26320-26339 — unified retrieval facade (shared by all four callers)
# ---------------------------------------------------------------------------


class RetrievalIdentityMissingError(McpFaceError):
    """Fail-closed: no execution identity, therefore no retrieval (AC-23)."""

    Code: int = 26320
    Msg: str = "Retrieval requires an execution identity"
    http_status: int = 403


class KnowledgeUnreachableError(McpFaceError):
    """One answer for missing / ungranted / unsupported knowledge bases (AC-11).

    The facade refuses the whole request rather than silently dropping the
    unreachable targets, and it never says *why* a target is unreachable —
    the three causes must stay indistinguishable so existence does not leak.
    """

    Code: int = 26321
    Msg: str = "Knowledge base is unreachable"
    http_status: int = 404

    def __init__(self, unreachable_ids: list[int], **kwargs):
        super().__init__(unreachable_ids=list(unreachable_ids), **kwargs)


class KnowledgeCapabilityRevokedError(McpFaceError):
    """A declared (whitelisted) knowledge base no longer exists (AC-46).

    Distinguishable on purpose: F055 turns it into an app-visible "capability
    revoked" error instead of quietly narrowing the declared scope.
    """

    Code: int = 26322
    Msg: str = "Declared knowledge capability has been revoked"
    http_status: int = 409

    def __init__(self, knowledge_id: int, **kwargs):
        super().__init__(knowledge_id=int(knowledge_id), **kwargs)


class RetrievalScopeTooLargeError(McpFaceError):
    """Too many targets, or a granted scope wider than the facade enumerates."""

    Code: int = 26323
    Msg: str = "Retrieval scope is too large; name the knowledge bases explicitly"
    http_status: int = 400
