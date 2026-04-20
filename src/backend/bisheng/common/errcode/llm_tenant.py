from .base import BaseErrorCode


# LLM-tenant module error codes, module code: 198
# Assigned by F020-llm-tenant-isolation (v2.5.1). Covers LLM Server/Model
# CRUD under the Tenant-tree model (INV-T15, INV-T16):
#   - Child Admins may freely CRUD their own tenant's LLMs but Root-shared
#     LLMs are read-only for them (19801).
#   - Cross-tenant model references (knowledge / workflow / assistant) that
#     fall outside the caller's visible set raise 19802.
#   - System-level config endpoints (workbench / knowledge / assistant /
#     evaluation default models) remain super-admin-only (19803).
#   - Optional endpoint whitelist blocks non-compliant LLM registrations
#     when configured (19804; default empty = no restriction).


class LLMModelSharedReadonlyError(BaseErrorCode):
    Code: int = 19801
    Msg: str = (
        'Root-shared LLM server/model is read-only for Child Admins '
        '(INV-T15); only global super admin may modify'
    )


class LLMModelNotAccessibleError(BaseErrorCode):
    Code: int = 19802
    Msg: str = (
        'Target LLM model is not in the current visible tenant set '
        '(cross-tenant reference or deleted)'
    )


class LLMSystemConfigForbiddenError(BaseErrorCode):
    Code: int = 19803
    Msg: str = (
        'System-level LLM configuration (workbench / knowledge / assistant '
        '/ evaluation defaults) is restricted to the global super admin'
    )


class LLMEndpointNotWhitelistedError(BaseErrorCode):
    Code: int = 19804
    Msg: str = (
        'LLM server endpoint does not match any prefix in '
        'settings.llm.endpoint_whitelist'
    )
