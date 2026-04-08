"""
频道文章AI助手对话相关的请求/响应 Schema
"""
from typing import Optional, List

from pydantic import BaseModel, Field


class ChannelArticleChatRequest(BaseModel):
    """频道文章AI助手对话请求"""
    article_doc_id: str = Field(..., description='ES文章文档ID，用于获取文章内容作为对话上下文')
    model: str = Field(..., description='模型ID')
    text: str = Field(..., description='用户消息内容')
    conversationId: Optional[str] = Field(None, description='会话ID，为空则创建新会话')
    parentMessageId: Optional[str] = Field(None, description='父消息ID')


class ClearChatRequest(BaseModel):
    """清空对话请求"""
    conversationId: str = Field(..., description='要清空的会话ID')
