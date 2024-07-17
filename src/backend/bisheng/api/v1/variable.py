from typing import List, Optional
from uuid import UUID

from loguru import logger
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import delete, select

from bisheng.api.services.user_service import get_login_user
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.base import session_getter
from bisheng.database.models.flow_version import FlowVersionDao
from bisheng.database.models.variable_value import Variable, VariableCreate, VariableRead, VariableDao

# build router
router = APIRouter(prefix='/variable', tags=['variable'])


@router.post('/', status_code=200, response_model=UnifiedResponseModel[VariableRead])
def post_variable(variable: Variable):
    try:
        if not variable.version_id:
            raise HTTPException(status_code=500, detail='version_id is required')
        if variable.id:
            # 更新，采用全量替换
            with session_getter() as session:
                db_variable = session.get(Variable, variable.id)
            db_variable.variable_name = variable.variable_name[:50]
            db_variable.value = variable.value
            db_variable.value_type = variable.value_type
        else:
            # if name exist
            with session_getter() as session:
                db_variable = session.exec(
                    select(Variable).where(
                        Variable.node_id == variable.node_id,
                        Variable.variable_name == variable.variable_name,
                        Variable.version_id == variable.version_id)).all()
            if db_variable:
                raise HTTPException(status_code=500, detail='name repeat, please choose another')
            db_variable = Variable.from_orm(variable)

        with session_getter() as session:
            session.add(db_variable)
            session.commit()
            session.refresh(db_variable)
        return resp_200(db_variable)
    except Exception as e:
        logger.exception("post variable error: ")
        return HTTPException(status_code=500, detail=str(e))


@router.get('/list', response_model=UnifiedResponseModel[List[VariableRead]], status_code=200)
def get_variables(*,
                  flow_id: str,
                  node_id: Optional[str] = None,
                  variable_name: Optional[str] = None,
                  version_id: Optional[int] = None):
    try:
        flow_id = UUID(flow_id).hex
        # 没传ID默认获取当前版本的数据
        if version_id is None:
            version_id = FlowVersionDao.get_version_by_flow(flow_id).id
        res = VariableDao.get_variables(flow_id, node_id, variable_name, version_id)
        return resp_200(res)

    except Exception as e:
        return HTTPException(status_code=500, detail=str(e))


@router.delete('/del', status_code=200)
def del_variables(*, id: int):
    try:
        statment = delete(Variable).where(Variable.id == id)
        with session_getter() as session:
            session.exec(statment)
            session.commit()
        return resp_200()

    except Exception as e:
        return HTTPException(status_code=500, detail=str(e))


@router.post('/save_all', status_code=200)
def save_all_variables(*, data: List[VariableCreate]):
    try:
        # delete first
        flow_id = data[0].flow_id
        with session_getter() as session:
            session.exec(delete(Variable).where(Variable.flow_id == flow_id))
            session.commit()
            for var in data:
                db_var = Variable.model_validate(var)
                session.add(db_var)
            session.commit()
        return resp_200()
    except Exception as e:
        return HTTPException(status_code=500, detail=str(e))
