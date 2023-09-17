import hashlib

from bisheng.database.models.server import Server
from bisheng.database.models.user import User
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
        user = session.exec(select(User).limit(1)).all()
        if not user:
            md5 = hashlib.md5()
            md5.update(settings.admin.get('password').encode('utf-8'))
            user = User(user_name=settings.admin.get('user_name'),
                        password=md5.hexdigest(),
                        role='admin')
            session.add(user)
            session.commit()

        rts = session.exec(
            select(Server).where(Server.endpoint == settings.bisheng_rt['server'])).all()
        if not rts:
            db_rt = Server(endpoint=settings.bisheng_rt['server'],
                           server=settings.bisheng_rt['name'])
            session.add(db_rt)
            session.commit()


def get_session():
    with Session(engine) as session:
        yield session
