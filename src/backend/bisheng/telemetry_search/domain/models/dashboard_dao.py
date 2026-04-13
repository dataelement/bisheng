from typing import List

from sqlalchemy import or_, and_, func, text
from sqlmodel import col, select, delete, update

from bisheng.core.database import get_async_db_session
from .dashboard import Dashboard, DashboardType, DashboardStatus, DashboardComponent, DashboardDefault


class DashboardDao:

    @classmethod
    async def exec_sql_str(cls, sql_str: str) -> None:
        async with get_async_db_session() as session:
            await session.exec(text(sql_str))
            await session.commit()

    @classmethod
    async def insert(cls, data: Dashboard) -> Dashboard:
        async with get_async_db_session() as session:
            session.add(data)
            await session.commit()
            await session.refresh(data)
            return data

    @classmethod
    async def update(cls, data: Dashboard) -> Dashboard:
        if not data.id:
            raise ValueError("Dashboard id is required for update.")
        async with get_async_db_session() as session:
            session.add(data)
            await session.commit()
            await session.refresh(data)
            return data

    @classmethod
    async def get_one(cls, dashboard_id: int) -> Dashboard:
        async with get_async_db_session() as session:
            statement = select(Dashboard).where(col(Dashboard.id) == dashboard_id)
            result = await session.exec(statement)
            return result.first()

    @classmethod
    async def delete_one(cls, dashboard_id: int) -> bool:
        async with get_async_db_session() as session:
            statement = delete(Dashboard).where(col(Dashboard.id) == dashboard_id)
            await session.exec(statement)
            component_statement = delete(DashboardComponent).where(col(DashboardComponent.dashboard_id) == dashboard_id)
            await session.exec(component_statement)
            await session.commit()
            return True

    @classmethod
    async def update_dashboard_title(cls, dashboard_id: int, new_title: str) -> bool:
        statement = update(Dashboard).where(col(Dashboard.id) == dashboard_id).values(title=new_title)
        async with get_async_db_session() as session:
            await session.exec(statement)
            await session.commit()
            return True

    @classmethod
    async def update_dashboard_status(cls, dashboard_id: int, new_status: DashboardStatus) -> bool:
        statement = update(Dashboard).where(col(Dashboard.id) == dashboard_id).values(status=new_status.value)
        async with get_async_db_session() as session:
            await session.exec(statement)
            await session.commit()
            return True

    @staticmethod
    def generate_dashboard_filter_statement(statement, keyword: str = None, dashboard_type: List[DashboardType] = None,
                                            manage_ids: List[int] = None, extra_ids: List[int] = None,
                                            extra_status: DashboardStatus = None, user_id: int = None,
                                            filter_ids: List[int] = None):
        if user_id and extra_ids is not None:
            statement = statement.where(or_(
                col(Dashboard.user_id) == user_id,
                and_(col(Dashboard.id).in_(extra_ids), col(Dashboard.status) == extra_status.value),
                col(Dashboard.id).in_(manage_ids),
            ))
        elif user_id:
            statement = statement.where(col(Dashboard.user_id) == user_id)
        if keyword:
            statement = statement.where(col(Dashboard.title).like(f"%{keyword}%"))
        if dashboard_type:
            statement = statement.where(col(Dashboard.dashboard_type).in_([one.value for one in dashboard_type]))
        if filter_ids:
            statement = statement.where(col(Dashboard.id).in_(filter_ids))
        return statement

    @classmethod
    async def get_dashboards(cls, keyword: str = None, dashboard_type: List[DashboardType] = None,
                             manage_ids: List[int] = None, extra_ids: List[int] = None,
                             extra_status: DashboardStatus = None, user_id: int = None,
                             filter_ids: List[int] = None) -> List[Dashboard]:
        statement = select(Dashboard)
        statement = cls.generate_dashboard_filter_statement(statement, keyword=keyword, dashboard_type=dashboard_type,
                                                            manage_ids=manage_ids, extra_ids=extra_ids,
                                                            extra_status=extra_status, user_id=user_id,
                                                            filter_ids=filter_ids)
        statement = statement.order_by(col(Dashboard.update_time).desc())

        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def count_dashboards(cls, keyword: str = None, dashboard_type: List[DashboardType] = None,
                               manage_ids: List[int] = None, extra_ids: List[int] = None,
                               extra_status: DashboardStatus = None, user_id: int = None) -> int:
        statement = select(func.count(Dashboard.id))
        statement = cls.generate_dashboard_filter_statement(statement, keyword=keyword, dashboard_type=dashboard_type,
                                                            manage_ids=manage_ids, extra_ids=extra_ids,
                                                            extra_status=extra_status, user_id=user_id)
        async with get_async_db_session() as session:
            return await session.scalar(statement)

    @classmethod
    async def set_default_dashboard(cls, user_id: int, dashboard_id: int) -> DashboardDefault:
        statement = select(DashboardDefault).where(col(DashboardDefault.user_id) == user_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            data = result.first()
            if not data:
                data = DashboardDefault(user_id=user_id, dashboard_id=dashboard_id)
            data.dashboard_id = dashboard_id
            session.add(data)
            await session.commit()
            await session.refresh(data)
            return data

    @classmethod
    async def get_default_dashboard(cls, user_id: int) -> DashboardDefault:
        statement = select(DashboardDefault).where(col(DashboardDefault.user_id) == user_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    async def replace_dashboard_components(cls, dashboard: Dashboard,
                                           components: List[DashboardComponent]) -> Dashboard:
        delete_statement = delete(DashboardComponent).where(col(DashboardComponent.dashboard_id) == dashboard.id)
        async with get_async_db_session() as session:
            await session.exec(delete_statement)
            session.add_all(components)
            session.add(dashboard)
            await session.commit()
            await session.refresh(dashboard)
            return dashboard

    @classmethod
    async def get_one_component(cls, component_id: str) -> DashboardComponent:
        statement = select(DashboardComponent).where(col(DashboardComponent.id) == component_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.first()

    @classmethod
    async def get_components(cls, dashboard_id: int) -> List[DashboardComponent]:
        statement = select(DashboardComponent).where(col(DashboardComponent.dashboard_id) == dashboard_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def insert_components(cls, components: List[DashboardComponent]) -> None:
        async with get_async_db_session() as session:
            session.add_all(components)
            await session.commit()
