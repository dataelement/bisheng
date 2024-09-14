from bisheng.api.errcode.base import BaseErrorCode


# 技能服务相关的返回错误码，功能模块代码：105
class NotFoundVersionError(BaseErrorCode):
    Code: int = 10500
    Msg: str = '未找到技能版本信息'


class CurVersionDelError(BaseErrorCode):
    Code: int = 10501
    Msg: str = '当前正在使用版本无法删除'


class VersionNameExistsError(BaseErrorCode):
    Code: int = 10502
    Msg: str = '版本名已存在'


class NotFoundFlowError(BaseErrorCode):
    Code: int = 10520
    Msg: str = '技能不存在'


class FlowOnlineEditError(BaseErrorCode):
    Code: int = 10521
    Msg: str = '技能已上线，不可编辑'

