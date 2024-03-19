from bisheng.api.errcode.base import BaseErrorCode


# finetune训练模块 返回错误码，业务代码101
class CreateFinetuneError(BaseErrorCode):
    Code: int = 10100
    Msg: str = '创建训练任务失败'


class TrainDataNoneError(BaseErrorCode):
    Code: int = 10101
    Msg: str = '个人训练集和预置训练集最少选择一个'


class NotFoundJobError(BaseErrorCode):
    Code: int = 10102
    Msg: str = '任务不存在'


class JobStatusError(BaseErrorCode):
    Code: int = 10103
    Msg: str = '任务状态错误'


class CancelJobError(BaseErrorCode):
    Code: int = 10104
    Msg: str = '任务取消失败'


class DeleteJobError(BaseErrorCode):
    Code: int = 10105
    Msg: str = '任务删除失败'


class ExportJobError(BaseErrorCode):
    Code: int = 10106
    Msg: str = '任务发布失败'


class ChangeModelNameError(BaseErrorCode):
    Code: int = 10107
    Msg: str = '模型名接口修改失败'


class UnExportJobError(BaseErrorCode):
    Code: int = 10108
    Msg: str = '取消发布失败'


class InvalidExtraParamsError(BaseErrorCode):
    Code: int = 10109
    Msg: str = '无效的训练参数'


class ModelNameExistsError(BaseErrorCode):
    Code: int = 10110
    Msg: str = '模型名已存在'


class TrainFileNotExistError(BaseErrorCode):
    Code: int = 10120
    Msg: str = '训练文件不存在'


class GetGPUInfoError(BaseErrorCode):
    Code: int = 10125
    Msg: str = '获取GPU信息失败'
