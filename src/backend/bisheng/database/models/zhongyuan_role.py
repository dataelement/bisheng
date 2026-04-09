from datetime import datetime
from typing import Dict, List, Optional

from bisheng.core.database import get_sync_db_session
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, delete, text, update,Integer
from sqlmodel import Field, select


# ===================== 模型定义（严格匹配指定字段） =====================
class ZhongYuanRoleBase(SQLModelSerializable):
    """中原角色表基础模型（核心字段：user_id, user_uuid, account_no, user_name, status, operation_desc, org_name, org_code, sup_org_code）"""
    # 核心业务字段（按需求指定）
    user_id: str = Field(index=True, description='用户ID', unique=True)  # 用户ID唯一
    user_uuid: Optional[str] = Field(default=None, index=True, description='用户UUID')
    account_no: Optional[str] = Field(default=None, index=True, description='账号编号')
    user_name: str = Field(description='用户名')
    status: Optional[int] = Field(default=1, description='用户状态（1=有效）')
    operation_desc: Optional[str] = Field(default=None, description='操作描述')
    org_name: Optional[str] = Field(default=None, description='所属组织名称')
    org_code: Optional[str] = Field(default=None, index=True, description='所属组织编码')
    sup_org_code: Optional[str] = Field(default=None, description='所属父组织编码')
    # 新增字段：role_id、group_id（可重复int类型）
    role_id: Optional[int] = Field(default=None, description='角色ID（可重复）')
    group_id: Optional[int] = Field(default=None, description='分组ID（可重复）')
    # 新增 bisheng_user_id 字段（int类型，可选）
    bisheng_user_id: Optional[int] = Field(default=None, description='Bisheng用户ID', index=True)
    # 通用审计字段（对齐原有表结构）
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP'))
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
            onupdate=text('CURRENT_TIMESTAMP')
        )
    )


class ZhongYuanRole(ZhongYuanRoleBase, table=True):
    """中原角色表数据库实体模型"""
    # id: Optional[int] = Field(default=None, primary_key=True)  # 主键ID
    id: Optional[int] = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))


class ZhongYuanRoleRead(ZhongYuanRoleBase):
    """查询返回模型"""
    id: Optional[int] = None  # 主键ID返回


class ZhongYuanRoleUpdate(ZhongYuanRoleBase):
    """更新模型（仅保留可更新字段）"""
    status: Optional[int] = None
    operation_desc: Optional[str] = None
    org_name: Optional[str] = None
    org_code: Optional[str] = None
    sup_org_code: Optional[str] = None
    role_id: Optional[int] = None  # 新增可更新字段
    group_id: Optional[int] = None  # 新增可更新字段
    bisheng_user_id: Optional[int] = None  # 新增可更新字段
    update_user: Optional[int] = None  # 最后更新人


class ZhongYuanRoleCreate(ZhongYuanRoleBase):
    """创建模型"""
    # 创建时无需传主键ID和审计字段（自动填充）
    id: Optional[int] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


