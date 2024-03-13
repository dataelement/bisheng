from typing import Any, List

from bisheng.api.errcode.component import ComponentExistError, ComponentNotExistError
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.component import Component, ComponentDao


class ComponentService:
    @classmethod
    def get_all_component(cls, user: Any) -> UnifiedResponseModel[List[Component]]:
        res = ComponentDao.get_user_components(user.get('user_id'))
        return resp_200(data=res)

    @classmethod
    def save_component(cls, component: Component) -> UnifiedResponseModel[Component]:
        exist_component = ComponentDao.get_component_by_name(component.user_id, component.name)
        if exist_component:
            return ComponentExistError.return_resp()
        component = ComponentDao.insert_component(component)
        return resp_200(data=component)

    @classmethod
    def update_component(cls, component: Component) -> UnifiedResponseModel[Component]:
        exist_component = ComponentDao.get_component_by_name(component.user_id, component.name)
        if not exist_component:
            return ComponentNotExistError.return_resp()
        exist_component.data = component.data
        exist_component.description = component.description
        exist_component.version = component.version
        component = ComponentDao.update_component(exist_component)
        return resp_200(data=component)

    @classmethod
    def delete_component(cls, user_id: int, name: str) -> UnifiedResponseModel[Component]:
        exist_component = ComponentDao.get_component_by_name(user_id, name)
        if not exist_component:
            return ComponentNotExistError.return_resp()
        component = ComponentDao.delete_component(exist_component)
        return resp_200(data=component)
