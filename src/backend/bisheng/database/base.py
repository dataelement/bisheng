import hashlib
from contextlib import contextmanager
from typing import Generator

from bisheng.database.init_config import init_config
from bisheng.database.models.role import Role
from bisheng.database.models.user import User
from bisheng.database.models.user_role import UserRole
from bisheng.database.service import DatabaseService
from bisheng.settings import settings
from bisheng.utils.logger import logger
from sqlmodel import Session, select

db_service: 'DatabaseService' = DatabaseService(settings.database_url)


def init_default_data():
    """初始化数据库"""
    from bisheng.cache.redis import redis_client
    if redis_client.setNx('init_default_data', '1'):
        try:
            db_service.create_db_and_tables()
            with session_getter() as session:
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
            # 初始化数据库config
            init_config()
        except Exception as exc:
            # if the exception involves tables already existing
            # we can ignore it
            if 'already exists' not in str(exc):
                logger.error(f'Error creating DB and tables: {exc}')
                raise RuntimeError('Error creating DB and tables') from exc
        finally:
            redis_client.delete('init_default_data')


def get_session() -> Generator['Session', None, None]:
    yield from db_service.get_session()


@contextmanager
def session_getter():
    """轻量级session context"""
    try:
        session = Session(db_service.engine)
        yield session
    except Exception as e:
        print('Session rollback because of exception:', e)
        session.rollback()
        raise
    finally:
        session.close()
