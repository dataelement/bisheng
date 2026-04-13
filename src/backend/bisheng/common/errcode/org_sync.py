from .base import BaseErrorCode


# Org sync module error codes, module code: 220
class OrgSyncConfigNotFoundError(BaseErrorCode):
    Code: int = 22000
    Msg: str = 'Org sync config not found'


class OrgSyncConfigDuplicateError(BaseErrorCode):
    Code: int = 22001
    Msg: str = 'Org sync config with same provider and name already exists'


class OrgSyncAuthFailedError(BaseErrorCode):
    Code: int = 22002
    Msg: str = 'Provider authentication failed'


class OrgSyncAlreadyRunningError(BaseErrorCode):
    Code: int = 22003
    Msg: str = 'Sync is already running for this config'


class OrgSyncProviderError(BaseErrorCode):
    Code: int = 22004
    Msg: str = 'Provider error'


class OrgSyncPermissionDeniedError(BaseErrorCode):
    Code: int = 22005
    Msg: str = 'No permission for org sync operation'


class OrgSyncInvalidConfigError(BaseErrorCode):
    Code: int = 22006
    Msg: str = 'Invalid org sync config'


class OrgSyncFetchError(BaseErrorCode):
    Code: int = 22007
    Msg: str = 'Failed to fetch data from provider'


class OrgSyncReconcileError(BaseErrorCode):
    Code: int = 22008
    Msg: str = 'Unrecoverable error during reconciliation'


class OrgSyncConfigDisabledError(BaseErrorCode):
    Code: int = 22009
    Msg: str = 'Org sync config is disabled'
