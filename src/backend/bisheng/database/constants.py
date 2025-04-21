from enum import Enum

# 默认普通用户角色的ID
DefaultRole = 2
# 超级管理员角色ID
AdminRole = 1


class ToolPresetType(Enum):
    PRESET = 1  # 预置工具
    API = 0  # 自定义API工具
    MCP = 2  # mcp类型的工具


# 消息表里一些基础的category类型
class MessageCategory(Enum):
    QUESTION = 'question'  # 用户问题
    ANSWER = 'answer'  # 答案
