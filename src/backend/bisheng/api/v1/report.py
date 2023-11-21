
from uuid import UUID, uuid4

from bisheng.database.base import get_session
from bisheng.database.models.report import Report, ReportRead
from bisheng.utils import minio_client
from bisheng.utils.logger import logger
from bisheng_langchain.utils.requests import Requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
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
    if 2 == status:
        # 保存回掉
        file = await Requests().aget(url=file_url)
        object_name = mino_prefix+key
        minio_client.MinioClient().upload_minio_data(object_name, file)
        db_report = Report(version_key=key, object_name=object_name)
        session.add(db_report)
        session.commit()
    return {'error': 0}


@router.post('/save_template', response_model=ReportRead)
async def save_template(data: dict, session: Session = Depends(get_session)):
    flow_id = data.get('flow_id')
    key = data.get('key')

    db_report = session.exec(select(Report).where(Report.version_key == key)).first()
    if not db_report:
        raise HTTPException(status_code=500, detail='当前文件未保存，稍后再试')
    db_report.flow_id = UUID(flow_id).hex
    session.add(db_report)
    session.commit()

    return jsonable_encoder(db_report)


@router.get('/report_temp', response_model=ReportRead)
async def get_template(*, flow_id: str, session: Session = Depends(get_session)):
    flow_id = UUID(flow_id).hex
    db_report = session.exec(select(Report).where(
        Report.flow_id == flow_id,
        Report.del_yn == 0).order_by(Report.update_time.desc())).first()
    if not db_report:
        raise HTTPException(status_code=500, detail='无模板信息')

    file_url = minio_client.MinioClient().get_share_link(db_report.object_name)
    version_key = uuid4().hex
    res = {
        'temp_url': file_url,
        'version_key': version_key,
    }

    return jsonable_encoder(res)
