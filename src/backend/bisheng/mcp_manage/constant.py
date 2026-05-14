from enum import Enum


class McpClientType(str, Enum):
    SSE = 'sse'
    STDIO = 'stdio'
    STREAMABLE = 'streamable'
