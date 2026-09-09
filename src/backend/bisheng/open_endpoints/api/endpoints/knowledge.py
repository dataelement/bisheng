
from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, UploadFile

from bisheng.api.v1.schemas import UploadFileResponse
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.knowledge.domain.schemas.knowledge_schema import (
    AddKnowledgeMetadataFieldsReq,
    ModifyKnowledgeFileMetaDataReq,
    UpdateKnowledgeMetadataFieldsReq,
)
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.temp_upload_service import TempUploadService
from bisheng.open_api.api.dependencies import get_open_api_execution
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_api.domain.services.session_subject_service import session_subject_from_principal
from bisheng.open_endpoints.api.dependencies import get_knowledge_file_service, get_knowledge_service
from bisheng.open_endpoints.domain.schemas.knowledge import DeleteUserMetadataReq
from bisheng.open_endpoints.domain.utils import get_open_api_operator_async

router = APIRouter(prefix='/knowledge', tags=['OpenAPI', 'Knowledge'])


@router.post("/upload", response_model=UnifiedResponseModel[UploadFileResponse])
@open_api_scope("chat:invoke", session=True)
async def upload_daily_attachment(
    file: UploadFile = File(...),
    principal: OpenApiPrincipal = Depends(get_open_api_execution),
):
    try:
        result = await TempUploadService.upload(file, session_subject_from_principal(principal))
        return resp_200(
            data=UploadFileResponse(
                file_path=result.file_path,
                relative_path=result.relative_path,
                file_name=result.file_name,
            )
        )
    finally:
        await file.close()


# Add Knowledge Metadata Fields Endpoint
@router.post('/add_metadata_fields', response_model=UnifiedResponseModel)
@open_api_scope("knowledge:write")
async def add_metadata_fields(*,
                              default_user: UserPayload = Depends(get_open_api_operator_async),
                              req_data: AddKnowledgeMetadataFieldsReq,
                              knowledge_service: KnowledgeService = Depends(get_knowledge_service)):
    """
    Add metadata fields to a knowledge base.
    Args:
        default_user:
        req_data:
        knowledge_service:

    Returns:

    """

    await knowledge_service.add_metadata_fields(default_user, req_data)

    return resp_200(data=True)


@router.put("/modify_metadata_fields", response_model=UnifiedResponseModel)
@open_api_scope("knowledge:write")
async def update_metadata_fields(*,
                                 default_user: UserPayload = Depends(get_open_api_operator_async),
                                 req_data: UpdateKnowledgeMetadataFieldsReq,
                                 knowledge_service: KnowledgeService = Depends(get_knowledge_service),
                                 background_tasks: BackgroundTasks):
    """
     Update metadata fields in a knowledge base.
    Args:
        default_user:
        req_data:
        knowledge_service:
        background_tasks:

    Returns:

    """

    await knowledge_service.update_metadata_fields(
        default_user, req_data, background_tasks)
    return resp_200(data=True)


@router.delete('/delete_metadata_fields', response_model=UnifiedResponseModel)
@open_api_scope("knowledge:write")
async def delete_metadata_fields(*,
                                 default_user: UserPayload = Depends(get_open_api_operator_async),
                                 knowledge_id: int = Body(..., embed=True, description="Knowledge ID"),
                                 field_names: list[str] = Body(..., embed=True,
                                                               description="List of field names to delete"),
                                 knowledge_service: KnowledgeService = Depends(get_knowledge_service),
                                 background_tasks: BackgroundTasks):
    """
    Delete metadata fields from a knowledge base.
    Args:
        default_user:
        knowledge_id:
        field_names:
        knowledge_service:
        background_tasks:
    Returns:
    """

    await knowledge_service.delete_metadata_fields(
        default_user, knowledge_id, field_names, background_tasks)

    return resp_200(data=True)


