from typing import TYPE_CHECKING

from bisheng.services.base import Service
from loguru import logger
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


class DatabaseService(Service):
    name: str = 'database_service'

    def __init__(self, database_url: str):
        self.database_url = database_url
        # This file is in langflow.services.database.manager.py
        # the ini is in langflow
        # langflow_dir = Path(__file__).parent.parent.parent
        # self.script_location = langflow_dir / "alembic"
        # self.alembic_cfg_path = langflow_dir / "alembic.ini"
        self.engine = self._create_engine()

    def _create_engine(self) -> 'Engine':
        """Create the engine for the database."""
        if self.database_url and self.database_url.startswith('sqlite'):
            connect_args = {'check_same_thread': False}
        else:
            connect_args = {}
        return create_engine(self.database_url, connect_args=connect_args, pool_pre_ping=True)

    def __enter__(self):
        self._session = Session(self.engine)
        return self._session

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:  # If an exception has been raised
            logger.error(f'Session rollback because of exception: {exc_type.__name__} {exc_value}')
            self._session.rollback()
        else:
            self._session.commit()
        self._session.close()

    def get_session(self):
        with Session(self.engine) as session:
            yield session

    def create_db_and_tables(self):
        # from sqlalchemy import inspect

        # inspector = inspect(self.engine)
        # table_names = inspector.get_table_names()
        # current_tables = ["flow", "user", "apikey"]

        # if table_names and all(table in table_names for table in current_tables):
        #     logger.debug("Database and tables already exist")
        #     return

        logger.debug('Creating database and tables')

        for table in SQLModel.metadata.sorted_tables:
            try:
                table.create(self.engine, checkfirst=True)
            except OperationalError as oe:
                logger.warning(f'Table {table} already exists, skipping. Exception: {oe}')
            except Exception as exc:
                logger.error(f'Error creating table {table}: {exc}')
                raise RuntimeError(f'Error creating table {table}') from exc

        # Now check if the required tables exist, if not, something went wrong.
        # inspector = inspect(self.engine)
        # table_names = inspector.get_table_names()
        # for table in current_tables:
        #     if table not in table_names:
        #         logger.error("Something went wrong creating the database and tables.")
        #         logger.error("Please check your database settings.")
        #         raise RuntimeError("Something went wrong creating the database and tables.")

        logger.debug('Database and tables created successfully')
