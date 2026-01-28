from bisheng.common.errcode.base import BaseErrorCode


class SopFileError(BaseErrorCode):
    Code: int = 11010
    Msg: str = 'SOPFile format does not meet requirements'


class SopShowcaseError(BaseErrorCode):
    Code: int = 11011
    Msg: str = 'SOPFailed to set featured case'


class FileUploadError(BaseErrorCode):
    __doc__ = 'LinsightFailed to upload documents'
    Code: int = 11020
    Msg: str = 'Upload Failed'


# Your Idea has run out of uses, please use the new invite code to activate the Idea feature
class LinsightUseUpError(BaseErrorCode):
    Code: int = 11030
    Msg: str = 'Your Idea has run out of uses, please use the new invite code to activate the Idea feature'


# Failed to submit Idea User Issue
class LinsightQuestionError(BaseErrorCode):
    Code: int = 11040
    Msg: str = 'Failed to submit Idea User Issue'


# Please contact the administrator to check the status of the workbench vector retrieval model
class LinsightVectorModelError(BaseErrorCode):
    Code: int = 11050
    Msg: str = 'Please contact the administrator to check the status of the workbench vector retrieval model'


# Instruction manual retrieval failed, vector retrieval and keyword retrieval are not available
class LinsightDocSearchError(BaseErrorCode):
    Code: int = 11060
    Msg: str = 'Instruction manual retrieval failed, vector retrieval and keyword retrieval are not available'


# Guidebook retrieval failed
class LinsightDocNotFoundError(BaseErrorCode):
    Code: int = 11070
    Msg: str = 'Guidebook retrieval failed'


# Failed to initialize the Inspiration Workbench tool
class LinsightToolInitError(BaseErrorCode):
    Code: int = 11080
    Msg: str = 'Failed to initialize the Inspiration Workbench tool'


# InspirationBisheng LLMRelated Errors
class LinsightBishengLLMError(BaseErrorCode):
    Code: int = 11090
    Msg: str = 'InspirationBisheng LLMRelated Errors'


# BuatSOPContent failed
class LinsightGenerateSopError(BaseErrorCode):
    Code: int = 11100
    Msg: str = 'BuatSOPContent failed'


# ChangeSOPContent failed
class LinsightModifySopError(BaseErrorCode):
    Code: int = 11110
    Msg: str = 'ChangeSOPContent failed'


# The Inspiration session version has been completed or is being executed and cannot be executed again
class LinsightSessionVersionRunningError(BaseErrorCode):
    Code: int = 11120
    Msg: str = 'The Inspiration session version has been completed or is being executed and cannot be executed again'


# Failed to start the Ideas task
class LinsightStartTaskError(BaseErrorCode):
    Code: int = 11130
    Msg: str = 'Failed to start the Ideas task'


# Failed to get Ideas queue queue status
class LinsightQueueStatusError(BaseErrorCode):
    Code: int = 11140
    Msg: str = 'Failed to get Ideas queue queue status'


# Failed to add instruction manual, failed to add data for vector store
class LinsightAddSopError(BaseErrorCode):
    Code: int = 11150
    Msg: str = 'Failed to add instruction manual, failed to add data for vector store'


# Failed to update the instruction manual, vector store update data failed
class LinsightUpdateSopError(BaseErrorCode):
    Code: int = 11160
    Msg: str = 'Failed to update the instruction manual, vector store update data failed'


# Failed to delete instruction manual, failed to delete data in vector store
class LinsightDeleteSopError(BaseErrorCode):
    Code: int = 11170
    Msg: str = 'Failed to delete instruction manual, failed to delete data in vector store'


class SopContentOverLimitError(BaseErrorCode):
    Code: int = 11171
    Msg: str = '{sop_name}The content is too long'


class InviteCodeInvalidError(BaseErrorCode):
    Code: int = 11180
    Msg: str = 'The invite code you entered is invalid'


class InviteCodeBindError(BaseErrorCode):
    Code: int = 11190
    Msg: str = 'Additional invite codes bound'
