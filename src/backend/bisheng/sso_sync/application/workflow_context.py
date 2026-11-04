"""延迟任务的追踪因果信息。没有构造认证主体或恢复业务授权的能力。"""

from contextlib import contextmanager

from loguru import logger
from pydantic import ValidationError

from bisheng.common.errcode.sso_sync import KunlianTrustRejectedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.sso_sync.domain.schemas.kunlian import KunlianWorkflowCause


@contextmanager
def workflow_causal_scope(headers, *, user_id: int, execution_snapshot):
    if not headers or "kunlian_causal_context" not in headers:
        yield None
        return
    try:
        cause = KunlianWorkflowCause.model_validate(headers["kunlian_causal_context"])
    except ValidationError:
        raise KunlianTrustRejectedError() from None
    if (
        execution_snapshot is not None
        or type(user_id) is not int
        or cause.user_id != user_id
        or type(headers.get("tenant_id")) is not int
        or cause.tenant_id != headers["tenant_id"]
        or cause.tenant_id != get_current_tenant_id()
    ):
        raise KunlianTrustRejectedError()
    logger.debug(
        "Kunlian workflow cause request_id={} user_id={} tenant_id={} session={}",
        cause.request_id,
        cause.user_id,
        cause.tenant_id,
        cause.session_hash[:12],
    )
    yield cause
