import hashlib
from contextlib import contextmanager
from typing import Generator, Optional

from bisheng.database.init_config import init_config
from bisheng.database.models.role import Role
from bisheng.database.models.user import User
from bisheng.database.models.user_role import UserRole
from bisheng.database.service import DatabaseService
from bisheng.settings import settings
from bisheng.utils.logger import logger
from sqlmodel import Session, select

db_service = DatabaseService(settings.database_url)


def init_default_data():
    # 写入默认数据
    try:
        db_service.create_db_and_tables()
    except Exception as exc:
        # if the exception involves tables already existing
        # we can ignore it
        if 'already exists' not in str(exc):
            logger.error(f'Error creating DB and tables: {exc}')
            raise RuntimeError('Error creating DB and tables') from exc

    with session_getter(db_service) as session:
        db_role = session.exec(select(Role).limit(1)).all()
        if not db_role:
            # 初始化系统配置, 管理员拥有所有权限
            db_role = Role(id=1, role_name='系统管理员', remark='系统所有权限管理员')
            session.add(db_role)
            db_role_normal = Role(id=2, role_name='普通用户', remark='一般权限管理员')
            session.add(db_role_normal)
            session.commit()

        user = session.exec(select(User).limit(1)).all()
        if not user:
            md5 = hashlib.md5()
            md5.update(settings.admin.get('password').encode('utf-8'))
            user = User(
                user_id=1,
                user_name=settings.admin.get('user_name'),
                password=md5.hexdigest(),
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            db_userrole = UserRole(user_id=user.user_id, role_id=db_role.id)
            session.add(db_userrole)
            session.commit()

    init_config()


def get_session() -> Generator['Session', None, None]:
    yield from db_service.get_session()


@contextmanager
def session_getter(db_service_p: Optional[DatabaseService] = db_service):
    try:
        session = Session(db_service_p.engine)
        yield session
    except Exception as e:
        print('Session rollback because of exception:', e)
        session.rollback()
        raise
    finally:
        session.close()
