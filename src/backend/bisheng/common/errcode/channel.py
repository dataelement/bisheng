from .base import BaseErrorCode


class BishengInformationUnAuthorizedError(BaseErrorCode):
    Code: int = 13001
    Msg: str = 'Unauthorized access to Bisheng Information Service'

class BishengInformationServiceError(BaseErrorCode):
    Code: int = 13002
    Msg: str = 'Error occurred while accessing Bisheng Information Service'

# Channel module error codes, module code: 130
# Article not found
class ArticleNotFoundError(BaseErrorCode):
    Code: int = 13040
    Msg: str = '文章不存在'


# Channel chat conversation not found
class ChannelChatConversationNotFoundError(BaseErrorCode):
    Code: int = 13041
    Msg: str = '对话会话不存在'
