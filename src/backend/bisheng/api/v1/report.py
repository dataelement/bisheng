import hashlib

import jwt
from fastapi import APIRouter, Body, Depends, Header, HTTPException
from loguru import logger
from sqlmodel import select

from bisheng.api.services.office_callback import afetch_office_document
from bisheng.api.services.report_editor_security import authorize_editor, resolve_callback_report, verify_callback
from bisheng.api.services.report_repository import ReportRepository
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.core.database import get_sync_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.report import Report
from bisheng.permission.application.business_authorization import check_business_action
from bisheng.utils import generate_uuid

# build router
router = APIRouter(prefix="/report", tags=["report"])
mino_prefix = "report/"


@router.post("/office_token")
async def get_office_token(
    payload: dict = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Sign the OnlyOffice editorConfig with JWT secret and return the token.

    Signing is only ever requested by the browser before it boots the editor --
    the document server never calls this. Without a login this was a signing
    oracle: anyone could have any payload signed with `office_jwt_secret` and
    hand the document server an editor config of their choosing.
    """
    secret = bisheng_settings.get_from_db("office_jwt_secret") or ""
    if not isinstance(secret, str) or not secret:
        raise HTTPException(503, "Document server authentication is not configured")
    config = await authorize_editor(payload, login_user)
    token = jwt.encode(config, secret, algorithm="HS256")
    return resp_200({"token": token, "config": config})


@router.post("/callback")
async def callback(data: dict, authorization: str | None = Header(default=None)):
    if not isinstance(data.get("token"), str) and not isinstance(authorization, str):
        return {"error": 1}
    secret = bisheng_settings.get_from_db("office_jwt_secret") or ""
    body = verify_callback(data, secret, authorization if isinstance(authorization, str) else None)
    if body is None:
        return {"error": 1}
    if body["status"] not in {2, 6}:
        return {"error": 0}
    key = body["key"]
    db_report = await resolve_callback_report(key)
    if db_report is None:
        return {"error": 1}
    # No default/middleware tenant is trusted for a document-server callback.
    with tenant_execution_scope(db_report.tenant_id):
        content = await afetch_office_document(body["url"])
        if content is None:
            return {"error": 1}
        # Immutable content-addressed write: a stale concurrent key cannot
        # overwrite the blob referenced by a newer report row.
        digest = hashlib.sha256(content).hexdigest()
        object_name = f"{mino_prefix}{db_report.id}/{key}/{digest}.docx"
        minio_client = await get_minio_storage()
        await minio_client.put_object(
            bucket_name=minio_client.bucket,
            object_name=object_name,
            file=content,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        if not ReportRepository.save_callback(db_report.id, key, object_name):
            logger.warning("Report callback key changed during save; row update refused")
            return {"error": 1}
    return {"error": 0}


@router.get("/report_temp")
async def get_template(*, flow_id: str, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Open an editor only for a user who can edit the owning workflow.

    The handler used to carry no login dependency, and CustomMiddleware only
    authenticates requests that bring a token, so an anonymous GET could read
    any flow's presigned report URL and mint a new ``newversion_key``.
    """
    if not await check_business_action(login_user, resource_type="workflow", resource_id=flow_id, action="edit"):
        raise UnAuthorizedError()
    with get_sync_db_session() as session:
        db_report = session.exec(
            select(Report).where(Report.flow_id == flow_id, Report.del_yn == 0).order_by(Report.update_time.desc())
        ).first()
    file_url = ""
    if not db_report:
        db_report = Report(flow_id=flow_id)
    elif db_report.object_name:
        minio_client = await get_minio_storage()
        file_url = await minio_client.get_share_link(db_report.object_name, clear_host=False)

    if not db_report.newversion_key or not db_report.object_name:
        version_key = generate_uuid()
        db_report.newversion_key = version_key
        with get_sync_db_session() as session:
            session.add(db_report)
            session.commit()
            session.refresh(db_report)
    else:
        version_key = db_report.newversion_key
    res = {
        "flow_id": flow_id,
        "temp_url": file_url,
        "original_version": db_report.version_key,
        "version_key": version_key,
    }

    return resp_200(res)
