from uuid import UUID, uuid4

from bisheng.api.v1.schemas import resp_200
from bisheng.database.base import get_session
from bisheng.database.models.report import Report
from bisheng.utils import minio_client
from bisheng.utils.logger import logger
from bisheng_langchain.utils.requests import Requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/report', tags=['report'])
mino_prefix = 'report/'


@router.post('/callback')
async def callback(data: dict, session: Session = Depends(get_session)):
    status = data.get('status')
    file_url = data.get('url')
    key = data.get('key')
    logger.debug(f'calback={data}')
    if status in {2, 6}:
        # 保存回掉
        logger.info(f'office_callback url={file_url}')
        file = Requests().get(url=file_url)
        object_name = mino_prefix + key + '.docx'
        minio_client.MinioClient().upload_minio_data(
            object_name, file._content, len(file._content),
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document')  # noqa
        # 重复保存，key 不更新
        db_report = session.exec(
            select(Report).where(or_(Report.version_key == key,
                                     Report.newversion_key == key))).first()
        if not db_report:
            logger.error(f'report_callback cannot find the flow_id flow_id={key}')
            raise HTTPException(status_code=500, detail='cannot find the flow_id')
        db_report.object_name = object_name
        db_report.version_key = key
        db_report.newversion_key = None
        session.add(db_report)
        session.commit()
    return {'error': 0}


@router.get('/report_temp')
async def get_template(*, flow_id: str, session: Session = Depends(get_session)):
    flow_id = UUID(flow_id).hex
    db_report = session.exec(
        select(Report).where(Report.flow_id == flow_id,
                             Report.del_yn == 0).order_by(Report.update_time.desc())).first()
    file_url = ''
    if not db_report:
        db_report = Report(flow_id=flow_id)
    elif db_report.object_name:
        file_url = minio_client.MinioClient().get_share_link(db_report.object_name)
    if not db_report.newversion_key or not db_report.object_name:
        version_key = uuid4().hex
        db_report.newversion_key = version_key
        session.add(db_report)
        session.commit()
    else:
        version_key = db_report.newversion_key
    res = {
        'flow_id': flow_id,
        'temp_url': file_url,
        'original_version': db_report.version_key,
        'version_key': version_key,
    }

    return resp_200(res)
