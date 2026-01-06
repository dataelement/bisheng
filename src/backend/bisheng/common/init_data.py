import hashlib
import json
import os
from typing import List

from loguru import logger
from sqlmodel import select, update

from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.database import get_async_db_session, get_database_connection
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.database.constants import AdminRole, DefaultRole
from bisheng.database.models.component import Component
from bisheng.database.models.group import Group, DefaultGroup
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import RoleAccess, AccessType, WebMenuResource
from bisheng.database.models.template import Template
from bisheng.telemetry_search.domain.init_dataset import init_dashboard_datasets
from bisheng.tool.domain.models.gpts_tools import GptsTools
from bisheng.tool.domain.models.gpts_tools import GptsToolsType
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRoleDao


async def init_default_data():
    """初始化数据库"""
    redis_client = await get_redis_client()
    if await redis_client.asetNx('init_default_data', '1'):
        try:
            db_manager = await get_database_connection()
            await db_manager.create_db_and_tables()
            async with get_async_db_session() as session:
                db_role = await session.exec(select(Role).limit(1))
                db_role = db_role.all()
                if not db_role:
                    # 初始化系统配置, 管理员拥有所有权限
                    db_role = Role(id=AdminRole, role_name='System Admin', remark='System highest privileges',
                                   group_id=DefaultGroup)
                    session.add(db_role)
                    db_role_normal = Role(id=DefaultRole, role_name='Regular users', remark='Regular users',
                                          group_id=DefaultGroup)
                    session.add(db_role_normal)
                    # 给普通用户赋予 构建、知识、模型菜单栏的查看权限
                    session.add_all([
                        RoleAccess(role_id=DefaultRole, type=AccessType.WEB_MENU.value,
                                   third_id=WebMenuResource.BUILD.value),
                        RoleAccess(role_id=DefaultRole, type=AccessType.WEB_MENU.value,
                                   third_id=WebMenuResource.KNOWLEDGE.value),
                        RoleAccess(role_id=DefaultRole, type=AccessType.WEB_MENU.value,
                                   third_id=WebMenuResource.MODEL.value),
                    ])
                    await session.commit()
                # 添加默认用户组
                group = await session.exec(select(Group).limit(1))
                group = group.all()
                if not group:
                    group = Group(id=DefaultGroup, group_name='Default user group', create_user=1, update_user=1)
                    session.add(group)
                    await session.commit()
                    await session.refresh(group)

                user = await session.exec(select(User).limit(1))
                user = user.all()
                if not user and settings.admin:
                    md5 = hashlib.md5()
                    md5.update(settings.admin.get('password').encode('utf-8'))
                    user = User(
                        user_id=1,
                        user_name=settings.admin.get('user_name'),
                        password=md5.hexdigest(),
                    )
                    session.add(user)
                    await session.commit()
                    await session.refresh(user)
                    await UserRoleDao.set_admin_user(user.user_id)

                component_db = await session.exec(select(Component).limit(1))
                component_db = component_db.all()
                if not component_db:
                    db_components = []
                    json_items = json.loads(read_from_conf('../database/data/component.json'))
                    for item in json_items:
                        for k, v in item.items():
                            db_component = Component(name=k, user_id=1, user_name='admin', data=v)
                            db_components.append(db_component)
                    session.add_all(db_components)
                    await session.commit()

                # 初始化预置技能模板
                templates = await session.exec(select(Template).limit(1))
                templates = templates.all()
                if not templates:
                    json_items = json.loads(read_from_conf('../database/data/template.json'))
                    for item in json_items:
                        session.add(Template(**item))
                    await session.commit()

                # 初始化预置工具列表
                preset_tools = await session.exec(select(GptsTools).limit(1))
                preset_tools = preset_tools.all()
                if not preset_tools:
                    preset_tools = []
                    json_items = json.loads(read_from_conf('../database/data/t_gpts_tools.json'))
                    for item in json_items:
                        preset_tool = GptsTools(**item)
                        preset_tools.append(preset_tool)
                    session.add_all(preset_tools)
                    await session.commit()
                # 初始化预置工具类别
                preset_tools_type = await session.exec(select(GptsToolsType).limit(1))
                preset_tools_type = preset_tools_type.all()
                if not preset_tools_type:
                    preset_tools_type = []
                    json_items = json.loads(read_from_conf('../database/data/t_gpts_tools_type.json'))
                    for item in json_items:
                        preset_tool_type = GptsToolsType(**item)
                        preset_tools_type.append(preset_tool_type)
                    session.add_all(preset_tools_type)
                    await session.commit()
                    # 设置预置工具所属的类别, 需要和预置数据一致，所以id是固定的
                    for i in range(1, 7):
                        await session.exec(update(GptsTools).where(GptsTools.id == i).values(type=i))
                    # 属于天眼查类别下的工具
                    tyc_types: List[int] = list(range(7, 18))
                    await session.exec(
                        update(GptsTools).where(GptsTools.id.in_(tyc_types)).values(type=7))
                    # 属于金融类别下的工具
                    jr_types: List[int] = list(range(18, 28))
                    await session.exec(
                        update(GptsTools).where(GptsTools.id.in_(jr_types)).values(type=8))
                    await session.commit()

            # 初始化数据库config
            await settings.init_config()

            # init dashboard data
            await init_dashboard_datasets()
        except Exception as exc:
            # if the exception involves tables already existing
            # we can ignore it
            if 'already exists' not in str(exc):
                logger.exception(f'Error creating DB and tables: {exc}')
                raise RuntimeError('Error creating DB and tables') from exc
        finally:
            await redis_client.adelete('init_default_data')


def read_from_conf(file_path: str) -> str:
    # Get current path
    current_path = os.path.dirname(os.path.abspath(__file__))

    file_path = os.path.join(current_path, file_path)

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return content


def upload_preset_minio_file():
    """ 上传预置文件到minio, 为了和工作流模板配合 """
    minio_client = get_minio_storage_sync()
    # 上传 「多助手并行+串行报告生成」 工作流模板需要的docx文件
    template_data = read_from_conf('../database/data/0254d1808a5247d2a3ee0d0011819acb.docx')
    minio_client.put_object_sync(bucket_name=minio_client.bucket,
                                 object_name='workflow/report/0254d1808a5247d2a3ee0d0011819acb.docx',
                                 file=template_data,
                                 content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
