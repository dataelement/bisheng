"""Management user search without changing the shared legacy DAO contract."""

from sqlalchemy import func
from sqlmodel import select

from bisheng.common.subject_search import normalize_keyword
from bisheng.core.database import get_sync_db_session
from bisheng.core.database.subject_search import exact_id_priority, subject_match_condition
from bisheng.user.domain.models.user import User


class ManagementSearchRepository:
    @classmethod
    def list_users(cls, user_ids=None, keyword=None, page=0, limit=0):
        kw = normalize_keyword(keyword or "")
        filters = []
        if user_ids is not None:
            filters.append(User.user_id.in_(user_ids))
        if kw:
            filters.append(
                subject_match_condition(User.user_id, User.user_name, User.external_id, kw, name_prefix=False)
            )
        stmt = select(User).where(*filters)
        if kw:
            stmt = stmt.order_by(exact_id_priority(User.external_id, kw))
        stmt = stmt.order_by(User.user_id.desc())
        if page and limit:
            stmt = stmt.offset((page - 1) * limit).limit(limit)
        with get_sync_db_session() as session:
            total = session.scalar(select(func.count(User.user_id)).where(*filters))
            return session.exec(stmt).all(), total
