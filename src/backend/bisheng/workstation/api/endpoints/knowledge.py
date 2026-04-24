from datetime import datetime
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Body, File, Request, UploadFile

from bisheng.api.v1.schemas import resp_200
from bisheng.common.errcode.http_error import ServerError
from bisheng.core.cache.utils import save_download_file, save_uploaded_file
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.workstation.domain.services import WorkStationService

from ..dependencies import LoginUserDep

router = APIRouter()


@router.post('/knowledgeUpload')
def knowledge_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    login_user=LoginUserDep,
):
    try:
        file_path = save_download_file(file.file, 'bisheng', file.filename)
        res = WorkStationService.uploadPersonalKnowledge(
            request,
            login_user,
            file_path=file_path,
            background_tasks=background_tasks,
        )
        return resp_200(data=res[0])
    except Exception as exc:
        raise ServerError(msg=f'Knowledge base upload failed: {str(exc)}', exception=exc)
    finally:
        file.file.close()


@router.get('/queryKnowledge')
async def query_knowledge_list(request: Request, page: int, size: int, login_user=LoginUserDep):
    res, total = await WorkStationService.queryKnowledgeList(request, login_user, page, size)
    return resp_200(data={'list': res, 'total': total})


@router.delete('/deleteKnowledge')
def delete_knowledge(request: Request, file_id: int, login_user=LoginUserDep):
    res = KnowledgeService.delete_knowledge_file(request, login_user, [file_id])
    return resp_200(data=res)


@router.post('/files')
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    file_id: str = Body(..., description='Doc.ID'),
    login_user=LoginUserDep,
):
    try:
        file_path = await save_uploaded_file(file, 'bisheng', unquote(file.filename))
        return resp_200(
            data={
                'filepath': file_path,
                'filename': unquote(file.filename),
                'type': file.content_type,
                'user': login_user.user_id,
                '_id': uuid4().hex,
                'createdAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'updatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'temp_file_id': file_id,
                'file_id': uuid4().hex,
                'message': 'File uploaded successfully',
                'context': 'message_attachment',
            }
        )
    except Exception as exc:
        raise ServerError(msg=f'File upload failed: {str(exc)}', exception=exc)
    finally:
        await file.close()
