from enum import Enum


class McpClientType(Enum, str):
    SSE = 'sse'
    STDIO = 'stdio'
    STREAMABLE = 'streamable'
