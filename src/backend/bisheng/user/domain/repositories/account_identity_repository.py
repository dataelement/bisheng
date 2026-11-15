"""Portable instance-wide identity transactions; no HTTP or remote work."""

from contextlib import contextmanager

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from bisheng.common.errcode.user import AccountAlreadyExistsError
from bisheng.core.database import get_sync_db_session
from bisheng.database.constants import AdminRole, DefaultRole
from bisheng.database.models.user_group import UserGroup
from bisheng.database.models.user_role import UserRole
from bisheng.user.domain.models.account_identity import UserAccountReservation, UserIdentityWriteGuard
from bisheng.user.domain.models.user import User
from bisheng.user.domain.rules.identity import account_key, validate_account, validate_nickname


class AccountIdentityRepository:
    session_scope = staticmethod(get_sync_db_session)

    @classmethod
    def ensure_guard(cls) -> None:
        # Seed in a separate short transaction: a missing-row FOR UPDATE may
        # hold conflicting gap locks on MySQL when two first writers arrive.
        try:
            with cls.session_scope() as session:
                if session.get(UserIdentityWriteGuard, 1) is None:
                    session.add(UserIdentityWriteGuard(id=1))
                    session.commit()
        except IntegrityError:
            with cls.session_scope() as session:
                if session.get(UserIdentityWriteGuard, 1) is None:
                    raise
            logger.debug("Identity write guard was initialized by another writer")

    @classmethod
    @contextmanager
    def identity_transaction(cls):
        cls.ensure_guard()
        with cls.session_scope() as session:
            session.exec(select(UserIdentityWriteGuard).where(UserIdentityWriteGuard.id == 1).with_for_update()).one()
            yield session
            session.commit()

    @staticmethod
    def _occupied(session: Session, account: str, *, exact: bool) -> bool:
        statement = select(User.user_id).where(User.external_id == account)
        if exact:
            statement = statement.where(User.account_rule_version == 0)
        if session.exec(statement.limit(1)).first() is not None:
            return True
        return session.get(UserAccountReservation, account_key(account)) is not None

    @classmethod
    def create(
        cls,
        user: User,
        *,
        exact: bool,
        role_ids: list[int],
        group_ids: list[int],
        bootstrap: bool = False,
    ) -> User:
        validate_nickname(user.user_name)
        if exact:
            validate_account(user.external_id)
        try:
            with cls.identity_transaction() as session:
                if user.external_id is not None and cls._occupied(session, user.external_id, exact=exact):
                    raise AccountAlreadyExistsError(field="external_id")
                user.account_rule_version = 1 if exact else 0
                user.account_match_key = account_key(user.external_id) if exact else "legacy"
                user.nickname_customized = False
                if exact:
                    user.source = "local"
                    user.legacy_sso_name = None
                if bootstrap:
                    first = session.get(User, 1) is None
                    user.user_id = 1 if first else None
                    role_ids = [AdminRole if first else DefaultRole]
                session.add(user)
                session.flush()
                if exact:
                    session.add(UserAccountReservation(account_key=user.account_match_key, user_id=user.user_id))
                for role_id in sorted(set(role_ids)):
                    session.add(UserRole(user_id=user.user_id, role_id=role_id))
                for group_id in sorted(set(group_ids)):
                    session.add(UserGroup(user_id=user.user_id, group_id=group_id))
                session.flush()
                session.refresh(user)
                session.expunge(user)
                return user
        except IntegrityError:
            # Translate only an actual identity collision. FK/binding/storage
            # failures retain their original exception and roll everything back.
            if user.external_id is not None:
                with cls.session_scope() as session:
                    if cls._occupied(session, user.external_id, exact=exact):
                        raise AccountAlreadyExistsError(field="external_id") from None
            raise

    @classmethod
    def login_candidates(cls, raw_account: str) -> list[User]:
        try:
            key = account_key(raw_account)
        except UnicodeEncodeError:
            return []  # Lone surrogates cannot identify a persisted UTF-8 account.
        with cls.session_scope() as session:
            legacy_account = raw_account.strip()
            candidates = (
                list(
                    session.exec(
                        select(User).where(
                            User.account_rule_version == 0,
                            User.external_id == legacy_account,
                        )
                    ).all()
                )
                if legacy_account
                else []
            )
            reservation = session.get(UserAccountReservation, key)
            if reservation is not None:
                exact = session.get(User, reservation.user_id)
                if exact is not None:
                    if (
                        exact.account_rule_version != 1
                        or exact.account_match_key != key
                        or exact.external_id != raw_account
                    ):
                        raise RuntimeError("Account reservation does not match its owning identity")
                    candidates.append(exact)
            return cls._detach(session, candidates)

    @classmethod
    def find_external(cls, raw_account: str, source: str | None = None) -> list[User]:
        with cls.session_scope() as session:
            statement = select(User).where(User.external_id == raw_account).order_by(User.user_id)
            if source is not None:
                statement = statement.where(User.source == source)
            users = session.exec(statement).all()
            candidates = [u for u in users if u.account_rule_version == 0 or u.external_id == raw_account]
            return cls._detach(session, candidates)

    @classmethod
    def find_deprecated_sso_name(cls, name: str, *, captured_only: bool) -> list[User]:
        with cls.session_scope() as session:
            statement = select(User).where(User.account_rule_version == 0)
            if captured_only:
                statement = statement.where(User.legacy_sso_name == name)
            else:
                statement = statement.where(User.legacy_sso_name.is_(None), User.user_name == name)
            return cls._detach(session, list(session.exec(statement).all()))

    @staticmethod
    def _detach(session: Session, candidates: list[User]) -> list[User]:
        unique = {user.user_id: user for user in candidates}
        for user in unique.values():
            session.expunge(user)
        return list(unique.values())
