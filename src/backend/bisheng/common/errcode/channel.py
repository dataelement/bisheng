from .base import BaseErrorCode


class BishengInformationUnAuthorizedError(BaseErrorCode):
    Code: int = 13001
    Msg: str = 'Unauthorized access to Bisheng Information Service'

class BishengInformationServiceError(BaseErrorCode):
    Code: int = 13002
    Msg: str = 'Error occurred while accessing Bisheng Information Service'


# Channel Management error codes, module code: 130
class ChannelNotFoundError(BaseErrorCode):
    Code: int = 13010
    Msg: str = '频道不存在'

# 私密频道访问权限错误
class ChannelAccessDeniedError(BaseErrorCode):
    Code: int = 13011
    Msg: str = '无权访问私密频道'

# 频道以订阅或以提交申请
class ChannelAlreadySubscribedError(BaseErrorCode):
    Code: int = 13012
    Msg: str = '已订阅该频道或已提交申请'


# Channel module error codes, module code: 130
# Article not found
class ArticleNotFoundError(BaseErrorCode):
    Code: int = 13040
    Msg: str = '文章不存在'


# Channel chat conversation not found
class ChannelChatConversationNotFoundError(BaseErrorCode):
    Code: int = 13041
    Msg: str = '对话会话不存在'
