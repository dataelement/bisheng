"""Tenant-scoped persistence for legacy report editor records."""

from sqlalchemy import or_
from sqlmodel import select

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_sync_db_session
from bisheng.database.models.report import Report
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.user.domain.models.user import User


class ReportRepository:
    @staticmethod
    def editor_is_active(user_id: int, tenant_id: int) -> bool:
        with get_sync_db_session() as session:
            return (
                session.exec(
                    select(User.user_id)
                    .join(UserTenant, UserTenant.user_id == User.user_id)
                    .join(Tenant, Tenant.id == UserTenant.tenant_id)
                    .where(
                        User.user_id == user_id,
                        User.delete == 0,
                        UserTenant.tenant_id == tenant_id,
                        UserTenant.status == "active",
                        UserTenant.is_active == 1,
                        Tenant.status == "active",
                    )
                ).first()
                is not None
            )

    @staticmethod
    def find_by_key(key: str) -> Report | None:
        with get_sync_db_session() as session:
            rows = session.exec(
                select(Report).where(Report.del_yn == 0, or_(Report.version_key == key, Report.newversion_key == key))
            ).all()
            # A duplicated legacy key cannot select an arbitrary victim.
            if (
                len(rows) != 1
                or rows[0].tenant_id != get_current_tenant_id()
                or key != (rows[0].newversion_key or rows[0].version_key)
            ):
                return None
            return rows[0]

    @staticmethod
    def save_callback(report_id: int, key: str, object_name: str) -> bool:
        with get_sync_db_session() as session:
            row = session.exec(
                select(Report).where(Report.id == report_id, Report.del_yn == 0).with_for_update()
            ).first()
            if (
                row is None
                or row.tenant_id != get_current_tenant_id()
                or key != (row.newversion_key or row.version_key)
            ):
                return False
            row.object_name = object_name
            row.version_key = key
            row.newversion_key = None
            session.add(row)
            session.commit()
            return True
