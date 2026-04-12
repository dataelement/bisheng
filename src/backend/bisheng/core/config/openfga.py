"""OpenFGA configuration model."""

from typing import Optional

from pydantic import BaseModel, Field


class OpenFGAConf(BaseModel):
    """OpenFGA connection and behavior configuration."""

    enabled: bool = Field(default=True, description='Whether to enable OpenFGA integration')
    api_url: str = Field(default='http://localhost:8080', description='OpenFGA HTTP API URL')
    store_name: str = Field(default='bisheng', description='Store name (auto-created if not exists)')
    store_id: Optional[str] = Field(default=None, description='Existing store ID (skip auto-create)')
    model_id: Optional[str] = Field(default=None, description='Existing model ID (skip auto-write)')
    timeout: int = Field(default=5, description='HTTP request timeout in seconds')
