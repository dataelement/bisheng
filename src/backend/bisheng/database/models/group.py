from datetime import datetime
from typing import Dict, List, Optional, Any

from sqlmodel import Field, select, Column, DateTime, delete, text, update

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable

# 默认用户组的ID
DefaultGroup = 2


class GroupBase(SQLModelSerializable):
    id: Optional[int] = Field(default=None, primary_key=True)
    parent_id: int = Field(default=0, index=True, description='父级用户组ID')
    code: Optional[str] = Field(default=None, index=True, unique=True,
                                description='用户组路径，从根节点到当前节点的code路径')
    level: Optional[int] = Field(default=0, index=True, description='用户组层级')
    third_id: Optional[str] = Field(default=0, index=True, description='第三方用户组唯一标识。例如对应到企微里的部门ID')
    group_name: str = Field(index=False, description='前端展示名称', unique=True)
    remark: Optional[str] = Field(index=False)
    create_user: Optional[int] = Field(index=True, description="创建用户的ID")
    update_user: Optional[int] = Field(description="更新用户的ID")
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Group(GroupBase, table=True):
    # id = 2 表示默认用户组
    pass


class GroupRead(GroupBase):
    group_admins: Optional[List[Dict]]

    # 记录从根节点到当前节点的name路径  a/b/c
    parent_group_path: Optional[str]

    # 子用户组
    children: Optional[List[Any]]


class GroupUpdate(GroupBase):
    role_name: Optional[str]
    remark: Optional[str]


class GroupCreate(GroupBase):
    group_admins: Optional[List[int]]


class GroupDao(GroupBase):

    @staticmethod
    def generate_group_code(parent_code: str, current_level_code: str = None) -> str:
        """
        parent_code: 表示父用户组的code
        current_level_code: 表示当前用户组所在层级的最新code
         001: 代表第一层级的第一个用户组
         001|001: 代表第二层级的第一个用户组，且父用户组属于编码为A1的用户组
        """
        level_num = 1
        if current_level_code:
            level_num = int(current_level_code.split('|')[-1]) + 1
        if parent_code:
            return f'{parent_code}|{level_num:0>3}'
        else:
            return f'{level_num:0>3}'

    @staticmethod
    def parse_parent_code(group_code: str) -> List[str]:
        """ 解析出父用户组的code """
        code_list = group_code.split('|')
        if len(code_list) == 1:
            return []
        res = []
        prev = ''
        for one in code_list[:-1]:
            prev = f'{prev}|{one}' if prev else one
            res.append(prev)
        return res

    @classmethod
    def get_user_group(cls, group_id: int) -> Group | None:
        with session_getter() as session:
            statement = select(Group).where(Group.id == group_id)
            return session.exec(statement).first()

    @classmethod
    def insert_group(cls, group: GroupCreate) -> Group:
        """ 插入用户组，设置用户组的code和层级 """
        with session_getter() as session:
            group_add = Group.validate(group)

            # 判断所属的父用户组
            parent_group_code = ""
            if group.parent_id != 0:
                parent_group = session.exec(select(Group).where(Group.id == group.parent_id)).first()
                if not parent_group:
                    raise ValueError('父级用户组不存在')
                group_add.level = parent_group.level + 1
                parent_group_code = parent_group.code
            else:
                group_add.level = 0

            # 查询当前层级最新的用户组的code
            tmp = select(Group).where(Group.level == group_add.level).order_by(Group.id.desc()).limit(1)
            latest_group = session.exec(tmp).first()
            group_add.code = cls.generate_group_code(parent_group_code, latest_group.code if latest_group else None)

            session.add(group_add)
            session.commit()
            session.refresh(group_add)
            return group_add

    @classmethod
    def get_all_group(cls) -> list[Group]:
        with session_getter() as session:
            statement = select(Group).order_by(Group.update_time.desc())
            return session.exec(statement).all()

    @classmethod
    def get_group_by_ids(cls, ids: List[int]) -> list[Group]:
        if not ids:
            raise ValueError('ids is empty')
        with session_getter() as session:
            statement = select(Group).where(Group.id.in_(ids)).order_by(Group.update_time.desc())
            return session.exec(statement).all()

    @classmethod
    def delete_group(cls, group_id: int):
        with session_getter() as session:
            session.exec(delete(Group).where(Group.id == group_id))
            session.commit()

    @classmethod
    def update_group(cls, group: Group) -> Group:
        with session_getter() as session:
            session.add(group)
            session.commit()
            session.refresh(group)
            return group

    @classmethod
    def update_groups(cls, groups: List[Group]) -> List[Group]:
        with session_getter() as session:
            session.add_all(groups)
            session.commit()
            return groups

    @classmethod
    def update_group_update_user(cls, group_id: int, user_id: int):
        """ 提供给闭源模块 """
        with session_getter() as session:
            statement = update(Group).where(Group.id == group_id).values(update_user=user_id,
                                                                         update_time=datetime.now())
            session.exec(statement)
            session.commit()

    @classmethod
    def get_child_groups(cls, group_code: str, level: int = None) -> list[Group]:
        """ 获取指定用户组的子用户组 """
        statement = select(Group).where(Group.code.like(f'{group_code}%')).where(Group.code != group_code)
        if level:
            statement = statement.where(Group.level == level)
        statement = statement.order_by(Group.id.asc())
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def get_child_groups_by_id(cls, group_id: int) -> list[Group]:
        """ 获取指定用户组的直接子用户组 """
        with session_getter() as session:
            statement = select(Group).where(Group.parent_id == group_id)
            return session.exec(statement).all()

    @classmethod
    def get_parent_groups(cls, group_code: str, level: int = None) -> List[Group]:
        """ 获取指定用户组的父用户组 """
        parent_group_code = cls.parse_parent_code(group_code)
        if not parent_group_code:
            return []
        statement = select(Group).where(Group.code.in_(parent_group_code))
        if level:
            statement = statement.where(Group.level == level)
        statement = statement.order_by(Group.id.asc())
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def get_parent_groups_by_ids(cls, group_ids: list[int], level: int = None) -> List[Group]:
        """ 获取指定用户组的父用户组 """
        if not group_ids:
            return []
        statement = select(Group).where(Group.id.in_(group_ids))
        if level:
            statement = statement.where(Group.level == level)
        statement = statement.order_by(Group.id.asc())
        with session_getter() as session:
            all_groups = session.exec(statement).all()
            if not all_groups:
                return []
            # 获取所有的父用户组的code
            parent_group_code = []
            for one in all_groups:
                parent_group_code.extend(cls.parse_parent_code(one.code))
            parent_group_code = list(set(parent_group_code))
            if not parent_group_code:
                return []
            # 获取所有的父用户组
            return session.exec(select(Group).where(Group.code.in_(parent_group_code))).all()

    @classmethod
    def get_group_by_code(cls, group_code: str) -> Group | None:
        with session_getter() as session:
            statement = select(Group).where(Group.code == group_code)
            return session.exec(statement).first()