# ===================== DAO 操作类（对齐原有GroupDao风格） =====================
class ZhongYuanRoleDao(ZhongYuanRoleBase):
    """中原角色表数据访问层（完全对齐原有GroupDao逻辑）"""

    @classmethod
    def get_user_by_id(cls, id: int) -> ZhongYuanRole | None:
        """根据主键ID查询"""
        with get_sync_db_session() as session:
            statement = select(ZhongYuanRole).where(ZhongYuanRole.id == id)
            return session.exec(statement).first()

    @classmethod
    def get_user_by_user_id(cls, user_id: str) -> ZhongYuanRole | None:
        """根据用户ID查询（核心去重逻辑）"""
        with get_sync_db_session() as session:
            statement = select(ZhongYuanRole).where(ZhongYuanRole.user_id == user_id)
            return session.exec(statement).first()

    @classmethod
    def get_user_by_org_code(cls, org_code: str) -> list[ZhongYuanRole]:
        """根据组织编码查询用户列表"""
        with get_sync_db_session() as session:
            statement = select(ZhongYuanRole).where(ZhongYuanRole.org_code == org_code)
            return session.exec(statement).all()

    @classmethod
    def insert_user(cls, user: ZhongYuanRoleCreate) -> ZhongYuanRole:
        """创建中原角色记录"""
        with get_sync_db_session() as session:
            # 数据校验 & 转换为数据库实体
            user_add = ZhongYuanRole.validate(user)
            # 插入数据库
            session.add(user_add)
            session.commit()
            session.refresh(user_add)  # 刷新获取主键ID
            return user_add

    @classmethod
    def get_all_user(cls) -> list[ZhongYuanRole]:
        """查询所有记录（按更新时间降序）"""
        with get_sync_db_session() as session:
            statement = select(ZhongYuanRole).order_by(ZhongYuanRole.update_time.desc())
            return session.exec(statement).all()

    @classmethod
    def get_user_by_ids(cls, ids: List[int]) -> list[ZhongYuanRole]:
        """根据主键ID列表批量查询"""
        if not ids:
            raise ValueError('ids is empty')
        with get_sync_db_session() as session:
            statement = select(ZhongYuanRole).where(ZhongYuanRole.id.in_(ids)).order_by(ZhongYuanRole.update_time.desc())
            return session.exec(statement).all()

    @classmethod
    def get_user_by_user_ids(cls, user_ids: List[str]) -> list[ZhongYuanRole]:
        """根据用户ID列表批量查询"""
        if not user_ids:
            raise ValueError('user_ids is empty')
        with get_sync_db_session() as session:
            statement = select(ZhongYuanRole).where(ZhongYuanRole.user_id.in_(user_ids))
            return session.exec(statement).all()

    @classmethod
    def get_user_by_sup_org_code(cls, sup_org_code: str) -> list[ZhongYuanRole]:
        """根据父组织编码查询用户列表"""
        with get_sync_db_session() as session:
            statement = select(ZhongYuanRole).where(ZhongYuanRole.sup_org_code == sup_org_code)
            return session.exec(statement).all()

    @classmethod
    def delete_user(cls, id: int):
        """根据主键ID删除记录"""
        with get_sync_db_session() as session:
            session.exec(delete(ZhongYuanRole).where(ZhongYuanRole.id == id))
            session.commit()

    @classmethod
    def delete_user_by_user_id(cls, user_id: str):
        """根据用户ID删除记录"""
        with get_sync_db_session() as session:
            session.exec(delete(ZhongYuanRole).where(ZhongYuanRole.user_id == user_id))
            session.commit()

    @classmethod
    def update_user(cls, user: ZhongYuanRole) -> ZhongYuanRole:
        """全量更新记录"""
        with get_sync_db_session() as session:
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    @classmethod
    def update_user_partial(cls, id: int, update_data: ZhongYuanRoleUpdate) -> ZhongYuanRole | None:
        """部分更新记录（仅更新非None字段）"""
        with get_sync_db_session() as session:
            # 查询原数据
            user = session.exec(select(ZhongYuanRole).where(ZhongYuanRole.id == id)).first()
            if not user:
                return None
            # 仅更新非None字段
            for key, value in update_data.dict(exclude_unset=True).items():
                if hasattr(user, key) and value is not None:
                    setattr(user, key, value)
            # 提交更新
            session.commit()
            session.refresh(user)
            return user

    @classmethod
    def update_user_update_user(cls, id: int, user_id: int):
        """更新最后更新人（对齐原有Dao逻辑）"""
        with get_sync_db_session() as session:
            statement = update(ZhongYuanRole).where(ZhongYuanRole.id == id).values(
                update_user=user_id,
                update_time=datetime.now()
            )
            session.exec(statement)
            session.commit()

    @classmethod
    def batch_insert_users(cls, users: List[ZhongYuanRoleCreate]) -> List[ZhongYuanRole]:
        """批量创建记录（优化性能）"""
        if not users:
            return []
        with get_sync_db_session() as session:
            user_list = []
            for user in users:
                user_add = ZhongYuanRole.validate(user)
                user_list.append(user_add)
            # 批量插入
            session.add_all(user_list)
            session.commit()
            # 刷新获取主键
            for u in user_list:
                session.refresh(u)
            return user_list

    @classmethod
    def get_user_by_user_name(cls, user_name: str) -> list[ZhongYuanRole]:
        """根据用户名模糊查询（扩展常用查询）"""
        with get_sync_db_session() as session:
            statement = select(ZhongYuanRole).where(ZhongYuanRole.user_name.like(f'%{user_name}%'))
            return session.exec(statement).all()

    @classmethod
    def get_user_by_status(cls, status: int) -> list[ZhongYuanRole]:
        """根据用户状态查询（1=有效，0=无效）"""
        with get_sync_db_session() as session:
            statement = select(ZhongYuanRole).where(ZhongYuanRole.status == status)
            return session.exec(statement).all()
    
    @classmethod
    def update_user_status(cls, user_id: str, new_status: int) -> bool:
        """
        根据用户ID更新用户状态
        :param user_id: 用户ID（业务主键）
        :param new_status: 新状态（1=有效，0=无效）
        :return: 更新是否成功
        """
        with get_sync_db_session() as session:
            # 执行更新操作
            statement = update(ZhongYuanRole).where(
                ZhongYuanRole.user_id == user_id
            ).values(
                status=new_status,
                update_time=datetime.now()  # 同步更新时间
            )
            result = session.exec(statement)
            session.commit()
            # 判断是否有记录被更新
            return result.rowcount > 0