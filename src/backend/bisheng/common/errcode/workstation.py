from .base import BaseErrorCode


# WorkstationModule-related return error code, function module code:120
# No web_search tool found in database
class WebSearchToolNotFoundError(BaseErrorCode):
    Code: int = 12040
    Msg: str = "not foundweb_searchTools"


# Session does not exist
class ConversationNotFoundError(BaseErrorCode):
    Code: int = 12041
    Msg: str = "Session does not exist"


# This agent has been added
class AgentAlreadyExistsError(BaseErrorCode):
    Code: int = 12042
    Msg: str = "This agent has been added"


class UsedAppNotFoundError(BaseErrorCode):
    Code: int = 12043
    Msg: str = "Used app not found"


class UsedAppNotOnlineError(BaseErrorCode):
    Code: int = 12044
    Msg: str = "Used app not online"


class DepartmentDailyChatConcurrentLimitError(BaseErrorCode):
    """Department traffic control: too many users in daily-mode chat at once."""

    Code: int = 12045
    Msg: str = "部门同时在线会话数已达上限，请稍后再试"


# F079 tag management console (12046-12049).
# Registered in features/v2.6.0/release-contract.md under module code 120.


class TagConsoleBatchTooLargeError(BaseErrorCode):
    """A single batch operation carries more items than the console allows."""

    Code: int = 12046
    Msg: str = "单次批量操作最多处理 500 个标签"


class TagConsolePageParamsError(BaseErrorCode):
    """page / page_size out of the accepted range."""

    Code: int = 12047
    Msg: str = "分页参数不合法"


class TagConsoleActionNotApplicableError(BaseErrorCode):
    """The action does not apply to the tag's current state.

    Raised before delegating to the review flow so the caller gets a meaningful
    message instead of the misleading "tag not found" that the underlying query
    would produce for an already-rejected tag.
    """

    Code: int = 12048
    Msg: str = "该标签的当前状态不支持此操作"


class TagConsoleRejectReasonRequiredError(BaseErrorCode):
    """Rejecting a tag requires a reason, for both single and batch calls."""

    Code: int = 12049
    Msg: str = "驳回原因不能为空"
