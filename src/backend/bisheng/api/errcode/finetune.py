from bisheng.api.errcode.base import BaseErrorCode


# finetune训练模块 返回错误码，业务代码101
class CreateFinetuneError(BaseErrorCode):
    code: int = 10100
    msg: str = '创建训练任务失败'


class TrainDataNoneError(BaseErrorCode):
    code: int = 10101
    msg: str = '个人训练集和预置训练集最少选择一个'


class NotFoundJobError(BaseErrorCode):
    code: int = 10102
    msg: str = '任务不存在'


class JobStatusError(BaseErrorCode):
    code: int = 10103
    msg: str = '任务状态错误'


class CancelJobError(BaseErrorCode):
    code: int = 10104
    msg: str = '任务取消失败'


class DeleteJobError(BaseErrorCode):
    code: int = 10105
    msg: str = '任务删除失败'


class ExportJobError(BaseErrorCode):
    code: int = 10106
    msg: str = '任务发布失败'


class ChangeModelNameError(BaseErrorCode):
    code: int = 10107
    msg: str = '模型名接口修改失败'


class TrainFileNotExistError(BaseErrorCode):
    code: int = 10120
    msg: str = '训练文件不存在'
