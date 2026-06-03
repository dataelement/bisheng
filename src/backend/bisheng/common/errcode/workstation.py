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


class UsedAppNotFoundError(BaseErrorCode):
    Code: int = 12043
    Msg: str = 'Used app not found'

class UsedAppNotOnlineError(BaseErrorCode):
    Code: int = 12044
    Msg: str = 'Used app not online'


class DepartmentDailyChatConcurrentLimitError(BaseErrorCode):
    """Department traffic control: too many users in daily-mode chat at once."""

    Code: int = 12045
    Msg: str = '部门同时在线会话数已达上限，请稍后再试'


# --- F028: Conversation export / import to knowledge space (12060-12079) ---


class ConversationMessageNotFoundError(BaseErrorCode):
    Code: int = 12060
    Msg: str = '消息不存在或已删除，请刷新会话'


class ConversationMessageBatchTooLargeError(BaseErrorCode):
    Code: int = 12061
    Msg: str = '单次最多选中 200 条消息'


class ConversationMessageNotOwnedError(BaseErrorCode):
    Code: int = 12062
    Msg: str = '消息不存在或无访问权'


class ConversationExportFormatUnsupportedError(BaseErrorCode):
    Code: int = 12063
    Msg: str = '不支持的导出格式'


class ConversationExportRenderFailedError(BaseErrorCode):
    Code: int = 12064
    Msg: str = '文件生成失败，请稍后重试'


class ConversationImportSpaceNotFoundError(BaseErrorCode):
    Code: int = 12065
    Msg: str = '知识空间不存在或已删除'


class ConversationImportFolderNotFoundError(BaseErrorCode):
    Code: int = 12066
    Msg: str = '文件夹不存在或已删除'


class ConversationImportPermissionDeniedError(BaseErrorCode):
    Code: int = 12067
    Msg: str = '暂无权限导入到该知识空间'


class ConversationImportQuotaExceededError(BaseErrorCode):
    Code: int = 12068
    Msg: str = '知识空间配额已满'


class ConversationImportFailedError(BaseErrorCode):
    Code: int = 12069
    Msg: str = '导入失败，请稍后重试'


class ConversationImportFileTooLargeError(BaseErrorCode):
    # Per-file size limit (env.uploaded_files_maximum_size). Distinct from the
    # quota error (12068) so the frontend shows the size reason, not "空间已满".
    Code: int = 12070
    Msg: str = '文件大小超过上传限制'