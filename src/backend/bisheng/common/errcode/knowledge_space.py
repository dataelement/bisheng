from .base import BaseErrorCode


# Knowledge Space module error codes: 180xx
class SpaceNotFoundError(BaseErrorCode):
    Code: int = 18000
    Msg: str = 'Knowledge Space does not exist'


class SpaceLimitError(BaseErrorCode):
    Code: int = 18001
    Msg: str = 'You can create a maximum of 30 Knowledge Spaces'


class SpaceFolderNotFoundError(BaseErrorCode):
    Code: int = 18010
    Msg: str = 'Folder does not exist'


class SpaceFolderDepthError(BaseErrorCode):
    Code: int = 18011
    Msg: str = 'Directory depth cannot exceed 10 levels'


class SpaceFolderDuplicateError(BaseErrorCode):
    Code: int = 18012
    Msg: str = 'Folder name already exists in this directory'


class SpaceFileNotFoundError(BaseErrorCode):
    Code: int = 18020
    Msg: str = 'File does not exist'


class SpaceFileDuplicateError(BaseErrorCode):
    Code: int = 18021
    Msg: str = 'A file with the same name or content already exists in this space'


class SpaceFileExtensionError(BaseErrorCode):
    Code: int = 18022
    Msg: str = 'File extension cannot be changed during rename'


class SpaceFileNameDuplicateError(BaseErrorCode):
    Code: int = 18023
    Msg: str = 'File name already exists in this space'


class SpaceFileSizeLimitError(BaseErrorCode):
    Code: int = 18024
    Msg: str = 'File size limit exceeded'


# ── Subscribe ────────────────────────────────────────────────────────────────

class SpaceSubscribePrivateError(BaseErrorCode):
    Code: int = 18030
    Msg: str = 'Private knowledge spaces cannot be subscribed to'


class SpaceAlreadySubscribedError(BaseErrorCode):
    Code: int = 18031
    Msg: str = 'You have already subscribed to or applied for this knowledge space'


class SpaceSubscribeLimitError(BaseErrorCode):
    Code: int = 18032
    Msg: str = 'You can subscribe to a maximum of 50 knowledge spaces'


# ── Permission ────────────────────────────────────────────────────────────────

class SpacePermissionDeniedError(BaseErrorCode):
    Code: int = 18040
    Msg: str = 'Permission denied: only the creator or admin can perform this operation'


# —— TAG
class SpaceTagExistsError(BaseErrorCode):
    Code: int = 18050
    Msg: str = 'Tag already exists in this space'
