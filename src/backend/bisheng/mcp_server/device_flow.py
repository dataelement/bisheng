from __future__ import annotations

import time
from typing import Optional

from pydantic import BaseModel, Field

from bisheng.utils import generate_uuid

MCP_DEVICE_FLOW_TTL_MAX = 15 * 60
MCP_DEVICE_FLOW_TTL_DEFAULT = 10 * 60
MCP_DEVICE_FLOW_INTERVAL_DEFAULT = 5
MCP_DEVICE_FLOW_INTERVAL_MAX = 30
MCP_DEVICE_REDIS_PREFIX = 'mcp:device'


class McpDeviceSession(BaseModel):
    device_code: str
    user_code: str
    client_id: str
    client_name: str = ''
    scopes: list[str] = Field(default_factory=list)
    status: str = 'pending'
    expires_at: int
    interval: int = MCP_DEVICE_FLOW_INTERVAL_DEFAULT
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))
    last_poll_at: int = 0
    user_id: Optional[int] = None
    user_name: str = ''
    parent_session_hash: str = ''
    denied_reason: str = ''

    @property
    def expired(self) -> bool:
        return self.expires_at <= int(time.time())

    @property
    def expires_in(self) -> int:
        return max(0, self.expires_at - int(time.time()))


def normalize_device_flow_ttl(expires_in: Optional[int]) -> int:
    if expires_in is None:
        return MCP_DEVICE_FLOW_TTL_DEFAULT
    return max(60, min(int(expires_in), MCP_DEVICE_FLOW_TTL_MAX))


def normalize_device_flow_interval(interval: Optional[int]) -> int:
    if interval is None:
        return MCP_DEVICE_FLOW_INTERVAL_DEFAULT
    return max(1, min(int(interval), MCP_DEVICE_FLOW_INTERVAL_MAX))


def device_code_key(device_code: str) -> str:
    return f'{MCP_DEVICE_REDIS_PREFIX}:code:{device_code}'


def user_code_key(user_code: str) -> str:
    return f'{MCP_DEVICE_REDIS_PREFIX}:user:{user_code}'


def generate_device_code() -> str:
    return generate_uuid().replace('-', '')


def generate_user_code() -> str:
    raw = generate_uuid().replace('-', '').upper()
    return f'{raw[:4]}-{raw[4:8]}'


async def save_device_session(redis_client, session: McpDeviceSession):
    expiration = max(1, session.expires_in)
    await redis_client.aset(device_code_key(session.device_code), session.model_dump(), expiration=expiration)
    await redis_client.aset(user_code_key(session.user_code), session.device_code, expiration=expiration)


async def load_device_session_by_device_code(redis_client, device_code: str) -> Optional[McpDeviceSession]:
    payload = await redis_client.aget(device_code_key(device_code))
    if not payload:
        return None
    if isinstance(payload, McpDeviceSession):
        return payload
    return McpDeviceSession.model_validate(payload)


async def load_device_session_by_user_code(redis_client, user_code: str) -> Optional[McpDeviceSession]:
    device_code = await redis_client.aget(user_code_key(user_code))
    if not device_code:
        return None
    return await load_device_session_by_device_code(redis_client, device_code)


async def delete_device_session(redis_client, session: McpDeviceSession):
    await redis_client.adelete(device_code_key(session.device_code))
    await redis_client.adelete(user_code_key(session.user_code))
