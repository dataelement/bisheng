from enum import Enum


class ToolPresetType(Enum):
    PRESET = 1  # 预置工具
    API = 0  # 自定义API工具
    MCP = 2  # mcp类型的工具


class AuthMethod(Enum):
    NO = 0
    API_KEY = 1


class AuthType(Enum):
    BASIC = "basic"
    BEARER = "bearer"
    CUSTOM = "custom"
