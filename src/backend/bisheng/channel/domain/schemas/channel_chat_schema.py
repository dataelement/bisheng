"""
Channel Article AI Assistant Chat Request/Response Schema
"""
from typing import Optional, List

from pydantic import BaseModel, Field


class ChannelArticleChatRequest(BaseModel):
    """Channel Article AI Assistant Chat Request"""
    article_doc_id: str = Field(..., description='ES article document ID, used to fetch article content as conversation context')
    model: str = Field(..., description='Model ID')
    text: str = Field(..., description='User message content')
    conversationId: Optional[str] = Field(None, description='Conversation ID, creates new conversation if empty')
    parentMessageId: Optional[str] = Field(None, description='Parent message ID')


class ClearChatRequest(BaseModel):
    """Clear Chat Request"""
    conversationId: str = Field(..., description='Conversation ID to clear')
