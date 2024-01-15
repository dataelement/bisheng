from typing import List, Optional
from uuid import UUID

from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.base import get_session
from bisheng.database.models.variable_value import Variable, VariableCreate, VariableRead
from fastapi import APIRouter, HTTPException
from fastapi.params import Depends
from sqlmodel import Session, delete, select

# build router
router = APIRouter(prefix='/variable', tags=['variable'])


@router.post('/', status_code=200, response_model=UnifiedResponseModel[VariableRead])
def post_variable(
        variable: Variable,
        session: Session = Depends(get_session),
):
    try:
        if variable.id:
            # 更新，采用全量替换
            db_variable = session.get(Variable, variable.id)
            db_variable.variable_name = variable.variable_name[:50]
            db_variable.value = variable.value
            db_variable.value_type = variable.value_type
        else:
            # if name exist
            db_variable = session.exec(
                select(Variable).where(Variable.node_id == variable.node_id,
                                       Variable.variable_name == variable.variable_name)).all()
            if db_variable:
                raise HTTPException(status_code=500, detail='name repeat, please choose another')
            db_variable = Variable.from_orm(variable)

        session.add(db_variable)
        session.commit()
        session.refresh(db_variable)
        return resp_200(db_variable)
    except Exception as e:
        return HTTPException(status_code=500, detail=str(e))


@router.get('/list', response_model=UnifiedResponseModel[List[VariableRead]], status_code=200)
def get_variables(
        *,
        flow_id: str,
        node_id: Optional[str] = None,
        variable_name: Optional[str] = None,
        session: Session = Depends(get_session),
):
    try:
        flow_id = UUID(flow_id).hex
        query = select(Variable).where(Variable.flow_id == flow_id)
        if node_id:
            query = query.where(Variable.node_id == node_id)
        if variable_name:
            query = query.where(Variable.variable_name == variable_name)

        res = session.exec(query.order_by(Variable.id.asc())).all()
        return resp_200(res)

    except Exception as e:
        return HTTPException(status_code=500, detail=str(e))


@router.delete('/del', status_code=200)
def del_variables(
        *,
        id: int,
        session: Session = Depends(get_session),
):
    try:
        statment = delete(Variable).where(Variable.id == id)

        session.exec(statment)
        session.commit()
        return resp_200()

    except Exception as e:
        return HTTPException(status_code=500, detail=str(e))


@router.post('/save_all', status_code=200)
def save_all_variables(
        *,
        data: List[VariableCreate],
        session: Session = Depends(get_session),
):
    try:
        # delete first
        flow_id = data[0].flow_id
        session.exec(delete(Variable).where(Variable.flow_id == flow_id))
        session.flush()
        for var in data:
            db_var = Variable.from_orm(var)
            session.add(db_var)
        session.commit()
        return resp_200()
    except Exception as e:
        session.rollback()
        return HTTPException(status_code=500, detail=str(e))