@router.get('/get_metadata_fields/{knowledge_id}', response_model=UnifiedResponseModel)
@open_api_scope("knowledge:write")
async def list_metadata_fields(*,
                               default_user: UserPayload = Depends(get_open_api_operator_async),
                               knowledge_id: int,
                               knowledge_service: KnowledgeService = Depends(get_knowledge_service)):
    """
    List metadata fields of a knowledge base.
    Args:
         default_user:
         knowledge_id:
         knowledge_service:

    Returns:

    """

    metadata_fields = await knowledge_service.list_metadata_fields(default_user, knowledge_id)

    return resp_200(data=metadata_fields)


@router.post('/file/add_user_metadata', response_model=UnifiedResponseModel)
@open_api_scope("knowledge:write")
async def add_file_user_metadata(*,
                                 default_user: UserPayload = Depends(get_open_api_operator_async),
                                 knowledge_id: int = Body(..., embed=True, description="Knowledge ID"),
                                 add_metadata_list: list[ModifyKnowledgeFileMetaDataReq] = Body(...,
                                                                                                description="File User Metadata List"),
                                 knowledge_file_service: KnowledgeFileService = Depends(get_knowledge_file_service)):
    """
    Add user metadata to a knowledge file.
    Args:
        knowledge_id:
        add_metadata_list:
        default_user:
        knowledge_file_service:

    Returns:

    """

    await knowledge_file_service.add_file_user_metadata(
        default_user, knowledge_id, add_metadata_list)

    return resp_200(data=True)


@router.put('/file/modify_user_metadata', response_model=UnifiedResponseModel)
@open_api_scope("knowledge:write")
async def modify_file_user_metadata(*,
                                    default_user: UserPayload = Depends(get_open_api_operator_async),
                                    knowledge_id: int = Body(..., embed=True, description="Knowledge ID"),
                                    modify_metadata_list: list[ModifyKnowledgeFileMetaDataReq] = Body(...,
                                                                                                      description="File User Metadata List"),
                                    knowledge_file_service: KnowledgeFileService = Depends(
                                        get_knowledge_file_service)):
    """
    Modify user metadata of a knowledge file.
    Args:
        modify_metadata_list:
        knowledge_id:
        default_user:
        knowledge_file_service:

    Returns:

    """

    await knowledge_file_service.batch_modify_file_user_metadata(default_user, knowledge_id,
                                                                 modify_metadata_list)

    return resp_200(data=True)


@router.delete('/file/delete_user_metadata', response_model=UnifiedResponseModel)
@open_api_scope("knowledge:write")
async def delete_file_user_metadata(*,
                                    default_user: UserPayload = Depends(get_open_api_operator_async),
                                    knowledge_id: int = Body(..., embed=True, description="Knowledge ID"),
                                    delete_user_metadatas: list[DeleteUserMetadataReq] = Body(...,
                                                                                              description="Delete User Metadata List"),
                                    knowledge_file_service: KnowledgeFileService = Depends(
                                        get_knowledge_file_service)):
    """
    Delete user metadata from a knowledge file.
    Args:
        default_user:
        knowledge_id:
        delete_user_metadatas:
        knowledge_file_service:

    Returns:

    """

    await knowledge_file_service.batch_delete_file_user_metadata(
        default_user, knowledge_id, delete_user_metadatas)

    return resp_200(data=True)


@router.post('/file/list_user_metadata', response_model=UnifiedResponseModel)
@open_api_scope("knowledge:write")
async def list_file_user_metadata(*,
                                  default_user: UserPayload = Depends(get_open_api_operator_async),
                                  knowledge_id: int = Body(..., embed=True, description="Knowledge ID"),
                                  knowledge_file_ids: list[int] = Body(..., description="Knowledge File IDs"),
                                  knowledge_file_service: KnowledgeFileService = Depends(
                                      get_knowledge_file_service)):
    """
    List user metadata of knowledge files.
    Args:
        default_user:
        knowledge_id:
        knowledge_file_ids:
        knowledge_file_service:

    Returns:

    """

    metadata_list = await knowledge_file_service.list_knowledge_file_user_metadata(
        default_user, knowledge_id, knowledge_file_ids)

    return resp_200(data=metadata_list)
