from datetime import datetime

from sqlalchemy import and_, delete, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Column, DateTime, Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT


class UserLinkBase(SQLModelSerializable):
    user_id: int = Field(index=True)
    type: str = Field(index=True, max_length=32)
    type_detail: str = Field(index=True, max_length=255, description="typeRelated Information")
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class UserLink(UserLinkBase, table=True):
    __tablename__ = "user_link"
    id: int | None = Field(default=None, primary_key=True)


class UserLinkDao(UserLinkBase):
    @classmethod
    def get_user_link(cls, user_id: int, types: list) -> list[UserLink]:
        with get_sync_db_session() as session:
            statement = select(UserLink).where(and_(UserLink.user_id == user_id, UserLink.type.in_(types)))
            statement = statement.order_by(
                UserLink.create_time.desc()
            )  # Sort by creation time descending, newest added first
            return session.exec(statement).all()

    @classmethod
    def add_user_link(cls, user_id: int, type: str, type_detail: str) -> tuple[UserLink, bool]:
        """
        Add user link

        Returns:
            tuple[UserLink, bool]: (User Linked Objects, Whether to add for new)
        """
        with get_sync_db_session() as session:
            try:
                # Try inserting directly, leveraging the database's unique constraints
                user_link = UserLink(
                    user_id=user_id,
                    type=type,
                    type_detail=type_detail,
                    create_time=datetime.now(),
                    update_time=datetime.now(),
                )
                session.add(user_link)
                session.commit()
                return user_link, True  # Add New
            except IntegrityError:
                # Rollback and query existing records if unique constraints are violated
                session.rollback()
                existing = session.exec(
                    select(UserLink).where(
                        and_(UserLink.user_id == user_id, UserLink.type == type, UserLink.type_detail == type_detail)
                    )
                ).first()
                return existing, False  # already exists

    @classmethod
    def touch_user_link(cls, user_id: int, type: str, type_detail: str) -> tuple[UserLink, bool]:
        """Record or refresh a link, bumping ``update_time`` on every call.

        Unlike ``add_user_link`` (idempotent, first-write-wins), this is used for
        "recently used" ordering: an existing link's ``update_time`` is moved to
        now so the most recently touched row sorts first. Returns
        ``(link, is_new)``.
        """
        now = datetime.now()
        with get_sync_db_session() as session:
            existing = session.exec(
                select(UserLink).where(
                    and_(
                        UserLink.user_id == user_id,
                        UserLink.type == type,
                        UserLink.type_detail == type_detail,
                    )
                )
            ).first()
            if existing is not None:
                existing.update_time = now
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return existing, False
            user_link = UserLink(user_id=user_id, type=type, type_detail=type_detail, create_time=now, update_time=now)
            session.add(user_link)
            session.commit()
            session.refresh(user_link)
            return user_link, True

    @classmethod
    def delete_user_link(cls, user_id: int, type: str, type_detail: str) -> None:
        with get_sync_db_session() as session:
            statement = delete(UserLink).where(
                and_(UserLink.user_id == user_id, UserLink.type == type, UserLink.type_detail == type_detail)
            )
            session.exec(statement)
            session.commit()
        return True
