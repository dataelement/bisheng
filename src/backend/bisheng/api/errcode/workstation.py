from bisheng.api.errcode.base import BaseErrorCode


# Workstation模块相关的返回错误码，功能模块代码：120
# No web_search tool found in database
class WebSearchToolNotFoundError(BaseErrorCode):
    Code: int = 12040
    Msg: str = '未找到web_search工具'


# 会话不存在
class ConversationNotFoundError(BaseErrorCode):
    Code: int = 12041
    Msg: str = '会话不存在'

# 该智能体已被添加
class AgentAlreadyExistsError(BaseErrorCode):
    Code: int = 12042
    Msg: str = '该智能体已被添加'