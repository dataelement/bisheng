"""User-owned nickname, profile version and audit are committed together."""

from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.user import NicknameValidationError, UserForbiddenError
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter, get_current_tenant_id
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.audit_log import AuditLog, EventType, ObjectType, SystemId
from bisheng.database.models.org_snapshot import stamp_audit_logs
from bisheng.database.models.tenant import UserTenant
from bisheng.database.models.user_group import UserGroup
from bisheng.user.domain.models.user import User
from bisheng.user.domain.repositories.dsh_profile import UserDshProfileRepository
from bisheng.user.domain.rules.identity import validate_nickname_change
from bisheng.user.domain.schemas.nickname import NicknameActor


class NicknameRepository:
    session_scope = staticmethod(get_sync_db_session)
    stamp = staticmethod(stamp_audit_logs)

    @classmethod
    def rename(
        cls,
        user_id: int,
        proposed: str,
        actor: NicknameActor,
        *,
        profile_enabled: bool = False,
    ) -> User:
        try:
            with cls.session_scope() as own:
                user = cls._rename(own, user_id, proposed, actor, profile_enabled)
                own.commit()
                own.refresh(user)
                own.expunge(user)
                return user
        except NicknameValidationError as error:
            cls.record_failure(user_id, proposed, actor, reason=error.message)
            raise

    @classmethod
    def _rename(
        cls, session: Session, user_id: int, proposed: str, actor: NicknameActor, profile_enabled: bool
    ) -> User:
        user = session.exec(select(User).where(User.user_id == user_id).with_for_update()).one_or_none()
        if user is None:
            raise NotFoundError()
        if user.delete != 0:
            raise UserForbiddenError()
        before = user.user_name
        if not validate_nickname_change(before, proposed):
            return user
        operator = session.get(User, actor.user_id)
        if operator is None:
            raise NotFoundError()
        operator_name = operator.user_name
        if user.account_rule_version == 0 and user.legacy_sso_name is None:
            user.legacy_sso_name = before
        user.user_name, user.nickname_customized = proposed, True
        session.add(user)
        if profile_enabled:
            UserDshProfileRepository.bump_snapshot(session, user)
        cls._audit(session, user, actor, before, proposed, "success", operator_name=operator_name)
        session.flush()
        return user

    @classmethod
    def record_failure(cls, user_id: int, proposed: str, actor: NicknameActor, *, reason: str) -> None:
        try:
            cls._record_failure(user_id, proposed, actor, reason=reason)
        except SQLAlchemyError:
            # The attempt is already rejected without a nickname write. Keep
            # its original error if only the failure-audit store is unavailable.
            logger.exception("Could not persist rejected nickname attempt actor={} target={}", actor.user_id, user_id)

    @classmethod
    def _record_failure(cls, user_id: int, proposed: str, actor: NicknameActor, *, reason: str) -> None:
        with cls.session_scope() as session:
            user = session.get(User, user_id)
            operator = session.get(User, actor.user_id)
            if user is None or operator is None:
                logger.warning(
                    "Nickname failure audit target no longer exists actor={} target={}", actor.user_id, user_id
                )
                return
            cls._audit(
                session,
                user,
                actor,
                user.user_name,
                proposed,
                "failure",
                reason=reason,
                operator_name=operator.user_name,
            )
            session.commit()

    @classmethod
    def _audit(
        cls,
        session: Session,
        user: User,
        actor: NicknameActor,
        before: str,
        after: str,
        result: str,
        *,
        operator_name: str,
        reason: str | None = None,
    ) -> None:
        # The caller has already verified the target. These instance-level
        # identity snapshots must not disappear under the editor's tenant view.
        with bypass_tenant_filter():
            tenant_id = session.exec(
                select(UserTenant.tenant_id).where(
                    UserTenant.user_id == user.user_id,
                    UserTenant.is_active == 1,
                )
            ).first()
            group_ids = list(session.exec(select(UserGroup.group_id).where(UserGroup.user_id == actor.user_id)).all())
        row = AuditLog(
            operator_id=actor.user_id,
            operator_name=operator_name,
            group_ids=group_ids,
            system_id=SystemId.SYSTEM.value,
            event_type=EventType.UPDATE_USER.value,
            object_type=ObjectType.USER_CONF.value,
            object_id=str(user.user_id),
            object_name=user.user_name,
            target_type="user",
            target_id=str(user.user_id),
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
            operator_tenant_id=get_current_tenant_id() or actor.tenant_id,
            ip_address=actor.ip_address,
            note="Nickname updated" if result == "success" else "Nickname update failed",
            reason=reason,
            audit_metadata={"field": "user_name", "before": before, "after": after, "result": result},
        )
        cls.stamp([row])
        session.add(row)
