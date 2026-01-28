import io
from typing import Optional

from datasets import Dataset
from fastapi import APIRouter, Depends, Query, UploadFile, Form, BackgroundTasks

from bisheng.api.services.evaluation import EvaluationService, add_evaluation_task
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.server import UploadFileExtError
from bisheng.core.cache.utils import convert_encoding_cchardet
from bisheng.core.database import get_sync_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.evaluation import EvaluationCreate, Evaluation

router = APIRouter(prefix='/evaluation', tags=['Evaluation'], dependencies=[Depends(UserPayload.get_login_user)])


@router.get('')
def get_evaluation(*,
                   page: Optional[int] = Query(default=1, gt=0, description='Page'),
                   limit: Optional[int] = Query(default=10, gt=0, description='Listings Per Page'),
                   login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get a list of assessment tasks. """
    return EvaluationService.get_evaluation(login_user, page, limit)


@router.post('')
def create_evaluation(*,
                      file: UploadFile,
                      prompt: str = Form(),
                      exec_type: str = Form(),
                      unique_id: str = Form(),
                      version: Optional[int | str] = Form(default=None),
                      background_tasks: BackgroundTasks,
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Create Assessment Task. """
    user_id = login_user.user_id
    if not version:
        version = 0

    try:
        # Try transcoding
        output_file = convert_encoding_cchardet(file_io=io.BytesIO(file.file.read()))
        csv_data = EvaluationService.parse_csv(file_data=output_file)
        data_samples = {
            "question": [one.get('question') for one in csv_data],
            "answer": [one.get('answer') for one in csv_data],
            "ground_truths": [[one.get('ground_truth')] for one in csv_data]
        }
        dataset = Dataset.from_dict(data_samples)
    except Exception:
        raise UploadFileExtError()
    finally:
        file.file.seek(0)

    file_name, file_path = EvaluationService.upload_file(file=file)
    db_evaluation = Evaluation.model_validate(EvaluationCreate(unique_id=unique_id,
                                                               exec_type=exec_type,
                                                               version=version,
                                                               prompt=prompt,
                                                               user_id=user_id,
                                                               file_name=file_name,
                                                               file_path=file_path))
    with get_sync_db_session() as session:
        session.add(db_evaluation)
        session.commit()
        session.refresh(db_evaluation)

    background_tasks.add_task(add_evaluation_task, evaluation_id=db_evaluation.id)

    return resp_200(db_evaluation.copy())


@router.delete('/{evaluation_id}', status_code=200)
def delete_evaluation(*, evaluation_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Delete Assessment Task (Logical Delete). """
    return EvaluationService.delete_evaluation(evaluation_id, user_payload=login_user)


@router.get('/result/file/download')
async def get_download_url(*,
                           file_url: str,
                           login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get file download address. """
    minio_client = await get_minio_storage()
    download_url = await minio_client.get_share_link(file_url)
    return resp_200(data={
        'url': download_url
    })


@router.post('/{evaluation_id}/process', status_code=200)
def process_evaluation(*, evaluation_id: int, background_tasks: BackgroundTasks,
                       login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Perform assessment tasks manually. """
    background_tasks.add_task(add_evaluation_task, evaluation_id=evaluation_id)
    return resp_200()
