"""LLM configuration model (v2.5.1 F020)."""

from typing import List

from pydantic import BaseModel, Field


class LLMConf(BaseModel):
    """F020 — LLM server registration policy (Child Admin self-service).

    ``endpoint_whitelist`` is an optional compliance lever: when non-empty,
    Child Admins registering a new LLM server must declare a ``config.endpoint``
    (or ``config.openai_api_base``) whose prefix matches one of the listed
    entries; mismatches return 19804. Global super admins are always exempt.
    The default empty list means "no restriction" so single-tenant installs
    don't have to opt in.
    """

    endpoint_whitelist: List[str] = Field(
        default_factory=list,
        description=(
            'Allowed endpoint URL prefixes Child Admins may register. '
            'Empty list = no restriction (default). Example: '
            '["https://api.openai.com", "https://*.azure.com"]'
        ),
    )
