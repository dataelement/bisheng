from __future__ import annotations

from bisheng.common.errcode import BaseErrorCode


class KnowledgeMigrationError(BaseErrorCode):
    HttpStatus: int = 400

    @property
    def http_status(self) -> int:
        return self.HttpStatus


class KnowledgeMigrationInvalidRequestError(KnowledgeMigrationError):
    Code = 18900
    Msg = "knowledge_migration_invalid_request"
    HttpStatus = 400


class KnowledgeMigrationNotFoundError(KnowledgeMigrationError):
    Code = 18901
    Msg = "knowledge_migration_not_found"
    HttpStatus = 404


class KnowledgeMigrationStateConflictError(KnowledgeMigrationError):
    Code = 18902
    Msg = "knowledge_migration_state_conflict"
    HttpStatus = 409


class KnowledgeMigrationCandidateInvalidError(KnowledgeMigrationError):
    Code = 18903
    Msg = "knowledge_migration_candidate_invalid"
    HttpStatus = 400


class KnowledgeMigrationDispatchError(KnowledgeMigrationError):
    Code = 18904
    Msg = "knowledge_migration_dispatch_failed"
    HttpStatus = 503


# The portal renders `status_message` verbatim — it has no mapping for the
# key-style messages above — so these three carry text a user can act on.
class MigrationPreserveLinkSourceLevelMixedError(KnowledgeMigrationError):
    Code = 18905
    Msg = "保留原位链接时，来源知识库必须属于同一层级，请分批迁移"  # noqa: RUF001
    HttpStatus = 400


class MigrationPreserveLinkPublicSourceError(KnowledgeMigrationError):
    Code = 18906
    Msg = "公共知识库没有上一级，无法在保留原位链接的模式下迁移"  # noqa: RUF001
    HttpStatus = 400


class MigrationPreserveLinkTargetLevelError(KnowledgeMigrationError):
    Code = 18907
    Msg = "保留原位链接时，目标知识库只能是来源的上一级"  # noqa: RUF001
    HttpStatus = 400
