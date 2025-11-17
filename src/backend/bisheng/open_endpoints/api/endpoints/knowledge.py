from typing import List

from fastapi import APIRouter, Depends, BackgroundTasks, Body

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.knowledge.domain.schemas.knowledge_schema import AddKnowledgeMetadataFieldsReq, \
    UpdateKnowledgeMetadataFieldsReq
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.open_endpoints.api.dependencies import get_knowledge_service
from bisheng.open_endpoints.domain.utils import get_default_operator_async

router = APIRouter(prefix='/knowledge', tags=['OpenAPI', 'Knowledge'])


# Add Knowledge Metadata Fields Endpoint
@router.post('/add_metadata_fields', response_model=UnifiedResponseModel)
async def add_metadata_fields(*,
                              default_user: UserPayload = Depends(get_default_operator_async),
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

    knowledge_model = await knowledge_service.add_metadata_fields(default_user, req_data)

    return resp_200(data=knowledge_model)


@router.put("update_metadata_fields", response_model=UnifiedResponseModel)
async def update_metadata_fields(*,
                                 default_user: UserPayload = Depends(get_default_operator_async),
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

    knowledge_model = await knowledge_service.update_metadata_fields(
        default_user, req_data, background_tasks)
    return resp_200(data=knowledge_model)


@router.delete('/delete_metadata_fields', response_model=UnifiedResponseModel)
async def delete_metadata_fields(*,
                                 default_user: UserPayload = Depends(get_default_operator_async),
                                 knowledge_id: int = Body(..., embed=True, description="Knowledge ID"),
                                 field_names: List[str] = Body(..., embed=True,
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

    knowledge_model = await knowledge_service.delete_metadata_fields(
        default_user, knowledge_id, field_names, background_tasks)

    return resp_200(data=knowledge_model)


@router.get('/list_metadata_fields', response_model=UnifiedResponseModel)
async def list_metadata_fields(*,
                               default_user: UserPayload = Depends(get_default_operator_async),
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
