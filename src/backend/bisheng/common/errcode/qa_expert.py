# ruff: noqa: RUF001, RUF002
"""专家问答模块业务错误码（183xx）。"""

from bisheng.common.errcode.base import BaseErrorCode


class QaExpertQuestionAccessDeniedError(BaseErrorCode):
    """当前用户不可见该问题（定向隔离 / 未登录等）。"""

    Code, Msg = 18301, "无权查看该问题"


class QaExpertAnswerNotAllowedError(BaseErrorCode):
    """当前用户不具备回答资格。"""

    Code, Msg = 18302, "当前无权回答该问题"


class QaExpertContentLockedError(BaseErrorCode):
    """首答后正文/类型/邀请已锁定。"""

    Code, Msg = 18303, "问题内容已锁定，不可编辑"


class QaExpertAdoptLimitError(BaseErrorCode):
    """同题采纳槽位已满（最多 3 条）。"""

    Code, Msg = 18304, "每个问题最多采纳 3 个回答"


class QaExpertPublishNotAllowedError(BaseErrorCode):
    """不可发起或审批转公开。"""

    Code, Msg = 18305, "当前无权发起或审批转公开"


class QaExpertPublishConflictError(BaseErrorCode):
    """已有进行中的转公开申请。"""

    Code, Msg = 18306, "已有进行中的转公开申请"


class QaExpertAdminRequiredError(BaseErrorCode):
    """需要专家库管理员（Portal isPortalAdmin），不是平台超管门闸。"""

    Code, Msg = 18307, "需要专家库管理员权限"


class QaExpertDisabledError(BaseErrorCode):
    """专家已停用，不可新回答。"""

    Code, Msg = 18308, "专家已停用"


class QaExpertCommentNotAllowedError(BaseErrorCode):
    """定向题须先提交有效回答才能评论（追问除外）。"""

    Code, Msg = 18309, "定向题须先提交有效回答后才能评论"


class QaExpertPublishDurationInvalidError(BaseErrorCode):
    """转公开有效期仅允许 1/3/7 天。"""

    Code, Msg = 18310, "转公开有效期不合法"


class QaExpertAnonymousRevealRequiredError(BaseErrorCode):
    """定向且勾选匿名时，必须预选转公开后是否公开姓名。"""

    Code, Msg = 18311, "定向匿名须选择转公开后是否公开姓名"


class QaExpertAnswerDeleteNotAllowedError(BaseErrorCode):
    """作者删答：已采纳，或存在有效转公开申请。"""

    Code, Msg = 18312, "当前不可删除该回答"
