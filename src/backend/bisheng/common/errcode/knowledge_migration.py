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
