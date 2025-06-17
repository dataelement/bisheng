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


class FlowNameExistsError(BaseErrorCode):
    Code: int = 10503
    Msg: str = '技能名重复'


class NotFoundFlowError(BaseErrorCode):
    Code: int = 10520
    Msg: str = '技能不存在'


class FlowOnlineEditError(BaseErrorCode):
    Code: int = 10521
    Msg: str = '技能已上线，不可编辑'


class WorkFlowOnlineEditError(BaseErrorCode):
    Code: int = 10525
    Msg: str = '工作流已上线，不可编辑'


class WorkFlowInitError(BaseErrorCode):
    Code: int = 10526
    Msg: str = '工作流初始化失败'


class WorkFlowWaitUserTimeoutError(BaseErrorCode):
    Code: int = 10527
    Msg: str = '工作流等待用户输入超时'


class WorkFlowNodeRunMaxTimesError(BaseErrorCode):
    Code: int = 10528
    Msg: str = '节点执行超过最大次数'


class WorkflowNameExistsError(BaseErrorCode):
    Code: int = 10529
    Msg: str = '应用名称重复'


class FlowTemplateNameError(BaseErrorCode):
    Code: int = 10530
    Msg: str = '模板名称已存在'


class WorkFlowNodeUpdateError(BaseErrorCode):
    Code: int = 10531
    Msg: str = '<节点名称>功能已升级，需删除后重新拖入。'


class WorkFlowVersionUpdateError(BaseErrorCode):
    Code: int = 10532
    Msg: str = '工作流版本已升级，请联系创建者重新编排'


class WorkFlowTaskBusyError(BaseErrorCode):
    Code: int = 10540
    Msg: str = '服务器线程数已满，请稍候再试'
