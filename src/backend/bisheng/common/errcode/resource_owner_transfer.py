from .base import BaseErrorCode


# F018 resource-owner-transfer module, code: 196
# Assigned by F018 spec §9 (v2.5.1).


class ResourceTransferPermissionError(BaseErrorCode):
    Code: int = 19601
    Msg: str = 'Only the resource owner or a tenant admin may transfer ownership'


class ResourceTransferBatchLimitError(BaseErrorCode):
    Code: int = 19602
    Msg: str = 'Transfer batch exceeds 500 items; split into smaller requests'


class ResourceTransferReceiverOutOfTenantError(BaseErrorCode):
    # AC-08 / INV-T10: to_user leaf tenant must lie in {tenant_id, Root}.
    # AC-08d note: when tenant_id == Root and to_user leaf is a Child,
    # callers should use F011 POST /api/v1/tenants/{child_id}/resources/migrate-from-root
    # to sink tenant_id first, then transfer within the Child.
    Code: int = 19603
    Msg: str = 'to_user leaf tenant must lie within the resource tenant visible set'


class ResourceTransferUnsupportedTypeError(BaseErrorCode):
    Code: int = 19604
    Msg: str = 'Unsupported resource type for transfer'


class ResourceTransferTxFailedError(BaseErrorCode):
    Code: int = 19605
    Msg: str = 'MySQL/OpenFGA transaction failed; all changes rolled back'


class ResourceTransferSelfError(BaseErrorCode):
    Code: int = 19606
    Msg: str = 'from_user_id and to_user_id must be different'
