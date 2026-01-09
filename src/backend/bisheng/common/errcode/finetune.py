from .base import BaseErrorCode


# finetuneTraining Module Return error code, business code101
class CreateFinetuneError(BaseErrorCode):
    Code: int = 10100
    Msg: str = 'Failed to create training task'


class TrainDataNoneError(BaseErrorCode):
    Code: int = 10101
    Msg: str = 'Individual Training Sets and Preset Training Sets Select at least one'


class NotFoundJobError(BaseErrorCode):
    Code: int = 10102
    Msg: str = 'Quest does not exist'


class JobStatusError(BaseErrorCode):
    Code: int = 10103
    Msg: str = 'Task status error'


class CancelJobError(BaseErrorCode):
    Code: int = 10104
    Msg: str = 'Task cancellation failed'


class DeleteJobError(BaseErrorCode):
    Code: int = 10105
    Msg: str = 'Task deletion failed'


class ExportJobError(BaseErrorCode):
    Code: int = 10106
    Msg: str = 'Task publishing failed'


class ChangeModelNameError(BaseErrorCode):
    Code: int = 10107
    Msg: str = 'Model name interface modification failed'


class UnExportJobError(BaseErrorCode):
    Code: int = 10108
    Msg: str = 'Failed to unpublish'


class InvalidExtraParamsError(BaseErrorCode):
    Code: int = 10109
    Msg: str = 'Invalid training parameters'


class ModelNameExistsError(BaseErrorCode):
    Code: int = 10110
    Msg: str = 'Model name already exists'


class TrainFileNotExistError(BaseErrorCode):
    Code: int = 10120
    Msg: str = 'Training file does not exist'


class GetGPUInfoError(BaseErrorCode):
    Code: int = 10125
    Msg: str = 'DapatkanGPUMessage failed'


class GetModelError(BaseErrorCode):
    Code: int = 10126
    Msg: str = 'Access to model list failed'
