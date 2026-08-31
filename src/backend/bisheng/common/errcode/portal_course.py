from bisheng.common.errcode.base import BaseErrorCode


class PortalCourseNotFoundError(BaseErrorCode):
    Code: int = 25001
    Msg: str = "课程不存在"


class PortalCourseVideoNotFoundError(BaseErrorCode):
    Code: int = 25002
    Msg: str = "课程视频不存在"


class PortalCourseNotPublishableError(BaseErrorCode):
    Code: int = 25003
    Msg: str = "课程至少需要一个已启用且来源有效的视频"


class PortalCourseMediaTooLargeError(BaseErrorCode):
    Code: int = 25004
    Msg: str = "视频文件不能超过 1 GiB"


class PortalCourseMediaUnsupportedError(BaseErrorCode):
    Code: int = 25005
    Msg: str = "视频容器或编码不受支持"


class PortalCourseUrlInvalidError(BaseErrorCode):
    Code: int = 25006
    Msg: str = "视频外链无效"


class PortalCourseSourceInvalidError(BaseErrorCode):
    Code: int = 25007
    Msg: str = "视频来源字段无效"


class PortalCourseProbeFailedError(BaseErrorCode):
    Code: int = 25008
    Msg: str = "无法识别视频媒体信息"


class PortalCourseSourceReplaceError(BaseErrorCode):
    Code: int = 25009
    Msg: str = "视频来源保存或替换失败"


class PortalCourseCatalogNotFoundError(BaseErrorCode):
    Code: int = 25010
    Msg: str = "课程目录不存在"


class PortalCourseCatalogParentInvalidError(BaseErrorCode):
    Code: int = 25011
    Msg: str = "课程目录父节点无效"


class PortalCourseCatalogInUseError(BaseErrorCode):
    Code: int = 25012
    Msg: str = "课程目录下仍有子目录或课程无法删除"


class PortalCourseCatalogNameDuplicateError(BaseErrorCode):
    Code: int = 25013
    Msg: str = "同一父目录下名称不能重复"


class PortalCourseCatalogImportError(BaseErrorCode):
    Code: int = 25014
    Msg: str = "课程目录导入失败"


class PortalCourseCatalogDepthExceededError(BaseErrorCode):
    Code: int = 25015
    Msg: str = "课程目录层级不能超过 8 级"


class PortalCourseVideoNotSupportedError(BaseErrorCode):
    Code: int = 25016
    Msg: str = "第三方课程不支持配置视频"


class PortalCourseExternalUrlRequiredError(BaseErrorCode):
    Code: int = 25017
    Msg: str = "第三方课程需要配置有效链接"


class PortalCourseImportError(BaseErrorCode):
    Code: int = 25018
    Msg: str = "第三方课程导入失败"
