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
