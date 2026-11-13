"""Transaction boundary for workflow form variables.

Bulk ORM DELETE is not tenant-filtered. Use only entities loaded under the
verified resource boundary, and commit replacement once after all INSERTs.
"""

from contextlib import contextmanager

from sqlmodel import select

from bisheng.core.database import get_sync_db_session
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.variable_value import Variable


class VariableRepository:
    def __init__(self, session):
        self.session = session

    @classmethod
    @contextmanager
    def transaction(cls):
        with get_sync_db_session() as session:
            with session.begin():
                yield cls(session)

    def flow(self, flow_id, *, lock=False):
        statement = select(Flow).where(Flow.id == flow_id, Flow.is_delete == 0)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.session.exec(statement).first()

    def version(self, flow_id, version_id, *, lock=False):
        statement = select(FlowVersion).where(FlowVersion.flow_id == flow_id, FlowVersion.is_delete == 0)
        statement = (
            statement.where(FlowVersion.is_current == 1)
            if version_id is None
            else statement.where(FlowVersion.id == version_id)
        )
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.session.exec(statement).one_or_none()

    def variable(self, variable_id, *, lock=False):
        statement = select(Variable).where(Variable.id == variable_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.session.exec(statement).first()

    def variables(self, flow_id, version_id, node_id=None, variable_name=None, *, lock=False):
        statement = select(Variable).where(Variable.flow_id == flow_id, Variable.version_id == version_id)
        if node_id is not None:
            statement = statement.where(Variable.node_id == node_id)
        if variable_name is not None:
            statement = statement.where(Variable.variable_name == variable_name)
        if lock:
            # Current read is required after authorization under MySQL REPEATABLE READ.
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return self.session.exec(statement.order_by(Variable.id)).all()

    def insert(self, values, tenant_id):
        variable = Variable.model_validate(dict(values, tenant_id=tenant_id))
        self.session.add(variable)
        self.session.flush()
        self.session.refresh(variable)
        return variable

    def remove(self, variable):
        self.session.delete(variable)

    def flush(self):
        self.session.flush()
