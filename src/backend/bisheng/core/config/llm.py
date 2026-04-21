"""LLM configuration model."""

from typing import List

from pydantic import BaseModel, Field


class LLMConf(BaseModel):
    """LLM server registration policy.

    ``endpoint_whitelist`` is an optional compliance lever: when non-empty,
    non-super callers registering a new LLM server must declare a
    ``config.endpoint`` / ``config.openai_api_base`` whose prefix matches
    one of the listed entries; mismatches return 19804. Default empty
    list means "no restriction".
    """

    endpoint_whitelist: List[str] = Field(
        default_factory=list,
        description=(
            'Allowed endpoint URL prefixes. Empty list = no restriction. '
            'Example: ["https://api.openai.com", "https://*.azure.com"]'
        ),
    )
