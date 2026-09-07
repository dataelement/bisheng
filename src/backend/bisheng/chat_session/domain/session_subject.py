"""Typed ownership rules shared by every conversation adapter."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from loguru import logger
from sqlalchemy import Select
from sqlmodel import col

from bisheng.database.models.session import MessageSession

SessionSubjectType = Literal["user", "service_account", "public_v3"]


@dataclass(frozen=True, slots=True)
class SessionSubject:
    """The caller identity used to stamp and retrieve message sessions."""

    tenant_id: int
    subject_type: SessionSubjectType
    subject_id: int | None
    compatibility_user_id: int
    external_user_id: str | None = None
    resource_id: str | None = None

    @classmethod
    def natural_person(cls, *, tenant_id: int, user_id: int) -> SessionSubject:
        return cls(
            tenant_id=tenant_id,
            subject_type="user",
            subject_id=user_id,
            compatibility_user_id=user_id,
        )

    @classmethod
    def service_account(
        cls,
        *,
        tenant_id: int,
        service_account_id: int,
        resource_owner_user_id: int,
        external_user_id: str | None,
    ) -> SessionSubject:
        if external_user_id is None:
            logger.warning(
                "Open API service account {} opened a session without X-End-User; "
                "the session is isolated only at service-account granularity",
                service_account_id,
            )
        return cls(
            tenant_id=tenant_id,
            subject_type="service_account",
            subject_id=service_account_id,
            compatibility_user_id=resource_owner_user_id,
            external_user_id=external_user_id,
        )

    @classmethod
    def public_v3(
        cls,
        *,
        tenant_id: int,
        operator_user_id: int,
        resource_id: str,
    ) -> SessionSubject:
        return cls(
            tenant_id=tenant_id,
            subject_type="public_v3",
            subject_id=None,
            compatibility_user_id=operator_user_id,
            resource_id=resource_id,
        )

    def stamp(self, session: MessageSession) -> MessageSession:
        """Apply the durable ownership projection to a newly created row."""

        session.tenant_id = self.tenant_id
        session.user_id = self.compatibility_user_id
        if self.subject_type == "service_account":
            session.api_subject_type = self.subject_type
            session.api_subject_id = self.subject_id
            session.external_user_id = self.external_user_id
        elif self.subject_type == "public_v3":
            session.api_subject_type = self.subject_type
            session.api_subject_id = None
            session.external_user_id = None
            if self.resource_id is not None:
                session.flow_id = self.resource_id
        else:
            session.api_subject_type = None
            session.api_subject_id = None
            session.external_user_id = None
        return session

    @property
    def storage_partition(self) -> str:
        """Stable, path-safe attachment partition matching session isolation."""

        if self.subject_type == "service_account":
            external = sha256((self.external_user_id or "").encode("utf-8")).hexdigest()[:16]
            return f"service-account/{self.subject_id}/{external}"
        if self.subject_type == "public_v3":
            resource = sha256((self.resource_id or "").encode("utf-8")).hexdigest()[:16]
            return f"public-v3/{resource}"
        return str(self.subject_id)

    def matches(self, session: MessageSession) -> bool:
        if session.is_delete or session.tenant_id != self.tenant_id:
            return False
        if self.subject_type == "service_account":
            return (
                session.api_subject_type == "service_account"
                and session.api_subject_id == self.subject_id
                and session.external_user_id == self.external_user_id
            )
        if self.subject_type == "public_v3":
            return (
                session.api_subject_type == "public_v3"
                and self.resource_id is not None
                and session.flow_id == self.resource_id
            )
        return session.api_subject_type is None and session.user_id == self.subject_id

    def filter_statement(self, statement: Select) -> Select:
        """Apply the same matcher to a SQL statement before pagination."""

        statement = statement.where(
            MessageSession.tenant_id == self.tenant_id,
            col(MessageSession.is_delete).is_(False),
        )
        if self.subject_type == "service_account":
            statement = statement.where(
                MessageSession.api_subject_type == "service_account",
                MessageSession.api_subject_id == self.subject_id,
            )
            if self.external_user_id is None:
                return statement.where(col(MessageSession.external_user_id).is_(None))
            return statement.where(MessageSession.external_user_id == self.external_user_id)
        if self.subject_type == "public_v3":
            return statement.where(
                MessageSession.api_subject_type == "public_v3",
                MessageSession.flow_id == self.resource_id,
            )
        return statement.where(
            col(MessageSession.api_subject_type).is_(None),
            MessageSession.user_id == self.subject_id,
        )


__all__ = ["SessionSubject", "SessionSubjectType"]
