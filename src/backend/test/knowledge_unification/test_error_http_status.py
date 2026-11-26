"""New domain errors must retain their intended transport status on v2."""

import pytest

from bisheng.common.errcode import knowledge
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.open_api.domain.http_status import open_api_http_status


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ReferenceCoverageNotReadyError", 503),
        ("ResourceReferenceConflictError", 409),
        ("ResourceReferenceInvalidError", 409),
        ("KnowledgeProcessingObsoleteError", 409),
        ("KnowledgeOperationPlanConflictError", 409),
        ("KnowledgeProcessingConflictError", 409),
        ("KnowledgeProcessingSettingsConflictError", 409),
        ("KnowledgeProcessingJobNotFoundError", 404),
        ("KnowledgeProcessingJobNotRetryableError", 409),
        ("KnowledgeIdempotencyConflictError", 409),
        ("KnowledgeOperationConfirmationRequiredError", 409),
        ("KnowledgeOperationPlanChangedError", 409),
        ("KnowledgeOperationPlanExpiredError", 409),
    ],
)
def test_f118_status_for_domain_and_http_exception(name, expected):
    error_type = getattr(knowledge, name)
    assert open_api_http_status(error_type()) == expected
    assert open_api_http_status(error_type.http_exception()) == expected


def test_existing_error_mapping_remains_unchanged():
    assert open_api_http_status(PermissionDeniedError()) == 403
    assert open_api_http_status(knowledge.BackendProcessingError()) == 400
