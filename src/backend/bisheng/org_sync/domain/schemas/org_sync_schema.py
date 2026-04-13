"""Request/response DTOs for org sync API endpoints."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Request DTOs
# ---------------------------------------------------------------------------

class OrgSyncConfigCreate(BaseModel):
    provider: str
    config_name: str
    auth_type: str
    auth_config: dict
    sync_scope: Optional[dict] = None
    schedule_type: str = 'manual'
    cron_expression: Optional[str] = None

    @field_validator('provider')
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {'feishu', 'wecom', 'dingtalk', 'generic_api'}
        if v not in allowed:
            raise ValueError(f'provider must be one of {allowed}')
        return v

    @field_validator('auth_type')
    @classmethod
    def validate_auth_type(cls, v: str) -> str:
        allowed = {'api_key', 'password'}
        if v not in allowed:
            raise ValueError(f'auth_type must be one of {allowed}')
        return v

    @field_validator('schedule_type')
    @classmethod
    def validate_schedule_type(cls, v: str) -> str:
        allowed = {'manual', 'cron'}
        if v not in allowed:
            raise ValueError(f'schedule_type must be one of {allowed}')
        return v


class OrgSyncConfigUpdate(BaseModel):
    auth_type: Optional[str] = None
    auth_config: Optional[dict] = None
    sync_scope: Optional[dict] = None
    schedule_type: Optional[str] = None
    cron_expression: Optional[str] = None
    status: Optional[str] = None
    config_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Response DTOs
# ---------------------------------------------------------------------------

class OrgSyncConfigRead(BaseModel):
    id: int
    provider: str
    config_name: str
    auth_type: str
    auth_config: dict  # masked
    sync_scope: Optional[dict] = None
    schedule_type: str
    cron_expression: Optional[str] = None
    sync_status: str
    last_sync_at: Optional[datetime] = None
    last_sync_result: Optional[str] = None
    status: str
    create_user: Optional[int] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


class OrgSyncLogRead(BaseModel):
    id: int
    config_id: int
    trigger_type: str
    trigger_user: Optional[int] = None
    status: str
    dept_created: int = 0
    dept_updated: int = 0
    dept_archived: int = 0
    member_created: int = 0
    member_updated: int = 0
    member_disabled: int = 0
    member_reactivated: int = 0
    error_details: Optional[list] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    create_time: Optional[datetime] = None


class RemoteTreeNode(BaseModel):
    external_id: str
    name: str
    children: list['RemoteTreeNode'] = []


# ---------------------------------------------------------------------------
# Sensitive field masking (AC-34)
# ---------------------------------------------------------------------------

SENSITIVE_KEYS = {'app_secret', 'api_key', 'password', 'secret', 'token'}


def mask_sensitive_fields(auth_config: dict) -> dict:
    """Replace sensitive values with '****' for API responses."""
    masked = {}
    for key, value in auth_config.items():
        if key.lower() in SENSITIVE_KEYS or 'secret' in key.lower() or 'password' in key.lower():
            masked[key] = '****'
        elif isinstance(value, dict):
            masked[key] = mask_sensitive_fields(value)
        else:
            masked[key] = value
    return masked
