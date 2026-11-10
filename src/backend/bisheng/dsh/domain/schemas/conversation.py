"""Untrusted conversation hints scoped by authenticated identity before upstream use.

The client sends these inside the request body's ``audit_context`` object, using the
same keys and values as the model-audit contract (``conversation_id``/``request_kind``),
so one negotiated field serves both audit and supplier affinity.
"""

import hashlib
import json
from typing import Literal

from pydantic import Field, ValidationError

from bisheng.dsh.domain.schemas.contracts import DshContract

AUDIT_CONTEXT_KEY = "audit_context"


class ConversationHint(DshContract):
    conversation_id: str = Field(min_length=1, max_length=256)
    request_kind: Literal["chat", "compaction", "session-title"] = "chat"

    def upstream_headers(self, principal, model_id: int) -> dict[str, str]:
        # Compaction shares the conversation's long prefix, so it keeps the chat scope to
        # reuse the supplier cache; only short title calls get their own scope.
        scope_kind = "session-title" if self.request_kind == "session-title" else "chat"
        scope = [
            "dsh-conversation-v1",
            str(int(principal.tenant_id)),
            str(int(principal.user_id)),
            str(model_id),
            scope_kind,
            self.conversation_id,
        ]
        digest = hashlib.sha256(json.dumps(scope, separators=(",", ":")).encode()).hexdigest()
        return {"session_id": digest}


def parse_conversation(raw) -> ConversationHint | None:
    """Metadata never fails a model request: invalid or absent context only drops affinity."""
    if not isinstance(raw, dict) or "conversation_id" not in raw:
        return None
    try:
        return ConversationHint.model_validate(
            {key: raw[key] for key in ("conversation_id", "request_kind") if key in raw}
        )
    except ValidationError:
        return None
