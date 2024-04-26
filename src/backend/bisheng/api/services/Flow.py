from typing import List, Dict

from fastapi.encoders import jsonable_encoder

from bisheng.api.errcode.flow import NotFoundVersionError, CurVersionDelError, VersionNameExistsError, \
    NotFoundFlowError, \
    FlowOnlineEditError
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200, FlowVersionCreate
from bisheng.database.models.flow import FlowDao, FlowStatus
from bisheng.database.models.flow_version import FlowVersionDao, FlowVersionRead, FlowVersion
from bisheng.database.models.role_access import RoleAccessDao, AccessType
from bisheng.database.models.user import UserDao
from bisheng.database.models.user_role import UserRoleDao


class FlowService:
    @classmethod
    def get_version_list_by_flow(cls, user: UserPayload, flow_id: str) -> UnifiedResponseModel[List[FlowVersionRead]]:
        """
        根据技能ID 获取技能的所有版本信息
        """
        data = FlowVersionDao.get_list_by_flow(flow_id)
        return resp_200(data=data)

    @classmethod
    def get_version_info(cls, user: UserPayload, version_id: int) -> UnifiedResponseModel[FlowVersion]:
        """
        根据版本ID获取版本详细信息
        """
        data = FlowVersionDao.get_version_by_id(version_id)
        return resp_200(data=data)

    @classmethod
    def delete_version(cls, user: UserPayload, version_id: int) -> UnifiedResponseModel[None]:
        """
        根据版本ID删除版本
        """
        version_info = FlowVersionDao.get_version_by_id(version_id)
        if not version_info:
            return NotFoundVersionError.return_resp()
        if version_info.is_current == 1:
            return CurVersionDelError.return_resp()

        FlowVersionDao.delete_flow_version(version_id)
        return resp_200()

    @classmethod
    def change_current_version(cls, user: UserPayload, flow_id: str, version_id: int) -> UnifiedResponseModel[None]:
        """
        修改当前版本
        """
        # 技能上线状态不允许 切换版本
        flow_info = FlowDao.get_flow_by_id(flow_id)
        if not flow_info:
            return NotFoundFlowError.return_resp()
        if flow_info.status == FlowStatus.ONLINE:
            return FlowOnlineEditError.return_resp()

        # 切换版本
        version_info = FlowVersionDao.get_version_by_id(version_id)
        if not version_info:
            return NotFoundVersionError.return_resp()
        if version_info.is_current == 1:
            return resp_200()

        # 修改当前版本为用户选择的版本
        FlowVersionDao.change_current_version(flow_id, version_info)
        return resp_200()

    @classmethod
    def create_new_version(cls, user: UserPayload, flow_id: str, flow_version: FlowVersionCreate) -> \
            UnifiedResponseModel[FlowVersion]:
        """
        创建新版本
        """
        exist_version = FlowVersionDao.get_version_by_name(flow_id, flow_version.name)
        if exist_version:
            return VersionNameExistsError.return_resp()

        flow_version = FlowVersion(flow_id=flow_id, name=flow_version.name, description=flow_version.description,
                                   data=flow_version.data)

        flow_version = FlowVersionDao.create_version(flow_version)
        return resp_200(data=flow_version)

    @classmethod
    def update_version_info(cls, user: UserPayload, version_id: int, flow_version: FlowVersionCreate) \
            -> UnifiedResponseModel[FlowVersion]:
        """
        更新版本信息
        """

        version_info = FlowVersionDao.get_version_by_id(version_id)
        if not version_info:
            return NotFoundVersionError.return_resp()

        # 版本是当前版本, 且技能处于上线状态则不可编辑
        if version_info.is_current == 1:
            # 技能上线状态不允许编辑
            flow_info = FlowDao.get_flow_by_id(version_info.flow_id)
            if not flow_info:
                return NotFoundFlowError.return_resp()
            if flow_info.status == FlowStatus.ONLINE:
                return FlowOnlineEditError.return_resp()

        version_info.name = flow_version.name if flow_version.name else version_info.name
        version_info.description = flow_version.description if flow_version.description else version_info.description
        version_info.data = flow_version.data if flow_version.data else version_info.data

        flow_version = FlowVersionDao.update_version(version_info)
        return resp_200(data=flow_version)

    @classmethod
    def get_all_flows(cls, user: UserPayload, name: str, status: int, page: int = 1, page_size: int = 10) -> \
            UnifiedResponseModel[List[Dict]]:
        """
        获取所有技能
        """
        # 获取用户可见的技能列表
        if user.is_admin():
            data = FlowDao.get_flows(user.user_id, "admin", name, status, page, page_size)
            total = FlowDao.count_flows(user.user_id, "admin", name, status)
        else:
            user_role = UserRoleDao.get_user_roles(user.user_id)
            role_ids = [role.role_id for role in user_role]
            role_access = RoleAccessDao.get_role_access(role_ids, AccessType.FLOW)
            flow_id_extra = []
            if role_access:
                flow_id_extra = [access.third_id for access in role_access]
            data = FlowDao.get_flows(user.user_id, flow_id_extra, name, status, page, page_size)
            total = FlowDao.count_flows(user.user_id, flow_id_extra, name, status)

        # 获取技能列表对应的用户信息和版本信息
        # 技能ID列表
        flow_ids = []
        # 技能创建用户的ID列表
        user_ids = []
        for one in data:
            flow_ids.append(one.id.hex)
            user_ids.append(one.user_id)
        # 获取列表内的用户信息
        user_infos = UserDao.get_user_by_ids(user_ids)
        user_dict = {one.user_id: one.user_name for one in user_infos}

        # 获取列表内的版本信息
        version_infos = FlowVersionDao.get_list_by_flow_ids(flow_ids)
        flow_versions = {}
        for one in version_infos:
            if one.flow_id not in flow_versions:
                flow_versions[one.flow_id] = []
            flow_versions[one.flow_id].append(jsonable_encoder(one))

        # 重新拼接技能列表list信息
        res = []
        for one in data:
            flow_info = jsonable_encoder(one)
            flow_info['user_name'] = user_dict.get(one.user_id, one.user_id)
            flow_info['write'] = True if user.is_admin() or user.user_id == one.user_id else False
            flow_info['version_list'] = flow_versions.get(one.id.hex, [])
            res.append(flow_info)

        return resp_200(data={
            "data": res,
            "total": total
        })
