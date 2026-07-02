from .base import BaseErrorCode


# Knowledge Space module error codes: 180xx
class SpaceNotFoundError(BaseErrorCode):
    Code: int = 18000
    Msg: str = 'Knowledge Space does not exist'


class SpaceLimitError(BaseErrorCode):
    Code: int = 18001
    Msg: str = 'You can create a maximum of 200 Knowledge Spaces'


class DepartmentKnowledgeSpaceExistsError(BaseErrorCode):
    Code: int = 18002
    Msg: str = 'Department knowledge space already exists'


class SpaceNameDuplicateError(BaseErrorCode):
    Code: int = 18003
    Msg: str = '知识空间名称已存在'


class SpaceFolderNotFoundError(BaseErrorCode):
    Code: int = 18010
    Msg: str = 'Folder does not exist'


class SpaceFolderDepthError(BaseErrorCode):
    Code: int = 18011
    Msg: str = 'Directory depth cannot exceed 10 levels'


class SpaceFolderDuplicateError(BaseErrorCode):
    Code: int = 18012
    Msg: str = 'Folder name already exists in this directory'


class SpaceFolderCircularMoveError(BaseErrorCode):
    Code: int = 18013
    Msg: str = 'Cannot move a folder into itself or its own subdirectory'


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


class SpaceFileEncodingDuplicateError(BaseErrorCode):
    Code: int = 18025
    Msg: str = '文件编码已存在'


class SpaceBusinessDomainCodeInvalidError(BaseErrorCode):
    Code: int = 18026
    Msg: str = 'Invalid business domain code'


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


class SpaceInvalidLevelError(BaseErrorCode):
    Code: int = 18041
    Msg: str = 'Invalid knowledge space level'


class SpaceInvalidScopeOwnerError(BaseErrorCode):
    Code: int = 18042
    Msg: str = 'Invalid knowledge space owner'


class SpaceCreatePublicDeniedError(BaseErrorCode):
    Code: int = 18043
    Msg: str = 'Only super admin can create public knowledge spaces'


class SpaceCreateDepartmentDeniedError(BaseErrorCode):
    Code: int = 18044
    Msg: str = 'Only super admin can create department knowledge spaces'


class SpaceCreateTeamDeniedError(BaseErrorCode):
    Code: int = 18045
    Msg: str = 'You can only create team knowledge spaces for your user groups'


class SpaceAuthorizeSubjectDeniedError(BaseErrorCode):
    Code: int = 18046
    Msg: str = 'This subject type cannot be authorized for the knowledge space level'


class SpaceAuthorizeScopeDeniedError(BaseErrorCode):
    Code: int = 18047
    Msg: str = 'The authorization target is outside the allowed knowledge space scope'


class SpaceTenantMismatchError(BaseErrorCode):
    Code: int = 18048
    Msg: str = '当前租户与知识空间归属租户不一致，暂不支持该操作，请切换到知识空间所属租户后重试'


# —— TAG
class SpaceTagExistsError(BaseErrorCode):
    Code: int = 18050
    Msg: str = 'Tag already exists in this space'


# —— Version management
class VersionManagementDisabledError(BaseErrorCode):
    Code: int = 18060
    Msg: str = 'Version management is disabled.'


class VersionLinkFileNotReadyError(BaseErrorCode):
    Code: int = 18061
    Msg: str = 'File must finish parsing before version management.'


class VersionLinkTargetUnavailableError(BaseErrorCode):
    Code: int = 18062
    Msg: str = 'Target document is unavailable.'


class VersionLinkSourceMultiVersionError(BaseErrorCode):
    Code: int = 18063
    Msg: str = 'Source document already has multiple versions and cannot be linked to another document.'


class VersionLinkSourceFileMissingError(BaseErrorCode):
    Code: int = 18064
    Msg: str = 'Source file no longer exists or has been deleted.'


# F027: cursor-based pagination — cursor parsing/version/context/key-length failed
class KnowledgeSpaceInvalidCursorError(BaseErrorCode):
    Code: int = 18070
    Msg: str = 'Invalid pagination cursor'


class FavoriteSpaceProtectedError(BaseErrorCode):
    Code: int = 18071
    Msg: str = '『我的收藏』为系统知识库，不可删除或修改'


class SpaceNameSensitiveWordError(BaseErrorCode):
    Code: int = 18072
    Msg: str = '名称包含敏感词，请修改后重试'


class SpaceFileNameSensitiveWordError(BaseErrorCode):
    Code: int = 18073
    Msg: str = '文件名包含敏感词，请修改后重试'


class SpaceFileContentSensitiveWordError(BaseErrorCode):
    Code: int = 18074
    Msg: str = '文件内容包含敏感词，请修改后重试'
