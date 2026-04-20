from .base import BaseErrorCode


# Module code: 198 (LLM-tenant). 19801 covers both "Child Admin cannot
# edit Root-shared LLM" and "user is not any kind of admin" cases —
# both are 403-style write denials routed through the same UI toast.


class LLMModelSharedReadonlyError(BaseErrorCode):
    Code: int = 19801
    Msg: str = (
        'Root-shared LLM server/model is read-only for Child Admins; '
        'only global super admin may modify'
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
