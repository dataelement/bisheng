"""知识库文档纠错业务错误码, 模块号 184.

积分系统占用 182. 纠错不复用 182, 避免和调分, 规则, 公司根冲突.
"""

from bisheng.common.errcode.base import BaseErrorCode


class FileCorrectionContentRequiredError(BaseErrorCode):
    """纠错说明为空."""

    Code: int = 18400
    Msg: str = "请填写纠错说明"


class FileCorrectionContentTooLongError(BaseErrorCode):
    """纠错说明超过 500 字."""

    Code: int = 18401
    Msg: str = "纠错说明不能超过 500 字"


class FileCorrectionSelfSubmitError(BaseErrorCode):
    """上传人不能纠自己的文档."""

    Code: int = 18402
    Msg: str = "不能为自己上传的文档提交纠错"


class FileCorrectionUploaderUnavailableError(BaseErrorCode):
    """文档没有可登录的上传人."""

    Code: int = 18403
    Msg: str = "当前没有可处理的上传人"


class FileCorrectionSpaceNotAllowedError(BaseErrorCode):
    """个人库、收藏库或不支持的库层级."""

    Code: int = 18404
    Msg: str = "当前文档不能提交纠错"


class FileCorrectionViewDeniedError(BaseErrorCode):
    """不能查看该文档. 文案不写成文档不存在."""

    Code: int = 18405
    Msg: str = "无权查看该文档"


class FileCorrectionPendingExistsError(BaseErrorCode):
    """同一人同一文档已有待处理纠错."""

    Code: int = 18406
    Msg: str = "你已有一条审批中的纠错, 请在「申请」中查看"


class FileCorrectionContentForbiddenError(BaseErrorCode):
    """非反馈人、非冻结上传人读取正文. 不区分记录是否存在."""

    Code: int = 18407
    Msg: str = "无权查看纠错说明"


class FileCorrectionUpdateFileNotReadyError(BaseErrorCode):
    """新文件还不能成为当前主版本."""

    Code: int = 18409
    Msg: str = "新文件还在解析, 解析完成后再采纳并更新"


class FileCorrectionUpdateFileInvalidError(BaseErrorCode):
    """新文件不能收成这篇文档的新版本."""

    Code: int = 18410
    Msg: str = "请上传同一知识库中的另一份新文件"


class FileCorrectionUpdateInProgressError(BaseErrorCode):
    """采纳并更新的新文件还在解析, 不能做其他处理."""

    Code: int = 18411
    Msg: str = "新文件正在解析, 请等待完成后再处理"


class FileCorrectionUpdateRetryNotAllowedError(BaseErrorCode):
    """当前没有解析失败的更新文件, 不能重新解析."""

    Code: int = 18412
    Msg: str = "当前没有解析失败的更新文件, 无法重新解析"


class FileCorrectionUploaderOnlyError(BaseErrorCode):
    """只有冻结的上传人可以处理这条纠错."""

    Code: int = 18408
    Msg: str = "只有文档上传人可以处理这条纠错"
