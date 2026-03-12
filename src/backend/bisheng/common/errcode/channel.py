from .base import BaseErrorCode


class BishengInformationUnAuthorizedError(BaseErrorCode):
    Code: int = 13001
    Msg: str = 'Unauthorized access to Bisheng Information Service'


class BishengInformationServiceError(BaseErrorCode):
    Code: int = 13002
    Msg: str = 'Error occurred while accessing Bisheng Information Service'


# Parsing failed, please try again or submit a manual request
class InformationSourceParseError(BaseErrorCode):
    Code: int = 13003
    Msg: str = 'Parsing failed, please try again or submit a manual requirement'


# This website cannot be crawled due to permission settings. Please enter a valid "Column List Page" URL (e.g., News, Policies and Regulations list pages).
class InformationSourceAuthError(BaseErrorCode):
    Code: int = 13004
    Msg: str = 'Access denied by website permissions. Please provide a valid "Column List Page" URL (e.g., News or Policy list pages)'


# Detected as a single article or non-list page. Please enter a valid "Column List Page" URL (e.g., News, Policies and Regulations list pages).
class InformationSourcePageError(BaseErrorCode):
    Code: int = 13005
    Msg: str = 'Single article or non-list page detected. Please provide a valid "Column List Page" URL (e.g., News or Policy list pages)'


# Channel Management error codes, module code: 130
class ChannelNotFoundError(BaseErrorCode):
    Code: int = 13010
    Msg: str = 'Channel not found'


# Private channel access permission error
class ChannelAccessDeniedError(BaseErrorCode):
    Code: int = 13011
    Msg: str = 'Access denied to private channel'


# Channel already subscribed or application submitted
class ChannelAlreadySubscribedError(BaseErrorCode):
    Code: int = 13012
    Msg: str = 'Already subscribed to this channel or application is pending'


# No permission to operate channel
class ChannelPermissionDeniedError(BaseErrorCode):
    Code: int = 13013
    Msg: str = 'Permission denied for this channel operation'


# Channel module error codes, module code: 130
# Article not found
class ArticleNotFoundError(BaseErrorCode):
    Code: int = 13040
    Msg: str = 'Article not found'


# Channel chat conversation not found
class ChannelChatConversationNotFoundError(BaseErrorCode):
    Code: int = 13041
    Msg: str = 'Chat conversation not found'
