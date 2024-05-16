import hashlib
import json
import os
from contextlib import contextmanager
from typing import List

from sqlalchemy import text

from bisheng.database.init_config import init_config
from bisheng.database.service import DatabaseService
from bisheng.settings import settings
from bisheng.utils.logger import logger
from sqlmodel import Session, select, update

db_service: 'DatabaseService' = DatabaseService(settings.database_url)


def init_default_data():
    """初始化数据库"""
    from bisheng.cache.redis import redis_client
    from bisheng.database.models.component import Component
    from bisheng.database.models.role import Role
    from bisheng.database.models.user import User
    from bisheng.database.models.user_role import UserRole
    from bisheng.database.models.gpts_tools import GptsTools
    from bisheng.database.models.gpts_tools import GptsToolsType
    from bisheng.database.models.sft_model import SftModel
    from bisheng.database.models.flow_version import FlowVersion

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
                if not user and settings.admin:
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

                component_db = session.exec(select(Component).limit(1)).all()
                if not component_db:
                    db_components = []
                    json_items = json.loads(read_from_conf('component.json'))
                    for item in json_items:
                        for k, v in item.items():
                            db_component = Component(name=k, user_id=1, user_name='admin', data=v)
                            db_components.append(db_component)
                    session.add_all(db_components)
                    session.commit()

                # 初始化预置工具列表
                preset_tools = session.exec(select(GptsTools).limit(1)).all()
                if not preset_tools:
                    preset_tools = []
                    json_items = json.loads(read_from_conf('t_gpts_tools.json'))
                    for item in json_items:
                        item['api_params'] = json.loads(item['api_params'])
                        preset_tool = GptsTools(**item)
                        preset_tools.append(preset_tool)
                    session.add_all(preset_tools)
                    session.commit()
                # 初始化预置工具类别
                preset_tools_type = session.exec(select(GptsToolsType).limit(1)).all()
                if not preset_tools_type:
                    preset_tools_type = []
                    json_items = json.loads(read_from_conf('t_gpts_tools_type.json'))
                    for item in json_items:
                        preset_tool_type = GptsToolsType(**item)
                        preset_tools_type.append(preset_tool_type)
                    session.add_all(preset_tools_type)
                    session.commit()
                    # 设置预置工具所属的类别, 需要和预置数据一致，所以id是固定的
                    for i in range(1, 7):
                        session.exec(update(GptsTools).where(GptsTools.id == i).values(type=i))
                    # 属于天眼查类别下的工具
                    tyc_types: List[int] = list(range(7, 18))
                    session.exec(update(GptsTools).where(GptsTools.id.in_(tyc_types)).values(type=7))
                    # 属于金融类别下的工具
                    jr_types: List[int] = list(range(18, 28))
                    session.exec(update(GptsTools).where(GptsTools.id.in_(jr_types)).values(type=8))
                    session.commit()
                # 初始化配置可用于微调的基准模型
                preset_models = session.exec(select(SftModel).limit(1)).all()
                if not preset_models:
                    preset_models = []
                    json_items = json.loads(read_from_conf('sft_model.json'))
                    for item in json_items:
                        preset_model = SftModel(**item)
                        preset_models.append(preset_model)
                    session.add_all(preset_models)
                    session.commit()

                # 初始化补充默认的技能版本表
                flow_version = session.exec(select(FlowVersion).limit(1)).all()
                if not flow_version:
                    sql_query = text("INSERT INTO `flowversion` (`name`, `flow_id`, `data`, `user_id`, `is_current`, `is_delete`) \
                     select 'v0', `id` as flow_id, `data`, `user_id`, 1, 0 from `flow`;")
                    session.execute(sql_query)
                    session.commit()
                    # 修改表单数据表
                    sql_query = text(
                        "UPDATE `t_variable_value` a SET a.version_id=(SELECT `id` from `flowversion` WHERE flow_id=a.flow_id and is_current=1)")
                    session.execute(sql_query)
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


@contextmanager
def session_getter() -> Session:
    """轻量级session context"""
    try:
        session = Session(db_service.engine)
        yield session
    except Exception as e:
        logger.info('Session rollback because of exception:{}', e)
        session.rollback()
        raise
    finally:
        session.close()


def read_from_conf(file_path: str) -> str:
    if '/' not in file_path:
        # Get current path
        current_path = os.path.dirname(os.path.abspath(__file__))

        file_path = os.path.join(current_path, file_path)

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return content
