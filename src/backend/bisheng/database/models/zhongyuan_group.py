from datetime import datetime
from typing import Dict, List, Optional

from bisheng.core.database import get_sync_db_session
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, delete, text, update,Integer
from sqlmodel import Field, select


# ===================== 模型定义（严格匹配指定字段） =====================
class ZhongYuanGroupBase(SQLModelSerializable):
    """中原集团表基础模型（字段：group_id, org_id, org_code, sup_org_code, org_status, org_name, full_org_name, remark）"""
    # 核心字段（按需求指定）
    group_id: Optional[int] = Field(default=None, index=True, description='关联的分组ID')
    org_id: str = Field(index=True, description='组织ID', unique=True)  # 组织ID唯一
    org_code: str = Field(index=True, description='组织编码')
    sup_org_code: Optional[str] = Field(default=None, description='父组织编码')
    org_status: Optional[int] = Field(default=1, description='组织状态（1=有效，0=无效）')
    org_name: str = Field(description='组织名称')
    full_org_name: str = Field(description='组织完整层级名称')
    remark: Optional[str] = Field(default=None, description='备注')
    # 通用审计字段（对齐原有Group表）
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


class ZhongYuanGroup(ZhongYuanGroupBase, table=True):
    # id: Optional[int] = Field(default=None, primary_key=True)  # 主键ID（需求指定）
    id: Optional[int] = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))


class ZhongYuanGroupRead(ZhongYuanGroupBase):
    """查询返回模型"""
    id: Optional[int] = None  # 主键ID返回


class ZhongYuanGroupUpdate(ZhongYuanGroupBase):
    """更新模型（仅保留可更新字段）"""
    org_status: Optional[int] = None
    remark: Optional[str] = None
    update_user: Optional[int] = None


class ZhongYuanGroupCreate(ZhongYuanGroupBase):
    """创建模型"""
    # 创建时无需传主键ID和审计字段（自动填充）
    id: Optional[int] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


# ===================== DAO 操作类（对齐原有GroupDao风格） =====================
class ZhongYuanGroupDao(ZhongYuanGroupBase):
    """中原集团表数据访问层（完全对齐原有GroupDao逻辑）"""

    @classmethod
    def get_group_by_id(cls, id: int) -> ZhongYuanGroup | None:
        """根据主键ID查询"""
        with get_sync_db_session() as session:
            statement = select(ZhongYuanGroup).where(ZhongYuanGroup.id == id)
            return session.exec(statement).first()

    @classmethod
    def get_group_by_org_id(cls, org_id: str) -> ZhongYuanGroup | None:
        """根据组织ID查询（核心去重逻辑）"""
        with get_sync_db_session() as session:
            statement = select(ZhongYuanGroup).where(ZhongYuanGroup.org_id == org_id)
            return session.exec(statement).first()

    @classmethod
    def get_group_by_group_id(cls, group_id: int) -> list[ZhongYuanGroup]:
        """根据关联的分组ID查询"""
        with get_sync_db_session() as session:
            statement = select(ZhongYuanGroup).where(ZhongYuanGroup.group_id == group_id)
            return session.exec(statement).all()

    @classmethod
    def insert_group(cls, group: ZhongYuanGroupCreate) -> ZhongYuanGroup:
        """创建中原集团记录（自动填充创建人）"""
        with get_sync_db_session() as session:
            # 数据校验 & 转换为数据库实体
            group_add = ZhongYuanGroup.validate(group)
            # 插入数据库
            session.add(group_add)
            session.commit()
            session.refresh(group_add)  # 刷新获取主键ID
            return group_add

    @classmethod
    def get_all_group(cls) -> list[ZhongYuanGroup]:
        """查询所有记录（按更新时间降序）"""
        with get_sync_db_session() as session:
            statement = select(ZhongYuanGroup).order_by(ZhongYuanGroup.update_time.desc())
            return session.exec(statement).all()

    @classmethod
    def get_group_by_ids(cls, ids: List[int]) -> list[ZhongYuanGroup]:
        """根据主键ID列表批量查询"""
        if not ids:
            raise ValueError('ids is empty')
        with get_sync_db_session() as session:
            statement = select(ZhongYuanGroup).where(ZhongYuanGroup.id.in_(ids)).order_by(ZhongYuanGroup.update_time.desc())
            return session.exec(statement).all()

    @classmethod
    def get_group_by_org_ids(cls, org_ids: List[str]) -> list[ZhongYuanGroup]:
        """根据组织ID列表批量查询"""
        if not org_ids:
            raise ValueError('org_ids is empty')
        with get_sync_db_session() as session:
            statement = select(ZhongYuanGroup).where(ZhongYuanGroup.org_id.in_(org_ids))
            return session.exec(statement).all()

    @classmethod
    def delete_group(cls, id: int):
        """根据主键ID删除记录"""
        with get_sync_db_session() as session:
            session.exec(delete(ZhongYuanGroup).where(ZhongYuanGroup.id == id))
            session.commit()

    @classmethod
    def delete_group_by_org_id(cls, org_id: str):
        """根据组织ID删除记录"""
        with get_sync_db_session() as session:
            session.exec(delete(ZhongYuanGroup).where(ZhongYuanGroup.org_id == org_id))
            session.commit()

    @classmethod
    def update_group(cls, group: ZhongYuanGroup) -> ZhongYuanGroup:
        """全量更新记录"""
        with get_sync_db_session() as session:
            session.add(group)
            session.commit()
            session.refresh(group)
            return group

    @classmethod
    def update_group_partial(cls, id: int, update_data: ZhongYuanGroupUpdate) -> ZhongYuanGroup | None:
        """部分更新记录（仅更新非None字段）"""
        with get_sync_db_session() as session:
            # 查询原数据
            group = session.exec(select(ZhongYuanGroup).where(ZhongYuanGroup.id == id)).first()
            if not group:
                return None
            # 仅更新非None字段
            for key, value in update_data.dict(exclude_unset=True).items():
                if hasattr(group, key) and value is not None:
                    setattr(group, key, value)
            # 提交更新
            session.commit()
            session.refresh(group)
            return group

    @classmethod
    def update_group_update_user(cls, id: int, user_id: int):
        """更新最后更新人（对齐原有GroupDao）"""
        with get_sync_db_session() as session:
            statement = update(ZhongYuanGroup).where(ZhongYuanGroup.id == id).values(
                update_user=user_id,
                update_time=datetime.now()
            )
            session.exec(statement)
            session.commit()

    @classmethod
    def batch_insert_groups(cls, groups: List[ZhongYuanGroupCreate]) -> List[ZhongYuanGroup]:
        """批量创建记录（优化性能）"""
        if not groups:
            return []
        with get_sync_db_session() as session:
            group_list = []
            for group in groups:
                group_add = ZhongYuanGroup.validate(group)
                group_list.append(group_add)
            # 批量插入
            session.add_all(group_list)
            session.commit()
            # 刷新获取主键
            for g in group_list:
                session.refresh(g)
            return group_list
