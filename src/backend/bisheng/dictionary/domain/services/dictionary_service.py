"""Dictionary domain service - 系统字典业务逻辑层"""

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dictionary import (
    DictionaryDuplicateError,
    DictionaryNotFoundError,
    DictionaryPermissionDeniedError,
)
from bisheng.common.schemas.api import PageData
from bisheng.dictionary.domain.models.system_dictionary import SystemDictionary
from bisheng.dictionary.domain.repositories.interfaces.system_dictionary_repository import (
    SystemDictionaryRepository,
)
from bisheng.dictionary.domain.schemas.dictionary_schema import (
    DictionaryCreateRequest,
    DictionaryResponse,
    DictionaryTypeEnum,
    DictionaryTypeResponse,
    DictionaryUpdateRequest,
)


class DictionaryService:
    """系统字典业务服务"""

    def __init__(self, repository: SystemDictionaryRepository):
        self.repository = repository

    @staticmethod
    def _ensure_admin(user: UserPayload) -> None:
        """校验当前用户是否为管理员,否则抛出权限错误"""
        if not user.is_admin():
            raise DictionaryPermissionDeniedError()

    async def create(
        self,
        request: DictionaryCreateRequest,
        user: UserPayload,
    ) -> DictionaryResponse:
        """新增字典条目(管理员)"""
        self._ensure_admin(user)

        existing = await self.repository.find_by_type_and_key(request.type, request.dict_key)
        if existing:
            raise DictionaryDuplicateError()

        entity = SystemDictionary(
            type=request.type,
            dict_key=request.dict_key,
            dict_value=request.dict_value,
            sort_order=request.sort_order,
            is_enabled=request.is_enabled,
        )
        saved = await self.repository.save(entity)
        return DictionaryResponse.model_validate(saved)

    async def update(
        self,
        dictionary_id: int,
        request: DictionaryUpdateRequest,
        user: UserPayload,
    ) -> DictionaryResponse:
        """更新字典条目(管理员)"""
        self._ensure_admin(user)

        entity = await self.repository.find_by_id(dictionary_id)
        if not entity:
            raise DictionaryNotFoundError()

        if request.dict_value is not None:
            entity.dict_value = request.dict_value

        if request.sort_order is not None:
            entity.sort_order = request.sort_order

        if request.is_enabled is not None:
            entity.is_enabled = request.is_enabled

        updated = await self.repository.update(entity)
        return DictionaryResponse.model_validate(updated)

    async def delete(
        self,
        dictionary_id: int,
        user: UserPayload,
    ) -> bool:
        """删除字典条目(管理员)"""
        self._ensure_admin(user)

        entity = await self.repository.find_by_id(dictionary_id)
        if not entity:
            raise DictionaryNotFoundError()

        return await self.repository.delete(dictionary_id)

    async def get_by_id(self, dictionary_id: int) -> DictionaryResponse:
        """根据 ID 查询字典条目"""
        entity = await self.repository.find_by_id(dictionary_id)
        if not entity:
            raise DictionaryNotFoundError()
        return DictionaryResponse.model_validate(entity)

    async def find_by_type_and_key(self, dict_type: str, dict_key: str) -> DictionaryResponse:
        """根据 dict_type 和 dict_key 查询启用的字典条目"""
        entity = await self.repository.find_by_type_and_key(dict_type, dict_key)
        if not entity:
            raise DictionaryNotFoundError()
        return DictionaryResponse.model_validate(entity)

    async def get_list_by_type(self, dict_type: str) -> list[DictionaryResponse]:
        """根据 dict_type 查询启用的字典条目列表"""
        entities = await self.repository.find_by_type(dict_type)
        if not entities:
            raise DictionaryNotFoundError()
        return [DictionaryResponse.model_validate(entity) for entity in entities]

    async def list_by_type(self) -> list[DictionaryTypeResponse]:
        """查询所有字典类型"""
        return [DictionaryTypeResponse(name=member.value, type=member.name.lower()) for member in DictionaryTypeEnum]

    async def list_page(
        self,
        dict_type: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PageData[DictionaryResponse]:
        """分页查询字典条目"""
        entities, total = await self.repository.find_page(
            dict_type=dict_type,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        data = [DictionaryResponse.model_validate(entity) for entity in entities]
        return PageData(data=data, total=total)
