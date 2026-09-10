"""Bounded primary-department names for authorized DSH browser displays."""

from sqlmodel import Session, select

from bisheng.database.models.department import Department, UserDepartment
from bisheng.user.domain.repositories.dsh_profile import UserDshProfileRepository


class DshDisplayRepository:
    @staticmethod
    def read(session: Session, user_ids: list[int]) -> dict[int, dict]:
        profiles = UserDshProfileRepository.batch_snapshot(session, user_ids)
        if not profiles:
            return profiles
        rows = session.exec(
            select(UserDepartment.user_id, Department.name)
            .join(Department, Department.id == UserDepartment.department_id)
            .where(UserDepartment.user_id.in_(list(profiles)), UserDepartment.is_primary == 1)
            .order_by(UserDepartment.user_id, UserDepartment.id)
        ).all()
        departments = {}
        for user_id, name in rows:
            departments.setdefault(user_id, name)
        return {
            user_id: {**profile, "department_name": departments.get(user_id)} for user_id, profile in profiles.items()
        }
