from enum import Enum


class ToolPresetType(Enum):
    PRESET = 1  # Provisioning Tools
    API = 0  # CustomizableAPITools
    MCP = 2  # mcpTypes of Tools


class AuthMethod(Enum):
    NO = 0
    API_KEY = 1


class AuthType(Enum):
    BASIC = "basic"
    BEARER = "bearer"
    CUSTOM = "custom"
