"""Shared response translation for permission endpoints."""

from __future__ import annotations

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.common.schemas.api import UnifiedResponseModel


def permission_error_response(error: BaseErrorCode) -> UnifiedResponseModel:
    """Preserve structured business codes in the unified HTTP envelope."""

    if isinstance(error, PermissionInvalidResourceError):
        return PermissionInvalidResourceError.return_resp()
    return error.return_resp_instance(data=None)
