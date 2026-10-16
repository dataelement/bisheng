"""Untrusted conversation hints scoped by authenticated identity before upstream use."""

import hashlib
import json
from typing import Literal

from pydantic import Field

from bisheng.dsh.domain.schemas.contracts import DshContract


class ConversationHint(DshContract):
    conversation_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    purpose: Literal["chat", "compaction", "session-title"] = "chat"

    def upstream_headers(self, principal, model_id: int) -> dict[str, str]:
        scope = [
            "dsh-conversation-v1",
            str(int(principal.tenant_id)),
            str(int(principal.user_id)),
            str(model_id),
            self.purpose,
            self.conversation_id,
        ]
        digest = hashlib.sha256(json.dumps(scope, separators=(",", ":")).encode()).hexdigest()
        return {"session_id": digest}
