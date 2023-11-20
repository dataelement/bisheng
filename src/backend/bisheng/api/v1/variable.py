
from uuid import UUID

from bisheng.database.base import get_session
from bisheng.database.models.variable_value import Variable, VariableRead
from fastapi import APIRouter, HTTPException
from fastapi.params import Depends
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/variable', tags=['variable'])


@router.post('/', status_code=200, response_model=VariableRead)
def post_variable(variable: Variable, session: Session = Depends(get_session),):
    try:
        if variable.id:
            # 更新，采用全量替换
            db_variable = session.get(Variable, variable.id)
            db_variable.variable_name = variable.variable_name
            db_variable.value = variable.value
            db_variable.value_type = variable.value_type
        else:
            variable.flow_id = UUID(variable.flow_id).hex
            db_variable = Variable.from_orm(variable)

        session.add(db_variable)
        session.commit()
        session.refresh(db_variable)
        return db_variable
    except Exception as e:
        return HTTPException(status_code=500, detail=str(e))


@router.get('/list', status_code=200)
def get_variables(*, flow_id: str, node_id: str, variable_name: str,
                  session: Session = Depends(get_session),):
    try:
        flow_id = UUID(flow_id).hex
        query = select(Variable).where(Variable.flow_id == flow_id,
                                       Variable.node_id == node_id)

        res = session.exec(query).all()
        res_list = [{'variable_name': r.variable_name,
                     'variable_value': r.value,
                     'variable_type': r.value_type} for r in res]
        return res_list

    except Exception as e:
        return HTTPException(status_code=500, detail=str(e))
