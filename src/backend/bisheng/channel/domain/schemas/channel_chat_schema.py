"""
Channel Article AI Assistant Chat Request/Response Schema
"""
from typing import Optional, List

from pydantic import BaseModel, Field


class ChannelArticleChatRequest(BaseModel):
    """Channel Article AI Assistant Chat Request"""
    article_doc_id: str = Field(..., description='ES article document ID, used to fetch article content as conversation context')
    text: str = Field(..., description='User message content')
    parentMessageId: Optional[str] = Field(None, description='Parent message ID')


class ClearChatRequest(BaseModel):
    """Clear Chat Request"""
    article_doc_id: str = Field(..., description='Article document ID to clear chat')
