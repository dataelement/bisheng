"""Dictionary domain service - 系统字典业务逻辑层"""

from io import BytesIO

import openpyxl
import pandas as pd
from fastapi import UploadFile
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dictionary import (
    DictionaryDuplicateError,
    DictionaryExportEmptyError,
    DictionaryImportFileEmptyError,
    DictionaryImportFormatError,
    DictionaryImportHeaderError,
    DictionaryImportParseError,
    DictionaryImportTypeInvalidError,
    DictionaryNotFoundError,
    DictionaryPermissionDeniedError,
)
from bisheng.common.schemas.api import PageData
from bisheng.dictionary.domain.models.system_dictionary import SystemDictionary
from bisheng.dictionary.domain.repositories.interfaces.system_dictionary_repository import (
    SystemDictionaryRepository,
)
from bisheng.dictionary.domain.schemas.dictionary_schema import (
    DICTIONARY_EXPORT_HEADERS,
    DICTIONARY_TYPE_CODE_TO_LABEL,
    DICTIONARY_TYPE_LABEL_TO_CODE,
    DictionaryCreateRequest,
    DictionaryImportResult,
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

        if request.dict_key is not None:
            entity.dict_key = request.dict_key

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

    async def get_list_by_type(self, dict_type: str, page: int = 1, page_size: int = 20) -> list[DictionaryResponse]:
        """根据 dict_type 查询启用的字典条目列表"""
        entities = await self.repository.find_by_type(dict_type, page, page_size)
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
        sort_by: bool | None = None,
        is_enabled: bool | None = None,
    ) -> PageData[DictionaryResponse]:
        """分页查询字典条目"""
        entities, total = await self.repository.find_page(
            dict_type=dict_type,
            keyword=keyword,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            is_enabled=is_enabled,
        )
        data = [DictionaryResponse.model_validate(entity) for entity in entities]
        return PageData(data=data, total=total)

    async def export(self, user: UserPayload, dict_type: str | None = None) -> bytes:
        """导出字典数据为 Excel 字节流,管理员权限"""
        self._ensure_admin(user)

        entities = await self.repository.find_all_for_export(dict_type)
        if not entities:
            raise DictionaryExportEmptyError()

        rows = []
        for entity in entities:
            rows.append(
                {
                    "类型": DICTIONARY_TYPE_CODE_TO_LABEL.get(entity.type, entity.type),
                    "字典键": entity.dict_key,
                    "字典取值": entity.dict_value,
                    "排序权重": entity.sort_order,
                    "是否启用": "是" if entity.is_enabled else "否",
                }
            )

        df = pd.DataFrame(rows, columns=DICTIONARY_EXPORT_HEADERS)
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="字典数据", index=False)
        bio.seek(0)
        return bio.getvalue()

    async def import_excel(self, user: UserPayload, file: UploadFile) -> DictionaryImportResult:
        """从 Excel 导入字典数据,管理员权限"""
        self._ensure_admin(user)

        if not file.filename:
            raise DictionaryImportFileEmptyError()

        if not file.filename.lower().endswith((".xlsx", ".xls")):
            raise DictionaryImportFormatError()

        contents = await file.read()
        if not contents:
            raise DictionaryImportFileEmptyError()

        try:
            wb = openpyxl.load_workbook(BytesIO(contents), data_only=True)
        except Exception as exc:
            logger.exception("Failed to parse dictionary import excel")
            raise DictionaryImportParseError() from exc

        sheet = wb.active
        if sheet is None:
            raise DictionaryImportParseError()

        # 读取表头
        header_row = next(sheet.iter_rows(values_only=True), None)
        if header_row is None:
            raise DictionaryImportHeaderError()

        headers = [str(cell).strip() if cell is not None else "" for cell in header_row]
        if headers != DICTIONARY_EXPORT_HEADERS:
            raise DictionaryImportHeaderError()

        total = 0
        success = 0
        failed = 0
        errors: list[str] = []
        seen_keys: set[tuple[str, str]] = set()

        # 从第二行开始读取数据
        for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            # 跳过完全空行
            if all(cell is None or str(cell).strip() == "" for cell in row):
                continue

            total += 1

            try:
                if len(row) < len(DICTIONARY_EXPORT_HEADERS):
                    raise ValueError("insufficient columns")

                type_label = str(row[0]).strip() if row[0] is not None else ""
                dict_key = str(row[1]).strip() if row[1] is not None else ""
                dict_value = str(row[2]).strip() if row[2] is not None else ""
                sort_order_raw = row[3]
                is_enabled_raw = row[4]

                if not type_label:
                    raise ValueError("type is required")
                if not dict_key:
                    raise ValueError("dict_key is required")
                if not dict_value:
                    raise ValueError("dict_value is required")

                dict_type = DICTIONARY_TYPE_LABEL_TO_CODE.get(type_label)
                if not dict_type:
                    raise DictionaryImportTypeInvalidError()

                unique_key = (dict_type, dict_key)
                if unique_key in seen_keys:
                    raise ValueError(f"duplicate dict_key '{dict_key}' under type '{type_label}' in Excel")
                seen_keys.add(unique_key)

                try:
                    sort_order = int(sort_order_raw) if sort_order_raw is not None else 0
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"invalid sort_order: {sort_order_raw}") from exc

                if isinstance(is_enabled_raw, bool):
                    is_enabled = is_enabled_raw
                else:
                    is_enabled_str = str(is_enabled_raw).strip() if is_enabled_raw is not None else ""
                    is_enabled = is_enabled_str in ("是", "True", "true", "1", "Y", "y")

                existing = await self.repository.find_by_type_and_key(dict_type, dict_key)
                if existing:
                    existing.dict_value = dict_value
                    existing.sort_order = sort_order
                    existing.is_enabled = is_enabled
                    await self.repository.update(existing)
                else:
                    entity = SystemDictionary(
                        type=dict_type,
                        dict_key=dict_key,
                        dict_value=dict_value,
                        sort_order=sort_order,
                        is_enabled=is_enabled,
                    )
                    await self.repository.save(entity)

                success += 1
            except Exception as exc:
                failed += 1
                reason = str(exc)
                errors.append(f"第 {row_idx} 行导入失败: {reason}")

        return DictionaryImportResult(total=total, success=success, failed=failed, errors=errors)
