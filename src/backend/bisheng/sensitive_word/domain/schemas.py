from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class SensitiveWordBusinessType(str, Enum):
    KNOWLEDGE_SPACE_FILE_PARSE = 'knowledge_space_file_parse'
    CHANNEL_ARTICLE = 'channel_article'


class SensitiveWordScopeType(str, Enum):
    TENANT = 'tenant'


SensitiveWordType = Literal['builtin', 'custom']


class SensitiveWordPolicyPayload(BaseModel):
    enabled: bool = False
    words_types: List[SensitiveWordType] = Field(default_factory=list)
    custom_words: str = ''
    auto_reply: str = ''
    extra_config: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('words_types')
    @classmethod
    def dedupe_words_types(cls, value: List[str]) -> List[str]:
        allowed = {'builtin', 'custom'}
        result: List[str] = []
        for item in value or []:
            if item in allowed and item not in result:
                result.append(item)
        return result


class SensitiveWordPolicyResp(SensitiveWordPolicyPayload):
    tenant_id: int
    business_type: SensitiveWordBusinessType
    scope_type: SensitiveWordScopeType = SensitiveWordScopeType.TENANT
    scope_id: str


class SensitiveWordHit(BaseModel):
    word: str
    count: int


class SensitiveWordCheckResult(BaseModel):
    enabled: bool = False
    hits: List[SensitiveWordHit] = Field(default_factory=list)
    auto_reply: Optional[str] = None
