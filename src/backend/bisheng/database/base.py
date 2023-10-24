import hashlib

import yaml
from bisheng.database.models.config import Config
from bisheng.database.models.role import Role
from bisheng.database.models.user import User
from bisheng.database.models.user_role import UserRole
from bisheng.settings import settings
from bisheng.utils.logger import logger
from sqlmodel import Session, SQLModel, create_engine, select

if settings.database_url and settings.database_url.startswith('sqlite'):
    connect_args = {'check_same_thread': False}
else:
    connect_args = {}
if not settings.database_url:
    raise RuntimeError('No database_url provided')
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


def create_db_and_tables():
    logger.debug('Creating database and tables')
    try:
        SQLModel.metadata.create_all(engine)
    except Exception as exc:
        logger.error(f'Error creating database and tables: {exc}')
        raise RuntimeError('Error creating database and tables') from exc
    # Now check if the table Flow exists, if not, something went wrong
    # and we need to create the tables again.
    from sqlalchemy import inspect

    inspector = inspect(engine)
    if 'flow' not in inspector.get_table_names():
        logger.error('Something went wrong creating the database and tables.')
        logger.error('Please check your database settings.')

        raise RuntimeError('Something went wrong creating the database and tables.')
    else:
        logger.debug('Database and tables created successfully')

    # 写入默认数据
    with Session(engine) as session:
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

        # 初始化config
        config = session.exec(select(Config).limit(1)).all()
        if not config:
            knowledge = settings.knowledges
            default_llm = settings.default_llm
            db_knowledge = Config(key='knowledges', value=yaml.dump(knowledge))
            db_llm = Config(key='default_llm', value=yaml.dump(default_llm))
            session.add(db_knowledge)
            session.add(db_llm)
            session.commit()


def get_session():
    with Session(engine) as session:
        yield session
