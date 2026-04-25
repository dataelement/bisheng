from .base import BaseErrorCode


class BishengInformationUnAuthorizedError(BaseErrorCode):
    Code: int = 19001
    Msg: str = 'Unauthorized access to Bisheng Information Service'


class BishengInformationServiceError(BaseErrorCode):
    Code: int = 19002
    Msg: str = 'Error occurred while accessing Bisheng Information Service'


# Parsing failed, please try again or submit a manual request
class InformationSourceParseError(BaseErrorCode):
    Code: int = 19003
    Msg: str = 'Parsing failed, please try again or submit a manual requirement'


# This website cannot be crawled due to permission settings. Please enter a valid "Column List Page" URL (e.g., News, Policies and Regulations list pages).
class InformationSourceAuthError(BaseErrorCode):
    Code: int = 19004
    Msg: str = 'Access denied by website permissions. Please provide a valid "Column List Page" URL (e.g., News or Policy list pages)'


# Detected as a single article or non-list page. Please enter a valid "Column List Page" URL (e.g., News, Policies and Regulations list pages).
class InformationSourcePageError(BaseErrorCode):
    Code: int = 19005
    Msg: str = 'Single article or non-list page detected. Please provide a valid "Column List Page" URL (e.g., News or Policy list pages)'


class InformationSourceCrawlLimitError(BaseErrorCode):
    Code: int = 19006
    Msg: str = '网站爬取数量超过当前 API key 限制'


class InformationSourceSubscriptionLimitError(BaseErrorCode):
    Code: int = 19007
    Msg: str = '订阅信息源数量超过当前 API key 限制'


class InformationSourceWechatSearchLimitError(BaseErrorCode):
    Code: int = 19008
    Msg: str = '公众号检索次数超过当前 API key 限制'


# Channel Management error codes, module code: 190
class ChannelNotFoundError(BaseErrorCode):
    Code: int = 19010
    Msg: str = 'Channel not found'


# Private channel access permission error
class ChannelAccessDeniedError(BaseErrorCode):
    Code: int = 19011
    Msg: str = 'Access denied to private channel'


# Channel already subscribed or application submitted
class ChannelAlreadySubscribedError(BaseErrorCode):
    Code: int = 19012
    Msg: str = 'Already subscribed to this channel or application is pending'


# No permission to operate channel
class ChannelPermissionDeniedError(BaseErrorCode):
    Code: int = 19013
    Msg: str = 'Permission denied for this channel operation'


# Channel module error codes, module code: 190
# Article not found
class ArticleNotFoundError(BaseErrorCode):
    Code: int = 19040
    Msg: str = 'Article not found'


# Channel chat conversation not found
class ChannelChatConversationNotFoundError(BaseErrorCode):
    Code: int = 19041
    Msg: str = 'Chat conversation not found'


# User has reached the maximum limit for creating channels
class ChannelCreateLimitExceededError(BaseErrorCode):
    Code: int = 19050
    Msg: str = 'Maximum limit for creating channels reached (up to 10 channels)'


# Channel has reached the maximum limit for administrators
class ChannelAdminLimitExceededError(BaseErrorCode):
    Code: int = 19051
    Msg: str = 'Maximum limit for administrators reached (up to 5 admins)'


# User has reached the maximum limit for subscribing channels
class ChannelSubscribeLimitExceededError(BaseErrorCode):
    Code: int = 19052
    Msg: str = 'Maximum limit for subscribing channels reached (up to 20 channels)'


# Knowledge space LLM not configured
class KnowledgeSpaceLLMNotConfiguredError(BaseErrorCode):
    Code: int = 19053
    Msg: str = 'Knowledge space LLM is not configured. Please configure it in workbench settings first'
