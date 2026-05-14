"""
Channel Article AI Assistant Chat Request/Response Schema
"""
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict


class ChannelArticleChatRequest(BaseModel):
    """Channel Article AI Assistant Chat Request"""
    model_config = ConfigDict(validate_by_alias=True, validate_by_name=True)

    article_doc_id: str = Field(..., description='ES article document ID, used to fetch article content as conversation context')
    text: str = Field(..., description='User message content')
    parentMessageId: Optional[str] = Field(None, description='Parent message ID')
    model_id: int = Field(..., alias='modelId', description='Selected LLM model ID')


class ClearChatRequest(BaseModel):
    """Clear Chat Request"""
    article_doc_id: str = Field(..., description='Article document ID to clear chat')
