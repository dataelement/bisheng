import json
from typing import Any, Dict, List, Optional

import redis
from langchain.memory.chat_memory import BaseChatMemory
from langchain_core.messages import (AIMessage, BaseMessage, HumanMessage, get_buffer_string,
                                     message_to_dict, messages_from_dict)
from langchain_core.pydantic_v1 import root_validator
from pydantic import Field


class ConversationRedisMemory(BaseChatMemory):
    """Using redis for storing conversation memory."""
    redis_client: redis.Redis = Field(default=None, exclude=True)
    human_prefix: str = 'Human'
    ai_prefix: str = 'AI'
    session_id: str = 'session'
    memory_key: str = 'history'  #: :meta private:
    redis_url: str
    redis_prefix: str = 'redis_buffer_'
    ttl: Optional[int] = None

    @root_validator()
    def validate_environment(cls, values: Dict) -> Dict:
        redis_url = values.get('redis_url')
        if not redis_url:
            raise ValueError('Redis URL must be set')
        pool = redis.ConnectionPool.from_url(redis_url, max_connections=1)
        values['redis_client'] = redis.StrictRedis(connection_pool=pool)
        return values

    @property
    def buffer(self) -> Any:
        """String buffer of memory."""
        return self.buffer_as_messages if self.return_messages else self.buffer_as_str

    async def abuffer(self) -> Any:
        """String buffer of memory."""
        return (await self.abuffer_as_messages()
                if self.return_messages else await self.abuffer_as_str())

    def _buffer_as_str(self, messages: List[BaseMessage]) -> str:
        return get_buffer_string(
            messages,
            human_prefix=self.human_prefix,
            ai_prefix=self.ai_prefix,
        )

    @property
    def buffer_as_str(self) -> str:
        """Exposes the buffer as a string in case return_messages is True."""
        messages = self.buffer_as_messages
        return self._buffer_as_str(messages)

        # return self._buffer_as_str(self.chat_memory.messages)

    async def abuffer_as_str(self) -> str:
        """Exposes the buffer as a string in case return_messages is True."""
        # messages = await self.chat_memory.aget_messages()
        messages = self.buffer_as_messages
        return self._buffer_as_str(messages)

    @property
    def buffer_as_messages(self) -> List[BaseMessage]:
        """Exposes the buffer as a list of messages in case return_messages is False."""
        # return self.chat_memory.messages
        redis_value = self.redis_client.lrange(self.redis_prefix + self.session_id, 0, -1)
        items = [json.loads(m.decode('utf-8')) for m in redis_value[::-1]]
        messages = messages_from_dict(items)
        return messages

    async def abuffer_as_messages(self) -> List[BaseMessage]:
        """Exposes the buffer as a list of messages in case return_messages is False."""
        self.buffer_as_messages

    @property
    def memory_variables(self) -> List[str]:
        """Will always return list of memory variables.

        :meta private:
        """
        return [self.memory_key]

    def load_memory_variables(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Return history buffer."""
        return {self.memory_key: self.buffer}

    async def aload_memory_variables(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Return key-value pairs given the text input to the chain."""
        buffer = await self.abuffer()
        return {self.memory_key: buffer}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, str]) -> None:
        """Save context from this conversation to buffer."""
        input_str, output_str = self._get_input_output(inputs, outputs)

        input_message_str = json.dumps(message_to_dict(HumanMessage(content=input_str)),
                                       ensure_ascii=False)
        output_message_str = json.dumps(message_to_dict(AIMessage(content=output_str)),
                                        ensure_ascii=False)
        self.redis_client.lpush(self.redis_prefix + self.session_id, input_message_str)
        self.redis_client.lpush(self.redis_prefix + self.session_id, output_message_str)
        if self.ttl:
            self.redis_client.expire(self.redis_prefix + self.session_id, self.ttl)
