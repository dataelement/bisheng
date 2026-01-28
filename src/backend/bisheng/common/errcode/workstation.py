from .base import BaseErrorCode


# WorkstationModule-related return error code, function module code:120
# No web_search tool found in database
class WebSearchToolNotFoundError(BaseErrorCode):
    Code: int = 12040
    Msg: str = 'not foundweb_searchTools'


# Session does not exist
class ConversationNotFoundError(BaseErrorCode):
    Code: int = 12041
    Msg: str = 'Session does not exist'

# This agent has been added
class AgentAlreadyExistsError(BaseErrorCode):
    Code: int = 12042
    Msg: str = 'This agent has been added'