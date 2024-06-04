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
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi_jwt_auth import AuthJWT
from bisheng.database.models.evaluation import EvaluationRead, EvaluationCreate, Evaluation
from langchain_community.document_loaders import (BSHTMLLoader, PyPDFLoader, TextLoader,
                                                  UnstructuredMarkdownLoader,
                                                  UnstructuredPowerPointLoader,
                                                  UnstructuredWordDocumentLoader)
from pymilvus import Collection
from sqlalchemy import delete, func, or_
from sqlmodel import select

router = APIRouter(prefix='/evaluation', tags=['Skills'])


@router.post('/create', response_model=UnifiedResponseModel[EvaluationRead], status_code=201)
def create_evaluation(*, evaluation: EvaluationCreate, authorize: AuthJWT = Depends()):
    """ 创建评测任务. """
    authorize.jwt_required()
    payload = json.loads(authorize.get_jwt_subject())
    user_id = payload.get('user_id')

    db_evaluation = Evaluation.model_validate(evaluation)

    db_evaluation.user_id = user_id
    with session_getter() as session:
        session.add(db_evaluation)
        session.commit()
        session.refresh(db_evaluation)
    return resp_200(db_evaluation.copy())
