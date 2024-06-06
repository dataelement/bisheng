import json
import os
import re
import time
from typing import List, Optional
from uuid import uuid4

from bisheng.api.services.knowledge_imp import (addEmbedding, decide_vectorstores,
                                                delete_knowledge_file_vectors, retry_files)
from bisheng.api.utils import access_check
from bisheng.api.v1.schemas import UnifiedResponseModel, UploadFileResponse, resp_200, resp_500
from bisheng.cache.utils import file_download, save_uploaded_file
from bisheng.database.base import session_getter
from bisheng.api.services.evaluation import EvaluationService
from bisheng.api.services.user_service import UserPayload
from bisheng.database.models.knowledge import (Knowledge, KnowledgeCreate, KnowledgeDao,
                                               KnowledgeRead)
from bisheng.database.models.knowledge_file import (KnowledgeFile, KnowledgeFileDao,
                                                    KnowledgeFileRead)
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.user import User
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.settings import settings
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient
from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, Form
from fastapi.encoders import jsonable_encoder
from fastapi_jwt_auth import AuthJWT
from fastapi import APIRouter, Body, Depends, HTTPException, Query, WebSocket, WebSocketException, UploadFile, File
from bisheng.database.models.evaluation import EvaluationRead, EvaluationCreate, Evaluation
from langchain_community.document_loaders import (BSHTMLLoader, PyPDFLoader, TextLoader,
                                                  UnstructuredMarkdownLoader,
                                                  UnstructuredPowerPointLoader,
                                                  UnstructuredWordDocumentLoader)
from pymilvus import Collection
from sqlalchemy import delete, func, or_
from sqlmodel import select

router = APIRouter(prefix='/evaluation', tags=['Skills'])


@router.get('', response_model=UnifiedResponseModel[List[Evaluation]])
def get_assistant(*,
                  name: str = Query(default=None, description='助手名称，模糊匹配, 包含描述的模糊匹配'),
                  page: Optional[int] = Query(default=1, gt=0, description='页码'),
                  limit: Optional[int] = Query(default=10, gt=0, description='每页条数'),
                  status: Optional[int] = Query(default=None, description='是否上线状态'),
                  Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    current_user = json.loads(Authorize.get_jwt_subject())
    user = UserPayload(**current_user)
    return EvaluationService.get_assistant(user, status, page, limit)


@router.post('/create', response_model=UnifiedResponseModel[EvaluationRead], status_code=201)
def create_evaluation(*,
                      file: UploadFile,
                      prompt: str = Form(),
                      exec_type: str = Form(),
                      unique_id: str = Form(),
                      version: Optional[int] = Form(default=None),
                      authorize: AuthJWT = Depends()):
    """ 创建评测任务. """
    authorize.jwt_required()
    payload = json.loads(authorize.get_jwt_subject())
    user_id = payload.get('user_id')

    db_evaluation = Evaluation.model_validate(
        EvaluationCreate(unique_id=unique_id,
                         exec_type=exec_type,
                         version=version,
                         prompt=prompt,
                         user_id=user_id))

    with session_getter() as session:
        session.add(db_evaluation)
        session.commit()
        session.refresh(db_evaluation)
    return resp_200(db_evaluation.copy())
